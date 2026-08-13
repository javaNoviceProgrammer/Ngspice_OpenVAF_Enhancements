/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1987 Thomas L. Quarles
**********/
/*
 */

/*
 * This routine gives access to the internal device parameters
 * of independent Voltage SouRCe
 */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/ifsim.h"
#include "vsrcdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"


/* Enhancement-447: which waveform a given query parameter belongs to, so an ask
   for one waveform's coefficients can be refused when a DIFFERENT waveform is
   the one actually declared. Returns 0 for anything that is not a waveform. */
static int VSRCfnTypeOf(int which)
{
    switch (which) {
    case VSRC_PULSE:    return PULSE;
    case VSRC_SINE:     return SINE;
    case VSRC_EXP:      return EXP;
    case VSRC_PWL:      return PWL;
    case VSRC_SFFM:     return SFFM;
    case VSRC_AM:       return AM;
    case VSRC_TRNOISE:  return TRNOISE;
    case VSRC_TRRANDOM: return TRRANDOM;
    default:            return 0;
    }
}

/* ARGSUSED */
int
VSRCask(CKTcircuit *ckt, GENinstance *inst, int which, IFvalue *value, IFvalue *select)
{
    VSRCinstance *here = (VSRCinstance*)inst;
    static char *msg = "Current and power not available in ac analysis";
    int temp;
    double *v, *w;

    NG_IGNORE(select);

    switch(which) {
        case VSRC_DC:
            value->rValue = here->VSRCdcValue;
            return (OK);
        case VSRC_AC_MAG:
            value->rValue = here->VSRCacMag;
            return (OK);
        case VSRC_AC_PHASE:
            value->rValue = here->VSRCacPhase;
            return (OK);
        case VSRC_PULSE:
        case VSRC_SINE:
        case VSRC_EXP:
        case VSRC_PWL:
        case VSRC_SFFM:
        case VSRC_AM:
        case VSRC_TRNOISE:
        case VSRC_TRRANDOM:
            /* Enhancement-447: every waveform shares one VSRCcoeffs array, and
               all eight of these used to answer from it unconditionally. So
               `show v1` on a source declared only `sin(0 2 3k)` reported the
               coefficients 0/2/3000 EIGHT times -- once under `sin` and once
               under each of pulse, exp, pwl, sffm, am, trnoise and trrandom --
               positively asserting seven stimuli the source does not have.
               `show` could not be used to find out which waveform a source
               actually had. Only the ACTIVE function answers now; the generic
               VSRC_FCN_COEFFS query below still returns the raw array. */
            if (VSRCfnTypeOf(which) != here->VSRCfunctionType) {
                /* Report it as EMPTY rather than as an error: `show` then
                   renders a bare "-" for it, exactly as it already does for a
                   source with no transient waveform at all, instead of a column
                   of "<<NAN, error>>". */
                value->v.numValue = 0;
                value->v.vec.rVec = NULL;
                return (OK);
            }
            /* FALLTHROUGH */
        case VSRC_FCN_COEFFS:
            temp = value->v.numValue = here->VSRCfunctionOrder;
            v = value->v.vec.rVec = TMALLOC(double, here->VSRCfunctionOrder);
            w = here->VSRCcoeffs;
            while (temp--)
                *v++ = *w++;
            return (OK);
        case VSRC_AC:
            value->v.numValue = 2;
            value->v.vec.rVec = TMALLOC(double, value->v.numValue);
            value->v.vec.rVec[0] = here->VSRCacMag;
            value->v.vec.rVec[1] = here->VSRCacPhase;
            return (OK);
        case VSRC_NEG_NODE:
            value->iValue = here->VSRCnegNode;
            return (OK);
        case VSRC_POS_NODE:
            value->iValue = here->VSRCposNode;
            return (OK);
        case VSRC_FCN_TYPE:
            value->iValue = here->VSRCfunctionType;
            return (OK);
        case VSRC_AC_REAL:
            value->rValue = here->VSRCacReal;
            return (OK);
        case VSRC_AC_IMAG:
            value->rValue = here->VSRCacImag;
            return (OK);
        case VSRC_R:
            value->rValue = here->VSRCr;
            return (OK);
        case VSRC_TD:
            value->rValue = here->VSRCrdelay;
            return (OK);
        case VSRC_FCN_ORDER:
            value->rValue = here->VSRCfunctionOrder;
            return (OK);
        case VSRC_CURRENT:
            if (ckt->CKTcurrentAnalysis & DOING_AC) {
                FREE(errMsg);
                errMsg = TMALLOC(char, strlen(msg) + 1);
                errRtn = "VSRCask";
                strcpy(errMsg,msg);
                return(E_ASKCURRENT);
            } else {
                if (ckt->CKTrhsOld)
                    value->rValue = *(ckt->CKTrhsOld + here->VSRCbranch);
                else
                    value->rValue = 0.;
            }
            return(OK);
        case VSRC_POWER:
            if (ckt->CKTcurrentAnalysis & DOING_AC) {
                FREE(errMsg);
                errMsg = TMALLOC(char, strlen(msg) + 1);
                errRtn = "VSRCask";
                strcpy(errMsg,msg);
                return(E_ASKPOWER);
            } else {
                value->rValue = (*(ckt->CKTrhsOld+here->VSRCposNode)
                        - *(ckt->CKTrhsOld + here->VSRCnegNode)) *
                         *(ckt->CKTrhsOld + here->VSRCbranch);
            }
            return(OK);
#ifdef RFSPICE
        case VSRC_PORTNUM:
            value->rValue = here->VSRCportNum;
            return (OK);
        case VSRC_PORTZ0:
            value->rValue = here->VSRCportZ0;
            return (OK);
        case VSRC_PORTPWR:
            value->rValue = here->VSRCportPower;
            return (OK);
        case VSRC_PORTFREQ:
            value->rValue = here->VSRCportFreq;
            return (OK);
        case VSRC_PORTPHASE:
            value->rValue = here->VSRCportPhase;
            return (OK);
#endif
#ifdef SHARED_MODULE
        case VSRC_EXTERNAL:
            /* Don't do anything */
            return (OK);
#endif
        default:
            return (E_BADPARM);
    }
    /* NOTREACHED */
}
