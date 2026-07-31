/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "inddefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"


/*ARGSUSED*/
int
MUTask(CKTcircuit *ckt, GENinstance *inst, int which, IFvalue *value,
       IFvalue *select)
{
    MUTinstance *here = (MUTinstance*)inst;
    double vr;
    double vi;
    double sr;
    double si;
    double vm;
    switch(which) {
        case MUT_COEFF:
            value->rValue = here->MUTfactor;
            return(OK);
        case MUT_IND1:
            value->uValue = here->MUTindName1;
            return(OK);
        case MUT_IND2:
            value->uValue = here->MUTindName2;
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
        case MUT_QUEST_SENS_DC:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_Sap[select->iValue + 1]+
                        here->MUTsenParmNo);
            }
            return(OK);
        case MUT_QUEST_SENS_REAL:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                        here->MUTsenParmNo);
            }
            return(OK);
        case MUT_QUEST_SENS_IMAG:
            value->rValue = 0.0;
            if(ckt->CKTsenInfo){
                value->rValue = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->MUTsenParmNo);
            }
            return(OK);
        case MUT_QUEST_SENS_MAG:
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
                        here->MUTsenParmNo);
                si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->MUTsenParmNo);
                value->rValue = (vr * sr + vi * si)/vm;
            }
            return(OK);
        case MUT_QUEST_SENS_PH:
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
                        here->MUTsenParmNo);
                si = *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->MUTsenParmNo);
                value->rValue = (vr * si - vi * sr)/vm;
            }
            return(OK);
        case MUT_QUEST_SENS_CPLX:
            value->cValue.real = 0.0;
            value->cValue.imag = 0.0;
            if(ckt->CKTsenInfo){
                value->cValue.real= 
                        *(ckt->CKTsenInfo->SEN_RHS[select->iValue + 1]+
                        here->MUTsenParmNo);
                value->cValue.imag= 
                        *(ckt->CKTsenInfo->SEN_iRHS[select->iValue + 1]+
                        here->MUTsenParmNo);
            }
            return(OK);
        default:
            return(E_BADPARM);
    }
    /* NOTREACHED */
}
