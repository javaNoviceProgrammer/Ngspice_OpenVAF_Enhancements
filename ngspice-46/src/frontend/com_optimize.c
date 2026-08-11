/**********
Enhancement-130 / Enhancement-143: a built-in parameter optimizer.

`optimize` varies a set of circuit/device parameters, re-runs one or more
user-chosen analyses, and drives a user-supplied objective to a minimum. Two
modes are supported:

  * Scalar mode (-minimize <expr>): minimize a single scalar expression with a
    derivative-free Nelder-Mead downhill simplex (Enhancement-130).

  * Least-squares mode (one or more -target <expr> <value> [<weight>]): fit the
    circuit to a set of target measurements by minimizing the weighted sum of
    squared residuals  Sum_i [ w_i*(expr_i - value_i) ]^2 . Smooth problems --
    curve fitting, device-parameter extraction -- converge much faster with the
    gradient-based Levenberg-Marquardt method (finite-difference Jacobian), which
    is the default here; -method nm forces Nelder-Mead on the summed cost
    (Enhancement-143).

Targets may be spread over several analyses: each -analysis opens a new "stage",
and every -target that follows it is evaluated on that stage's results, so a
single objective can combine (say) a DC operating point and an AC response
(Enhancement-143 multi-analysis objectives).

The search runs in normalized [0,1] parameter space (so it is scale-invariant
across parameters that span orders of magnitude).

Two GLOBAL, population-based, derivative-free methods explore the whole parameter
box (rather than settling into whichever basin the start point sits in like the
local simplex), so they are the right tools for MULTIMODAL / rugged objectives
with several local minima:

  * -method pso (Enhancement-194): particle swarm -- a swarm of trial points, each
    pulled toward its own and the swarm's best-seen point.
  * -method de (Enhancement-195): differential evolution -- trials are built from a
    scaled DIFFERENCE of random members (v = a + F*(b-c)) crossed with the target,
    which self-scales to the population spread; often more robust on rugged /
    discontinuous landscapes.
  * -method sa (Enhancement-196): simulated annealing -- a SINGLE walker that
    accepts an uphill move with probability exp(-Dcost/T), climbing out of local
    minima while the temperature T is high and settling as T is cooled to zero.
    It evaluates one candidate per step (no population), so it is the cheapest
    global method when each analysis is expensive.

All work for a scalar -minimize objective and -target least-squares. `-swarmsize
<N>` sets the pso/de population (default auto, ~10+4*np), `-seed <s>` makes a run
reproducible.

Syntax (in a .control block, after the circuit is loaded):

  optimize (-param|-mparam|-dparam) <name> <init> <lo> <hi>  [...]
           -analysis <command ...>
           ( -minimize <expression ...>
             | -target <expr> <value> [<weight>]  [-target ...]
               [ -analysis <command ...> -target ... ] )
           [-method nm|lm|pso|de|sa] [-swarmsize <N>] [-seed <s>]
           [-maxiter <N>] [-tol <T>] [-verbose]

Three knob kinds, all in-place except -dparam:
  -param  <name> -- an `alter` target: a device instance (e.g. R1, C1) or an
          instance parameter (e.g. @m1[w]); changed with `alter <name>=<value>`.
  -mparam <name> -- a `.model`-card parameter, named `@<model>[<param>]` (e.g.
          @dmod[is]); changed with `altermod <name>=<value>`. Also in place, no
          re-parse (a .model param is not `alter`-reachable, only `altermod`).
  -dparam <name> -- a symbolic netlist `.param` (e.g. `.param w=1u`); since those
          are expanded at parse time, changed with `alterparam <name>=<value>`
          then a `reset` that re-sources the deck (re-evaluating every `.param`
          and re-stamping device values) -- heavier, but the only way to tune a
          `.param`.
Deck params are applied and re-sourced first, then the in-place `alter` /
`altermod` params, so the kinds mix correctly. For every
candidate the optimizer applies the values, runs each -analysis command, and
evaluates the objective. `-analysis` and `-minimize` collect every following token up to the
next `-<letter>` flag, so multi-word commands/expressions need no quoting; a
-target expression is a single token (use the no-space forms `v(out)-v(in)`,
`mag(v(out))`, `v(out)[3]`). Each objective/target reads the LAST value of its
expression, so target a single point with a one-point analysis or a vector index.
Console chatter from the hundreds of inner analyses is suppressed (via
ft_optimizing) unless `-verbose`.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/wordlist.h"
#include "ngspice/fteext.h"
#include "ngspice/cpextern.h"
#include "ngspice/randnumb.h"    /* Enhancement-206: inner Monte-Carlo sampling */

#include "com_optimize.h"
#include "com_sweep.h"           /* Enhancement-322: shared .param fast-path engine */
#include "ngspice/cktdefs.h"     /* Enhancement-323: CKTcircuit->CKThead[] */
#include "ngspice/devdefs.h"     /* Enhancement-323: DEVices[] / DEVmaxnum   */
#include "ngspice/osdiitf.h"     /* Enhancement-323: osdi_devtype_is_osdi (call #ifdef OSDI) */

#define OPT_MAXP    128          /* max parameters to optimize (E-197)    */
#define OPT_MAXS      8          /* max analysis stages                   */
#define OPT_MAXT    128          /* max least-squares targets (E-197)     */
#define OPT_MAXSPEC  32          /* Enhancement-206: max yield specs      */
#define OPT_MAXOBJ    8          /* Enhancement-216: max NSGA-II objectives */
#define OPT_PENALTY  1e30        /* cost for a failed / non-finite eval   */

/* Enhancement-206 (design centering): one pass/fail spec for the inner Monte
 * Carlo, exactly like montecarlo's -spec: an expression bounded by -max/-min. */
struct opt_spec {
    char   metric[256];
    double hi, lo;
    int    hasmax, hasmin;
};

struct opt_target {
    char  *expr;                 /* expression to fit                     */
    double target;               /* desired value                         */
    double weight;               /* residual weight                       */
    int    stage;                /* which -analysis stage it belongs to   */
};

/* how a parameter is applied to the circuit */
#define OPT_ALTER      0         /* device/instance param, in place via `alter`   */
#define OPT_DECKPARAM  1         /* symbolic `.param`, via `alterparam` + re-source*/
#define OPT_MODELPARAM 2         /* .model card param, in place via `altermod`    */

struct optctx {
    int np;
    char *name[OPT_MAXP];
    int  kind[OPT_MAXP];         /* OPT_ALTER / OPT_DECKPARAM / OPT_MODELPARAM     */
    int  has_deckparam;          /* any OPT_DECKPARAM present -> a re-source per eval*/
    double lo[OPT_MAXP], hi[OPT_MAXP], x0[OPT_MAXP];

    int ns;                              /* number of analysis stages      */
    char *analysis[OPT_MAXS];

    int nt;                              /* number of least-squares targets*/
    struct opt_target tgt[OPT_MAXT];

    char *objective;                     /* scalar -minimize expr (or NULL)*/
    int method;                          /* 0 auto, 1 nelder-mead, 2 levmar, 3 pso*/
    int maxiter;
    double tol;
    int verbose;
    int nevals;
    int nfailed;                         /* Enhancement-438: evals whose analysis never solved */
    int swarmsize;                       /* Enhancement-194: PSO population (0=auto)*/
    unsigned long seed;                  /* Enhancement-194: PSO RNG seed          */

    /* Enhancement-206: design centering. When `center` is set the objective is
     * the parametric yield / worst-case Cpk from an inner Monte Carlo run of
     * `nsamples` samples at the candidate design point (the process variation is
     * in the deck's agauss/.param stmts, re-sampled by each inner reset). */
    int    center;
    int    nspec;
    struct opt_spec spec[OPT_MAXSPEC];
    int    nsamples;
    int    lhs;                          /* Latin-Hypercube inner sampling         */
    unsigned mcseed;                     /* inner MC seed                          */
    double last_yield;                   /* yield at the last centering eval       */
    double last_cpk;                     /* worst-case Cpk at the last eval        */

    /* Enhancement-216: multi-objective / Pareto optimization (NSGA-II). Instead of
     * one scalar cost, `nobj` competing objectives are traded off; the result is a
     * Pareto FRONT of non-dominated designs rather than a single optimum. Each
     * objective is a metric expression that is minimized, or maximized (negated to
     * a common minimization convention). Selected with `-method nsga2`. */
    int    nobj;
    char  *obj[OPT_MAXOBJ];
    int    obj_max[OPT_MAXOBJ];          /* 1 = maximize, 0 = minimize             */

    /* Enhancement-322: .param fast-path. When every OPT_DECKPARAM knob feeds only
     * addressable device/model values, each eval pushes the re-evaluated values
     * in place (shared sw_fp_* engine) instead of alterparam+reset -- no per-eval
     * re-source. Not used with -center (its reset re-samples process variation). */
    int    fp_armed;
    int    fp_idx[OPT_MAXP];             /* knob index of each deck-param fast slot */
    int    fp_n;
};


static double clamp01(double u)
{
    return u < 0.0 ? 0.0 : (u > 1.0 ? 1.0 : u);
}


/* Run one command SYNCHRONOUSLY by dispatching straight through the command
 * table. Unlike cp_evloop(), which (called re-entrantly) defers the command to
 * the outer interpreter loop -- so it would run after the optimizer returns, with
 * the quiet flag already cleared -- this executes it now, inside opt_eval. */
static void opt_run_cmd(const char *cmdstr)
{
    wordlist *wl = cp_lexer((char *) cmdstr);   /* tokenize on whitespace */
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
        fprintf(cp_err, "optimize: unknown command '%s'\n", wl->wl_word);
    wl_free(wl);
}


/* Enhancement-438: did the analysis just run actually solve?
 *
 * An optimizer that cannot tell a failed evaluation from a real one will walk
 * straight into the region where the model refuses its parameters, read the
 * previous point's plot back as if it were this point's answer, and then report
 * that it CONVERGED there. `optimize -param @n1[area] 1 -5 5` against a model
 * declaring `area from (0:inf)` did exactly that: 21 failed evaluations, no
 * mention of them, and a confident "converged" at area = 1.1e-15.
 *
 * runcoms.c already publishes the verdict in the `sim_status` shell variable. */
static int opt_run_failed(void)
{
    int st = 0;
    if (cp_getvar("sim_status", CP_NUM, &st, sizeof st))
        return st != 0;
    return 0;
}


/* parse a SPICE-style number (understands k / meg / u / n / p ... suffixes) */
static double optnum(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}


/* Evaluate one ngspice expression, returning the LAST value of the result vector
 * (its magnitude if complex), or OPT_PENALTY on a failed / non-finite eval. */
static double opt_eval_expr(const char *expr)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    double f = OPT_PENALTY;

    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1) {
            if (isreal(v))
                f = v->v_realdata[v->v_length - 1];
            else
                f = hypot(v->v_compdata[v->v_length - 1].cx_real,
                          v->v_compdata[v->v_length - 1].cx_imag);
            if (!finite(f))
                f = OPT_PENALTY;
        }
        /* garbage-collect the temporary vector ft_evaluate may have created
         * (mirrors com_let), so hundreds of evaluations do not leak */
        if (!pn->pn_value && v)
            vec_free(v);
        free_pnode(pn);
    }
    return f;
}


/* Publish a scalar result as a permanent nutmeg vector + a shell variable
 * (mirrors montecarlo's hs_set_result). Enhancement-206. */
static void dc_set_result(const char *name, double val)
{
    struct dvec *v;
    cp_vset(name, CP_REAL, &val);
    v = dvec_alloc(copy(name), SV_NOTYPE, VF_REAL | VF_PERMANENT, 1, NULL);
    if (v) { v->v_realdata[0] = val; vec_new(v); }
}

/* Apply the in-place design knobs (device/instance via `alter`, .model-card via
 * `altermod`) for the normalized point u. Factored out (Enhancement-206) so the
 * centering MC loop can re-apply them after each `reset` re-sources the deck. */
static void opt_apply_inplace(struct optctx *c, const double *u)
{
    char cmd[512];
    int k;
    for (k = 0; k < c->np; k++) {
        double val = c->lo[k] + clamp01(u[k]) * (c->hi[k] - c->lo[k]);
        if (c->kind[k] == OPT_ALTER)
            (void) snprintf(cmd, sizeof cmd, "alter %s=%.10g", c->name[k], val);
        else if (c->kind[k] == OPT_MODELPARAM)
            (void) snprintf(cmd, sizeof cmd, "altermod %s=%.10g", c->name[k], val);
        else
            continue;                    /* OPT_DECKPARAM handled by alterparam+reset */
        opt_run_cmd(cmd);
    }
}

/* Enhancement-206: the design-centering objective. The design point is already
 * applied (the deck .params were alterparam'd + re-sourced by the caller); here
 * we run an inner Monte Carlo of `nsamples` samples -- each `reset` re-samples
 * the deck's process variation (agauss/.param, and any mccorr correlations)
 * around the current design center -- evaluate every spec, and reduce to the
 * worst-case Cpk (the smooth objective the outer optimizer maximizes) plus the
 * pass-fraction yield (reported). Returns -min(Cpk) so that MINIMIZING the cost
 * MAXIMIZES the process capability -> centers the design. */
static double opt_eval_center(struct optctx *c, const double *u)
{
    double sum[OPT_MAXSPEC], sumsq[OPT_MAXSPEC];
    long npass = 0;
    int i, s;
    char cmd[64];

    for (s = 0; s < c->nspec; s++) { sum[s] = 0.0; sumsq[s] = 0.0; }

    if (c->lhs) {
        mc_lhs_config(c->nsamples, c->mcseed);
    } else {
        (void) snprintf(cmd, sizeof cmd, "setseed %u", c->mcseed);
        opt_run_cmd(cmd);
    }

    for (i = 0; i < c->nsamples; i++) {
        ft_optimizing = TRUE;            /* keep reset/analysis quiet (as montecarlo does) */
        opt_run_cmd("reset");            /* re-source: design center (persisted) + fresh process draw */
        ft_optimizing = TRUE;
        opt_apply_inplace(c, u);         /* reset wiped in-place alters -> re-apply the center */
        opt_run_cmd(c->analysis[0]);
        int pass = 1;
        for (s = 0; s < c->nspec; s++) {
            double m = opt_eval_expr(c->spec[s].metric);
            sum[s] += m; sumsq[s] += m * m;
            if ((c->spec[s].hasmax && m > c->spec[s].hi) ||
                (c->spec[s].hasmin && m < c->spec[s].lo))
                pass = 0;
        }
        if (pass) npass++;
    }
    if (c->lhs)
        mc_sss_off();

    double mincpk = 1e30;
    for (s = 0; s < c->nspec; s++) {
        double mu  = sum[s] / c->nsamples;
        double var = sumsq[s] / c->nsamples - mu * mu;
        double sig = var > 0.0 ? sqrt(var) : 0.0;
        double cpk;
        if (sig < 1e-300) {
            /* degenerate (no spread): Cpk is +/-large depending on whether the
             * mean is inside the window, so the optimizer still moves it in. */
            int within = (!c->spec[s].hasmax || mu <= c->spec[s].hi) &&
                         (!c->spec[s].hasmin || mu >= c->spec[s].lo);
            cpk = within ? 100.0 : -100.0;
        } else {
            double cu = c->spec[s].hasmax ? (c->spec[s].hi - mu) / (3.0 * sig) : 1e30;
            double cl = c->spec[s].hasmin ? (mu - c->spec[s].lo) / (3.0 * sig) : 1e30;
            cpk = cu < cl ? cu : cl;
        }
        if (cpk < mincpk) mincpk = cpk;
    }
    c->last_yield = (double) npass / (double) c->nsamples;
    c->last_cpk = mincpk;
    return -mincpk;
}

/* Evaluate at a normalized point u in [0,1]^np: alter each param in place, run
 * every analysis stage, and either evaluate the scalar objective or accumulate
 * the least-squares residuals. Returns the scalar cost (the objective value, or
 * the weighted sum of squared residuals). If resid != NULL (least-squares mode),
 * it is filled with the nt residuals. */
/* Enhancement-322: try to arm the .param fast-path for this optimization. Every
 * OPT_DECKPARAM knob must feed only in-place-able device/model values (sw_fp_build
 * captures + self-checks them); -center is excluded because its inner reset
 * re-samples process variation. Returns 1 if armed. */
/* Engage the fast path only when a reset is actually expensive. The in-place
 * apply has a fixed per-eval cost (numparam re-eval + dico ops) that is roughly
 * independent of circuit size, while a reset's cost grows with the deck. Below
 * the crossover a small deck re-parses faster than the fast path's overhead,
 * and -- because the in-place values differ from the reset path in the last few
 * digits (numparam string formatting) -- an extremely tight -tol could otherwise
 * send the two paths to different iteration counts. So on a small, cheap circuit
 * we keep the (already cheap) reset.
 *
 * The crossover is about reset COST, not device count: a resistor reset just
 * re-parses a line, but an OSDI (compiled Verilog-A) reset re-runs each
 * instance's setup/temperature callbacks and is ~30x costlier per device --
 * measured crossovers ~80 primitives vs ~3 OSDI instances. So we weight each
 * instance by its device kind and compare the weighted total to the primitive
 * threshold. */
#define OPT_FP_MIN_DEVICES 80
#define OPT_FP_OSDI_WEIGHT 30

static int opt_fp_arm(struct optctx *c)
{
    char *names[OPT_MAXP];
    int k, weighted = 0;
    CKTcircuit *ckt;

    c->fp_armed = 0;
    c->fp_n = 0;
    if (c->center || !c->has_deckparam || !ft_curckt || !ft_curckt->ci_ckt)
        return 0;

    /* weighted device count: OSDI instances cost ~OPT_FP_OSDI_WEIGHT resets */
    ckt = ft_curckt->ci_ckt;
    {
        int type;
        for (type = 0; type < DEVmaxnum; type++) {
            GENmodel *m;
            GENinstance *inst;
            int per = 1;
            if (!DEVices[type])
                continue;
#ifdef OSDI
            if (osdi_devtype_is_osdi(type))
                per = OPT_FP_OSDI_WEIGHT;
#endif
            for (m = ckt->CKThead[type]; m; m = m->GENnextModel)
                for (inst = m->GENinstances; inst; inst = inst->GENnextInstance)
                    weighted += per;
        }
    }
    if (weighted < OPT_FP_MIN_DEVICES)
        return 0;                            /* reset is cheaper than the fast path */

    for (k = 0; k < c->np; k++)
        if (c->kind[k] == OPT_DECKPARAM) {
            c->fp_idx[c->fp_n] = k;
            names[c->fp_n] = c->name[k];
            c->fp_n++;
        }
    if (c->fp_n == 0)
        return 0;
    c->fp_armed = sw_fp_build(names, c->fp_n);
    return c->fp_armed;
}

/* Enhancement-322: push the current deck-param values in place (no reset). */
static void opt_fp_apply(struct optctx *c, const double *u)
{
    char *names[OPT_MAXP];
    double vals[OPT_MAXP];
    int j;
    for (j = 0; j < c->fp_n; j++) {
        int k = c->fp_idx[j];
        names[j] = c->name[k];
        vals[j] = c->lo[k] + clamp01(u[k]) * (c->hi[k] - c->lo[k]);
    }
    sw_fp_apply(names, vals, c->fp_n);
}

static double opt_eval(struct optctx *c, const double *u, double *resid)
{
    int k, s, i;
    char cmd[512];
    double cost = 0.0;

    /* Silence the per-iteration console chatter (alter's re-setup banner, the
     * analysis banner, row count, reference-value progress) unless -verbose.
     * ft_optimizing gates those prints at their source -- the analyses write to
     * stdout directly, and docommand's cp_ioreset() would undo an external fd
     * redirect. `alter` changes the value in place (no re-source), so the flag
     * set here survives through to the analyses. */
    ft_optimizing = !c->verbose;

    /* Symbolic `.param`s can only be changed by editing the deck and re-parsing:
     * `alterparam name=val` rewrites the stored deck, then `reset` re-sources it
     * (re-evaluating every `.param` expression and re-stamping device values). We
     * apply all deck params first, re-source once, THEN apply the in-place `alter`
     * params -- because `reset` rebuilds the circuit from the deck and would wipe
     * an earlier in-place `alter`. Circuits with no `.param` knob skip this
     * entirely (unchanged fast path). */
    if (c->has_deckparam) {
        if (c->fp_armed) {                 /* Enhancement-322: in-place, no reset */
            opt_fp_apply(c, u);
        } else {
            for (k = 0; k < c->np; k++) {
                if (c->kind[k] != OPT_DECKPARAM)
                    continue;
                double val = c->lo[k] + clamp01(u[k]) * (c->hi[k] - c->lo[k]);
                (void) snprintf(cmd, sizeof cmd, "alterparam %s=%.10g",
                                c->name[k], val);
                opt_run_cmd(cmd);
            }
            opt_run_cmd("reset");
            ft_optimizing = !c->verbose;   /* re-assert: re-source cleared it */
        }
    }

    /* Apply the in-place params on the (possibly re-sourced) circuit: device /
     * instance params with `alter`, .model-card params with `altermod`. Both take
     * effect immediately without a re-parse, so they run after any `.param`
     * re-source above. */
    opt_apply_inplace(c, u);

    c->nevals++;

    if (c->center) {
        /* Enhancement-206: objective is the inner Monte-Carlo yield / Cpk. */
        cost = opt_eval_center(c, u);
    } else if (c->nt > 0) {
        /* least-squares: each stage's analysis, then its targets, evaluated
         * while that stage's plot is still current */
        for (s = 0; s < c->ns; s++) {
            opt_run_cmd(c->analysis[s]);
            if (opt_run_failed()) {         /* Enhancement-438 */
                c->nfailed++;
                cost = OPT_PENALTY;
                break;
            }
            for (i = 0; i < c->nt; i++) {
                if (c->tgt[i].stage != s)
                    continue;
                double val = opt_eval_expr(c->tgt[i].expr);
                double ri;
                if (val >= OPT_PENALTY)
                    ri = 1e15;                    /* bad eval -> push away  */
                else
                    ri = c->tgt[i].weight * (val - c->tgt[i].target);
                if (resid)
                    resid[i] = ri;
                cost += ri * ri;
            }
        }
    } else {
        /* scalar objective evaluated after the (single) analysis stage */
        opt_run_cmd(c->analysis[0]);
        if (opt_run_failed()) {
            /* Enhancement-438: no solution -> no objective. Penalise so the
             * search moves away, instead of scoring the previous point's plot. */
            c->nfailed++;
            cost = OPT_PENALTY;
        } else {
            cost = opt_eval_expr(c->objective);
        }
    }

    ft_optimizing = FALSE;
    return cost;
}


/* Solve the n-by-n dense system A x = b by Gaussian elimination with partial
 * pivoting. A (row-major) and b are overwritten. Returns 0 if singular. */
static int solve_lin(int n, double *A, double *b, double *x)
{
    int i, j, k;

    for (i = 0; i < n; i++) {
        int piv = i;
        double mx = fabs(A[i * n + i]);
        for (k = i + 1; k < n; k++) {
            double a = fabs(A[k * n + i]);
            if (a > mx) { mx = a; piv = k; }
        }
        if (mx < 1e-300)
            return 0;
        if (piv != i) {
            for (j = 0; j < n; j++) {
                double t = A[i * n + j]; A[i * n + j] = A[piv * n + j]; A[piv * n + j] = t;
            }
            double t = b[i]; b[i] = b[piv]; b[piv] = t;
        }
        for (k = i + 1; k < n; k++) {
            double f = A[k * n + i] / A[i * n + i];
            for (j = i; j < n; j++)
                A[k * n + j] -= f * A[i * n + j];
            b[k] -= f * b[i];
        }
    }
    for (i = n - 1; i >= 0; i--) {
        double spp = b[i];
        for (j = i + 1; j < n; j++)
            spp -= A[i * n + j] * x[j];
        x[i] = spp / A[i * n + i];
    }
    return 1;
}


/* Levenberg-Marquardt least-squares over the np normalized parameters. On entry
 * ubest holds the normalized start point; on exit it holds the best point and
 * *fbest the sum of squared residuals there. Jacobian by forward (or, near the
 * upper bound, backward) finite differences. */
static void levenberg_marquardt(struct optctx *c, double *ubest, double *fbest)
{
    const int n = c->np, m = c->nt;
    const double h = 1e-3;
    double u[OPT_MAXP], r0[OPT_MAXT], rj[OPT_MAXT];
    double J[OPT_MAXT][OPT_MAXP];
    double A[OPT_MAXP * OPT_MAXP], g[OPT_MAXP], delta[OPT_MAXP], unew[OPT_MAXP];
    double lambda = 1e-3, cost0;
    int i, j, k, iter;

    for (j = 0; j < n; j++)
        u[j] = clamp01(ubest[j]);
    cost0 = opt_eval(c, u, r0);

    for (iter = 0; iter < c->maxiter; iter++) {
        int accepted = 0;
        double dnorm = 0.0, costn = cost0;
        int tries;

        /* finite-difference Jacobian J[i][j] = d r_i / d u_j */
        for (j = 0; j < n; j++) {
            double uj[OPT_MAXP], sgn = 1.0;
            for (i = 0; i < n; i++) uj[i] = u[i];
            if (u[j] + h > 1.0) { uj[j] = u[j] - h; sgn = -1.0; }
            else                  uj[j] = u[j] + h;
            (void) opt_eval(c, uj, rj);
            for (i = 0; i < m; i++)
                J[i][j] = (rj[i] - r0[i]) / (sgn * h);
        }

        /* normal equations: A = J^T J, g = J^T r0 */
        for (i = 0; i < n; i++) {
            g[i] = 0.0;
            for (k = 0; k < m; k++) g[i] += J[k][i] * r0[k];
            for (j = 0; j < n; j++) {
                double s = 0.0;
                for (k = 0; k < m; k++) s += J[k][i] * J[k][j];
                A[i * n + j] = s;
            }
        }

        /* increase lambda until (A + lambda*diag(A)) delta = -g reduces cost */
        for (tries = 0; tries < 12 && !accepted; tries++) {
            double M[OPT_MAXP * OPT_MAXP], b[OPT_MAXP];
            for (i = 0; i < n; i++) {
                for (j = 0; j < n; j++) M[i * n + j] = A[i * n + j];
                double d = A[i * n + i];
                M[i * n + i] += lambda * (d > 1e-12 ? d : 1e-12) + 1e-12;
                b[i] = -g[i];
            }
            if (!solve_lin(n, M, b, delta)) { lambda *= 4.0; continue; }

            dnorm = 0.0;
            for (i = 0; i < n; i++) {
                unew[i] = clamp01(u[i] + delta[i]);
                dnorm += delta[i] * delta[i];
            }
            costn = opt_eval(c, unew, rj);
            if (costn < cost0) {
                for (i = 0; i < n; i++) u[i] = unew[i];
                for (i = 0; i < m; i++) r0[i] = rj[i];
                accepted = 1;
                lambda *= 0.3;
                if (lambda < 1e-12) lambda = 1e-12;
            } else {
                lambda *= 4.0;
            }
        }

        if (c->verbose)
            fprintf(cp_out, "  iter %-3d  cost %.6g  lambda %.2g  (%d evals)\n",
                    iter + 1, accepted ? costn : cost0, lambda, c->nevals);

        if (!accepted)
            break;                                /* cannot reduce further  */
        {
            double improve = cost0 - costn;
            cost0 = costn;
            if (improve <= c->tol * (cost0 + c->tol) || sqrt(dnorm) < c->tol)
                break;                            /* converged              */
        }
    }

    for (j = 0; j < n; j++)
        ubest[j] = u[j];
    *fbest = cost0;
}


/* Nelder-Mead downhill simplex over the np normalized parameters. On entry
 * ubest holds the normalized starting point; on exit it holds the best point
 * and *fbest its cost. In least-squares mode the cost is the summed square. */
static void nelder_mead(struct optctx *c, double *ubest, double *fbest)
{
    const double alpha = 1.0, gamma = 2.0, rho = 0.5, sigma = 0.5;
    const int n = c->np;
    double s[OPT_MAXP + 1][OPT_MAXP], fv[OPT_MAXP + 1];
    double cent[OPT_MAXP], xr[OPT_MAXP], xe[OPT_MAXP], xc[OPT_MAXP];
    int i, j, iter, lo;

    /* build the initial simplex: the start point plus one point per dimension
     * nudged by 0.1 in normalized space */
    for (j = 0; j < n; j++)
        s[0][j] = clamp01(ubest[j]);
    fv[0] = opt_eval(c, s[0], NULL);
    for (i = 1; i <= n; i++) {
        for (j = 0; j < n; j++)
            s[i][j] = s[0][j];
        double b = s[0][i - 1] + 0.1;
        if (b > 1.0)
            b = s[0][i - 1] - 0.1;
        s[i][i - 1] = clamp01(b);
        fv[i] = opt_eval(c, s[i], NULL);
    }

    for (iter = 0; iter < c->maxiter; iter++) {
        int hi, nh;
        double fr;

        lo = hi = 0;
        for (i = 1; i <= n; i++) {
            if (fv[i] < fv[lo]) lo = i;
            if (fv[i] > fv[hi]) hi = i;
        }
        nh = (hi == 0) ? 1 : 0;
        for (i = 0; i <= n; i++)
            if (i != hi && fv[i] > fv[nh]) nh = i;

        if (fv[hi] - fv[lo] <= c->tol * (fabs(fv[lo]) + c->tol))
            break;                               /* converged */

        for (j = 0; j < n; j++) {                /* centroid of all but worst */
            double sum = 0.0;
            for (i = 0; i <= n; i++)
                if (i != hi) sum += s[i][j];
            cent[j] = sum / n;
        }

        for (j = 0; j < n; j++)                  /* reflect */
            xr[j] = clamp01(cent[j] + alpha * (cent[j] - s[hi][j]));
        fr = opt_eval(c, xr, NULL);

        if (fr < fv[lo]) {                        /* expand */
            double fe;
            for (j = 0; j < n; j++)
                xe[j] = clamp01(cent[j] + gamma * (xr[j] - cent[j]));
            fe = opt_eval(c, xe, NULL);
            if (fe < fr) {
                for (j = 0; j < n; j++) s[hi][j] = xe[j];
                fv[hi] = fe;
            } else {
                for (j = 0; j < n; j++) s[hi][j] = xr[j];
                fv[hi] = fr;
            }
        } else if (fr < fv[nh]) {                 /* accept reflection */
            for (j = 0; j < n; j++) s[hi][j] = xr[j];
            fv[hi] = fr;
        } else {                                  /* contract */
            double fc;
            for (j = 0; j < n; j++)
                xc[j] = clamp01(cent[j] + rho * (s[hi][j] - cent[j]));
            fc = opt_eval(c, xc, NULL);
            if (fc < fv[hi]) {
                for (j = 0; j < n; j++) s[hi][j] = xc[j];
                fv[hi] = fc;
            } else {                              /* shrink toward the best */
                for (i = 0; i <= n; i++)
                    if (i != lo) {
                        for (j = 0; j < n; j++)
                            s[i][j] = clamp01(s[lo][j] + sigma * (s[i][j] - s[lo][j]));
                        fv[i] = opt_eval(c, s[i], NULL);
                    }
            }
        }
        if (c->verbose)
            fprintf(cp_out, "  iter %-3d  best cost %.6g  (%d evals)\n",
                    iter + 1, fv[lo], c->nevals);
    }

    lo = 0;
    for (i = 1; i <= n; i++)
        if (fv[i] < fv[lo]) lo = i;
    for (j = 0; j < n; j++)
        ubest[j] = s[lo][j];
    *fbest = fv[lo];
}


/* Enhancement-194: a small self-contained PRNG (splitmix64) so PSO is
 * reproducible from `-seed` and independent of ngspice's global RNG state. */
static unsigned long long opt_rng;
static void   opt_srand(unsigned long s) { opt_rng = s ? (unsigned long long) s
                                                        : 0x9e3779b97f4a7c15ULL; }
static double opt_rand(void)                          /* uniform in [0,1)          */
{
    unsigned long long z = (opt_rng += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    z =  z ^ (z >> 31);
    return (double) (z >> 11) * (1.0 / 9007199254740992.0);   /* 53-bit mantissa   */
}


/* Enhancement-194: particle swarm optimization over the np normalized parameters.
 * A global, population-based, derivative-free method -- robust on multimodal /
 * rugged objectives where the local Nelder-Mead simplex settles into whichever
 * basin it starts in. N particles fly through [0,1]^np, each pulled toward its own
 * best-seen point (pbest) and the swarm's best (gbest) with the standard
 * Clerc-Kennedy constriction (chi = 0.72984, phi = 2.05), velocities clamped to
 * half the box. Particle 0 starts at the user's init point; the rest are random.
 * On exit ubest holds the best point found and *fbest its cost. Works for both
 * scalar (-minimize) and least-squares (-target) objectives, since opt_eval
 * returns the scalar cost either way. */
static void particle_swarm(struct optctx *c, double *ubest, double *fbest)
{
    const int    n = c->np, N = c->swarmsize;
    const double chi = 0.72984, phi = 2.05, vmax = 0.5;
    double *x  = TMALLOC(double, (size_t) N * (size_t) n);   /* positions          */
    double *v  = TMALLOC(double, (size_t) N * (size_t) n);   /* velocities         */
    double *pb = TMALLOC(double, (size_t) N * (size_t) n);   /* personal-best pos  */
    double *pf = TMALLOC(double, N);                         /* personal-best cost */
    double gb[OPT_MAXP], gf = 1e300;
    int i, j, iter, gi = 0, stall = 0;

    opt_srand(c->seed);

    /* seed the swarm: particle 0 at the start point, the rest uniform random */
    for (i = 0; i < N; i++) {
        for (j = 0; j < n; j++) {
            x[i * n + j]  = (i == 0) ? clamp01(ubest[j]) : opt_rand();
            v[i * n + j]  = (opt_rand() * 2.0 - 1.0) * vmax;
            pb[i * n + j] = x[i * n + j];
        }
        pf[i] = opt_eval(c, &x[i * n], NULL);
        if (pf[i] < gf) { gf = pf[i]; gi = i; }
    }
    for (j = 0; j < n; j++) gb[j] = pb[gi * n + j];

    for (iter = 0; iter < c->maxiter; iter++) {
        double prevgf = gf;
        for (i = 0; i < N; i++) {
            for (j = 0; j < n; j++) {
                double r1 = opt_rand(), r2 = opt_rand();
                double vv = chi * (v[i * n + j]
                          + phi * r1 * (pb[i * n + j] - x[i * n + j])
                          + phi * r2 * (gb[j]         - x[i * n + j]));
                if (vv >  vmax) vv =  vmax;
                if (vv < -vmax) vv = -vmax;
                v[i * n + j] = vv;
                x[i * n + j] = clamp01(x[i * n + j] + vv);
            }
            double f = opt_eval(c, &x[i * n], NULL);
            if (f < pf[i]) {
                pf[i] = f;
                for (j = 0; j < n; j++) pb[i * n + j] = x[i * n + j];
                if (f < gf) { gf = f; for (j = 0; j < n; j++) gb[j] = x[i * n + j]; }
            }
        }
        /* converge on relative gbest stagnation held over several iterations
         * (E-197: more patience as dimension grows; unchanged for small n) */
        if (prevgf - gf <= c->tol * (fabs(gf) + c->tol)) {
            if (++stall >= 8 + n / 4) break;
        } else {
            stall = 0;
        }
        if (c->verbose)
            fprintf(cp_out, "  iter %-3d  best cost %.6g  (%d evals)\n",
                    iter + 1, gf, c->nevals);
    }

    for (j = 0; j < n; j++) ubest[j] = gb[j];
    *fbest = gf;
    tfree(x); tfree(v); tfree(pb); tfree(pf);
}


/* Enhancement-195: differential evolution (DE/rand/1/bin) over the np normalized
 * parameters. Like PSO a global, population-based, derivative-free method, but it
 * builds each trial by adding a scaled DIFFERENCE of two random population members
 * to a third -- v = a + F*(b - c) -- then binomially crosses it with the target
 * vector. That difference vector self-scales to the population's own spread (large
 * while the members are far apart, shrinking as they converge), which makes DE
 * robust on rugged / discontinuous / poorly-scaled landscapes where a fixed step
 * struggles. Greedy selection keeps the trial only if it is no worse. On exit
 * ubest holds the best point and *fbest its cost. Works for scalar and
 * least-squares objectives (opt_eval returns the scalar cost either way). */
static void differential_evolution(struct optctx *c, double *ubest, double *fbest)
{
    const int    n = c->np, NP = c->swarmsize;
    const double F = 0.8;
    /* Crossover rate. Classic DE/rand/1 uses CR ~ 0.9, which mutates almost every
     * coordinate -- fine in low dimension, but in HIGH dimension a trial that
     * perturbs ~n coordinates at once is nearly always worse than the target and
     * gets rejected, so DE stalls. Enhancement-197: cap the expected number of
     * mutated coordinates (~CR*n) at about 15 for large n, so high-dimensional
     * runs still make progress; small problems keep the classic CR = 0.9 exactly. */
    const double CR = (n <= 16) ? 0.9 : 15.0 / (double) n;
    double *x  = TMALLOC(double, (size_t) NP * (size_t) n);   /* population        */
    double *fx = TMALLOC(double, NP);                         /* member costs      */
    double trial[OPT_MAXP], gb[OPT_MAXP], gf = 1e300;
    int i, j, iter, gi = 0, stall = 0;

    opt_srand(c->seed);

    /* init: member 0 at the start point, the rest uniform random in [0,1]^n */
    for (i = 0; i < NP; i++) {
        for (j = 0; j < n; j++)
            x[i * n + j] = (i == 0) ? clamp01(ubest[j]) : opt_rand();
        fx[i] = opt_eval(c, &x[i * n], NULL);
        if (fx[i] < gf) { gf = fx[i]; gi = i; }
    }
    for (j = 0; j < n; j++) gb[j] = x[gi * n + j];

    for (iter = 0; iter < c->maxiter; iter++) {
        double prevgf = gf;
        for (i = 0; i < NP; i++) {
            int a, b, e, jr;
            double ft;
            do a = (int) (opt_rand() * NP); while (a == i);              /* distinct */
            do b = (int) (opt_rand() * NP); while (b == i || b == a);
            do e = (int) (opt_rand() * NP); while (e == i || e == a || e == b);
            jr = (int) (opt_rand() * n);            /* one always-crossed dimension  */
            for (j = 0; j < n; j++) {
                if (opt_rand() < CR || j == jr)
                    trial[j] = clamp01(x[a * n + j] + F * (x[b * n + j] - x[e * n + j]));
                else
                    trial[j] = x[i * n + j];
            }
            ft = opt_eval(c, trial, NULL);
            if (ft <= fx[i]) {                       /* greedy: keep if no worse     */
                for (j = 0; j < n; j++) x[i * n + j] = trial[j];
                fx[i] = ft;
                if (ft < gf) { gf = ft; for (j = 0; j < n; j++) gb[j] = trial[j]; }
            }
        }
        /* E-197: high-dimensional runs plateau for several generations between
         * improvements, so give the stagnation counter more patience as n grows
         * (unchanged for small n: 8 for n <= 3). */
        if (prevgf - gf <= c->tol * (fabs(gf) + c->tol)) {
            if (++stall >= 8 + n / 4) break;
        } else {
            stall = 0;
        }
        if (c->verbose)
            fprintf(cp_out, "  iter %-3d  best cost %.6g  (%d evals)\n",
                    iter + 1, gf, c->nevals);
    }

    for (j = 0; j < n; j++) ubest[j] = gb[j];
    *fbest = gf;
    tfree(x); tfree(fx);
}


/* Enhancement-196: simulated annealing over the np normalized parameters. A
 * single-walker global, derivative-free method: from the current point it proposes
 * a random neighbour and accepts it if it is better, OR -- with probability
 * exp(-Dcost/T) -- if it is worse (the Metropolis rule), so it can climb out of a
 * local minimum while the "temperature" T is high, then settles as T is cooled
 * geometrically toward zero. Unlike a swarm/population it evaluates ONE candidate
 * per step, so it is the cheapest global method when each analysis is expensive.
 * The step size and T are auto-scaled to the problem (T0 from the cost spread of
 * random probes; the step shrinks as T cools). On exit ubest holds the best point
 * ever visited and *fbest its cost. Works for scalar and least-squares objectives. */
static void simulated_annealing(struct optctx *c, double *ubest, double *fbest)
{
    const int n = c->np;
    double x[OPT_MAXP], xn[OPT_MAXP], best[OPT_MAXP];
    double fx, fn, fb, T, T0, alpha, sum;
    int i, j, level, L, m;

    opt_srand(c->seed);

    for (j = 0; j < n; j++) { x[j] = clamp01(ubest[j]); best[j] = x[j]; }
    fx = fb = opt_eval(c, x, NULL);

    /* initial temperature: the mean |cost change| of a handful of random probes,
     * so an uphill move of that size is accepted about half the time when hot */
    sum = 0.0; m = 0;
    for (i = 0; i < 12; i++) {
        for (j = 0; j < n; j++) xn[j] = opt_rand();
        fn = opt_eval(c, xn, NULL);
        if (fn < OPT_PENALTY) { sum += fabs(fn - fx); m++; }
    }
    T0 = (m > 0 && sum > 0.0) ? sum / m : 1.0;
    T  = T0;

    /* c->maxiter temperature levels, L moves each; cool ~4 decades over the run */
    L     = 8 + 4 * n;
    alpha = pow(1e-4, 1.0 / (double) (c->maxiter > 1 ? c->maxiter : 1));

    for (level = 0; level < c->maxiter; level++) {
        double step = 0.30 * sqrt(T / T0) + 0.02;   /* wide when hot, fine when cold */
        for (i = 0; i < L; i++) {
            for (j = 0; j < n; j++)
                xn[j] = clamp01(x[j] + step * (opt_rand() * 2.0 - 1.0));
            fn = opt_eval(c, xn, NULL);
            {
                double d = fn - fx;
                if (d <= 0.0 || opt_rand() < exp(-d / T)) {   /* Metropolis accept */
                    for (j = 0; j < n; j++) x[j] = xn[j];
                    fx = fn;
                    if (fx < fb) {                            /* remember the best */
                        fb = fx;
                        for (j = 0; j < n; j++) best[j] = x[j];
                    }
                }
            }
        }
        T *= alpha;
        if (c->verbose)
            fprintf(cp_out, "  level %-3d  T %.3g  best cost %.6g  (%d evals)\n",
                    level + 1, T, fb, c->nevals);
    }

    for (j = 0; j < n; j++) ubest[j] = best[j];
    *fbest = fb;
}


/* ==================== Enhancement-216: NSGA-II Pareto ====================== */

/* Evaluate all `nobj` objectives at the normalized point `u` into `f`. Maximized
 * objectives are negated, so throughout NSGA-II "smaller is better" for every
 * objective (a single minimization convention). Shares opt_eval's param-apply
 * prologue (deck-param re-source + in-place alter). */
static void opt_eval_objs(struct optctx *c, const double *u, double *f)
{
    int i, k;
    char cmd[512];

    ft_optimizing = !c->verbose;
    if (c->has_deckparam) {
        if (c->fp_armed) {                 /* Enhancement-322: in-place, no reset */
            opt_fp_apply(c, u);
        } else {
            for (k = 0; k < c->np; k++) {
                if (c->kind[k] != OPT_DECKPARAM)
                    continue;
                double val = c->lo[k] + clamp01(u[k]) * (c->hi[k] - c->lo[k]);
                (void) snprintf(cmd, sizeof cmd, "alterparam %s=%.10g",
                                c->name[k], val);
                opt_run_cmd(cmd);
            }
            opt_run_cmd("reset");
            ft_optimizing = !c->verbose;
        }
    }
    opt_apply_inplace(c, u);
    c->nevals++;

    opt_run_cmd(c->analysis[0]);
    for (i = 0; i < c->nobj; i++) {
        double v = opt_eval_expr(c->obj[i]);
        if (v >= OPT_PENALTY)
            v = 1e15;                       /* failed eval -> dominated everywhere */
        f[i] = c->obj_max[i] ? -v : v;      /* minimization convention */
    }
    ft_optimizing = FALSE;
}

/* Pareto dominance (minimization): a dominates b iff a[i] <= b[i] for all i and
 * a[i] < b[i] for at least one. */
static int nsga_dominates(const double *a, const double *b, int m)
{
    int i, strictly = 0;
    for (i = 0; i < m; i++) {
        if (a[i] > b[i]) return 0;
        if (a[i] < b[i]) strictly = 1;
    }
    return strictly;
}

/* Fast non-dominated sort: fill rank[i] with the Pareto front index of member i
 * (0 = the non-dominated front). O(m * P^2), P = population size. */
static void nsga_sort(const double *F, int P, int m, int *rank)
{
    int i, j, front, remaining = P;
    int *ndom = TMALLOC(int, P);          /* # of members that dominate i */
    for (i = 0; i < P; i++) { rank[i] = -1; ndom[i] = 0; }
    for (i = 0; i < P; i++)
        for (j = 0; j < P; j++)
            if (i != j && nsga_dominates(&F[j * m], &F[i * m], m))
                ndom[i]++;
    front = 0;
    while (remaining > 0) {
        int found = 0;
        for (i = 0; i < P; i++)
            if (rank[i] < 0 && ndom[i] == 0) { rank[i] = front; found++; }
        /* peel this front: decrement the domination count of everyone it dominated */
        for (i = 0; i < P; i++) {
            if (rank[i] != front) continue;
            for (j = 0; j < P; j++)
                if (rank[j] < 0 && nsga_dominates(&F[i * m], &F[j * m], m))
                    ndom[j]--;
        }
        remaining -= found;
        front++;
        if (found == 0) {                 /* numerical safety: assign the rest */
            for (i = 0; i < P; i++) if (rank[i] < 0) rank[i] = front;
            break;
        }
    }
    tfree(ndom);
}

/* Crowding distance within each front: boundary points get +inf, interior points
 * the sum over objectives of the normalized gap to their two neighbours. Larger =
 * more isolated = preferred, to spread the front. */
static void nsga_crowding(const double *F, int P, int m, const int *rank,
                          double *crowd)
{
    int i, o, a, b, nf, front, maxfront = 0;
    int *idx = TMALLOC(int, P);
    for (i = 0; i < P; i++) { crowd[i] = 0.0; if (rank[i] > maxfront) maxfront = rank[i]; }
    for (front = 0; front <= maxfront; front++) {
        nf = 0;
        for (i = 0; i < P; i++) if (rank[i] == front) idx[nf++] = i;
        if (nf == 0) continue;
        for (o = 0; o < m; o++) {
            /* insertion-sort the front's members by objective o */
            for (a = 1; a < nf; a++) {
                int key = idx[a];
                for (b = a - 1; b >= 0 && F[idx[b] * m + o] > F[key * m + o]; b--)
                    idx[b + 1] = idx[b];
                idx[b + 1] = key;
            }
            double fmin = F[idx[0] * m + o], fmax = F[idx[nf - 1] * m + o];
            double span = fmax - fmin;
            crowd[idx[0]] = crowd[idx[nf - 1]] = 1e30;   /* boundary = infinite */
            if (span <= 0.0) continue;
            for (a = 1; a < nf - 1; a++)
                if (crowd[idx[a]] < 1e30)
                    crowd[idx[a]] += (F[idx[a + 1] * m + o] - F[idx[a - 1] * m + o]) / span;
        }
    }
    tfree(idx);
}

/* Crowded-comparison: i is "better" than j if it has a lower Pareto rank, or the
 * same rank but a larger crowding distance. */
static int nsga_better(int i, int j, const int *rank, const double *crowd)
{
    if (rank[i] != rank[j]) return rank[i] < rank[j];
    return crowd[i] > crowd[j];
}

/* Binary tournament over the first P members using the crowded-comparison. */
static int nsga_tournament(int P, const int *rank, const double *crowd)
{
    int a = (int) (opt_rand() * P), b = (int) (opt_rand() * P);
    if (a >= P) a = P - 1;
    if (b >= P) b = P - 1;
    return nsga_better(a, b, rank, crowd) ? a : b;
}

/* NSGA-II main loop. Real-coded: SBX crossover + polynomial mutation on the
 * normalized [0,1] parameters, elitist (parent+offspring) survivor selection by
 * (rank, crowding). Prints the final non-dominated front. */
static void nsga2(struct optctx *c)
{
    const int n = c->np, m = c->nobj, N = c->swarmsize;
    const double eta_c = 15.0, eta_m = 20.0;   /* SBX / mutation distribution indices */
    const double pm = 1.0 / (double) n;        /* per-gene mutation probability */
    /* R holds 2N members: parents [0,N) then offspring [N,2N). */
    double *X = TMALLOC(double, (size_t) 2 * N * n);
    double *F = TMALLOC(double, (size_t) 2 * N * m);
    int    *rank  = TMALLOC(int, 2 * N);
    double *crowd = TMALLOC(double, 2 * N);
    int    *order = TMALLOC(int, 2 * N);
    int i, j, o, gen;

    opt_srand(c->seed);

    /* initial parents: member 0 at the start point, the rest uniform random */
    for (i = 0; i < N; i++) {
        for (j = 0; j < n; j++)
            X[i * n + j] = (i == 0)
                ? clamp01((c->x0[j] - c->lo[j]) / (c->hi[j] - c->lo[j]))
                : opt_rand();
        opt_eval_objs(c, &X[i * n], &F[i * m]);
    }

    for (gen = 0; gen < c->maxiter; gen++) {
        /* rank+crowd the current parents [0,N) for tournament selection */
        nsga_sort(F, N, m, rank);
        nsga_crowding(F, N, m, rank, crowd);

        /* create N offspring into [N,2N) */
        for (i = 0; i < N; i += 2) {
            int p1 = nsga_tournament(N, rank, crowd);
            int p2 = nsga_tournament(N, rank, crowd);
            int c1 = N + i, c2 = N + ((i + 1 < N) ? i + 1 : i);
            for (j = 0; j < n; j++) {
                double y1 = X[p1 * n + j], y2 = X[p2 * n + j], ch1, ch2;
                /* SBX crossover */
                if (opt_rand() <= 0.9 && fabs(y1 - y2) > 1e-14) {
                    double u = opt_rand();
                    double beta = (u <= 0.5) ? pow(2.0 * u, 1.0 / (eta_c + 1.0))
                                             : pow(1.0 / (2.0 * (1.0 - u)), 1.0 / (eta_c + 1.0));
                    ch1 = 0.5 * ((1.0 + beta) * y1 + (1.0 - beta) * y2);
                    ch2 = 0.5 * ((1.0 - beta) * y1 + (1.0 + beta) * y2);
                } else {
                    ch1 = y1; ch2 = y2;
                }
                /* polynomial mutation */
                if (opt_rand() < pm) {
                    double u = opt_rand();
                    double d = (u < 0.5) ? pow(2.0 * u, 1.0 / (eta_m + 1.0)) - 1.0
                                         : 1.0 - pow(2.0 * (1.0 - u), 1.0 / (eta_m + 1.0));
                    ch1 += d;
                }
                if (opt_rand() < pm) {
                    double u = opt_rand();
                    double d = (u < 0.5) ? pow(2.0 * u, 1.0 / (eta_m + 1.0)) - 1.0
                                         : 1.0 - pow(2.0 * (1.0 - u), 1.0 / (eta_m + 1.0));
                    ch2 += d;
                }
                X[c1 * n + j] = clamp01(ch1);
                X[c2 * n + j] = clamp01(ch2);
            }
            opt_eval_objs(c, &X[c1 * n], &F[c1 * m]);
            if (c2 != c1)
                opt_eval_objs(c, &X[c2 * n], &F[c2 * m]);
        }

        /* elitist survivor selection: rank+crowd all 2N, keep the best N as parents */
        nsga_sort(F, 2 * N, m, rank);
        nsga_crowding(F, 2 * N, m, rank, crowd);
        for (i = 0; i < 2 * N; i++) order[i] = i;
        /* insertion sort order[] by crowded-comparison (2N is small) */
        for (i = 1; i < 2 * N; i++) {
            int key = order[i];
            for (j = i - 1; j >= 0 && nsga_better(key, order[j], rank, crowd); j--)
                order[j + 1] = order[j];
            order[j + 1] = key;
        }
        /* compact the top N to the front of X/F (walk from the back to avoid clobber) */
        {
            double *nx = TMALLOC(double, (size_t) N * n);
            double *nf = TMALLOC(double, (size_t) N * m);
            for (i = 0; i < N; i++) {
                for (j = 0; j < n; j++) nx[i * n + j] = X[order[i] * n + j];
                for (o = 0; o < m; o++) nf[i * m + o] = F[order[i] * m + o];
            }
            for (i = 0; i < N; i++) {
                for (j = 0; j < n; j++) X[i * n + j] = nx[i * n + j];
                for (o = 0; o < m; o++) F[i * m + o] = nf[i * m + o];
            }
            tfree(nx); tfree(nf);
        }
        if (c->verbose) {
            nsga_sort(F, N, m, rank);
            int nfront = 0;
            for (i = 0; i < N; i++) if (rank[i] == 0) nfront++;
            fprintf(cp_out, "  gen %-3d  front size %-3d  (%d evals)\n",
                    gen + 1, nfront, c->nevals);
        }
    }

    /* final front: rank the parents, collect and report rank-0, sorted by obj 1 */
    nsga_sort(F, N, m, rank);
    {
        int *fr = TMALLOC(int, N), nfr = 0;
        for (i = 0; i < N; i++) if (rank[i] == 0) fr[nfr++] = i;
        /* sort the front by the first objective (in its natural, un-negated sense) */
        for (i = 1; i < nfr; i++) {
            int key = fr[i];
            for (j = i - 1; j >= 0 && F[fr[j] * m] > F[key * m]; j--) fr[j + 1] = fr[j];
            fr[j + 1] = key;
        }
        fprintf(cp_out, "optimize: NSGA-II Pareto front -- %d non-dominated design%s "
                        "after %d evaluations\n", nfr, nfr == 1 ? "" : "s", c->nevals);
        /* header: objective names, then parameter names */
        fprintf(cp_out, "   ");
        for (o = 0; o < m; o++)
            fprintf(cp_out, " %s%s", c->obj_max[o] ? "max:" : "min:", c->obj[o]);
        fprintf(cp_out, " |");
        for (j = 0; j < n; j++) fprintf(cp_out, " %s", c->name[j]);
        fprintf(cp_out, "\n");
        for (i = 0; i < nfr; i++) {
            int e = fr[i];
            fprintf(cp_out, "   ");
            for (o = 0; o < m; o++)
                fprintf(cp_out, " %.6g", c->obj_max[o] ? -F[e * m + o] : F[e * m + o]);
            fprintf(cp_out, " |");
            for (j = 0; j < n; j++)
                fprintf(cp_out, " %.6g", c->lo[j] + X[e * n + j] * (c->hi[j] - c->lo[j]));
            fprintf(cp_out, "\n");
        }
        /* publish the front's objective columns as vectors pareto1..paretoM so the
         * front can be plotted (plot pareto2 vs pareto1). */
        for (o = 0; o < m; o++) {
            struct dvec *v;
            char vn[32];
            (void) snprintf(vn, sizeof vn, "pareto%d", o + 1);
            v = dvec_alloc(copy(vn), SV_NOTYPE, VF_REAL | VF_PERMANENT, nfr, NULL);
            if (v) {
                for (i = 0; i < nfr; i++)
                    v->v_realdata[i] = c->obj_max[o] ? -F[fr[i] * m + o] : F[fr[i] * m + o];
                vec_new(v);
            }
        }
        tfree(fr);
    }
    tfree(X); tfree(F); tfree(rank); tfree(crowd); tfree(order);
}


static int is_flag(const char *w)
{
    return w && w[0] == '-' && isalpha((unsigned char) w[1]);
}


/* does the token look like a plain number (optionally signed)? */
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


/* collect tokens from *pwl up to the next flag, joined with single spaces */
/* Each token is cp_unquote()d: ngspice's lexer strips `'...'` itself but keeps
 * the characters of `"..."` in the word (parser/lexical.c), leaving each command
 * to remove them. Kept identical to the copy in com_sweep.c. */
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


void com_optimize(wordlist *wl)
{
    struct optctx c;
    double ubest[OPT_MAXP], fbest = OPT_PENALTY;
    int k, use_lm, use_pso, use_de, use_sa;

    memset(&c, 0, sizeof c);
    c.maxiter = 100;
    c.tol = 1e-6;

    while (wl) {
        const char *w = wl->wl_word;
        if (eq(w, "-param") || eq(w, "-p") || eq(w, "-dparam") || eq(w, "-d") ||
            eq(w, "-mparam") || eq(w, "-m")) {
            int knd = (eq(w, "-dparam") || eq(w, "-d")) ? OPT_DECKPARAM :
                      (eq(w, "-mparam") || eq(w, "-m")) ? OPT_MODELPARAM : OPT_ALTER;
            if (c.np >= OPT_MAXP) {
                fprintf(cp_err, "optimize: too many -param (max %d)\n", OPT_MAXP);
                goto cleanup;
            }
            wordlist *a = wl->wl_next, *b = a ? a->wl_next : NULL;
            wordlist *d = b ? b->wl_next : NULL, *e = d ? d->wl_next : NULL;
            if (!a || !b || !d || !e) {
                fprintf(cp_err, "optimize: %s needs <name> <init> <lo> <hi>\n", w);
                goto cleanup;
            }
            c.name[c.np] = copy(a->wl_word);
            c.kind[c.np] = knd;
            c.x0[c.np]   = optnum(b->wl_word);
            c.lo[c.np]   = optnum(d->wl_word);
            c.hi[c.np]   = optnum(e->wl_word);
            if (c.hi[c.np] <= c.lo[c.np]) {
                fprintf(cp_err, "optimize: param '%s' needs hi > lo\n", c.name[c.np]);
                tfree(c.name[c.np]);
                goto cleanup;
            }
            if (knd == OPT_DECKPARAM)
                c.has_deckparam = 1;
            c.np++;
            wl = e->wl_next;
        } else if (eq(w, "-analysis") || eq(w, "-a")) {
            if (c.ns >= OPT_MAXS) {
                fprintf(cp_err, "optimize: too many -analysis (max %d)\n", OPT_MAXS);
                goto cleanup;
            }
            wl = wl->wl_next;
            c.analysis[c.ns] = collect_until_flag(&wl);
            if (!c.analysis[c.ns]) {
                fprintf(cp_err, "optimize: -analysis needs a command\n");
                goto cleanup;
            }
            c.ns++;
        } else if (eq(w, "-minimize") || eq(w, "-o") ||
                   (eq(w, "-min") && c.nspec == 0 && !c.center)) {
            /* bare -min is the scalar-objective alias only outside centering mode;
             * once a -spec is present (or -center given) it is a spec lower bound. */
            wl = wl->wl_next;
            char *e = collect_until_flag(&wl);
            /* First -minimize also seeds the scalar objective (for nm/pso/de/sa);
             * every -minimize/-maximize appends to the NSGA-II objective list
             * (Enhancement-216). */
            if (!c.objective)
                c.objective = copy(e);
            if (c.nobj < OPT_MAXOBJ) {
                c.obj[c.nobj] = e;
                c.obj_max[c.nobj] = 0;
                c.nobj++;
            } else {
                tfree(e);
            }
        } else if (eq(w, "-maximize") || eq(w, "-maxobj")) {
            /* Enhancement-216: a maximized NSGA-II objective (negated internally to
             * the common minimization convention). NB not "-max", which is the
             * E-206 spec upper-bound flag. */
            wl = wl->wl_next;
            char *e = collect_until_flag(&wl);
            if (c.nobj < OPT_MAXOBJ) {
                c.obj[c.nobj] = e;
                c.obj_max[c.nobj] = 1;
                c.nobj++;
            } else {
                tfree(e);
            }
        } else if (eq(w, "-target")) {
            if (c.ns < 1) {
                fprintf(cp_err, "optimize: -target must follow an -analysis\n");
                goto cleanup;
            }
            if (c.nt >= OPT_MAXT) {
                fprintf(cp_err, "optimize: too many -target (max %d)\n", OPT_MAXT);
                goto cleanup;
            }
            wordlist *a = wl->wl_next, *b = a ? a->wl_next : NULL;
            if (!a || !b) {
                fprintf(cp_err, "optimize: -target needs <expr> <value> [<weight>]\n");
                goto cleanup;
            }
            c.tgt[c.nt].expr   = copy(a->wl_word);
            c.tgt[c.nt].target = optnum(b->wl_word);
            c.tgt[c.nt].weight = 1.0;
            c.tgt[c.nt].stage  = c.ns - 1;
            wl = b->wl_next;
            if (wl && !is_flag(wl->wl_word) && is_number_token(wl->wl_word)) {
                c.tgt[c.nt].weight = optnum(wl->wl_word);
                wl = wl->wl_next;
            }
            c.nt++;
        } else if (eq(w, "-method")) {
            if (wl->wl_next) {
                const char *mm = wl->wl_next->wl_word;
                if (eq(mm, "nm") || eq(mm, "neldermead") || eq(mm, "simplex"))
                    c.method = 1;
                else if (eq(mm, "lm") || eq(mm, "levmar") || eq(mm, "leastsq"))
                    c.method = 2;
                else if (eq(mm, "pso") || eq(mm, "swarm") || eq(mm, "particleswarm"))
                    c.method = 3;        /* Enhancement-194 */
                else if (eq(mm, "de") || eq(mm, "diffevol") ||
                         eq(mm, "differentialevolution"))
                    c.method = 4;        /* Enhancement-195 */
                else if (eq(mm, "sa") || eq(mm, "anneal") ||
                         eq(mm, "simulatedannealing"))
                    c.method = 5;        /* Enhancement-196 */
                else if (eq(mm, "nsga2") || eq(mm, "nsga") || eq(mm, "pareto"))
                    c.method = 6;        /* Enhancement-216 */
                else {
                    fprintf(cp_err, "optimize: unknown -method '%s' "
                                    "(use nm, lm, pso, de, sa or nsga2)\n", mm);
                    goto cleanup;
                }
                wl = wl->wl_next->wl_next;
            } else {
                wl = NULL;
            }
        } else if (eq(w, "-swarmsize") || eq(w, "-swarm") || eq(w, "-npart")) {
            if (wl->wl_next) { c.swarmsize = atoi(wl->wl_next->wl_word); wl = wl->wl_next->wl_next; }
            else wl = NULL;
        } else if (eq(w, "-seed")) {
            if (wl->wl_next) { c.seed = (unsigned long) strtoul(wl->wl_next->wl_word, NULL, 10);
                               wl = wl->wl_next->wl_next; }
            else wl = NULL;
        } else if (eq(w, "-maxiter") || eq(w, "-n")) {
            if (wl->wl_next) { c.maxiter = atoi(wl->wl_next->wl_word); wl = wl->wl_next->wl_next; }
            else wl = NULL;
        } else if (eq(w, "-tol") || eq(w, "-t")) {
            if (wl->wl_next) { c.tol = atof(wl->wl_next->wl_word); wl = wl->wl_next->wl_next; }
            else wl = NULL;
        } else if (eq(w, "-verbose") || eq(w, "-v")) {
            c.verbose = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-center") || eq(w, "-yield")) {   /* Enhancement-206 */
            c.center = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-samples") || eq(w, "-nsamp")) {
            if (wl->wl_next) { c.nsamples = atoi(wl->wl_next->wl_word); wl = wl->wl_next->wl_next; }
            else wl = NULL;
        } else if (eq(w, "-lhs")) {
            c.lhs = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-spec")) {
            c.center = 1;
            if (c.nspec >= OPT_MAXSPEC) {
                fprintf(cp_err, "optimize: too many -spec (max %d)\n", OPT_MAXSPEC);
                goto cleanup;
            }
            if (!wl->wl_next) { fprintf(cp_err, "optimize: -spec needs a metric expression\n"); goto cleanup; }
            wl = wl->wl_next;
            strncpy(c.spec[c.nspec].metric, wl->wl_word, sizeof c.spec[c.nspec].metric - 1);
            c.spec[c.nspec].metric[sizeof c.spec[c.nspec].metric - 1] = '\0';
            c.spec[c.nspec].hasmax = c.spec[c.nspec].hasmin = 0;
            c.nspec++;
            wl = wl->wl_next;
        } else if (eq(w, "-max")) {
            if (c.nspec == 0) { fprintf(cp_err, "optimize: -max before any -spec\n"); goto cleanup; }
            if (!wl->wl_next) { fprintf(cp_err, "optimize: -max needs a value\n"); goto cleanup; }
            wl = wl->wl_next;
            c.spec[c.nspec - 1].hi = optnum(wl->wl_word); c.spec[c.nspec - 1].hasmax = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-min") && c.nspec > 0) {
            if (!wl->wl_next) { fprintf(cp_err, "optimize: -min needs a value\n"); goto cleanup; }
            wl = wl->wl_next;
            c.spec[c.nspec - 1].lo = optnum(wl->wl_word); c.spec[c.nspec - 1].hasmin = 1;
            wl = wl->wl_next;
        } else {
            fprintf(cp_err, "optimize: unrecognized token '%s'\n", w);
            wl = wl->wl_next;
        }
    }

    /* --- validate --- */
    if (c.np < 1 || c.ns < 1 || (!c.objective && c.nt == 0 && !c.center)) {
        fprintf(cp_err, "usage: optimize (-param|-mparam|-dparam) <name> <init> "
                        "<lo> <hi> [...] -analysis <cmd> (-minimize <expr> | -target "
                        "<expr> <val> [<w>] ... | -center (-spec <m> [-max hi] [-min lo])... "
                        "-samples N [-lhs]) [-method nm|lm|pso|de|sa] [-swarmsize N] "
                        "[-seed s] [-maxiter N] [-tol T] [-verbose]\n");
        goto cleanup;
    }
    if (c.center && (c.objective || c.nt > 0)) {
        fprintf(cp_err, "optimize: -center (yield/Cpk) cannot be combined with -minimize/-target\n");
        goto cleanup;
    }
    if (c.center) {   /* Enhancement-206: design centering */
        int s;
        if (c.nspec < 1) {
            fprintf(cp_err, "optimize: -center needs at least one -spec <metric> (-max/-min)\n");
            goto cleanup;
        }
        for (s = 0; s < c.nspec; s++)
            if (!c.spec[s].hasmax && !c.spec[s].hasmin) {
                fprintf(cp_err, "optimize: spec '%s' has no -max/-min limit\n", c.spec[s].metric);
                goto cleanup;
            }
        if (c.ns > 1) {
            fprintf(cp_err, "optimize: -center uses a single -analysis stage\n");
            goto cleanup;
        }
        if (c.nsamples < 2) c.nsamples = 100;         /* default inner MC size */
        c.mcseed = (unsigned) (c.seed ? c.seed : 1);
    }
    if (c.objective && c.nt > 0) {
        fprintf(cp_err, "optimize: use either -minimize or -target, not both\n");
        goto cleanup;
    }
    if (c.objective && c.ns > 1) {
        fprintf(cp_err, "optimize: multiple -analysis stages require -target objectives\n");
        goto cleanup;
    }
    if (c.maxiter < 1) c.maxiter = 1;
    if (c.tol <= 0.0) c.tol = 1e-6;

    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "optimize: no circuit loaded\n");
        goto cleanup;
    }

    /* Enhancement-322: arm the .param fast-path (in-place per-eval instead of
     * alterparam+reset) if every deck-param knob is safely in-place-able. Covers
     * both the NSGA-II and scalar branches below; -center opts out inside. */
    if (opt_fp_arm(&c))
        fprintf(cp_out, "optimize: fast .param path armed (no per-eval reset)\n");

    /* method resolution: LS defaults to Levenberg-Marquardt, scalar to
     * Nelder-Mead; -method may override. LM needs least-squares targets; PSO and
     * NM work for either objective kind (Enhancement-194). */
    if (c.method == 2 && c.nt == 0) {
        fprintf(cp_err, "optimize: -method lm requires -target objectives\n");
        goto cleanup;
    }
    /* Enhancement-216: NSGA-II is multi-objective and returns a Pareto FRONT rather
     * than a single optimum, so it runs on its own branch below. */
    if (c.method == 6) {
        int o;
        if (c.nobj < 2) {
            fprintf(cp_err, "optimize: -method nsga2 needs at least two objectives "
                            "(-minimize/-maximize <expr>)\n");
            goto cleanup;
        }
        if (c.np < 1) {
            fprintf(cp_err, "optimize: -method nsga2 needs at least one -param\n");
            goto cleanup;
        }
        if (c.ns != 1) {
            fprintf(cp_err, "optimize: -method nsga2 uses a single -analysis stage\n");
            goto cleanup;
        }
        if (c.swarmsize <= 0) {
            c.swarmsize = 20 + 4 * c.np;
            if (c.swarmsize > 200) c.swarmsize = 200;
        }
        if (c.swarmsize < 8) c.swarmsize = 8;
        if (c.swarmsize % 2) c.swarmsize++;          /* even for pairwise breeding */
        fprintf(cp_out, "optimize: NSGA-II -- %d parameter%s, %d objectives, "
                        "population %d, seed %lu, up to %d generations\n",
                c.np, c.np == 1 ? "" : "s", c.nobj, c.swarmsize, c.seed, c.maxiter);
        fprintf(cp_out, "   objectives:");
        for (o = 0; o < c.nobj; o++)
            fprintf(cp_out, " %s(%s)", c.obj_max[o] ? "max" : "min", c.obj[o]);
        fprintf(cp_out, "\n");
        nsga2(&c);
        goto cleanup;
    }

    use_lm  = (c.method == 2) || (c.method == 0 && c.nt > 0);
    use_pso = (c.method == 3);
    use_de  = (c.method == 4);
    use_sa  = (c.method == 5);
    if (use_pso || use_de || use_sa) use_lm = 0;

    if (use_pso || use_de) {
        /* auto population: ~4x the dimension, bounded for speed. E-197 raised the
         * cap from 60 to 256 so a high-dimensional run (up to OPT_MAXP params) gets
         * an adequately sized swarm; `-swarmsize` overrides either way. DE needs at
         * least 4 distinct members (target + a,b,c) to form a mutant. */
        if (c.swarmsize <= 0) {
            c.swarmsize = 10 + 4 * c.np;
            if (c.swarmsize > 256) c.swarmsize = 256;
        }
        if (c.swarmsize < 5) c.swarmsize = 5;
    }

    {
        const char *mname = use_pso ? "Particle Swarm"
                          : use_de  ? "Differential Evolution"
                          : use_sa  ? "Simulated Annealing"
                          : use_lm  ? "Levenberg-Marquardt" : "Nelder-Mead";
        if (c.center)
            fprintf(cp_out, "optimize: design centering -- %d design param%s, %d spec%s, "
                            "%d %s MC samples/eval, analysis '%s', maximizing worst-case Cpk (%s)\n",
                    c.np, c.np == 1 ? "" : "s", c.nspec, c.nspec == 1 ? "" : "s",
                    c.nsamples, c.lhs ? "Latin-Hypercube" : "random", c.analysis[0], mname);
        else if (c.nt > 0)
            fprintf(cp_out, "optimize: %d parameter%s, %d target%s over %d analysis "
                            "stage%s, %s\n",
                    c.np, c.np == 1 ? "" : "s", c.nt, c.nt == 1 ? "" : "s",
                    c.ns, c.ns == 1 ? "" : "s", mname);
        else
            fprintf(cp_out, "optimize: %d parameter%s, analysis '%s', minimizing '%s' (%s)\n",
                    c.np, c.np == 1 ? "" : "s", c.analysis[0], c.objective, mname);
        if (use_pso)
            fprintf(cp_out, "optimize: swarm of %d particles, seed %lu, up to %d iterations\n",
                    c.swarmsize, c.seed, c.maxiter);
        else if (use_de)
            fprintf(cp_out, "optimize: population of %d vectors, seed %lu, up to %d generations\n",
                    c.swarmsize, c.seed, c.maxiter);
        else if (use_sa)
            fprintf(cp_out, "optimize: annealing, seed %lu, %d cooling levels\n",
                    c.seed, c.maxiter);
    }

    for (k = 0; k < c.np; k++)
        ubest[k] = clamp01((c.x0[k] - c.lo[k]) / (c.hi[k] - c.lo[k]));

    if (use_pso)
        particle_swarm(&c, ubest, &fbest);
    else if (use_de)
        differential_evolution(&c, ubest, &fbest);
    else if (use_sa)
        simulated_annealing(&c, ubest, &fbest);
    else if (use_lm)
        levenberg_marquardt(&c, ubest, &fbest);
    else
        nelder_mead(&c, ubest, &fbest);

    /* leave the circuit at the optimum and report. The final run is verbose for a
     * plain optimize (one analysis), but stays quiet for centering -- a verbose
     * final run would re-do the whole inner MC and flood the console with resets. */
    c.verbose = !c.center;
    (void) opt_eval(&c, ubest, NULL);

    if (c.center) {
        fprintf(cp_out, "optimize: centered -- worst-case Cpk = %.4g, yield = %.2f%% "
                        "(%d MC samples), after %d evaluations\n",
                c.last_cpk, 100.0 * c.last_yield, c.nsamples, c.nevals);
        dc_set_result("dcenter_yield", c.last_yield);
        dc_set_result("dcenter_cpk", c.last_cpk);
    } else if (c.nt > 0)
        fprintf(cp_out, "optimize: converged, sum-sq residual = %.6g (rms %.6g) "
                        "after %d evaluations\n",
                fbest, sqrt(fbest / c.nt), c.nevals);
    else
        fprintf(cp_out, "optimize: converged, objective = %.6g after %d evaluations\n",
                fbest, c.nevals);
    /* Enhancement-438: failed evaluations were silently absorbed -- a search
     * whose range reaches into a region the model refuses would report a
     * confident "converged" without ever mentioning that a third of its
     * evaluations produced no solution. Say so, and point at the usual cause. */
    if (c.nfailed)
        fprintf(cp_out, "optimize: NOTE -- %d of %d evaluation%s did not solve and "
                        "were scored as worst-case; check that the search range "
                        "stays inside every parameter's legal domain.\n",
                c.nfailed, c.nevals, c.nfailed == 1 ? "" : "s");
    for (k = 0; k < c.np; k++) {
        double val = c.lo[k] + ubest[k] * (c.hi[k] - c.lo[k]);
        fprintf(cp_out, "    %s = %.6g\n", c.name[k], val);
    }

cleanup:
    sw_fp_free();                        /* Enhancement-322: drop fast-path binds */
    for (k = 0; k < c.np; k++)
        tfree(c.name[k]);
    for (k = 0; k < c.ns; k++)
        tfree(c.analysis[k]);
    for (k = 0; k < c.nt; k++)
        tfree(c.tgt[k].expr);
    for (k = 0; k < c.nobj; k++)          /* Enhancement-216 */
        tfree(c.obj[k]);
    tfree(c.objective);
}
