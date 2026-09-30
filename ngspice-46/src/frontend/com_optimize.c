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
  * -method cmaes (Enhancement-764): covariance matrix adaptation evolution
    strategy -- a Gaussian search distribution whose covariance and step size
    are adapted from the RANKING of each generation's candidates. It learns the
    scale and orientation of the valley (a knob spanning decades, correlated
    knobs), never reads a cost (a failed evaluation is the worst rank and
    nothing more), and does not clamp onto a bound; the standard choice for a
    black-box problem in two to fifty knobs.
  * -method bayes (Enhancement-765): Bayesian optimization -- a Gaussian-process
    surrogate (Matern 5/2, a length scale per knob) fitted to every evaluation
    so far, the next point chosen by expected improvement. The method for the
    SLOW deck: tens of evaluations where the population methods spend
    thousands, in up to a dozen knobs. -maxiter is its evaluation budget.
  * -method tr (Enhancement-768): a derivative-free trust region on a quadratic
    model -- a LOCAL method, like the simplex, but one evaluation per step, a
    Hessian learned from 2n+1 interpolation points, and the knob bounds inside
    its subproblem, so it runs along a wall instead of clamping onto it. It is
    what -polish and the surrogate's hand-off run for a scalar objective.

All work for a scalar -minimize objective and -target least-squares. `-swarmsize
<N>` sets the pso/de/cmaes population (default auto, ~10+4*np for pso/de,
4+3*ln(np) for cmaes), `-seed <s>` makes a run reproducible. `-polish`
(Enhancement-764) finishes a global method's best point with the local one
(Nelder-Mead, or Levenberg-Marquardt for -target fits) so a global search ends
with the local methods' precision; `-starts <k>` runs the method from k extra
Latin-hypercube start points besides the given one, each with a share of
-maxiter (CMA-ES doubles its population per start), reports which start won and
polishes the winner.

Constraints (Enhancement-766): `-constrain <expr> -max <hi>` and/or `-min <lo>`,
any number of them, turn the fit into a design problem -- "minimise the current
subject to v(out) >= 0.9" -- solved by an augmented Lagrangian around whichever
method was chosen: the method minimises the objective plus (rho/2) max(0, g +
lambda/rho)^2 per constraint side, the multipliers are updated between rounds,
rho grows when the violation does not shrink, and the search stops feasible
within -ctol (default 1e-4, relative to max(1, |bound|)) or reports INFEASIBLE.
The report prints every constraint's value, whether it is active, and the
multiplier as the objective's sensitivity to the bound; `optimize_feasible` is
published beside the E-762 variables.

Syntax (in a .control block, after the circuit is loaded):

  optimize (-param|-mparam|-dparam) <name> <init> <lo> <hi>  [...]
           -analysis <command ...>
           ( -minimize <expression ...>
             | -target <expr> <value> [<weight>]  [-target ...]
               [ -analysis <command ...> -target ... ] )
           [-constrain <expr> (-max <hi> | -min <lo>) ...] [-ctol <T>]
           [-method nm|lm|tr|pso|de|sa|cmaes|bayes] [-swarmsize <N>] [-seed <s>]
           [-maxiter <N>] [-tol <T>] [-polish] [-starts <k>] [-verbose]

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
#include "com_aging.h"      /* Enhancement-501: aging_replay() */
#include "com_sweep.h"           /* Enhancement-322: shared .param fast-path engine */
#include "ngspice/cktdefs.h"     /* Enhancement-323: CKTcircuit->CKThead[] */
#include "ngspice/devdefs.h"     /* Enhancement-323: DEVices[] / DEVmaxnum   */
#include "ngspice/osdiitf.h"     /* Enhancement-323: osdi_devtype_is_osdi (call #ifdef OSDI) */

#define OPT_MAXP    128          /* max parameters to optimize (E-197)    */
#define OPT_MAXS      8          /* max analysis stages                   */
#define OPT_MAXT    128          /* max least-squares targets (E-197)     */
#define OPT_MAXSPEC  32          /* Enhancement-206: max yield specs      */
#define OPT_MAXOBJ    8          /* Enhancement-216: max NSGA-II objectives */
#define OPT_MAXC     32          /* Enhancement-766: max constraints        */
#define OPT_PENALTY  1e30        /* cost for a failed / non-finite eval   */

/* Enhancement-762 (optimize hunt F1 of 2026-09-29): WHY the search stopped.
 * Every stop used to be reported as "converged" -- the iteration cap, a run
 * in which no evaluation solved, one whose objective never moved -- and only
 * an interrupt (E-537) was told apart. The methods now record their reason,
 * the report prints the matching phrase, and `optimize_status` (a string
 * variable), `optimize_converged` (1 for CONVERGED and COMPLETED),
 * `optimize_cost` and `optimize_evals` are published for a script to test. */
#define OPT_ST_CONVERGED   0     /* the method's own criterion was met          */
#define OPT_ST_MAXITER     1     /* -maxiter ran out first: NOT converged        */
#define OPT_ST_COMPLETED   2     /* a fixed schedule ran to its end (sa, nsga2)  */
#define OPT_ST_NOSOLVE     3     /* no evaluation produced a solution            */
#define OPT_ST_UNCHANGED   4     /* the objective was the same at every eval     */
#define OPT_ST_INTERRUPTED 5     /* the user stopped it (E-537)                  */
#define OPT_ST_INFEASIBLE  6     /* Enhancement-766: a constraint could not be met */

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

/* Enhancement-766: one constraint -- an expression bounded above and/or below,
 * read after its stage's analysis like a target. `val` is the last
 * evaluation's value (OPT_PENALTY when the stage did not solve); the
 * multipliers are in the scaled units of opt_con_g(). */
struct opt_con {
    char  *expr;
    double hi, lo;
    int    hashi, haslo;
    int    stage;
    double val;
    double lam_hi, lam_lo;
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
    /* Enhancement-472: reuse bookkeeping. `reuse_ready` says a circuit is
       standing that this evaluation did not re-source; `reuse_failed` remembers
       that the last analysis produced no solution, whose leftover state nothing
       downstream can characterise. */
    int reuse_ready;
    int reuse_failed;
    int nfailed;                         /* Enhancement-438: evals whose analysis never solved */
    /* Enhancement-499: the spread of objective values actually observed, so the
       final report can tell a search that MOVED from one that never could. */
    double fseen_lo, fseen_hi;
    int    fseen_n;
    int swarmsize;                       /* Enhancement-194: PSO population (0=auto)*/
    unsigned long seed;                  /* Enhancement-194: PSO RNG seed          */
    int    polish;                       /* Enhancement-764: finish with the local method */
    int    starts;                       /* Enhancement-764: extra Latin-hypercube starts */
    double nm_step;                      /* Enhancement-764: Nelder-Mead's first simplex
                                          * edge in the cube (0 = the 0.1 it always used) */
    int    cap_is_evals;                 /* Enhancement-765: -maxiter counted evaluations
                                          * (Bayesian optimization), for the report's word */
    int    polish_iters;                 /* Enhancement-765: the hand-off -- what the surrogate
                                          * left of the budget goes to the local method */

    /* Enhancement-766: constraints, solved by an augmented Lagrangian around
     * the chosen method (al_solve). While al_active is set opt_eval adds the
     * augmented terms to the cost (and a residual per constraint side for LM). */
    int    nc;
    struct opt_con con[OPT_MAXC];
    int    ncside;                       /* constraint sides = extra LM residuals   */
    double ctol;                         /* feasibility tolerance, relative (1e-4)  */
    double rho;                          /* the penalty parameter                   */
    int    al_active;
    int    nm_restart;                   /* rebuild a simplex that collapsed onto a bound */
    int    al_rounds;
    int    al_feasible;
    double al_viol;                      /* the largest scaled violation at the end */
    int    al_worst, al_worst_hi;        /* which constraint and side it was         */

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
    unsigned long mc_trial0;             /* E-536 (hunt bug 8): osdimc trial
                                          * checkpoint -- every -center candidate
                                          * replays the same trial window        */
    int    interrupted;                  /* E-537 (hunt I): the user stopped the
                                          * search, so it did not converge       */
    int    status;                       /* E-762: one of OPT_ST_*               */
    int    lhs_warned;                   /* E-537 (hunt O): said once          */

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
    if (cp_coms[i].co_comname && cp_coms[i].co_func) {
        /* Enhancement-501: an INTERNAL `reset` exists to redraw the random
           parameters, not to un-age the circuit. `age` is written at run time
           and has no deck representation, so re-sourcing drops it -- which left
           wcd, highsigma and optimize -center reporting a FRESH device's
           reliability for a circuit the user had aged. Mark the reset as ours
           so com_rset keeps the record, then put the doses back. A `reset` the
           USER types is not marked, drops the record, and still means what it
           always did. */
        int agereset = (strcasecmp(wl->wl_word, "reset") == 0);
        if (agereset) {
            aging_internal_reset++;
            /* E-536 fix (hunt bug 8): this reset belongs to the optimizer's
             * own machinery, exactly like sw_run_cmd's -- the osdimc trial
             * sequence must keep running. Without it, a `-dparam` fit's
             * per-evaluation re-source zeroed the counter (the held sample
             * silently became the nominal mid-search) and `-center`'s inner
             * Monte-Carlo saw NO osdimc variation at all. */
            OSDImcPreserveTrial();
        }
        sw_inner_run_begin();           /* Enhancement-656: not an autocorner run */
        cp_coms[i].co_func(wl->wl_next);
        sw_inner_run_end();
        if (agereset) {
            aging_internal_reset--;
            alter_journal_replay();  /* Enhancement-544: the user's alters ... */
            aging_replay();          /* ... then the doses on top of them */
        }
    }
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
/* Enhancement-472: ask for the circuit to be kept for this analysis.
 *
 * The optimizer's ordinary evaluation path never re-sources the deck: -param
 * and -mparam knobs are pushed in place, and with Enhancement-322's fast path
 * armed so are -dparam ones. It then paid for a full teardown and rebuild
 * anyway, once per evaluation -- and a fit runs hundreds of them.
 *
 * Ask only when a circuit is actually standing (`reuse_ready`, cleared by any
 * re-source), and never after an analysis that failed. `-center` is excluded
 * outright: its inner Monte-Carlo resets per sample, so there is nothing to
 * keep and the flag would be stale. The request is still only a request --
 * CKTdoJob re-decides node collapse and rebuilds for real if the topology
 * moved, and declines for any device whose collapse it cannot re-check. */
static void opt_reuse_ask(struct optctx *c)
{
    if (c->reuse_ready && !c->reuse_failed && !c->center)
        sw_request_reuse();
}

static int opt_run_failed(void)
{
    int st = 0;
    if (cp_getvar("sim_status", CP_NUM, &st, sizeof st))
        return st != 0;
    return 0;
}


/* (E-763: optnum(), the lenient SPICE-number parser that took `abc` as 0 and
 * `10o` as 10, is gone -- every number the command takes goes through
 * opt_strictnum() below) */

/* Enhancement-499: parse a NUMERIC OPTION the way this command already parses
 * every other number it is given.
 *
 * The bounds, `-target` values and weights, and `-spec` limits all go through
 * optnum() above, which understands SPICE suffixes and scientific notation.
 * `-maxiter`, `-samples`, `-swarmsize` and `-tol` did not: they called atoi()
 * and atof() directly, which stop at the first character they cannot use and
 * return 0 for text. So `1k` meant 1000 in a bound and 1 in `-maxiter` ON THE
 * SAME COMMAND LINE; `-maxiter 2e2` ran 2 iterations, not 200, and returned a
 * worse fit while still reporting "converged"; `-samples 2e2` ran 2 Monte-Carlo
 * samples and design centering still printed a yield with a confidence
 * interval; and `abc` was accepted everywhere as 0, in silence. `sweep lin 2e2`
 * (200 points) and `montecarlo 2e2` (200 samples) were already right, so this
 * was the odd one of the three loop commands.
 *
 * Refused rather than repaired: a count or a tolerance IS the request, and
 * substituting one would answer a different question without saying so. */
static int opt_strictnum(const char *w, double *out)
{
    char *s = (char *) w;
    double v = 0.0;

    if (!w || !*w)
        return 0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        return 0;
    while (*s == ' ' || *s == '\t')
        s++;
    if (*s)                             /* trailing junk: `5x`, `2e2q` */
        return 0;
    if (!(v == v))                      /* NaN */
        return 0;
    *out = v;
    return 1;
}


/* an integer-valued option: strict, whole-token, and at least `lo` */
static int opt_intopt(const char *w, const char *what, int lo, int *out)
{
    double v;

    if (!opt_strictnum(w, &v)) {
        fprintf(cp_err, "optimize: %s needs a number, not '%s'\n", what,
                w ? w : "");
        return 0;
    }
    if (v != floor(v)) {
        fprintf(cp_err, "optimize: %s must be a whole number, not %s\n", what, w);
        return 0;
    }
    if (v < (double) lo || v > 2147483647.0) {
        fprintf(cp_err, "optimize: %s must be %d or more (got %s)\n", what, lo, w);
        return 0;
    }
    *out = (int) v;
    return 1;
}


/* Enhancement-501: a SPEC LIMIT, which may legitimately be negative but must be
 * finite -- a non-finite limit is never violated, so the spec silently does not
 * exist. (opt_realopt below refuses negatives; that is right for `-tol`, wrong
 * for a bound.) */
static int opt_boundopt(const char *w, const char *what, double *out)
{
    double v;

    if (!opt_strictnum(w, &v)) {
        fprintf(cp_err, "optimize: %s needs a number, not '%s'\n", what,
                w ? w : "");
        return 0;
    }
    if (!finite(v)) {
        fprintf(cp_err, "optimize: %s must be finite (got %s); a non-finite limit "
                        "is never violated, so the spec would silently not exist\n",
                what, w);
        return 0;
    }
    *out = v;
    return 1;
}


/* a real-valued option: strict, whole-token, finite, and not negative */
static int opt_realopt(const char *w, const char *what, double *out)
{
    double v;

    if (!opt_strictnum(w, &v)) {
        fprintf(cp_err, "optimize: %s needs a number, not '%s'\n", what,
                w ? w : "");
        return 0;
    }
    if (v < 0.0) {
        fprintf(cp_err, "optimize: %s must not be negative (got %s)\n", what, w);
        return 0;
    }
    *out = v;
    return 1;
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

    /* E-536 fix (hunt bug 8): rewind the osdimc trial counter to the
     * checkpoint taken before the search, so every candidate's inner
     * Monte-Carlo replays the SAME window of trials (draws are pure
     * functions of the counter). The yield objective then samples osdimc
     * variation AND is deterministic across candidates -- the same property
     * the seeded netlist draws below already have. -center therefore runs
     * WITHOUT the hold the deterministic methods take. */
    OSDImcTrialRewind(c->mc_trial0);

    if (c->lhs) {
        mc_lhs_config(c->nsamples, c->mcseed);
        /* E-537 (hunt O): see the note in com_sweep.c -- -lhs does not reach
         * osdimc draws. Said once per command, not once per candidate. */
        if (OSDImcActive() && !c->lhs_warned) {
            c->lhs_warned = 1;
            fprintf(cp_err,
                    "optimize: NOTE -- -lhs stratifies the netlist's own random "
                    ".params; it does NOT cover `.option osdimc` draws.\n");
        }
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

/* Enhancement-766: the scale of a constraint side -- its bound's magnitude, so
 * a 40 dB gain and a 100 uA current weigh alike; 1 for a bound of zero */
static double opt_con_scale(const struct opt_con *k, int upper)
{
    double b = upper ? k->hi : k->lo;
    return fabs(b) > 0.0 ? fabs(b) : 1.0;
}

/* a constraint side as g <= 0 in units of its scale: the upper side
 * (value - hi)/s, the lower (lo - value)/s */
static double opt_con_g(const struct opt_con *k, int upper)
{
    double s = opt_con_scale(k, upper);
    return upper ? (k->val - k->hi) / s : (k->lo - k->val) / s;
}

/* Enhancement-766: read the constraints of stage s from the current plot */
static void opt_eval_cons(struct optctx *c, int s, int failed)
{
    int j;
    for (j = 0; j < c->nc; j++)
        if (c->con[j].stage == s)
            c->con[j].val = failed ? OPT_PENALTY : opt_eval_expr(c->con[j].expr);
}

/* Enhancement-766: the augmented terms at the last evaluation, added to `cost`
 * and written as residuals after the targets when `resid` is given */
static double opt_al_terms(const struct optctx *c, double *resid)
{
    double add = 0.0;
    int j, side = c->nt;
    for (j = 0; j < c->nc; j++) {
        const struct opt_con *k = &c->con[j];
        int up;
        for (up = 1; up >= 0; up--) {
            double g, lam, r;
            if (up ? !k->hashi : !k->haslo) continue;
            if (k->val >= OPT_PENALTY) { r = 1e15; }
            else {
                g = opt_con_g(k, up);
                lam = up ? k->lam_hi : k->lam_lo;
                r = g + lam / c->rho;
                r = r > 0.0 ? sqrt(0.5 * c->rho) * r : 0.0;
            }
            if (resid) resid[side] = r;
            side++;
            add += r * r;
        }
    }
    return add;
}

static double opt_eval(struct optctx *c, const double *u, double *resid)
{
    int k, s, i;
    char cmd[512];
    double cost = 0.0;

    /* E-536 (hunt bug 17): once the user has interrupted, every further
     * evaluation is wasted work (a population method can owe dozens before
     * its loop-top poll fires) -- return the penalty cost immediately so the
     * method winds down without running more analyses. */
    if (ft_intrpt) {
        if (resid)
            for (k = 0; k < c->nt + c->ncside; k++)
                resid[k] = 0.0;
        return OPT_PENALTY;
    }

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
            c->reuse_ready = 0;            /* Enhancement-472: circuit is new */
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
            opt_reuse_ask(c);               /* Enhancement-472 */
            opt_run_cmd(c->analysis[s]);
            c->reuse_failed = opt_run_failed();
            c->reuse_ready = 1;
            if (c->reuse_failed) {          /* Enhancement-438 */
                int t;
                c->nfailed++;
                cost = OPT_PENALTY;
                /* Enhancement-766 (and the 2026-09-29 hunt's F6): the residuals
                 * of this and the later stages used to be left unwritten, so
                 * LM's Jacobian read whatever the stack held; push away */
                if (resid)
                    for (t = 0; t < c->nt; t++)
                        if (c->tgt[t].stage >= s) resid[t] = 1e15;
                for (t = s; t < c->ns; t++)
                    opt_eval_cons(c, t, 1);
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
            opt_eval_cons(c, s, 0);             /* Enhancement-766 */
        }
    } else {
        /* scalar objective evaluated after the (single) analysis stage */
        opt_reuse_ask(c);                   /* Enhancement-472 */
        opt_run_cmd(c->analysis[0]);
        c->reuse_failed = opt_run_failed();
        c->reuse_ready = 1;
        if (c->reuse_failed) {
            /* Enhancement-438: no solution -> no objective. Penalise so the
             * search moves away, instead of scoring the previous point's plot. */
            c->nfailed++;
            cost = OPT_PENALTY;
            opt_eval_cons(c, 0, 1);             /* Enhancement-766 */
        } else {
            cost = opt_eval_expr(c->objective);
            opt_eval_cons(c, 0, 0);             /* Enhancement-766 */
        }
    }

    /* Enhancement-766: the augmented Lagrangian's terms while al_solve runs
     * the inner method; a cost already at the penalty stays there */
    if (c->nc > 0 && c->al_active && !c->center) {
        double add = opt_al_terms(c, resid);
        if (cost < OPT_PENALTY) cost += add;
    }

    ft_optimizing = FALSE;
    /* Enhancement-499: remember the spread, for the verdict printed at the end */
    if (cost == cost) {                       /* ignore NaN */
        if (c->fseen_n == 0 || cost < c->fseen_lo) c->fseen_lo = cost;
        if (c->fseen_n == 0 || cost > c->fseen_hi) c->fseen_hi = cost;
        c->fseen_n++;
    }

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
    const int n = c->np, m = c->nt + (c->al_active ? c->ncside : 0);   /* E-766 */
    const double h = 1e-3;
    double u[OPT_MAXP], r0[OPT_MAXT], rj[OPT_MAXT];
    double J[OPT_MAXT][OPT_MAXP];
    double A[OPT_MAXP * OPT_MAXP], g[OPT_MAXP], delta[OPT_MAXP], unew[OPT_MAXP];
    double lambda = 1e-3, cost0;
    int i, j, k, iter;

    for (j = 0; j < n; j++)
        u[j] = clamp01(ubest[j]);
    cost0 = opt_eval(c, u, r0);

    c->status = OPT_ST_MAXITER;          /* E-762: unless a break below says otherwise */
    for (iter = 0; iter < c->maxiter; iter++) {
        /* E-536 (hunt bug 17): an interrupt only aborts the inner analysis it
         * lands in, and the next dosim() clears the flag -- poll here so
         * Ctrl-C actually stops the search (the best point so far is
         * reported by the normal epilogue). */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at iteration %d\n", iter);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }
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

        if (!accepted) {
            /* no step of any length lowers the cost: a minimum to within the
             * finite-difference accuracy, which is what convergence means here */
            c->status = OPT_ST_CONVERGED;
            break;                                /* cannot reduce further  */
        }
        {
            double improve = cost0 - costn;
            cost0 = costn;
            if (improve <= c->tol * (cost0 + c->tol) || sqrt(dnorm) < c->tol) {
                c->status = OPT_ST_CONVERGED;
                break;                            /* converged              */
            }
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
    int i, j, iter, lo, restarts = 0;

    /* build the initial simplex: the start point plus one point per dimension
     * nudged by 0.1 in normalized space (Enhancement-764: a -polish from a
     * global method's best point asks for a smaller edge through nm_step) */
    const double edge = c->nm_step > 0.0 ? c->nm_step : 0.1;
    for (j = 0; j < n; j++)
        s[0][j] = clamp01(ubest[j]);
    fv[0] = opt_eval(c, s[0], NULL);
    for (i = 1; i <= n; i++) {
        for (j = 0; j < n; j++)
            s[i][j] = s[0][j];
        double b = s[0][i - 1] + edge;
        if (b > 1.0)
            b = s[0][i - 1] - edge;
        s[i][i - 1] = clamp01(b);
        fv[i] = opt_eval(c, s[i], NULL);
    }

    c->status = OPT_ST_MAXITER;          /* E-762 */
    for (iter = 0; iter < c->maxiter; iter++) {
        /* E-536 (hunt bug 17): an interrupt only aborts the inner analysis it
         * lands in, and the next dosim() clears the flag -- poll here so
         * Ctrl-C actually stops the search (the best point so far is
         * reported by the normal epilogue). */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at iteration %d\n", iter);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }
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

        if (fv[hi] - fv[lo] <= c->tol * (fabs(fv[lo]) + c->tol)) {
            /* Enhancement-766: a simplex clamped against a bound goes FLAT -- every
             * vertex has the same clamped value in that coordinate, so no
             * reflection can ever move along it -- and passes this test with
             * that dimension undecided (from (1k, 1k) the constrained divider
             * ended at R1 = 100 on the wall with the optimum at 1111 along it).
             * Under the constrained solve (nm_restart) rebuild the simplex around
             * the best vertex with an inward edge and go on; twice at most. The
             * unconstrained simplex is left as it was. */
            if (c->nm_restart && restarts < 2) {
                int flat = 0;
                for (j = 0; j < n && !flat; j++) {
                    double spread = 0.0;
                    for (i = 0; i <= n; i++)
                        if (fabs(s[i][j] - s[lo][j]) > spread) spread = fabs(s[i][j] - s[lo][j]);
                    flat = spread < 1e-12;
                }
                if (flat) {
                    double b0[OPT_MAXP];
                    for (j = 0; j < n; j++) b0[j] = s[lo][j];
                    for (j = 0; j < n; j++) s[0][j] = b0[j];
                    fv[0] = fv[lo];
                    for (i = 1; i <= n; i++) {
                        double e;
                        for (j = 0; j < n; j++) s[i][j] = b0[j];
                        e = b0[i - 1] + 0.05;
                        if (e > 1.0) e = b0[i - 1] - 0.05;
                        s[i][i - 1] = clamp01(e);
                        fv[i] = opt_eval(c, s[i], NULL);
                    }
                    restarts++;
                    continue;
                }
            }
            c->status = OPT_ST_CONVERGED;
            break;                               /* converged */
        }

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

    c->status = OPT_ST_MAXITER;          /* E-762 */
    for (iter = 0; iter < c->maxiter; iter++) {
        /* E-536 (hunt bug 17): an interrupt only aborts the inner analysis it
         * lands in, and the next dosim() clears the flag -- poll here so
         * Ctrl-C actually stops the search (the best point so far is
         * reported by the normal epilogue). */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at iteration %d\n", iter);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }
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
            if (++stall >= 8 + n / 4) { c->status = OPT_ST_CONVERGED; break; }
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

    c->status = OPT_ST_MAXITER;          /* E-762 */
    for (iter = 0; iter < c->maxiter; iter++) {
        /* E-536 (hunt bug 17): an interrupt only aborts the inner analysis it
         * lands in, and the next dosim() clears the flag -- poll here so
         * Ctrl-C actually stops the search (the best point so far is
         * reported by the normal epilogue). */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at iteration %d\n", iter);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }
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
            if (++stall >= 8 + n / 4) { c->status = OPT_ST_CONVERGED; break; }
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

    c->status = OPT_ST_COMPLETED;        /* E-762: the schedule is the stop */
    for (level = 0; level < c->maxiter; level++) {
        /* E-536 (hunt bug 17): an interrupt only aborts the inner analysis it
         * lands in, and the next dosim() clears the flag -- poll here so
         * Ctrl-C actually stops the search (the best point so far is
         * reported by the normal epilogue). */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at iteration %d\n", level);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }
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



/* ==================== Enhancement-768: trust region ========================= */

/* the quadratic model's value relative to its centre: g'd + d'Hd/2 */
static double tr_q(int n, const double *g, const double *H, const double *d)
{
    double q = 0.0;
    int i, j;
    for (i = 0; i < n; i++) {
        double hd = 0.0;
        for (j = 0; j < n; j++) hd += H[i * n + j] * d[j];
        q += d[i] * (g[i] + 0.5 * hd);
    }
    return q;
}

/* coordinate minimisation of the model over the box lo <= d <= hi, from d: each
 * pass minimises the one-dimensional quadratic in every coordinate exactly
 * (an end of the interval when the curvature is not positive), so the model
 * value never rises */
static void tr_coord(int n, const double *g, const double *H, const double *lo,
                     const double *hi, double *d)
{
    int sweep, i, j;
    for (sweep = 0; sweep < 200; sweep++) {
        double moved = 0.0;
        for (i = 0; i < n; i++) {
            double ge = g[i], hii = H[i * n + i], t;
            for (j = 0; j < n; j++) if (j != i) ge += H[i * n + j] * d[j];
            if (hii > 1e-300) {
                t = -ge / hii;
                if (t < lo[i]) t = lo[i];
                if (t > hi[i]) t = hi[i];
            } else {
                double ql = ge * lo[i] + 0.5 * hii * lo[i] * lo[i];
                double qh = ge * hi[i] + 0.5 * hii * hi[i] * hi[i];
                double qc = ge * d[i] + 0.5 * hii * d[i] * d[i];
                t = ql <= qh ? lo[i] : hi[i];
                if (qc <= ql && qc <= qh) t = d[i];
            }
            if (fabs(t - d[i]) > moved) moved = fabs(t - d[i]);
            d[i] = t;
        }
        if (moved < 1e-15) break;
    }
}

/* the trust-region subproblem: minimise g'd + d'Hd/2 over the box lo <= d <= hi
 * (the radius and the knob bounds together -- a box, so nothing is clamped
 * afterwards). A Newton step on the free coordinates with the bound ones held,
 * the active set grown one hit at a time, then polished by coordinate
 * minimisation and cross-checked against coordinate minimisation from zero;
 * the lower of the two is returned, and neither can be above zero. */
static void tr_box_qp(int n, const double *g, const double *H, const double *lo,
                      const double *hi, double *d)
{
    double dn[OPT_MAXP], dc[OPT_MAXP], b[OPT_MAXP], x[OPT_MAXP];
    int fixed[OPT_MAXP], idx[OPT_MAXP];
    double *M = TMALLOC(double, (size_t) n * (size_t) n);
    int i, j, a, bb, pass;

    for (i = 0; i < n; i++) { dn[i] = dc[i] = 0.0; fixed[i] = 0; }
    for (pass = 0; pass <= n; pass++) {
        int nf = 0, worst = -1;
        double wfrac = 1.0;
        for (i = 0; i < n; i++) if (!fixed[i]) idx[nf++] = i;
        if (nf == 0) break;
        for (a = 0; a < nf; a++) {
            double r = -g[idx[a]];
            for (j = 0; j < n; j++) if (fixed[j]) r -= H[idx[a] * n + j] * dn[j];
            b[a] = r;
            for (bb = 0; bb < nf; bb++) M[a * nf + bb] = H[idx[a] * n + idx[bb]];
        }
        if (!solve_lin(nf, M, b, x)) break;
        for (a = 0; a < nf; a++) {               /* how far toward it the box allows */
            double from = dn[idx[a]], to = x[a], fr = 1.0;
            if (to != to) { wfrac = 0.0; worst = -2; break; }
            if (to > hi[idx[a]])      fr = (hi[idx[a]] - from) / (to - from);
            else if (to < lo[idx[a]]) fr = (lo[idx[a]] - from) / (to - from);
            if (fr < wfrac) { wfrac = fr; worst = a; }
        }
        if (worst == -2) break;
        for (a = 0; a < nf; a++) dn[idx[a]] += wfrac * (x[a] - dn[idx[a]]);
        if (worst < 0) break;
        dn[idx[worst]] = x[worst] > dn[idx[worst]] || x[worst] > hi[idx[worst]] ? hi[idx[worst]] : lo[idx[worst]];
        if (x[worst] < lo[idx[worst]]) dn[idx[worst]] = lo[idx[worst]];
        fixed[idx[worst]] = 1;
    }
    for (i = 0; i < n; i++) {
        if (dn[i] != dn[i]) dn[i] = 0.0;
        if (dn[i] < lo[i]) dn[i] = lo[i];
        if (dn[i] > hi[i]) dn[i] = hi[i];
    }
    tr_coord(n, g, H, lo, hi, dn);
    tr_coord(n, g, H, lo, hi, dc);
    if (tr_q(n, g, H, dn) <= tr_q(n, g, H, dc)) memcpy(d, dn, (size_t) n * sizeof *d);
    else                                        memcpy(d, dc, (size_t) n * sizeof *d);
    tfree(M);
}

/* the least-change update of the model c0 + g'y + y'Hy/2 (y = x - xk): the
 * smallest change of H in the Frobenius norm that makes the model interpolate
 * Fv at the m points Y, from the KKT system
 *
 *     [ A  X ] [ lambda ]   [ r ]        A_jl = (y_j' y_l)^2 / 2
 *     [ X' 0 ] [ dc, dg ] = [ 0 ]        X = [1, y_j'],  r = Fv - model
 *
 * solved in coordinates scaled by the radius so its entries are of order one;
 * then H += sum lambda_j y_j y_j'. With H = 0 on entry this is the
 * minimum-Frobenius-norm model. Returns 0 when the system is singular (a
 * degenerate point set) or the result does not interpolate. */
static int tr_update(int n, int m, const double *Y, const double *Fv, const double *xk,
                     double delta, double *c0, double *g, double *H,
                     double *W, double *rhs, double *sol, double *yh)
{
    const int N = m + n + 1;
    double fmin = 1e300, fmax = -1e300;
    int i, j, l;

    for (j = 0; j < m; j++) {
        for (i = 0; i < n; i++) yh[j * n + i] = (Y[j * n + i] - xk[i]) / delta;
        if (Fv[j] < fmin) fmin = Fv[j];
        if (Fv[j] > fmax) fmax = Fv[j];
    }
    memset(W, 0, (size_t) N * (size_t) N * sizeof *W);
    for (j = 0; j < m; j++) {
        for (l = 0; l < m; l++) {
            double dot = 0.0;
            for (i = 0; i < n; i++) dot += yh[j * n + i] * yh[l * n + i];
            W[j * N + l] = 0.5 * dot * dot;
        }
        W[j * N + m] = W[m * N + j] = 1.0;
        for (i = 0; i < n; i++)
            W[j * N + m + 1 + i] = W[(m + 1 + i) * N + j] = yh[j * n + i];
    }
    for (j = 0; j < m; j++) {
        double y[OPT_MAXP];
        for (i = 0; i < n; i++) y[i] = Y[j * n + i] - xk[i];
        rhs[j] = Fv[j] - (*c0 + tr_q(n, g, H, y));
    }
    for (j = m; j < N; j++) rhs[j] = 0.0;
    if (!solve_lin(N, W, rhs, sol)) return 0;
    for (j = 0; j < N; j++) if (sol[j] != sol[j] || fabs(sol[j]) > 1e250) return 0;
    *c0 += sol[m];
    for (i = 0; i < n; i++) g[i] += sol[m + 1 + i] / delta;
    for (j = 0; j < m; j++) {
        double lam = sol[j] / (delta * delta);
        if (lam == 0.0) continue;
        for (i = 0; i < n; i++)
            for (l = 0; l < n; l++)
                H[i * n + l] += lam * yh[j * n + i] * yh[j * n + l];
    }
    for (j = 0; j < m; j++) {                    /* does it interpolate? */
        double y[OPT_MAXP], q;
        for (i = 0; i < n; i++) y[i] = Y[j * n + i] - xk[i];
        q = *c0 + tr_q(n, g, H, y);
        if (fabs(Fv[j] - q) > 1e-6 * (fabs(Fv[j]) + (fmax - fmin)) + 1e-300) return -1;
    }
    return 1;
}

/* the 2n axis points around xk at the radius, kept inside the cube: xk + delta e_i
 * and xk - delta e_i, or two steps to the inside when one would leave it */
static void tr_axis_set(int n, const double *xk, double delta, double *Y)
{
    int i, j;
    for (j = 0; j < n; j++) Y[j] = xk[j];
    for (i = 0; i < n; i++) {
        double plus = xk[i] + delta, minus = xk[i] - delta;
        if (plus > 1.0)  plus  = xk[i] - 2.0 * delta;
        if (minus < 0.0) minus = xk[i] + 2.0 * delta;
        for (j = 0; j < n; j++) Y[(1 + 2 * i) * n + j] = Y[(2 + 2 * i) * n + j] = xk[j];
        Y[(1 + 2 * i) * n + i] = clamp01(plus);
        Y[(2 + 2 * i) * n + i] = clamp01(minus);
    }
}

/* Enhancement-768: a derivative-free trust-region method on a quadratic model,
 * over the np normalized parameters -- the local method the polish and the
 * surrogate's hand-off were missing. Nelder-Mead spends several evaluations per
 * useful step and converges linearly at best, and clamped against a knob's
 * bound its simplex goes flat and stops; this method keeps 2n + 1 points,
 * interpolates them with a quadratic whose Hessian changes least from one
 * iteration to the next (tr_update: curvature accumulates as the points move),
 * and minimises the model inside a box of radius delta around the best point
 * INTERSECTED with the knob bounds (tr_box_qp) -- a bound is part of the
 * subproblem, so a step runs along a wall instead of being clamped onto it.
 *
 * One evaluation per iteration: the trial point; the ratio of the actual to the
 * predicted decrease accepts it (>= 0.1) and moves the radius (doubled when the
 * model was good and the step reached it, halved when it was poor); the trial
 * point replaces the point farthest from the centre, so the set follows the
 * search. When the model expects less than -tol of decrease, the points still
 * farther than two radii are brought in one at a time (a geometry step: the
 * model is only trusted where its points are); with none left the search is
 * CONVERGED if the last trial step delivered what the model predicted (the
 * model has just proven itself), and otherwise the radius drops tenfold and the
 * test repeats, down to a radius of -tol. Rejected steps that shrink the radius
 * to -tol end it too (a noisy objective).
 * A failed evaluation is not interpolated: the step is refused and the radius
 * halved. The first radius is 0.1 of the box (0.05 and 0.02 when the polish and
 * the surrogate's hand-off call it). On exit ubest holds the best point and
 * *fbest its cost; scalar, least-squares and centering objectives, and the
 * augmented objective of a constrained solve. */
static void trust_region(struct optctx *c, double *ubest, double *fbest)
{
    const int n = c->np, m = 2 * n + 1, N = m + n + 1;
    double *Y   = TMALLOC(double, (size_t) m * (size_t) n);
    double *yh  = TMALLOC(double, (size_t) m * (size_t) n);
    double *Fv  = TMALLOC(double, m);
    double *H   = TMALLOC(double, (size_t) n * (size_t) n);
    double *W   = TMALLOC(double, (size_t) N * (size_t) N);
    double *rhs = TMALLOC(double, N), *sol = TMALLOC(double, N);
    double g[OPT_MAXP], xk[OPT_MAXP], d[OPT_MAXP], lo[OPT_MAXP], hi[OPT_MAXP], xn[OPT_MAXP];
    double delta = c->nm_step > 0.0 ? c->nm_step : 0.1, c0, fk;
    const double dend = c->tol > 1e-12 ? c->tol : 1e-12;
    int kb = 0, iter, i, j, geom = 0, nsol = 0, good = 0, upd;

#define TR_DIST(jj, cen, out) do { int q_; (out) = 0.0;                      \
        for (q_ = 0; q_ < n; q_++)                                            \
            if (fabs(Y[(jj) * n + q_] - (cen)[q_]) > (out)) (out) = fabs(Y[(jj) * n + q_] - (cen)[q_]); } while (0)
    /* rebuild the axis set around xk at the current radius and the model from
     * nothing: the fallback when the point set has degenerated */
#define TR_REBUILD() do {                                                     \
        double fmax_ = -1e300;                                                \
        tr_axis_set(n, xk, delta, Y);                                         \
        Fv[0] = fk;                                                           \
        for (j = 1; j < m; j++) { Fv[j] = opt_eval(c, &Y[j * n], NULL);       \
                                  if (Fv[j] < OPT_PENALTY && Fv[j] > fmax_) fmax_ = Fv[j]; } \
        if (fk > fmax_) fmax_ = fk;                                           \
        for (j = 1; j < m; j++) if (Fv[j] >= OPT_PENALTY) Fv[j] = fmax_ + fabs(fmax_) + 1.0; \
        kb = 0;                                                               \
        for (j = 1; j < m; j++) if (Fv[j] < Fv[kb]) kb = j;                   \
        for (i = 0; i < n; i++) { xk[i] = Y[kb * n + i]; g[i] = 0.0; }        \
        fk = Fv[kb]; c0 = fk;                                                 \
        memset(H, 0, (size_t) n * (size_t) n * sizeof *H);                    \
        (void) tr_update(n, m, Y, Fv, xk, delta, &c0, g, H, W, rhs, sol, yh); \
        good = 0;                                                             \
    } while (0)

    for (i = 0; i < n; i++) xk[i] = clamp01(ubest[i]);
    fk = opt_eval(c, xk, NULL);
    c->status = OPT_ST_MAXITER;
    if (fk >= OPT_PENALTY) {
        /* the start does not solve: look at the axis points for one that does */
        tr_axis_set(n, xk, delta, Y);
        for (j = 1; j < m; j++) {
            double f = opt_eval(c, &Y[j * n], NULL);
            if (f < fk) { fk = f; for (i = 0; i < n; i++) xn[i] = Y[j * n + i]; nsol = 1; }
        }
        if (!nsol) {                     /* nothing solves: the epilogue's NO SOLUTION */
            for (i = 0; i < n; i++) ubest[i] = xk[i];
            *fbest = fk;
            goto tr_done;
        }
        for (i = 0; i < n; i++) xk[i] = xn[i];
    }
    TR_REBUILD();

    for (iter = 0; iter < c->maxiter; iter++) {
        double pred, dn = 0.0, ftol, fn, rho;
        int far = -1;
        double fard = 2.0 * delta;

        /* E-536 (hunt bug 17): poll the interrupt at the loop top */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at iteration %d\n", iter);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }

        for (i = 0; i < n; i++) {
            lo[i] = -delta > -xk[i] ? -delta : -xk[i];
            hi[i] = delta < 1.0 - xk[i] ? delta : 1.0 - xk[i];
        }
        tr_box_qp(n, g, H, lo, hi, d);
        pred = -tr_q(n, g, H, d);
        for (i = 0; i < n; i++) if (fabs(d[i]) > dn) dn = fabs(d[i]);
        ftol = c->tol * (fabs(fk) + c->tol);

        if (pred <= ftol || dn < 1e-14) {
            /* the model expects nothing worth an evaluation. It is trusted only
             * where its points are: bring in the farthest one that is more
             * than two radii away, and when none is left go down a decade */
            for (j = 0; j < m; j++) {
                double dist;
                if (j == kb) continue;
                TR_DIST(j, xk, dist);
                if (dist > fard) { fard = dist; far = j; }
            }
            if (far < 0) {
                /* every point is within two radii. Done when the radius is at
                 * -tol, or when the model has just proven itself: the last
                 * trial step delivered what it predicted (ratio within a
                 * quarter of 1), so its "nothing left" can be believed at this
                 * radius without walking down five decades to confirm it */
                if (delta <= dend || good) { c->status = OPT_ST_CONVERGED; break; }
                delta *= 0.1;
                if (delta < dend) delta = dend;
                if (c->verbose)
                    fprintf(cp_out, "  iter %-3d  cost %.6g  radius %.3g  (model minimum; %d evals)\n",
                            iter + 1, fk, delta, c->nevals);
                continue;
            }
            /* a geometry step: a point at the radius along the next axis */
            {
                int tries, placed = 0;
                for (tries = 0; tries < 2 * n && !placed; tries++, geom++) {
                    int ax = (geom / 2) % n, dup = 0;
                    double sgn = (geom % 2) ? -1.0 : 1.0, v = xk[ax] + sgn * delta;
                    if (v < 0.0 || v > 1.0) continue;
                    for (i = 0; i < n; i++) xn[i] = xk[i];
                    xn[ax] = v;
                    for (j = 0; j < m && !dup; j++) {
                        double dist;
                        if (j == far) continue;
                        TR_DIST(j, xn, dist);
                        dup = dist < 1e-3 * delta;
                    }
                    placed = !dup;
                }
                if (!placed) {           /* every axis point is taken: drop a decade */
                    if (delta <= dend) { c->status = OPT_ST_CONVERGED; break; }
                    delta *= 0.1;
                    if (delta < dend) delta = dend;
                    continue;
                }
            }
            fn = opt_eval(c, xn, NULL);
            if (fn >= OPT_PENALTY) { double fmax_ = fk;
                for (j = 0; j < m; j++) if (Fv[j] > fmax_) fmax_ = Fv[j];
                fn = fmax_ + fabs(fmax_) + 1.0; }
            for (i = 0; i < n; i++) Y[far * n + i] = xn[i];
            Fv[far] = fn;
            if (fn < fk) {
                double st[OPT_MAXP];
                for (i = 0; i < n; i++) st[i] = xn[i] - xk[i];
                c0 += tr_q(n, g, H, st);
                for (i = 0; i < n; i++) { double hd = 0.0;
                    for (j = 0; j < n; j++) hd += H[i * n + j] * st[j];
                    g[i] += hd; }
                for (i = 0; i < n; i++) xk[i] = xn[i];
                fk = fn; kb = far;
            }
            upd = tr_update(n, m, Y, Fv, xk, delta, &c0, g, H, W, rhs, sol, yh);
            if (upd != 1) TR_REBUILD();
            if (c->verbose)
                fprintf(cp_out, "  iter %-3d  cost %.6g  radius %.3g  (geometry%s; %d evals)\n",
                        iter + 1, fk, delta, upd == 1 ? "" : upd == 0 ? ", set rebuilt: singular" : ", set rebuilt: residual", c->nevals);
            continue;
        }

        /* the trial step */
        for (i = 0; i < n; i++) xn[i] = clamp01(xk[i] + d[i]);
        fn = opt_eval(c, xn, NULL);
        if (fn >= OPT_PENALTY) {         /* no solution there: refuse, come closer */
            delta = 0.5 * (dn < delta ? dn : delta);
            if (delta < dend) { c->status = OPT_ST_CONVERGED; break; }
            continue;
        }
        rho = (fk - fn) / pred;
        {
            /* the trial point replaces the point farthest from the centre-to-be */
            const double *cen = fn < fk ? xn : xk;
            int drop = -1;
            double dd = -1.0;
            for (j = 0; j < m; j++) {
                double dist;
                if (j == kb && fn >= fk) continue;
                TR_DIST(j, cen, dist);
                if (dist > dd) { dd = dist; drop = j; }
            }
            for (i = 0; i < n; i++) Y[drop * n + i] = xn[i];
            Fv[drop] = fn;
            if (fn < fk) {
                c0 += tr_q(n, g, H, d);
                for (i = 0; i < n; i++) { double hd = 0.0;
                    for (j = 0; j < n; j++) hd += H[i * n + j] * d[j];
                    g[i] += hd; }
                for (i = 0; i < n; i++) xk[i] = xn[i];
                fk = fn; kb = drop;
            }
        }
        if (rho >= 0.7 && dn >= 0.99 * delta) delta = 2.0 * delta < 0.5 ? 2.0 * delta : 0.5;
        else if (rho < 0.1)                   delta = 0.5 * dn > 0.1 * delta ? 0.5 * dn : 0.1 * delta;
        good = fabs(rho - 1.0) <= 0.25;
        upd = tr_update(n, m, Y, Fv, xk, delta, &c0, g, H, W, rhs, sol, yh);
        if (upd != 1) TR_REBUILD();
        if (c->verbose)
            fprintf(cp_out, "  iter %-3d  cost %.6g  radius %.3g  ratio %.2f%s  (%d evals)\n",
                    iter + 1, fk, delta, rho, upd == 1 ? "" : upd == 0 ? "  (set rebuilt: singular)" : "  (set rebuilt: residual)", c->nevals);
        if (delta < dend) { c->status = OPT_ST_CONVERGED; break; }
    }
#undef TR_DIST
#undef TR_REBUILD

    for (i = 0; i < n; i++) ubest[i] = xk[i];
    *fbest = fk;
tr_done:
    tfree(Y); tfree(yh); tfree(Fv); tfree(H); tfree(W); tfree(rhs); tfree(sol);
}

/* ==================== Enhancement-764: CMA-ES ============================== */

/* Enhancement-764: a standard normal deviate (Box-Muller on two uniforms; the
 * first is taken in (0, 1] so the log is finite). Same stream as opt_rand, so
 * a run is reproducible from `-seed`. */
static double opt_gauss(void)
{
    double u1 = 1.0 - opt_rand(), u2 = opt_rand();
    return sqrt(-2.0 * log(u1)) * cos(6.283185307179586 * u2);
}

/* Enhancement-764: cyclic Jacobi eigendecomposition of the symmetric n x n
 * matrix A (row-major; destroyed). On return d[i] is the i-th eigenvalue and
 * column i of V its eigenvector, so A = V diag(d) V'. n is at most OPT_MAXP
 * (128), where the O(n^3) sweeps cost microseconds against an analysis. */
static void opt_jacobi(int n, double *A, double *V, double *d)
{
    int i, j, k, sweep;

    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++)
            V[i * n + j] = (i == j) ? 1.0 : 0.0;
    for (sweep = 0; sweep < 100; sweep++) {
        double off = 0.0, diag = 0.0;
        for (i = 0; i < n; i++) {
            diag += A[i * n + i] * A[i * n + i];
            for (j = i + 1; j < n; j++)
                off += A[i * n + j] * A[i * n + j];
        }
        if (off <= 1e-30 * (diag + 1e-300))
            break;
        for (i = 0; i < n - 1; i++)
            for (j = i + 1; j < n; j++) {
                double apq = A[i * n + j], theta, t, cs, sn;
                if (fabs(apq) < 1e-300)
                    continue;
                theta = 0.5 * (A[j * n + j] - A[i * n + i]) / apq;
                t  = (theta >= 0.0 ? 1.0 : -1.0) / (fabs(theta) + sqrt(theta * theta + 1.0));
                cs = 1.0 / sqrt(t * t + 1.0);
                sn = t * cs;
                for (k = 0; k < n; k++) {              /* columns i, j */
                    double aki = A[k * n + i], akj = A[k * n + j];
                    A[k * n + i] = cs * aki - sn * akj;
                    A[k * n + j] = sn * aki + cs * akj;
                }
                for (k = 0; k < n; k++) {              /* rows i, j */
                    double aik = A[i * n + k], ajk = A[j * n + k];
                    A[i * n + k] = cs * aik - sn * ajk;
                    A[j * n + k] = sn * aik + cs * ajk;
                }
                A[i * n + j] = A[j * n + i] = 0.0;
                for (k = 0; k < n; k++) {              /* V = V J */
                    double vki = V[k * n + i], vkj = V[k * n + j];
                    V[k * n + i] = cs * vki - sn * vkj;
                    V[k * n + j] = sn * vki + cs * vkj;
                }
            }
    }
    for (i = 0; i < n; i++)
        d[i] = A[i * n + i];
}

/* Enhancement-764: Covariance Matrix Adaptation Evolution Strategy over the np
 * normalized parameters (Hansen's (mu/mu_w, lambda)-CMA-ES with the published
 * default constants). Each generation samples lambda candidates from
 * N(m, sigma^2 C), RANKS them by cost, recombines the best mu into the new mean
 * with log-decreasing weights, and adapts the covariance C (a rank-one update
 * along the evolution path p_c and a rank-mu update from the selected steps)
 * and the step size sigma (cumulative step-size adaptation on the conjugate
 * path p_s against its expected length under random selection).
 *
 * Why a seventh method: it is rank-based, so it never reads a cost -- a failed
 * evaluation (OPT_PENALTY) is the worst rank and steers the distribution away
 * without poisoning a mean or a temperature, and a generation in which nothing
 * solved moves nothing (three in a row with no solution ever found end the
 * search, which the epilogue reports as NO SOLUTION); and it learns the scale
 * and the orientation of the valley, so a knob spanning decades needs no log
 * scaling and correlated knobs need no rotation of the box, where Nelder-Mead's
 * axis-aligned simplex, LM's fixed finite-difference step and a swarm that
 * clamps its velocities at a wall all struggle (the 2026-09-29 hunt's O1 and
 * O2). Candidates outside the cube are re-drawn a few times, then projected
 * onto it and ranked with a penalty on the squared distance moved (scaled by
 * the generation's spread of solved costs), so a mean may settle ON a bound
 * when the optimum is there without the distribution collapsing early.
 *
 * lambda is -swarmsize (default 4 + floor(3 ln n)), mu = lambda/2, sigma_0 = 0.3
 * in the unit cube, candidate 0 of the first generation is the start point.
 * Stops CONVERGED when sigma times the longest axis of C is below -tol (the
 * distribution has shrunk to the tolerance, in the cube), or -- the published
 * TolFun rule -- when the costs of the current generation and the best costs
 * of the last 10 + 30 n / lambda generations all lie within -tol of each other
 * (the swarm's test on the all-time best would fire while the distribution is
 * still learning the valley: a start on its floor sees worse samples for many
 * generations, legitimately); MAXITER when the generations run out. On exit ubest holds the best point and *fbest its
 * cost. Works for scalar, least-squares and centering objectives alike. */
static void cma_es(struct optctx *c, double *ubest, double *fbest)
{
    const int n = c->np, lam = c->swarmsize, mu = lam / 2;
    double *C = TMALLOC(double, (size_t) n * (size_t) n);    /* covariance        */
    double *B = TMALLOC(double, (size_t) n * (size_t) n);    /* its eigenvectors  */
    double *A = TMALLOC(double, (size_t) n * (size_t) n);    /* scratch copy      */
    double *D = TMALLOC(double, n);                          /* sqrt eigenvalues  */
    double *X = TMALLOC(double, (size_t) lam * (size_t) n);  /* candidates        */
    double *Y = TMALLOC(double, (size_t) lam * (size_t) n);  /* their steps / sigma */
    double *F = TMALLOC(double, lam);                        /* costs             */
    double *P = TMALLOC(double, lam);                        /* boundary penalties */
    double *R = TMALLOC(double, lam);                        /* ranking keys      */
    double *w = TMALLOC(double, mu);                         /* recombination weights */
    int    *idx = TMALLOC(int, lam);
    double m[OPT_MAXP], pc[OPT_MAXP], ps[OPT_MAXP], yw[OPT_MAXP], z[OPT_MAXP],
           tmp[OPT_MAXP], gb[OPT_MAXP];
    double sigma = 0.3, sumw = 0.0, mueff = 0.0, cc, cs, c1, cmu, damps, chiN;
    double gf = 1e300, dmax = 1.0, dmin = 1.0;
    const int nhist = 10 + (30 * n) / lam;                   /* TolFun window     */
    double *hist = TMALLOC(double, nhist);                   /* generation bests  */
    int i, j, k, gen, allfail = 0, ngen = 0;

    opt_srand(c->seed);
    for (i = 0; i < mu; i++) { w[i] = log(mu + 0.5) - log(i + 1.0); sumw += w[i]; }
    for (i = 0; i < mu; i++) { w[i] /= sumw; mueff += w[i] * w[i]; }
    mueff = 1.0 / mueff;
    cc    = (4.0 + mueff / n) / (n + 4.0 + 2.0 * mueff / n);
    cs    = (mueff + 2.0) / (n + mueff + 5.0);
    c1    = 2.0 / ((n + 1.3) * (n + 1.3) + mueff);
    cmu   = 2.0 * (mueff - 2.0 + 1.0 / mueff) / ((n + 2.0) * (n + 2.0) + mueff);
    if (cmu > 1.0 - c1) cmu = 1.0 - c1;
    damps = sqrt((mueff - 1.0) / (n + 1.0)) - 1.0;
    damps = 1.0 + cs + 2.0 * (damps > 0.0 ? damps : 0.0);
    chiN  = sqrt((double) n) * (1.0 - 1.0 / (4.0 * n) + 1.0 / (21.0 * n * (double) n));

    for (j = 0; j < n; j++) {
        m[j] = clamp01(ubest[j]);
        gb[j] = m[j];
        pc[j] = ps[j] = 0.0;
        D[j] = 1.0;
        for (k = 0; k < n; k++)
            C[j * n + k] = B[j * n + k] = (j == k) ? 1.0 : 0.0;
    }

    c->status = OPT_ST_MAXITER;          /* E-762: unless a break below says otherwise */
    for (gen = 0; gen < c->maxiter; gen++) {
        double flo = 1e300, fhi = -1e300, scale, psn;
        int nfin = 0, hsig;

        /* E-536 (hunt bug 17): poll the interrupt at the loop top, as the
         * other methods do; the best point so far is reported by the epilogue */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at generation %d\n", gen);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }

        /* sample lambda candidates: x = m + sigma B D z, z ~ N(0, I) */
        for (i = 0; i < lam; i++) {
            double dist2 = 0.0;
            int tries;
            for (tries = 0; tries < 10; tries++) {
                int inside = 1;
                if (gen == 0 && i == 0) {            /* the start point itself */
                    for (j = 0; j < n; j++) X[i * n + j] = m[j];
                    break;
                }
                for (k = 0; k < n; k++) z[k] = D[k] * opt_gauss();
                for (j = 0; j < n; j++) {
                    double s = 0.0;
                    for (k = 0; k < n; k++) s += B[j * n + k] * z[k];
                    X[i * n + j] = m[j] + sigma * s;
                    if (X[i * n + j] < 0.0 || X[i * n + j] > 1.0) inside = 0;
                }
                if (inside) break;
            }
            for (j = 0; j < n; j++) {                /* project; remember the move */
                double x = X[i * n + j], xc = clamp01(x);
                dist2 += (x - xc) * (x - xc);
                X[i * n + j] = xc;
                Y[i * n + j] = (xc - m[j]) / sigma;
            }
            F[i] = opt_eval(c, &X[i * n], NULL);
            P[i] = dist2;
            if (F[i] < gf) { gf = F[i]; for (j = 0; j < n; j++) gb[j] = X[i * n + j]; }
            if (F[i] < OPT_PENALTY) {
                nfin++;
                if (F[i] < flo) flo = F[i];
                if (F[i] > fhi) fhi = F[i];
            }
        }

        /* rank: solved candidates by cost plus the boundary penalty (a squared
         * distance in the cube, scaled to the generation's spread of costs so
         * it orders the projected candidates without outweighing a real
         * difference), the failed ones last, ordered by how far outside they were */
        scale = (nfin > 1 && fhi > flo) ? (fhi - flo) : (fabs(flo) > 0.0 && flo < 1e300 ? fabs(flo) : 1.0);
        for (i = 0; i < lam; i++) {
            R[i] = (F[i] >= OPT_PENALTY) ? OPT_PENALTY + P[i] : F[i] + scale * P[i];
            idx[i] = i;
        }
        for (i = 1; i < lam; i++) {                  /* insertion sort, lam <= 256 */
            int t = idx[i];
            for (j = i; j > 0 && R[idx[j - 1]] > R[t]; j--) idx[j] = idx[j - 1];
            idx[j] = t;
        }

        if (nfin == 0) {
            /* nothing solved: there is no order to learn from. Widen the
             * search a little and try again; three such generations with no
             * solution ever found end the search (the epilogue's NO SOLUTION). */
            if (++allfail >= 3 && gf >= OPT_PENALTY)
                break;
            if (sigma < 0.5) sigma *= 1.5;
            if (c->verbose)
                fprintf(cp_out, "  gen %-3d  no candidate solved  sigma %.3g  (%d evals)\n",
                        gen + 1, sigma, c->nevals);
            continue;
        }
        allfail = 0;

        /* recombine the best mu into the new mean; y_w is the mean's step */
        for (j = 0; j < n; j++) {
            double s = 0.0;
            for (i = 0; i < mu; i++) s += w[i] * X[idx[i] * n + j];
            tmp[j] = s;
        }
        for (j = 0; j < n; j++) { yw[j] = (tmp[j] - m[j]) / sigma; m[j] = tmp[j]; }

        /* p_s = (1 - c_s) p_s + sqrt(c_s (2 - c_s) mu_eff) C^-1/2 y_w,
         * with C^-1/2 = B D^-1 B' */
        for (j = 0; j < n; j++) {
            double s = 0.0;
            for (k = 0; k < n; k++) s += B[k * n + j] * yw[k];
            z[j] = s / D[j];
        }
        psn = 0.0;
        for (j = 0; j < n; j++) {
            double s = 0.0;
            for (k = 0; k < n; k++) s += B[j * n + k] * z[k];
            ps[j] = (1.0 - cs) * ps[j] + sqrt(cs * (2.0 - cs) * mueff) * s;
            psn += ps[j] * ps[j];
        }
        psn = sqrt(psn);
        hsig = psn / sqrt(1.0 - pow(1.0 - cs, 2.0 * (gen + 1))) / chiN < 1.4 + 2.0 / (n + 1.0);

        /* p_c = (1 - c_c) p_c + h_sig sqrt(c_c (2 - c_c) mu_eff) y_w */
        for (j = 0; j < n; j++)
            pc[j] = (1.0 - cc) * pc[j] + (hsig ? sqrt(cc * (2.0 - cc) * mueff) * yw[j] : 0.0);

        /* C = (1 - c_1 - c_mu) C + c_1 (p_c p_c' + (1 - h_sig) c_c (2 - c_c) C)
         *     + c_mu sum_i w_i y_i y_i' */
        for (j = 0; j < n; j++)
            for (k = j; k < n; k++) {
                double s = 0.0, v;
                for (i = 0; i < mu; i++) s += w[i] * Y[idx[i] * n + j] * Y[idx[i] * n + k];
                v = (1.0 - c1 - cmu) * C[j * n + k]
                  + c1 * (pc[j] * pc[k] + (hsig ? 0.0 : cc * (2.0 - cc)) * C[j * n + k])
                  + cmu * s;
                C[j * n + k] = C[k * n + j] = v;
            }

        /* sigma *= exp((c_s / d_s) (|p_s| / chiN - 1)) */
        sigma *= exp((cs / damps) * (psn / chiN - 1.0));

        /* the new axes: C = B diag(D^2) B' */
        memcpy(A, C, (size_t) n * (size_t) n * sizeof *A);
        opt_jacobi(n, A, B, D);
        dmax = 0.0; dmin = 1e300;
        for (j = 0; j < n; j++) {
            if (D[j] < 1e-40) D[j] = 1e-40;
            D[j] = sqrt(D[j]);
            if (D[j] > dmax) dmax = D[j];
            if (D[j] < dmin) dmin = D[j];
        }
        if (dmax > 1e7 * dmin) {         /* condition guard: nudge the flat axes */
            for (j = 0; j < n; j++) C[j * n + j] += (dmax * 1e-7) * (dmax * 1e-7);
        }

        if (c->verbose)
            fprintf(cp_out, "  gen %-3d  best cost %.6g  sigma %.3g  axis ratio %.3g  (%d evals)\n",
                    gen + 1, gf, sigma, dmax / dmin, c->nevals);

        /* stop: the distribution has shrunk to the tolerance in the cube ... */
        if (sigma * dmax < c->tol) { c->status = OPT_ST_CONVERGED; break; }
        /* ... or nothing is left to resolve (TolFun): this generation's solved
         * costs and the generation bests of the window all within tolerance */
        hist[ngen % nhist] = flo;
        ngen++;
        if (ngen >= nhist) {
            double hlo = 1e300, hhi = -1e300;
            for (i = 0; i < nhist; i++) {
                if (hist[i] < hlo) hlo = hist[i];
                if (hist[i] > hhi) hhi = hist[i];
            }
            if (hhi - hlo <= c->tol * (fabs(gf) + c->tol) &&
                fhi - flo <= c->tol * (fabs(gf) + c->tol)) {
                c->status = OPT_ST_CONVERGED;
                break;
            }
        }
    }

    for (j = 0; j < n; j++) ubest[j] = gb[j];
    *fbest = gf;
    tfree(C); tfree(B); tfree(A); tfree(D); tfree(X); tfree(Y);
    tfree(F); tfree(P); tfree(R); tfree(w); tfree(idx); tfree(hist);
}



/* ==================== Enhancement-765: Bayesian optimization =============== */

/* Enhancement-765: a Nelder-Mead simplex on a callback, for the surrogate's own
 * minimisations (the marginal likelihood over the hyperparameters, the negated
 * expected improvement over the cube). Standard coefficients; the box [lo, hi]
 * is optional and enforced by clamping. On return x holds the best point and
 * the best value is returned. Kept apart from nelder_mead() so that method, and
 * every report it prints, stays byte for byte what it was. */
static double nm_callback(int n, double *x, double (*fn)(const double *, void *), void *arg,
                          double step, int maxiter, double tol, const double *lo, const double *hi)
{
    const int m = n + 1;
    double *s = TMALLOC(double, (size_t) m * (size_t) n), *fv = TMALLOC(double, m);
    double *cent = TMALLOC(double, n), *xr = TMALLOC(double, n), *xe = TMALLOC(double, n),
           *xc = TMALLOC(double, n);
    int i, j, iter, ilo, ihi, inh;
    double best;

#define NMC_CLAMP(v, j) (lo && hi ? ((v) < lo[j] ? lo[j] : (v) > hi[j] ? hi[j] : (v)) : (v))
    for (j = 0; j < n; j++) s[j] = NMC_CLAMP(x[j], j);
    fv[0] = fn(s, arg);
    for (i = 1; i < m; i++) {
        for (j = 0; j < n; j++) s[i * n + j] = s[j];
        s[i * n + i - 1] = NMC_CLAMP(s[i - 1] + step, i - 1);
        if (s[i * n + i - 1] == s[i - 1]) s[i * n + i - 1] = NMC_CLAMP(s[i - 1] - step, i - 1);
        fv[i] = fn(&s[i * n], arg);
    }
    for (iter = 0; iter < maxiter; iter++) {
        ilo = ihi = 0;
        for (i = 1; i < m; i++) { if (fv[i] < fv[ilo]) ilo = i; if (fv[i] > fv[ihi]) ihi = i; }
        inh = (ihi == 0) ? 1 : 0;
        for (i = 0; i < m; i++) if (i != ihi && fv[i] > fv[inh]) inh = i;
        if (fv[ihi] - fv[ilo] <= tol * (fabs(fv[ilo]) + tol)) break;
        for (j = 0; j < n; j++) {
            double sum = 0.0;
            for (i = 0; i < m; i++) if (i != ihi) sum += s[i * n + j];
            cent[j] = sum / n;
            xr[j] = NMC_CLAMP(cent[j] + (cent[j] - s[ihi * n + j]), j);
        }
        {
            double fr = fn(xr, arg);
            if (fr < fv[ilo]) {
                double fe;
                for (j = 0; j < n; j++) xe[j] = NMC_CLAMP(cent[j] + 2.0 * (xr[j] - cent[j]), j);
                fe = fn(xe, arg);
                if (fe < fr) { memcpy(&s[ihi * n], xe, (size_t) n * sizeof *xe); fv[ihi] = fe; }
                else         { memcpy(&s[ihi * n], xr, (size_t) n * sizeof *xr); fv[ihi] = fr; }
            } else if (fr < fv[inh]) {
                memcpy(&s[ihi * n], xr, (size_t) n * sizeof *xr); fv[ihi] = fr;
            } else {
                double fc;
                for (j = 0; j < n; j++) xc[j] = NMC_CLAMP(cent[j] + 0.5 * (s[ihi * n + j] - cent[j]), j);
                fc = fn(xc, arg);
                if (fc < fv[ihi]) {
                    memcpy(&s[ihi * n], xc, (size_t) n * sizeof *xc); fv[ihi] = fc;
                } else {                                     /* shrink toward the best */
                    for (i = 0; i < m; i++) if (i != ilo) {
                        for (j = 0; j < n; j++)
                            s[i * n + j] = NMC_CLAMP(s[ilo * n + j] + 0.5 * (s[i * n + j] - s[ilo * n + j]), j);
                        fv[i] = fn(&s[i * n], arg);
                    }
                }
            }
        }
    }
#undef NMC_CLAMP
    ilo = 0;
    for (i = 1; i < m; i++) if (fv[i] < fv[ilo]) ilo = i;
    memcpy(x, &s[ilo * n], (size_t) n * sizeof *x);
    best = fv[ilo];
    tfree(s); tfree(fv); tfree(cent); tfree(xr); tfree(xe); tfree(xc);
    return best;
}

/* Enhancement-765: the Gaussian-process surrogate. A Matern-5/2 kernel with one
 * length scale per knob (in cube units: a knob the objective does not depend on
 * gets a long one, and the surrogate drops it), a signal variance and a noise
 * floor; the targets are the costs, log-transformed when they are all positive
 * and span two decades or more (a -target sum of squares does near its optimum),
 * standardised over the solved points, with a failed evaluation imputed at the
 * worst solved value plus three standard deviations. The kernel matrix is
 * N x N for N evaluations; a Cholesky factorisation at N <= 2000 is nothing. */
struct gp {
    int    n, N;
    const double *X;          /* N x n, the evaluated points (owned by the caller) */
    double *y;                /* N standardised targets                             */
    double *L;                /* N x N Cholesky factor of K + sn2 I                 */
    double *alpha;            /* K^-1 y                                             */
    double *ell;              /* n length scales                                    */
    double sf2, sn2;          /* signal and noise variance                          */
};

static double gp_kern(const struct gp *g, const double *a, const double *b)
{
    double r2 = 0.0, r, s5;
    int j;
    for (j = 0; j < g->n; j++) {
        double d = (a[j] - b[j]) / g->ell[j];
        r2 += d * d;
    }
    r  = sqrt(r2);
    s5 = 2.23606797749979 * r;
    return g->sf2 * (1.0 + s5 + 5.0 * r2 / 3.0) * exp(-s5);
}

/* factor K + sn2 I and solve for alpha; 0 when the matrix is not positive definite */
static int gp_fit(struct gp *g)
{
    const int N = g->N;
    int i, j, k;
    for (i = 0; i < N; i++)
        for (j = 0; j <= i; j++)
            g->L[i * N + j] = gp_kern(g, &g->X[i * g->n], &g->X[j * g->n])
                            + (i == j ? g->sn2 + 1e-10 : 0.0);
    for (j = 0; j < N; j++) {                              /* Cholesky, lower */
        double d = g->L[j * N + j];
        for (k = 0; k < j; k++) d -= g->L[j * N + k] * g->L[j * N + k];
        if (d <= 0.0 || d != d) return 0;
        d = sqrt(d);
        g->L[j * N + j] = d;
        for (i = j + 1; i < N; i++) {
            double s = g->L[i * N + j];
            for (k = 0; k < j; k++) s -= g->L[i * N + k] * g->L[j * N + k];
            g->L[i * N + j] = s / d;
        }
    }
    for (i = 0; i < N; i++) {                              /* L z = y */
        double s = g->y[i];
        for (k = 0; k < i; k++) s -= g->L[i * N + k] * g->alpha[k];
        g->alpha[i] = s / g->L[i * N + i];
    }
    for (i = N - 1; i >= 0; i--) {                         /* L' alpha = z */
        double s = g->alpha[i];
        for (k = i + 1; k < N; k++) s -= g->L[k * N + i] * g->alpha[k];
        g->alpha[i] = s / g->L[i * N + i];
    }
    return 1;
}

/* the log marginal likelihood of the fitted surrogate */
static double gp_lml(const struct gp *g)
{
    double s = 0.0, ld = 0.0;
    int i;
    for (i = 0; i < g->N; i++) {
        s  += g->y[i] * g->alpha[i];
        ld += log(g->L[i * g->N + i]);
    }
    return -0.5 * s - ld - 0.5 * g->N * 1.8378770664093453;
}

/* predictive mean and variance of the latent function at x */
static void gp_predict(const struct gp *g, const double *x, double *mean, double *var)
{
    const int N = g->N;
    double *kv = TMALLOC(double, N);
    double m = 0.0, v = 0.0;
    int i, k;
    for (i = 0; i < N; i++) {
        kv[i] = gp_kern(g, x, &g->X[i * g->n]);
        m += kv[i] * g->alpha[i];
    }
    for (i = 0; i < N; i++) {                              /* v = L^-1 k */
        double s = kv[i];
        for (k = 0; k < i; k++) s -= g->L[i * N + k] * kv[k];
        kv[i] = s / g->L[i * N + i];
        v += kv[i] * kv[i];
    }
    *mean = m;
    *var  = g->sf2 - v;
    if (*var < 1e-12) *var = 1e-12;
    tfree(kv);
}

/* hyperparameters as theta = (log ell_1..n, log sf2, log sn2), boxed */
static void gp_set_theta(struct gp *g, const double *th)
{
    int j;
    for (j = 0; j < g->n; j++) {
        double e = exp(th[j]);
        g->ell[j] = e < 5e-2 ? 5e-2 : e > 1e2 ? 1e2 : e;   /* a twentieth of the box: finer is the local method's */
    }
    g->sf2 = exp(th[g->n]);     if (g->sf2 < 1e-3) g->sf2 = 1e-3; if (g->sf2 > 1e3) g->sf2 = 1e3;
    g->sn2 = exp(th[g->n + 1]); if (g->sn2 < 1e-8) g->sn2 = 1e-8; if (g->sn2 > 1.0) g->sn2 = 1.0;
}

static double gp_neg_lml_cb(const double *th, void *arg)
{
    struct gp *g = (struct gp *) arg;
    gp_set_theta(g, th);
    if (!gp_fit(g)) return 1e300;
    return -gp_lml(g);
}

/* expected improvement below ybest (standardised units), with a small
 * exploration offset; the callback returns its negative for the minimiser */
struct ei_arg { const struct gp *g; double ybest; };

static double gp_ei(const struct gp *g, const double *x, double ybest)
{
    double m, v, s, z, cdf, pdf;
    gp_predict(g, x, &m, &v);
    s = sqrt(v);
    z = (ybest - 0.01 - m) / s;
    cdf = 0.5 * erfc(-z / 1.4142135623730951);
    pdf = exp(-0.5 * z * z) / 2.5066282746310002;
    return (ybest - 0.01 - m) * cdf + s * pdf;
}

static double gp_neg_ei_cb(const double *x, void *arg)
{
    const struct ei_arg *a = (const struct ei_arg *) arg;
    return -gp_ei(a->g, x, a->ybest);
}

/* Latin-hypercube points in the cube on E-194's stream: for each knob one
 * stratum per point, shuffled, a uniform draw inside the stratum */
static void opt_lhs(int npts, int n, double *X)
{
    int j, s, t;
    for (j = 0; j < n; j++) {
        for (s = 0; s < npts; s++) X[s * n + j] = (double) s;
        for (s = npts - 1; s > 0; s--) {
            double tmp;
            t = (int) (opt_rand() * (s + 1));
            if (t > s) t = s;
            tmp = X[s * n + j]; X[s * n + j] = X[t * n + j]; X[t * n + j] = tmp;
        }
        for (s = 0; s < npts; s++)
            X[s * n + j] = clamp01((X[s * n + j] + opt_rand()) / npts);
    }
}

/* Enhancement-765: Bayesian optimization over the np normalized parameters.
 * When one evaluation is a transient of seconds, the number of evaluations is
 * the whole cost, and this method spends its own arithmetic to save them: a
 * Gaussian-process surrogate is fitted to every point evaluated so far and the
 * next point maximises the EXPECTED IMPROVEMENT, which trades the surrogate's
 * predicted gain against its uncertainty. On a smooth objective in up to a
 * dozen knobs it reaches the optimum in tens of evaluations where the swarm and
 * DE spend thousands and the simplex a few hundred.
 *
 * The design, kept to what the size of the problem needs: an initial design of
 * 2n + 2 Latin-hypercube points (the start point among them); the surrogate of
 * struct gp above, its hyperparameters by maximising the marginal likelihood
 * with nm_callback in log space (every evaluation while there are fewer than 20,
 * every fifth after); the acquisition maximised on the surrogate over 400 + 100n
 * Latin-hypercube candidates and perturbations of the best point, the three
 * best refined with nm_callback -- thousands of surrogate evaluations cost less
 * than one analysis. A failed evaluation is imputed at the worst solved cost
 * plus three standard deviations, so the surrogate learns that region is bad
 * without a discontinuity; a design in which nothing solved is redrawn (three
 * times at most, then the epilogue's NO SOLUTION).
 *
 * -maxiter is the EVALUATION budget here (the report says "evaluations"), and
 * the stop tests are CONVERGED when the largest expected improvement in
 * standardised units falls below -tol, or when the best cost has not moved by
 * -tol over the last 10 + 2n evaluations while that improvement is below 1e-2;
 * MAXITER when the budget runs out; and -- since a Gaussian process locates the
 * basin in tens of evaluations but cannot resolve a cost that falls by orders
 * of magnitude at the optimum -- when it expects less than a thousandth of the
 * cost spread twice running, or a criterion is met with budget left, the rest
 * of the budget goes to the local method (Nelder-Mead, or LM for a -target
 * fit) through E-764's polish. The report adds what no other method can: the
 * surrogate's predicted cost at the optimum with its uncertainty, and the
 * length scales -- a knob's is "(no dependence seen)" above ten box widths,
 * which is E-762's `unchanged` case with a diagnosis. On exit ubest holds the best
 * point and *fbest its cost; scalar, least-squares and centering objectives. */
static void bayes_opt(struct optctx *c, double *ubest, double *fbest)
{
    const int n = c->np, budget = c->maxiter;
    int n0 = 2 * n + 2;
    double *X = TMALLOC(double, (size_t) budget * (size_t) n);   /* evaluated points */
    double *F = TMALLOC(double, budget);                         /* their raw costs  */
    struct gp g;
    int handoff_reason = 0;
    double th[OPT_MAXP + 2], gb[OPT_MAXP], xn[OPT_MAXP];
    double gf = 1e300, ymean = 0.0, ystd = 1.0, eimax = 0.0, tstart = 0.0;
    int N = 0, i, j, k, rounds = 0, uselog = 0, stall = 0, fitted = 0, lowei = 0;
    double last_improved_f = 1e300;

    if (n0 > budget) n0 = budget;
    memset(&g, 0, sizeof g);
    g.n = n; g.X = X;
    g.y     = TMALLOC(double, budget);
    g.L     = TMALLOC(double, (size_t) budget * (size_t) budget);
    g.alpha = TMALLOC(double, budget);
    g.ell   = TMALLOC(double, n);
    for (j = 0; j < n; j++) { th[j] = log(0.3); g.ell[j] = 0.3; gb[j] = clamp01(ubest[j]); }
    th[n] = 0.0; th[n + 1] = log(1e-4); g.sf2 = 1.0; g.sn2 = 1e-4;

    opt_srand(c->seed);
    c->cap_is_evals = 1;
    c->status = OPT_ST_MAXITER;

#define BO_EVAL(idx) do {                                                   \
        F[idx] = opt_eval(c, &X[(idx) * n], NULL);                          \
        if (F[idx] < gf) { gf = F[idx]; for (j = 0; j < n; j++) gb[j] = X[(idx) * n + j]; } \
        if (c->verbose && fitted)                                           \
            fprintf(cp_out, "  eval %-3d  cost %.6g  best %.6g  max EI %.3g\n", (idx) + 1, F[idx], gf, eimax); \
        else if (c->verbose)                                                \
            fprintf(cp_out, "  eval %-3d  cost %.6g  best %.6g  (design)\n", (idx) + 1, F[idx], gf); \
    } while (0)

    /* the initial design: the start point and 2n + 1 Latin-hypercube points */
    opt_lhs(n0, n, X);
    for (j = 0; j < n; j++) X[j] = clamp01(ubest[j]);
    for (i = 0; i < n0; i++) {
        if (ft_intrpt) break;
        BO_EVAL(N);
        N++;
    }
    (void) tstart;

    while (N < budget) {
        int nsol = 0, redo = 0;
        double tmin = 1e300, tmax = -1e300, tsum = 0.0, tsq = 0.0, tfail;
        double fmin = 1e300, fmax = -1e300;

        /* E-536 (hunt bug 17): one analysis can be seconds here -- poll before
         * every evaluation, not once per population */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at evaluation %d\n", N);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }

        /* the targets: log when all solved costs are positive and span two
         * decades, standardised over the solved points, failures imputed */
        for (i = 0; i < N; i++)
            if (F[i] < OPT_PENALTY) { nsol++; if (F[i] < fmin) fmin = F[i]; if (F[i] > fmax) fmax = F[i]; }
        if (nsol == 0) {
            /* nothing solved yet: redraw the design (three rounds at most) */
            if (++rounds >= 3) break;
            redo = (N + n0 <= budget) ? n0 : budget - N;
            if (redo <= 0) break;
            opt_lhs(redo, n, &X[N * n]);
            for (i = 0; i < redo; i++) { if (ft_intrpt) break; BO_EVAL(N); N++; }
            continue;
        }
        uselog = (fmin > 0.0 && fmax / fmin >= 100.0);
        for (i = 0; i < N; i++) {
            if (F[i] >= OPT_PENALTY) continue;
            double t = uselog ? log(F[i]) : F[i];
            g.y[i] = t;
            tsum += t; tsq += t * t;
            if (t < tmin) tmin = t; if (t > tmax) tmax = t;
        }
        ymean = tsum / nsol;
        ystd  = sqrt(tsq / nsol - ymean * ymean > 0.0 ? tsq / nsol - ymean * ymean : 0.0);
        if (ystd < 1e-300 * (fabs(ymean) + 1.0) || ystd != ystd) ystd = fabs(ymean) > 0.0 ? 1e-6 * fabs(ymean) : 1.0;
        tfail = tmax + 3.0 * ystd;
        for (i = 0; i < N; i++)
            g.y[i] = ((F[i] >= OPT_PENALTY ? tfail : g.y[i]) - ymean) / ystd;
        g.N = N;

        /* the hyperparameters by marginal likelihood, then the fit */
        if (N <= 20 || (N % 5) == 0 || !fitted) {
            double th0[OPT_MAXP + 2];
            memcpy(th0, th, (size_t) (n + 2) * sizeof *th);
            (void) nm_callback(n + 2, th0, gp_neg_lml_cb, &g, 0.7, 60 + 20 * n, 1e-4, NULL, NULL);
            if (gp_neg_lml_cb(th0, &g) < 1e300) memcpy(th, th0, (size_t) (n + 2) * sizeof *th);
        }
        gp_set_theta(&g, th);
        for (k = 0; k < 6 && !gp_fit(&g); k++) {          /* not PD: more noise */
            th[n + 1] += log(10.0);
            gp_set_theta(&g, th);
        }
        if (k >= 6) break;
        fitted = 1;

        /* the acquisition: expected improvement over Latin-hypercube candidates
         * and perturbations of the best point, the three best refined */
        {
            const int ncand = 400 + 100 * n, npert = 20, ntot = ncand + npert;
            double *C = TMALLOC(double, (size_t) ntot * (size_t) n);
            double *E = TMALLOC(double, ntot);
            struct ei_arg ea;
            double ybest = 1e300, lo01[OPT_MAXP], hi01[OPT_MAXP];
            int top[3] = { -1, -1, -1 }, t;
            for (i = 0; i < N; i++) if (F[i] < OPT_PENALTY && g.y[i] < ybest) ybest = g.y[i];
            ea.g = &g; ea.ybest = ybest;
            for (j = 0; j < n; j++) { lo01[j] = 0.0; hi01[j] = 1.0; }
            opt_lhs(ncand, n, C);
            for (i = ncand; i < ntot; i++)
                for (j = 0; j < n; j++)
                    C[i * n + j] = clamp01(gb[j] + (i < ncand + npert / 2 ? 0.05 : 0.01) * opt_gauss());
            for (i = 0; i < ntot; i++) {
                E[i] = gp_ei(&g, &C[i * n], ybest);
                for (t = 0; t < 3; t++)
                    if (top[t] < 0 || E[i] > E[top[t]]) {
                        int u;
                        for (u = 2; u > t; u--) top[u] = top[u - 1];
                        top[t] = i;
                        break;
                    }
            }
            eimax = -1.0;
            for (t = 0; t < 3; t++) {
                double xt[OPT_MAXP], e;
                if (top[t] < 0) continue;
                memcpy(xt, &C[top[t] * n], (size_t) n * sizeof *xt);
                e = -nm_callback(n, xt, gp_neg_ei_cb, &ea, 0.05, 40, 1e-6, lo01, hi01);
                if (e > eimax) { eimax = e; memcpy(xn, xt, (size_t) n * sizeof *xn); }
            }
            /* never re-evaluate a point already known: fall back to the best
             * candidate that is new */
            for (t = 0; t < ntot; t++) {
                int dup = 0;
                for (i = 0; i < N && !dup; i++) {
                    double d2 = 0.0;
                    for (j = 0; j < n; j++) d2 += (xn[j] - X[i * n + j]) * (xn[j] - X[i * n + j]);
                    dup = d2 < 1e-16;
                }
                if (!dup) break;
                { int bi = -1; for (i = 0; i < ntot; i++) if (E[i] >= 0.0 && (bi < 0 || E[i] > E[bi])) bi = i;
                  if (bi < 0) break;
                  memcpy(xn, &C[bi * n], (size_t) n * sizeof *xn); E[bi] = -1.0; }
            }
            tfree(C); tfree(E);
        }

        /* stop: nothing left to gain (the surrogate's own criterion) ... */
        if (eimax < c->tol) { c->status = OPT_ST_CONVERGED; handoff_reason = 0; break; }
        /* ... or it expects less than a thousandth of the cost spread, twice
         * running, once the design and a few steps are behind it -- the point
         * at which a local method finishes faster than another surrogate step */
        lowei = (eimax < 1e-3) ? lowei + 1 : 0;
        if (lowei >= 2 && N >= n0 + 2 + n) { c->status = OPT_ST_CONVERGED; handoff_reason = 1; break; }
        /* ... or the best has not moved for 10 + 2n evaluations while the
         * surrogate expects little */
        if (last_improved_f - gf <= c->tol * (fabs(gf) + c->tol)) stall++;
        else { stall = 0; last_improved_f = gf; }
        if (stall >= 10 + 2 * n && eimax < 1e-2) { c->status = OPT_ST_CONVERGED; handoff_reason = 2; break; }

        memcpy(&X[N * n], xn, (size_t) n * sizeof *xn);
        BO_EVAL(N);
        N++;
    }
#undef BO_EVAL

    /* the hand-off: a Gaussian process locates the basin in tens of evaluations
     * and cannot resolve a cost that falls by orders of magnitude at the
     * optimum (the spike is sharper than any length scale), so when its
     * criterion is met with budget left, the rest of the budget goes to the
     * local method -- Nelder-Mead, or LM for a -target fit -- through the
     * -polish machinery of E-764, capped at the evaluations that remain */
    if (c->status == OPT_ST_CONVERGED && N < budget && !c->interrupted && gf < OPT_PENALTY &&
        c->starts == 0) {               /* under -starts the winner is polished anyway */
        if (!c->al_active)              /* E-766: once, not in every constraint round */
            fprintf(cp_out, "optimize: surrogate converged after %d evaluations (%s); the budget's "
                            "remaining %d evaluation%s go%s to the local method\n",
                    N, handoff_reason == 0 ? "the largest expected improvement is below -tol"
                     : handoff_reason == 1 ? "it expects less than a thousandth of the cost spread"
                                           : "the best cost has not moved and little is expected",
                    budget - N, budget - N == 1 ? "" : "s", budget - N == 1 ? "es" : "");
        c->polish = 1;
        c->polish_iters = budget - N;
    }

    /* the surrogate's own account of the optimum */
    if (fitted && gf < OPT_PENALTY) {
        double m, v, s, lo, hi, pm;
        gp_predict(&g, gb, &m, &v);
        s  = sqrt(v);
        pm = m * ystd + ymean;
        lo = (m - s) * ystd + ymean;
        hi = (m + s) * ystd + ymean;
        if (uselog) { pm = exp(pm); lo = exp(lo); hi = exp(hi); }
        fprintf(cp_out, "optimize: surrogate -- predicted cost %.6g (%.3g .. %.3g, one sigma) at the "
                        "optimum after %d evaluations, %s; length scales (box widths):",
                pm, lo, hi, N, uselog ? "fitted to log cost" : "fitted to the cost");
        for (j = 0; j < n; j++)
            fprintf(cp_out, " %s %.3g%s", c->name[j], g.ell[j], g.ell[j] >= 10.0 ? " (no dependence seen)" : "");
        fprintf(cp_out, "\n");
    }

    for (j = 0; j < n; j++) ubest[j] = gb[j];
    *fbest = gf;
    tfree(X); tfree(F); tfree(g.y); tfree(g.L); tfree(g.alpha); tfree(g.ell);
}



/* ==================== Enhancement-766: constraints ========================= */

/* Enhancement-766: run one method from u; the switch every caller shares */
static void opt_run_method(struct optctx *c, int which, double *u, double *f)
{
    switch (which) {
    case 3: particle_swarm(c, u, f); break;
    case 4: differential_evolution(c, u, f); break;
    case 5: simulated_annealing(c, u, f); break;
    case 7: cma_es(c, u, f); break;
    case 8: bayes_opt(c, u, f); break;
    case 9: trust_region(c, u, f); break;
    case 2: levenberg_marquardt(c, u, f); break;
    default: nelder_mead(c, u, f); break;
    }
}

/* Enhancement-766: the augmented Lagrangian around any scalar method. Each
 * constraint side is g(x) <= 0 in units of max(1, |bound|) -- the upper side
 * (value - hi)/s, the lower (lo - value)/s -- and opt_eval adds
 *
 *     (rho/2) * max(0, g + lambda/rho)^2
 *
 * to the cost for each (as a residual sqrt(rho/2) max(0, g + lambda/rho) for
 * LM) while al_active is set. The outer loop minimises that with the chosen
 * method, reads the objective and the constraint values at the inner optimum,
 * updates every multiplier lambda <- max(0, lambda + rho g), raises rho tenfold
 * when the largest violation did not fall by a factor of four, and stops when
 * the largest violation is within -ctol, or after ten rounds (INFEASIBLE).
 * rho starts balanced against the problem, 2|f0| / viol0^2 from one evaluation
 * at the start point (a fixed 10 dwarfed an objective of 1e-4 by four orders
 * and the inner method rushed into a box corner to kill the penalty, then
 * called the corner converged); every round is solved to the user's -tol. On
 * exit ubest is the last inner optimum and *fbest the OBJECTIVE there (not the
 * augmented cost); the multipliers stay in the context for the report, where
 * lambda/s is the objective's sensitivity to the bound. */
static const char *opt_status_word(int st);   /* defined with the report helpers below */

static void al_solve(struct optctx *c, int which, double *ubest, double *fbest)
{
    double prev_viol = 1e300, viol = 0.0, f = OPT_PENALTY;
    int round, j, inner = OPT_ST_MAXITER, worst = -1, worst_hi = 1;

    if (c->rho <= 0.0) {
        /* the starting penalty, balanced against the objective and the
         * violation at the start point: (rho/2) viol0^2 ~ |f0| */
        double viol0 = 0.0;
        c->al_active = 0;
        f = opt_eval(c, ubest, NULL);
        if (f < OPT_PENALTY) {
            double fs = fabs(f);
            for (j = 0; j < c->nc; j++) {
                const struct opt_con *k = &c->con[j];
                if (k->hashi && opt_con_g(k, 1) > viol0) viol0 = opt_con_g(k, 1);
                if (k->haslo && opt_con_g(k, 0) > viol0) viol0 = opt_con_g(k, 0);
            }
            if (viol0 < 1e-2) viol0 = 1e-2;
            /* a -target fit that already fits at the start has f0 ~ 0 and no
             * scale of its own; the cost of being wholly off, sum (w t)^2, is one */
            if (c->nt > 0) {
                double t = 0.0;
                for (j = 0; j < c->nt; j++)
                    t += c->tgt[j].weight * c->tgt[j].target * c->tgt[j].weight * c->tgt[j].target;
                if (t > fs) fs = t;
            }
            c->rho = fs > 0.0 ? 2.0 * fs / (viol0 * viol0) : 1.0;
            if (c->rho < 1e-9) c->rho = 1e-9;
            if (c->rho > 1e9)  c->rho = 1e9;
        } else
            c->rho = 1.0;
    }
    for (round = 0; round < 10; round++) {
        c->al_active = 1;
        c->nm_restart = 1;
        c->status = OPT_ST_MAXITER;
        opt_run_method(c, which, ubest, fbest);
        inner = c->status;
        c->al_active = 0;
        c->nm_restart = 0;
        if (c->interrupted) break;

        /* the objective and the constraint values at the inner optimum */
        f = opt_eval(c, ubest, NULL);
        if (f >= OPT_PENALTY) break;      /* nothing to read: NO SOLUTION */
        viol = 0.0; worst = -1;
        for (j = 0; j < c->nc; j++) {
            struct opt_con *k = &c->con[j];
            if (k->hashi) {
                double g = opt_con_g(k, 1);
                if (g > viol) { viol = g; worst = j; worst_hi = 1; }
                k->lam_hi = k->lam_hi + c->rho * g > 0.0 ? k->lam_hi + c->rho * g : 0.0;
            }
            if (k->haslo) {
                double g = opt_con_g(k, 0);
                if (g > viol) { viol = g; worst = j; worst_hi = 0; }
                k->lam_lo = k->lam_lo + c->rho * g > 0.0 ? k->lam_lo + c->rho * g : 0.0;
            }
        }
        c->al_rounds++;
        fprintf(cp_out, "optimize: constraints round %d -- objective %.6g, largest violation %.3g%s, "
                        "penalty %.3g, %s after %d evaluations\n",
                c->al_rounds, f, viol,
                viol <= c->ctol ? " (feasible)" : worst >= 0 ? " (relative)" : "",
                c->rho, opt_status_word(inner), c->nevals);
        if (viol <= c->ctol) break;
        if (viol > 0.25 * prev_viol && c->rho < 1e12)   /* no progress: tenfold, or a hundredfold when none at all */
            c->rho *= viol > 0.9 * prev_viol ? 100.0 : 10.0;
        prev_viol = viol;
    }
    c->al_active = 0;
    if (!c->interrupted && f < OPT_PENALTY) {
        *fbest = f;
        c->al_viol = viol;
        c->al_worst = worst;
        c->al_worst_hi = worst_hi;
        c->al_feasible = viol <= c->ctol;
        c->status = c->al_feasible ? inner : OPT_ST_INFEASIBLE;
    }
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

    /* E-536 (hunt bug 17): see opt_eval -- wind down without more analyses */
    if (ft_intrpt) {
        for (k = 0; k < c->nobj; k++)
            f[k] = OPT_PENALTY;
        return;
    }

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

    c->status = OPT_ST_COMPLETED;        /* E-762: the generations are the stop */
    for (gen = 0; gen < c->maxiter; gen++) {
        /* E-536 (hunt bug 17): an interrupt only aborts the inner analysis it
         * lands in, and the next dosim() clears the flag -- poll here so
         * Ctrl-C actually stops the search (the best point so far is
         * reported by the normal epilogue). */
        if (ft_intrpt) {
            fprintf(cp_err, "optimize: interrupted at iteration %d\n", gen);
            c->interrupted = 1;          /* E-537 (hunt I): not a convergence */
            c->status = OPT_ST_INTERRUPTED;
            break;
        }
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


/* Enhancement-762: the status as a word (the `optimize_status` variable) */
static const char *opt_status_word(int st)
{
    switch (st) {
    case OPT_ST_CONVERGED:   return "converged";
    case OPT_ST_MAXITER:     return "maxiter";
    case OPT_ST_COMPLETED:   return "completed";
    case OPT_ST_NOSOLVE:     return "nosolve";
    case OPT_ST_UNCHANGED:   return "unchanged";
    case OPT_ST_INTERRUPTED: return "interrupted";
    case OPT_ST_INFEASIBLE:  return "infeasible";    /* Enhancement-766 */
    }
    return "unknown";
}

/* ... and as the phrase the report line opens with */
static const char *opt_status_phrase(const struct optctx *c, char *buf, size_t n)
{
    switch (c->status) {
    case OPT_ST_CONVERGED:
        return "converged";
    case OPT_ST_MAXITER:
        (void) snprintf(buf, n, "stopped at -maxiter (%d %s%s) -- NOT converged",
                        c->maxiter, c->cap_is_evals ? "evaluation" : "iteration",
                        c->maxiter == 1 ? "" : "s");
        return buf;
    case OPT_ST_COMPLETED:
        (void) snprintf(buf, n, "%s complete (%d %s)",
                        c->method == 5 ? "cooling schedule" : "run",
                        c->maxiter, c->method == 5 ? "levels" : "generations");
        return buf;
    case OPT_ST_NOSOLVE:
        return "NO SOLUTION -- no evaluation solved";
    case OPT_ST_UNCHANGED:
        return "unchanged -- nothing was optimised";
    case OPT_ST_INTERRUPTED:
        return "INTERRUPTED -- best point so far";
    case OPT_ST_INFEASIBLE:          /* Enhancement-766 */
        if (c->al_worst >= 0) {
            const struct opt_con *k = &c->con[c->al_worst];
            double b = c->al_worst_hi ? k->hi : k->lo, s = opt_con_scale(k, c->al_worst_hi);
            (void) snprintf(buf, n, "INFEASIBLE -- %s %s %g missed by %.3g after %d round%s",
                            k->expr, c->al_worst_hi ? "<=" : ">=", b, c->al_viol * s,
                            c->al_rounds, c->al_rounds == 1 ? "" : "s");
        } else
            (void) snprintf(buf, n, "INFEASIBLE -- the constraints could not be met");
        return buf;
    }
    return "stopped";
}

/* publish the outcome: `optimize_status` (a string variable), and the vectors
 * plus variables `optimize_converged` (1 when the search ended on its own
 * criterion or completed its schedule), `optimize_cost` and `optimize_evals` */
static void opt_publish_outcome(const struct optctx *c, double fbest, int has_cost)
{
    const char *word = opt_status_word(c->status);
    cp_vset("optimize_status", CP_STRING, word);
    dc_set_result("optimize_converged",
                  (c->status == OPT_ST_CONVERGED || c->status == OPT_ST_COMPLETED) ? 1.0 : 0.0);
    dc_set_result("optimize_evals", (double) c->nevals);
    if (has_cost)
        dc_set_result("optimize_cost", fbest);
    if (c->nc > 0)                        /* Enhancement-766 */
        dc_set_result("optimize_feasible", c->al_feasible ? 1.0 : 0.0);
}

void com_optimize(wordlist *wl)
{
    struct optctx c;
    double ubest[OPT_MAXP], fbest = OPT_PENALTY;
    int k, use_lm, use_pso, use_de, use_sa, use_cma, use_bo, use_tr;
    int mc_held = 0;                     /* E-536 (hunt bug 16): bracket balance */

    int last_limit = 0;                  /* Enhancement-766: 1 a -spec, 2 a -constrain owns the next -max/-min */

    memset(&c, 0, sizeof c);
    sw_reuse_report(NULL, NULL);        /* Enhancement-472: zero the tally */
    c.maxiter = 100;
    c.tol = 1e-6;
    c.ctol = 1e-4;                       /* Enhancement-766 */
    c.al_worst = -1;

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
            /* Enhancement-763 (optimize hunt F2 of 2026-09-29): the knob's
             * three numbers get the rule E-499 gave the options. optnum()
             * took `abc` as 0 and `10o` as 10 in silence, so a typo moved a
             * search bound without a word; an init outside the box was
             * clamped to a bound, also in silence; a knob named twice was
             * altered twice with the last value winning. */
            {
                int dup;
                for (dup = 0; dup < c.np; dup++)
                    if (eq(c.name[dup], a->wl_word)) {
                        fprintf(cp_err, "optimize: %s '%s' given twice\n", w, a->wl_word);
                        goto cleanup;
                    }
                if (!opt_strictnum(b->wl_word, &c.x0[c.np])) {
                    fprintf(cp_err, "optimize: %s %s: <init> needs a number, not '%s'\n",
                            w, a->wl_word, b->wl_word);
                    goto cleanup;
                }
                if (!opt_strictnum(d->wl_word, &c.lo[c.np])) {
                    fprintf(cp_err, "optimize: %s %s: <lo> needs a number, not '%s'\n",
                            w, a->wl_word, d->wl_word);
                    goto cleanup;
                }
                if (!opt_strictnum(e->wl_word, &c.hi[c.np])) {
                    fprintf(cp_err, "optimize: %s %s: <hi> needs a number, not '%s'\n",
                            w, a->wl_word, e->wl_word);
                    goto cleanup;
                }
            }
            c.name[c.np] = copy(a->wl_word);
            c.kind[c.np] = knd;
            if (c.hi[c.np] <= c.lo[c.np]) {
                fprintf(cp_err, "optimize: param '%s' needs hi > lo\n", c.name[c.np]);
                tfree(c.name[c.np]);
                goto cleanup;
            }
            if (c.x0[c.np] < c.lo[c.np] || c.x0[c.np] > c.hi[c.np]) {
                fprintf(cp_err, "optimize: %s %s: init %g lies outside [%g, %g]; the search "
                                "starts inside its own range\n",
                        w, c.name[c.np], c.x0[c.np], c.lo[c.np], c.hi[c.np]);
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
                   (eq(w, "-min") && c.nspec == 0 && !c.center && last_limit != 2)) {
            /* bare -min is the scalar-objective alias only outside centering mode;
             * once a -spec is present (or -center given) it is a spec lower bound,
             * and after a -constrain (Enhancement-766) the constraint's. */
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
            /* Enhancement-763: the value and the weight are numbers or the
             * command is refused -- `-target v(out) - v(in) 0.4` (an expression
             * with a space) took `-` as a value of 0 and fitted to it, and a
             * weight of 0 or -1 was accepted (0 made the residual identically
             * zero, E-499's NOTE said "nothing was optimised" afterwards). */
            {
                double tv;
                if (!opt_strictnum(b->wl_word, &tv)) {
                    fprintf(cp_err, "optimize: -target %s: <value> needs a number, not '%s' "
                                    "(an expression with spaces must be one token: "
                                    "v(out)-v(in), not v(out) - v(in))\n",
                            a->wl_word, b->wl_word);
                    goto cleanup;
                }
                c.tgt[c.nt].expr   = copy(a->wl_word);
                c.tgt[c.nt].target = tv;
            }
            c.tgt[c.nt].weight = 1.0;
            c.tgt[c.nt].stage  = c.ns - 1;
            wl = b->wl_next;
            if (wl && !is_flag(wl->wl_word) && is_number_token(wl->wl_word)) {
                double wv;
                if (!opt_strictnum(wl->wl_word, &wv)) {
                    fprintf(cp_err, "optimize: -target %s: the weight needs a number, not '%s'\n",
                            a->wl_word, wl->wl_word);
                    c.nt++;                      /* the expr is owned: let cleanup free it */
                    goto cleanup;
                }
                if (wv <= 0.0) {
                    fprintf(cp_err, "optimize: -target %s: the weight must be positive (got %s); "
                                    "a zero weight fits nothing and a negative one is the "
                                    "positive one squared\n", a->wl_word, wl->wl_word);
                    c.nt++;
                    goto cleanup;
                }
                c.tgt[c.nt].weight = wv;
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
                else if (eq(mm, "cmaes") || eq(mm, "cma") || eq(mm, "cma-es") ||
                         eq(mm, "cmaes") || eq(mm, "evolutionstrategy"))
                    c.method = 7;        /* Enhancement-764 */
                else if (eq(mm, "bayes") || eq(mm, "bo") || eq(mm, "bayesian") ||
                         eq(mm, "gp") || eq(mm, "surrogate"))
                    c.method = 8;        /* Enhancement-765 */
                else if (eq(mm, "tr") || eq(mm, "trust") || eq(mm, "trustregion") ||
                         eq(mm, "quad") || eq(mm, "quadratic"))
                    c.method = 9;        /* Enhancement-768 */
                else {
                    fprintf(cp_err, "optimize: unknown -method '%s' "
                                    "(use nm, lm, tr, pso, de, sa, cmaes, bayes or nsga2)\n", mm);
                    goto cleanup;
                }
                wl = wl->wl_next->wl_next;
            } else {
                /* Enhancement-763: a bare option flag used to fall off the end
                 * of the command in silence and the default ran */
                fprintf(cp_err, "optimize: -method needs nm, lm, tr, pso, de, sa, cmaes, bayes or nsga2\n");
                goto cleanup;
            }
        } else if (eq(w, "-swarmsize") || eq(w, "-swarm") || eq(w, "-npart")) {
            if (wl->wl_next) {
                if (!opt_intopt(wl->wl_next->wl_word, "-swarmsize", 1, &c.swarmsize))
                    goto cleanup;                        /* Enhancement-499 */
                wl = wl->wl_next->wl_next;
            }
            else { fprintf(cp_err, "optimize: %s needs a value\n", w); goto cleanup; }
        } else if (eq(w, "-seed")) {
            if (wl->wl_next) {
                /* Enhancement-499: same rule as montecarlo's -seed and as
                   Enhancement-497 gave `setseed` -- a seed that cannot be used
                   must be refused, not truncated or dropped in silence. */
                int sv;
                if (!opt_intopt(wl->wl_next->wl_word, "-seed", 1, &sv))
                    goto cleanup;
                c.seed = (unsigned long) sv;
                wl = wl->wl_next->wl_next;
            }
            else { fprintf(cp_err, "optimize: -seed needs a value\n"); goto cleanup; }
        } else if (eq(w, "-maxiter") || eq(w, "-n")) {
            if (wl->wl_next) {
                if (!opt_intopt(wl->wl_next->wl_word, "-maxiter", 1, &c.maxiter))
                    goto cleanup;                        /* Enhancement-499 */
                wl = wl->wl_next->wl_next;
            }
            else { fprintf(cp_err, "optimize: %s needs a value\n", w); goto cleanup; }
        } else if (eq(w, "-tol") || eq(w, "-t")) {
            if (wl->wl_next) {
                if (!opt_realopt(wl->wl_next->wl_word, "-tol", &c.tol))
                    goto cleanup;                        /* Enhancement-499 */
                wl = wl->wl_next->wl_next;
            }
            else { fprintf(cp_err, "optimize: %s needs a value\n", w); goto cleanup; }
        } else if (eq(w, "-verbose") || eq(w, "-v")) {
            c.verbose = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-center") || eq(w, "-yield")) {   /* Enhancement-206 */
            c.center = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-samples") || eq(w, "-nsamp")) {
            if (wl->wl_next) {
                if (!opt_intopt(wl->wl_next->wl_word, "-samples", 1, &c.nsamples))
                    goto cleanup;                        /* Enhancement-499 */
                wl = wl->wl_next->wl_next;
            }
            else { fprintf(cp_err, "optimize: %s needs a value\n", w); goto cleanup; }
        } else if (eq(w, "-lhs")) {
            c.lhs = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-polish")) {         /* Enhancement-764 */
            c.polish = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-starts") || eq(w, "-restarts")) {   /* Enhancement-764 */
            if (wl->wl_next) {
                if (!opt_intopt(wl->wl_next->wl_word, "-starts", 1, &c.starts))
                    goto cleanup;
                wl = wl->wl_next->wl_next;
            } else { fprintf(cp_err, "optimize: -starts needs a count\n"); goto cleanup; }
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
            last_limit = 1;                     /* Enhancement-766: -max/-min are the spec's */
            wl = wl->wl_next;
        } else if (eq(w, "-constrain") || eq(w, "-constraint") || eq(w, "-subject")) {
            /* Enhancement-766: a constraint, bounded by the -max/-min that follow
             * as a -spec is; the expression is one token, as a -target's is */
            if (c.nc >= OPT_MAXC) {
                fprintf(cp_err, "optimize: too many -constrain (max %d)\n", OPT_MAXC);
                goto cleanup;
            }
            if (!wl->wl_next || is_flag(wl->wl_next->wl_word)) {
                fprintf(cp_err, "optimize: -constrain needs <expr>, then -max <hi> and/or -min <lo> "
                                "(the expression is one token: v(out), not v(out) - v(in))\n");
                goto cleanup;
            }
            c.con[c.nc].expr  = copy(wl->wl_next->wl_word);
            c.con[c.nc].hashi = c.con[c.nc].haslo = 0;
            c.con[c.nc].stage = c.ns > 0 ? c.ns - 1 : 0;
            c.con[c.nc].val   = OPT_PENALTY;
            c.con[c.nc].lam_hi = c.con[c.nc].lam_lo = 0.0;
            c.nc++;
            last_limit = 2;
            wl = wl->wl_next->wl_next;
        } else if (eq(w, "-ctol")) {           /* Enhancement-766 */
            if (wl->wl_next) {
                if (!opt_realopt(wl->wl_next->wl_word, "-ctol", &c.ctol))
                    goto cleanup;
                if (c.ctol <= 0.0) { fprintf(cp_err, "optimize: -ctol must be positive\n"); goto cleanup; }
                wl = wl->wl_next->wl_next;
            } else { fprintf(cp_err, "optimize: -ctol needs a value\n"); goto cleanup; }
        } else if (eq(w, "-max")) {
            if (c.nspec == 0 && last_limit != 2) {
                fprintf(cp_err, "optimize: -max before any -spec or -constrain\n"); goto cleanup;
            }
            if (!wl->wl_next) { fprintf(cp_err, "optimize: -max needs a value\n"); goto cleanup; }
            wl = wl->wl_next;
            if (last_limit == 2) {              /* Enhancement-766: the constraint's */
                if (!opt_boundopt(wl->wl_word, "-constrain -max", &c.con[c.nc - 1].hi))
                    goto cleanup;
                c.con[c.nc - 1].hashi = 1;
                wl = wl->wl_next;
                continue;
            }
            /* Enhancement-501: same rule as montecarlo/wcd/highsigma -- a spec
               limit must be finite, or it is never violated and silently does not
               exist. A NaN lower bound here reported Cpk = 1e+30 (OPT_PENALTY). */
            if (!opt_boundopt(wl->wl_word, "-spec -max", &c.spec[c.nspec - 1].hi))
                goto cleanup;
            c.spec[c.nspec - 1].hasmax = 1;
            wl = wl->wl_next;
        } else if (eq(w, "-min") && (c.nspec > 0 || last_limit == 2)) {
            if (!wl->wl_next) { fprintf(cp_err, "optimize: -min needs a value\n"); goto cleanup; }
            wl = wl->wl_next;
            if (last_limit == 2) {              /* Enhancement-766: the constraint's */
                if (!opt_boundopt(wl->wl_word, "-constrain -min", &c.con[c.nc - 1].lo))
                    goto cleanup;
                c.con[c.nc - 1].haslo = 1;
                wl = wl->wl_next;
                continue;
            }
            if (!opt_boundopt(wl->wl_word, "-spec -min", &c.spec[c.nspec - 1].lo))
                goto cleanup;                                    /* Enhancement-501 */
            c.spec[c.nspec - 1].hasmin = 1;
            wl = wl->wl_next;
        } else {
            /* Enhancement-763: the command used to go on past it -- `-maxiter5`
             * ran with the default cap, a stray word after a -target ran a fit
             * to the wrong target -- and report as if nothing had happened */
            fprintf(cp_err, "optimize: unrecognized token '%s'; the command is refused "
                            "(an expression or command that begins with '-' must be "
                            "quoted, a -target expression must be one token)\n", w);
            goto cleanup;
        }
    }

    /* --- validate --- */
    /* Enhancement-763: several -minimize/-maximize are NSGA-II objectives; a
     * scalar method used the first and dropped the rest in silence */
    if (c.method != 6 && c.nobj > 1) {
        fprintf(cp_err, "optimize: %d objectives were given (-minimize/-maximize); a scalar "
                        "method minimises one -- give one, or -method nsga2 for a Pareto "
                        "front\n", c.nobj);
        goto cleanup;
    }
    if (c.np < 1 || c.ns < 1 || (!c.objective && c.nt == 0 && !c.center)) {
        fprintf(cp_err, "usage: optimize (-param|-mparam|-dparam) <name> <init> "
                        "<lo> <hi> [...] -analysis <cmd> (-minimize <expr> | -target "
                        "<expr> <val> [<w>] ... | -center (-spec <m> [-max hi] [-min lo])... "
                        "-samples N [-lhs]) [-constrain <expr> (-max hi | -min lo) ...] [-ctol T] "
                        "[-method nm|lm|tr|pso|de|sa|cmaes|bayes] [-swarmsize N] "
                        "[-seed s] [-maxiter N] [-tol T] [-polish] [-starts k] [-verbose]\n");
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
    /* Enhancement-764: -polish and -starts belong to the scalar search; NSGA-II
     * returns a front, which has no single point to polish or to start from */
    if (c.method == 6 && (c.polish || c.starts > 0)) {
        fprintf(cp_err, "optimize: %s cannot be combined with -method nsga2 (a Pareto "
                        "front has no single best point)\n", c.polish ? "-polish" : "-starts");
        goto cleanup;
    }
    /* Enhancement-766: constraints */
    if (c.nc > 0) {
        int j;
        for (j = 0; j < c.nc; j++)
            if (!c.con[j].hashi && !c.con[j].haslo) {
                fprintf(cp_err, "optimize: -constrain %s has no -max/-min limit\n", c.con[j].expr);
                goto cleanup;
            }
        if (c.method == 6) {
            fprintf(cp_err, "optimize: -constrain is not available under -method nsga2 (a front "
                            "has no single point to hold to a bound)\n");
            goto cleanup;
        }
        if (c.center) {
            fprintf(cp_err, "optimize: -constrain cannot be combined with -center (its -spec limits "
                            "are the yield's; a constraint bounds a nominal metric)\n");
            goto cleanup;
        }
        c.ncside = 0;
        for (j = 0; j < c.nc; j++) c.ncside += c.con[j].hashi + c.con[j].haslo;
        if (c.nt > 0 && c.nt + c.ncside > OPT_MAXT) {
            fprintf(cp_err, "optimize: %d targets and %d constraint sides exceed the %d residuals "
                            "Levenberg-Marquardt holds\n", c.nt, c.ncside, OPT_MAXT);
            goto cleanup;
        }
        for (j = 0; j < c.nc; j++)
            if (c.con[j].stage >= c.ns) c.con[j].stage = c.ns - 1;
    }
    if (c.polish && c.starts == 0 &&
        (c.method == 1 || c.method == 2 || c.method == 9 || (c.method == 0 && !c.center))) {
        fprintf(cp_out, "optimize: NOTE -- -polish finishes a global method (pso, de, sa, "
                        "cmaes, bayes) with the local one; %s is the local method, so it is ignored\n",
                c.method == 9 ? "Trust-Region" :
                (c.method == 2 || (c.method == 0 && c.nt > 0)) ? "Levenberg-Marquardt"
                                                                : "Nelder-Mead");
        c.polish = 0;
    }
    /* Enhancement-535: the optimizer's whole search is ONE Monte-Carlo
     * sample under `.option osdimc` -- each Nelder-Mead evaluation is a
     * run-class op, and per-evaluation redraws made the objective
     * stochastic (measured: "converged" 2.4% off a closed-form optimum,
     * reported with full confidence). Cleared at cleanup.
     *
     * E-536 fix (hunt bug 8): -center is the exception -- its objective IS a
     * Monte-Carlo, so its inner samples must draw fresh trials; determinism
     * across candidates comes from replaying the same trial window instead
     * (see opt_eval_center). And the release is guarded (hunt bug 16): a
     * parse error reaches cleanup without ever taking the bracket, and with
     * the hold now a DEPTH an unbalanced release would pop an OUTER loop
     * command's hold. */
    c.mc_trial0 = OSDImcTrialCheckpoint();
    if (!c.center) {
        OSDImcHoldTrial(TRUE);
        mc_held = 1;
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
        } else if (c.swarmsize < 8 || (c.swarmsize % 2)) {
            /* Enhancement-763: raised in silence before */
            int asked = c.swarmsize;
            if (c.swarmsize < 8) c.swarmsize = 8;
            if (c.swarmsize % 2) c.swarmsize++;      /* even for pairwise breeding */
            fprintf(cp_out, "optimize: NOTE -- -swarmsize %d raised to %d (NSGA-II breeds "
                            "in pairs from a population of at least eight)\n",
                    asked, c.swarmsize);
        }
        fprintf(cp_out, "optimize: NSGA-II -- %d parameter%s, %d objectives, "
                        "population %d, seed %lu, up to %d generations\n",
                c.np, c.np == 1 ? "" : "s", c.nobj, c.swarmsize, c.seed, c.maxiter);
        fprintf(cp_out, "   objectives:");
        for (o = 0; o < c.nobj; o++)
            fprintf(cp_out, " %s(%s)", c.obj_max[o] ? "max" : "min", c.obj[o]);
        fprintf(cp_out, "\n");
        nsga2(&c);
        opt_publish_outcome(&c, 0.0, 0);   /* E-762: completed or interrupted */
        goto cleanup;
    }

    use_lm  = (c.method == 2) || (c.method == 0 && c.nt > 0);
    use_pso = (c.method == 3);
    use_de  = (c.method == 4);
    use_sa  = (c.method == 5);
    use_cma = (c.method == 7);           /* Enhancement-764 */
    use_bo  = (c.method == 8);           /* Enhancement-765 */
    use_tr  = (c.method == 9);           /* Enhancement-768 */
    if (use_pso || use_de || use_sa || use_cma || use_bo || use_tr) use_lm = 0;
    if (use_bo) {
        /* Enhancement-765: the surrogate keeps every evaluation in an N x N
         * matrix; past two thousand a population method is the right tool */
        if (c.maxiter > 2000) {
            fprintf(cp_out, "optimize: NOTE -- -maxiter %d capped at 2000 for Bayesian optimization "
                            "(its surrogate holds every evaluation; use a population method for a "
                            "larger budget)\n", c.maxiter);
            c.maxiter = 2000;
        }
        if (c.swarmsize > 0)
            fprintf(cp_out, "optimize: NOTE -- -swarmsize does not apply to Bayesian optimization "
                            "(no population; ignored)\n");
    }

    if (use_pso || use_de) {
        /* auto population: ~4x the dimension, bounded for speed. E-197 raised the
         * cap from 60 to 256 so a high-dimensional run (up to OPT_MAXP params) gets
         * an adequately sized swarm; `-swarmsize` overrides either way. DE needs at
         * least 4 distinct members (target + a,b,c) to form a mutant. */
        if (c.swarmsize <= 0) {
            c.swarmsize = 10 + 4 * c.np;
            if (c.swarmsize > 256) c.swarmsize = 256;
        } else if (c.swarmsize < 5) {
            /* Enhancement-763: raised in silence before */
            fprintf(cp_out, "optimize: NOTE -- -swarmsize %d raised to 5 (%s)\n", c.swarmsize,
                    use_de ? "differential evolution needs four distinct members besides the target"
                           : "particle swarm needs five particles");
            c.swarmsize = 5;
        }
    }
    if (use_cma) {
        /* Enhancement-764: the published default population, 4 + floor(3 ln n);
         * mu = lambda/2 needs at least two members, so lambda is at least 4 */
        if (c.swarmsize <= 0) {
            c.swarmsize = 4 + (int) floor(3.0 * log((double) c.np));
            if (c.swarmsize > 256) c.swarmsize = 256;
        } else if (c.swarmsize < 4) {
            fprintf(cp_out, "optimize: NOTE -- -swarmsize %d raised to 4 (CMA-ES recombines "
                            "the best half of at least four candidates)\n", c.swarmsize);
            c.swarmsize = 4;
        }
    }

    {
        const char *mname = use_pso ? "Particle Swarm"
                          : use_de  ? "Differential Evolution"
                          : use_sa  ? "Simulated Annealing"
                          : use_cma ? "CMA-ES"
                          : use_bo  ? "Bayesian optimization"
                          : use_tr  ? "Trust-Region"
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
        else if (use_cma)
            fprintf(cp_out, "optimize: CMA-ES population of %d (recombining %d), seed %lu, "
                            "up to %d generations\n",
                    c.swarmsize, c.swarmsize / 2, c.seed, c.maxiter);
        else if (use_bo) {
            int n0 = 2 * c.np + 2, per = c.starts > 0 ? (c.maxiter + c.starts) / (c.starts + 1) : c.maxiter;
            if (n0 > per) n0 = per;
            fprintf(cp_out, "optimize: Bayesian optimization -- a Gaussian-process surrogate (Matern 5/2, "
                            "a length scale per knob) and expected improvement, seed %lu, a budget of "
                            "%d evaluation%s (%d in the initial design)\n",
                    c.seed, per, per == 1 ? "" : "s", n0);
        }
        if (c.starts > 0)
            fprintf(cp_out, "optimize: %d start%s -- the given point and %d Latin-hypercube "
                            "point%s, %d %s%s each, the winner polished\n",
                    c.starts + 1, "s", c.starts, c.starts == 1 ? "" : "s",
                    (c.maxiter + c.starts) / (c.starts + 1), use_bo ? "evaluation" : "iteration",
                    (c.maxiter + c.starts) / (c.starts + 1) == 1 ? "" : "s");
        if (c.nc > 0) {                  /* Enhancement-766 */
            int j;
            fprintf(cp_out, "optimize: %d constraint%s (augmented Lagrangian around %s, feasible within "
                            "%g of each bound):", c.nc, c.nc == 1 ? "" : "s", mname, c.ctol);
            for (j = 0; j < c.nc; j++) {
                if (c.con[j].haslo) fprintf(cp_out, " %s >= %g", c.con[j].expr, c.con[j].lo);
                if (c.con[j].hashi) fprintf(cp_out, "%s %s <= %g", c.con[j].haslo ? "," : "", c.con[j].expr, c.con[j].hi);
                if (j + 1 < c.nc) fprintf(cp_out, ";");
            }
            fprintf(cp_out, "\n");
        }
    }

    for (k = 0; k < c.np; k++)
        ubest[k] = clamp01((c.x0[k] - c.lo[k]) / (c.hi[k] - c.lo[k]));

    {
        const int which = use_pso ? 3 : use_de ? 4 : use_sa ? 5 : use_cma ? 7 : use_bo ? 8 : use_tr ? 9
                        : use_lm ? 2 : 1;
        if (c.starts > 0) {
            /* Enhancement-764: multi-start. The given point and `starts`
             * Latin-hypercube points in the cube, each run with its share of
             * -maxiter (a population method with its own seed per start, CMA-ES
             * with a population doubled per start -- the IPOP restart rule); the
             * best of the runs is then polished below with the local method. */
            const int nrun = c.starts + 1, full = c.maxiter, lam0 = c.swarmsize;
            const unsigned long seed0 = c.seed;
            double *lhs = TMALLOC(double, (size_t) c.starts * (size_t) c.np);
            double bu[OPT_MAXP], bf = OPT_PENALTY, u0[OPT_MAXP];
            int r, win = 0, bstatus = c.status;

            opt_srand(seed0);
            for (k = 0; k < c.np; k++) {             /* one stratum per start, shuffled */
                int s, t;
                for (s = 0; s < c.starts; s++) lhs[s * c.np + k] = (double) s;
                for (s = c.starts - 1; s > 0; s--) {
                    double tmpv;
                    t = (int) (opt_rand() * (s + 1));
                    if (t > s) t = s;
                    tmpv = lhs[s * c.np + k]; lhs[s * c.np + k] = lhs[t * c.np + k]; lhs[t * c.np + k] = tmpv;
                }
                for (s = 0; s < c.starts; s++)
                    lhs[s * c.np + k] = clamp01((lhs[s * c.np + k] + opt_rand()) / c.starts);
            }
            for (k = 0; k < c.np; k++) u0[k] = ubest[k];
            c.maxiter = (full + nrun - 1) / nrun;
            if (c.maxiter < 1) c.maxiter = 1;
            for (r = 0; r < nrun && !c.interrupted; r++) {
                double f = OPT_PENALTY;
                int ev0 = c.nevals;
                if (r > 0) {
                    for (k = 0; k < c.np; k++) ubest[k] = lhs[(r - 1) * c.np + k];
                    c.seed = seed0 + (unsigned long) r;
                    if (use_cma) c.swarmsize = (lam0 << r) > 256 ? 256 : (lam0 << r);
                } else {
                    for (k = 0; k < c.np; k++) ubest[k] = u0[k];
                }
                c.status = OPT_ST_MAXITER;
                c.polish_iters = 0;      /* E-765: a start's hand-off is not the winner's */
                if (c.nc > 0) {          /* E-766: fresh multipliers per start */
                    int j;
                    for (j = 0; j < c.nc; j++) c.con[j].lam_hi = c.con[j].lam_lo = 0.0;
                    c.rho = 0.0;             /* re-balanced at this start */
                    al_solve(&c, which, ubest, &f);
                } else
                    opt_run_method(&c, which, ubest, &f);
                if (use_cma)
                    fprintf(cp_out, "optimize: start %d of %d (%s, population %d) -- %s, cost %.6g "
                                    "after %d evaluations\n",
                            r + 1, nrun, r == 0 ? "the given point" : "Latin-hypercube point",
                            c.swarmsize, opt_status_word(c.status), f, c.nevals - ev0);
                else
                    fprintf(cp_out, "optimize: start %d of %d (%s) -- %s, cost %.6g after %d evaluations\n",
                            r + 1, nrun, r == 0 ? "the given point" : "Latin-hypercube point",
                            opt_status_word(c.status), f, c.nevals - ev0);
                if (f < bf) {
                    bf = f; win = r; bstatus = c.status;
                    for (k = 0; k < c.np; k++) bu[k] = ubest[k];
                }
            }
            c.maxiter = full; c.swarmsize = lam0; c.seed = seed0;
            c.polish_iters = 0;
            for (k = 0; k < c.np; k++) ubest[k] = bu[k];
            fbest = bf;
            c.status = bstatus;
            if (!c.interrupted) {
                fprintf(cp_out, "optimize: start %d of %d won (cost %.6g)%s\n",
                        win + 1, nrun, bf, win == 0 ? " -- the given point" : "");
                c.polish = 1;
            }
            dc_set_result("optimize_start", (double) (win + 1));
            tfree(lhs);
        } else if (c.nc > 0) {
            al_solve(&c, which, ubest, &fbest);      /* E-766 */
        } else {
            opt_run_method(&c, which, ubest, &fbest);
        }

        if (c.polish && !c.interrupted && fbest < OPT_PENALTY) {
            /* Enhancement-764: finish with the local method from the best point --
             * Levenberg-Marquardt for a -target fit, Nelder-Mead otherwise (a
             * half-size first simplex: the point is already good). A global
             * search stops at its population's resolution (the 2026-09-29 hunt's
             * O1: a six-particle swarm at 0.036 where the simplex reaches 2e-14);
             * the polish gives it the local methods' precision. Its status is the
             * final one: the local criterion met is what "converged" means here. */
            const int lm = (c.nt > 0 && !c.objective && !c.center);
            const double f0 = fbest;
            const int ev0 = c.nevals;
            char phrase[128];
            if (c.polish_iters > 0) {    /* E-765: the surrogate's hand-off */
                c.maxiter = c.polish_iters;
                fprintf(cp_out, "optimize: polish -- %s from the best point (cost %.6g), up to %d "
                                "iteration%s (the remaining budget)\n",
                        lm ? "Levenberg-Marquardt" : "Trust-Region", f0, c.maxiter,
                        c.maxiter == 1 ? "" : "s");
            } else
                fprintf(cp_out, "optimize: polish -- %s from the best point (cost %.6g)\n",
                        lm ? "Levenberg-Marquardt" : "Trust-Region", f0);
            c.status = OPT_ST_MAXITER;
            c.nm_step = c.polish_iters > 0 ? 0.02 : 0.05;   /* E-765: a surrogate's best is close */
            c.cap_is_evals = 0;          /* E-765: the polish counts iterations again */
            if (c.nc > 0) {              /* E-766: the polish holds the constraints too */
                if (c.starts > 0) {      /* the winner's multipliers were its start's; begin again */
                    int j;
                    for (j = 0; j < c.nc; j++) c.con[j].lam_hi = c.con[j].lam_lo = 0.0;
                    c.rho = 0.0;
                }
                al_solve(&c, lm ? 2 : 9, ubest, &fbest);
            } else if (lm) levenberg_marquardt(&c, ubest, &fbest);
            else    trust_region(&c, ubest, &fbest);   /* E-768: it was the simplex */
            c.nm_step = 0.0;
            fprintf(cp_out, "optimize: polish %s -- cost %.6g -> %.6g in %d evaluations\n",
                    opt_status_phrase(&c, phrase, sizeof phrase), f0, fbest, c.nevals - ev0);
        }
    }

    /* leave the circuit at the optimum and report. The final run is verbose for a
     * plain optimize (one analysis), but stays quiet for centering -- a verbose
     * final run would re-do the whole inner MC and flood the console with resets. */
    c.verbose = !c.center;
    /* Enhancement-544: the optimum is the user's circuit from here on -- journal
     * this final apply so a `montecarlo`/`wcd` run next analyses it, as it did
     * in place, instead of a deck the sampling command's reset put back. */
    alter_journal_arm(1);
    (void) opt_eval(&c, ubest, NULL);
    alter_journal_arm(0);
    /* Enhancement-767 (the 2026-09-29 hunt's F7): the fast path pushes every
     * -dparam value in place and never touches the stored deck, and this final
     * apply went the same way, so the next reset -- the user's, or any command's
     * internal one -- restored the INITIAL value, while a small deck, fitted
     * through alterparam, kept its optimum: which of the two a user got depended
     * on a device count they have no reason to know about. Write the optimum
     * into the deck once on this path too (no reset: the circuit holds it). */
    if (c.fp_armed) {
        ft_optimizing = TRUE;
        for (k = 0; k < c.np; k++)
            if (c.kind[k] == OPT_DECKPARAM) {
                char cmd[512];
                (void) snprintf(cmd, sizeof cmd, "alterparam %s=%.10g", c.name[k],
                                c.lo[k] + clamp01(ubest[k]) * (c.hi[k] - c.lo[k]));
                opt_run_cmd(cmd);
            }
        ft_optimizing = FALSE;
    }

    /* Enhancement-472: say what the reuse actually did. The evaluation count
       above is the honest place to look for a behaviour change, so the decision
       has to be visible next to it. */
    if (ft_ngdebug) {
        int rk = 0, rr = 0;
        if (sw_reuse_report(&rk, &rr))
            fprintf(cp_out, "optimize: setup reused at %d of %d analyses, %d "
                            "rebuilt after a node collapse moved\n",
                    rk, c.nevals, rr);
    }
    /* Enhancement-762 (optimize hunt F1): the reason the search stopped. The
     * methods recorded their own (criterion met, -maxiter ran out, a schedule
     * completed, an interrupt); two verdicts are the epilogue's: a best cost
     * still at the penalty means no evaluation ever solved, and an objective
     * that never moved means nothing was optimised (E-499's NOTE below says
     * why that happens). Every one of these used to read "converged". */
    {
        char phrase[128];
        const char *ph;
        if (c.interrupted)
            c.status = OPT_ST_INTERRUPTED;
        else if (fbest >= OPT_PENALTY)
            c.status = OPT_ST_NOSOLVE;
        else if (c.fseen_n > 1 && c.fseen_hi == c.fseen_lo)
            c.status = OPT_ST_UNCHANGED;
        ph = opt_status_phrase(&c, phrase, sizeof phrase);
        if (c.center) {
            fprintf(cp_out, "optimize: centering %s -- worst-case Cpk = %.4g, yield = %.2f%% "
                            "(%d MC samples), after %d evaluations\n",
                    ph, c.last_cpk, 100.0 * c.last_yield, c.nsamples, c.nevals);
            dc_set_result("dcenter_yield", c.last_yield);
            dc_set_result("dcenter_cpk", c.last_cpk);
        } else if (c.nt > 0)
            /* E-537 (hunt I): "converged" describes the search stopping on its
             * own criterion. A search the USER stopped did not, and saying so
             * was the one case E-499's qualifiers did not cover -- the
             * interrupt poll (E-536) breaks straight into this line, and if
             * the interrupt lands early the reported value can be the
             * untouched starting point. */
            fprintf(cp_out, "optimize: %s, sum-sq residual = %.6g (rms %.6g) "
                            "after %d evaluations\n",
                    ph, fbest, sqrt(fbest / c.nt), c.nevals);
        else
            fprintf(cp_out, "optimize: %s, objective = %.6g after %d evaluations\n",
                    ph, fbest, c.nevals);
        if (c.status == OPT_ST_MAXITER)
            fprintf(cp_out, "optimize: NOTE -- the iteration cap ended the search before "
                            "its own criterion did; raise -maxiter, or loosen -tol if the "
                            "reported value is close enough.\n");
        /* Enhancement-766: every constraint at the optimum -- its value, whether
         * it is active, and the multiplier as the objective's sensitivity to
         * the bound (lambda/s: what one unit of the bound costs or saves) */
        if (c.nc > 0 && fbest < OPT_PENALTY) {
            int j;
            for (j = 0; j < c.nc; j++) {
                const struct opt_con *k = &c.con[j];
                int up;
                for (up = 1; up >= 0; up--) {
                    double b, s, g, lam;
                    if (up ? !k->hashi : !k->haslo) continue;
                    b = up ? k->hi : k->lo; s = opt_con_scale(k, up);
                    g = opt_con_g(k, up); lam = up ? k->lam_hi : k->lam_lo;
                    if (g > c.ctol)
                        fprintf(cp_out, "optimize: constraint %s %s %g -- %.6g, VIOLATED by %.3g\n",
                                k->expr, up ? "<=" : ">=", b, k->val, g * s);
                    else if (lam > 0.0)
                        fprintf(cp_out, "optimize: constraint %s %s %g -- %.6g, active (multiplier %.4g: "
                                        "raising the bound %s the objective by about that much per unit)\n",
                                k->expr, up ? "<=" : ">=", b, k->val, lam / s, up ? "lowers" : "raises");
                    else if (-g <= c.ctol)   /* at the bound, the last round landed feasible */
                        fprintf(cp_out, "optimize: constraint %s %s %g -- %.6g, active (at the bound; the last "
                                        "round landed feasible, so the multiplier estimate is 0)\n",
                                k->expr, up ? "<=" : ">=", b, k->val);
                    else
                        fprintf(cp_out, "optimize: constraint %s %s %g -- %.6g, slack %.4g\n",
                                k->expr, up ? "<=" : ">=", b, k->val, -g * s);
                }
            }
        }
        opt_publish_outcome(&c, fbest, 1);
    }
    /* Enhancement-499: "converged" describes the SEARCH stopping, not the answer
     * being the one the author wanted, and three ordinary situations produced a
     * confident "converged" with nothing to show for it:
     *
     *   - the objective never moved. A parameter the objective does not depend
     *     on -- one outside the signal path, or a name that does not resolve at
     *     all, which prints an error and then optimises nothing -- ends after
     *     three evaluations with the STARTING value handed back as the fit. So
     *     did `-target v(out) 0.4 0`, whose zero weight makes the residual
     *     identically 0: the most convincing number the command can print.
     *   - the answer sits on a search bound, so the real optimum is outside the
     *     range and the reported value is a wall, not a minimum.
     *
     * Both are visible here and neither was said. This is the same duty
     * Enhancement-438 discharged for failed evaluations just below, and that
     * QPSS-HB discharges when it prints "STALLED above tol -- accepted". */
    if (c.fseen_n > 1 && c.fseen_hi == c.fseen_lo)
        fprintf(cp_out, "optimize: NOTE -- the objective was %.6g at every one of "
                        "the %d evaluations, so nothing was optimised and the "
                        "reported value is the starting value; check that the "
                        "objective actually depends on the parameter%s.\n",
                c.fseen_lo, c.nevals, c.np == 1 ? "" : "s");
    else {
        int nb = 0, kk;
        for (kk = 0; kk < c.np; kk++)
            if (c.hi[kk] > c.lo[kk] &&
                (ubest[kk] <= 1e-12 || ubest[kk] >= 1.0 - 1e-12))
                nb++;
        if (nb)
            fprintf(cp_out, "optimize: NOTE -- %d of %d parameter%s finished ON a "
                            "search bound; the optimum may lie outside the range "
                            "given.\n", nb, c.np, nb == 1 ? "" : "s");
    }

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
        char rname[128];
        double val = c.lo[k] + ubest[k] * (c.hi[k] - c.lo[k]);
        fprintf(cp_out, "    %s = %.6g\n", c.name[k], val);
        /* Enhancement-501: the answer was printed but not readable. `optimize`
         * already publishes what it SCORED (dcenter_yield, dcenter_cpk) yet not
         * what it SOLVED FOR, so a script -- or the shipped dcenter demo, whose
         * `print xc` asked for a `.param` as if it were a vector -- had no name
         * to fetch the centred knob by. A `-dparam` in particular is a numparam
         * symbol that never becomes a vector, so printing it was never going to
         * work. Publish each knob's final value under `optimize_<name>`. */
        (void) snprintf(rname, sizeof rname, "optimize_%s", c.name[k]);
        dc_set_result(rname, val);
    }

cleanup:
    if (mc_held) {                       /* Enhancement-535 / E-536 balance */
        OSDImcHoldTrial(FALSE);
        mc_held = 0;
    }
    sw_fp_free();                        /* Enhancement-322: drop fast-path binds */
    for (k = 0; k < c.np; k++)
        tfree(c.name[k]);
    for (k = 0; k < c.ns; k++)
        tfree(c.analysis[k]);
    for (k = 0; k < c.nt; k++)
        tfree(c.tgt[k].expr);
    for (k = 0; k < c.nobj; k++)          /* Enhancement-216 */
        tfree(c.obj[k]);
    for (k = 0; k < c.nc; k++)            /* Enhancement-766 */
        tfree(c.con[k].expr);
    tfree(c.objective);
}
