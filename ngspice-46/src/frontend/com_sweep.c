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

  sweep <knob> <start> <stop> <step>            [-analysis <cmd>] [-output <expr> ...]
  sweep <knob> lin|dec|oct <N> <start> <stop>   [-analysis <cmd>] [-output <expr> ...]
  sweep <knob> list <v1> <v2> ...               [-analysis <cmd>] [-output <expr> ...]

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
#include "com_sweep.h"

#define SW_ALTER   0             /* alter     -- device / instance / source      */
#define SW_MODEL   1             /* altermod  -- .model-card parameter            */
#define SW_DECK    2             /* alterparam + reset -- symbolic `.param`       */
#define SW_MAXOUT  256           /* max recorded output vectors                   */
#define SW_MAXPTS  100000        /* sanity cap on sweep points                    */


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


/* Set the knob to `val` with the appropriate command. */
static void sw_set(int kind, const char *name, double val)
{
    char cmd[512];
    if (kind == SW_DECK) {
        (void) snprintf(cmd, sizeof cmd, "alterparam %s=%.10g", name, val);
        sw_run_cmd(cmd);
        sw_run_cmd("reset");
        return;
    }
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


/* Guards against re-entrancy: a `.param` knob re-sources the deck (`reset`),
 * which re-runs a `.sweep` card -- that nested invocation must be a no-op or the
 * sweep would recurse forever. */
static int sweep_active = 0;

void com_sweep(wordlist *wl)
{
    char *knob = NULL, *analysis = NULL, *scname = NULL;
    char *outname[SW_MAXOUT], *outexpr[SW_MAXOUT];
    double *vals = NULL, *data = NULL;
    int kind, nout = 0, nv = 0, i, k;
    int save_optimizing = ft_optimizing;

    if (sweep_active)                /* re-entered via a .param re-source */
        return;
    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "sweep: no circuit loaded\n");
        return;
    }
    if (!wl || !wl->wl_word) {
        fprintf(cp_err, "usage: sweep <knob> (<start> <stop> <step> | "
                        "lin|dec|oct <N> <start> <stop> | list <v> ...) "
                        "[-analysis <cmd>] [-output <expr> ...]\n");
        return;
    }

    knob = copy(wl->wl_word);
    wl = wl->wl_next;

    /* --- sweep specification --- */
    if (wl && (eq(wl->wl_word, "lin") || eq(wl->wl_word, "dec") ||
               eq(wl->wl_word, "oct"))) {
        int mode = eq(wl->wl_word, "dec") ? 1 : eq(wl->wl_word, "oct") ? 2 : 0;
        wordlist *a = wl->wl_next, *b = a ? a->wl_next : NULL, *c = b ? b->wl_next : NULL;
        int n; double f0, f1;
        if (!a || !b || !c) {
            fprintf(cp_err, "sweep: %s needs <N> <start> <stop>\n", wl->wl_word);
            goto cleanup;
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
                goto cleanup;
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
        if (nv < 1) { fprintf(cp_err, "sweep: list needs values\n"); goto cleanup; }
        vals = TMALLOC(double, nv);
        for (i = 0; i < nv; i++) { vals[i] = sw_num(wl->wl_word); wl = wl->wl_next; }
    } else {                                         /* start stop step */
        wordlist *a = wl, *b = a ? a->wl_next : NULL, *c = b ? b->wl_next : NULL;
        double f0, f1, st; int cnt;
        if (!a || !b || !c) {
            fprintf(cp_err, "sweep: need <start> <stop> <step> after the knob\n");
            goto cleanup;
        }
        f0 = sw_num(a->wl_word); f1 = sw_num(b->wl_word); st = sw_num(c->wl_word);
        wl = c->wl_next;
        if (st == 0.0) { fprintf(cp_err, "sweep: step must be non-zero\n"); goto cleanup; }
        if ((f1 - f0) * st < 0.0) st = -st;          /* fix an obvious sign slip */
        cnt = (int) floor((f1 - f0) / st + 1e-9) + 1;
        if (cnt < 1) cnt = 1;
        if (cnt > SW_MAXPTS) cnt = SW_MAXPTS;
        nv = cnt;
        vals = TMALLOC(double, nv);
        for (i = 0; i < nv; i++) vals[i] = f0 + st * i;
    }

    /* --- options: -analysis / -output --- */
    while (wl) {
        const char *w = wl->wl_word;
        if (eq(w, "-analysis") || eq(w, "-a")) {
            wl = wl->wl_next;
            tfree(analysis);
            analysis = collect_until_flag(&wl);
        } else if (eq(w, "-output") || eq(w, "-o")) {
            if (wl->wl_next && nout < SW_MAXOUT) {
                /* accept `name=expr` (clean vector name) or a bare `expr` */
                char *tok = wl->wl_next->wl_word, *eqp = strchr(tok, '=');
                if (eqp && eqp != tok) {
                    outname[nout] = copy(tok);
                    outname[nout][eqp - tok] = '\0';
                    outexpr[nout] = copy(eqp + 1);
                } else {
                    outname[nout] = copy(tok);
                    outexpr[nout] = copy(tok);
                }
                nout++;
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

    kind = sw_kind(knob);
    fprintf(cp_out, "sweep: %s (%s) over %d point%s, analysis '%s'\n", knob,
            kind == SW_MODEL ? "model param" : kind == SW_DECK ? ".param" :
            "instance/device", nv, nv == 1 ? "" : "s", analysis);

    /* --- run the sweep --- */
    sweep_active = 1;                                /* block re-source recursion */
    ft_optimizing = TRUE;                            /* silence per-point chatter */
    for (i = 0; i < nv; i++) {
        sw_set(kind, knob, vals[i]);
        if (kind == SW_DECK)
            ft_optimizing = TRUE;                    /* reset may clear it */
        sw_run_cmd(analysis);

        if (i == 0 && nout == 0) {
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
        if (i == 0)
            data = TMALLOC(double, (size_t) nv * (size_t) nout);
        for (k = 0; k < nout; k++)
            data[(size_t) i * (size_t) nout + (size_t) k] = sw_eval_expr(outexpr[k]);
    }
    ft_optimizing = save_optimizing;

    /* --- emit the summary plot (knob values as the scale) --- */
    {
        struct plot *pl = plot_alloc("sweep");
        struct dvec *sc;
        scname = sw_scalename(knob);
        pl->pl_name = copy("Sweep");
        pl->pl_title = copy(knob);
        plot_new(pl);
        plot_setcur(pl->pl_typename);
        sc = dvec_alloc(copy(scname), SV_NOTYPE,
                        (short) (VF_REAL | VF_PERMANENT), nv, NULL);
        for (i = 0; i < nv; i++) sc->v_realdata[i] = vals[i];
        vec_new(sc);                                 /* first permanent -> scale */
        for (k = 0; k < nout; k++) {
            struct dvec *v = dvec_alloc(copy(outname[k]), SV_NOTYPE,
                                        (short) (VF_REAL | VF_PERMANENT), nv, NULL);
            for (i = 0; i < nv; i++)
                v->v_realdata[i] = data[(size_t) i * (size_t) nout + (size_t) k];
            vec_new(v);
        }
    }
    fprintf(cp_out, "sweep: %d points into plot '%s' (now current); "
                    "`plot <output>` to view vs %s.\n", nv, "sweep", scname);

cleanup:
    sweep_active = 0;
    ft_optimizing = save_optimizing;
    for (k = 0; k < nout; k++) { tfree(outname[k]); tfree(outexpr[k]); }
    tfree(knob); tfree(analysis); tfree(scname);
    tfree(vals); tfree(data);
}
