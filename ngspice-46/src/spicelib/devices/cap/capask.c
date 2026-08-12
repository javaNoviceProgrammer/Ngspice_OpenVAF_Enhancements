/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: September 2003 Paolo Nenzi
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "capdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"

/* ARGSUSED */
int
CAPask(CKTcircuit *ckt, GENinstance *inst, int which, IFvalue *value,
       IFvalue *select)
{
    CAPinstance *here = (CAPinstance *)inst;
    double vr;
    double vi;
    double sr;
    double si;
    double vm;
    static char *msg = "Current and power not available for ac analysis";

    switch(which) {
        case CAP_TEMP:
            value->rValue = here->CAPtemp - CONSTCtoK;
            return(OK);
        case CAP_DTEMP:
            value->rValue = here->CAPdtemp;
            return(OK);
        case CAP_CAP:
            /* Enhancement-446: report the capacitance this instance was GIVEN,
               not the m-multiplied total. `@c1[capacitance]` folded m in while
               `@r1[resistance]` reported the written value, so the same accessor
               idiom meant two different things depending on device type and a
               script reading a deck back got 2u for `C1 a b 1u m=2`.

               The simulation is untouched: capload.c applies m to the matrix
               stamps itself, so this is purely what the query reports. */
            value->rValue=here->CAPcapac;
            return(OK);
        case CAP_IC:
            value->rValue = here->CAPinitCond;
            return(OK);
        case CAP_WIDTH:
            value->rValue = here->CAPwidth;
            return(OK);
        case CAP_LENGTH:
            value->rValue = here->CAPlength;
            return(OK);
        case CAP_SCALE:
            value->rValue = here->CAPscale;
            return(OK);
	case CAP_BV_MAX:
	    value->rValue = here->CAPbv_max;
	    return(OK);
        case CAP_M:
            value->rValue = here->CAPm;
            return(OK);
        case CAP_TC1:
            value->rValue = here->CAPtc1;
            return(OK);
        case CAP_TC2:
            value->rValue = here->CAPtc2;
            return(OK);
        case CAP_CURRENT:
            if (ckt->CKTcurrentAnalysis & DOING_AC) {
                errMsg = TMALLOC(char, strlen(msg) + 1);
                errRtn = "CAPask";
                strcpy(errMsg,msg);
                return(E_ASKCURRENT);
            } else if (ckt->CKTcurrentAnalysis & (DOING_DCOP | DOING_TRCV)) {
                value->rValue = 0;
            } else if (ckt->CKTcurrentAnalysis & DOING_TRAN) {
                if (ckt->CKTmode & MODETRANOP) {
                    value->rValue = 0;
                } else {
                    value->rValue = *(ckt->CKTstate0 + here->CAPccap);
                }
            } else value->rValue = *(ckt->CKTstate0 + here->CAPccap);

            value->rValue *= here->CAPm;

            return(OK);
        case CAP_POWER:
            if (ckt->CKTcurrentAnalysis & DOING_AC) {
                errMsg = TMALLOC(char, strlen(msg) + 1);
                errRtn = "CAPask";
                strcpy(errMsg,msg);
                return(E_ASKPOWER);
            } else if (ckt->CKTcurrentAnalysis & (DOING_DCOP | DOING_TRCV)) {
                value->rValue = 0;
            } else if (ckt->CKTcurrentAnalysis & DOING_TRAN) {
                if (ckt->CKTmode & MODETRANOP) {
                    value->rValue = 0;
                } else {
                    value->rValue = *(ckt->CKTstate0 + here->CAPccap) *
                            (*(ckt->CKTrhsOld + here->CAPposNode) -
                            *(ckt->CKTrhsOld + here->CAPnegNode));
                }
            } else value->rValue = *(ckt->CKTstate0 + here->CAPccap) *
                            (*(ckt->CKTrhsOld + here->CAPposNode) -
                            *(ckt->CKTrhsOld + here->CAPnegNode));

            value->rValue *= here->CAPm;

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
        case CAP_QUEST_SENS_DC:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
               value->rValue = *(ckt->CKTsenInfo->SEN_Sap[select->iValue + 1]+
                    here->CAPsenParmNo);
            }
            return(OK);
        case CAP_QUEST_SENS_REAL:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
               value->rValue = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                    here->CAPsenParmNo);
            }
            return(OK);
        case CAP_QUEST_SENS_IMAG:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
               value->rValue = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                    here->CAPsenParmNo);
            }
            return(OK);
        case CAP_QUEST_SENS_MAG:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
               vr = *(ckt->CKTrhsOld + select->iValue + 1);
               vi = *(ckt->CKTirhsOld + select->iValue + 1);
               vm = sqrt(vr*vr + vi*vi);
               if(vm == 0){
                 value->rValue = 0;
                 return(OK);
               }
               sr = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                    here->CAPsenParmNo);
               si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                    here->CAPsenParmNo);
                   value->rValue = (vr * sr + vi * si)/vm;
            }
            return(OK);
        case CAP_QUEST_SENS_PH:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
               vr = *(ckt->CKTrhsOld + select->iValue + 1);
               vi = *(ckt->CKTirhsOld + select->iValue + 1);
               vm = vr*vr + vi*vi;
               if(vm == 0){
                 value->rValue = 0;
                 return(OK);
               }
               sr = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                    here->CAPsenParmNo);
               si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                    here->CAPsenParmNo);

                   value->rValue = (vr * si - vi * sr)/vm;
            }
            return(OK);

        case CAP_QUEST_SENS_CPLX:
            value->cValue.real = 0.0;
            value->cValue.imag = 0.0;
            if(ckt->CKTsenInfo){
                value->cValue.real=
                        *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                        here->CAPsenParmNo);
                value->cValue.imag=
                        *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->CAPsenParmNo);
            }
            return(OK);

        default:
            return(E_BADPARM);
        }
}

