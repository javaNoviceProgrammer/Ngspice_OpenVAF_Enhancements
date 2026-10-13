/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 2000 AlansFixes
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"
#include "swdefs.h"


/* Enhancement-884 (transient stress campaign 2026-10-12, N1): SWload's
 * state rule, from the state `s1` at the last accepted point, for a control
 * value `v`: on above vt + vh and off below vt - vh with hysteresis; with none
 * or a negative one, the band between the edges is entered as the state the
 * switch was not in, and kept (states: 0 off, 1 on, 2 off and 3 on in the
 * band). */
static double
sw_state(double v, double s1, double vt, double vh)
{
    if (vh > 0) {
        if (v > vt + vh)
            return 1;
        if (v < vt - vh)
            return 0;
        return s1;
    }
    if (v > vt - vh)
        return 1;
    if (v < vt + vh)
        return 0;
    if (s1 == 2 || s1 == 3)
        return s1;
    return (s1 == 1) ? 2 : 3;
}

#define SW_ON(s) ((s) == 1 || (s) == 3)

/* The fraction of the step under way at which the control, linear from `v1`
 * at the accepted point to `v0` at this attempt, crosses the band edge that
 * turns the switch over from `s1`; -1 when no edge does. */
static double
sw_crossing(double v1, double v0, double s1, double vt, double vh)
{
    double edge[2], e;
    double dir = (v0 > v1) ? 1.0 : -1.0;
    double eps = 1e-9 * fabs(v0 - v1);
    int i;

    edge[0] = vt + vh;
    edge[1] = vt - vh;
    /* the nearer edge first */
    if ((edge[1] - v1) * dir < (edge[0] - v1) * dir) {
        e = edge[0]; edge[0] = edge[1]; edge[1] = e;
    }
    for (i = 0; i < 2; i++) {
        e = edge[i];
        if ((e - v1) * dir <= 0 || (e - v0) * dir > 0)
            continue;
        if (SW_ON(sw_state(e + dir * eps, s1, vt, vh)) != SW_ON(s1))
            return (e - v1) / (v0 - v1);
    }
    return -1.0;
}

/* Enhancement-884: a switch that turned over in the point under way asks for
 * the point to be redone at its crossing (Enhancement-759's landing). Stock
 * ngspice let the truncation estimate find the crossing: the estimate at a
 * crossing measures the jump in the current the switching brings, the point
 * was rejected, the retry fell short of the crossing and was accepted, and the
 * next point crossed again -- the accepted points crept up to the crossing,
 * each closer than the last. At reltol 1e-6 the steps reached 1e-16 s, where
 * rounding in the integration is larger than Newton's tolerance, and a switch
 * with no hysteresis ended the run with "Timestep too small". Landed, a
 * crossing costs one rejected point. The landing lies on the crossing, the
 * control's linear interpolation between the accepted point and the attempt,
 * and the switch keeps its accepted state there (SWload, SWlandHold): the
 * circuit is integrated with the old state up to the crossing and with the new
 * one from it, which leaves no gap to creep across. dctran takes the step
 * after the landing, the one the switch turns over in, at order 1, as after a
 * source's corner. No request from the landing itself, from the step after a
 * landing, or for a crossing in the first thousandth of the step, which is the
 * step's start. */
static void
sw_land(CKTcircuit *ckt, SWmodel *model, SWinstance *here, double *timeStep)
{
    double s1 = ckt->CKTstate1[here->SWswitchstate];
    double s0 = ckt->CKTstate0[here->SWswitchstate];
    double v1 = ckt->CKTstate1[here->SWctrlvalue];
    double v0 = ckt->CKTstate0[here->SWctrlvalue];
    double theta, land, span;

    here->SWlandHold = 0;
    if (ckt->CKTlanding || ckt->CKTlandedBreak || SW_ON(s0) == SW_ON(s1) || v0 == v1 ||
            ckt->CKTdelta <= 20.0 * ckt->CKTdelmin)
        return;
    theta = sw_crossing(v1, v0, s1, model->SWvThreshold, model->SWvHysteresis);
    if (theta <= 0.0 || theta > 1.0)
        return;
    land = theta * ckt->CKTdelta;
    span = ckt->CKTfinalTime - ckt->CKTinitTime;
    if (theta < 1e-3 || (span > 0.0 && land < span * 1e-12))
        return;
    here->SWlandHold = 1;
    CKTlandRequest(ckt, land, 1, timeStep);
}

int
SWtrunc(GENmodel *inModel, CKTcircuit *ckt, double *timeStep)
{
    SWmodel *model = (SWmodel *) inModel;
    SWinstance *here;
    double   lastChange, maxChange, maxStep, ref;

    for (; model; model = SWnextModel(model))
        for (here = SWinstances(model); here; here = SWnextInstance(here)) {
            sw_land(ckt, model, here, timeStep);
            lastChange =
                ckt->CKTstate0[here->SWctrlvalue] -
                ckt->CKTstate1[here->SWctrlvalue];
            if (ckt->CKTstate0[here->SWswitchstate] == 0) {
                ref = model->SWvThreshold + model->SWvHysteresis;
                if (ckt->CKTstate0[here->SWctrlvalue] < ref && lastChange > 0) {
                    maxChange =
                        (ref - ckt->CKTstate0[here->SWctrlvalue]) * 0.75
                        + 0.05;
                    maxStep = maxChange / lastChange * ckt->CKTdeltaOld[0];
                    if (*timeStep > maxStep)
                        *timeStep = maxStep;
                }
            } else {
                ref = model->SWvThreshold - model->SWvHysteresis;
                if (ckt->CKTstate0[here->SWctrlvalue] > ref && lastChange < 0) {
                    maxChange =
                        (ref - ckt->CKTstate0[here->SWctrlvalue]) * 0.75
                        - 0.05;
                    maxStep = maxChange / lastChange * ckt->CKTdeltaOld[0];
                    if (*timeStep > maxStep)
                        *timeStep = maxStep;
                }
            }
        }

    return OK;
}
