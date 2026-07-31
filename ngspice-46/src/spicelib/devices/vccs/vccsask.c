/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1987 Thomas L. Quarles
**********/

/*
 * This routine gives access to the internal device parameters
 * of Voltage Controlled Current Source
 */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/ifsim.h"
#include "vccsdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"

/* ARGSUSED */
int
VCCSask(CKTcircuit *ckt, GENinstance *inst, int which, IFvalue *value, IFvalue *select)
{
    VCCSinstance *here = (VCCSinstance*)inst;
    double vr;
    double vi;
    double sr;
    double si;
    double vm;
    static char *msg = "Current and power not available for ac analysis";
    switch(which) {
        case VCCS_TRANS:
            value->rValue = here->VCCScoeff;
            return (OK);
        case VCCS_M:
            value->rValue = here->VCCSmValue;
            return (OK);
        case VCCS_POS_NODE:
            value->iValue = here->VCCSposNode;
            return (OK);
        case VCCS_NEG_NODE:
            value->iValue = here->VCCSnegNode;
            return (OK);
        case VCCS_CONT_P_NODE:
            value->iValue = here->VCCScontPosNode;
            return (OK);
        case VCCS_CONT_N_NODE:
            value->iValue = here->VCCScontNegNode;
            return (OK);
        case VCCS_CONT_V_OLD:
            value->rValue = *(ckt->CKTstate0 + here->VCCScontVOld);
            return (OK);
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
        case VCCS_QUEST_SENS_DC:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_Sap[select->iValue + 1]+
                        here->VCCSsenParmNo);
            }
            return(OK);
        case VCCS_QUEST_SENS_REAL:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                        here->VCCSsenParmNo);
            }
            return(OK);
        case VCCS_QUEST_SENS_IMAG:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->VCCSsenParmNo);
            }
            return(OK);
        case VCCS_QUEST_SENS_MAG:
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
                        here->VCCSsenParmNo);
                si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->VCCSsenParmNo);
                value->rValue = (vr * sr + vi * si)/vm;
            }
            return(OK);
        case VCCS_QUEST_SENS_PH:
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
                        here->VCCSsenParmNo);
                si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->VCCSsenParmNo);
                value->rValue =  (vr * si - vi * sr)/vm;
            }
            return(OK);
        case VCCS_QUEST_SENS_CPLX:
            value->cValue.real = 0.0;
            value->cValue.imag = 0.0;
            if(ckt->CKTsenInfo){
                value->cValue.real= 
                        *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                        here->VCCSsenParmNo);
                value->cValue.imag= 
                        *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->VCCSsenParmNo);
            }
            return(OK);
        case VCCS_CURRENT:
            if (ckt->CKTcurrentAnalysis & DOING_AC) {
                errMsg = TMALLOC(char, strlen(msg) + 1);
                errRtn = "VCCSask";
                strcpy(errMsg,msg);
                return(E_ASKCURRENT);
            } else {
                value->rValue = (*(ckt->CKTrhsOld+here->VCCScontPosNode)
                        - *(ckt->CKTrhsOld + here->VCCScontNegNode)) *   
                        (here->VCCScoeff);
            }
            return (OK);
        case VCCS_VOLTS:
	    value->rValue = (*(ckt->CKTrhsOld+here->VCCSposNode)
		- *(ckt->CKTrhsOld + here->VCCSnegNode));
            return (OK);
        case VCCS_POWER:
            if (ckt->CKTcurrentAnalysis & DOING_AC) {
                errMsg = TMALLOC(char, strlen(msg) + 1);
                errRtn = "VCCSask";
                strcpy(errMsg,msg);
                return(E_ASKPOWER);
            } else {
                value->rValue = (*(ckt->CKTrhsOld+here->VCCScontPosNode)
                        - *(ckt->CKTrhsOld + here->VCCScontNegNode)) *  
                        (here->VCCScoeff) * (*(ckt->CKTrhsOld+here->VCCSposNode)
                        - *(ckt->CKTrhsOld + here->VCCSnegNode));
            }
            return (OK);
        default:
            return (E_BADPARM);
    }
    /* NOTREACHED */
}
