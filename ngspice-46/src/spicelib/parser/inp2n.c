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
int INPbusKicadStyle(void)
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
/* Enhancement-464: the ONE place the bit spelling is decided, in a form the
   subcircuit expander can call too -- a plain buffer, so no dstring type has to
   cross the header. Duplicating three lines instead would be exactly the
   two-readers-of-one-rule shape E-454 had to repair in this same option. */
void INPbusBitSuffix(const char *lb, int kicad, char *out, size_t n)
{
    size_t i = 0;

    for (; *lb && i + 1 < n; lb++)
        out[i++] = (kicad && (*lb == '[' || *lb == ']')) ? '_' : *lb;
    out[i] = '\0';
}

static void autobus_cat_index(DSTRINGPTR nl, const char *lb, bool kicad)
{
    char buf[64];

    INPbusBitSuffix(lb, kicad, buf, sizeof buf);
    ds_cat_str(nl, buf);
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
int INPbusPorts(IFdevice *dev, int *start, int *cnt, int maxp)
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
    int np = INPbusPorts(dev, pstart, pcnt, AUTOBUS_MAXPORT);

    if (np == numnodes && np < *dev->terms) {
      DS_CREATE(nl, 128);
      char *scan = line;
      int p;
      bool badtok = FALSE;              /* Enhancement-445 */
      bool kicad = INPbusKicadStyle();  /* Enhancement-462 */

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

/* ===========================================================================
 * PROTOTYPE (Enhancement-463 candidate): `.option autoadapt adapter=<model>`
 *
 * Inject a two-bus-port adapter between two OSDI devices that share a bus node:
 *
 *     N1 a b mymodel1                 N1 a b_f mymodel1
 *     N2 b c mymodel2      ->         N2 b_r c mymodel2
 *                                     N_a1_ b_f b_r <adapter>
 *
 * WHERE THIS RUNS, AND WHY. Between INPpas1 and INPpas2 (see spiceif.c):
 *   - pas1 has filled the model table, so a line's PORT STRUCTURE is knowable --
 *     which is what "is this token a bus node?" needs. A textual pass earlier in
 *     inpcom.c cannot answer that.
 *   - subcircuits are long since flattened, so "inside a subcircuit" needs no
 *     separate path (and no second implementation to keep in step, which is the
 *     bill Enhancement-449 paid for autobus).
 *   - INP2N has NOT run, so the rewrite is at the TOKEN level and `.option
 *     autobus` then expands all three lines. Bus handling is not extra work
 *     here; it is the consequence of picking this seam.
 *
 * Rules (all deliberate, see the enhancement discussion):
 *   - a candidate token must occur EXACTLY TWICE in the whole deck, and both
 *     occurrences must be bus-port tokens on OSDI lines of equal width;
 *   - the device whose port INDEX is higher gets `_f`. Not deck order: a SPICE
 *     deck is order-independent and must stay that way;
 *   - both occurrences on ONE device is an ERROR, not a self-loop;
 *   - everything that does not qualify is REPORTED, never silently skipped.
 */
extern struct card *insert_new_line(struct card *card, char *line, int linenum,
                                    int linenum_orig, char *lineinfo);

#define ADAPT_MAXCAND 4096

struct adapt_use {
    struct card *card;
    int tokidx;                 /* which node token on the line */
    int port;                   /* port index within the model */
    int width;                  /* bits in that port */
    char *inst;
};

struct adapt_cand {
    char *node;
    int nuse;
    struct adapt_use use[2];
    int extra;                  /* uses beyond two, or non-OSDI sightings */
};

/* Is `node` named on a `.adapt` card? Whole tokens only -- a substring test
   would make `.adapt bb` silently select `b`. A flattened node carries its
   subcircuit path (`x1.b`), so the trailing component is accepted too, letting
   one `.adapt b` cover the same local node in every instance of a subcircuit. */
static bool adapt_listed(const char *list, const char *node, bool *hit)
{
    const char *p = list;
    const char *tail = strrchr(node, '.');
    tail = tail ? tail + 1 : node;

    while (*p) {
        size_t n = 0;
        while (*p && (isspace_c(*p) || *p == ','))
            p++;
        while (p[n] && !isspace_c(p[n]) && p[n] != ',')
            n++;
        if (n) {
            if ((strlen(node) == n && strncmp(p, node, n) == 0) ||
                (strlen(tail) == n && strncmp(p, tail, n) == 0)) {
                if (hit)
                    *hit = TRUE;
                return TRUE;
            }
        }
        p += n;
    }
    return FALSE;
}

/* whole-word occurrences of `tok` among the NODE positions of instance lines */
static int adapt_count_occurrences(struct card *deck, const char *tok)
{
    struct card *c;
    size_t n = strlen(tok);
    int total = 0;

    for (c = deck; c; c = c->nextcard) {
        char *p = c->line;
        if (!p || !*p || *p == '*' || *p == '.')
            continue;
        while ((p = strstr(p, tok)) != NULL) {
            char before = (p == c->line) ? ' ' : p[-1];
            const char *after = p + n;
            if (isspace_c(before) || before == '(') {
                /* the bus itself ... */
                if (*after == '\0' || isspace_c(*after) || *after == ')') {
                    total++;
                /* ... or one of its BITS. A reference to `b[0]` is a use of the
                   bus just as much as `b` is: split the bus and that resistor is
                   left on an orphan node, silently. Both spellings count --
                   `b[0]` and, under `.option autobus=kicad`, `b_0_`. */
                } else if (*after == '[') {
                    total++;
                } else if (*after == '_' && isdigit_c(after[1])) {
                    const char *q = after + 1;
                    while (isdigit_c(*q))
                        q++;
                    if (*q == '_' && (q[1] == '\0' || isspace_c(q[1]) || q[1] == ')'))
                        total++;
                }
            }
            p += n;
        }
    }
    return total;
}

/* the model name is the last token that is not a `k=v` parameter */
static char *adapt_model_of(char *line, int *ntok)
{
    char *c = line, *tok, *last = NULL, *skip;
    int i = 0;

    skip = gettok_instance(&c);                 /* the instance name */
    tfree(skip);
    while (*c) {
        tok = gettok_instance(&c);
        if (!tok)
            break;
        if (strchr(tok, '=')) {                 /* a parameter: stop */
            tfree(tok);
            break;
        }
        tfree(last);
        last = tok;
        i++;
    }
    *ntok = i;                                  /* nodes + the model name */
    return last;
}

/* Enhancement-466: is `.option autoadapt` on, and how loud?
 *
 *   0  off        1  on, QUIET (the default)        2  on, reporting
 *
 * QUIET IS THE DEFAULT because the reporting is per NODE: a deck with many
 * shared bus nodes printed a line for every split and another for every node
 * that did not qualify, which buried the run's real output. `=debug` asks for
 * it back. Genuine ERRORS -- a missing or wrong-shaped adapter model, a name
 * collision, `autoadapt` without `autobus` -- are never silenced; they mean the
 * option cannot do what the deck asked for.
 *
 * The off-words are honoured here for the first time. `.option autoadapt=0`,
 * `=false`, `=no` and `=off` ALL TURNED THE FEATURE ON in Enhancement-463: the
 * value was never looked at, only its presence. That is the same defect
 * Enhancements 450, 451 and 454 each had to repair in a sibling option, so the
 * word list is the one they share (`e454_value_is_off` in frontend/inp.c). */
static int autoadapt_mode(void)
{
    static char warned[64] = "";
    double d;
    char s[64];

    /* Enhancement-467: ask the MOST SPECIFIC type first.
     *
     * This cascade used to lead with CP_BOOL to mean "was the bare flag
     * given?", which worked only because cp_getvar refused to coerce anything
     * else to CP_BOOL. E-467 gave it that coercion -- so that `set interp=1`
     * and its ~110 siblings stop being ignored -- and a CP_BOOL probe now
     * answers TRUE for `=debug` too, which swallowed the debug mode and the
     * unknown-value warning before either could be seen. The string is the
     * only spelling that carries a MODE, so it must be read first. */
    if (cp_getvar("autoadapt", CP_STRING, s, sizeof s))
        goto have_string;
    if (cp_getvar("autoadapt", CP_REAL, &d, 0))
        return d != 0.0 ? 1 : 0;
    if (cp_getvar("autoadapt", CP_BOOL, NULL, 0))
        return 1;                       /* the bare flag */
    return 0;                           /* not given at all */

have_string:
    if (cieq(s, "0") || cieq(s, "false") || cieq(s, "no") || cieq(s, "off"))
        return 0;
    if (cieq(s, "debug"))
        return 2;
    if (cieq(s, "true") || cieq(s, "yes") || cieq(s, "on"))
        return 1;
    if (strcmp(s, warned) != 0) {
        fprintf(stderr, "Warning: unknown autoadapt value '%s'; expected "
                        "'debug'. Proceeding quietly.\n", s);
        strncpy(warned, s, sizeof warned - 1);
        warned[sizeof warned - 1] = '\0';
    }
    return 1;
}

void
INPadapt(CKTcircuit *ckt, struct card *deck, INPtables *tab)
{
    static struct adapt_cand cand[ADAPT_MAXCAND];
    int ncand = 0, i, made = 0, adapt_width = 0;
    char amodel[128], *only = NULL;
    struct card *c;
    int verbose;

    /* ---- the option, and the two ways it can be wrong ------------------- */
    verbose = autoadapt_mode();
    if (!verbose)
        return;
    verbose = (verbose == 2);           /* 2 = report, 1 = quiet */
    if (!cp_getvar("adapter", CP_STRING, amodel, sizeof(amodel)) || !amodel[0]) {
        fprintf(stderr, "Error: .option autoadapt needs an adapter model: "
                        "`.option autoadapt adapter=<modelname>`\n");
        return;
    }
    if (!autobus_enabled()) {
        fprintf(stderr, "Error: .option autoadapt requires .option autobus; "
                        "without it a bus node is not a single token and "
                        "nothing would be adapted.\n");
        return;
    }

    /* ---- the adapter model must exist and be exactly two bus ports ------ */
    {
        INPmodel *am = NULL;
        IFdevice *adev;
        int astart[AUTOBUS_MAXPORT], acnt[AUTOBUS_MAXPORT], anp;

        txfree(INPgetMod(ckt, amodel, &am, tab));
        if (!am) {
            fprintf(stderr, "Error: autoadapt: adapter model '%s' is not "
                            "defined in this deck.\n", amodel);
            return;
        }
        adev = ft_sim->devices[am->INPmodType];
        if (!adev || !adev->registry_entry) {
            fprintf(stderr, "Error: autoadapt: adapter model '%s' is not an "
                            "OSDI device.\n", amodel);
            return;
        }
        anp = INPbusPorts(adev, astart, acnt, AUTOBUS_MAXPORT);
        if (anp != 2 || acnt[0] < 2 || acnt[1] < 2 || acnt[0] != acnt[1]) {
            fprintf(stderr, "Error: autoadapt: adapter model '%s' must have "
                    "exactly two bus ports of equal width (found %d port(s), "
                    "widths %d/%d).\n", amodel, anp,
                    anp > 0 ? acnt[0] : 0, anp > 1 ? acnt[1] : 0);
            return;
        }
        adapt_width = acnt[0];
    }

    /* ---- an optional `.adapt n1, n2, ...` restricts the node set --------- */
    for (c = deck; c; c = c->nextcard)
        if (c->line && ciprefix(".adapt", c->line)) {
            char *rest = c->line + 6;
            if (!only) {
                only = copy(rest);
            } else {
                char *j = tprintf("%s %s", only, rest);
                tfree(only);
                only = j;
            }
            *(c->line) = '*';                   /* consumed */
        }

    /* ---- collect every bus-port token on every OSDI line ---------------- */
    for (c = deck; c; c = c->nextcard) {
        char *line = c->line, *mname, *scan, *inst;
        int ntok, np, t, p;
        int pstart[AUTOBUS_MAXPORT], pcnt[AUTOBUS_MAXPORT];
        INPmodel *thismodel = NULL;
        IFdevice *dev;

        if (!line || (tolower_c(*line) != 'n'))
            continue;
        mname = adapt_model_of(line, &ntok);
        if (!mname)
            continue;
        txfree(INPgetMod(ckt, mname, &thismodel, tab));
        if (!thismodel) { tfree(mname); continue; }
        dev = ft_sim->devices[thismodel->INPmodType];
        if (!dev || !dev->registry_entry) { tfree(mname); continue; }
        np = INPbusPorts(dev, pstart, pcnt, AUTOBUS_MAXPORT);
        /* An instance OF THE ADAPTER is not a candidate: otherwise a deck that
           already carries adapters -- hand-written, or from an earlier run of
           this pass -- gets them adapted in turn, `b_f` becoming `b_f_f`/`b_f_r`
           with a second adapter between. Measured before this guard existed. */
        if (cieq(mname, amodel)) {
            /* Enhancement-467: distinguish OUR OWN injected adapters, which
             * must stay silent for idempotency, from a USER device that happens
             * to use the adapter model. The latter disabled adaptation for that
             * line with nothing said: `.option autoadapt adapter=m1` where `m1`
             * is also a device model answered the UNADAPTED number (0.7560976
             * instead of 0.7590361) and printed nothing at all. Naming a model
             * that is in use is a deck mistake, not a preference, so this is
             * reported at Error level like the other adapter-model checks and
             * is not silenced by the quiet default (Enhancement-466). */
            if (!ciprefix("n_adapt", line))
                fprintf(stderr, "Error: autoadapt: the adapter model '%s' is "
                        "also used by device %.*s in this deck; that line "
                        "cannot be adapted. Give the adapter its own .model "
                        "card.\n", amodel, (int) strcspn(line, " \t"), line);
            tfree(mname);
            continue;
        }
        tfree(mname);
        if (np <= 0 || np != ntok - 1)          /* not the one-token-per-port form */
            continue;

        scan = line;
        inst = gettok_instance(&scan);
        for (p = 0; p < np; p++) {
            char *tok = gettok_instance(&scan);
            if (!tok)
                break;
            if (pcnt[p] > 1) {                  /* a BUS port only */
                for (i = 0; i < ncand; i++)
                    if (strcmp(cand[i].node, tok) == 0)
                        break;
                if (i == ncand && ncand < ADAPT_MAXCAND) {
                    cand[ncand].node = copy(tok);
                    cand[ncand].nuse = 0;
                    cand[ncand].extra = 0;
                    ncand++;
                }
                if (i < ncand) {
                    if (cand[i].nuse < 2) {
                        cand[i].use[cand[i].nuse].card = c;
                        cand[i].use[cand[i].nuse].tokidx = p;
                        cand[i].use[cand[i].nuse].port = p;
                        cand[i].use[cand[i].nuse].width = pcnt[p];
                        cand[i].use[cand[i].nuse].inst = copy(inst);
                        cand[i].nuse++;
                    } else {
                        cand[i].extra++;
                    }
                }
            }
            tfree(tok);
        }
        tfree(inst);
        (void) t;
    }

    /* ---- qualify, then inject ------------------------------------------- */
    for (i = 0; i < ncand; i++) {
        struct adapt_cand *k = &cand[i];
        struct adapt_use *f, *rr;
        int occ;
        char *nf, *nr, *aline;

        if (only && !adapt_listed(only, k->node, NULL))
            continue;
        if (k->nuse < 2)
            continue;
        if (k->extra) {
            if (verbose)
                fprintf(stderr, "Warning: autoadapt: bus node '%s' is used by more "
                    "than two OSDI ports; not adapted.\n", k->node);
            continue;
        }
        if (k->use[0].card == k->use[1].card) {
            fprintf(stderr, "Error: autoadapt: bus node '%s' appears on both "
                    "ports of instance %s; an adapter cannot be inserted into a "
                    "device's own two ports.\n", k->node, k->use[0].inst);
            continue;
        }
        if (k->use[0].width != k->use[1].width) {
            fprintf(stderr, "Error: autoadapt: bus node '%s' is %d bits on %s "
                    "but %d bits on %s; not adapted.\n", k->node,
                    k->use[0].width, k->use[0].inst,
                    k->use[1].width, k->use[1].inst);
            continue;
        }
        if (k->use[0].width != adapt_width) {
            fprintf(stderr, "Error: autoadapt: bus node '%s' is %d bits but the "
                    "adapter model '%s' has %d-bit ports; not adapted.\n",
                    k->node, k->use[0].width, amodel, adapt_width);
            continue;
        }
        occ = adapt_count_occurrences(deck, k->node);
        if (occ != 2) {
            if (verbose)
                fprintf(stderr, "Warning: autoadapt: node '%s' occurs %d times in "
                    "the deck, not exactly twice; not adapted.\n", k->node, occ);
            continue;
        }
        /* the HIGHER port index is the forward side -- intrinsic, so that
           reordering the deck cannot change the circuit */
        if (k->use[0].port > k->use[1].port) {
            f = &k->use[0]; rr = &k->use[1];
        } else if (k->use[1].port > k->use[0].port) {
            f = &k->use[1]; rr = &k->use[0];
        } else {
            f = &k->use[0]; rr = &k->use[1];
            if (verbose)
                fprintf(stderr, "Warning: autoadapt: node '%s' sits at port %d on "
                    "both %s and %s; falling back to deck order for _f/_r.\n",
                    k->node, f->port, f->inst, rr->inst);
        }
        nf = tprintf("%s_f", k->node);
        nr = tprintf("%s_r", k->node);
        if (adapt_count_occurrences(deck, nf) ||
            adapt_count_occurrences(deck, nr)) {
            fprintf(stderr, "Error: autoadapt: cannot split '%s' -- '%s' or "
                    "'%s' already exists in the deck.\n", k->node, nf, nr);
            tfree(nf); tfree(nr);
            continue;
        }

        /* rewrite the two lines, token by token */
        {
            struct adapt_use *u;
            int w;
            for (w = 0; w < 2; w++) {
                char *scan, *tk;
                int p = 0;
                DS_CREATE(nl, 128);
                u = (w == 0) ? f : rr;
                scan = u->card->line;
                tk = gettok_instance(&scan);
                ds_cat_str(&nl, tk); tfree(tk);
                while (*scan) {
                    tk = gettok_instance(&scan);
                    if (!tk)
                        break;
                    ds_cat_char(&nl, ' ');
                    ds_cat_str(&nl, (p == u->tokidx) ? (w == 0 ? nf : nr) : tk);
                    tfree(tk);
                    p++;
                }
                tfree(u->card->line);
                u->card->line = copy(ds_get_buf(&nl));
                ds_free(&nl);
            }
        }
        aline = tprintf("n_adapt%d_ %s %s %s", ++made, nf, nr, amodel);
        insert_new_line(f->card, aline, 0, f->card->linenum_orig,
                        f->card->linesource);
        if (verbose)
            fprintf(stdout, "autoadapt: %s split -> %s (%s port %d) / %s (%s port "
                "%d), %d bits, adapter n_adapt%d_ %s\n",
                k->node, nf, f->inst, f->port, nr, rr->inst, rr->port,
                f->width, made, amodel);
        tfree(nf); tfree(nr);
    }

    /* Enhancement-467: a `.adapt` member that selected no shared bus node.
     *
     * The adapter MODEL name was validated ("is not defined in this deck", "is
     * not an OSDI device"); the NODE list beside it was not checked at all. So
     * `.adapt nosuchnode` -- one typo -- silently switched the whole feature
     * off and the deck answered the unadapted number (0.7560976 where the
     * adapted circuit gives 0.7590361), with no diagnostic of any kind. A bare
     * `.adapt` and a `.adapt 42` did the same.
     *
     * Reported per member, so `.adapt b, nosuchnode` still adapts `b` and says
     * exactly which name went nowhere. Error level, never silenced by the quiet
     * default (Enhancement-466): this is a mistake in the deck, not a
     * preference about how much to print. */
    if (only) {
        const char *q = only;
        int reported = 0;

        while (*q) {
            size_t n = 0;
            while (*q && (isspace_c(*q) || *q == ','))
                q++;
            while (q[n] && !isspace_c(q[n]) && q[n] != ',')
                n++;
            if (n) {
                char *m = copy_substring(q, q + n);
                int j, found = 0;
                for (j = 0; j < ncand; j++)
                    if (adapt_listed(m, cand[j].node, NULL)) {
                        found = 1;
                        break;
                    }
                if (!found)
                    fprintf(stderr, "Error: autoadapt: .adapt names '%s', which "
                            "is not a bus node shared by two OSDI devices here; "
                            "nothing was adapted for it.\n", m);
                tfree(m);
                reported++;
            }
            q += n;
        }
        if (!reported)
            fprintf(stderr, "Error: autoadapt: a `.adapt` card with no node "
                    "names selects nothing, so no adapter was inserted. Omit "
                    "the card to adapt every shared bus node.\n");
    }

    for (i = 0; i < ncand; i++) {
        int u;
        for (u = 0; u < cand[i].nuse; u++)
            tfree(cand[i].use[u].inst);
        tfree(cand[i].node);
    }
    tfree(only);
}
