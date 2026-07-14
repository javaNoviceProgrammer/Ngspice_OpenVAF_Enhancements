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

#include "com_optimize.h"

#define OPT_MAXP     16          /* max parameters to optimize            */
#define OPT_MAXS      8          /* max analysis stages                   */
#define OPT_MAXT     64          /* max least-squares targets (total)     */
#define OPT_PENALTY  1e30        /* cost for a failed / non-finite eval   */

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
    int swarmsize;                       /* Enhancement-194: PSO population (0=auto)*/
    unsigned long seed;                  /* Enhancement-194: PSO RNG seed          */
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


/* Evaluate at a normalized point u in [0,1]^np: alter each param in place, run
 * every analysis stage, and either evaluate the scalar objective or accumulate
 * the least-squares residuals. Returns the scalar cost (the objective value, or
 * the weighted sum of squared residuals). If resid != NULL (least-squares mode),
 * it is filled with the nt residuals. */
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
        for (k = 0; k < c->np; k++) {
            if (c->kind[k] != OPT_DECKPARAM)
                continue;
            double val = c->lo[k] + clamp01(u[k]) * (c->hi[k] - c->lo[k]);
            (void) snprintf(cmd, sizeof cmd, "alterparam %s=%.10g", c->name[k], val);
            opt_run_cmd(cmd);
        }
        opt_run_cmd("reset");
        ft_optimizing = !c->verbose;   /* re-assert in case re-source cleared it */
    }

    /* Apply the in-place params on the (possibly re-sourced) circuit: device /
     * instance params with `alter`, .model-card params with `altermod`. Both take
     * effect immediately without a re-parse, so they run after any `.param`
     * re-source above. */
    for (k = 0; k < c->np; k++) {
        double val;
        if (c->kind[k] == OPT_ALTER)
            (void) snprintf(cmd, sizeof cmd, "alter %s=%.10g", c->name[k],
                            (val = c->lo[k] + clamp01(u[k]) * (c->hi[k] - c->lo[k])));
        else if (c->kind[k] == OPT_MODELPARAM)
            (void) snprintf(cmd, sizeof cmd, "altermod %s=%.10g", c->name[k],
                            (val = c->lo[k] + clamp01(u[k]) * (c->hi[k] - c->lo[k])));
        else
            continue;                    /* OPT_DECKPARAM handled above */
        (void) val;
        opt_run_cmd(cmd);
    }

    c->nevals++;

    if (c->nt > 0) {
        /* least-squares: each stage's analysis, then its targets, evaluated
         * while that stage's plot is still current */
        for (s = 0; s < c->ns; s++) {
            opt_run_cmd(c->analysis[s]);
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
        cost = opt_eval_expr(c->objective);
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
        /* converge on relative gbest stagnation held over several iterations */
        if (prevgf - gf <= c->tol * (fabs(gf) + c->tol)) {
            if (++stall >= 8) break;
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
    const double F = 0.8, CR = 0.9;                 /* classic DE/rand/1/bin gains */
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
        if (prevgf - gf <= c->tol * (fabs(gf) + c->tol)) {
            if (++stall >= 8) break;
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
        } else if (eq(w, "-minimize") || eq(w, "-min") || eq(w, "-o")) {
            wl = wl->wl_next;
            tfree(c.objective);
            c.objective = collect_until_flag(&wl);
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
                else {
                    fprintf(cp_err, "optimize: unknown -method '%s' "
                                    "(use nm, lm, pso, de or sa)\n", mm);
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
        } else {
            fprintf(cp_err, "optimize: unrecognized token '%s'\n", w);
            wl = wl->wl_next;
        }
    }

    /* --- validate --- */
    if (c.np < 1 || c.ns < 1 || (!c.objective && c.nt == 0)) {
        fprintf(cp_err, "usage: optimize (-param|-mparam|-dparam) <name> <init> "
                        "<lo> <hi> [...] -analysis <cmd> (-minimize <expr> | -target "
                        "<expr> <val> [<w>] ...) [-method nm|lm|pso|de|sa] [-swarmsize N] "
                        "[-seed s] [-maxiter N] [-tol T] [-verbose]\n");
        goto cleanup;
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

    /* method resolution: LS defaults to Levenberg-Marquardt, scalar to
     * Nelder-Mead; -method may override. LM needs least-squares targets; PSO and
     * NM work for either objective kind (Enhancement-194). */
    if (c.method == 2 && c.nt == 0) {
        fprintf(cp_err, "optimize: -method lm requires -target objectives\n");
        goto cleanup;
    }
    use_lm  = (c.method == 2) || (c.method == 0 && c.nt > 0);
    use_pso = (c.method == 3);
    use_de  = (c.method == 4);
    use_sa  = (c.method == 5);
    if (use_pso || use_de || use_sa) use_lm = 0;

    if (use_pso || use_de) {
        /* auto population: scales gently with dimension, bounded for speed. DE
         * needs at least 4 distinct members (target + a,b,c) to form a mutant. */
        if (c.swarmsize <= 0) {
            c.swarmsize = 10 + 4 * c.np;
            if (c.swarmsize > 60) c.swarmsize = 60;
        }
        if (c.swarmsize < 5) c.swarmsize = 5;
    }

    {
        const char *mname = use_pso ? "Particle Swarm"
                          : use_de  ? "Differential Evolution"
                          : use_sa  ? "Simulated Annealing"
                          : use_lm  ? "Levenberg-Marquardt" : "Nelder-Mead";
        if (c.nt > 0)
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

    /* leave the circuit at the optimum (verbose final run) and report */
    c.verbose = 1;
    (void) opt_eval(&c, ubest, NULL);

    if (c.nt > 0)
        fprintf(cp_out, "optimize: converged, sum-sq residual = %.6g (rms %.6g) "
                        "after %d evaluations\n",
                fbest, sqrt(fbest / c.nt), c.nevals);
    else
        fprintf(cp_out, "optimize: converged, objective = %.6g after %d evaluations\n",
                fbest, c.nevals);
    for (k = 0; k < c.np; k++) {
        double val = c.lo[k] + ubest[k] * (c.hi[k] - c.lo[k]);
        fprintf(cp_out, "    %s = %.6g\n", c.name[k], val);
    }

cleanup:
    for (k = 0; k < c.np; k++)
        tfree(c.name[k]);
    for (k = 0; k < c.ns; k++)
        tfree(c.analysis[k]);
    for (k = 0; k < c.nt; k++)
        tfree(c.tgt[k].expr);
    tfree(c.objective);
}
