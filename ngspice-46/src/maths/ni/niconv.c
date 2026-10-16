/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

/*
 * NIconvTest(ckt)
 *  perform the convergence test - returns 1 if any of the 
 *  values in the old and new arrays have changed by more 
 *  than absTol + relTol*(max(old,new)), otherwise returns 0
 */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/optdefs.h"  /* ERRP_* -- Enhancement-539 */

#include <float.h>

extern bool ft_ngdebug;


int
NIconvTest(CKTcircuit *ckt)
{
    int i; /* generic loop variable */
    int size;  /* size of the matrix */
    CKTnode *node; /* current matrix entry */
    double old;
    double new;
    double tol;
    static int nancount = 0;

    node = ckt->CKTnodes;
    size = SMPmatSize(ckt->CKTmatrix);
#ifdef STEPDEBUG
    for (i=1;i<=size;i++) {
        new =  ckt->CKTrhs [i] ;
        old =  ckt->CKTrhsOld [i] ;
        printf("chk for convergence:   %s    new: %g    old: %g\n",CKTnodName(ckt,i),new,old);
    }
#endif /* STEPDEBUG */
    for (i=1;i<=size;i++) {
        node = node->next;
        new =  ckt->CKTrhs [i] ;
        old =  ckt->CKTrhsOld [i] ;
        if (isnan(new)) {
            if (ft_ngdebug && nancount < 10) {
                fprintf(stderr, "Warning: non-convergence, node %s is nan\n", CKTnodName(ckt, i));
                nancount++;
            }
            else if (ft_ngdebug && nancount == 10) {
                fprintf(stderr, "    non-convergence warnings (nan) limited to 10 node %s\n", CKTnodName(ckt, i));
                nancount++;
            }
            return 1;
        }
        if(node->type == SP_VOLTAGE) {
            /* LRM 3.6.1: a nature's declared abstol governs convergence for
             * signals of that nature -- unless the user set `vntol` himself,
             * in which case the explicit option wins (see CKTtolGiven). */
            tol =  ckt->CKTreltol * (MAX(fabs(old),fabs(new))) +
                    ((node->natabstol > 0.0 &&
                      !(ckt->CKTtolGiven & ERRP_VNTOL))
                         ? node->natabstol : ckt->CKTvoltTol);
            if (fabs(new-old) >tol ) {
#ifdef STEPDEBUG
                printf(" non-convergence at node (type=3) %s (fabs(new-old)>tol --> fabs(%g-%g)>%g)\n",CKTnodName(ckt,i),new,old,tol);
                printf("    reltol: %g    voltTol: %g   (tol=reltol*(MAX(fabs(old),fabs(new))) + voltTol)\n",ckt->CKTreltol,ckt->CKTvoltTol);
#endif /* STEPDEBUG */
                ckt->CKTtroubleNode = i;
                ckt->CKTtroubleElt = NULL;
                return(1);
            }
        } else {
            tol =  ckt->CKTreltol * (MAX(fabs(old),fabs(new))) +
                    ((node->natabstol > 0.0 &&
                      !(ckt->CKTtolGiven & ERRP_ABSTOL))
                         ? node->natabstol : ckt->CKTabstol);
            if (fabs(new-old) >tol ) {
#ifdef STEPDEBUG
                printf(" non-convergence at node (type=%d) %s (fabs(new-old)>tol --> fabs(%g-%g)>%g)\n",node->type,CKTnodName(ckt,i),new,old,tol);
                printf("    reltol: %g    abstol: %g   (tol=reltol*(MAX(fabs(old),fabs(new))) + abstol)\n",ckt->CKTreltol,ckt->CKTabstol);
#endif /* STEPDEBUG */
                ckt->CKTtroubleNode = i;
                ckt->CKTtroubleElt = NULL;
                return(1);
            }
        }
    }

#ifdef NEWCONV
    /* Enhancement-889 (nonlinear correctness campaign 2026-10-15, F1): the
     * device tests ask whether the step just solved moves a device's current
     * by more than reltol of it -- the device's share of the KCL residual at
     * the point it was loaded at, which is the point NIiter reports. Two
     * things kept every one of them from ever deciding anything. NIiter
     * assigns this function's return value to CKTnoncon, and CKTconvTest
     * returns OK when a device has counted itself unconverged: the count was
     * overwritten with 0. And 22 of the 30 tests (the diode, the BJTs, BSIM,
     * HiSIM, the B source) and VDMOS's body diode read their voltages from
     * CKTrhsOld, which here, before NIiter's swap, still holds the load
     * point: the "new" voltage equalled the stored one and the predicted
     * change was 0 (the level-1 to 9 MOSFETs read CKTrhs). A diode across
     * a resistor between two 100 V nodes converged 0.68 V forward with
     * 2.47 mA of KCL error, since the node test allows 0.1 V a step there.
     * The tests now see the new solution through either vector, and their
     * count is the answer. They are skipped in MODEINITFIX, where a device
     * that is `off` is held at zero whatever the solution says -- the load
     * routines exempt it from their limiting count there for the same
     * reason -- and MODEINITFLOAT always follows to confirm the point.
     *
     * What they see is the new solution with every unknown that moved by no
     * more than its own rounding (64 eps of it) held at the load point: a
     * step of that size is the solve's noise, not Newton's. Without it an
     * npn whose base an ideal source forward-biased by 2 V -- its collector
     * current the near-cancelling difference of two 1e13 A transport
     * currents -- predicted a 0.013 A change from a one-ulp move of vbe
     * against a tolerance of 1e-5 A, and never converged. 64 eps of a node
     * voltage moves a junction's current by under 1e-10 of itself, so no
     * real step is hidden. CKTrhsSpare is scratch between the solve and the
     * swap. */
    if (ckt->CKTmode & MODEINITFIX)
        return(0);
    {
        double *loaded = ckt->CKTrhsOld, *solved = ckt->CKTrhs;
        double *seen = ckt->CKTrhsSpare ? ckt->CKTrhsSpare : solved;
        for (i = 1; i <= size && seen != solved; i++) {
            double d = solved[i] - loaded[i];
            seen[i] = (fabs(d) <= 64.0 * DBL_EPSILON *
                       MAX(fabs(solved[i]), fabs(loaded[i])))
                ? loaded[i] : solved[i];
        }
        seen[0] = 0.0;
        ckt->CKTconvLoaded = loaded;    /* OSDIconvTest's load point */
        ckt->CKTrhsOld = ckt->CKTrhs = seen;
        i = CKTconvTest(ckt);
        ckt->CKTrhsOld = loaded;
        ckt->CKTrhs = solved;
        ckt->CKTconvLoaded = NULL;
    }
    if (i || ckt->CKTnoncon) {
        ckt->CKTtroubleNode = 0;
        return(i ? i : 1);
    }
    return(0);
#else /* NEWCONV */
    return(0);
#endif /* NEWCONV */
}
