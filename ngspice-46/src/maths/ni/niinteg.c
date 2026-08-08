/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

/* NIintegrate(ckt,geq,ceq,cap,qcap)
 *  integrate the specified capacitor - method and order in the
 *  ckt structure, ccap follows qcap.
 */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"

#define ccap qcap+1

/* Enhancement-419: Alexander's 3-stage, order-3, L-stable SDIRK.
 *   gamma is the root of  g^3 - 3g^2 + 3g/2 - 1/6 = 0  in (1/3, 1/2)
 *   c = [gamma, (1+gamma)/2, 1]
 *   a = [[gamma,     0,     0    ]
 *        [(1-g)/2,   gamma, 0    ]
 *        [b1,        b2,    gamma]]     with b1,b2 below
 * The last row equals the weight vector b, i.e. the tableau is STIFFLY
 * ACCURATE, so the final stage is the step's answer and no combination step is
 * needed. b1+b2+gamma == 1 and the last row sums to c[3] == 1; both are
 * asserted by the example suite rather than taken on trust.
 *
 * The coefficients are DERIVED from gamma here rather than written out as
 * literals: a mistyped digit in a Butcher tableau does not crash, it quietly
 * costs an order of convergence, which is exactly the sort of defect that
 * survives every test that only checks "the answer looks reasonable". */
#define SDIRK_STAGES 3
static const double sdirk_gamma = 0.43586652150845899942;

static double sdirk_a(int i, int j)   /* 1-based, i >= j */
{
    double g = sdirk_gamma;
    if (i == j)
        return g;
    if (i == 2 && j == 1)
        return (1.0 - g) / 2.0;
    if (i == 3 && j == 1)
        return -(6.0 * g * g - 16.0 * g + 1.0) / 4.0;
    if (i == 3 && j == 2)
        return (6.0 * g * g - 20.0 * g + 5.0) / 4.0;
    return 0.0;
}

double NIsdirkC(int stage)            /* abscissa c[stage], 1-based */
{
    int j;
    double c = 0.0;
    for (j = 1; j <= stage; j++)
        c += sdirk_a(stage, j);
    return c;
}

void NIsdirkInfo(int *stages, double *gamma)
{
    if (stages)
        *stages = SDIRK_STAGES;
    if (gamma)
        *gamma = sdirk_gamma;
}

int
NIintegrate(CKTcircuit *ckt, double *geq, double *ceq, double cap, int qcap)
{
    static char *ordmsg = "Illegal integration order";
    static char *methodmsg = "Unknown integration method";

    switch(ckt->CKTintegrateMethod) {

    case TRAPEZOIDAL:
        switch(ckt->CKTorder) {
        case 1:
            ckt->CKTstate0[ccap] = ckt->CKTag[0] * ckt->CKTstate0[qcap]
                    + ckt->CKTag[1] * ckt->CKTstate1[qcap];
            break;
        case 2:
            ckt->CKTstate0[ccap] = - ckt->CKTstate1[ccap] * ckt->CKTag[1] +
                    ckt->CKTag[0] *
                    ( ckt->CKTstate0[qcap] - ckt->CKTstate1[qcap] );
            break;
        default:
            errMsg = TMALLOC(char, strlen(ordmsg) + 1);
            strcpy(errMsg,ordmsg);
            return(E_ORDER);
        }
        break;
    /* Enhancement-419: TR-BDF2 borrows both existing formulas rather than
     * adding a third. Stage 1 is the trapezoidal order-2 rule over gamma*h;
     * stage 2 is the Gear order-2 rule, reading q1 = the stage-1 charge and
     * q2 = the charge at t, which dctran arranges by rotating the state slots
     * once between the sub-steps. The coefficients come from NIcomCof. */
    case TRBDF2:
        if (ckt->CKTtrStage <= 1) {
            ckt->CKTstate0[ccap] = - ckt->CKTstate1[ccap] * ckt->CKTag[1] +
                    ckt->CKTag[0] *
                    ( ckt->CKTstate0[qcap] - ckt->CKTstate1[qcap] );
        } else {
            ckt->CKTstate0[ccap] = ckt->CKTag[0] * ckt->CKTstate0[qcap]
                                 + ckt->CKTag[1] * ckt->CKTstate1[qcap]
                                 + ckt->CKTag[2] * ckt->CKTstate2[qcap];
        }
        break;

    /* Enhancement-419: SDIRK stage i. The stage relation
     *     q_i = q_n + h * sum_{j<=i} a_ij * i_j
     * solved for the unknown stage current gives
     *     i_i = (q_i - q_n)/(h*gamma) - sum_{j<i} (a_ij/gamma) * i_j
     * The previous stage CURRENTS are what this needs, not just their charges
     * -- and they are already there, because ccap sits beside qcap in the same
     * state vector, so rotating the slots carries both.
     *
     * dctran rotates once per completed stage, so during stage i the slot
     * state[k] holds stage (i-k) and state[i] holds the values at t. */
    case SDIRK: {
        int i = ckt->CKTsdirkStage;
        int k;
        double g = ckt->CKTsdirkGamma;
        double acc = ckt->CKTag[0] *
            (ckt->CKTstate0[qcap] - ckt->CKTstates[i][qcap]);
        for (k = 1; k < i; k++)
            acc -= (sdirk_a(i, i - k) / g) * ckt->CKTstates[k][ccap];
        ckt->CKTstate0[ccap] = acc;
        break;
    }

    /* Enhancement-419: Adams-Moulton. Same shape as the SDIRK stage relation,
     * but the earlier values are earlier TIMEPOINTS rather than stages, and the
     * charge is referenced to q_n (state1) rather than to the start of a step:
     *     i_n+1 = (q_n+1 - q_n)/(h*w0) - sum_{j>=1} (w_j/w0) * i_n+1-j
     * At order 2 the weights are (1/2, 1/2), so ag[0] = 2/h and ag[1] = 1 --
     * character for character the TRAPEZOIDAL order-2 branch above. */
    case ADAMS: {
        int j;
        double acc = ckt->CKTag[0] *
            (ckt->CKTstate0[qcap] - ckt->CKTstate1[qcap]);
        for (j = 1; j < ckt->CKTorder; j++)
            acc -= ckt->CKTag[j] * ckt->CKTstates[j][ccap];
        ckt->CKTstate0[ccap] = acc;
        break;
    }

    case GEAR:
        ckt->CKTstate0[ccap]=0;
        switch(ckt->CKTorder) {

        case 6:
            ckt->CKTstate0[ccap] += ckt->CKTag[6]* ckt->CKTstate6[qcap];
            /* fall through */
        case 5:
            ckt->CKTstate0[ccap] += ckt->CKTag[5]* ckt->CKTstate5[qcap];
            /* fall through */
        case 4:
            ckt->CKTstate0[ccap] += ckt->CKTag[4]* ckt->CKTstate4[qcap];
            /* fall through */
        case 3:
            ckt->CKTstate0[ccap] += ckt->CKTag[3]* ckt->CKTstate3[qcap];
            /* fall through */
        case 2:
            ckt->CKTstate0[ccap] += ckt->CKTag[2]* ckt->CKTstate2[qcap];
            /* fall through */
        case 1:
            ckt->CKTstate0[ccap] += ckt->CKTag[1]* ckt->CKTstate1[qcap];
            ckt->CKTstate0[ccap] += ckt->CKTag[0]* ckt->CKTstate0[qcap];
            break;

        default:
            return(E_ORDER);

        }
        break;

    default:
        errMsg = TMALLOC(char, strlen(methodmsg) + 1);
        strcpy(errMsg,methodmsg);
        return(E_METHOD);
    }
    *ceq = ckt->CKTstate0[ccap] - ckt->CKTag[0] * ckt->CKTstate0[qcap];
    *geq = ckt->CKTag[0] * cap;
    return(OK);
}
