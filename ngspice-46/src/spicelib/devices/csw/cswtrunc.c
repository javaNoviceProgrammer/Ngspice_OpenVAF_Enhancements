/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 2000 AlansFixes
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"

#include "cswdefs.h"


/* Enhancement-884 (transient stress campaign 2026-10-12, N1): the
 * current-controlled switch lands on its crossing as the voltage-controlled
 * one does (swtrunc.c, where the reasons are); CSWload's state rule is the
 * same, on the controlling current. */
static double
csw_state(double i, double s1, double it, double ih)
{
    if (ih > 0) {
        if (i > it + ih)
            return 1;
        if (i < it - ih)
            return 0;
        return s1;
    }
    if (i > it - ih)
        return 1;
    if (i < it + ih)
        return 0;
    if (s1 == 2 || s1 == 3)
        return s1;
    return (s1 == 1) ? 2 : 3;
}

#define CSW_ON(s) ((s) == 1 || (s) == 3)

static double
csw_crossing(double i1, double i0, double s1, double it, double ih)
{
    double edge[2], e;
    double dir = (i0 > i1) ? 1.0 : -1.0;
    double eps = 1e-9 * fabs(i0 - i1);
    int k;

    edge[0] = it + ih;
    edge[1] = it - ih;
    if ((edge[1] - i1) * dir < (edge[0] - i1) * dir) {
        e = edge[0]; edge[0] = edge[1]; edge[1] = e;
    }
    for (k = 0; k < 2; k++) {
        e = edge[k];
        if ((e - i1) * dir <= 0 || (e - i0) * dir > 0)
            continue;
        if (CSW_ON(csw_state(e + dir * eps, s1, it, ih)) != CSW_ON(s1))
            return (e - i1) / (i0 - i1);
    }
    return -1.0;
}

static void
csw_land(CKTcircuit *ckt, CSWmodel *model, CSWinstance *here, double *timeStep)
{
    double s1 = ckt->CKTstate1[here->CSWswitchstate];
    double s0 = ckt->CKTstate0[here->CSWswitchstate];
    double i1 = ckt->CKTstate1[here->CSWctrlvalue];
    double i0 = ckt->CKTstate0[here->CSWctrlvalue];
    double theta, land, span;

    here->CSWlandHold = 0;
    if (ckt->CKTlanding || ckt->CKTlandedBreak || CSW_ON(s0) == CSW_ON(s1) || i0 == i1 ||
            ckt->CKTdelta <= 20.0 * ckt->CKTdelmin)
        return;
    theta = csw_crossing(i1, i0, s1, model->CSWiThreshold, model->CSWiHysteresis);
    if (theta <= 0.0 || theta > 1.0)
        return;
    land = theta * ckt->CKTdelta;
    span = ckt->CKTfinalTime - ckt->CKTinitTime;
    if (theta < 1e-3 || (span > 0.0 && land < span * 1e-12))
        return;
    here->CSWlandHold = 1;
    CKTlandRequest(ckt, land, 1, timeStep);
}

int
CSWtrunc(GENmodel *inModel, CKTcircuit *ckt, double *timeStep)
{
    CSWmodel *model = (CSWmodel *) inModel;
    CSWinstance *here;

    /* Enhancement-884: the landing only. Stock ngspice also limited the step
       as the controlling current approached the threshold (SWtrunc's rule),
       but that limit never ran: CSWload did not store the control value it
       read, so the change it saw was 0. The value is stored now, for the
       landing, and the limit is left out, as before. */
    for (; model; model = CSWnextModel(model))
        for (here = CSWinstances(model); here; here = CSWnextInstance(here))
            csw_land(ckt, model, here, timeStep);

    return OK;
}
