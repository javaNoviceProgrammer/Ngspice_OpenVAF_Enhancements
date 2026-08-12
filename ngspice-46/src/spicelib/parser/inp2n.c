/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1988 Thomas L. Quarles
Modified: 2001 Paolo Nenzi (Cider Integration)
**********/

#include "ngspice/ngspice.h"

#include "ngspice/devdefs.h"
#include "ngspice/fteext.h"
#include "ngspice/ifsim.h"
#include "ngspice/inpdefs.h"
#include "ngspice/inpmacs.h"
#include "ngspice/dstring.h"

#include "inpxx.h"
#include <stdio.h>


/* Enhancement-444: `.option autobus` -- let a Verilog-A bus port be connected
 * by ONE node name in the netlist.
 *
 * A Verilog-A `inout [0:4] a` compiles to five OSDI terminals named `a[0]` ..
 * `a[4]`, so the netlist has always had to spell all five out:
 *
 *     N1 a[0] a[1] a[2] a[3] a[4] b busdev
 *
 * The model already knows the shape -- `dev->termNames[]` holds exactly those
 * names, and Enhancement-402 was already reading that table to report the
 * terminals a short line left unconnected. With the option set, a line that
 * supplies one token per PORT rather than one per TERMINAL is expanded using
 * the model's own bit indices:
 *
 *     N1 a b busdev      ->      N1 a[0] a[1] a[2] a[3] a[4] b busdev
 *
 * so `a[2]` elsewhere in the deck binds to the same node, nodes being unified
 * by name.
 *
 * It is opt-in because a short instance line already MEANS something: it leaves
 * trailing terminals unconnected, which is the `$port_connected` idiom BSIMSOI,
 * BSIM-CMG/IMG/BULK, BSIM6 and PSP-HV rely on. Without the option no deck
 * changes meaning at all.
 *
 * Ports are grouped from the terminal names: consecutive `base[i]` sharing a
 * base is one bus port, a bracket-free name is a scalar port. The generated
 * index is copied from the model's own name, so a port declared `[4:0]` or
 * `[1:5]` produces those indices rather than an assumed 0..n-1.
 */
#define AUTOBUS_MAXPORT 1024

/* the base name of a terminal, and whether it carried an index */
static size_t autobus_base(const char *nm, bool *indexed)
{
    const char *lb = nm ? strchr(nm, '[') : NULL;
    *indexed = (lb != NULL);
    return lb ? (size_t) (lb - nm) : (nm ? strlen(nm) : 0);
}

/* Group terminals into ports. Returns the port count, or -1 if the table is
   unusable. start[p] is the first terminal of port p, cnt[p] its width. */
static int autobus_ports(IFdevice *dev, int *start, int *cnt, int maxp)
{
    int t, np = 0;

    if (!dev->termNames || !dev->numNames || *dev->numNames < *dev->terms)
        return -1;

    for (t = 0; t < *dev->terms; t++) {
        const char *nm = dev->termNames[t];
        bool indexed;
        size_t blen;

        if (!nm)
            return -1;
        blen = autobus_base(nm, &indexed);

        if (np > 0 && indexed) {
            const char *prev = dev->termNames[start[np - 1]];
            bool pindexed;
            size_t plen = autobus_base(prev, &pindexed);
            if (pindexed && plen == blen && strncmp(prev, nm, blen) == 0) {
                cnt[np - 1]++;          /* another bit of the same port */
                continue;
            }
        }
        if (np == maxp)
            return -1;
        start[np] = t;
        cnt[np] = 1;
        np++;
    }
    return np;
}

void INP2N(CKTcircuit *ckt, INPtables *tab, struct card *current) {
  /* Mname <node> <node> <node> <node> <model> [L=<val>]
   *       [W=<val>] [AD=<val>] [AS=<val>] [PD=<val>]
   *       [PS=<val>] [NRD=<val>] [NRS=<val>] [OFF]
   *       [IC=<val>,<val>,<val>]
   */

  int          type;      /* Model type. */
  char        *line;      /* Unparsed part of the current line. */
  char        *name;      /* Device instance name. */
  int          error;     /* Temporary error code. */
  int          numnodes;  /* Flag indicating 4 or 5 (or 6 or 7) nodes. */
  GENinstance *fast;      /* Pointer to the actual instance. */
  int          waslead;   /* Funny unlabeled number was found. */
  double       leadval;   /* Value of unlabeled number. */
  INPmodel    *thismodel; /* Pointer to model description for user's model. */
  GENmodel    *mdfast;    /* Pointer to the actual model. */
  IFdevice    *dev;
  CKTnode     *node;
  char        *c, *token = NULL, *prev = NULL, *pprev = NULL, *eqp;
  int          i;
  char        *autobus_line = NULL;   /* Enhancement-444 */

  line = current->line;
  INPgetNetTok(&line, &name, 1);
  INPinsert(&name, tab);

  /* Find the last non-parameter token in the line. */

  c = line;
  for (i = 0, eqp = NULL; *c != '\0'; ++i) {
      tfree(pprev);
      pprev = prev;
      prev = token;
      token = gettok_instance(&c);
      eqp = strchr(token, '=');
      if (eqp)
          break;
  }
  if (eqp) {
      tfree(token); // A parameter or starts with '='.
      if (*c == '=') {
          /* Now prev points to a parameter pprev is the model. */

          --i;
          token = pprev;
          tfree(prev);
      } else {
          token = prev;
          tfree(pprev);
      }
  }

  /* We have single terminal Verilog-A modules */

  if (i >= 2) {
      c = INPgetMod(ckt, token, &thismodel, tab);
      /* check if using model binning -- pass in line since need 'l' and 'w' */
      if (!thismodel)
          txfree(INPgetModBin(ckt, token, &thismodel, tab, line));
      if (c && !thismodel) {
          LITERR(c);
          tfree(c);
          tfree(token);
          return;
      }
  }
  tfree(token);
  if (i < 2 || !thismodel) {
      LITERR("could not find a valid modelname");
      return;
  }
  type = thismodel->INPmodType;
  mdfast = thismodel->INPmodfast;
  dev = ft_sim->devices[type];

  /* E-242: the N dispatcher hosts OSDI devices (registry_entry set) and the
   * native n-port rational device (name "nport"); accept either. */
  if (!dev->registry_entry && strcmp(dev->name, "nport") != 0) {
    LITERR("incorrect model type! Expected OSDI or nport device");
    return;
  }

  numnodes = i - 1;
  if (numnodes > *dev->terms) {
    LITERR("too many nodes connected to instance");
    return;
  }

  /* Enhancement-402: FEWER nodes than the device has terminals is legal -- it is
   * how a netlist leaves an optional terminal (a thermal or body node) absent, and
   * the model reads that back through $port_connected. But nothing distinguished it
   * from a TYPO, and nothing was reported either way: the missing terminals were
   * bound to -1 below and the device silently simulated a different circuit.
   *
   * Say so. An omitted terminal DANGLES -- it is not grounded -- so every branch
   * touching it carries no current; spelling that out matters because the natural
   * assumption is the opposite. Warn rather than reject: rejecting would break the
   * $port_connected idiom that BSIMSOI, BSIM-CMG/IMG/BULK, BSIM6 and PSP-HV rely
   * on, and a dangling node is NOT a substitute (it reports $port_connected == 1). */
  /* Enhancement-444: with `.option autobus`, one token per PORT expands to one
     per TERMINAL using the model's own bit indices. Done before the warning
     below, so a line that expands is not also reported as under-connected. */
  if (numnodes < *dev->terms && cp_getvar("autobus", CP_BOOL, NULL, 0)) {
    int pstart[AUTOBUS_MAXPORT], pcnt[AUTOBUS_MAXPORT];
    int np = autobus_ports(dev, pstart, pcnt, AUTOBUS_MAXPORT);

    if (np == numnodes && np < *dev->terms) {
      DS_CREATE(nl, 128);
      char *scan = line;
      int p;

      for (p = 0; p < np; p++) {
        char *tok = gettok_instance(&scan);
        int k;
        if (!tok)
          break;
        for (k = 0; k < pcnt[p]; k++) {
          const char *tn = dev->termNames[pstart[p] + k];
          const char *lb = strchr(tn, '[');
          if (p || k)
            ds_cat_char(&nl, ' ');
          ds_cat_str(&nl, tok);
          if (lb)                       /* copy the model's own index */
            ds_cat_str(&nl, lb);
        }
        tfree(tok);
      }
      if (p == np) {                    /* every port got a token */
        ds_cat_char(&nl, ' ');
        ds_cat_str(&nl, scan);          /* the model name and any parameters */
        autobus_line = copy(ds_get_buf(&nl));
        line = autobus_line;
        numnodes = *dev->terms;
      }
      ds_free(&nl);
    }
  }

  if (numnodes < *dev->terms) {
    int missing;
    fprintf(stderr,
            "\nWarning: instance %s: %d of the %d terminals of model type '%s' "
            "are not connected.\n",
            name, *dev->terms - numnodes, *dev->terms, dev->name);
    for (missing = numnodes; missing < *dev->terms; missing++) {
      const char *tname = (dev->termNames && dev->numNames &&
                           missing < *dev->numNames && dev->termNames[missing])
                              ? dev->termNames[missing]
                              : "?";
      fprintf(stderr, "         terminal %d ('%s') is absent\n", missing + 1, tname);
    }
    fprintf(stderr,
            "         The model sees $port_connected() = 0 for these, and any branch\n"
            "         to them carries no current. They are NOT grounded -- connect\n"
            "         them to 0 explicitly if that is what you meant.\n"
            "         Line: %s\n\n",
            current->line);
  }

  IFC(newInstance, (ckt, mdfast, &fast, name));

  /* Rescan to process nodes. */

  for (i = 0; i < *dev->terms; i++) {
      if (i < numnodes) {
          token = gettok_instance(&line);
          INPtermInsert(ckt, &token, tab, &node); // Consumes token
          IFC(bindNode, (ckt, fast, i + 1, node));
      } else {
          GENnode(fast)[i] = -1;
      }
  }
  token = gettok_instance(&line); // Eat model name.
  tfree(token);
  PARSECALL((&line, ckt, type, fast, &leadval, &waslead, tab));
  if (waslead)
    LITERR(" error:  no unlabeled parameter permitted on osdi devices\n");
  tfree(autobus_line);                  /* Enhancement-444 */
}
