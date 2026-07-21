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
plot named `sweep`, with the knob values as the scale, so `plot <output>` shows the
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
 * (magnitude if complex), or 0 on failure */
static double sw_eval_expr(const char *expr)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    double f = 0.0;
    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1) {
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
        /* Enhancement-268: `@*[param]` is the wildcard model-parameter knob --
         * applied in place via `altermod @*[param]=` (no deck re-source), which
         * sets `param` on every loaded model that has it. */
        if (mod[0] == '*' && mod[1] == '\0')
            return SW_MODEL;
        if (*mod && ft_curckt && ft_curckt->ci_ckt &&
            ft_sim->findModel(ft_curckt->ci_ckt, (IFuid) mod))
            return SW_MODEL;
        return SW_ALTER;
    } else {
        int found = 0;
        (void) nupa_get_param(name, &found);
        return found ? SW_DECK : SW_ALTER;
    }
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


/* collect tokens up to the next flag, joined with single spaces */
static char *collect_until_flag(wordlist **pwl)
{
    char *acc = NULL;
    wordlist *wl = *pwl;
    while (wl && !is_flag(wl->wl_word)) {
        if (!acc) {
            acc = copy(wl->wl_word);
        } else {
            char *j = tprintf("%s %s", acc, wl->wl_word);
            tfree(acc);
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
        int n; double f0, f1;
        if (!a || !b || !c) {
            fprintf(cp_err, "sweep: %s needs <N> <start> <stop>\n", wl->wl_word);
            return 0;
        }
        n = atoi(a->wl_word); f0 = sw_num(b->wl_word); f1 = sw_num(c->wl_word);
        wl = c->wl_next;
        if (n < 1) n = 1;
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
            for (x = f0; x <= f1 * (1 + 1e-9) && nv < SW_MAXPTS; x *= mul) nv++;
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
        double f0, f1, st; int cnt;
        if (!a || !b || !c) {
            fprintf(cp_err, "sweep: need <start> <stop> <step> after the knob\n");
            return 0;
        }
        f0 = sw_num(a->wl_word); f1 = sw_num(b->wl_word); st = sw_num(c->wl_word);
        wl = c->wl_next;
        if (st == 0.0) { fprintf(cp_err, "sweep: step must be non-zero\n"); return 0; }
        if ((f1 - f0) * st < 0.0) st = -st;          /* fix an obvious sign slip */
        cnt = (int) floor((f1 - f0) / st + 1e-9) + 1;
        if (cnt < 1) cnt = 1;
        if (cnt > SW_MAXPTS) cnt = SW_MAXPTS;
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


/* Guards against re-entrancy: a `.param` knob re-sources the deck (`reset`),
 * which re-runs a `.sweep` card -- that nested invocation must be a no-op or the
 * sweep would recurse forever. */
static int sweep_active = 0;

void com_sweep(wordlist *wl)
{
    char *analysis = NULL, *scname = NULL;
    char *outname[SW_MAXOUT], *outexpr[SW_MAXOUT];
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

    for (j = 0; j < SW_MAXKNOB; j++) {
        kname[j] = NULL; kvals[j] = NULL; kscname[j] = NULL;
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
            if (wl->wl_next && nout < SW_MAXOUT) {
                /* accept `name=expr` (clean vector name) or a bare `expr` */
                char *tok = wl->wl_next->wl_word, *eqp = strchr(tok, '=');
                if (eqp && eqp != tok) {
                    /* explicit name=expr: use the given name verbatim, no bus expansion */
                    outname[nout] = copy(tok);
                    outname[nout][eqp - tok] = '\0';
                    outexpr[nout] = copy(eqp + 1);
                    nout++;
                } else {
                    /* bare token: expand a bus range `base[lo:hi]`, else add as-is */
                    sw_add_bare_output(outname, outexpr, &nout, tok);
                }
                wl = wl->wl_next->wl_next;
            } else {
                wl = wl->wl_next ? wl->wl_next->wl_next : NULL;
            }
        } else {
            fprintf(cp_err, "sweep: unrecognized token '%s'\n", w);
            wl = wl->wl_next;
        }
    }
    if (!analysis)
        analysis = copy("op");

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
                kname[0], kkind[0] == SW_MODEL ? "model param" :
                kkind[0] == SW_DECK ? ".param" : "instance/device",
                nv0, nv0 == 1 ? "" : "s", analysis);
    else {
        fprintf(cp_out, "sweep: %s over %d point%s", kname[0], nv0,
                nv0 == 1 ? "" : "s");
        for (j = 1; j < nknob; j++)
            fprintf(cp_out, " x %s(%d)", kname[j], knv[j]);
        fprintf(cp_out, " = %d runs -> %d curve%s per output, analysis '%s'\n",
                npt, ncomb, ncomb == 1 ? "" : "s", analysis);
    }

    /* --- run the sweep over the cartesian product (inner knob varies fastest,
     * so point p = outer_combo * nv0 + inner_index) --- */
    sweep_active = 1;                                /* block re-source recursion */
    ft_optimizing = TRUE;                            /* silence per-point chatter */
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
        if (resetNeeded && anyDeck) {                /* re-source once for the point */
            for (j = 0; j < nknob; j++)
                if (kkind[j] == SW_DECK) sw_set_deck(kname[j], curval[j]);
            sw_run_cmd("reset");
            ft_optimizing = TRUE;                    /* reset clears it */
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
            } else {
                data[(size_t) p * (size_t) nout + (size_t) k] = sw_eval_expr(outexpr[k]);
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
        sc = dvec_alloc(copy(scname), SV_NOTYPE,
                        (short) (VF_REAL | VF_PERMANENT), nv0, NULL);
        for (i = 0; i < nv0; i++) sc->v_realdata[i] = kvals[0][i];
        vec_new(sc);                                 /* first permanent -> scale */
        for (k = 0; k < nout; k++)
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
    if (nknob == 1)
        fprintf(cp_out, "sweep: %d points into the 'sweep' plot%s; "
                        "`plot <output>` to view vs %s.\n",
                nv0, overlay ? "" : " (now current)", scname);
    else
        fprintf(cp_out, "sweep: %d curve%s x %d output%s into the 'sweep' plot%s; "
                        "`plot <output>_...` to view the family vs %s.\n",
                ncomb, ncomb == 1 ? "" : "s", nout, nout == 1 ? "" : "s",
                overlay ? "" : " (now current)", scname);

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
    sweep_active = 0;
    ft_optimizing = save_optimizing;
    for (k = 0; k < nout; k++) { tfree(outname[k]); tfree(outexpr[k]); }
    if (ovx) for (p = 0; p < npt; p++) tfree(ovx[p]);
    if (ovy) for (p = 0; p < npt * nout; p++) tfree(ovy[p]);
    tfree(ovx); tfree(ovy); tfree(ovlen); tfree(scwavename);
    for (j = 0; j < SW_MAXKNOB; j++) {
        tfree(kname[j]); tfree(kvals[j]); tfree(kscname[j]);
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
            analysis[0] = '\0';
            wl = wl->wl_next;
            while (wl && wl->wl_word && wl->wl_word[0] != '-') {
                if (analysis[0]) strncat(analysis, " ", sizeof(analysis) - strlen(analysis) - 1);
                strncat(analysis, wl->wl_word, sizeof(analysis) - strlen(analysis) - 1);
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
            analysis[0] = '\0';
            wl = wl->wl_next;
            while (wl && wl->wl_word && wl->wl_word[0] != '-') {
                if (analysis[0]) strncat(analysis, " ", sizeof(analysis) - strlen(analysis) - 1);
                strncat(analysis, wl->wl_word, sizeof(analysis) - strlen(analysis) - 1);
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

    long npass = 0;
    ft_optimizing = TRUE;
    /* Enhancement-188: warm-start each sample's DC bias point from the previous
     * converged solution (opt-in). Only the iteration count changes; the
     * converged point -- and thus the yield -- is identical to the cold path. */
    if (usewarm)
        CKTsetWarmStart(1);
    for (int i = 0; i < nsamp; i++) {
        ft_optimizing = TRUE;
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
