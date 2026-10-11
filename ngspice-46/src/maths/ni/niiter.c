/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 2001 AlansFixes
**********/

/*
 * NIiter(ckt,maxIter)
 *
 *  This subroutine performs the actual numerical iteration.
 *  It uses the sparse matrix stored in the circuit struct
 *  along with the matrix loading program, the load data, the
 *  convergence test function, and the convergence parameters
 */

#include "ngspice/ngspice.h"
#include "ngspice/trandefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/fteext.h"

#include <float.h>
#ifdef OSDI
#include "ngspice/optdefs.h"  /* Enhancement-736: ERRP_PIVTOL */
#include "ngspice/osdiitf.h"   /* Enhancement-689: OSDIuicSeed */
#endif

/* Limit the number of 'singular matrix' warnings */
static int msgcount = 0;
static int smallpivcount = 0;   /* Enhancement-736 */
static int smallpivlastcol = 0;
static double smallpivlastmag = 0.0;


/* Enhancement-867: iterative refinement of the real solve, the twin of
 * Enhancement-860's for ac.
 *
 * Sparse never scales a row and orders the matrix once per analysis: an
 * operating point at its first iteration, a dc sweep at its first point.
 * A VCVS of gain 1e12 in a follower whose feedback runs through a 0 V source
 * put the gain beside entries of 1 in one row, and the order Sparse chose
 * there lost the gain's worth of digits: 1.8e-5 at the operating point, 2.4e-4
 * through a transient, 25 % at a gain of 1e15.  A dc sweep of a resistance
 * kept the order its first point chose while the load moved eight decades,
 * and an ammeter beside it read 0.5 % wrong.  KLU was exact on both.
 *
 * Sparse's factorization is given a copy of the loaded matrix (SMPloadCopy,
 * taken after the diagonal gmin is added); KLU keeps its own.  After the
 * solve the residual r = b - A x gives the componentwise backward error
 * max |r_i| / (|A| |x| + |b|)_i; where that is above rounding, A d = r is
 * solved with the same factors and x + d kept while its backward error
 * falls.  A solve that was good costs one pass over the matrix's entries. */
#define NI_REFINE_TOL   (64.0 * DBL_EPSILON)
#define NI_REFINE_STEPS 2

static SMPcCopy ni_copy;
static double *ni_buf;
static int ni_buf_n;
static int *ni_kind;      /* 1 for a branch current, 0 for a node voltage */

/* b, r, den, fl, the candidate y, the scale s, the guard's |G| s, and x's
 * residual and terms while y is weighed, each n + 1 long; the unknowns'
 * kinds once per NIiter call (kinds == 0) */
static double *
ni_scratch(CKTcircuit *ckt, int n, int *kinds)
{
    CKTnode *node;
    int i;

    if (n + 1 > ni_buf_n) {
        ni_buf = TREALLOC(double, ni_buf, 9 * (size_t) (n + 1));
        ni_kind = TREALLOC(int, ni_kind, (size_t) (n + 1));
        ni_buf_n = n + 1;
        *kinds = 0;
    }
    if (!*kinds) {
        for (i = 0; i <= n; i++)
            ni_kind[i] = 0;
        for (node = ckt->CKTnodes; node; node = node->next)
            if (node->number > 0 && node->number <= n && node->type == SP_CURRENT)
                ni_kind[node->number] = 1;
        *kinds = 1;
    }
    return ni_buf;
}

/* s_j = the largest |x| of j's kind, volts for a node, amperes for a branch:
 * the scale x_j's rounding is relative to (ni_kind filled) */
static void
ni_kind_scale(int n, const double *x, double *s)
{
    double sv = 0.0, si = 0.0;
    int i;

    for (i = 1; i <= n; i++) {
        double a = fabs(x[i]);
        if (ni_kind[i]) {
            if (a > si)
                si = a;
        } else if (a > sv) {
            sv = a;
        }
    }
    s[0] = 0.0;
    for (i = 1; i <= n; i++)
        s[i] = ni_kind[i] ? si : sv;
}

/* Enhancement-868: a row whose own terms are this far below its scale
 * (|A| s)_i carries only rounding -- the unknowns of two nodes a 0 V source
 * ties to ground -- and has no backward error to measure */
#define NI_NOISE_ROW    (1024.0 * DBL_EPSILON)
/* Enhancement-869: the E-256 guard's floor, in units of (|G| s)_k -- the
 * same line, so a row the refinement takes for rounding the guard does too */
#define NI_GUARD_ROUND  NI_NOISE_ROW

/* The residual b - A x into r, and x's backward error: the componentwise
 * max |r_i| / (|A| |x| + |b|)_i over the rows that carry more than
 * rounding.  Enhancement-867 measured every row against the larger of
 * (|A| |x| + |b|)_i and (|A| s)_i, which kept the rounding rows out but also
 * a row whose branch current sits beside a far larger one elsewhere: a 6e-8 A
 * sensor's KCL row next to a 4e5 A inductor read 2e-16 and its 1.5e-3 error
 * stood (Enhancement-868, F3 of the 2026-10-11 campaign). */
static double
ni_residual(CKTcircuit *ckt, int n, const double *b, const double *x,
            double *s, double *r, double *den, double *fl)
{
    double w = 0.0;
    int i;

    ni_kind_scale(n, x, s);
    SMPresidual(ckt->CKTmatrix, n, b, x, s, r, den, fl);
    for (i = 1; i <= n; i++) {
        double num = fabs(r[i]);
        /* a row whose terms are down where doubles lose precision has no
         * measurable backward error, nor one that is all rounding */
        if (num > 0.0 && den[i] >= DBL_MIN / DBL_EPSILON &&
            den[i] > NI_NOISE_ROW * fl[i]) {
            double q = num / den[i];
            if (q > w)
                w = q;
        }
    }
    return w;
}

/* x = CKTrhs, the solution of A x = b with b in buf.  Enhancement-868: the
 * candidate x + d is weighed against x row by row over the larger of the two
 * rows' terms.  A row whose true value is 0 has terms that are all error and
 * shrink with its residual, so its own ratio stays at 1 however much better
 * the step makes it -- a numerically singular network's KCL row went from
 * 3.6e-5 to 6.3e-9 and the step was refused. */
static void
ni_refine(CKTcircuit *ckt, double *buf, int n)
{
    double *b = buf, *r = b + (n + 1), *den = r + (n + 1), *fl = den + (n + 1);
    double *y = fl + (n + 1), *s = y + (n + 1);
    double *rx = buf + 7 * (size_t) (n + 1), *dx = rx + (n + 1);
    double *x = ckt->CKTrhs;
    double w, w1;
    int i, step;

    x[0] = 0.0;
    w = ni_residual(ckt, n, b, x, s, r, den, fl);
    for (step = 0; step < NI_REFINE_STEPS && w > NI_REFINE_TOL; step++) {
        double ex = 0.0, ey = 0.0;
        memcpy(rx, r, (size_t) (n + 1) * sizeof(double));
        memcpy(dx, den, (size_t) (n + 1) * sizeof(double));
        r[0] = 0.0;
        SMPsolve(ckt->CKTmatrix, r, ckt->CKTrhsSpare);
        for (i = 1; i <= n; i++)
            y[i] = x[i] + r[i];
        y[0] = 0.0;
        w1 = ni_residual(ckt, n, b, y, s, r, den, fl);
        for (i = 1; i <= n; i++) {
            double d = dx[i] > den[i] ? dx[i] : den[i];
            if (d < DBL_MIN / DBL_EPSILON || d <= NI_NOISE_ROW * fl[i])
                continue;
            if (fabs(rx[i]) / d > ex)
                ex = fabs(rx[i]) / d;
            if (fabs(r[i]) / d > ey)
                ey = fabs(r[i]) / d;
        }
        if (!(ey < ex))
            break;
        memcpy(x, y, (size_t) (n + 1) * sizeof(double));
        w = w1;
    }
}


/* Enhancement-736: .option pivtol, "the absolute minimum value for a matrix
 * entry to be accepted as a pivot", reached both solvers and changed nothing
 * a user could see: Sparse honoured it while choosing among candidates and,
 * when no candidate passed, took the largest element and reported a verdict
 * ngspice maps to OK; KLU ignored the value.  Every full factorization now
 * records its first pivot at or below pivtol (SMPreorder / SMPcReorder,
 * SMPsmallPivot), and this prints it, naming the node whose unknown the
 * pivot belongs to and, when the pivot came from another node's equation,
 * that node too, once for a given node and magnitude; six in all, all of
 * them under `set ngdebug`, like the singular-matrix messages.  It speaks
 * when the deck set pivtol (ERRP_PIVTOL), or under ngdebug for the default.  A factorization that reuses a pivot order
 * (spFactor, klu_refactor) does not check: the order is what was chosen. */
void
NIsmallPivot(CKTcircuit *ckt)
{
    int row, col;
    double mag;

    if (!SMPsmallPivot(ckt->CKTmatrix, &row, &col, &mag))
        return;
    /* The default floor, 1e-13, is crossed by decks that are fine (an OSDI
     * branch that carries nothing, a probe source's row beside a 10 T-ohm
     * path), and Spice3 chose to say nothing then; the floor a deck sets is
     * a request, and is answered.  `set ngdebug` reports the default too. */
    if (!(ckt->CKTtolGiven & ERRP_PIVTOL) && !ft_ngdebug)
        return;
    /* KLU factors afresh at every reorder request (an operating point asks
     * twice, a transient and an AC once more) and finds the same pivot each
     * time, to rounding; the same node at the same magnitude is reported once. */
    if (col == smallpivlastcol && fabs(mag - smallpivlastmag) <= 1e-6 * fabs(smallpivlastmag))
        return;
    smallpivlastcol = col;
    smallpivlastmag = mag;
    if (!ft_ngdebug && smallpivcount >= 6)
        return;
    smallpivcount++;
    if (row == col || row <= 0)
        SPfrontEnd->IFerrorf(ERR_WARNING,
                             "the pivot for node %s is %g, below pivtol (%g)\n",
                             NODENAME(ckt, col), mag, ckt->CKTpivotAbsTol);
    else
        SPfrontEnd->IFerrorf(ERR_WARNING,
                             "the pivot for node %s (from the equation of node %s) is %g, below pivtol (%g)\n",
                             NODENAME(ckt, col), NODENAME(ckt, row), mag, ckt->CKTpivotAbsTol);
    if (!ft_ngdebug && smallpivcount == 6)
        SPfrontEnd->IFerrorf(ERR_WARNING,
                             "further pivtol warnings are not printed (set ngdebug to see them all)\n");
}

/* NIiter() - return value is non-zero for convergence failure */

int
NIiter(CKTcircuit *ckt, int maxIter)
{
    double startTime, *OldCKTstate0 = NULL;
    int error, i, j;

    int iterno = 0;
    int ni_kinds = 0;       /* Enhancement-867: ni_kind filled for this call */
    int ipass = 0;
    int fixpass = 0;   /* Enhancement-568: iterations spent in MODEINITFIX */
    int fixmax;        /* Enhancement-568: the most it may spend there */

    /* some convergence issues that get resolved by increasing max iter */
    if (maxIter < 100)
        maxIter = 100;

    /* Enhancement-568: a nodeset is HELD (MODEINITFIX) until the rest of the
     * circuit has settled around it, and only then released. CKTload holds a
     * node whose KCL row carries no branch current by REPLACING the row with
     * v = nodeset (the CIDER form), so a device between that node and a stiff
     * one may have no equilibrium to settle to at all: a diode clamp asked to
     * sit 97 V forward-biased is limited upward by a quarter volt per pass,
     * for ever. The hold then ate the whole Newton budget, the junction ran to
     * exp() overflow, and both solvers finished the point 2000 iterations later
     * through source stepping -- KLU announcing a singular matrix at the clamp
     * source, Sparse saying nothing (same NaN, different pivot test). A tenth
     * of the budget is the hold's share: every legitimate nodeset measured
     * settles in 5 to 12 passes, and a hold that has not settled in ten is a
     * nodeset the circuit cannot satisfy, so releasing it is the only move
     * left. Scales with itl1 for the circuits that need a bigger budget.
     * Plain Newton on a deck without nodesets is NOT subject to it: there
     * MODEINITFIX is simply the phase in which Newton runs its whole course
     * (the released phase then confirms the point), and cutting it at ten
     * passes moved a diode ladder's answer by 51 uV -- one iteration's worth
     * -- and twenty of the warmstart suite's samples across a spec edge. The
     * E-111 line search and E-153 trust region, on the other hand, act only
     * in the released phase, so a Newton that cycles never let them act at
     * all: with either enabled the budget applies too, and the globalization
     * the user asked for takes over after it. */
    fixmax = MAX(10, maxIter / 10);

    if ((ckt->CKTmode & MODETRANOP) && (ckt->CKTmode & MODEUIC)) {
        SWAP(double *, ckt->CKTrhs, ckt->CKTrhsOld);
        error = CKTload(ckt);
        if (error)
            return(error);
#ifdef OSDI
        /* Enhancement-689 (hunt F7 of 2026-09-21): the initial conditions a
         * Verilog-A model's analysis("ic") branch places as potential
         * contributions seed the start vector -- this one load is all the
         * "ic analysis" `uic` has, and nothing solved what it stamped. */
        error = OSDIuicSeed(ckt);
        if (error)
            return(error);
#endif
        return(OK);
    }

#ifdef WANT_SENSE2
    if (ckt->CKTsenInfo) {
        error = NIsenReinit(ckt);
        if (error)
            return(error);
    }
#endif

    if (ckt->CKTniState & NIUNINITIALIZED) {
        error = NIreinit(ckt); /* always returns 0 */
        if (error) {
#ifdef STEPDEBUG
            printf("re-init returned error \n");
#endif
            return(error);
        }
    }

    /* OldCKTstate0 = TMALLOC(double, ckt->CKTnumStates + 1); */

    /* Enhancement-153: reset the trust-region damping for this Newton solve. */
    if (ckt->CKTtrustregion)
        ckt->CKTtrLambda = 0.0;

    for (;;) {
        double trGmin = ckt->CKTdiagGmin;   /* E-153: effective diagonal add */
        double guard_merit = 0.0;           /* E-568 R1: the E-256 guard's merit, rows at round-off exempt */

        ckt->CKTnoncon = 0;

#ifdef NEWPRED
        if (!(ckt->CKTmode & MODEINITPRED))
#endif
        {

            error = CKTload(ckt);
            /* printf("loaded, noncon is %d\n", ckt->CKTnoncon); */
            /* fflush(stdout); */
            iterno++;
            if (error) {
                ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
                printf("load returned error \n");
#endif
                FREE(OldCKTstate0);
                return (error);
            }

            /* Enhancement-127: pseudo-transient continuation. The DC problem
             * f(x)=0 is embedded in a fictitious backward-Euler step
             * f(x) + Gps*(x - x_prev) = 0. The diagonal Gps term is added at
             * factor time (CKTdiagGmin, set by the PTC driver, like gmin
             * stepping); here we add the Gps*x_prev coupling to the RHS. As the
             * pseudo-timestep grows (Gps -> 0) the solution relaxes to the true
             * DC operating point along a stable trajectory. */
            if (ckt->CKTpseudoGmin > 0.0 && ckt->CKTpseudoPrev) {
                int sz = SMPmatSize(ckt->CKTmatrix);
                int k;
                for (k = 1; k <= sz; k++)
                    ckt->CKTrhs[k] += ckt->CKTpseudoGmin * ckt->CKTpseudoPrev[k];
            }

            /* printf("after loading, before solving\n"); */
            /* CKTdump(ckt); */

            if (!(ckt->CKTniState & NIDIDPREORDER)) {
                error = SMPpreOrder(ckt->CKTmatrix);
                if (error) {
                    ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
                    printf("pre-order returned error \n");
#endif
                    FREE(OldCKTstate0);
                    return(error); /* badly formed matrix */
                }
                ckt->CKTniState |= NIDIDPREORDER;
            }

            if ((ckt->CKTmode & MODEINITJCT) ||
                ((ckt->CKTmode & MODEINITTRAN) && (iterno == 1)))
            {
                ckt->CKTniState |= NISHOULDREORDER;
            }

            /* Enhancement-111: residual merit ||F(x_k)|| = ||G*x_k - b|| for the
             * globalized Newton line search. Computed here -- after the matrix
             * is loaded and preordered but BEFORE it is LU-factored (spMultiply
             * requires an unfactored matrix). G is the just-loaded Jacobian,
             * x_k = CKTrhsOld, b = CKTrhs. F is the KCL residual (a current) --
             * the merit function ngspice's iterate-based Newton otherwise lacks.
             * CKTrhsSpare is scratch (free until the solve below).
             * Enhancement-256: also compute it for a plain (line-search-off)
             * DC / tran operating point, so the false-convergence guard below
             * has the KCL residual available. */
            if ((ckt->CKTlinesearch || ckt->CKTtrustregion ||
                 (ckt->CKTdcFirstTry && (ckt->CKTmode & MODEINITFLOAT))) &&
                ckt->CKTrhsSpare && (iterno > 1)) {
                int sz = SMPmatSize(ckt->CKTmatrix);
                int k;
                double m = 0.0;
                double *absterm = NULL;
                SMPmultiply(ckt->CKTmatrix, ckt->CKTrhsSpare, ckt->CKTrhsOld,
                            NULL, NULL);
                /* Enhancement-568 (R1): the guard below scales a row's residual by
                 * |(G*x)_k|.  On a row with no independent source that is the
                 * residual ITSELF (b_k = 0), and on a high-gain branch equation it
                 * is the difference of million-sized terms and is supposed to be
                 * zero -- either way the scale collapses to abstol and the solve's
                 * own rounding reads as a KCL violation: a VCVS of gain 1e6 in
                 * unity feedback converged in 4 Newton iterations and was declined
                 * here (127 gmin iterations under KLU; under Sparse from gain 1e8,
                 * where its output node's KCL row carries 2e-10 A of residual in
                 * 2e-2 A of terms, one part in 1e8).  The scale is right for every
                 * row whose net current is real: on a diode ladder it declines a
                 * node whose residual is 19 % of its net current and the extra
                 * Newton step moves the answer by a spec band, so it is kept.  A row
                 * is exempt only while its residual is below one part per million
                 * of its term traffic, sum_j |G_kj||x_j| + |b_k| -- three decades
                 * finer than the reltol voltage test can resolve, two above the
                 * worst rounding seen.  A non-finite residual still fires.  The
                 * line-search / trust-region merit is untouched. */
                /* Enhancement-869: and never below what x's own rounding makes of
                 * the row.  x_j is good to about eps times the largest unknown of
                 * its kind, not eps times itself: the control voltage of a VCVS of
                 * gain A in feedback is v(out)/A, rounded at the circuit's volts,
                 * and the gain multiplies that rounding into its branch row.  At a
                 * gain of 1e12 an inverting amplifier's row carried 2.5e-5 of
                 * residual in 2.5 of terms, ten times the exemption, and a linear
                 * circuit went through 126 iterations of gmin stepping (3 up to
                 * 1e11).  The bound is 1024 eps of (|G| s)_k, s_j the largest
                 * unknown of j's kind -- 2e-13 of a row's own scale, where a real
                 * KCL violation sits many decades higher -- the line below which
                 * the refinement takes a row for rounding (NI_NOISE_ROW). */
                double *scaleterm = NULL;
                if (ckt->CKTdcFirstTry && !ckt->CKTlinesearch && !ckt->CKTtrustregion) {
                    double *gb = ni_scratch(ckt, sz, &ni_kinds);
                    double *gs = gb + 5 * (size_t) (sz + 1);
                    absterm = TMALLOC(double, (size_t) sz + 1);
                    SMPmultiplyAbs(ckt->CKTmatrix, absterm, ckt->CKTrhsOld);
                    ni_kind_scale(sz, ckt->CKTrhsOld, gs);
                    scaleterm = gb + 6 * (size_t) (sz + 1);
                    SMPmultiplyAbs(ckt->CKTmatrix, scaleterm, gs);
                }
                for (k = 1; k <= sz; k++) {
                    double resid = ckt->CKTrhsSpare[k] - ckt->CKTrhs[k];
                    double w = fabs(resid) /
                        (ckt->CKTabstol + ckt->CKTreltol * fabs(ckt->CKTrhsSpare[k]));
                    if (w > m)
                        m = w;
                    if (absterm) {
                        double roundoff = 1.0e-6 *
                            (absterm[k] + fabs(ckt->CKTrhs[k]));
                        if (roundoff < NI_GUARD_ROUND * scaleterm[k])   /* E-869 */
                            roundoff = NI_GUARD_ROUND * scaleterm[k];
                        if (!finite(resid))
                            guard_merit = resid;      /* NaN / Inf: !finite() below fires */
                        else if (fabs(resid) > roundoff && w > guard_merit)
                            guard_merit = w;
                    }
                }
                if (absterm)
                    FREE(absterm);
                ckt->CKTlsMerit = m;

                /* Enhancement-153: Levenberg-Marquardt trust-region Newton. When
                 * a positive damping `lambda` is in effect (set by the step
                 * rejection below), add mu = lambda * ||diag(J)|| to the Jacobian
                 * diagonal (trGmin, applied at factor time) AND mu*x_k to the RHS,
                 * so the solve yields the exact damped step
                 *   x_{k+1} = x_k - (J + mu I)^-1 F(x_k)
                 * (the E-127 pseudo-transient RHS coupling with x_prev = x_k).
                 * The scale ||diag(J)|| makes lambda dimensionless (Marquardt),
                 * and the fixed point is F=0 for any mu -- so it converges to the
                 * true operating point. lambda starts at 0 and returns to 0 once
                 * the steps succeed, making this result-neutral on well-behaved
                 * circuits; a large mu tilts the step toward steepest descent,
                 * regularizing an ill-conditioned Jacobian a line search cannot. */
                if (ckt->CKTtrustregion && (iterno > 1) && (ckt->CKTtrLambda > 0.0) &&
                    ((ckt->CKTmode & MODETRANOP) || (ckt->CKTmode & MODEDCOP)) &&
                    (ckt->CKTmode & MODEINITFLOAT)) {
                    double mu = ckt->CKTtrLambda * SMPdiagNorm(ckt->CKTmatrix);
                    if (finite(mu) && mu > 0.0) {
                        for (k = 1; k <= sz; k++)
                            ckt->CKTrhs[k] += mu * ckt->CKTrhsOld[k];
                        trGmin = ckt->CKTdiagGmin + mu;
                    }
                }
            }

            /* Enhancement-867: every solve can become the accepted point --
             * a converged NIiter returns the iterate its last load used,
             * CKTrhsOld -- except the junction guess's, which MODEINITFIX
             * always follows; that one is not checked */
            ckt->CKTmatrix->SMPloadCopy =
                (ckt->CKTmode & MODEINITJCT) ? NULL : &ni_copy;
            if (ckt->CKTniState & NISHOULDREORDER) {
                startTime = SPfrontEnd->IFseconds();

#ifdef KLU
                if (ckt->CKTkluMODE) {
                    ckt->CKTmatrix->SMPkluMatrix->KLUloadDiagGmin = 1 ;
                }
#endif

                /* Enhancement-838: a voltage node whose loaded row or
                 * column holds no nonzero value makes this factorization fail
                 * whatever the pivoting; with no diagonal gmin in the matrix,
                 * hold it first (CKTdeadHold) */
                if (trGmin == 0.0)
                    (void) CKTdeadHold(ckt);
                error = SMPreorder(ckt->CKTmatrix, ckt->CKTpivotAbsTol,
                                   ckt->CKTpivotRelTol, trGmin);
                ckt->CKTstat->STATreorderTime +=
                    SPfrontEnd->IFseconds() - startTime;
                if (error) {
                    /* new feature - we can now find out something about what is
                     * wrong - so we ask for the troublesome entry
                     * Limit the number of messages to 6, if not 'set ngdebug'.
                     */
                    if (ft_ngdebug || msgcount < 6) {
                        SMPgetError(ckt->CKTmatrix, &i, &j);
                        if(eq(NODENAME(ckt, i), NODENAME(ckt, j)))
                            SPfrontEnd->IFerrorf(ERR_WARNING, "singular matrix:  check node %s\n", NODENAME(ckt, i));
                        else
                            SPfrontEnd->IFerrorf(ERR_WARNING, "singular matrix:  check nodes %s and %s\n", NODENAME(ckt, i), NODENAME(ckt, j));
                        msgcount += 1;
                    }
                    /* Enhancement-679 (hunt F8): the singular row is the cause
                     * the transient's "Timestep too small" names -- it read
                     * "cause unrecorded" after six "check node" warnings. */
                    SMPgetError(ckt->CKTmatrix, &i, &j);
                    ckt->CKTtroubleNode = i;
                    ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
                    printf("reorder returned error \n");
#endif
                    FREE(OldCKTstate0);
                    return(error); /* can't handle these errors - pass up! */
                }
                ckt->CKTniState &= ~NISHOULDREORDER;
                NIsmallPivot(ckt);   /* Enhancement-736 */
            } else {
                startTime = SPfrontEnd->IFseconds();

#ifdef KLU
                if (ckt->CKTkluMODE) {
                    ckt->CKTmatrix->SMPkluMatrix->KLUloadDiagGmin = 1 ;
                }
#endif

                error = SMPluFac(ckt->CKTmatrix, ckt->CKTpivotAbsTol,
                                 trGmin);
                ckt->CKTstat->STATdecompTime +=
                    SPfrontEnd->IFseconds() - startTime;

#ifdef KLU
                if ((ckt->CKTkluMODE) && (error == E_SINGULAR)) {

                    /* Francesco Lannutti - 25 Aug 2020
                     * If the matrix is numerically singular during ReFactorization, take the same matrix and factor it from scratch in the same iteration.
                     * This is my mod with KLU. It saves run-time, but also the system at the next iteration may be different.
                     * How do we guarantee that the system is the same at the next iteration? So, the original SPARSE version below sounds like a bug.
                     */
                    if (ft_ngdebug)
                        fprintf (stderr, "Warning: KLU ReFactor failed. Factoring again...\n") ;
                    ckt->CKTniState |= NISHOULDREORDER;
                    ckt->CKTmatrix->SMPkluMatrix->KLUloadDiagGmin = 0 ;
                    if (trGmin == 0.0)
                        (void) CKTdeadHold(ckt);   /* Enhancement-838 */
                    error = SMPreorder(ckt->CKTmatrix, ckt->CKTpivotAbsTol, ckt->CKTpivotRelTol, trGmin);
                    ckt->CKTstat->STATreorderTime += SPfrontEnd->IFseconds() - startTime;
                    if (error) {
                        SMPgetError(ckt->CKTmatrix, &i, &j);
                        if (ft_ngdebug || msgcount < 6) {
                            SMPgetError(ckt->CKTmatrix, &i, &j);
                            if (eq(NODENAME(ckt, i), NODENAME(ckt, j)))
                                SPfrontEnd->IFerrorf(ERR_WARNING, "singular matrix:  check node %s\n", NODENAME(ckt, i));
                            else
                                SPfrontEnd->IFerrorf(ERR_WARNING, "singular matrix:  check nodes %s and %s\n", NODENAME(ckt, i), NODENAME(ckt, j));
                            msgcount += 1;
                        }

                        /* Enhancement-679: see the Sparse branch above */
                        SMPgetError(ckt->CKTmatrix, &i, &j);
                        ckt->CKTtroubleNode = i;
                        /* CKTload(ckt); */
                        /* SMPprint(ckt->CKTmatrix, stdout); */
                        /* seems to be singular - pass the bad news up */
                        ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
                        printf("lufac returned error \n");
#endif
                        FREE(OldCKTstate0);
                        return(error);
                    }
                    NIsmallPivot(ckt);   /* Enhancement-736 */
                } else if (error) {
                    if (!(ckt->CKTkluMODE) && (error == E_SINGULAR)) {

                        /* Francesco Lannutti - 25 Aug 2020
                         * If the matrix is numerically singular during ReFactorization, factor it from scratch at the next iteration.
                         * This is the original SPICE3F5 code and uses SPARSE.
                         */

                        ckt->CKTniState |= NISHOULDREORDER;
                        DEBUGMSG(" forced reordering....\n");
                        continue;
                    }
                    /* CKTload(ckt); */
                    /* SMPprint(ckt->CKTmatrix, stdout); */
                    /* seems to be singular - pass the bad news up */
                    ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
                    printf("lufac returned error \n");
#endif
                    FREE(OldCKTstate0);
                    return(error);
                }
#else
                if (error) {
                    if (error == E_SINGULAR) {

                        /* Francesco Lannutti - 25 Aug 2020
                         * If the matrix is numerically singular during ReFactorization, factor it from scratch at the next iteration.
                         * This is the original SPICE3F5 code and uses SPARSE.
                         */

                        ckt->CKTniState |= NISHOULDREORDER;
                        DEBUGMSG(" forced reordering....\n");
                        continue;
                    }
                    /* CKTload(ckt); */
                    /* SMPprint(ckt->CKTmatrix, stdout); */
                    /* seems to be singular - pass the bad news up */
                    ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
                    printf("lufac returned error \n");
#endif
                    FREE(OldCKTstate0);
                    return(error);
                }
#endif

            }

            /* moved it to here as if xspice is included then CKTload changes
               CKTnumStates the first time it is run */
            if (!OldCKTstate0)
                OldCKTstate0 = TMALLOC(double, ckt->CKTnumStates + 1);
            if (ckt->CKTstate0)
                memcpy(OldCKTstate0, ckt->CKTstate0,
                       (size_t) ckt->CKTnumStates * sizeof(double));

            startTime = SPfrontEnd->IFseconds();
            {
                /* Enhancement-867: b kept for the residual */
                int nref = SMPmatSize(ckt->CKTmatrix);
                double *refbuf = (nref > 0 && !(ckt->CKTmode & MODEINITJCT)) ?
                    ni_scratch(ckt, nref, &ni_kinds) : NULL;
                if (refbuf) {
                    memcpy(refbuf, ckt->CKTrhs, (size_t) (nref + 1) * sizeof(double));
                    refbuf[0] = 0.0;
                }
                SMPsolve(ckt->CKTmatrix, ckt->CKTrhs, ckt->CKTrhsSpare);
                if (refbuf)
                    ni_refine(ckt, refbuf, nref);
            }
            ckt->CKTstat->STATsolveTime +=
                SPfrontEnd->IFseconds() - startTime;
#ifdef STEPDEBUG
            /*XXXX*/
            if (ckt->CKTrhs[0] != 0.0)
                printf("NIiter: CKTrhs[0] = %g\n", ckt->CKTrhs[0]);
            if (ckt->CKTrhsSpare[0] != 0.0)
                printf("NIiter: CKTrhsSpare[0] = %g\n", ckt->CKTrhsSpare[0]);
            if (ckt->CKTrhsOld[0] != 0.0)
                printf("NIiter: CKTrhsOld[0] = %g\n", ckt->CKTrhsOld[0]);
            /*XXXX*/
#endif
            ckt->CKTrhs[0] = 0;
            ckt->CKTrhsSpare[0] = 0;
            ckt->CKTrhsOld[0] = 0;

            if (iterno > maxIter) {
                ckt->CKTstat->STATnumIter += iterno;
                /* we don't use this info during transient analysis */
                if (ckt->CKTcurrentAnalysis != DOING_TRAN) {
                    FREE(errMsg);
                    errMsg = copy("Too many iterations without convergence");
#ifdef STEPDEBUG
                    fprintf(stderr, "too many iterations without convergence: %d iter's (max iter == %d)\n",
                    iterno, maxIter);
#endif
                }
                FREE(OldCKTstate0);
                return(E_ITERLIM);
            }

            if ((ckt->CKTnoncon == 0) && (iterno != 1))
                ckt->CKTnoncon = NIconvTest(ckt);
            else
                ckt->CKTnoncon = 1;

            /* Enhancement-153: never declare convergence while the trust-region
             * step is still damped (lambda > 0) -- force another, less-damped
             * iteration so the accepted operating point is an undamped Newton
             * step (F = 0), keeping the result identical to plain Newton. */
            if (ckt->CKTtrustregion && (ckt->CKTtrLambda > 0.0) &&
                (ckt->CKTnoncon == 0))
                ckt->CKTnoncon = 1;

            /* Enhancement-256: reject a SPURIOUS operating point. NIconvTest
             * checks only the iterate-to-iterate voltage change; a Newton step
             * pinned by a near-singular Jacobian -- e.g. a behavioral source
             * whose derivative -> infinity at the v = 0 initial guess, like
             * B I=sqrt(v(n)) -- takes a vanishing step (dv -> 0, "converged")
             * while grossly VIOLATING KCL: the node-current residual
             * F = G*x - b (CKTlsMerit above, normalized by the current
             * tolerance) stays huge. Verify it, in the DC / tran operating
             * point: if the worst node imbalance is >100x tolerance (a genuinely
             * converged point sits near 1, so this is result-neutral on every
             * well-behaved circuit), decline convergence so CKTop falls through to
             * gmin / source stepping, which regularizes the singular node and
             * finds the true point. CKTdcFirstTry is set by CKTop only around the
             * first plain-Newton attempt, so this covers EVERY operating-point
             * solve -- .op (MODEDCOP), the transient op (MODETRANOP, E-257), and
             * the .dc sweep's first point (MODEDCTRANCURVE, E-258) -- while never
             * firing inside a convergence-aid sub-solve (optran/gmin/src, which
             * run with CKTdcFirstTry == 0). MODEINITFLOAT excludes the initial
             * junction-guess iteration. */
            if ((ckt->CKTnoncon == 0) && (iterno > 1) && ckt->CKTdcFirstTry &&
                (ckt->CKTmode & MODEINITFLOAT) &&
                !ckt->CKTlinesearch && !ckt->CKTtrustregion &&
                (!finite(guard_merit) || guard_merit > 100.0))   /* E-568 R1: rows at round-off exempt */
                ckt->CKTnoncon = 1;

#ifdef STEPDEBUG
            printf("noncon is %d\n", ckt->CKTnoncon);
#endif
        }

        if ((ckt->CKTnodeDamping != 0) && (ckt->CKTnoncon != 0) &&
            ((ckt->CKTmode & MODETRANOP) || (ckt->CKTmode & MODEDCOP)) &&
            (iterno > 1))
        {
            CKTnode *node;
            double diff, maxdiff = 0;
            for (node = ckt->CKTnodes->next; node; node = node->next)
                if (node->type == SP_VOLTAGE) {
                    diff = fabs(ckt->CKTrhs[node->number] - ckt->CKTrhsOld[node->number]);
                    if (maxdiff < diff)
                        maxdiff = diff;
                }

            if (maxdiff > 10) {
                double damp_factor = 10 / maxdiff;
                if (damp_factor < 0.1)
                    damp_factor = 0.1;
                for (node = ckt->CKTnodes->next; node; node = node->next) {
                    diff = ckt->CKTrhs[node->number] - ckt->CKTrhsOld[node->number];
                    ckt->CKTrhs[node->number] =
                        ckt->CKTrhsOld[node->number] + (damp_factor * diff);
                }
                for (i = 0; i < ckt->CKTnumStates; i++) {
                    diff = ckt->CKTstate0[i] - OldCKTstate0[i];
                    ckt->CKTstate0[i] = OldCKTstate0[i] + (damp_factor * diff);
                }
            }
        }

        /* Enhancement-153: trust-region step acceptance (option `trustregion`,
         * OFF by default; takes precedence over the line search). The step just
         * solved (x_new = CKTrhs) used the current damping mu = lambda*||diag||.
         * Evaluate the true residual ||F(x_new)|| by re-loading at x_new; if it
         * did NOT decrease vs ||F(x_k)|| the step is rejected -- x_k is restored,
         * lambda is grown, and another iteration is forced so the step is retried
         * with more damping (re-loaded and re-factored at the top of the loop).
         * If it decreased, the step is accepted and lambda relaxes toward 0. This
         * is the standard Levenberg-Marquardt acceptance: unlike the line search
         * (which only shortens a fixed Newton direction) it also *re-aims* the
         * step, so it can escape an ill-conditioned or divergent Jacobian. */
        if (ckt->CKTtrustregion && (ckt->CKTnoncon != 0) &&
            ((ckt->CKTmode & MODETRANOP) || (ckt->CKTmode & MODEDCOP)) &&
            (ckt->CKTmode & MODEINITFLOAT) && (iterno > 1))
        {
            int sz = SMPmatSize(ckt->CKTmatrix);
            int k, saved_noncon = ckt->CKTnoncon;
            double merit_k = ckt->CKTlsMerit, trial_merit = 0.0;

            if (ckt->CKTlsBufSz < sz + 1) {
                FREE(ckt->CKTlsXk);
                FREE(ckt->CKTlsD);
                ckt->CKTlsXk = TMALLOC(double, sz + 1);
                ckt->CKTlsD  = TMALLOC(double, sz + 1);
                ckt->CKTlsBufSz = sz + 1;
            }
            for (k = 1; k <= sz; k++) {
                ckt->CKTlsXk[k] = ckt->CKTrhsOld[k];   /* x_k               */
                ckt->CKTlsD[k]  = ckt->CKTrhs[k];      /* x_new (the step)  */
            }
            /* residual at x_new: load there (state reset to x_k first) */
            for (k = 1; k <= sz; k++)
                ckt->CKTrhsOld[k] = ckt->CKTlsD[k];
            if (OldCKTstate0 && ckt->CKTstate0)
                memcpy(ckt->CKTstate0, OldCKTstate0,
                       (size_t) ckt->CKTnumStates * sizeof(double));
            if (!CKTload(ckt)) {
                SMPmultiply(ckt->CKTmatrix, ckt->CKTrhsSpare, ckt->CKTrhsOld,
                            NULL, NULL);
                for (k = 1; k <= sz; k++) {
                    double resid = ckt->CKTrhsSpare[k] - ckt->CKTrhs[k];
                    double w = fabs(resid) /
                        (ckt->CKTabstol + ckt->CKTreltol * fabs(ckt->CKTrhsSpare[k]));
                    if (w > trial_merit)
                        trial_merit = w;
                }
            } else {
                trial_merit = 2.0 * merit_k + 1.0;   /* load failed -> reject */
            }
            /* restore x_k and its device state */
            for (k = 1; k <= sz; k++)
                ckt->CKTrhsOld[k] = ckt->CKTlsXk[k];
            if (OldCKTstate0 && ckt->CKTstate0)
                memcpy(ckt->CKTstate0, OldCKTstate0,
                       (size_t) ckt->CKTnumStates * sizeof(double));
            ckt->CKTnoncon = saved_noncon;

            if (trial_merit <= merit_k * (1.0 + 1.0e-4) ||
                ckt->CKTtrLambda >= 1.0e12) {
                /* ACCEPT: advance to x_new; relax the damping toward 0. */
                for (k = 1; k <= sz; k++) {
                    ckt->CKTrhs[k]    = ckt->CKTlsD[k];   /* x_new  */
                    ckt->CKTrhsOld[k] = ckt->CKTlsXk[k];  /* x_k    */
                }
                ckt->CKTtrLambda *= 0.25;
                if (ckt->CKTtrLambda < 1.0e-12)
                    ckt->CKTtrLambda = 0.0;
            } else {
                /* REJECT: stay at x_k, grow lambda, force another iteration so
                 * the step is retried with more damping. */
                for (k = 1; k <= sz; k++) {
                    ckt->CKTrhs[k]    = ckt->CKTlsXk[k];
                    ckt->CKTrhsOld[k] = ckt->CKTlsXk[k];
                }
                ckt->CKTtrLambda = (ckt->CKTtrLambda > 0.0)
                                       ? ckt->CKTtrLambda * 4.0 : 1.0e-3;
                ckt->CKTnoncon = 1;
            }
        }

        /* Enhancement-111: globalized (damped) Newton via Armijo backtracking
         * line search (option `linesearch`, OFF by default). Runs only on the
         * non-convergence path. Using the residual merit ||F|| = ||G*x - b||
         * (the KCL current mismatch, computed above before factorization), it
         * damps the full Newton step x_k -> x_full by the largest lambda in
         * {1, 1/2, 1/4, ...} that gives a sufficient decrease of ||F|| (Armijo).
         * Each trial RE-LOADS the devices at the trial point x_k + lambda*d and
         * re-evaluates ||F|| on the (SMPclear-reset, unfactored) matrix. At/near
         * a solution the full step already reduces ||F||, so lambda = 1 is
         * accepted on the first trial (result-neutral); backtracking only kicks
         * in on genuine overshoot. This gives ngspice the principled globalized
         * Newton it lacks -- the merit is the real residual, not the iterate
         * change. */
        if (ckt->CKTlinesearch && !ckt->CKTtrustregion && (ckt->CKTnoncon != 0) &&
            ((ckt->CKTmode & MODETRANOP) || (ckt->CKTmode & MODEDCOP)) &&
            (ckt->CKTmode & MODEINITFLOAT) && (iterno > 1))
        {
            int sz = SMPmatSize(ckt->CKTmatrix);
            int k, saved_noncon = ckt->CKTnoncon;
            double lambda = 1.0, merit_k = ckt->CKTlsMerit;

            if (ckt->CKTlsBufSz < sz + 1) {
                FREE(ckt->CKTlsXk);
                FREE(ckt->CKTlsD);
                ckt->CKTlsXk = TMALLOC(double, sz + 1);
                ckt->CKTlsD  = TMALLOC(double, sz + 1);
                ckt->CKTlsBufSz = sz + 1;
            }
            /* save x_k and the full Newton step d = x_full - x_k */
            for (k = 1; k <= sz; k++) {
                ckt->CKTlsXk[k] = ckt->CKTrhsOld[k];
                ckt->CKTlsD[k]  = ckt->CKTrhs[k] - ckt->CKTrhsOld[k];
            }
            for (;;) {
                double trial_merit = 0.0;
                for (k = 1; k <= sz; k++)
                    ckt->CKTrhsOld[k] = ckt->CKTlsXk[k] + lambda * ckt->CKTlsD[k];
                /* Reset the device state (junction-voltage limiting reference)
                 * to x_k before every trial, so each trial load limits relative
                 * to the SAME point -- SPICE limiting is stateful and would
                 * otherwise drift across trials and corrupt the iteration. */
                if (OldCKTstate0 && ckt->CKTstate0)
                    memcpy(ckt->CKTstate0, OldCKTstate0,
                           (size_t) ckt->CKTnumStates * sizeof(double));
                if (CKTload(ckt))       /* trial load failed -> stop backtracking */
                    break;
                SMPmultiply(ckt->CKTmatrix, ckt->CKTrhsSpare, ckt->CKTrhsOld,
                            NULL, NULL);
                for (k = 1; k <= sz; k++) {
                    double resid = ckt->CKTrhsSpare[k] - ckt->CKTrhs[k];
                    double w = fabs(resid) /
                        (ckt->CKTabstol + ckt->CKTreltol * fabs(ckt->CKTrhsSpare[k]));
                    if (w > trial_merit)
                        trial_merit = w;
                }
                /* Armijo sufficient-decrease (c = 1e-4); floor lambda at 1/64 */
                if (trial_merit <= (1.0 - 1.0e-4 * lambda) * merit_k ||
                    lambda <= 1.0 / 64.0)
                    break;
                lambda *= 0.5;
            }
            /* Accept the (damped) step. Put x_trial into CKTrhs and restore
             * CKTrhsOld = x_k so the SWAP below advances to x_trial. Roll the
             * device state back to x_k so the trial loads leave NO state trace:
             * the next iteration then loads at x_trial with the x_k limiting
             * reference -- exactly the cadence a normal (un-line-searched)
             * iteration would have. Only the chosen x_trial position persists. */
            for (k = 1; k <= sz; k++) {
                ckt->CKTrhs[k]    = ckt->CKTrhsOld[k];
                ckt->CKTrhsOld[k] = ckt->CKTlsXk[k];
            }
            if (OldCKTstate0 && ckt->CKTstate0)
                memcpy(ckt->CKTstate0, OldCKTstate0,
                       (size_t) ckt->CKTnumStates * sizeof(double));
            ckt->CKTnoncon = saved_noncon; /* trial loads dirtied it */
        }

        if (ckt->CKTmode & MODEINITFLOAT) {
            if ((ckt->CKTmode & MODEDC) && ckt->CKThadNodeset) {
                if (ipass)
                    ckt->CKTnoncon = ipass;
                ipass = 0;
            }
            if (ckt->CKTnoncon == 0) {
                ckt->CKTstat->STATnumIter += iterno;
                FREE(OldCKTstate0);
                return(OK);
            }
        } else if (ckt->CKTmode & MODEINITJCT) {
            ckt->CKTmode = (ckt->CKTmode & ~INITF) | MODEINITFIX;
            ckt->CKTniState |= NISHOULDREORDER;
        } else if (ckt->CKTmode & MODEINITFIX) {
            fixpass++;
            if (ckt->CKTnoncon == 0 ||
                ((ckt->CKThadNodeset || ckt->CKTlinesearch || ckt->CKTtrustregion) &&
                 fixpass >= fixmax))                        /* Enhancement-568 */
                ckt->CKTmode = (ckt->CKTmode & ~INITF) | MODEINITFLOAT;
            ipass = 1;
        } else if (ckt->CKTmode & MODEINITSMSIG) {
            ckt->CKTmode = (ckt->CKTmode & ~INITF) | MODEINITFLOAT;
        } else if (ckt->CKTmode & MODEINITTRAN) {
            if (iterno <= 1)
                ckt->CKTniState |= NISHOULDREORDER;
            ckt->CKTmode = (ckt->CKTmode & ~INITF) | MODEINITFLOAT;
        } else if (ckt->CKTmode & MODEINITPRED) {
            ckt->CKTmode = (ckt->CKTmode & ~INITF) | MODEINITFLOAT;
        } else {
            ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
            printf("bad initf state \n");
#endif
            FREE(OldCKTstate0);
            return(E_INTERN);
            /* impossible - no such INITF flag! */
        }

        /* build up the lvnim1 array from the lvn array */
        SWAP(double *, ckt->CKTrhs, ckt->CKTrhsOld);
        /* printf("after loading, after solving\n"); */
        /* CKTdump(ckt); */
    }
    /*NOTREACHED*/
}

void NIresetwarnmsg(void) {
    msgcount = 0;
}
