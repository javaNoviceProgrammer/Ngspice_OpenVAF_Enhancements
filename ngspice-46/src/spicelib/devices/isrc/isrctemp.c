/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/smpdefs.h"
#include "ngspice/cktdefs.h"
#include "isrcdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"

/*ARGSUSED*/
int
ISRCtemp(GENmodel *inModel, CKTcircuit *ckt)
        /* Pre-process voltage source parameters
         */
{
    ISRCmodel *model = (ISRCmodel *) inModel;
    ISRCinstance *here;
    double radians;

    NG_IGNORE(ckt);

    /*  loop through all the voltage source models */
    for( ; model != NULL; model = ISRCnextModel(model)) {

        /* loop through all the instances of the model */
        for (here = ISRCinstances(model); here != NULL ;
                here=ISRCnextInstance(here)) {

            if(here->ISRCacGiven && !here->ISRCacMGiven) {
                here->ISRCacMag = 1;
            }
            if(here->ISRCacGiven && !here->ISRCacPGiven) {
                here->ISRCacPhase = 0;
            }
            if (!here->ISRCdcGiven && !here->ISRCfuncTGiven) {
                /* no DC value, no transient value */
                SPfrontEnd->IFerrorf(ERR_INFO,
                    "%s: has no value, DC 0 assumed",
                    here->ISRCname);
            }
            else if (here->ISRCdcGiven && here->ISRCfuncTGiven
                    && here->ISRCfunctionType != TRNOISE
                    && here->ISRCfunctionType != TRRANDOM
                    && here->ISRCfunctionType != EXTERNAL) {
                /* DC value and transient time 0 values given */
                double time0value;
                /* determine transient time 0 value */
                if (here->ISRCfunctionType == AM || here->ISRCfunctionType == PWL)
                    time0value = here->ISRCcoeffs[1];
                else
                    time0value = here->ISRCcoeffs[0];
                /* No warning issued if DC value and transient time 0 value are the same */
    /* Enhancement-513: this note describes a STATIC property of the deck -- the
     * source carries both a DC value and a transient function whose t=0 value
     * differs -- but it was emitted from ISRCTEMP, which CKTdoJob runs once per
     * ANALYSIS. A loop command therefore repeated it once per point: a 100-sample
     * `montecarlo` printed it 100 times, and because Enhancement-477's progress
     * line redraws with '\r', each copy landed on the bar and mangled both
     * ("...time=0 value.ran  47%)"). Latched per instance, so it is said once per
     * deck load and again after a re-source, which rebuilds the instances. */
                if (!AlmostEqualUlps(time0value, here->ISRCdcValue, 3)
                        && !here->ISRCdcNoteDone) {
                    here->ISRCdcNoteDone = 1;
                    SPfrontEnd->IFerrorf(ERR_INFO,
                        "%s: dc value used for op instead of transient time=0 value.",
                        here->ISRCname);
                }
            }
            if(!here->ISRCmGiven)
                here->ISRCmValue = 1;
            radians = here->ISRCacPhase * M_PI / 180.0;
            here->ISRCacReal = here->ISRCacMag * cos(radians);
            here->ISRCacImag = here->ISRCacMag * sin(radians);
        }
    }

    return(OK);
}
