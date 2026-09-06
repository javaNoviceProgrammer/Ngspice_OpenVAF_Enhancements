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

/* Limit the number of 'singular matrix' warnings */
static int msgcount = 0;

/* NIiter() - return value is non-zero for convergence failure */

int
NIiter(CKTcircuit *ckt, int maxIter)
{
    double startTime, *OldCKTstate0 = NULL;
    int error, i, j;

    int iterno = 0;
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
                if (ckt->CKTdcFirstTry && !ckt->CKTlinesearch && !ckt->CKTtrustregion) {
                    absterm = TMALLOC(double, (size_t) sz + 1);
                    SMPmultiplyAbs(ckt->CKTmatrix, absterm, ckt->CKTrhsOld);
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

            if (ckt->CKTniState & NISHOULDREORDER) {
                startTime = SPfrontEnd->IFseconds();

#ifdef KLU
                if (ckt->CKTkluMODE) {
                    ckt->CKTmatrix->SMPkluMatrix->KLUloadDiagGmin = 1 ;
                }
#endif

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
                    ckt->CKTstat->STATnumIter += iterno;
#ifdef STEPDEBUG
                    printf("reorder returned error \n");
#endif
                    FREE(OldCKTstate0);
                    return(error); /* can't handle these errors - pass up! */
                }
                ckt->CKTniState &= ~NISHOULDREORDER;
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
            SMPsolve(ckt->CKTmatrix, ckt->CKTrhs, ckt->CKTrhsSpare);
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
