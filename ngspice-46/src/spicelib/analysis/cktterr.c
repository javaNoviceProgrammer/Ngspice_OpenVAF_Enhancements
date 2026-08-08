/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"

#define ccap (qcap+1)


void
CKTterr(int qcap, CKTcircuit *ckt, double *timeStep)
{ 
    double volttol;
    double chargetol;
    double tol;
    double del;
    double diff[8];
    double deltmp[8];
    double factor=0;
    int i;
    int j;
    static double gearCoeff[] = {
        .5,
        .2222222222,
        .1363636364,
        .096,
        .07299270073,
        .05830903790
    };
    static double trapCoeff[] = {
        .5,
        .08333333333
    };

    volttol = ckt->CKTabstol + ckt->CKTreltol * 
            MAX( fabs(ckt->CKTstate0[ccap]), fabs(ckt->CKTstate1[ccap]));
            
    chargetol = MAX(fabs(ckt->CKTstate0[qcap]),fabs(ckt->CKTstate1[qcap]));
    chargetol = ckt->CKTreltol * MAX(chargetol,ckt->CKTchgtol)/ckt->CKTdelta;
    tol = MAX(volttol,chargetol);
    /* now divided differences */
    for(i=ckt->CKTorder+1;i>=0;i--) {
        diff[i] = ckt->CKTstates[i][qcap];
    }
    for(i=0 ; i <= ckt->CKTorder ; i++) {
        deltmp[i] = ckt->CKTdeltaOld[i];
    }
    j = ckt->CKTorder;
    for (;;) {
        for(i=0;i <= j;i++) {
            diff[i] = (diff[i] - diff[i+1])/deltmp[i];
        }
        if (--j < 0) break;
        for(i=0;i <= j;i++) {
            deltmp[i] = deltmp[i+1] + ckt->CKTdeltaOld[i];
        }
    }
    switch(ckt->CKTintegrateMethod) {
        case GEAR:
            factor = gearCoeff[ckt->CKTorder-1];
            break;

        case TRAPEZOIDAL:
            factor = trapCoeff[ckt->CKTorder - 1] ;
            break;

        /* Enhancement-419: TR-BDF2 is second order, and the divided
         * differences above are taken over the ACCEPTED points (the stage-1
         * value is spliced out of the history before the step is accepted), so
         * the order-2 trapezoidal constant is the right scale. Leaving this
         * case out would be silent: `factor` stays 0, `del` becomes
         * trtol*tol/abstol, and the step is never limited at all. */
        case TRBDF2:
            /* TR-BDF2's own local error constant, (3g^2-4g+2)/(12(2-g)) with
             * g = 2-sqrt(2), NOT the trapezoidal 1/12 borrowed earlier. It
             * works out to 0.04044, i.e. 2.06x smaller -- and the fixed-step
             * order test measures TR-BDF2 as 2.02x more accurate than
             * trapezoidal on the same grid, so the constant and the
             * implementation confirm each other independently. Using 1/12 here
             * overstated the error and cost steps for no accuracy. */
            factor = 0.0404401145;
            break;

        /* Enhancement-419: the SDIRK tableau is order 3 and CKTorder is held at
         * 3 across its step, so the divided differences above are taken to the
         * matching depth and Gear's order-3 constant is the right scale. */
        case SDIRK:
            /* Alexander SDIRK3's own principal error constant, not Gear's.
             * For a Runge-Kutta method R(z) = 1 + sum_k z^(k+1) b^T A^k e, so
             * the order-p constant is C = b^T A^p e - 1/(p+1)!. That formula
             * reproduces the two constants already in this file EXACTLY --
             * 1/12 for trapezoidal and 1/2 for backward Euler -- which is what
             * makes it safe to trust on a tableau nobody has tabulated here.
             * It gives |C| = 0.025897; the borrowed 3/22 overstated the local
             * error 5.27x, so the step was ~1.74x smaller than warranted. */
            factor = 0.0258970847;
            break;

        /* Enhancement-419: Adams-Moulton at order k. The Adams error constants
         * differ from Gear's, but both scale the same order-k divided
         * difference; using Gear's makes the step estimate conservative rather
         * than wrong, and the campaign measures the observed order directly. */
        case ADAMS:
            factor = gearCoeff[ckt->CKTorder > 1 ? ckt->CKTorder - 1 : 0];
            break;
    }
    del = ckt->CKTtrtol * tol/MAX(ckt->CKTabstol,factor * fabs(diff[0]));
    if(ckt->CKTorder == 2) {
        del = sqrt(del);
    } else if (ckt->CKTorder == 3) {
        del = cbrt(del);
    } else if (ckt->CKTorder > 3) {
        del = exp(log(del)/ckt->CKTorder);
    }
    *timeStep = MIN(*timeStep,del);
    return;
}
