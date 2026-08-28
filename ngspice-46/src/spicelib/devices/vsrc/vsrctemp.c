/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/smpdefs.h"
#include "ngspice/cktdefs.h"
#include "vsrcdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"

/*ARGSUSED*/
int
VSRCtemp(GENmodel *inModel, CKTcircuit *ckt)
        /* Pre-process voltage source parameters
         */
{
    VSRCmodel *model = (VSRCmodel *) inModel;
    VSRCinstance *here;
    double radians;

    NG_IGNORE(ckt);

#ifdef RFSPICE
    ckt->CKTportCount = 0;
    int* portIDs;
    int  prevPort;
#endif

    /*  loop through all the voltage source models */
    for( ; model != NULL; model = VSRCnextModel(model)) {

        /* loop through all the instances of the model */
        for (here = VSRCinstances(model); here != NULL ;
                here=VSRCnextInstance(here)) {

            /* Enhancement-498: re-arm the transient breakpoint schedule.
             *
             * VSRCbreak_time is per-RUN state, not topology: VSRCaccept walks
             * it forward across a transient and only schedules the next edge
             * when `CKTtime >= VSRCbreak_time`. VSRCsetup seeds it to -1.0 so
             * the first accepted point arms the first edge.
             *
             * Enhancement-471's setup-reuse fast path skips CKTunsetup/CKTsetup
             * between sweep points, so the seed never ran again and the instance
             * carried the PREVIOUS run's break time -- a value at or past that
             * run's TSTOP. At t=0 of the next run the test was false, and it
             * stayed false for the whole run: a PULSE or PWL source scheduled
             * NO breakpoints at all and the stepper walked straight over every
             * edge. A 5-point sweep of an RC driven by a narrow PWL pulse put
             * `maximum(v(n))` 44% out (106% at other spacings) while reporting
             * nothing, and `optimize` fitted a parameter 13% wrong and called
             * it converged. Sources with no breakpoints (SIN, EXP, dc) and
             * every non-transient analysis were unaffected, which is why the
             * reuse suites -- none of which contain a PULSE or PWL source --
             * stayed green.
             *
             * CKTtemp runs once per job on BOTH paths (the reuse branch calls
             * it explicitly, to re-decide OSDI node collapse), and does not run
             * on a `resume`, so this re-arms exactly when a new analysis starts
             * and leaves a continued run alone. */
            here->VSRCbreak_time = -1.0;

            if(here->VSRCacGiven && !here->VSRCacMGiven) {
                here->VSRCacMag = 1;
            }
            if(here->VSRCacGiven && !here->VSRCacPGiven) {
                here->VSRCacPhase = 0;
            }
            if (!here->VSRCdcGiven && !here->VSRCfuncTGiven) {
                /* no DC value, no transient value */
                SPfrontEnd->IFerrorf(ERR_INFO,
                    "%s: has no value, DC 0 assumed",
                    here->VSRCname);
            }
            else if (here->VSRCdcGiven && here->VSRCfuncTGiven
                     && here->VSRCfunctionType != TRNOISE
                     && here->VSRCfunctionType != TRRANDOM
                     && here->VSRCfunctionType != EXTERNAL) {
                /* DC value and transient time 0 values given */
                double time0value;
                /* determine transient time 0 value */
                if (here->VSRCfunctionType == AM || here->VSRCfunctionType == PWL)
                    time0value = here->VSRCcoeffs[1];
                else
                    time0value = here->VSRCcoeffs[0];
                /* No warning issued if DC value and transient time 0 value are the same */
                if (!AlmostEqualUlps(time0value, here->VSRCdcValue, 3)) {
                    SPfrontEnd->IFerrorf(ERR_INFO,
                        "%s: dc value used for op instead of transient time=0 value.",
                        here->VSRCname);
                }
            }
            radians = here->VSRCacPhase * M_PI / 180.0;
            here->VSRCacReal = here->VSRCacMag * cos(radians);
            here->VSRCacImag = here->VSRCacMag * sin(radians);
#ifdef RFSPICE
            // To have a power port, we need to define its index value
            // AND a proper port impedance
            if (here->VSRCportNumGiven)
            {
                if (!here->VSRCportZ0Given)
                    here->VSRCportZ0 = 50.0;

                /* Enhancement-384: a port whose z0 is zero or negative used to be
                 * demoted to "not a port" right here, in silence. Nothing told
                 * the user, and `sp` simply ran with the ports that were left:
                 * a 2-port with `z0=0` on port 2 produced a plot containing only
                 * S_1_1 -- no S_1_2, S_2_1 or S_2_2 -- and an S_1_1 that was a
                 * different number from the correct one. A reference impedance
                 * of zero is not a modelling choice, it is a typo, and z0 is a
                 * divisor here (VSRCportY0 = 1/z0, VSRCki = 0.5/sqrt(z0)). */
                if (here->VSRCportNum > 0 && here->VSRCportZ0 <= 0.0) {
                    SPfrontEnd->IFerrorf(ERR_FATAL,
                        "%s: port %d has z0 = %g; the reference impedance must be "
                        "positive", here->VSRCname, here->VSRCportNum,
                        here->VSRCportZ0);
                    return(E_PARMVAL);
                }

                here->VSRCisPort = here->VSRCportZ0 > 0.0 && here->VSRCportNum > 0;
            }
            else
                here->VSRCisPort = FALSE;

            if (here->VSRCisPort)
            {
                /* Enhancement-385: decide the PORT waveform HERE, where whether
                 * this source is a port is actually known, instead of in
                 * VSRCparam's `pwr`/`freq` cases.
                 *
                 * E-384 stopped those cases clobbering an explicit SIN/PULSE/PWL
                 * (`if (!VSRCfuncTGiven)`), but that left the dc-only source
                 * unprotected: it has no waveform, so the guard passed and
                 * `sens` -- which perturbs `pwr` and `freq` on EVERY voltage
                 * source -- still turned it into a PORT and left it there. A
                 * following transient then read 0 where the answer was 1.0. The
                 * state-restoration audit caught that E-384 had only covered
                 * half the class.
                 *
                 * A source is a port only if portnum and a positive z0 say so,
                 * which is exactly the condition guarding this block. */
                if (!here->VSRCfuncTGiven)
                    here->VSRCfunctionType = PORT;

                if (!here->VSRCportFreqGiven)
                    here->VSRCportFreq = 1.0e9;
                if (!here->VSRCportPowerGiven)
                    here->VSRCportPower = 0.001; // 1mW (0dBm) default RF power
                if (!here->VSRCportPhaseGiven)
                    here->VSRCportPhase = 0.0;

                here->VSRC2pifreq = 2.0 * M_PI * here->VSRCportFreq;
                here->VSRCVAmplitude = sqrt(here->VSRCportPower * 4.0 * here->VSRCportZ0);
                here->VSRCportY0 = 1.0 / here->VSRCportZ0;
                here->VSRCportPhaseRad = here->VSRCportPhase * M_PI / 180.0;
                here->VSRCki = 0.5 / sqrt(here->VSRCportZ0);

                ckt->CKTportCount++;
                ckt->CKTrfPorts = (GENinstance**)TREALLOC(GENinstance*, ckt->CKTrfPorts, ckt->CKTportCount);
                ckt->CKTrfPorts[ckt->CKTportCount - 1] = (GENinstance*)here;

                // Reorder ports according to their PortNum
                unsigned int done = 0;
                while (!done)
                {
                    int nMax = ckt->CKTportCount - 1;
                    done = 1;
                    for (int n = 0; n < nMax; n++)
                    {
                        VSRCinstance* a = (VSRCinstance*)ckt->CKTrfPorts[n];
                        VSRCinstance* b = (VSRCinstance*)ckt->CKTrfPorts[n + 1];
                        if (a->VSRCportNum > b->VSRCportNum)
                        {
                            // Swap a and b. Restart
                            done = 0;
                            ckt->CKTrfPorts[n] = (GENinstance*)b;
                            ckt->CKTrfPorts[n + 1] = (GENinstance*)a;
                            break;
                        }
                    }
                }
            }
#endif
        }
    }

#ifdef RFSPICE
    portIDs = (int*)malloc((size_t)ckt->CKTportCount * sizeof(int));
    if (portIDs == NULL)
        return (E_NOMEM);

    int curport = 0;

    // Sweep thru all ports to check for correct indexing

    /*  loop through all the voltage source models */
    for (model = (VSRCmodel*)inModel; model != NULL; model = VSRCnextModel(model)) {
        /* loop through all the instances of the model */
        for (here = VSRCinstances(model); here != NULL;
            here = VSRCnextInstance(here)) {

            if (!here->VSRCisPort) continue;

            int curId = here->VSRCportNum;
            // If port Index > port Count then we have either a duplicate number or a missing number
            if (curId > ckt->CKTportCount)
            {
                SPfrontEnd->IFerrorf(ERR_FATAL,
                    "%s: incorrect port ordering",
                    here->VSRCname);
                free(portIDs);
                return (E_BADPARM);
            }


            // Check if we have already defined the "curId"
            for (prevPort = 0; prevPort < curport; prevPort++)
            {
                if (portIDs[prevPort] == curId)
                {
                    SPfrontEnd->IFerrorf(ERR_FATAL,
                        "%s: duplicate port Index",
                        here->VSRCname);
                    free(portIDs);
                    return (E_BADPARM);
                }
            }

            portIDs[curport++] = curId;
        }
    }

    free(portIDs);

#endif
    return(OK);
}
