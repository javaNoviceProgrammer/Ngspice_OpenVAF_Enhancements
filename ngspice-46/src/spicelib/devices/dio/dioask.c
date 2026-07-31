/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified by Paolo Nenzi 2003 and Dietmar Warning 2012
**********/

#include "ngspice/ngspice.h"
#include "ngspice/const.h"
#include "ngspice/devdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/cktdefs.h"
#include "diodefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"

/* ARGSUSED */
int
DIOask (CKTcircuit *ckt, GENinstance *inst, int which, IFvalue *value, 
        IFvalue *select)
{
    DIOinstance *here = (DIOinstance*)inst;
    double vr;
    double vi;
    double sr;
    double si;
    double vm;
    static char *msg = "Current and power not available for ac analysis";

    switch (which) {
        case DIO_OFF:
            value->iValue = here->DIOoff;
            return(OK);
        case DIO_IC:
            value->rValue = here->DIOinitCond;
            return(OK);
        case DIO_AREA:
            value->rValue = here->DIOarea;
            return(OK);
        case DIO_PJ:
            value->rValue = here->DIOpj;
            return(OK);
        case DIO_W:
            value->rValue = here->DIOw;
            return(OK);
        case DIO_L:
            value->rValue = here->DIOl;
            return(OK);
        case DIO_M:
            value->rValue = here->DIOm;
            return(OK);
        case DIO_LM:
            value->rValue = here->DIOlengthMetal;
            return(OK);
        case DIO_LP:
            value->rValue = here->DIOlengthPoly;
            return(OK);
        case DIO_WM:
            value->rValue = here->DIOwidthMetal;
            return(OK);
        case DIO_WP:
            value->rValue = here->DIOwidthPoly;
            return(OK);
        case DIO_THERMAL:
            value->iValue = here->DIOthermal;
            return(OK);

        case DIO_TEMP:
            value->rValue = here->DIOtemp-CONSTCtoK;
            return(OK);
        case DIO_DTEMP:
            value->rValue = here->DIOdtemp;
            return(OK);    
        case DIO_VOLTAGE:
            value->rValue = *(ckt->CKTstate0+here->DIOvoltage);
            return(OK);
        case DIO_CURRENT:
            value->rValue = *(ckt->CKTstate0+here->DIOcurrent);
            if ((here->DIOqpNode > 0) && (here->DIOtTransitTime!=0))
                value->rValue += here->DIOqpGain * *(ckt->CKTstate0 + here->DIOcqcsr);
            return(OK);
        case DIO_CAP: 
            value->rValue = here->DIOcap;
            if ((here->DIOqpNode > 0) && (here->DIOtTransitTime!=0))
                value->rValue += here->DIOtTransitTime * *(ckt->CKTstate0+here->DIOconduct);
            return(OK);
        case DIO_CHARGE: 
            value->rValue = *(ckt->CKTstate0+here->DIOcapCharge);
            if ((here->DIOqpNode > 0) && (here->DIOtTransitTime!=0))
                value->rValue += here->DIOqpGain * *(ckt->CKTstate0 + here->DIOsrcapCharge);
            return(OK);
        case DIO_CAPCUR:
            value->rValue = *(ckt->CKTstate0+here->DIOcapCurrent);
            return(OK);
        case DIO_CONDUCT:
            value->rValue = *(ckt->CKTstate0+here->DIOconduct);
            return(OK);
        case DIO_POWER :
            if (ckt->CKTcurrentAnalysis & DOING_AC) {
                errMsg = TMALLOC(char, strlen(msg) + 1);
                errRtn = "DIOask";
                strcpy(errMsg,msg);
                return(E_ASKPOWER);
            } else {
                value->rValue = *(ckt->CKTstate0 + here->DIOcurrent) *
                        *(ckt->CKTstate0 + here->DIOvoltage) +
                        *(ckt->CKTstate0 + here->DIOcurrent) *
                        *(ckt->CKTstate0 + here->DIOcurrent) / here->DIOtConductance;
            }
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
        case DIO_QUEST_SENS_DC:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_Sap[select->iValue + 1]+
                here->DIOsenParmNo);
            }
            return(OK);
        case DIO_QUEST_SENS_REAL:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                here->DIOsenParmNo);
            }
            return(OK);
        case DIO_QUEST_SENS_IMAG:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                here->DIOsenParmNo);
            }
            return(OK);
        case DIO_QUEST_SENS_MAG:
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
                        here->DIOsenParmNo);
                si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->DIOsenParmNo);
                value->rValue = (vr * sr + vi * si)/vm;
            }
            return(OK);
        case DIO_QUEST_SENS_PH:
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
                        here->DIOsenParmNo);
                si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->DIOsenParmNo);

                value->rValue = (vr * si - vi * sr)/vm;
            }
            return(OK);
        case DIO_QUEST_SENS_CPLX:
            value->cValue.real = 0.0;
            value->cValue.imag = 0.0;
            if(ckt->CKTsenInfo){
                value->cValue.real= 
                        *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                        here->DIOsenParmNo);
                value->cValue.imag= 
                        *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->DIOsenParmNo);
            }
            return(OK);
        default:
            return(E_BADPARM);
        }
}  

