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
#ifdef OSDI
#include "ngspice/osdiitf.h"
#endif

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
/* Enhancement-481: `.option silentports` -- what to do with a terminal the
 * instance line left out. THREE states, because silencing the report and
 * repairing the circuit are genuinely different requests:
 *
 *   (unset)                 warn, and leave the terminal dangling. The default,
 *                           and E-402's decision: an omitted terminal looks
 *                           exactly like a typo, so it gets said out loud.
 *   silentports  (bare)     no warning; the terminal STILL DANGLES. What the
 *   silentports=dangle      option's own name promises, and nothing more, so a
 *   silentports=quiet       deck that reads `$port_connected` on purpose -- the
 *                           LRM optional-terminal idiom -- keeps working exactly
 *                           as it did, just without the message. `dangle` and
 *                           `quiet` are synonyms; `1`, `true`, `yes` and `on`
 *                           mean the bare card, so they land here too.
 *   silentports=ground      no warning, and the terminal is BOUND TO GROUND.
 *                           Asked for explicitly, because it CHANGES THE CIRCUIT.
 *
 * Why grounding has to be asked for by name: an omitted terminal is not grounded
 * by ngspice -- it gets a private node `<inst>#<term>` (`osdi/osdisetup.c` builds
 * one for every terminal past the last connected one), and that is upstream
 * behaviour, not E-402's. For the ten corpus models that pin an optional pin with
 * a POTENTIAL contribution (`Temp(t) <+ 0.0`: BSIM6, BSIM-BULK, BSIM-SOI, asmhemt,
 * mvsg_cmc, PSP-HV ...) that private node has nothing driving it, so the operating
 * point dies on `singular matrix: check node <inst>#t` -- diagnosed and accepted
 * under E-402, whose user-facing answer has always been "write `0` for it".
 * `=ground` writes the `0`, so a schematic front end that hides a thermal pin --
 * KiCad's exporter is the case that prompted this -- simulates instead of
 * aborting. But it makes the model read `$port_connected() == 1` and build the
 * branches it would otherwise skip, with the node held at 0, so it is a different
 * circuit from the one the netlist describes. A word the user typed is the right
 * gate for that; the bare card is not.
 *
 * The value test is `autobus_enabled`'s, because a plain `cp_getvar(.., CP_BOOL,
 * ..)` treats `silentports=0`, `=false`, `=no` and `=off` as the variable being
 * PRESENT and therefore true -- the defect Enhancements 450, 451, 454, 466 and
 * 467 each shipped once. E-454's other half applies too: the SPELLING decides the
 * published type, so the bare form arrives as a CP_BOOL, `=1`/`=0` as a CP_REAL
 * and every word form as a CP_STRING, and all three have to be asked.
 *
 * ASK FOR THE STRING FIRST. Since Enhancement-467 gave `cp_getvar` a CP_BOOL
 * COERCION, a CP_BOOL query answers TRUE for any value that is not one of the
 * off-words -- which is right for a two-state option and fatal for a three-state
 * one: it would swallow `ground` and every misspelling and report them all as
 * plain "on". The word has to be read before anything coerces it. CP_REAL next
 * for `=1`/`=0`, and CP_BOOL last, where it means only what it is now asked: the
 * bare card, with no value at all.
 *
 * An unrecognised word is REPORTED and then ignored, leaving the default in
 * place, which follows ngspice's own handling of a bad enumerated option value
 * (`.options method=banana` -> "unsupported integration method", run continues).
 * Falling back to the default rather than to any ON state is the safe direction:
 * a typo must not be what silently drops a diagnostic or changes a circuit.
 * Reported once per distinct bad word, since this runs per instance line and a
 * hundred devices should not produce a hundred copies. */
typedef enum {
    SP_OFF = 0,   /* warn; terminal dangles */
    SP_QUIET,     /* silent; terminal dangles -- the bare card */
    SP_GROUND     /* silent; terminal bound to node 0 -- `=ground` only */
} SPmode;

static SPmode silentports_mode(void)
{
    static char badval[64] = "";
    double d;
    char s[64];

    if (cp_getvar("silentports", CP_STRING, s, sizeof(s))) {
        if (cieq(s, "0") || cieq(s, "false") || cieq(s, "no") || cieq(s, "off"))
            return SP_OFF;
        if (cieq(s, "ground"))
            return SP_GROUND;
        if (cieq(s, "dangle") || cieq(s, "quiet") || cieq(s, "1") ||
            cieq(s, "true") || cieq(s, "yes") || cieq(s, "on"))
            return SP_QUIET;
        if (strcmp(s, badval) != 0) {           /* once per distinct bad word */
            strncpy(badval, s, sizeof(badval) - 1);
            badval[sizeof(badval) - 1] = '\0';
            fprintf(stderr,
                    "\nWarning: unsupported value '%s' for option silentports; "
                    "expected 'dangle' (or 'quiet') or 'ground'. Ignored.\n\n", s);
        }
        return SP_OFF;
    }
    if (cp_getvar("silentports", CP_REAL, &d, 0))
        return (d != 0.0) ? SP_QUIET : SP_OFF;  /* `=1` / `=0` */
    if (cp_getvar("silentports", CP_BOOL, NULL, 0))
        return SP_QUIET;                        /* bare `.option silentports` */
    return SP_OFF;
}

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
    /* Enhancement-490: `1` belongs on this list too. It is the mirror of the
       `0` in the off-word list above and `autobus_enabled` already honours it,
       but the comment on the early return -- "`=1`: a NUMBER, not a string" --
       was only true of `set autobus=1`. A deck `.option autobus=1` card
       publishes a STRING, so it reached here and a perfectly good on-word was
       reported as a style that does not exist. */
    if (!cieq(s, "1") && !cieq(s, "true") && !cieq(s, "yes") && !cieq(s, "on") &&
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

/* Enhancement-490: is this token already a single BIT rather than a bus base?
   `a[0]` in the default spelling, `a_0_` under `.option autobus=kicad`.

   Shared for the same reason INPbusBitSuffix is. subckt.c asks it of a
   `.subckt` formal; INP2N now asks it of an instance token, because a line that
   MIXES the two ways of writing a bus port is read by the answer. Two copies of
   the rule would be free to disagree about the KiCad spelling -- exactly the
   two-readers-of-one-rule shape E-454 had to repair in this same option.

   The bracket spelling is always a bit. The underscore spelling counts only
   while `autobus=kicad` is on, so an ordinary node called `foo_1_` is never
   mistaken for one in a deck that never asked for the KiCad convention. */
int INPbusTokenIndexed(const char *name, size_t len, int kicad)
{
    if (!name || len == 0)
        return 0;
    if (memchr(name, '[', len))
        return 1;
    if (kicad && name[len - 1] == '_') {
        size_t i = len - 1, digits = 0;
        while (i > 0 && isdigit_c(name[i - 1])) {
            i--;
            digits++;
        }
        if (digits && i > 1 && name[i - 1] == '_')
            return 1;
    }
    return 0;
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
    /* Enhancement-490: name the PORT, not its first terminal. The caller has
       only the terminal name to hand, so `b[0:2]` was reported as "the bus port
       'b[0]'" -- an index the user never wrote and could not act on. */
    char port[64];
    const char *lb = portterm ? strchr(portterm, '[') : NULL;
    size_t bl = lb ? (size_t) (lb - portterm)
                   : (portterm ? strlen(portterm) : 1);

    if (bl >= sizeof port)
        bl = sizeof port - 1;
    memcpy(port, portterm ? portterm : "?", bl);
    port[bl] = '\0';
    portterm = port;

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
  SPmode       sp_mode;   /* Enhancement-481: `.option silentports` */
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
    /* 2026-09-04 hunt, F1: say WHICH built-in the card resolved to, and --
     * when a Verilog-A module of that name was refused at load -- why the
     * deck ended up here, since that is the one likely explanation for an N
     * line naming a built-in model. */
    const char *lib = NULL;
    const char *refused = NULL;
    char *msg;
#ifdef OSDI
    refused = osdi_refused_module_for(dev->name, &lib);
#endif
    if (refused) {
      msg = tprintf("incorrect model type! Expected OSDI or nport device, but "
                    "model \"%s\" is ngspice's built-in %s. The Verilog-A "
                    "module \"%s\" loaded from \"%s\" was refused for "
                    "colliding with that name; rename the module to use it",
                    thismodel->INPmodName, dev->name, refused,
                    lib ? lib : "?");
    } else {
      msg = tprintf("incorrect model type! Expected OSDI or nport device, but "
                    "model \"%s\" is ngspice's built-in %s",
                    thismodel->INPmodName, dev->name);
    }
    LITERR(msg);
    tfree(msg);
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
    /* Enhancement-490: a line that MIXES the two forms -- one bus port left in
       shorthand while another port's bits are written out:

           N1 a b[0:2] busdev        for  inout [0:4] a;  inout [0:2] b;

       The branch above fires only on a token count equal to the PORT count, and
       positional binding covers a count equal to the TERMINAL count. A mixed
       line is neither, so it used to fall through both and bind POSITIONALLY
       against the flat terminal list: `a` onto a[0], then `b[0]` onto a[1],
       `b[1]` onto a[2] -- every node one or more terminals off. The only thing
       said was E-402's warning about the terminals left over at the tail, which
       names the symptom and not the cause; a user who adds the two nodes it
       asks for still has a circuit wired entirely wrong. Worse, E-445's
       autobus_token_ok exists to explain this exact mistake and sits inside the
       count check, so it could never reach the line that needed it.

       There is nothing ambiguous to resolve. Walk the ports left to right and
       let each token say which form it is in: a bare name on a bus port is
       shorthand for that port's bits, anything already carrying an index -- or
       ground, which E-445 established can never be indexed -- means this port
       was written out, so take as many tokens as it has bits. `N1 a 0 0 0 bd`
       reads correctly under the same rule.

       Accept the rewrite only when the walk consumes exactly the tokens the
       line has. Anything else means the written-out bits do not match the width
       the model declares, which no reading can repair -- refuse it there, where
       the port and both widths are still in hand to say so, rather than let the
       old silent misbinding through. */
    else if (np > 0 && np < numnodes && numnodes < *dev->terms) {
      DS_CREATE(nl, 128);
      char *scan = line;
      char *tok = NULL;
      const char *shortport = NULL;
      int p, used = 0, emitted = 0, expanded = 0, shortbits = 0;
      bool ranout = FALSE;
      bool kicad = INPbusKicadStyle();  /* Enhancement-462 */

      for (p = 0; p < np; p++) {
        int k;

        /* Never read past the node tokens: gettok_instance cannot tell where
           they end, so without this a port claiming more bits than the line has
           left would swallow the model name and report against it. */
        if (used >= numnodes) {
          ranout = TRUE;
          break;
        }
        tok = gettok_instance(&scan);
        if (!tok) {
          ranout = TRUE;
          break;
        }

        if (pcnt[p] > 1 && strcmp(tok, "0") != 0 &&
            !INPbusTokenIndexed(tok, strlen(tok), kicad)) {
          /* shorthand: this one token stands for the whole port */
          for (k = 0; k < pcnt[p]; k++) {
            const char *tn = dev->termNames[pstart[p] + k];
            const char *lb = strchr(tn, '[');
            if (emitted)
              ds_cat_char(&nl, ' ');
            ds_cat_str(&nl, tok);
            if (lb)                     /* copy the model's own index */
              autobus_cat_index(&nl, lb, kicad);
            emitted++;
          }
          if (!expanded) {              /* remember the first, to name it */
            shortport = dev->termNames[pstart[p]];
            shortbits = pcnt[p];
          }
          used++;
          expanded++;
          tfree(tok);
          tok = NULL;
        } else {
          /* written out: this port takes one token per bit */
          for (k = 0; k < pcnt[p]; k++) {
            if (k) {
              if (used >= numnodes) {
                ranout = TRUE;
                break;
              }
              tok = gettok_instance(&scan);
              if (!tok) {
                ranout = TRUE;
                break;
              }
            }
            if (emitted)
              ds_cat_char(&nl, ' ');
            ds_cat_str(&nl, tok);
            emitted++;
            used++;
            tfree(tok);
            tok = NULL;
          }
          if (ranout)
            break;
        }
      }
      tfree(tok);

      if (expanded > 0 && !ranout && used == numnodes) {
        ds_cat_char(&nl, ' ');
        ds_cat_str(&nl, scan);          /* the model name and any parameters */
        autobus_line = copy(ds_get_buf(&nl));
        line = autobus_line;
        numnodes = *dev->terms;
        ds_free(&nl);
      } else if (expanded > 0) {
        char msg[256], pbase[64];
        const char *lb = shortport ? strchr(shortport, '[') : NULL;
        size_t bl = lb ? (size_t) (lb - shortport)
                       : (shortport ? strlen(shortport) : 1);

        ds_free(&nl);
        if (bl >= sizeof pbase)
          bl = sizeof pbase - 1;
        memcpy(pbase, shortport ? shortport : "?", bl);
        pbase[bl] = '\0';

        fprintf(stderr,
                "\nError: instance %s: this line mixes a bus port written in "
                "shorthand with\n       another port's bits written out, and the "
                "two do not add up.\n"
                "       Model '%s' has %d terminals in %d ports, and the line "
                "writes %d node\n       tokens. Reading them port by port -- "
                "'%s' in shorthand for its %d bits,\n       then one token per "
                "bit for each port written out -- %s.\n"
                "       Write every bus port the same way: %d tokens (each bus "
                "in shorthand)\n       or %d (every bit written out). A range "
                "written here may also be the\n       wrong width for the port "
                "it feeds.\n"
                "       Line: %s\n\n",
                name, dev->name, *dev->terms, np, numnodes,
                pbase, shortbits,
                ranout ? "runs out before every port is fed"
                       : "uses only some of them",
                np, *dev->terms, current->line);
        snprintf(msg, sizeof msg,
                 "instance %s mixes a shorthand bus port with written-out bits; "
                 "the token count matches neither %d (all shorthand) nor %d "
                 "(all bits)", name, np, *dev->terms);
        LITERR(msg);
        return;
      } else {
        ds_free(&nl);                   /* nothing in shorthand: unchanged */
      }
    }
  }

  /* Enhancement-481: one lookup decides BOTH the message and the binding below.
   * Reading the variable twice would let a `.control` block that changes it
   * mid-parse warn about a terminal it then grounds, or the reverse. */
  sp_mode = silentports_mode();

  if (numnodes < *dev->terms && sp_mode == SP_OFF) {
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
      } else if (sp_mode == SP_GROUND) {
          /* Enhancement-481: `.option silentports` -- bind what the line left
           * out to node 0. `copy` because INPtermInsert consumes the token:
           * it either takes ownership or frees it against the existing entry,
           * and "0" always resolves to the ground node. Binding here rather
           * than leaving -1 is what makes osdisetup.c count the terminal as
           * connected, so `$port_connected()` reports 1 and no `<inst>#<term>`
           * node is created. */
          token = copy("0");
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
