/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: Apr 2000 - Paolo Nenzi
**********/

#include "ngspice/ngspice.h"
#include "ngspice/const.h"
#include "resdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"


/* TODO : there are "double" value compared with 0 (eg: vm == 0)
 *        Need to substitute this check with a suitable eps.
 *        PN 2003
 */

int
RESask(CKTcircuit *ckt, GENinstance *inst, int which, IFvalue *value,
       IFvalue *select)
{
    RESinstance *fast = (RESinstance *)inst;
    double vr;
    double vi;
    double sr;
    double si;
    double vm;
    static char *msg = "Current and power not available for ac analysis";

    switch(which) {
    case RES_TEMP:
        value->rValue = fast->REStemp - CONSTCtoK;
        return(OK);
    case RES_DTEMP:
        value->rValue = fast->RESdtemp;
        return(OK);
    case RES_CONDUCT:
        value->rValue = fast->RESconduct;
        return(OK);
    case RES_RESIST:
        /* Enhancement-447 considered reporting the EFFECTIVE resistance here
           (restemp.c folds the temperature factor and `scale` into RESconduct
           and leaves RESresist nominal, so this answers 1000 for a `1k
           tc1=0.001` that behaves as 1073 at 100 C). It is deliberately left
           NOMINAL: Enhancement-426 settled this convention and documents
           `1/@r1[conductance]` as the way to read what is actually stamped --
           its suite asserts both halves. @c[capacitance] and @l[inductance]
           fold their temperature in, so the three devices do disagree, but that
           is a settled convention rather than a defect to flip here. */
        value->rValue = fast->RESresist;
        return(OK);
    case RES_ACCONDUCT:
        value->rValue = fast->RESacConduct;
        return (OK);
    case RES_ACRESIST:
        value->rValue = fast->RESacResist;
        return(OK);
    case RES_LENGTH:
        value->rValue = fast->RESlength;
        return(OK);
    case RES_WIDTH:
        value->rValue = fast->RESwidth;
        return(OK);
    case RES_SCALE:
        value->rValue = fast->RESscale;
        return(OK);
    case RES_M:
        value->rValue = fast->RESm;
        return(OK);
    case RES_TC1:
        value->rValue = fast->REStc1;
        return(OK);
    case RES_TC2:
        value->rValue = fast->REStc2;
        return(OK);
    case RES_TCE:
        value->rValue = fast->REStce;
        return(OK);
    case RES_BV_MAX:
        value->rValue = fast->RESbv_max;
        return(OK);
    case RES_NOISY:
        value->iValue = fast->RESnoisy;
        return(OK);
    /* Enhancement-386: the sensitivity queries below answer 0 when there is no
     * sensitivity data, instead of leaving *value untouched and returning OK.
     *
     * They used to write nothing at all unless ckt->CKTsenInfo was set -- which
     * it never is on an ordinary run -- yet still returned OK, so the caller read
     * whatever happened to be in its IFvalue. In the frontend that is a `static
     * IFvalue` reused by every query (spiceif.c, doask), so `print @r1[sens_cplx]`
     * handed back the PREVIOUS query's bytes reinterpreted as a double: denormal
     * garbage like 2.12736e-314 that changed between runs and between calls.
     * Two other callers pass an uninitialised STACK IFvalue (dctrcurv.c, which
     * then saves the result as a parameter's nominal to restore later, and
     * cktsens.c's sens_getp), so this had to be fixed in the handlers rather than
     * in any one caller.
     *
     * Zero matches the intent already in the code: the MAG and PH cases return
     * `value->rValue = 0` explicitly when the response magnitude is zero. */
    case RES_QUEST_SENS_DC:
        value->rValue = 0.0;
        if (ckt->CKTsenInfo) {
            value->rValue = *(ckt->CKTsenInfo->SEN_Sap[select->iValue + 1] +
                              fast->RESsenParmNo);
        }
        return(OK);
    case RES_QUEST_SENS_REAL:
        value->rValue = 0.0;
        if (ckt->CKTsenInfo) {
            value->rValue = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1] +
                              fast->RESsenParmNo);
        }
        return(OK);
    case RES_QUEST_SENS_IMAG:
        value->rValue = 0.0;
        if (ckt->CKTsenInfo) {
            value->rValue = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1] +
                              fast->RESsenParmNo);
        }
        return(OK);
    case RES_QUEST_SENS_MAG:
        value->rValue = 0.0;
        if (ckt->CKTsenInfo) {
            vr = *(ckt->CKTrhsOld + select->iValue + 1);
            vi = *(ckt->CKTirhsOld + select->iValue + 1);
            vm = sqrt(vr*vr + vi*vi);
            if (vm == 0) {
                value->rValue = 0;
                return(OK);
            }
            sr = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1] +
                   fast->RESsenParmNo);
            si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1] +
                   fast->RESsenParmNo);
            value->rValue = (vr * sr + vi * si) / vm;
        }
        return(OK);
    case RES_QUEST_SENS_PH:
        value->rValue = 0.0;
        if (ckt->CKTsenInfo) {
            vr = *(ckt->CKTrhsOld + select->iValue + 1);
            vi = *(ckt->CKTirhsOld + select->iValue + 1);
            vm = vr*vr + vi*vi;
            if (vm == 0) {
                value->rValue = 0;
                return(OK);
            }
            sr = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1] +
                   fast->RESsenParmNo);
            si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1] +
                   fast->RESsenParmNo);
            value->rValue = (vr * si - vi * sr) / vm;
        }
        return(OK);
    case RES_QUEST_SENS_CPLX:
        value->cValue.real = 0.0;
        value->cValue.imag = 0.0;
        if (ckt->CKTsenInfo) {
            value->cValue.real=
                *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1] +
                  fast->RESsenParmNo);
            value->cValue.imag=
                *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1] +
                  fast->RESsenParmNo);
        }
        return(OK);
    case RES_CURRENT:
        if (ckt->CKTcurrentAnalysis & DOING_AC) {
            errMsg = tprintf("%s: %s", inst->GENname, msg);
            errRtn = "RESask";
            return(E_ASKCURRENT);
        } else if (ckt->CKTrhsOld) {
            value->rValue = (*(ckt->CKTrhsOld + fast->RESposNode) -
                             *(ckt->CKTrhsOld + fast->RESnegNode));
            value->rValue *= fast->RESconduct;
            return(OK);
        } else {
            errMsg = tprintf("No current values available for %s", fast->RESname);
            errRtn = "RESask";
            return(E_ASKCURRENT);
        }
    case RES_POWER:
        if (ckt->CKTcurrentAnalysis & DOING_AC) {
            errMsg = tprintf("%s: %s", inst->GENname, msg);
            errRtn = "RESask";
            return(E_ASKPOWER);
        } else if (ckt->CKTrhsOld) {
            value->rValue = (*(ckt->CKTrhsOld + fast->RESposNode) -
                             *(ckt->CKTrhsOld + fast->RESnegNode)) *
                            (*(ckt->CKTrhsOld + fast->RESposNode) -
                             *(ckt->CKTrhsOld + fast->RESnegNode));
            value->rValue *= fast->RESconduct;
            return(OK);
        } else {
            errMsg = tprintf("No power values available for %s", fast->RESname);
            errRtn = "RESask";
            return(E_ASKCURRENT);
        }
        
    default:
        return(E_BADPARM);
    }
    /* NOTREACHED */
}
