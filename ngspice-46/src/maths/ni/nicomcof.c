/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/cpextern.h"

/* xmu=0:    Backward Euler
 * xmu=0.5:  trapezoidal (standard)
 */


int
NIcomCof(CKTcircuit *ckt)
{

    double mat[8][8];   /* matrix to compute the gear coefficients in */
    int i,j,k;          /* generic loop indicies */
    double arg;
    double arg1;

    /*  this routine calculates the timestep-dependent terms used in the
     *  numerical integration.
     */ 

    /*  
     *  compute coefficients for particular integration method 
     */ 
    switch(ckt->CKTintegrateMethod) {

    case TRAPEZOIDAL:
        switch(ckt->CKTorder) {

        case 1:
            ckt->CKTag[0] = 1/ckt->CKTdelta;
            ckt->CKTag[1] = -1/ckt->CKTdelta;
            break;

        case 2:
            ckt->CKTag[0] = 1.0 / ckt->CKTdelta / (1.0 - ckt->CKTxmu);
            ckt->CKTag[1] = ckt->CKTxmu / (1.0 - ckt->CKTxmu);
            break;

        default:
            return(E_ORDER);
        }
        break;

    /* Enhancement-419: TR-BDF2. The two sub-steps reuse the trapezoidal and
     * Gear-2 integration FORMULAS -- only the coefficients differ, so they are
     * built here and nothing downstream needs to know which stage is running.
     *
     * ckt->CKTdelta stays the FULL step h throughout. Shortening it to the
     * sub-step instead would corrupt dctran's breakpoint and step-control
     * arithmetic, which reasons about h; the sub-step lengths appear only here. */
    case TRBDF2: {
        double g = ckt->CKTtrGamma;
        double h = ckt->CKTdelta;
        if (g <= 0.0 || g >= 1.0 || h <= 0.0)
            return(E_ORDER);
        if (ckt->CKTtrStage <= 1) {
            /* Trapezoidal over gamma*h, in the shape the TRAPEZOIDAL order-2
             * branch of NIintegrate consumes:
             *     i_gamma = -ag[1]*i_n + ag[0]*(q_gamma - q_n)
             * xmu is honoured, so `.option xmu` damps this sub-step exactly as
             * it damps a plain trapezoidal run. */
            ckt->CKTag[0] = 1.0 / (g * h) / (1.0 - ckt->CKTxmu);
            ckt->CKTag[1] = ckt->CKTxmu / (1.0 - ckt->CKTxmu);
        } else {
            /* BDF2 across t, t+gamma*h, t+h: an UNEQUAL-step BDF2 with
             * h1 = (1-gamma)*h the newest interval and h2 = gamma*h. In the
             * Gear-2 shape ag[0]*q0 + ag[1]*q1 + ag[2]*q2, with q1 the stage-1
             * charge and q2 the charge at t. The three coefficients sum to
             * zero, so a constant charge integrates to exactly zero current. */
            double h1 = (1.0 - g) * h;
            double h2 = g * h;
            memset(ckt->CKTag, 0, 7 * sizeof(double));
            ckt->CKTag[0] = (2.0 * h1 + h2) / (h1 * (h1 + h2));
            ckt->CKTag[1] = -(h1 + h2) / (h1 * h2);
            ckt->CKTag[2] = h1 / (h2 * (h1 + h2));
        }
        break;
    }

    /* Enhancement-419: every SDIRK stage shares one diagonal coefficient, so a
     * single line covers all of them -- and that sameness is the point: the
     * solver sees identical conductance scaling at every stage of every step. */
    case SDIRK:
        if (ckt->CKTdelta <= 0.0 || ckt->CKTsdirkGamma <= 0.0)
            return(E_ORDER);
        memset(ckt->CKTag, 0, 7 * sizeof(double));
        ckt->CKTag[0] = 1.0 / (ckt->CKTdelta * ckt->CKTsdirkGamma);
        break;

    /* Enhancement-419: variable-step Adams-Moulton weights.
     *
     * The textbook coefficients (1/2,1/2), (5,8,-1)/12, (9,19,-5,1)/24 are
     * FIXED-step. ngspice never takes fixed steps, so using them directly would
     * silently cost the order they were chosen for -- the same trap the Gear
     * branch below already avoids by solving for its coefficients each step.
     *
     * The weights come from integrating the Lagrange basis through the current
     * timepoint and the k-1 before it, over [t_n, t_n+1]. In normalised
     * coordinates tau = (t - t_n+1)/h the nodes are tau_j <= 0 with tau_0 = 0,
     * and the weights satisfy  sum_j w_j * tau_j^m = (-1)^m/(m+1)  for
     * m = 0..k-1. Normalising by h keeps the Vandermonde entries O(1); in raw
     * seconds they would be ~1e-10 raised to the k-th power, which is the
     * underflow the Gear branch warns about in its own comment. */
    case ADAMS: {
        int k = ckt->CKTorder;
        int m, j, piv;
        double vm[7][8];    /* [row m][col j | rhs] */
        double tau[7], h = ckt->CKTdelta, back = 0.0;

        if (k < 1 || k > 6 || h <= 0.0)
            return(E_ORDER);
        tau[0] = 0.0;
        for (j = 1; j < k; j++) {
            back += ckt->CKTdeltaOld[j-1];
            tau[j] = -back / h;
        }
        for (m = 0; m < k; m++) {
            for (j = 0; j < k; j++) {
                double p = 1.0;
                int e;
                for (e = 0; e < m; e++)
                    p *= tau[j];
                vm[m][j] = p;
            }
            vm[m][k] = ((m & 1) ? -1.0 : 1.0) / (m + 1.0);
        }
        /* Gaussian elimination with partial pivoting; k <= 6. */
        for (m = 0; m < k; m++) {
            piv = m;
            for (j = m + 1; j < k; j++)
                if (fabs(vm[j][m]) > fabs(vm[piv][m]))
                    piv = j;
            if (fabs(vm[piv][m]) < 1e-300)
                return(E_ORDER);
            if (piv != m)
                for (j = m; j <= k; j++) {
                    double t = vm[m][j]; vm[m][j] = vm[piv][j]; vm[piv][j] = t;
                }
            for (j = m + 1; j < k; j++) {
                double f = vm[j][m] / vm[m][m];
                int c;
                for (c = m; c <= k; c++)
                    vm[j][c] -= f * vm[m][c];
            }
        }
        for (m = k - 1; m >= 0; m--) {
            double s = vm[m][k];
            for (j = m + 1; j < k; j++)
                s -= vm[m][j] * ckt->CKTag[j];
            ckt->CKTag[m] = s / vm[m][m];
        }
        /* ag[] currently holds the weights w_j. Convert to the stamp's form:
         * ag[0] scales the charge difference, ag[j>=1] scale past currents. */
        {
            double w0 = ckt->CKTag[0];
            if (fabs(w0) < 1e-300)
                return(E_ORDER);
            for (j = k; j < 7; j++)
                ckt->CKTag[j] = 0.0;
            for (j = 1; j < k; j++)
                ckt->CKTag[j] = ckt->CKTag[j] / w0;
            ckt->CKTag[0] = 1.0 / (h * w0);
        }
        break;
    }

    case GEAR:
        switch(ckt->CKTorder) {

        case 1:
        /*  ckt->CKTag[0] = 1/ckt->CKTdelta;
            ckt->CKTag[1] = -1/ckt->CKTdelta;
            break;*/

        case 2:
        case 3:
        case 4:
        case 5:
        case 6:
            memset(ckt->CKTag, 0, 7*sizeof(double));
            ckt->CKTag[1] = -1/ckt->CKTdelta;
            /* first, set up the matrix */
            arg=0;
            for(i=0;i<=ckt->CKTorder;i++) { mat[0][i]=1; }
            for(i=1;i<=ckt->CKTorder;i++) { mat[i][0]=0; }
            /* SPICE2 difference warning
             * the following block builds the corrector matrix
             * using (sum of h's)/h(final) instead of just (sum of h's)
             * because the h's are typically ~1e-10, so h^7 is an
             * underflow on many machines, but the ratio is ~1
             * and produces much better results
             */
            for(i=1;i<=ckt->CKTorder;i++) {
                arg += ckt->CKTdeltaOld[i-1];
                arg1 = 1;
                for(j=1;j<=ckt->CKTorder;j++) {
                    arg1 *= arg/ckt->CKTdelta;
                    mat[j][i]=arg1;
                }
            }
            /* lu decompose */
            /* weirdness warning! 
             * The following loop (and the first one after the forward
             * substitution comment) start at one instead of zero
             * because of a SPECIAL CASE - the first column is 1 0 0 ...
             * thus, the first iteration of both loops does nothing,
             * so it is skipped
             */
            for(i=1;i<=ckt->CKTorder;i++) {
                for(j=i+1;j<=ckt->CKTorder;j++) {
                    mat[j][i] /= mat[i][i];
                    for(k=i+1;k<=ckt->CKTorder;k++) {
                        mat[j][k] -= mat[j][i]*mat[i][k];
                    }
                }
            }
            /* forward substitution */
            for(i=1;i<=ckt->CKTorder;i++) {
                for(j=i+1;j<=ckt->CKTorder;j++) {
                    ckt->CKTag[j]=ckt->CKTag[j]-mat[j][i]*ckt->CKTag[i];
                }
            }
            /* backward substitution */
            ckt->CKTag[ckt->CKTorder] /= mat[ckt->CKTorder][ckt->CKTorder];
            for(i=ckt->CKTorder-1;i>=0;i--) {
                for(j=i+1;j<=ckt->CKTorder;j++) {
                    ckt->CKTag[i]=ckt->CKTag[i]-mat[i][j]*ckt->CKTag[j];
                }
                ckt->CKTag[i] /= mat[i][i];
            }
            break;
                

        default:
            return(E_ORDER);
        }
        break;

    default:
        return(E_METHOD);
    }

#ifdef PREDICTOR
    /* ok, have the coefficients for corrector, now for the predictor */

    switch(ckt->CKTintegrateMethod) {

    default:
        return(E_METHOD);

    case TRAPEZOIDAL:
        /*   ADAMS-BASHFORD PREDICTOR FOR TRAPEZOIDAL CORRECTOR
         *     MAY BE SUPPLEMENTED BY SECOND ORDER GEAR CORRECTOR
         *     AGP(1) STORES b0 AND AGP(2) STORES b1
         */
        arg = ckt->CKTdelta/(2*ckt->CKTdeltaOld[1]);
        ckt->CKTagp[0] = 1+arg;
        ckt->CKTagp[1] = -arg;
        break;

    case GEAR:

        /*
         *  CONSTRUCT GEAR PREDICTOR COEFICENT MATRIX
         *  MUST STILL ACCOUNT FOR ARRAY AGP()
         *  KEEP THE SAME NAME FOR GMAT
         */
        memset(ckt->CKTagp, 0, 7*sizeof(double));
        /*   SET UP RHS OF EQUATIONS */
        ckt->CKTagp[0]=1;
        for(i=0;i<=ckt->CKTorder;i++) {
            mat[0][i] = 1;
        }
        arg = 0;
        for(i=0;i<=ckt->CKTorder;i++){
            arg += ckt->CKTdeltaOld[i];
            arg1 = 1;
            for(j=1;j<=ckt->CKTorder;j++) {
                arg1 *= arg/ckt->CKTdelta;
                mat[j][i]=arg1;
            }
        }
        /*
         *  SOLVE FOR GEAR COEFFICIENTS AGP(*)
         */

        /*
         *  LU DECOMPOSITION
         */
        for(i=0;i<=ckt->CKTorder;i++) {
            for(j=i+1;j<=ckt->CKTorder;j++) {
                mat[j][i] /= mat[i][i];
                for(k=i+1;k<=ckt->CKTorder;k++) {
                    mat[j][k] -= mat[j][i]*mat[i][k];
                }
            }
        }
        /*
         *  FORWARD SUBSTITUTION
         */
        for(i=0;i<=ckt->CKTorder;i++) {
            for(j=i+1;j<=ckt->CKTorder;j++) {
                ckt->CKTagp[j] -= mat[j][i]*ckt->CKTagp[i];
            }
        }
        /*
         *  BACKWARD SUBSTITUTION
         */
        ckt->CKTagp[ckt->CKTorder] /= mat[ckt->CKTorder][ckt->CKTorder];
        for(i=ckt->CKTorder-1;i>=0;i--) {
            for(j=i+1;j<=ckt->CKTorder;j++) {
                ckt->CKTagp[i] -= mat[i][j]*ckt->CKTagp[j];
            }
            ckt->CKTagp[i] /= mat[i][i];
        }
        /*
         *  FINISHED
         */
        break;
    }
#endif /* PREDICTOR */
    return(OK);
}
