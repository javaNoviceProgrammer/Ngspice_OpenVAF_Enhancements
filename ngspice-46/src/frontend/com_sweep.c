/**********
Enhancement-146: a universal `sweep` command (and `.sweep` card).

`sweep` varies ANY circuit knob over a range and records one or more outputs into
a plottable result -- a generalization of `.dc`, which can only step a source, a
resistor or a device *instance* parameter. `sweep` additionally handles **model**
parameters and symbolic **`.param`** values, auto-detecting which kind each knob
is and applying it with the right mechanism:

  * a device / instance / source / resistor  -> `alter`     (in place)
  * a `.model`-card parameter `@<model>[<p>]` -> `altermod`  (in place)
  * a symbolic netlist `.param`               -> `alterparam` + `reset` (re-source)

(the same three mechanisms the built-in optimizer uses, Enhancement-130/144/145).

Syntax (in a .control block, or as a `.sweep` card in the deck):

  sweep <knob> <start> <stop> <step>            [-vs <knob> <spec>]... [-analysis <cmd>] [-output <expr> ...] [-overlay]
  sweep <knob> lin|dec|oct <N> <start> <stop>   [-vs <knob> <spec>]... [-analysis <cmd>] [-output <expr> ...]
  sweep <knob> list <v1> <v2> ...               [-vs <knob> <spec>]... [-analysis <cmd>] [-output <expr> ...]

Enhancement-190: one or more `-vs <knob> <spec>` add OUTER knobs. The inner
(positional) knob is the x-axis of the summary plot; the outer knobs' cartesian
product forms a curve family -- one curve per output per outer combination, named
`<output>_<outerknob>_<value>...`. A single knob reduces exactly to E-146.

For every knob value it sets the knob, runs the `-analysis` command (default `op`),
and evaluates each `-output` expression (its LAST value). With no `-output`, every
node voltage of the analysis is recorded (like `.dc`). The results go into a new
plot named `sweep<N>` (Enhancement-367 -- it was `unknown<N>` before, because no
`sweep` entry existed in the plotabs[] table in typesdef.c; the command prints the
name it actually used), with the knob values as the scale, so `plot <output>` shows the
output versus the swept knob. The per-point analysis plots are kept too (e.g.
`tran1`, `tran2`, …) for overlaying waveforms. Console chatter from the inner
analyses is suppressed via `ft_optimizing`.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/fteext.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpextern.h"
#include "ngspice/dvec.h"
#include "ngspice/sim.h"

#include "numparam/numpaif.h"
#include "ngspice/randnumb.h"
#include "ngspice/devdefs.h"      /* Enhancement-320: DEVices[]/DEVmaxnum direct set */
#include "com_sweep.h"

#define SW_ALTER   0             /* alter     -- device / instance / source      */
#define SW_MODEL   1             /* altermod  -- .model-card parameter            */
#define SW_DECK    2             /* alterparam + reset -- symbolic `.param`       */
#define SW_MAXOUT  256           /* max recorded output vectors                   */
#define SW_MAXPTS  100000        /* sanity cap on sweep points                    */
#define SW_MAXKNOB 4             /* Enhancement-190: inner + up to 3 `-vs` knobs  */


/* Run one command synchronously through the command table (like the optimizer's
 * opt_run_cmd): cp_evloop() would defer it to the outer interpreter. */
static void sw_run_cmd(const char *cmdstr)
{
    wordlist *wl = cp_lexer((char *) cmdstr);
    int i;
    if (!wl || !wl->wl_word) {
        if (wl) wl_free(wl);
        return;
    }
    for (i = 0; cp_coms[i].co_comname; i++)
        if (strcasecmp(cp_coms[i].co_comname, wl->wl_word) == 0)
            break;
    if (cp_coms[i].co_comname && cp_coms[i].co_func)
        cp_coms[i].co_func(wl->wl_next);
    else
        fprintf(cp_err, "sweep: unknown command '%s'\n", wl->wl_word);
    wl_free(wl);
}


/* parse a SPICE-style number (k / meg / u / n / p suffixes) */
static double sw_num(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}


/* evaluate an ngspice expression on the current plot, returning its LAST value
 * (magnitude if complex), or 0 on failure.
 *
 * Enhancement-431: `*ok` (may be NULL) reports whether the expression actually
 * RESOLVED, because the returned 0.0 cannot say so -- it is indistinguishable
 * from an expression that is legitimately zero. Enhancement-385 hit exactly this
 * and added the same out-param to sw_read_knob() for the knob-restore case; a
 * `-output` that never resolves has the same problem and a worse symptom, since
 * it fills a whole column with zeros and plots as a clean flat line. */
static double sw_eval_expr_ok(const char *expr, int *ok)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    double f = 0.0;
    if (ok)
        *ok = 0;
    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1) {
            if (ok)
                *ok = 1;
            if (isreal(v))
                f = v->v_realdata[v->v_length - 1];
            else
                f = hypot(v->v_compdata[v->v_length - 1].cx_real,
                          v->v_compdata[v->v_length - 1].cx_imag);
            if (!finite(f))
                f = 0.0;
        }
        if (!pn->pn_value && v)
            vec_free(v);
        free_pnode(pn);
    }
    return f;
}

/* The historic spelling: every caller that only wants the value. */
static double sw_eval_expr(const char *expr)
{
    return sw_eval_expr_ok(expr, NULL);
}

/* Enhancement-189: linear interpolation of (x[],y[]) at xq, flat outside the
 * data range; x[] is assumed monotonic increasing. Used to resample per-point
 * waveforms onto a common scale for the `-overlay` family plot. */
static double sw_interp(const double *x, const double *y, int len, double xq)
{
    int lo, hi, mid;
    if (len <= 0) return 0.0;
    if (len == 1 || xq <= x[0]) return y[0];
    if (xq >= x[len - 1]) return y[len - 1];
    lo = 0; hi = len - 1;
    while (hi - lo > 1) { mid = (lo + hi) / 2; if (x[mid] <= xq) lo = mid; else hi = mid; }
    return (x[hi] == x[lo]) ? y[lo]
           : y[lo] + (y[hi] - y[lo]) * (xq - x[lo]) / (x[hi] - x[lo]);
}

/* Enhancement-189: evaluate `expr` and copy its FULL waveform plus its scale
 * (independent variable). Returns the length and mallocs *px (scale) and *py
 * (values, magnitude if complex); both are the caller's to free. The scale is
 * taken from the evaluated vector, falling back to the current plot's scale. */
static int sw_eval_vec(const char *expr, double **px, double **py)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    int n = 0;
    *px = *py = NULL;
    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1) {
            struct dvec *sc = v->v_scale ? v->v_scale
                              : (plot_cur ? plot_cur->pl_scale : NULL);
            int i;
            n = v->v_length;
            *py = TMALLOC(double, n);
            *px = TMALLOC(double, n);
            for (i = 0; i < n; i++)
                (*py)[i] = isreal(v) ? v->v_realdata[i]
                           : hypot(v->v_compdata[i].cx_real,
                                   v->v_compdata[i].cx_imag);
            for (i = 0; i < n; i++) {
                if (sc && i < sc->v_length)
                    (*px)[i] = isreal(sc) ? sc->v_realdata[i]
                               : hypot(sc->v_compdata[i].cx_real,
                                       sc->v_compdata[i].cx_imag);
                else
                    (*px)[i] = (double) i;
            }
        }
        if (!pn->pn_value && v)
            vec_free(v);
        free_pnode(pn);
    }
    return n;
}

/* Classify a knob so we know how to set it. `@<model>[p]` whose model exists is a
 * model parameter (altermod); a bare name that is a `.param` is a deck parameter
 * (alterparam + reset); everything else is an `alter` target. */
static int sw_kind(const char *name)
{
    if (name[0] == '@') {
        char mod[128];
        const char *p = name + 1;
        int i = 0;
        while (*p && *p != '[' && i < (int) sizeof mod - 1)
            mod[i++] = *p++;
        mod[i] = '\0';
        /* Enhancement-268/-269: wildcard knobs, applied in place via `altermod`
         * (no deck re-source): `@*[param]` sets every MODEL that has `param`;
         * `@#*[param]` and `@*[[param]]` set every INSTANCE that has it. All are
         * classified as in-place model-style knobs here; `alter_set` (device.c)
         * disambiguates model vs instance by the name token. The `@*[[param]]`
         * form leaves `mod` as "*" (the scan stops at the first '['). */
        if ((mod[0] == '*' && mod[1] == '\0') ||
            (mod[0] == '#' && mod[1] == '*' && mod[2] == '\0'))
            return SW_MODEL;
        /* Enhancement-436: `@*:rmod[param]` / `@*.rmod[param]` -- one model
         * name, every instance path including none. Classified as a model knob
         * so sw_set_inplace issues `altermod`, which is where the matching
         * lives. */
        if (mod[0] == '*' && (mod[1] == ':' || mod[1] == '.') && mod[2])
            return SW_MODEL;
        /* Enhancement-435: ...and a subcircuit-local model written the way the
         * rest of the hierarchy is written. Expansion renames a `.model rmod`
         * inside instance x1 to `x1:rmod` (levels joined with '.', the model
         * attached with ':'), and Enhancement-433 taught the name funnels to
         * accept the dotted `@x1.rmod[res]` that users actually type. `sweep`
         * missed that fix because it does not go through those funnels -- it
         * calls findModel itself, right here.
         *
         * The consequence was worse than a refusal: an unrecognised name falls
         * through to SW_ALTER, `alter` then reports "no such parameter" for a
         * MODEL parameter, and the sweep runs on with a knob that never moved --
         * producing a full set of points, rc=0, and a perfectly plottable FLAT
         * curve. Same shape as the zero column Enhancement-431 removed. */
        if (*mod && ft_curckt && ft_curckt->ci_ckt &&
            (ft_sim->findModel(ft_curckt->ci_ckt, (IFuid) mod) ||
             if_find_model_hier(ft_curckt->ci_ckt, mod)))
            return SW_MODEL;
        return SW_ALTER;
    } else {
        int found = 0;
        (void) nupa_get_param(name, &found);
        return found ? SW_DECK : SW_ALTER;
    }
}


/* Enhancement-284: describe a knob for the banner. `sw_kind` returns SW_MODEL for
 * every knob applied IN PLACE via `altermod` -- which includes the INSTANCE
 * wildcards `@#*[param]` / `@*[[param]]` -- so the banner must classify from the
 * name token rather than reuse the dispatch flag, or an instance wildcard is
 * mislabelled "model param". */
static const char *sw_knobdesc(const char *name, int kind)
{
    if (kind == SW_DECK)
        return ".param";
    if (name && name[0] == '@') {
        const char *p = name + 1;
        if (p[0] == '#' && p[1] == '*')
            return "instance param, wildcard";
        if (p[0] == '*' && p[1] == '[' && p[2] == '[')
            return "instance param, wildcard";
        if (p[0] == '*' && p[1] == '[')
            return "model param, wildcard";
    }
    return kind == SW_MODEL ? "model param" : "instance/device";
}



/* Enhancement-341: refuse an `-analysis` command that would destroy the circuit.
 *
 * `sw_run_cmd` dispatches any command by name, so `-analysis reset` and
 * `-analysis remcirc` free and rebuild (or remove) the very circuit the sweep is
 * iterating over. The loop then kept using its resolved knob bindings, the old
 * `CKTcircuit *` and the old plot, and ngspice died with SIGSEGV.
 *
 * Rejecting the command BEFORE the loop starts is deliberate. Detecting the
 * damage afterwards and breaking out is not enough: the sweep's post-loop plot
 * finalisation touches the same freed state, so an abort path would have to be
 * made safe as well -- and an early attempt at that turned a previously working
 * case (`-analysis 'optimize ...'`, which resets internally but recovers) into a
 * crash. Nothing legitimate is lost: a sweep re-sources the deck itself when a
 * knob needs it, so a user `reset` in the per-point analysis has no purpose.
 *
 * `optimize` is NOT rejected -- it resets internally but re-establishes its own
 * state, and it works today.
 */
static bool sw_analysis_is_destructive(const char *analysis)
{
    static const char *const banned[] = { "reset", "remcirc", "destroy",
                                          "source", "load", "quit", NULL };
    const char *p = analysis;
    size_t n;
    int i;

    while (*p == ' ' || *p == '\t')
        p++;
    for (n = 0; p[n] && p[n] != ' ' && p[n] != '\t'; n++)
        ;
    for (i = 0; banned[i]; i++)
        if (strlen(banned[i]) == n && strncasecmp(p, banned[i], n) == 0) {
            fprintf(cp_err,
                    "sweep: -analysis '%s' would destroy the circuit the sweep is "
                    "iterating over; use a real analysis (op, dc, ac, tran, ...). "
                    "The sweep re-sources the deck itself when a knob needs it.\n",
                    banned[i]);
            return TRUE;
        }
    return FALSE;
}

/* Stage a `.param` knob (alterparam only). Enhancement-190: the `reset` that
 * commits it is issued ONCE per point after every deck knob is staged, so a
 * multi-knob cartesian point re-sources the deck a single time. */
static void sw_set_deck(const char *name, double val)
{
    char cmd[512];
    (void) snprintf(cmd, sizeof cmd, "alterparam %s=%.10g", name, val);
    sw_run_cmd(cmd);
}

/* Set an `alter` / `altermod` knob in place. These are applied AFTER any reset,
 * because reset re-sources the deck and drops in-place alters. */
static void sw_set_inplace(int kind, const char *name, double val)
{
    char cmd[512];
    (void) snprintf(cmd, sizeof cmd, "%s %s=%.10g",
                    kind == SW_MODEL ? "altermod" : "alter", name, val);
    sw_run_cmd(cmd);
}


/* Enhancement-409: classify a WILDCARD knob and extract the parameter it names.
 *
 *   `@*[p]`    -> every MODEL     that has `p`   (Enhancement-268, do_model = 1)
 *   `@#*[p]`   -> every INSTANCE  that has `p`   (Enhancement-269, do_model = 0)
 *   `@*[[p]]`  -> every INSTANCE  that has `p`   (Enhancement-269 alias)
 *
 * The name is lowercased, because that is how the device tables store a keyword
 * and how `alter_set` matches it (Enhancement-284). Returns 1 for a wildcard.
 */
static int sw_wildcard_knob(const char *name, char *param, size_t plen,
                            int *do_model, char *leaf, size_t llen)
{
    const char *p, *end;
    size_t i, n;

    if (leaf && llen)
        leaf[0] = '\0';
    if (!name || name[0] != '@' || !param || plen == 0 || !do_model)
        return 0;
    p = name + 1;
    if (p[0] == '#' && p[1] == '*' && p[2] == '[') {
        *do_model = 0;
        p += 3;
    } else if (p[0] == '*' && p[1] == '[' && p[2] == '[') {
        *do_model = 0;
        p += 3;
    } else if (p[0] == '*' && p[1] == '[') {
        *do_model = 1;
        p += 2;
    } else if (p[0] == '*' && (p[1] == ':' || p[1] == '.') &&
               p[2] && p[2] != '[') {
        /* Enhancement-437: `@*:rmod[param]` / `@*.rmod[param]`, the named-model
         * wildcard Enhancement-436 added. It belongs here for the same two
         * reasons the older spellings do, and E-436 gave it neither:
         *
         *   1. sw_read_knob() must not try to read it as a scalar. `*` is in the
         *      lexer's `specials` set, so PPparse cannot lex the name and emits
         *      the stray-']' pair documented above -- which is exactly the
         *      spurious "no such device or model name" + "PPerror: syntax error"
         *      that a `sweep @*:rmod[res]` printed while otherwise working.
         *   2. It has no single readable value, so it must be captured
         *      per target for the restore -- without that the sweep left every
         *      matched model at the last swept value.
         *
         * The leaf name is reported separately so the caller can use the
         * name-filtered capture/replay rather than the match-everything one. */
        const char *lp = p + 2;
        const char *lend = strchr(lp, '[');
        size_t ln;
        if (!lend || lend == lp || !leaf || llen == 0)
            return 0;
        ln = (size_t) (lend - lp);
        if (ln >= llen)
            return 0;
        for (i = 0; i < ln; i++)
            leaf[i] = (char) tolower((unsigned char) lp[i]);
        leaf[ln] = '\0';
        *do_model = 1;
        p = lend + 1;
        end = strchr(p, ']');
        if (!end || end == p)
            return 0;
        n = (size_t) (end - p);
        if (n >= plen)
            return 0;
        for (i = 0; i < n; i++)
            param[i] = (char) tolower((unsigned char) p[i]);
        param[n] = '\0';
        return 1;
    } else {
        return 0;
    }
    end = strchr(p, ']');
    if (!end || end == p)
        return 0;
    n = (size_t) (end - p);
    if (n >= plen)
        return 0;
    for (i = 0; i < n; i++)
        param[i] = (char) tolower((unsigned char) p[i]);
    param[n] = '\0';
    return 1;
}


/* Enhancement-385: read an `alter`/`altermod` knob's CURRENT value, reporting
 * whether the read actually succeeded.
 *
 * sw_eval_expr() cannot be used for this: it returns 0.0 on failure, which is
 * indistinguishable from a knob that is legitimately zero, and restoring a
 * spurious 0 would be worse than not restoring at all. `*ok` lets the caller
 * keep E-350's all-or-nothing rule.
 *
 * The name is LOWER-CASED first. A `@name[param]` string built in C must be,
 * or PPparse rejects it and returns NULL with no diagnostic at all -- the trap
 * Enhancement-382 documents. Knob names arrive from the command wordlist, which
 * is already folded, but this builds no assumption on that. */
static double sw_read_knob(const char *name, int *ok)
{
    struct pnode *pn;
    char buf[512];
    size_t i;
    double f = 0.0;

    *ok = 0;
    if (!name)
        return 0.0;
    /* Enhancement-409: a wildcard names MANY parameters at once, so it is not a
     * readable vector and must never reach the expression parser. Doing so only
     * produced a diagnostic that looked like a broken parameter name --
     *
     *     Error: no such device or model name
     *     PPerror: syntax error in line segment
     *        @*[wavelength_nm]
     *     near
     *           wavelength_nm]
     *
     * -- because the lexer's `specials` set contains '*', so `@*[p]` cannot lex
     * as a single token and the leftover text is reported with a stray ']'.
     * Wildcards are captured per target by if_saveparam_wildcard() instead. */
    {
        char pbuf[128], lbuf[128];
        int dm;
        if (sw_wildcard_knob(name, pbuf, sizeof pbuf, &dm, lbuf, sizeof lbuf))
            return 0.0;                  /* *ok stays 0 -- read via the backend */
    }
    (void) snprintf(buf, sizeof buf, "%s", name);
    for (i = 0; buf[i]; i++)
        buf[i] = (char) tolower((unsigned char) buf[i]);

    pn = ft_getpnames_from_string(buf, TRUE);
    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1 && isreal(v)) {
            f = v->v_realdata[v->v_length - 1];
            if (finite(f))
                *ok = 1;
            else
                f = 0.0;
        }
        if (!pn->pn_value && v)
            vec_free(v);
        free_pnode(pn);
    }
    return f;
}


/* ============= Enhancement-320 / -321: .param FAST-SWEEP ======================
 * A swept `.param` normally forces a full `reset` (deck re-source + subckt
 * re-expand + CKTsetup + matrix reorder) at every point, because numparam folds
 * the param into device value literals at parse time and leaves no live binding.
 * When the swept param feeds ONLY addressable device/model VALUES, we instead
 * re-evaluate each dependent value against the retained numparam table and push
 * it into the live circuit with a direct in-place set -- no reset.
 *
 * E-321 extends this from top-level to SUBCIRCUIT-INTERNAL devices. The key is
 * that a flattened instance card (`r.x1.r1 in out 1e3`) carries `linenum` back
 * to its subckt-DEFINITION body line, whose ORIGINAL text (`r1 a b {rval}`, with
 * the expression intact) numparam retains in dicoS->dynrefptr. So a walk of the
 * flattened deck (ci_deck) + nupa_get_dynref(card->linenum) recovers, for every
 * instance (top-level and nested), its value expression paired with its full
 * hierarchical name -- no hierarchical-name reconstruction needed.
 *
 * Because a subckt can locally shadow or derive from a swept global, each bind
 * carries `flat_value` (the value numparam already baked into the flattened
 * card at nominal params). At arm time the captured expression is re-evaluated
 * against the GLOBAL dico and MUST reproduce that baked value; any mismatch
 * (a local shadow, a formal-param pass-through) DISARMS the whole path. Together
 * with the structural/derived/subckt-call disarms this keeps the guarantee that
 * a sweep can only get faster, never change its result. */
struct sw_fp_bind {
    char *cmd;                 /* textual fallback: "alter Rs0 = " / "altermod m vth0 = " */
    char *name;                /* device/model instance name (full flattened name) */
    char *param;               /* instance param keyword, or NULL for the principal */
    int   mod;                 /* 1 = .model param (setModelParm), 0 = instance      */
    char *expr;                /* e.g. "rval*2" (brace contents), re-evaluated/point */
    double flat_value;         /* value numparam baked into the flattened card       */
    int   flat_ok;             /* 1 = flat_value parsed, self-check applies           */
    /* Resolved once so the point loop can write the slot directly, bypassing the
     * per-point lex + @name resolution the textual alter/altermod path repeats.
     * `inst` is used for instance binds, `modp` for model binds (Enhancement-344);
     * exactly one is non-NULL, selected by `mod`. */
    GENinstance *inst;
    GENmodel *modp;
    int   devtype;
    int   parmid;
    int   rok;                 /* 1 = resolved, use direct set; 0 = textual cmd */
    /* Enhancement-346: this expression draws from the RNG (agauss/gauss/unif/
     * aunif/limit/mvnorm), so it is NOT constant between points. Such a bind is
     * captured even when the swept name is absent, is never evaluated at arm
     * time (that would consume a draw and fail the nominal self-check), is
     * never served from the by-expression-text cache (two devices with the same
     * text get INDEPENDENT draws, as re-sourcing gives them), and is evaluated
     * in DECK ORDER so the RNG stream is consumed exactly as a reset would. */
    int   rnd;
    int   seq;                 /* capture index = deck order */
    struct sw_fp_bind *next;
};
static struct sw_fp_bind *sw_fp_list = NULL;
static int sw_fp_armed = 0;
static int sw_fp_nseq = 0;     /* running capture counter (deck order) */
static int sw_fp_nrnd = 0;     /* how many captured binds draw from the RNG */

static int sw_ident_ch(int c)
{
    return isalnum(c) || c == '_';
}

/* Does this brace expression call a numparam function that consumes a random
 * draw? These are the only sources of per-evaluation variation in a value
 * expression; everything else is a pure function of the dico. */
static int sw_expr_is_random(const char *e)
{
    static const char *const rf[] = { "agauss", "gauss", "unif", "aunif",
                                      "limit", "mvnorm", NULL };
    const char *p;
    int i;

    if (!e)
        return 0;
    for (i = 0; rf[i]; i++) {
        size_t n = strlen(rf[i]);
        for (p = e; (p = strstr(p, rf[i])) != NULL; p += n) {
            const char *q = p + n;
            if (p > e && sw_ident_ch((unsigned char) p[-1]))
                continue;                       /* part of a longer identifier */
            while (*q && isspace((unsigned char) *q))
                q++;
            if (*q == '(')                      /* a call, not a bare word */
                return 1;
        }
    }
    return 0;
}

/* range form of sw_expr_is_random for un-terminated brace contents */
static int sw_expr_is_random_range(const char *b, const char *e)
{
    char *tmp = copy_substring(b, e);
    int r = sw_expr_is_random(tmp);
    tfree(tmp);
    return r;
}


/* whole-identifier-token search: TRUE iff `tok` occurs in [s,e) on ident
 * boundaries (so "rval" does not match inside "rvalue" or "xrval"). */
static int sw_has_token(const char *s, const char *e, const char *tok)
{
    size_t n = strlen(tok);
    const char *p;
    for (p = s; p + n <= e; p++) {
        if (strncmp(p, tok, n) != 0)
            continue;
        if (p > s && sw_ident_ch((unsigned char) p[-1]))
            continue;
        if (p + n < e && sw_ident_ch((unsigned char) p[n]))
            continue;
        return 1;
    }
    return 0;
}

/* does any swept name occur as a token in [s,e)? */
static int sw_line_has_swept(const char *s, const char *e,
                             char *const *sw, int nsw)
{
    int k;
    for (k = 0; k < nsw; k++)
        if (sw_has_token(s, e, sw[k]))
            return 1;
    return 0;
}

static void sw_fp_add(const char *cmd, const char *name, const char *param,
                      int mod, const char *beg_expr, const char *end_expr,
                      double flat_value, int flat_ok)
{
    struct sw_fp_bind *b = TMALLOC(struct sw_fp_bind, 1);
    b->cmd = copy(cmd);
    b->name = copy(name);
    b->param = param ? copy(param) : NULL;
    b->mod = mod;
    b->expr = copy_substring(beg_expr, end_expr);
    b->flat_value = flat_value;
    b->flat_ok = flat_ok;
    b->rnd = sw_expr_is_random(b->expr);
    b->seq = sw_fp_nseq++;
    if (b->rnd)
        sw_fp_nrnd++;
    b->inst = NULL;
    b->modp = NULL;
    b->devtype = -1;
    b->parmid = 0;
    b->rok = 0;
    b->next = sw_fp_list;
    sw_fp_list = b;
}

/* Extract the numeric value numparam baked into a flattened card line at the
 * slot named by `param` (NULL = the positional principal, i.e. the last token).
 * Captured device values are always numparam-formatted (%e), so strtod is
 * exact. Returns 1 and sets *out on success. */
static int sw_flat_value(const char *flat_line, const char *param, double *out)
{
    const char *p = flat_line;
    char *endp;
    double v;

    if (!flat_line)
        return 0;

    if (param) {                          /* named: find `param` <ws>? = <value> */
        size_t n = strlen(param);
        for (; *p; p++) {
            if (strncasecmp(p, param, n) != 0)
                continue;
            if (p > flat_line && sw_ident_ch((unsigned char) p[-1]))
                continue;
            {
                const char *q = p + n;
                while (*q && isspace((unsigned char) *q)) q++;
                if (*q != '=')
                    continue;
                q++;
                while (*q && isspace((unsigned char) *q)) q++;
                v = strtod(q, &endp);
                if (endp == q)
                    return 0;
                *out = v;
                return 1;
            }
        }
        return 0;
    }

    /* principal: the last whitespace-delimited token */
    {
        const char *last = NULL, *q = flat_line;
        while (*q) {
            while (*q && isspace((unsigned char) *q)) q++;
            if (!*q || *q == ';' || *q == '$' || *q == '*')
                break;
            last = q;
            while (*q && !isspace((unsigned char) *q)) q++;
        }
        if (!last)
            return 0;
        v = strtod(last, &endp);
        if (endp == last)
            return 0;
        *out = v;
        return 1;
    }
}

void sw_fp_free(void)
{
    struct sw_fp_bind *b = sw_fp_list, *nx;
    while (b) {
        nx = b->next;
        tfree(b->cmd);
        tfree(b->name);
        tfree(b->param);
        tfree(b->expr);
        tfree(b);
        b = nx;
    }
    sw_fp_list = NULL;
    sw_fp_armed = 0;
    sw_fp_nseq = 0;
    sw_fp_nrnd = 0;
}

/* Find a settable real parameter by keyword in a parameter table, returning its
 * id. `param` NULL selects the positional principal (instance tables only, since
 * a .model line has no principal slot). Returns 0 on no match, 1 on success. */
static int sw_fp_find_parm(const IFparm *tab, int ntab, const char *param,
                           int *parmid)
{
    int k;

    for (k = 0; tab && k < ntab; k++) {
        const IFparm *prm = tab + k;
        if (!(prm->dataType & IF_SET))
            continue;
        if ((prm->dataType & IF_VARTYPES) != IF_REAL)
            continue;
        if (param) {
            if (!cieq(prm->keyword, param))
                continue;
        } else if (!(prm->dataType & IF_PRINCIPAL)) {
            continue;
        }
        *parmid = prm->id;
        return 1;
    }
    return 0;
}

/* Resolve a bind to (instance-or-model, type, param-id) once, so the point loop
 * can set it directly. rok stays 0 on any failure -> that bind falls back to its
 * textual alter/altermod cmd, which is always correct, just slower. */
static void sw_fp_resolve(CKTcircuit *ckt, struct sw_fp_bind *b)
{
    int type;
    GENmodel *m;
    GENinstance *inst;

    b->rok = 0;
    if (!ckt)
        return;

    if (b->mod) {
        /* Enhancement-344: model binds take ft_sim->setModelParm directly.
         * A .model line only ever carries `key={expr}` slots, so b->param is
         * always set here; a NULL would mean a principal, which models lack. */
        if (!b->param)
            return;
        for (type = 0; type < DEVmaxnum; type++) {
            if (!DEVices[type])
                continue;
            for (m = ckt->CKThead[type]; m; m = m->GENnextModel)
                if (m->GENmodName && cieq(m->GENmodName, b->name)) {
                    IFdevice *dev = &DEVices[type]->DEVpublic;
                    if (sw_fp_find_parm(dev->modelParms,
                                        dev->numModelParms ? *dev->numModelParms : 0,
                                        b->param, &b->parmid)) {
                        b->modp = m;
                        b->devtype = type;
                        b->rok = 1;
                    }
                    return;             /* model found; settable or not, done */
                }
        }
        return;
    }

    /* Enhancement-410: the EXACT name first, then the hierarchical spelling
       written without the device-type letter subcircuit flattening prepends
       (`x1.r1` -> `r.x1.r1`), so a swept knob accepts the same name the
       accessor does. */
    {
        char alt[512];
        int pass;

        for (pass = 0; pass < 2; pass++) {
            const char *want = b->name;

            if (pass == 1) {
                const char *local = b->name ? strrchr(b->name, '.') : NULL;
                if (!local || !local[1] || local[1] == 'x' || local[1] == 'X')
                    break;
                if (strlen(b->name) + 3 > sizeof alt)
                    break;
                (void) snprintf(alt, sizeof alt, "%c.%s", local[1], b->name);
                want = alt;
            }

            for (type = 0; type < DEVmaxnum; type++) {
                if (!DEVices[type])
                    continue;
                for (m = ckt->CKThead[type]; m; m = m->GENnextModel)
                    for (inst = m->GENinstances; inst; inst = inst->GENnextInstance)
                        if (inst->GENname && cieq(inst->GENname, want)) {
                            IFdevice *dev = &DEVices[type]->DEVpublic;
                            if (sw_fp_find_parm(dev->instanceParms,
                                                dev->numInstanceParms
                                                    ? *dev->numInstanceParms : 0,
                                                b->param, &b->parmid)) {
                                b->inst = inst;
                                b->devtype = type;
                                b->rok = 1;
                            }
                            return;         /* instance found, settable or not */
                        }
            }
        }
    }
}

/* Classify+capture one top-level ELEMENT or .model line (`line`); `name` is the
 * already-extracted device/model instance name, `mod` selects altermod. Returns
 * 0 if the line makes the fast path INELIGIBLE, 1 if fully handled. Every swept
 * token must sit inside a value brace that is either the last token (principal)
 * or of the form `key={expr}`; anything else (node/name/mid position) disarms. */
static int sw_fp_scan_valueline(const char *line, const char *name, int mod,
                                char *const *sw, int nsw, const char *flat_line)
{
    const char *p = line;
    const char *le = line + strlen(line);

    while (*p) {
        if (*p == '{') {
            const char *bexp = p + 1;
            const char *q = bexp;
            int depth = 1;
            while (*q && depth) {           /* find matching close brace */
                if (*q == '{') depth++;
                else if (*q == '}') depth--;
                if (depth) q++;
            }
            if (depth) return 0;            /* unbalanced -> bail (ineligible) */
            /* q points at '}'; [bexp,q) is the expression */
            /* Enhancement-346: a RANDOM expression is captured even when the
             * swept name is absent -- it is not constant between points, and
             * leaving it alone is what made the fast path disagree with reset. */
            if (sw_line_has_swept(bexp, q, sw, nsw) ||
                sw_expr_is_random_range(bexp, q)) {
                const char *k = p;          /* look left of '{' for '=' */
                char cmd[600];
                while (k > line && isspace((unsigned char) k[-1])) k--;
                if (k > line && k[-1] == '=') {
                    /* key={expr} : named param */
                    const char *ke = k - 1;             /* at '=' */
                    const char *kend, *kbeg;
                    while (ke > line && isspace((unsigned char) ke[-1])) ke--;
                    kend = ke;                           /* one past key end? */
                    /* ke now just past '='; step to end of key */
                    kend = k - 1;
                    while (kend > line && isspace((unsigned char) kend[-1])) kend--;
                    kbeg = kend;
                    while (kbeg > line && sw_ident_ch((unsigned char) kbeg[-1])) kbeg--;
                    if (kbeg == kend) return 0;          /* no key ident */
                    {
                        char key[256];
                        double fv = 0.0;
                        int fok;
                        (void) snprintf(key, sizeof key, "%.*s",
                                        (int) (kend - kbeg), kbeg);
                        (void) snprintf(cmd, sizeof cmd, "%s %s %s = ",
                                        mod ? "altermod" : "alter", name, key);
                        fok = sw_flat_value(flat_line, key, &fv);
                        sw_fp_add(cmd, name, key, mod, bexp, q, fv, fok);
                    }
                } else {
                    /* positional: must be the last token on the line */
                    const char *r = q + 1;
                    double fv = 0.0;
                    int fok;
                    while (*r && isspace((unsigned char) *r)) r++;
                    if (*r != '\0' && *r != ';' && *r != '$' && *r != '*')
                        return 0;                        /* not last -> ineligible */
                    if (mod) return 0;                   /* .model has no principal */
                    (void) snprintf(cmd, sizeof cmd, "alter %s = ", name);
                    fok = sw_flat_value(flat_line, NULL, &fv);
                    sw_fp_add(cmd, name, NULL, 0, bexp, q, fv, fok);
                }
            }
            p = q + 1;
            continue;
        }
        /* a swept token OUTSIDE any brace (node/name/type position) disarms */
        if (sw_ident_ch((unsigned char) *p) &&
            (p == line || !sw_ident_ch((unsigned char) p[-1]))) {
            const char *w = p;
            while (*p && sw_ident_ch((unsigned char) *p)) p++;
            if (sw_line_has_swept(w, p, sw, nsw))
                return 0;
            continue;
        }
        p++;
    }
    (void) le;
    return 1;
}

/* qsort comparator: group bindings by identical expression text. */
static int sw_fp_cmp_expr(const void *a, const void *b)
{
    const struct sw_fp_bind *ba = *(struct sw_fp_bind *const *) a;
    const struct sw_fp_bind *bb = *(struct sw_fp_bind *const *) b;
    /* Enhancement-346: RANDOM binds sort first, in DECK ORDER. Re-sourcing
     * evaluates brace expressions in deck order, and only the random ones
     * consume the RNG, so evaluating exactly those in that order reproduces the
     * stream a reset would have produced. Deterministic binds follow, grouped
     * by expression text so each distinct one is evaluated once per point. */
    if (ba->rnd != bb->rnd)
        return bb->rnd - ba->rnd;
    if (ba->rnd)
        return ba->seq - bb->seq;
    return strcmp(ba->expr, bb->expr);
}

/* Build the fast-path binding list from the ORIGINAL (pre-expansion) deck for
 * the given swept `.param` names. Returns 1 and sets sw_fp_armed if every swept
 * occurrence is an addressable top-level device/model value; otherwise frees any
 * partial captures and returns 0 (caller uses the reset path). */
int sw_fp_build(char *const *sw, int nsw)
{
    struct card *deck, *c;
    int subckt_depth = 0, control_depth = 0;

    sw_fp_free();
    /* Enhancement-346: nsw == 0 is legitimate -- Monte Carlo has no swept knob,
     * only random value expressions to re-draw. Everything below already keys
     * off `has`/`sw_line_has_swept`, which is simply false everywhere when
     * nsw == 0, so pass 1 reduces to the random-in-a-structural-slot check. */
    if (nsw < 0 || !ft_curckt)
        return 0;
    deck = ft_curckt->ci_origdeck;
    if (!deck)
        return 0;

    /* ---- Pass 1: DISARM on any use of a swept param the fast path cannot
     * represent, scanning the ORIGINAL deck including subckt bodies. Device
     * VALUES (top-level and subckt-internal) are captured in pass 2; here we
     * only reject structural / derived / shadowing / subckt-passing uses. ---- */
    for (c = deck; c; c = c->nextcard) {
        const char *line = c->line, *p, *e;
        int is_subckt, is_ends, has;
        if (!line)
            continue;
        p = line;
        while (*p && isspace((unsigned char) *p)) p++;
        if (*p == '\0' || *p == '*')
            continue;                                   /* blank / comment */
        e = p + strlen(p);

        if (strncasecmp(p, ".control", 8) == 0) { control_depth++; continue; }
        if (strncasecmp(p, ".endc", 5) == 0) {
            if (control_depth > 0) control_depth--;
            continue;
        }
        if (control_depth > 0)
            continue;

        is_subckt = (strncasecmp(p, ".subckt", 7) == 0);
        is_ends = (strncasecmp(p, ".ends", 5) == 0 ||
                   strncasecmp(p, ".eom", 4) == 0);
        has = sw_line_has_swept(p, e, sw, nsw);
        /* Enhancement-346: a random draw is a varying value too, so a line that
         * calls one gets the same structural scrutiny as one naming a swept
         * param. `.param` is exempt: numparam inlines those into the device
         * lines, where pass 2 captures them. */
        if (!has && strncasecmp(p, ".param", 6) != 0 &&
            sw_expr_is_random_range(p, e))
            has = 1;

        if (is_subckt) {
            if (has) goto disarm;   /* swept param in a subckt header default */
            subckt_depth++;
            continue;
        }
        if (is_ends) { if (subckt_depth > 0) subckt_depth--; continue; }
        if (!has)
            continue;               /* line ignores every swept param */

        if (*p == '.') {
            if (strncasecmp(p, ".model", 6) == 0) {
                /* value params captured in pass 2 (flattened deck) -- allow */
            } else if (strncasecmp(p, ".param", 6) == 0) {
                /* per assignment: a swept LHS inside a subckt is a local shadow
                 * (disarm); a non-swept LHS whose RHS references a swept param is
                 * a derived param (disarm). A top-level swept LHS is the param's
                 * own definition (fine). */
                const char *q = p + 6;
                while (*q) {
                    const char *nb2, *ne2, *rb, *re;
                    int lhs_swept = 0, k;
                    while (*q && (isspace((unsigned char) *q) || *q == ',')) q++;
                    if (!*q) break;
                    nb2 = q;
                    while (*q && sw_ident_ch((unsigned char) *q)) q++;
                    ne2 = q;
                    while (*q && isspace((unsigned char) *q)) q++;
                    if (*q != '=') { q++; continue; }
                    q++;
                    while (*q && isspace((unsigned char) *q)) q++;
                    rb = q;
                    while (*q && *q != ',' && !isspace((unsigned char) *q)) q++;
                    re = q;
                    for (k = 0; k < nsw; k++)
                        if ((size_t)(ne2 - nb2) == strlen(sw[k]) &&
                            strncmp(nb2, sw[k], (size_t)(ne2 - nb2)) == 0)
                            lhs_swept = 1;
                    if (lhs_swept) {
                        if (subckt_depth > 0) goto disarm;   /* local shadow */
                    } else if (sw_line_has_swept(rb, re, sw, nsw)) {
                        goto disarm;                         /* derived-from-swept */
                    }
                }
            } else {
                goto disarm;        /* structural dot-card (.if/.temp/.tran/...) */
            }
        } else if (*p == 'x' || *p == 'X') {
            goto disarm;            /* subckt call passing a swept param */
        }
        /* other element lines: the swept param is a device value or a structural
         * device use -- both are decided in pass 2 from the flattened card. */
    }

    /* ---- Pass 2: CAPTURE device/model values from the FLATTENED deck. Each
     * card's original template text (with the {expr} intact) is recovered via
     * nupa_get_dynref(card->linenum); the card's first token is the full
     * (possibly hierarchical) instance name -- so subckt-internal instances are
     * addressed exactly like top-level ones. ---- */
    nupa_set_dicoslist(ft_curckt->ci_dicos);
    for (c = ft_curckt->ci_deck; c; c = c->nextcard) {
        const char *fl = c->line, *tmpl, *tp;
        char nm[256];
        if (!fl)
            continue;
        tp = fl;
        while (*tp && isspace((unsigned char) *tp)) tp++;
        if (*tp == '\0' || *tp == '*')
            continue;

        tmpl = nupa_get_dynref(c->linenum);
        if (!tmpl)
            continue;
        /* Enhancement-346: also let through a line whose value expression DRAWS
         * from the RNG even though no swept name appears in it. numparam inlines
         * a `.param`'s expression into the device line during preprocessing, so
         * `.param rv = agauss(...)` + `R2 a b {rv}` arrives here as
         * `r2 a b {(agauss(...))}` -- and skipping it is exactly what left such
         * a value frozen on the fast path while a reset re-drew it. */
        if (!sw_line_has_swept(tmpl, tmpl + strlen(tmpl), sw, nsw) &&
            !sw_expr_is_random(tmpl))
            continue;

        if (*tp == '.') {
            if (strncasecmp(tp, ".model", 6) == 0) {
                const char *np = tp + 6, *nb, *ne;
                while (*np && isspace((unsigned char) *np)) np++;
                nb = np;
                while (*np && !isspace((unsigned char) *np) && *np != '(') np++;
                ne = np;
                if (ne == nb) goto disarm;
                (void) snprintf(nm, sizeof nm, "%.*s", (int) (ne - nb), nb);
                if (!sw_fp_scan_valueline(tmpl, nm, 1, sw, nsw, fl))
                    goto disarm;
            }
            /* other flattened dot-cards were classified in pass 1 */
        } else {
            const char *nb = tp, *ne = tp;
            while (*ne && !isspace((unsigned char) *ne)) ne++;
            (void) snprintf(nm, sizeof nm, "%.*s", (int) (ne - nb), nb);
            if (!sw_fp_scan_valueline(tmpl, nm, 0, sw, nsw, fl))
                goto disarm;
        }
    }

    if (!sw_fp_list)                                    /* swept feeds nothing */
        return 0;

    /* ---- Pass 3: SELF-CHECK. Re-evaluate each captured expression against the
     * GLOBAL dico at the current (nominal) param values; it MUST reproduce the
     * value numparam baked into the flattened card. A mismatch means the value
     * depends on a subckt-local/shadowed symbol we would mis-drive globally, so
     * disarm. An unparsable baked value is treated the same (conservative). ---- */
    {
        struct sw_fp_bind *b;
        for (b = sw_fp_list; b; b = b->next) {
            int ok = 0;
            double v;
            /* Enhancement-346: a random expression cannot be self-checked --
             * re-evaluating it draws a NEW value, so it could never reproduce
             * the baked one, and the draw would perturb the RNG stream that
             * must match a re-source. Its correctness rests on the structural
             * disarms instead. */
            if (b->rnd)
                continue;
            if (!b->flat_ok)
                goto disarm;
            v = nupa_eval_expr(b->expr, &ok);
            if (!ok)
                goto disarm;
            if (fabs(v - b->flat_value) > 1e-6 * (fabs(b->flat_value) + 1e-30))
                goto disarm;
        }
    }

    /* resolve binds once for the fast direct-set path (instances and, since
     * Enhancement-344, models); anything unresolved keeps its textual command */
    {
        struct sw_fp_bind *b;
        for (b = sw_fp_list; b; b = b->next)
            sw_fp_resolve(ft_curckt->ci_ckt, b);
    }

    /* group identical expressions so the point loop evaluates each UNIQUE
     * expression only once -- a swept param usually feeds many identically
     * valued devices (every R = {rval}). Order among binds does not matter
     * (independent instance slots), so sorting by expr text is safe. */
    {
        int n = 0, i;
        struct sw_fp_bind *b, **arr;
        for (b = sw_fp_list; b; b = b->next) n++;
        if (n > 1) {
            arr = TMALLOC(struct sw_fp_bind *, n);
            for (b = sw_fp_list, i = 0; b; b = b->next) arr[i++] = b;
            qsort(arr, (size_t) n, sizeof(*arr), sw_fp_cmp_expr);
            for (i = 0; i < n - 1; i++) arr[i]->next = arr[i + 1];
            arr[n - 1]->next = NULL;
            sw_fp_list = arr[0];
            tfree(arr);
        }
    }
    sw_fp_armed = 1;
    return 1;

disarm:
    sw_fp_free();
    return 0;
}

/* Apply one sweep point via the fast path: override the swept params in the
 * numparam dico, refresh the derived-param closure, then re-evaluate and push
 * every captured device/model value with alter/altermod. No reset. */
void sw_fp_apply(char *const *sw, const double *vals, int nsw)
{
    struct sw_fp_bind *b;
    CKTcircuit *ckt = ft_curckt ? ft_curckt->ci_ckt : NULL;
    char *touched = NULL;
    int j, type, any_direct = 0;

    if (ft_curckt)
        nupa_set_dicoslist(ft_curckt->ci_dicos);

    /* Enhancement-346: a deck re-copy signals one Monte Carlo sample boundary
     * (nupa_signal(NUPADECKCOPY) -> mc_sample_advance()), which rewinds the
     * per-sample dimension counter and steps the Latin-Hypercube sampler to its
     * next stratified point. Skipping the re-source skips that signal, so the
     * stratified draws all came from dimension 0 of one sample -- which is
     * exactly why `-lhs` disagreed with the reset path while plain random draws
     * matched. Raise the same boundary here. */
    mc_sample_advance();

    for (j = 0; j < nsw; j++)
        nupa_add_param((char *) sw[j], vals[j]);
    nupa_recompute_params(sw, nsw);      /* refresh derived-param closure */

    if (ckt && DEVmaxnum > 0)
        touched = TMALLOC(char, DEVmaxnum);
    if (touched)
        for (type = 0; type < DEVmaxnum; type++)
            touched[type] = 0;

    const char *last_expr = NULL;        /* eval cache: binds are expr-sorted */
    double last_v = 0.0;
    for (b = sw_fp_list; b; b = b->next) {
        double v;
        if (!b->rnd && last_expr && strcmp(b->expr, last_expr) == 0) {
            v = last_v;                  /* same expression as previous bind */
        } else if (b->rnd) {
            /* Enhancement-346: never cached -- two devices carrying the same
             * random text must get INDEPENDENT draws, exactly as re-sourcing
             * gives them (verified: two `{agauss(1000,300,3)}` resistors come
             * out at 1113.1 and 1099.5, not equal). */
            int ok = 0;
            v = nupa_eval_expr(b->expr, &ok);
            if (!ok) { last_expr = NULL; continue; }
            last_expr = NULL;
        } else {
            int ok = 0;
            v = nupa_eval_expr(b->expr, &ok);
            if (!ok) { last_expr = NULL; continue; }
            last_expr = b->expr;
            last_v = v;
        }
        if (b->rok && touched && ckt) {  /* direct slot write, no lex/resolve */
            IFvalue val;
            val.rValue = v;
            if (b->mod)                  /* Enhancement-344: model tier */
                ft_sim->setModelParm(ckt, b->modp, b->parmid, &val, NULL);
            else
                ft_sim->setInstanceParm(ckt, b->inst, b->parmid, &val, NULL);
            touched[b->devtype] = 1;
            any_direct = 1;
        } else {                         /* textual fallback (unresolvable binds) */
            char cmd[700];
            (void) snprintf(cmd, sizeof cmd, "%s%.17g", b->cmd, v);
            sw_run_cmd(cmd);
        }
    }

    /* refresh each touched device type's derived state once (mirrors the
     * .dc @inst[param] path, DCTsetInstParam): O(devices) per type, not per
     * instance. RES recomputes its conductance inside DEVparam already, but
     * OSDI and other devices update derived state only in DEVtemperature. */
    if (any_direct && touched && ckt)
        for (type = 0; type < DEVmaxnum; type++)
            if (touched[type] && DEVices[type] && DEVices[type]->DEVtemperature)
                DEVices[type]->DEVtemperature(ckt->CKThead[type], ckt);
    tfree(touched);
}


/* a valid nutmeg vector name from the knob string (non-alnum -> '_') */
static char *sw_scalename(const char *knob)
{
    char *s = copy(knob), *p;
    for (p = s; *p; p++)
        if (!isalnum((unsigned char) *p) && *p != '_')
            *p = '_';
    return s;
}


static int is_flag(const char *w)
{
    return w && w[0] == '-' && isalpha((unsigned char) w[1]);
}


static int is_number_token(const char *w)
{
    const char *s = w;
    if (!w || !*w)
        return 0;
    if (*s == '+' || *s == '-')
        s++;
    return isdigit((unsigned char) *s) ||
           (*s == '.' && isdigit((unsigned char) s[1]));
}


/* Enhancement-270: parse a sweep bound as a FINITE number, returning 0 for a
 * non-numeric token (`sw_num`/`atof` silently return 0 for those, which turned a
 * typo'd bound into a 0-valued endpoint and thus a runaway 100000-point sweep) or
 * a non-finite value (`1e400` overflows to `inf`, which then fed an `(int)` cast
 * -> undefined behaviour). On success stores the value and returns 1. */
static int sw_isfinitenum(const char *w, double *out)
{
    char *s = (char *) w;
    double v;
    *out = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0) {
        if (!is_number_token(w))
            return 0;                 /* not a number at all */
        v = atof(w);
    }
    if (!isfinite(v))
        return 0;                     /* inf / NaN */
    *out = v;
    return 1;
}


/* collect tokens up to the next flag, joined with single spaces.
 *
 * Each token is cp_unquote()d first. ngspice's lexer treats the two quote
 * characters differently and says so in its own comments (parser/lexical.c):
 * `'...'` forms one word WITHOUT the quotes, while `"..."` forms one word
 * INCLUDING them, leaving each command to strip the survivors with
 * cp_unquote() -- which most of the frontend does and this file did not. So
 * `-analysis "tran 1n 20n"` reached the command lookup with its quotes still
 * attached and failed as `unknown command '"tran 1n 20n"'`, while the single
 * quoted spelling worked.
 *
 * Unquoting per TOKEN rather than on the joined result matters: stripping one
 * outer pair from `"tran" "1n" "20n"` would eat the wrong two characters. */
static char *collect_until_flag(wordlist **pwl)
{
    char *acc = NULL;
    wordlist *wl = *pwl;
    while (wl && !is_flag(wl->wl_word)) {
        char *tok = cp_unquote(wl->wl_word);   /* fresh memory */
        if (!acc) {
            acc = tok;
        } else {
            char *j = tprintf("%s %s", acc, tok);
            tfree(acc);
            tfree(tok);
            acc = j;
        }
        wl = wl->wl_next;
    }
    *pwl = wl;
    return acc;
}


/* Enhancement-190: parse ONE sweep specification -- `lin|dec|oct <N> <a> <b>`,
 * `list <v> ...`, or `<start> <stop> <step>` -- from the wordlist, advancing
 * *pwl past it. Mallocs *pvals (length *pnv, caller frees). Returns 1 on success,
 * 0 on a malformed spec. Used for both the positional inner knob and each `-vs`
 * outer knob, so all knobs accept the same three forms. */
static int sw_parse_spec(wordlist **pwl, double **pvals, int *pnv)
{
    wordlist *wl = *pwl;
    double *vals = NULL;
    int nv = 0, i;

    *pvals = NULL;
    *pnv = 0;

    if (wl && (eq(wl->wl_word, "lin") || eq(wl->wl_word, "dec") ||
               eq(wl->wl_word, "oct"))) {
        int mode = eq(wl->wl_word, "dec") ? 1 : eq(wl->wl_word, "oct") ? 2 : 0;
        wordlist *a = wl->wl_next, *b = a ? a->wl_next : NULL, *c = b ? b->wl_next : NULL;
        int n; double f0, f1, dn;
        if (!a || !b || !c) {
            fprintf(cp_err, "sweep: %s needs <N> <start> <stop>\n", wl->wl_word);
            return 0;
        }
        /* Enhancement-270: reject non-numeric / non-finite N/start/stop */
        if (!sw_isfinitenum(a->wl_word, &dn) ||
            !sw_isfinitenum(b->wl_word, &f0) || !sw_isfinitenum(c->wl_word, &f1)) {
            fprintf(cp_err, "sweep: %s needs finite numeric <N> <start> <stop>\n",
                    wl->wl_word);
            return 0;
        }
        n = atoi(a->wl_word);
        wl = c->wl_next;
        if (n < 1) n = 1;
        /* Enhancement-270: an absurd point count used to be silently clamped to
         * SW_MAXPTS (for lin, not even that -> a multi-GB alloc), so a huge <N>
         * or a tiny dec/oct spacing ran 100000 analyses (an apparent hang).
         * Reject it up front; a bounded <N> also keeps the dec/oct ratio > 1. */
        if (n > SW_MAXPTS) {
            fprintf(cp_err, "sweep: too many points (N=%d > %d)\n", n, SW_MAXPTS);
            return 0;
        }
        if (mode == 0) {                             /* lin: N points */
            nv = n;
            vals = TMALLOC(double, nv);
            for (i = 0; i < nv; i++)
                vals[i] = (nv == 1) ? f0 : f0 + (f1 - f0) * i / (nv - 1);
        } else {                                     /* dec / oct: N per unit */
            double per = (mode == 1) ? 10.0 : 2.0, mul = pow(per, 1.0 / n);
            double x;
            if (f0 <= 0.0 || f1 <= 0.0) {
                fprintf(cp_err, "sweep: dec/oct need positive endpoints\n");
                return 0;
            }
            for (x = f0; x <= f1 * (1 + 1e-9); x *= mul) {
                if (++nv > SW_MAXPTS) {              /* huge f1/f0 range */
                    fprintf(cp_err, "sweep: too many points (> %d); "
                            "check <N> and the start/stop range\n", SW_MAXPTS);
                    return 0;
                }
            }
            vals = TMALLOC(double, nv);
            for (i = 0, x = f0; i < nv; i++, x *= mul) vals[i] = x;
        }
    } else if (wl && eq(wl->wl_word, "list")) {
        wl = wl->wl_next;
        {   /* count then fill */
            wordlist *p = wl;
            while (p && is_number_token(p->wl_word)) { nv++; p = p->wl_next; }
        }
        if (nv < 1) { fprintf(cp_err, "sweep: list needs values\n"); return 0; }
        vals = TMALLOC(double, nv);
        for (i = 0; i < nv; i++) { vals[i] = sw_num(wl->wl_word); wl = wl->wl_next; }
    } else {                                         /* start stop step */
        wordlist *a = wl, *b = a ? a->wl_next : NULL, *c = b ? b->wl_next : NULL;
        double f0, f1, st, dcnt; int cnt;
        if (!a || !b || !c) {
            fprintf(cp_err, "sweep: need <start> <stop> <step> after the knob\n");
            return 0;
        }
        /* Enhancement-270: a non-numeric bound used to parse as 0 (runaway sweep),
         * and an overflowing bound (`1e400`->inf) fed the `(int)` cast below,
         * undefined behaviour. Require finite numbers, and clamp the point count
         * BEFORE the cast so inf/NaN can never reach it. */
        if (!sw_isfinitenum(a->wl_word, &f0) || !sw_isfinitenum(b->wl_word, &f1) ||
            !sw_isfinitenum(c->wl_word, &st)) {
            fprintf(cp_err, "sweep: non-numeric <start>/<stop>/<step> "
                    "('%s' '%s' '%s')\n", a->wl_word, b->wl_word, c->wl_word);
            return 0;
        }
        wl = c->wl_next;
        if (st == 0.0) { fprintf(cp_err, "sweep: step must be non-zero\n"); return 0; }
        if ((f1 - f0) * st < 0.0) st = -st;          /* fix an obvious sign slip */
        dcnt = floor((f1 - f0) / st + 1e-9) + 1;
        if (!(dcnt >= 1.0)) dcnt = 1.0;              /* also catches NaN */
        if (dcnt > (double) SW_MAXPTS) {             /* e.g. a tiny step: 1n 1u 1e-30 */
            fprintf(cp_err, "sweep: too many points (%.3g > %d); "
                    "check the step size\n", dcnt, SW_MAXPTS);
            return 0;
        }
        cnt = (int) dcnt;                            /* now in [1, SW_MAXPTS] */
        nv = cnt;
        vals = TMALLOC(double, nv);
        for (i = 0; i < nv; i++) vals[i] = f0 + st * i;
    }

    *pwl = wl;
    *pvals = vals;
    *pnv = nv;
    return nv > 0;
}


/* Enhancement-267: append `suffix` to `s` with the suffix sanitized to a legal
 * nutmeg name (non-alnum, except '_', -> '_'), while leaving `s` -- the caller's
 * base output name -- byte-for-byte intact. A knob suffix like `_g_1.5` carries a
 * float ('.', '-', 'e') that is illegal in a vector name and must be mapped, but
 * the base may legitimately be a bus node such as `ph[0]` (Enhancement-221) whose
 * brackets must survive: sanitizing the whole string turned `ph[0]` into `ph_0_`.
 * Takes ownership of both `s` and `suffix` (frees them) and returns the new
 * string. */
static char *sw_append_sanitized(char *s, char *suffix)
{
    char *p, *t;
    for (p = suffix; *p; p++)
        if (!isalnum((unsigned char) *p) && *p != '_') *p = '_';
    t = tprintf("%s%s", s, suffix);
    tfree(suffix);
    tfree(s);
    return t;
}


/* Enhancement-190: build a family-curve / waveform vector name. `base` plus, for
 * each knob index in [j0, nknob), a `_<scname>_<value>` segment. Only the appended
 * segments are sanitized (Enhancement-267); the base name is preserved so a bus
 * node like `ph[0]` keeps its brackets. With j0==nknob (single-knob summary) it
 * returns a plain copy of `base`. */
static char *sw_familyname(const char *base, char *const *kscname,
                           double *const *kvals, const int *idx,
                           int j0, int nknob)
{
    char *s = copy(base);
    int j;
    for (j = j0; j < nknob; j++)
        s = sw_append_sanitized(s, tprintf("_%s_%g", kscname[j], kvals[j][idx[j]]));
    return s;
}


/* Enhancement-189/190: build an overlay-waveform vector name -- `base` plus a
 * `_<value>` segment for EVERY knob (inner first). Only the appended segments are
 * sanitized (Enhancement-267); the base name is preserved. A single knob yields
 * `<base>_<value>` (the E-189 name). */
static char *sw_pointname(const char *base, double *const *kvals,
                          const int *idx, int nknob)
{
    char *s = copy(base);
    int j;
    for (j = 0; j < nknob; j++)
        s = sw_append_sanitized(s, tprintf("_%g", kvals[j][idx[j]]));
    return s;
}


/* Enhancement-267: add a bare `-output` token as one or more recorded outputs.
 * A bus range `base[lo:hi]` (a plain base name, integer lo/hi) is expanded into
 * one output per index -- `base[lo]`, `base[lo±1]`, ..., `base[hi]` -- to match
 * the netlist bus expansion (Enhancement-221), so `sweep g .. -output ph[0:3]`
 * records ph[0]..ph[3]. Any other token (an ordinary node or an expression) is
 * added verbatim. outname[]/outexpr[] get the same string; capped at SW_MAXOUT. */
static void sw_add_bare_output(char **outname, char **outexpr, int *pnout,
                               const char *tok)
{
    const char *lb = strchr(tok, '[');
    size_t len = strlen(tok);
    if (lb && lb != tok && len > 0 && tok[len - 1] == ']') {
        const char *p;
        int plain = 1;
        for (p = tok; p < lb; p++)
            if (!isalnum((unsigned char) *p) && *p != '_') { plain = 0; break; }
        if (plain) {
            char *ep;
            long lo = strtol(lb + 1, &ep, 10);
            if (ep != lb + 1 && *ep == ':') {
                long hi = strtol(ep + 1, &ep, 10);
                if (ep == tok + len - 1) {          /* the closing ']' */
                    long step = (hi >= lo) ? 1 : -1, i;
                    for (i = lo; *pnout < SW_MAXOUT; i += step) {
                        char *nm = tprintf("%.*s[%ld]", (int) (lb - tok), tok, i);
                        outname[*pnout] = nm;
                        outexpr[*pnout] = copy(nm);
                        (*pnout)++;
                        if (i == hi)
                            break;
                    }
                    return;
                }
            }
        }
    }
    if (*pnout < SW_MAXOUT) {
        outname[*pnout] = copy(tok);
        outexpr[*pnout] = copy(tok);
        (*pnout)++;
    }
}


/* Enhancement-432: the option flags `sweep` itself knows, used to decide where a
 * variadic `-output` list ends. A leading `-` on its own cannot end the list:
 * `-v(a)` is a legitimate (negated) output expression and the old single-token
 * form accepted it, so only a flag this command actually recognizes stops the
 * scan. A mistyped flag is therefore read as an expression -- and Enhancement-431
 * then names it in full when it fails to resolve. */
static int sw_is_optflag(const char *w)
{
    return w && (eq(w, "-analysis") || eq(w, "-a") ||
                 eq(w, "-overlay")  || eq(w, "-ov") ||
                 eq(w, "-vs")       || eq(w, "-family") ||
                 eq(w, "-output")   || eq(w, "-o"));
}


/* Enhancement-432: add ONE `-output` token. `name=expr` keeps the given name
 * verbatim (no bus expansion, so `ph=v(a)` is a name and not a bus base);
 * anything else goes through the bare form. Caller guarantees the room. */
static void sw_add_output_token(char **outname, char **outexpr, int *pnout,
                                const char *tok)
{
    const char *eqp = strchr(tok, '=');
    if (eqp && eqp != tok) {
        outname[*pnout] = copy(tok);
        outname[*pnout][eqp - tok] = '\0';
        outexpr[*pnout] = copy(eqp + 1);
        (*pnout)++;
        return;
    }
    sw_add_bare_output(outname, outexpr, pnout, tok);
}


/* Guards against re-entrancy: a `.param` knob re-sources the deck (`reset`),
 * which re-runs a `.sweep` card -- that nested invocation must be a no-op or the
 * sweep would recurse forever. */
static int sweep_active = 0;

void com_sweep(wordlist *wl)
{
    char *analysis = NULL, *scname = NULL;
    const char *swplotname = "sweep";  /* Enhancement-367: the real plot name */
    char *outname[SW_MAXOUT], *outexpr[SW_MAXOUT];
    /* Enhancement-431: how many sweep points each -output failed to resolve
     * at. An output that never resolved is a typo, not data, and must not be
     * emitted as a flat zero curve. */
    int outbad[SW_MAXOUT];
    int outfull = 0;                 /* Enhancement-432: SW_MAXOUT warned once  */
    double *data = NULL;
    int nout = 0, i, k, p, j;
    int save_optimizing = ft_optimizing;
    int overlay = 0;                 /* Enhancement-189: -overlay flag          */
    double **ovx = NULL, **ovy = NULL;   /* per-point waveform scale / values   */
    int *ovlen = NULL;               /* per-point waveform length               */
    char *scwavename = NULL;         /* the analysis scale name (e.g. "time")   */
    /* Enhancement-190: knob[0] is the inner knob (x-axis of the summary plot);
     * knob[1..] are `-vs` outer knobs whose cartesian product forms a curve
     * family. A single knob reduces exactly to the E-146/E-189 path. */
    char   *kname[SW_MAXKNOB];
    int     kkind[SW_MAXKNOB];
    double *kvals[SW_MAXKNOB];
    int     knv[SW_MAXKNOB];
    char   *kscname[SW_MAXKNOB];
    double  prevval[SW_MAXKNOB];
    int     nknob = 0, npt = 1, nv0 = 0, ncomb = 1, havePrev = 0;
    char   *deck_fp_names[SW_MAXKNOB];   /* Enhancement-320: swept .param names   */
    int     ndeck_fp = 0, fast_fp = 0;   /* .param fast-sweep arm state           */
    /* Enhancement-350: nominal value of each swept `.param`, captured before the
     * first point and put back when the sweep ends. See the restore at cleanup. */
    double  deck_fp_nominal[SW_MAXKNOB];
    int     ndeck_fp_nominal = 0;
    /* Enhancement-385: the same courtesy for `alter`/`altermod` knobs. E-350
     * captured and restored only the SW_DECK (`.param`) knobs; sweeping a device
     * or model parameter left it wherever the last point put it, so a following
     * analysis silently ran against the wrong circuit -- `sweep @r1[resistance]
     * 1800 2200 3` left r1 at 2199 and the next `op` was 3.8% off. */
    double  inplace_nominal[SW_MAXKNOB];
    int     ninplace_nominal = 0;
    /* Enhancement-409: a WILDCARD knob overwrites many targets whose nominals all
     * differ, so one number cannot undo it. These hold the per-target capture;
     * wild_nominal[j] != NULL marks knob j as the wildcard kind. wild_ckt[j]
     * pins the circuit the readings came from, so a `.param` co-knob that
     * re-sources the deck cannot make them be replayed onto a different one. */
    double *wild_nominal[SW_MAXKNOB];
    int     wild_n[SW_MAXKNOB], wild_domodel[SW_MAXKNOB];
    char    wild_param[SW_MAXKNOB][128];
    void   *wild_ckt[SW_MAXKNOB];
    /* Enhancement-437: non-empty for the `@*:rmod[param]` kind -- the model leaf
     * name whose copies this knob drives, so the capture/replay can be filtered
     * to them instead of hitting every model that has the parameter. */
    char    wild_leaf[SW_MAXKNOB][128];

    for (j = 0; j < SW_MAXKNOB; j++) {
        kname[j] = NULL; kvals[j] = NULL; kscname[j] = NULL;
        wild_nominal[j] = NULL; wild_n[j] = 0; wild_domodel[j] = 0;
        wild_param[j][0] = '\0'; wild_ckt[j] = NULL;
        wild_leaf[j][0] = '\0';
    }

    if (sweep_active)                /* re-entered via a .param re-source */
        return;
    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "sweep: no circuit loaded\n");
        return;
    }
    if (!wl || !wl->wl_word) {
        fprintf(cp_err, "usage: sweep <knob> (<start> <stop> <step> | "
                        "lin|dec|oct <N> <start> <stop> | list <v> ...) "
                        "[-vs <knob> <spec>]... "
                        "[-analysis <cmd>] [-output <expr> ...] [-overlay]\n");
        return;
    }

    /* --- inner knob (positional) + its spec --- */
    kname[0] = copy(wl->wl_word);
    wl = wl->wl_next;
    if (!sw_parse_spec(&wl, &kvals[0], &knv[0]))
        goto cleanup;
    nknob = 1;

    /* --- options: -vs (outer knob) / -analysis / -output / -overlay --- */
    while (wl) {
        const char *w = wl->wl_word;
        if (eq(w, "-analysis") || eq(w, "-a")) {
            wl = wl->wl_next;
            tfree(analysis);
            analysis = collect_until_flag(&wl);
        } else if (eq(w, "-overlay") || eq(w, "-ov")) {
            overlay = 1; wl = wl->wl_next;
        } else if (eq(w, "-vs") || eq(w, "-family")) {
            wl = wl->wl_next;
            if (!wl || !wl->wl_word) {
                fprintf(cp_err, "sweep: -vs needs <knob> <spec>\n");
                goto cleanup;
            }
            if (nknob >= SW_MAXKNOB) {
                char *skip;
                fprintf(cp_err, "sweep: at most %d knobs (ignoring '%s')\n",
                        SW_MAXKNOB, wl->wl_word);
                wl = wl->wl_next;
                skip = collect_until_flag(&wl);      /* skip its spec */
                tfree(skip);
            } else {
                char *nm = copy(wl->wl_word);
                wl = wl->wl_next;
                if (!sw_parse_spec(&wl, &kvals[nknob], &knv[nknob])) {
                    tfree(nm);
                    goto cleanup;
                }
                kname[nknob] = nm;
                nknob++;
            }
        } else if (eq(w, "-output") || eq(w, "-o")) {
            /* Enhancement-432: consume every expression up to the next option
             * flag, so `-output v(a) v(b)` records both. The usage line has
             * always advertised `-output <expr> ...`, but only the first token
             * was ever read and the rest fell through to `unrecognized token`,
             * which left the sweep running with a silently shorter output list. */
            int ntok = 0;
            wl = wl->wl_next;
            while (wl && wl->wl_word && !sw_is_optflag(wl->wl_word)) {
                char *tok = cp_unquote(wl->wl_word);   /* see collect_until_flag */
                if (nout < SW_MAXOUT) {
                    /* `name=expr` (clean vector name) or a bare `expr` */
                    sw_add_output_token(outname, outexpr, &nout, tok);
                } else if (!outfull) {
                    fprintf(cp_err, "sweep: at most %d outputs "
                                    "(ignoring '%s' and anything after it)\n",
                            SW_MAXOUT, tok);
                    outfull = 1;
                }
                tfree(tok);
                ntok++;
                wl = wl->wl_next;
            }
            if (!ntok)
                fprintf(cp_err, "sweep: %s needs an expression\n", w);
        } else {
            fprintf(cp_err, "sweep: unrecognized token '%s'\n", w);
            wl = wl->wl_next;
        }
    }
    if (!analysis)
        analysis = copy("op");

    /* Enhancement-341: reject a circuit-destroying -analysis before any work. */
    if (sw_analysis_is_destructive(analysis)) {
        tfree(analysis);
        return;
    }

    /* --- classify each knob and size the cartesian product --- */
    nv0 = knv[0];
    for (j = 0; j < nknob; j++) {
        kkind[j] = sw_kind(kname[j]);
        kscname[j] = sw_scalename(kname[j]);
        npt *= knv[j];
    }
    if (npt > SW_MAXPTS) {
        fprintf(cp_err, "sweep: %d cartesian points exceeds the %d cap\n",
                npt, SW_MAXPTS);
        goto cleanup;
    }
    ncomb = npt / nv0;                               /* outer-knob combinations */

    if (nknob == 1)
        fprintf(cp_out, "sweep: %s (%s) over %d point%s, analysis '%s'\n",
                kname[0], sw_knobdesc(kname[0], kkind[0]),
                nv0, nv0 == 1 ? "" : "s", analysis);
    else {
        fprintf(cp_out, "sweep: %s over %d point%s", kname[0], nv0,
                nv0 == 1 ? "" : "s");
        for (j = 1; j < nknob; j++)
            fprintf(cp_out, " x %s(%d)", kname[j], knv[j]);
        fprintf(cp_out, " = %d runs -> %d curve%s per output, analysis '%s'\n",
                npt, ncomb, ncomb == 1 ? "" : "s", analysis);
    }

    /* --- Enhancement-320: try to arm the .param fast-sweep. Collect the
     * SW_DECK (symbolic `.param`) knob names; if every swept param feeds only
     * addressable top-level device/model values, sw_fp_build() captures them and
     * the point loop pushes values in place (alter) instead of re-sourcing. */
    {
        ndeck_fp = 0;
        for (j = 0; j < nknob; j++)
            if (kkind[j] == SW_DECK)
                deck_fp_names[ndeck_fp++] = kname[j];
        /* Enhancement-350: remember what each swept `.param` was worth BEFORE the
         * first point overwrites it, so the sweep can put it back on the way out. */
        ndeck_fp_nominal = 0;
        for (j = 0; j < ndeck_fp; j++) {
            int found = 0;
            double v = nupa_get_param(deck_fp_names[j], &found);
            if (!found)
                break;                  /* cannot restore what we cannot read */
            deck_fp_nominal[ndeck_fp_nominal++] = v;
        }
        if (ndeck_fp_nominal != ndeck_fp)
            ndeck_fp_nominal = 0;       /* all or nothing -- never a partial undo */

        /* Enhancement-385: and the nominal of every in-place (`alter`/`altermod`)
         * knob, read from the LIVE circuit before the first point moves it. Same
         * all-or-nothing rule: a partially restored circuit is harder to reason
         * about than an untouched one. */
        {
            int nin = 0, allok = 1;
            for (j = 0; j < nknob; j++) {
                int ok = 0;
                double v;
                if (kkind[j] == SW_DECK)
                    continue;
                /* Enhancement-409: a wildcard is captured per target through the
                 * device tables, since it has no single readable value. */
                if (sw_wildcard_knob(kname[j], wild_param[j],
                                     sizeof wild_param[j], &wild_domodel[j],
                                     wild_leaf[j], sizeof wild_leaf[j])) {
                    int got;
                    if (!ft_curckt || !ft_curckt->ci_ckt) {
                        allok = 0;
                        break;
                    }
                    /* Enhancement-437: a named-model wildcard captures only the
                     * models carrying that leaf name; the older spellings still
                     * capture every target that has the parameter. */
                    if (wild_leaf[j][0])
                        got = if_saveparam_wildcard_model_named(
                                  ft_curckt->ci_ckt, wild_leaf[j],
                                  wild_param[j], &wild_nominal[j], &wild_n[j]);
                    else
                        got = if_saveparam_wildcard(ft_curckt->ci_ckt,
                                                    wild_param[j],
                                                    wild_domodel[j],
                                                    &wild_nominal[j],
                                                    &wild_n[j]);
                    if (!got) {
                        allok = 0;
                        break;
                    }
                    wild_ckt[j] = (void *) ft_curckt->ci_ckt;
                    inplace_nominal[nin++] = 0.0;   /* keeps the indices aligned */
                    continue;
                }
                v = sw_read_knob(kname[j], &ok);
                if (!ok) { allok = 0; break; }
                inplace_nominal[nin++] = v;
            }
            ninplace_nominal = allok ? nin : 0;
        }
        fast_fp = (ndeck_fp > 0) ? sw_fp_build(deck_fp_names, ndeck_fp) : 0;
        if (fast_fp) {
            int nb = 0, ntext = 0;
            struct sw_fp_bind *b;
            for (b = sw_fp_list; b; b = b->next) {
                nb++;
                if (!b->rok)
                    ntext++;
            }
            fprintf(cp_out, "sweep: fast .param path armed (%d value binding%s, "
                    "no per-point reset)", nb, nb == 1 ? "" : "s");
            /* Enhancement-344: instance AND model binds now take the direct slot
             * write, so an unresolved bind is the exception -- say so rather than
             * letting the slower textual push hide behind the same banner. */
            if (ntext)
                fprintf(cp_out, ", %d via alter/altermod", ntext);
            fprintf(cp_out, "\n");
        }
    }

    /* --- run the sweep over the cartesian product (inner knob varies fastest,
     * so point p = outer_combo * nv0 + inner_index) --- */
    sweep_active = 1;                                /* block re-source recursion */
    ft_optimizing = TRUE;                            /* silence per-point chatter */
    /* Enhancement-432: zero the WHOLE array, not just the `nout` entries known
     * here. With no `-output` the outputs are auto-collected inside the point
     * loop below, so `nout` is still 0 at this line and every auto-collected
     * output inherited stack garbage -- which E-431 then read as a resolve
     * failure and used to drop perfectly good curves. */
    for (k = 0; k < SW_MAXOUT; k++)
        outbad[k] = 0;                           /* Enhancement-431 */

    for (p = 0; p < npt; p++) {
        int idx[SW_MAXKNOB], rem = p, anyDeck = 0, deckChanged = 0, resetNeeded;
        double curval[SW_MAXKNOB];
        for (j = 0; j < nknob; j++) {
            idx[j] = rem % knv[j];
            rem /= knv[j];
            curval[j] = kvals[j][idx[j]];
        }
        for (j = 0; j < nknob; j++)
            if (kkind[j] == SW_DECK) {
                anyDeck = 1;
                if (!havePrev || curval[j] != prevval[j]) deckChanged = 1;
            }
        resetNeeded = (!havePrev) || deckChanged;
        if (resetNeeded && anyDeck) {
            if (fast_fp) {                           /* Enhancement-320: no reset */
                double dvals[SW_MAXKNOB];
                int di = 0;
                for (j = 0; j < nknob; j++)
                    if (kkind[j] == SW_DECK) dvals[di++] = curval[j];
                sw_fp_apply(deck_fp_names, dvals, ndeck_fp);
            } else {                                 /* re-source once for the point */
                for (j = 0; j < nknob; j++)
                    if (kkind[j] == SW_DECK) sw_set_deck(kname[j], curval[j]);
                sw_run_cmd("reset");
                ft_optimizing = TRUE;                /* reset clears it */
            }
        }
        for (j = 0; j < nknob; j++)                  /* in-place after any reset */
            if (kkind[j] != SW_DECK) sw_set_inplace(kkind[j], kname[j], curval[j]);
        for (j = 0; j < nknob; j++) prevval[j] = curval[j];
        havePrev = 1;
        sw_run_cmd(analysis);

        if (p == 0 && nout == 0) {
            /* no -output given: record every node voltage of the analysis */
            struct dvec *d;
            if (plot_cur)
                for (d = plot_cur->pl_dvecs; d && nout < SW_MAXOUT; d = d->v_next)
                    if (d->v_type == SV_VOLTAGE && isreal(d) && d->v_name &&
                        d->v_name[0] != '@' && !strchr(d->v_name, '#')) {
                        outname[nout] = copy(d->v_name);
                        outexpr[nout] = copy(d->v_name);
                        nout++;
                    }
            if (nout == 0) {
                ft_optimizing = save_optimizing;
                fprintf(cp_err, "sweep: no outputs (give -output <expr>)\n");
                goto cleanup;
            }
        }
        if (p == 0) {
            data = TMALLOC(double, (size_t) npt * (size_t) nout);
            if (overlay) {
                ovx = TMALLOC(double *, npt);
                ovlen = TMALLOC(int, npt);
                ovy = TMALLOC(double *, (size_t) npt * (size_t) nout);
                if (plot_cur && plot_cur->pl_scale && plot_cur->pl_scale->v_name)
                    scwavename = copy(plot_cur->pl_scale->v_name);
            }
        }
        for (k = 0; k < nout; k++) {
            if (overlay) {
                double *xk, *yk;
                int nk = sw_eval_vec(outexpr[k], &xk, &yk);
                if (k == 0) { ovx[p] = xk; ovlen[p] = nk; }
                else tfree(xk);                          /* same scale as k==0 */
                ovy[(size_t) p * (size_t) nout + (size_t) k] = yk;
                data[(size_t) p * (size_t) nout + (size_t) k] =
                    (nk > 0 && yk) ? yk[nk - 1] : 0.0;   /* last value from waveform */
                if (nk <= 0 || !yk)
                    outbad[k]++;                         /* Enhancement-431 */
            } else {
                int okk = 0;
                data[(size_t) p * (size_t) nout + (size_t) k] =
                    sw_eval_expr_ok(outexpr[k], &okk);
                if (!okk)
                    outbad[k]++;                         /* Enhancement-431 */
            }
        }
    }
    ft_optimizing = save_optimizing;

    /* --- emit the summary plot: the inner knob is the x-scale, and each
     * combination of the outer `-vs` knobs produces one curve per output. With a
     * single knob this is exactly the E-146 transfer curve (name = <output>). --- */
    {
        struct plot *pl = plot_alloc("sweep");
        struct dvec *sc;
        int c;
        scname = copy(kscname[0]);
        pl->pl_name = copy("Sweep");
        pl->pl_title = copy(kname[0]);
        plot_new(pl);
        plot_setcur(pl->pl_typename);
        /* Enhancement-367: remember the real name so the summary below can quote
         * something `setplot` accepts. `pl` is block-scoped. */
        swplotname = pl->pl_typename;
        sc = dvec_alloc(copy(scname), SV_NOTYPE,
                        (short) (VF_REAL | VF_PERMANENT), nv0, NULL);
        for (i = 0; i < nv0; i++) sc->v_realdata[i] = kvals[0][i];
        vec_new(sc);                                 /* first permanent -> scale */
        for (k = 0; k < nout; k++) {
            /* Enhancement-431: an output that resolved at NO sweep point is a
             * typo, not data. It used to be emitted anyway, as a column of
             * zeros -- a clean, plottable, entirely fictional flat line, behind
             * nothing louder than a `checkvalid` warning. Say so, and do not
             * emit the curve. A PARTIAL failure still gets its curve: the points
             * that did resolve are real, and dropping them would lose data. */
            if (outbad[k] >= npt) {
                fprintf(cp_err,
                        "Error: sweep -output %s never resolved -- no such "
                        "vector; that curve is not recorded.\n", outexpr[k]);
                continue;
            }
            if (outbad[k] > 0)
                fprintf(cp_err,
                        "Warning: sweep -output %s did not resolve at %d of %d "
                        "points; those entries are zero.\n",
                        outexpr[k], outbad[k], npt);
            for (c = 0; c < ncomb; c++) {
                int idx[SW_MAXKNOB], cc = c;
                struct dvec *v;
                for (j = 1; j < nknob; j++) { idx[j] = cc % knv[j]; cc /= knv[j]; }
                v = dvec_alloc(sw_familyname(outname[k], kscname, kvals, idx, 1, nknob),
                               SV_NOTYPE, (short) (VF_REAL | VF_PERMANENT), nv0, NULL);
                for (i = 0; i < nv0; i++)
                    v->v_realdata[i] =
                        data[((size_t) c * (size_t) nv0 + (size_t) i)
                             * (size_t) nout + (size_t) k];
                vec_new(v);
            }
        }
    }
    if (nknob == 1)
        /* Enhancement-367: name the plot the user can actually select. This
         * used to print the literal 'sweep', which `setplot` rejects -- the one
         * hint given for returning to an earlier sweep was wrong, and it only
         * bites once a session has more than one sweep. */
        fprintf(cp_out, "sweep: %d points into plot '%s'%s; "
                        "`plot <output>` to view vs %s.\n",
                nv0, swplotname, overlay ? "" : " (now current)", scname);
    else
        fprintf(cp_out, "sweep: %d curve%s x %d output%s into plot '%s'%s; "
                        "`plot <output>_...` to view the family vs %s.\n",
                ncomb, ncomb == 1 ? "" : "s", nout, nout == 1 ? "" : "s",
                swplotname, overlay ? "" : " (now current)", scname);

    /* --- Enhancement-189/190: -overlay plot of every run's full waveform, one
     * vector per (output, cartesian point) resampled onto a common grid. The
     * name carries every knob's value (inner first), so a single-knob overlay is
     * `<output>_<val>` exactly as in E-189. --- */
    if (overlay && ovy) {
        double xmin = HUGE_VAL, xmax = -HUGE_VAL;
        int ncommon = 0, jj;
        for (p = 0; p < npt; p++) {
            if (ovlen[p] < 1) continue;
            if (ovx[p][0] < xmin) xmin = ovx[p][0];
            if (ovx[p][ovlen[p] - 1] > xmax) xmax = ovx[p][ovlen[p] - 1];
            if (ovlen[p] > ncommon) ncommon = ovlen[p];
        }
        if (ncommon > 1 && xmax > xmin) {
            struct plot *pw = plot_alloc("sweepwave");
            struct dvec *xs;
            pw->pl_name = copy("Sweep waveforms");
            pw->pl_title = copy(kname[0]);
            plot_new(pw);
            plot_setcur(pw->pl_typename);
            xs = dvec_alloc(copy(scwavename ? scwavename : "x"), SV_NOTYPE,
                            (short) (VF_REAL | VF_PERMANENT), ncommon, NULL);
            for (jj = 0; jj < ncommon; jj++)
                xs->v_realdata[jj] = xmin + (xmax - xmin) * jj / (ncommon - 1);
            vec_new(xs);                             /* first permanent -> scale */
            for (k = 0; k < nout; k++)
                for (p = 0; p < npt; p++) {
                    int idx[SW_MAXKNOB], rem = p;
                    struct dvec *v;
                    for (j = 0; j < nknob; j++) { idx[j] = rem % knv[j]; rem /= knv[j]; }
                    v = dvec_alloc(sw_pointname(outname[k], kvals, idx, nknob),
                                   SV_NOTYPE, (short) (VF_REAL | VF_PERMANENT),
                                   ncommon, NULL);
                    for (jj = 0; jj < ncommon; jj++)
                        v->v_realdata[jj] = sw_interp(ovx[p],
                                                ovy[(size_t) p * (size_t) nout + (size_t) k],
                                                ovlen[p], xs->v_realdata[jj]);
                    vec_new(v);
                }
            fprintf(cp_out, "sweep: overlay of %d waveform%s per output resampled "
                            "to %d points in the 'sweepwave' plot '%s' (now current); "
                            "`plot <output>_<val> ...` to view.\n",
                    npt, npt == 1 ? "" : "s", ncommon, pw->pl_typename);
        } else {
            fprintf(cp_out, "sweep: -overlay ignored (analysis '%s' has no waveform "
                            "to overlay).\n", analysis);
        }
    }

cleanup:
    /* Enhancement-350: put each swept `.param` back to what it was worth before
     * the sweep started.
     *
     * The two paths used to disagree about this, which is exactly what E-320
     * promises they never do. The reset path drives a point with `alterparam`,
     * which edits the parameter PERMANENTLY -- so a later `reset`, which
     * re-sources that same deck, reproduced the last swept value rather than the
     * deck's. The fast path never touches the deck, so `reset` did restore. Same
     * command, same netlist, different state afterwards depending only on which
     * path happened to arm.
     *
     * Leaving it dirty also broke the NEXT sweep of the same parameter. Arming
     * self-checks each captured expression against the value numparam baked into
     * the flattened card at nominal; with the dico still holding the last swept
     * value that check cannot pass, so the second sweep silently fell back to the
     * reset path -- no error, just a quiet loss of the fast path, and then the
     * permanent edit above.
     *
     * Restoring is the direction that makes both paths agree AND keeps `reset`
     * meaningful. It also matches how ngspice treats a swept source in `.dc`,
     * which does not leave it parked at the last step. */
    if (ndeck_fp_nominal == ndeck_fp && ndeck_fp > 0) {
        /* The deck text and the numparam dico both have to go back. `alterparam`
         * rewrites the deck, which is what a later `reset` re-sources; the dico
         * is what the NEXT sweep reads for its own nominal and what arming
         * self-checks against, so leaving it dirty would just move the problem
         * one sweep along -- the second sweep would faithfully restore the first
         * sweep's last value as though it were the deck's. */
        for (j = 0; j < ndeck_fp; j++)
            sw_set_deck(deck_fp_names[j], deck_fp_nominal[j]);
        if (ft_curckt && ft_curckt->ci_dicos)
            nupa_set_dicoslist(ft_curckt->ci_dicos);
        for (j = 0; j < ndeck_fp; j++)
            nupa_add_param(deck_fp_names[j], deck_fp_nominal[j]);
        nupa_recompute_params(deck_fp_names, ndeck_fp);

        /* Enhancement-385: on the FAST path (E-320) the point loop never touched
         * the deck -- it pushed each point's values STRAIGHT INTO the live
         * circuit -- so putting the numparam table back is not enough. The
         * devices still held the last point's values: after
         * `sweep rl lin 3 1k 5k` a `.param rl=3k` deck was left with
         * @r2[resistance] = 5000, and the next `op` was 19% off. Push the
         * nominals back exactly the way each point was pushed. This must precede
         * sw_fp_free() below, which drops the binds it needs. */
        if (fast_fp)
            sw_fp_apply(deck_fp_names, deck_fp_nominal, ndeck_fp);
    }

    /* Enhancement-385: put the `alter`/`altermod` knobs back too. This runs
     * AFTER the `.param` restore above, because that path can `reset` (which
     * re-sources the deck and drops in-place alters); writing these first would
     * simply lose them. */
    if (ninplace_nominal > 0) {
        int nin = 0;
        for (j = 0; j < nknob; j++) {
            if (kkind[j] == SW_DECK)
                continue;
            if (nin < ninplace_nominal) {
                if (wild_nominal[j]) {
                    /* Enhancement-409: replay the per-target nominals, but only
                     * onto the circuit they were read from -- if a `.param`
                     * co-knob re-sourced the deck, every model is already back
                     * at its deck value and these readings no longer apply. */
                    if (ft_curckt && ft_curckt->ci_ckt &&
                            (void *) ft_curckt->ci_ckt == wild_ckt[j]) {
                        if (wild_leaf[j][0])     /* Enhancement-437 */
                            (void) if_restoreparam_wildcard_model_named(
                                       ft_curckt->ci_ckt, wild_leaf[j],
                                       wild_param[j], wild_nominal[j],
                                       wild_n[j]);
                        else
                            (void) if_restoreparam_wildcard(ft_curckt->ci_ckt,
                                                            wild_param[j],
                                                            wild_domodel[j],
                                                            wild_nominal[j],
                                                            wild_n[j]);
                    }
                } else {
                    sw_set_inplace(kkind[j], kname[j], inplace_nominal[nin]);
                }
            }
            nin++;
        }
    }

    sw_fp_free();                        /* Enhancement-320: drop fast-path binds */
    sweep_active = 0;
    ft_optimizing = save_optimizing;
    for (k = 0; k < nout; k++) { tfree(outname[k]); tfree(outexpr[k]); }
    if (ovx) for (p = 0; p < npt; p++) tfree(ovx[p]);
    if (ovy) for (p = 0; p < npt * nout; p++) tfree(ovy[p]);
    tfree(ovx); tfree(ovy); tfree(ovlen); tfree(scwavename);
    for (j = 0; j < SW_MAXKNOB; j++) {
        tfree(kname[j]); tfree(kvals[j]); tfree(kscname[j]);
        tfree(wild_nominal[j]);          /* Enhancement-409 */
    }
    tfree(analysis); tfree(scname);
    tfree(data);
}


/**********
Enhancement-150: `highsigma` -- rare-event (high-sigma) failure-probability
estimation by scaled-sigma importance sampling. It lives here because it reuses
this file's synchronous command runner (`sw_run_cmd`) and expression evaluator
(`sw_eval_expr`), and is likewise a sampling-driven analysis loop.

Plain Monte Carlo cannot reach the 4-6 sigma failure probabilities that matter
for high-replication circuits (SRAM cells, standard-cell libraries): a 1e-7
failure needs ~1e8 runs to see ten failures. Scaled-sigma sampling inflates every
Gaussian `.param`'s sigma by a factor `lambda`, so the rare failure region is
sampled often, then reweights each sample by the likelihood ratio
p_nominal/p_inflated to recover an unbiased estimate. It is direction-free -- no
gradient / sensitivity / most-probable-failure-point search -- so it is robust for
an arbitrary failure condition.

  highsigma <N> [-scale <lambda>] [-seed <s>] [-analysis <cmd>] -metric <expr> [-max <hi>] [-min <lo>]

Each of N samples re-sources the deck (redrawing the lambda-inflated Gaussian
`.param`s via the E-149/E-150 sampler), runs `-analysis` (default `op`), and
evaluates `-metric`; the sample fails if the metric exceeds `-max` or falls below
`-min` (at least one spec limit is required; give both for a two-sided spec). The
comparison is done here rather than inside the expression precisely because a bare
`>` / `<` in a control-language command is an I/O redirect. Reports P(fail), its
relative error, the equivalent one-sided sigma-to-fail, and the raw failure count,
and leaves them in the vectors/vars `highsigma_pfail`, `highsigma_relerr`,
`highsigma_sigma`, `highsigma_nfail`.
**********/

#define HS_MAXN 100000000

/* Publish a scalar result as a settable variable ($name) and a one-element
 * vector (so scripts can use it in `let`/`print`). */
static void hs_set_result(const char *name, double val)
{
    struct dvec *v;
    cp_vset(name, CP_REAL, &val);
    v = dvec_alloc(copy(name), SV_NOTYPE, VF_REAL | VF_PERMANENT, 1, NULL);
    if (v) {
        v->v_realdata[0] = val;
        vec_new(v);
    }
}

void com_highsigma(wordlist *wl)
{
    int nsamp = 0;
    double lambda = 2.0;
    unsigned seed = 1;
    char analysis[512] = "op";
    char metric[1024] = "";
    double hi = 0.0, lo = 0.0;
    int have_metric = 0, have_max = 0, have_min = 0;
    int save_optimizing = ft_optimizing;

    if (wl == NULL || wl->wl_word == NULL) {
        fprintf(cp_err, "Usage: highsigma <N> [-scale <lambda>] [-seed <s>] "
                        "[-analysis <cmd>] -metric <expr> [-max <hi>] [-min <lo>]\n");
        return;
    }

    nsamp = atoi(wl->wl_word);
    if (nsamp < 2 || nsamp > HS_MAXN) {
        fprintf(cp_err, "highsigma: sample count must be in [2, %d] (got '%s')\n",
                HS_MAXN, wl->wl_word);
        return;
    }
    wl = wl->wl_next;

    while (wl && wl->wl_word) {
        const char *w = wl->wl_word;
        if (eq(w, "-scale") || eq(w, "scale")) {
            if (!wl->wl_next) { fprintf(cp_err, "highsigma: -scale needs a value\n"); return; }
            wl = wl->wl_next; lambda = atof(wl->wl_word); wl = wl->wl_next;
        } else if (eq(w, "-seed") || eq(w, "seed")) {
            if (!wl->wl_next) { fprintf(cp_err, "highsigma: -seed needs a value\n"); return; }
            wl = wl->wl_next; seed = (unsigned) strtoul(wl->wl_word, NULL, 10); wl = wl->wl_next;
        } else if (eq(w, "-max")) {
            if (!wl->wl_next) { fprintf(cp_err, "highsigma: -max needs a value\n"); return; }
            wl = wl->wl_next; hi = sw_num(wl->wl_word); have_max = 1; wl = wl->wl_next;
        } else if (eq(w, "-min")) {
            if (!wl->wl_next) { fprintf(cp_err, "highsigma: -min needs a value\n"); return; }
            wl = wl->wl_next; lo = sw_num(wl->wl_word); have_min = 1; wl = wl->wl_next;
        } else if (eq(w, "-analysis")) {
            /* `is_flag()`, not a bare leading '-': an analysis argument may be
             * negative (`disto lin 3 1e5 1e6 -0.5`), and stopping at any '-'
             * ended the list there and left `-0.5` to be reported as an
             * unexpected token. Tokens are cp_unquote()d as in
             * collect_until_flag(), which `sweep` and `optimize` use. */
            analysis[0] = '\0';
            wl = wl->wl_next;
            while (wl && wl->wl_word && !is_flag(wl->wl_word)) {
                char *tok = cp_unquote(wl->wl_word);
                /* Enhancement-434: refuse rather than truncate. `analysis` is a
                 * fixed 512-byte buffer and strncat simply stopped at the end,
                 * so a longer command lost its tail SILENTLY and a DIFFERENT
                 * command ran. sweep/optimize build the same string with
                 * tprintf and have no limit; these three could not, so they at
                 * least have to say so. */
                if (strlen(analysis) + strlen(tok) + 2 > sizeof(analysis)) {
                    fprintf(cp_err, "%s: -analysis command is too long "
                                    "(limit %d characters)\n",
                            "highsigma", (int) sizeof(analysis) - 1);
                    tfree(tok);
                    return;
                }
                if (analysis[0]) strncat(analysis, " ", sizeof(analysis) - strlen(analysis) - 1);
                strncat(analysis, tok, sizeof(analysis) - strlen(analysis) - 1);
                tfree(tok);
                wl = wl->wl_next;
            }
        } else if (eq(w, "-metric")) {
            /* one token -- an ngspice expression needs no spaces, and a leading
             * '-' (e.g. `-1/i(v1)`) would otherwise look like a flag */
            if (!wl->wl_next) { fprintf(cp_err, "highsigma: -metric needs an expression\n"); return; }
            wl = wl->wl_next;
            strncpy(metric, wl->wl_word, sizeof(metric) - 1);
            metric[sizeof(metric) - 1] = '\0';
            have_metric = 1;
            wl = wl->wl_next;
        } else {
            fprintf(cp_err, "highsigma: unexpected token '%s'\n", w);
            return;
        }
    }

    if (!have_metric || metric[0] == '\0') {
        fprintf(cp_err, "highsigma: a '-metric <expr>' is required\n");
        return;
    }
    if (!have_max && !have_min) {
        fprintf(cp_err, "highsigma: give a spec limit -- '-max <hi>' and/or "
                        "'-min <lo>' (failure region)\n");
        return;
    }
    if (lambda <= 1.0) {
        fprintf(cp_err, "highsigma: -scale (lambda) must be > 1 (got %g)\n", lambda);
        return;
    }
    if (ft_curckt == NULL || ft_curckt->ci_ckt == NULL) {
        fprintf(cp_err, "highsigma: no circuit loaded\n");
        return;
    }

    {
        char spec[128] = "";
        if (have_max) snprintf(spec, sizeof spec, "> %g", hi);
        if (have_min) snprintf(spec + strlen(spec), sizeof spec - strlen(spec),
                               "%s< %g", have_max ? " or " : "", lo);
        fprintf(cp_out, "highsigma: %d samples, scale (sigma inflation) = %g, "
                        "analysis '%s', fail if (%s) %s\n",
                nsamp, lambda, analysis, metric, spec);
    }

    mc_sss_config(nsamp, lambda, seed);
    double sum_wf = 0.0, sum_w2f2 = 0.0;
    long nfail = 0;

    ft_optimizing = TRUE;
    for (int i = 0; i < nsamp; i++) {
        ft_optimizing = TRUE;               /* reset re-source may clear it */
        sw_run_cmd("reset");                /* redraws the lambda-inflated .params */
        sw_run_cmd(analysis);
        double m = sw_eval_expr(metric);
        double f = ((have_max && m > hi) || (have_min && m < lo)) ? 1.0 : 0.0;
        double w = mc_sample_weight();
        double x = w * f;
        sum_wf += x;
        sum_w2f2 += x * x;
        if (f != 0.0) nfail++;
    }
    ft_optimizing = save_optimizing;
    mc_sss_off();

    double pfail = sum_wf / (double) nsamp;
    double var_x = sum_w2f2 / (double) nsamp - pfail * pfail;
    if (var_x < 0.0) var_x = 0.0;
    double se = sqrt(var_x / (double) nsamp);
    double relerr = (pfail > 0.0) ? se / pfail : 0.0;
    double sigma = (pfail > 0.0 && pfail < 1.0) ? -inv_normal_cdf(pfail) : 0.0;

    fprintf(cp_out,
            "\n  failures observed : %ld / %d (in the inflated sampling)\n"
            "  P(fail)           : %.4e  +/- %.2e  (relative error %.1f%%)\n"
            "  equivalent sigma  : %.3f  (one-sided, P = Phi(-sigma))\n",
            nfail, nsamp, pfail, se, 100.0 * relerr, sigma);
    if (nfail == 0)
        fprintf(cp_out, "  (no failures sampled -- increase -scale or N; "
                        "P(fail) is below what this run can resolve)\n");

    hs_set_result("highsigma_pfail", pfail);
    hs_set_result("highsigma_relerr", relerr);
    hs_set_result("highsigma_sigma", sigma);
    hs_set_result("highsigma_nfail", (double) nfail);
}


/**********
Enhancement-151: `montecarlo` -- a packaged Monte Carlo yield analysis. It lives
here for the same reason `highsigma` does (reuses `sw_run_cmd` and
`sw_eval_expr`, and is a sampling-driven analysis loop).

  montecarlo <N> [-lhs] [-seed <s>] [-analysis <cmd>]
             (-spec <metric> [-max <hi>] [-min <lo>])...

Runs N Monte Carlo samples (each re-sources the deck, redrawing its random
`.param`s, and runs `-analysis`, default `op`), evaluates every `-spec` metric,
and counts a sample as PASS only if all specs are within their limits. Reports
the yield (fraction passing) with a Wilson 95% confidence interval and a
per-spec violation count; leaves `montecarlo_yield`, `montecarlo_npass`,
`montecarlo_n` for scripting. With `-lhs` it draws Latin-Hypercube samples
(Enhancement-149) for a lower-variance yield estimate. Process/mismatch
correlations are handled by `mvnorm()` (Enhancement-151) in the `.param`s, and
process corners by the ordinary `.lib`/`.include` corner selection.
**********/

#define MC_MAXSPEC 32

void com_montecarlo(wordlist *wl)
{
    int nsamp = 0, uselhs = 0, nspec = 0, usewarm = 0;
    unsigned seed = 1;
    char analysis[512] = "op";
    char metric[MC_MAXSPEC][256];
    double hi[MC_MAXSPEC], lo[MC_MAXSPEC];
    int hasmax[MC_MAXSPEC], hasmin[MC_MAXSPEC];
    long specfail[MC_MAXSPEC];
    int save_optimizing = ft_optimizing;
    int s;

    if (wl == NULL || wl->wl_word == NULL) {
        fprintf(cp_err, "Usage: montecarlo <N> [-lhs] [-warm] [-seed <s>] [-analysis <cmd>] "
                        "(-spec <metric> [-max <hi>] [-min <lo>])...\n");
        return;
    }
    nsamp = atoi(wl->wl_word);
    if (nsamp < 2) {
        fprintf(cp_err, "montecarlo: sample count must be >= 2 (got '%s')\n", wl->wl_word);
        return;
    }
    wl = wl->wl_next;

    while (wl && wl->wl_word) {
        const char *w = wl->wl_word;
        if (eq(w, "-lhs")) {
            uselhs = 1; wl = wl->wl_next;
        } else if (eq(w, "-warm")) {
            usewarm = 1; wl = wl->wl_next;
        } else if (eq(w, "-seed") || eq(w, "seed")) {
            if (!wl->wl_next) { fprintf(cp_err, "montecarlo: -seed needs a value\n"); return; }
            wl = wl->wl_next; seed = (unsigned) strtoul(wl->wl_word, NULL, 10); wl = wl->wl_next;
        } else if (eq(w, "-analysis")) {
            /* `is_flag()`, not a bare leading '-': an analysis argument may be
             * negative (`disto lin 3 1e5 1e6 -0.5`), and stopping at any '-'
             * ended the list there and left `-0.5` to be reported as an
             * unexpected token. Tokens are cp_unquote()d as in
             * collect_until_flag(), which `sweep` and `optimize` use. */
            analysis[0] = '\0';
            wl = wl->wl_next;
            while (wl && wl->wl_word && !is_flag(wl->wl_word)) {
                char *tok = cp_unquote(wl->wl_word);
                /* Enhancement-434: refuse rather than truncate. `analysis` is a
                 * fixed 512-byte buffer and strncat simply stopped at the end,
                 * so a longer command lost its tail SILENTLY and a DIFFERENT
                 * command ran. sweep/optimize build the same string with
                 * tprintf and have no limit; these three could not, so they at
                 * least have to say so. */
                if (strlen(analysis) + strlen(tok) + 2 > sizeof(analysis)) {
                    fprintf(cp_err, "%s: -analysis command is too long "
                                    "(limit %d characters)\n",
                            "montecarlo", (int) sizeof(analysis) - 1);
                    tfree(tok);
                    return;
                }
                if (analysis[0]) strncat(analysis, " ", sizeof(analysis) - strlen(analysis) - 1);
                strncat(analysis, tok, sizeof(analysis) - strlen(analysis) - 1);
                tfree(tok);
                wl = wl->wl_next;
            }
        } else if (eq(w, "-spec")) {
            if (nspec >= MC_MAXSPEC) { fprintf(cp_err, "montecarlo: too many -spec (max %d)\n", MC_MAXSPEC); return; }
            if (!wl->wl_next) { fprintf(cp_err, "montecarlo: -spec needs a metric expression\n"); return; }
            wl = wl->wl_next;
            strncpy(metric[nspec], wl->wl_word, sizeof(metric[nspec]) - 1);
            metric[nspec][sizeof(metric[nspec]) - 1] = '\0';
            hasmax[nspec] = hasmin[nspec] = 0; specfail[nspec] = 0;
            nspec++;
            wl = wl->wl_next;
        } else if (eq(w, "-max")) {
            if (nspec == 0) { fprintf(cp_err, "montecarlo: -max before any -spec\n"); return; }
            if (!wl->wl_next) { fprintf(cp_err, "montecarlo: -max needs a value\n"); return; }
            wl = wl->wl_next; hi[nspec - 1] = sw_num(wl->wl_word); hasmax[nspec - 1] = 1; wl = wl->wl_next;
        } else if (eq(w, "-min")) {
            if (nspec == 0) { fprintf(cp_err, "montecarlo: -min before any -spec\n"); return; }
            if (!wl->wl_next) { fprintf(cp_err, "montecarlo: -min needs a value\n"); return; }
            wl = wl->wl_next; lo[nspec - 1] = sw_num(wl->wl_word); hasmin[nspec - 1] = 1; wl = wl->wl_next;
        } else {
            fprintf(cp_err, "montecarlo: unexpected token '%s'\n", w);
            return;
        }
    }

    if (nspec == 0) {
        fprintf(cp_err, "montecarlo: at least one '-spec <metric> (-max/-min)' is required\n");
        return;
    }
    for (s = 0; s < nspec; s++)
        if (!hasmax[s] && !hasmin[s]) {
            fprintf(cp_err, "montecarlo: spec '%s' has no -max/-min limit\n", metric[s]);
            return;
        }
    if (ft_curckt == NULL || ft_curckt->ci_ckt == NULL) {
        fprintf(cp_err, "montecarlo: no circuit loaded\n");
        return;
    }

    fprintf(cp_out, "montecarlo: %d %s samples, analysis '%s', %d spec%s\n",
            nsamp, uselhs ? "Latin-Hypercube" : "random", analysis,
            nspec, nspec == 1 ? "" : "s");

    if (uselhs) {
        mc_lhs_config(nsamp, seed);
    } else {
        char cmd[64];
        snprintf(cmd, sizeof cmd, "setseed %u", seed);
        sw_run_cmd(cmd);
    }

    /* Enhancement-346: arm the fast path for Monte Carlo. MC has no swept knob
     * -- what varies per sample is the RNG, so sw_fp_build() is asked for the
     * random value bindings alone (nsw == 0). When every random draw feeds an
     * addressable device/model value, a sample is a re-draw plus an in-place
     * push instead of a full re-source; the binds are evaluated in deck order
     * and never cached, so the RNG stream is consumed exactly as the reset path
     * consumed it and the samples are identical draw for draw. */
    int fast_mc = sw_fp_build(NULL, 0);
    if (fast_mc)
        fprintf(cp_out, "montecarlo: fast path armed (%d random value binding%s,"
                " no per-sample reset)\n", sw_fp_nrnd, sw_fp_nrnd == 1 ? "" : "s");

    long npass = 0;
    ft_optimizing = TRUE;
    /* Enhancement-188: warm-start each sample's DC bias point from the previous
     * converged solution (opt-in). Only the iteration count changes; the
     * converged point -- and thus the yield -- is identical to the cold path. */
    if (usewarm)
        CKTsetWarmStart(1);
    for (int i = 0; i < nsamp; i++) {
        ft_optimizing = TRUE;
        if (fast_mc)
            sw_fp_apply(NULL, NULL, 0);   /* re-draw + push in place, no reset */
        else
            sw_run_cmd("reset");
        sw_run_cmd(analysis);
        int pass = 1;
        for (s = 0; s < nspec; s++) {
            double m = sw_eval_expr(metric[s]);
            if ((hasmax[s] && m > hi[s]) || (hasmin[s] && m < lo[s])) {
                pass = 0;
                specfail[s]++;
            }
        }
        if (pass) npass++;
    }
    if (usewarm)
        CKTsetWarmStart(0);
    ft_optimizing = save_optimizing;
    if (fast_mc)
        sw_fp_free();                     /* Enhancement-346: drop the binds */
    if (uselhs)
        mc_sss_off();

    /* yield and a Wilson 95% score interval for the pass proportion */
    double p = (double) npass / (double) nsamp;
    const double z = 1.959964, z2 = z * z;
    double denom = 1.0 + z2 / nsamp;
    double center = (p + z2 / (2.0 * nsamp)) / denom;
    double half = z * sqrt(p * (1.0 - p) / nsamp + z2 / (4.0 * nsamp * nsamp)) / denom;

    fprintf(cp_out, "\n  yield  : %.3f%%  (%ld / %d pass)\n"
                    "  95%% CI : [%.3f%%, %.3f%%]  (Wilson score)\n",
            100.0 * p, npass, nsamp,
            100.0 * (center - half), 100.0 * (center + half));
    for (s = 0; s < nspec; s++)
        fprintf(cp_out, "  spec %d (%s): %ld violation%s\n",
                s + 1, metric[s], specfail[s], specfail[s] == 1 ? "" : "s");

    hs_set_result("montecarlo_yield", p);
    hs_set_result("montecarlo_npass", (double) npass);
    hs_set_result("montecarlo_n", (double) nsamp);
}


/* ------------------------------------------------------------------------
 * Enhancement-305: worst-case distance / most-probable-failure-point.
 *
 * `highsigma` (Enhancement-150) estimates a rare-event probability by inflating
 * every Gaussian sigma and reweighting -- direction-free, and robust for an
 * arbitrary failure condition, but it spends its samples in every direction at
 * once. The industry-standard complement works in *standardised normal space*
 * (each statistical parameter mapped to N(0,1)) and asks a geometric question
 * instead: which point of the failure region is the most probable one?
 *
 * With the performance margin written as g(u) > 0 for pass, that point is the
 * one on the boundary g(u) = 0 closest to the origin. Its distance
 *
 *     beta = min |u|   subject to   g(u) = 0
 *
 * is the WORST-CASE DISTANCE, and because the density is spherically symmetric
 * the first-order (FORM) failure probability is simply
 *
 *     P_fail ~= Phi(-beta)
 *
 * exactly the sigma number a designer quotes. The search is the classical
 * Hasofer-Lind / Rackwitz-Fiessler iteration
 *
 *     u_{k+1} = [ (grad_g . u_k - g(u_k)) / |grad_g|^2 ] grad_g
 *
 * whose cost is bounded -- a handful of iterations, each of D+1 simulations for
 * the finite-difference gradient -- rather than the 1e7..1e9 samples plain Monte
 * Carlo would need to SEE a 5-6 sigma event.
 *
 * FORM is exact when g is linear in u (the boundary is then a hyperplane and
 * beta is its distance from the origin) and approximate when it curves. So the
 * command can optionally refine it with MEAN-SHIFT importance sampling centred
 * on the MPFP: sampling N(u*, I) and carrying the likelihood ratio gives an
 * unbiased estimate whose variance is small precisely because the samples land
 * where the failures are.
 * ------------------------------------------------------------------------ */

#define WCD_MAXDIM 256

/* Evaluate the deck at u and return the margin g(u): positive = pass. */
static double wcd_margin(const double *u, int ndim, const char *analysis,
                         const char *metric, double hi, double lo,
                         int hasmax, int hasmin)
{
    double m, g;
    mc_wcd_config(u, ndim);
    sw_run_cmd("reset");            /* redraws the .params at this u */
    sw_run_cmd(analysis);
    m = sw_eval_expr(metric);
    /* Distance to the nearest spec violation, in metric units. With both a max
     * and a min the pass band is an interval and the margin is the smaller of
     * the two distances. */
    if (hasmax && hasmin)
        g = (hi - m < m - lo) ? (hi - m) : (m - lo);
    else if (hasmax)
        g = hi - m;
    else
        g = m - lo;
    return g;
}

void com_wcd(wordlist *wl)
{
    char analysis[512] = "op";
    char metric[1024] = "";
    double hi = 0.0, lo = 0.0;
    int have_metric = 0, hasmax = 0, hasmin = 0;
    int maxiter = 20, nis = 0;
    double tol = 1e-4, step = 1e-3;
    unsigned seed = 1;
    int save_optimizing = ft_optimizing;
    double u[WCD_MAXDIM], grad[WCD_MAXDIM], unew[WCD_MAXDIM];
    int ndim = 0, it, d, converged = 0;
    double g0, beta = 0.0, pf_form;

    if (wl == NULL || wl->wl_word == NULL) {
        fprintf(cp_err, "Usage: wcd -metric <expr> [-max <hi>] [-min <lo>] "
                        "[-analysis <cmd>] [-maxiter <n>] [-tol <t>] [-step <h>] "
                        "[-is <N> [-seed <s>]]\n");
        return;
    }

    while (wl) {
        const char *w = wl->wl_word;
        if (eq(w, "-metric") || eq(w, "-spec")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -metric needs an expression\n"); return; }
            wl = wl->wl_next;
            strncpy(metric, wl->wl_word, sizeof(metric) - 1);
            metric[sizeof(metric) - 1] = '\0';
            have_metric = 1; wl = wl->wl_next;
        } else if (eq(w, "-max")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -max needs a value\n"); return; }
            wl = wl->wl_next; hi = sw_num(wl->wl_word); hasmax = 1; wl = wl->wl_next;
        } else if (eq(w, "-min")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -min needs a value\n"); return; }
            wl = wl->wl_next; lo = sw_num(wl->wl_word); hasmin = 1; wl = wl->wl_next;
        } else if (eq(w, "-analysis")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -analysis needs a command\n"); return; }
            /* the same multi-token collection its siblings use. This copied ONE
             * token, so `-analysis tran 1n 20n` kept `tran` and then rejected
             * `1n` as an unknown option -- wcd alone required quoting. */
            analysis[0] = '\0';
            wl = wl->wl_next;
            while (wl && wl->wl_word && !is_flag(wl->wl_word)) {
                char *tok = cp_unquote(wl->wl_word);
                /* Enhancement-434: refuse rather than truncate. `analysis` is a
                 * fixed 512-byte buffer and strncat simply stopped at the end,
                 * so a longer command lost its tail SILENTLY and a DIFFERENT
                 * command ran. sweep/optimize build the same string with
                 * tprintf and have no limit; these three could not, so they at
                 * least have to say so. */
                if (strlen(analysis) + strlen(tok) + 2 > sizeof(analysis)) {
                    fprintf(cp_err, "%s: -analysis command is too long "
                                    "(limit %d characters)\n",
                            "wcd", (int) sizeof(analysis) - 1);
                    tfree(tok);
                    return;
                }
                if (analysis[0]) strncat(analysis, " ", sizeof(analysis) - strlen(analysis) - 1);
                strncat(analysis, tok, sizeof(analysis) - strlen(analysis) - 1);
                tfree(tok);
                wl = wl->wl_next;
            }
        } else if (eq(w, "-maxiter")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -maxiter needs a value\n"); return; }
            wl = wl->wl_next; maxiter = atoi(wl->wl_word); wl = wl->wl_next;
        } else if (eq(w, "-tol")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -tol needs a value\n"); return; }
            wl = wl->wl_next; tol = sw_num(wl->wl_word); wl = wl->wl_next;
        } else if (eq(w, "-step")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -step needs a value\n"); return; }
            wl = wl->wl_next; step = sw_num(wl->wl_word); wl = wl->wl_next;
        } else if (eq(w, "-is")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -is needs a sample count\n"); return; }
            wl = wl->wl_next; nis = atoi(wl->wl_word); wl = wl->wl_next;
        } else if (eq(w, "-seed")) {
            if (!wl->wl_next) { fprintf(cp_err, "wcd: -seed needs a value\n"); return; }
            wl = wl->wl_next; seed = (unsigned) strtoul(wl->wl_word, NULL, 10); wl = wl->wl_next;
        } else {
            fprintf(cp_err, "wcd: unknown option '%s'\n", w);
            return;
        }
    }

    if (!have_metric) {
        fprintf(cp_err, "wcd: a '-metric <expr>' is required\n");
        return;
    }
    if (!hasmax && !hasmin) {
        fprintf(cp_err, "wcd: give a spec limit -- '-max <hi>' and/or '-min <lo>' "
                        "(the failure region)\n");
        return;
    }
    if (maxiter < 1 || maxiter > 1000) {
        fprintf(cp_err, "wcd: -maxiter must be in [1, 1000]\n");
        return;
    }
    if (!(step > 0.0)) {
        fprintf(cp_err, "wcd: -step must be > 0\n");
        return;
    }
    if (ft_curckt == NULL || ft_curckt->ci_ckt == NULL) {
        fprintf(cp_err, "wcd: no circuit loaded\n");
        return;
    }

    ft_optimizing = TRUE;

    /* --- the nominal point, which also discovers the dimensionality --------
     * How many Gaussian .params a deck draws is not known until it has been
     * evaluated once, so evaluate at u = 0 and ask how many draws were used. */
    for (d = 0; d < WCD_MAXDIM; d++)
        u[d] = 0.0;
    g0 = wcd_margin(u, WCD_MAXDIM, analysis, metric, hi, lo, hasmax, hasmin);
    ndim = mc_wcd_ndim();

    if (ndim < 1) {
        fprintf(cp_err, "wcd: the deck draws no Gaussian .params -- nothing to "
                        "search over (use agauss/gauss in a .param)\n");
        ft_optimizing = save_optimizing;
        mc_wcd_off();
        return;
    }
    if (ndim > WCD_MAXDIM) {
        fprintf(cp_err, "wcd: %d statistical dimensions exceeds the limit of %d\n",
                ndim, WCD_MAXDIM);
        ft_optimizing = save_optimizing;
        mc_wcd_off();
        return;
    }

    fprintf(cp_out, "wcd: %d statistical dimension%s, analysis '%s', "
                    "fail if (%s) %s\n",
            ndim, ndim == 1 ? "" : "s", analysis, metric,
            hasmax && hasmin ? "outside [min,max]" : hasmax ? "> max" : "< min");
    fprintf(cp_out, "  nominal margin g(0) = %+.6g  (%s at nominal)\n",
            g0, g0 > 0.0 ? "passes" : "FAILS");

    if (g0 <= 0.0)
        fprintf(cp_out, "  note: the nominal point already violates the spec, so the\n"
                        "        worst-case distance is reported as a NEGATIVE margin.\n");

    /* --- Hasofer-Lind / Rackwitz-Fiessler iteration ---------------------- */
    for (it = 0; it < maxiter; it++) {
        double g = wcd_margin(u, ndim, analysis, metric, hi, lo, hasmax, hasmin);
        double gn2 = 0.0, gdotu = 0.0, dnorm = 0.0, unorm = 0.0;

        /* forward-difference gradient: D extra evaluations */
        for (d = 0; d < ndim; d++) {
            double save = u[d], gp;
            u[d] = save + step;
            gp = wcd_margin(u, ndim, analysis, metric, hi, lo, hasmax, hasmin);
            u[d] = save;
            grad[d] = (gp - g) / step;
            gn2 += grad[d] * grad[d];
            gdotu += grad[d] * save;
        }

        if (gn2 <= 0.0) {
            fprintf(cp_err, "wcd: the metric does not respond to any statistical "
                            "parameter (zero gradient) -- cannot locate an MPFP\n");
            ft_optimizing = save_optimizing;
            mc_wcd_off();
            return;
        }

        {
            double c = (gdotu - g) / gn2;
            for (d = 0; d < ndim; d++) {
                unew[d] = c * grad[d];
                dnorm += (unew[d] - u[d]) * (unew[d] - u[d]);
                unorm += unew[d] * unew[d];
            }
        }
        dnorm = sqrt(dnorm);
        for (d = 0; d < ndim; d++)
            u[d] = unew[d];
        beta = sqrt(unorm);

        if (dnorm < tol) {
            converged = 1;
            break;
        }
    }

    if (!converged)
        fprintf(cp_out, "  warning: MPFP search did not converge in %d iterations "
                        "(last step %.3g); beta below is provisional\n", maxiter, tol);

    /* Sign: beta is a distance, but if nominal already fails the failure region
     * contains the origin and the "distance to failure" is negative. */
    if (g0 <= 0.0)
        beta = -beta;
    pf_form = 0.5 * erfc(beta / sqrt(2.0));      /* Phi(-beta) */

    fprintf(cp_out, "\n  worst-case distance : beta = %.4f sigma%s\n"
                    "  P(fail), first-order: %.6e   (= Phi(-beta))\n",
            beta, converged ? "" : "  [not converged]", pf_form);
    fprintf(cp_out, "  MPFP (standardised normal coordinates):\n   ");
    for (d = 0; d < ndim; d++)
        fprintf(cp_out, " u%d=%+.4f", d, u[d]);
    fprintf(cp_out, "\n");

    hs_set_result("wcd_beta", beta);
    hs_set_result("wcd_pfail", pf_form);
    hs_set_result("wcd_ndim", (double) ndim);
    hs_set_result("wcd_converged", (double) converged);

    /* --- optional mean-shift importance sampling around the MPFP ---------- */
    if (nis > 1) {
        double sum_wf = 0.0, sum_w2f2 = 0.0;
        long nfail = 0;
        int i;

        fprintf(cp_out, "\n  refining with %d mean-shift importance samples "
                        "centred on the MPFP...\n", nis);
        mc_wcd_shift(u, ndim, seed);
        for (i = 0; i < nis; i++) {
            double m, f = 0.0, w;
            sw_run_cmd("reset");
            sw_run_cmd(analysis);
            m = sw_eval_expr(metric);
            if ((hasmax && m > hi) || (hasmin && m < lo))
                f = 1.0;
            w = mc_sample_weight();
            if (f != 0.0) {
                nfail++;
                sum_wf += w;
                sum_w2f2 += w * w;
            }
        }
        {
            double pf = sum_wf / (double) nis;
            double var = sum_w2f2 / (double) nis - pf * pf;
            double se = (var > 0.0) ? sqrt(var / (double) nis) : 0.0;
            double rel = (pf > 0.0) ? se / pf : 0.0;
            double sig = (pf > 0.0 && pf < 1.0) ? -inv_normal_cdf(pf) : 0.0;
            fprintf(cp_out,
                    "  failures seen       : %ld / %d (in the shifted sampling)\n"
                    "  P(fail), mean-shift : %.6e  +/- %.2e  (relative error %.1f%%)\n"
                    "  equivalent sigma    : %.3f\n",
                    nfail, nis, pf, se, 100.0 * rel, sig);
            hs_set_result("wcd_pfail_is", pf);
            hs_set_result("wcd_pfail_is_err", se);
            hs_set_result("wcd_sigma_is", sig);
        }
    }

    mc_wcd_off();
    ft_optimizing = save_optimizing;
}
