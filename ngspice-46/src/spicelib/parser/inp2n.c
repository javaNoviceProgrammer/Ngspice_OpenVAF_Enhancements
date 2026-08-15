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

/* Enhancement-454: is `.option autobus` in force?
 *
 * The spelling decides the TYPE the options machinery publishes: a bare
 * `.option autobus` becomes a BOOL, `autobus=1` a NUMBER and `autobus=true` a
 * STRING. Asking only for CP_BOOL therefore saw the bare form and nothing else,
 * so `.option autobus=1` -- an ordinary way to write a boolean option, and not
 * reported as unknown -- silently left a bus port unbound HERE, while the
 * subcircuit path (which reads the option cards directly) honoured it.
 *
 * Every spelling is accepted, and the off-words are honoured, matching
 * `e454_value_is_off` in frontend/inp.c. The two readers are unavoidably
 * separate -- this one runs after the variable is published, that one before --
 * so they are kept to the same word list by hand; change both together. */
static bool autobus_enabled(void)
{
    double d;
    char s[64];

    if (cp_getvar("autobus", CP_BOOL, NULL, 0))
        return TRUE;
    if (cp_getvar("autobus", CP_REAL, &d, 0))
        return d != 0.0;
    if (cp_getvar("autobus", CP_STRING, s, sizeof(s)))
        return !(cieq(s, "0") || cieq(s, "false") ||
                 cieq(s, "no") || cieq(s, "off"));
    return FALSE;
}

/* Enhancement-462: which SPELLING does an expanded bit node get?
 *
 * `.option autobus` names bit k of port `a` as `a[k]`, copying the bracket text
 * from the model's own terminal name. KiCad cannot write that: its SPICE
 * exporter rewrites every `[` and `]` in a net name to `_`, so a sheet that
 * labels a wire `AA[0]` puts `/AA_0_` in the netlist -- measured, including
 * multi-digit indices (`ZA[10]` -> `/ZA_10_`). The two spellings never unify,
 * so under KiCad the bits of a bus port could not be labelled, plotted from the
 * signal list, or wired to ordinary parts.
 *
 * `.option autobus=kicad` switches the generated spelling to KiCad's, and
 * nothing else -- the indices still come from the model's terminal names, so a
 * port declared `[4:1]` still expands 1..4.
 *
 * Only this expansion is affected. The subcircuit path (`e449_expand_bus_port`
 * in frontend/subckt.c) maps a bus base onto the FORMALS the .subckt line
 * already declares rather than synthesising any name, so it has no spelling to
 * choose; the suite pins that a subcircuit still behaves identically. */
static bool autobus_kicad_style(void)
{
    static char warned[64] = "";
    char s[64];

    if (!cp_getvar("autobus", CP_STRING, s, sizeof(s)))
        return FALSE;               /* bare flag, or `=1`: a NUMBER, not a string */
    if (cieq(s, "kicad"))
        return TRUE;
    /* The on-words: the feature is on, in the default spelling. Anything else is
       a style that does not exist, and silently falling back to the default is
       how a KiCad sheet would come out floating with nothing said -- the shape
       Enhancements 447/451/455 each had to go back and fix. Say so, once per
       distinct spelling so a deck does not repeat it per device line. */
    if (!cieq(s, "true") && !cieq(s, "yes") && !cieq(s, "on") &&
        strcmp(s, warned) != 0) {
        fprintf(stderr, "Warning: unknown autobus style '%s'; expected 'kicad'. "
                        "Using the default a[k] spelling.\n", s);
        strncpy(warned, s, sizeof(warned) - 1);
        warned[sizeof(warned) - 1] = '\0';
    }
    return FALSE;
}

/* append the model's own index, in the chosen spelling: `[3]` or `_3_` */
static void autobus_cat_index(DSTRINGPTR nl, const char *lb, bool kicad)
{
    if (!kicad) {
        ds_cat_str(nl, lb);
        return;
    }
    for (; *lb; lb++)
        ds_cat_char(nl, (*lb == '[' || *lb == ']') ? '_' : *lb);
}

/* the base name of a terminal, and whether it carried an index */
static size_t autobus_base(const char *nm, bool *indexed)
{
    const char *lb = nm ? strchr(nm, '[') : NULL;
    *indexed = (lb != NULL);
    return lb ? (size_t) (lb - nm) : (nm ? strlen(nm) : 0);
}

/* Enhancement-445: whether a netlist token may be given a bit index.
 *
 * The expansion appended the model's own bracket text to whatever token the
 * user wrote, without asking whether that token could carry an index:
 *
 *   N1 0    b bd   ->  0[0] .. 0[4]      five ordinary FLOATING nodes, not ground
 *   N1 a[0] b bd   ->  a[0][0] .. a[0][4]
 *
 * Both left the device contributing nothing at all, rc=0, with no diagnostic --
 * while the identical line with the option OFF is reported by E-402's
 * under-connected warning further down. Refusing here restores that warning as
 * well as explaining the real problem.
 *
 * Ground is the case that matters in practice: tying a bus off is routine, and
 * `0[i]` can never be ground no matter how it is spelled ("gnd" has already
 * been rewritten to "0" by this point). Only BUS ports are checked -- a scalar
 * port is never indexed, so `0` or `a[0]` on one of those stays legal.
 */
static bool autobus_token_ok(const char *tok, const char *instname,
                             const char *portterm)
{
    if (strchr(tok, '[')) {
        fprintf(stderr,
                "\nWarning: instance %s: \"%s\" already carries an index, so it "
                "cannot be\n         expanded as the bus port '%s'; write the "
                "bits out individually.\n", instname, tok, portterm);
        return FALSE;
    }
    if (strcmp(tok, "0") == 0) {
        fprintf(stderr,
                "\nWarning: instance %s: ground cannot be indexed, so it cannot "
                "be expanded\n         as the bus port '%s'; tie the bits off "
                "individually (e.g. \"0 0 0\").\n", instname, portterm);
        return FALSE;
    }
    return TRUE;
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
  if (numnodes < *dev->terms && autobus_enabled()) {
    int pstart[AUTOBUS_MAXPORT], pcnt[AUTOBUS_MAXPORT];
    int np = autobus_ports(dev, pstart, pcnt, AUTOBUS_MAXPORT);

    if (np == numnodes && np < *dev->terms) {
      DS_CREATE(nl, 128);
      char *scan = line;
      int p;
      bool badtok = FALSE;              /* Enhancement-445 */
      bool kicad = autobus_kicad_style();  /* Enhancement-462 */

      for (p = 0; p < np; p++) {
        char *tok = gettok_instance(&scan);
        int k;
        if (!tok)
          break;
        /* Enhancement-445: only a BUS port indexes its token, so only those
           need the token to be indexable. */
        if (pcnt[p] > 1 &&
            !autobus_token_ok(tok, name, dev->termNames[pstart[p]])) {
          badtok = TRUE;
          tfree(tok);
          break;
        }
        for (k = 0; k < pcnt[p]; k++) {
          const char *tn = dev->termNames[pstart[p] + k];
          const char *lb = strchr(tn, '[');
          if (p || k)
            ds_cat_char(&nl, ' ');
          ds_cat_str(&nl, tok);
          if (lb)                       /* copy the model's own index */
            autobus_cat_index(&nl, lb, kicad);   /* Enhancement-462 */
        }
        tfree(tok);
      }
      if (p == np && !badtok) {         /* every port got a usable token */
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
