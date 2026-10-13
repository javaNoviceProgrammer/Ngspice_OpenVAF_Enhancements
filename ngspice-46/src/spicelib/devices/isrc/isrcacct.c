/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "isrcdefs.h"
#include "ngspice/trandefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"
#include "ngspice/missing_math.h"
#include "ngspice/1-f-code.h"
#include "ngspice/compatmode.h"

#ifndef HAVE_LIBFFTW3
extern void fftFree(void);
#endif

extern bool ft_ngdebug; /* some additional debug info printed */

int
ISRCaccept(CKTcircuit *ckt, GENmodel *inModel)
        /* set up the breakpoint table.  */
{
    ISRCmodel *model = (ISRCmodel *) inModel;
    ISRCinstance *here;
    int error;

    /*  loop through all the voltage source models */
    for( ; model != NULL; model = ISRCnextModel(model)) {

        /* loop through all the instances of the model */
        for (here = ISRCinstances(model); here != NULL ;
                here=ISRCnextInstance(here)) {

            if(!(ckt->CKTmode & (MODETRAN | MODETRANOP))) {
                /* not transient, so shouldn't be here */
                return(OK);
            } else {
                /* use the transient functions */
                switch(here->ISRCfunctionType) {

                    default: { /* no function specified:DC   no breakpoints */
                        break;
                    }

                    case PULSE: {
                        /* Enhancement-877: the next corner is scheduled from the
                         * time within the period, as VSRCaccept does. The chain
                         * this replaces set the next corner only when an
                         * accepted point landed on the current one, to 1e-7 PW;
                         * a rise shorter than minbreak cannot be landed on, the
                         * chain stopped, and every later edge was stepped over:
                         * 0.1 ps edges into an RC were 3.0e-2 off where the same
                         * pulse from a voltage source was 2.8e-4. The defaults
                         * are ISRCload's (Enhancement-446), so the corners are
                         * those of the waveform it loads. */
                        double TD, TR, TF, PW, PER;
                        double time, basetime;
                        double PHASE, phase, deltat;
                        double tmax = 1e99;
                        double wait, atime;

                        TD = here->ISRCfunctionOrder > 2
                            ? here->ISRCcoeffs[2] : 0.0;
                        TR = here->ISRCfunctionOrder > 3
                            && here->ISRCcoeffs[3] > 0.0
                            ? here->ISRCcoeffs[3] : ckt->CKTstep;
                        TF = here->ISRCfunctionOrder > 4
                            && here->ISRCcoeffs[4] > 0.0
                            ? here->ISRCcoeffs[4] : ckt->CKTstep;
                        PW = here->ISRCfunctionOrder > 5
                            && here->ISRCcoeffs[5] >= 0.0
                            ? here->ISRCcoeffs[5] : ckt->CKTfinalTime;
                        PER = here->ISRCfunctionOrder > 6
                            && here->ISRCcoeffs[6] > 0.0
                            ? here->ISRCcoeffs[6] : ckt->CKTfinalTime;
                        PHASE = here->ISRCfunctionOrder > 7
                            ? here->ISRCcoeffs[7] : 0.0;

                        /* offset time by delay */
                        time = ckt->CKTtime - TD;

                        if (newcompat.xs) {
                            /* normalize phase to cycles */
                            phase = PHASE / 360.0;
                            phase = fmod(phase, 1.0);
                            deltat = phase * PER;
                            while (deltat > 0)
                                deltat -= PER;
                            time += deltat;
                        } else if (PHASE > 0.0) {
                            /* the 8th parameter is the number of pulses */
                            tmax = PHASE * PER;
                            if (time > tmax)
                                break;
                        }

                        if (ckt->CKTtime < here->ISRCbreak_time)
                            break;

                        if (time >= PER) {
                            /* repeating signal: where in the period are we? */
                            basetime = PER * floor(time / PER);
                            time -= basetime;
                        }
                        /* Enhancement-875: a point on a period's first corner
                         * must not read as the end of the period before */
                        if (PER - time <= ckt->CKTminBreak)
                            time -= PER;

                        /* a corner closer than minbreak would be ignored; take
                         * the one after it */
                        atime = time + ckt->CKTminBreak;

                        if (atime < 0.0)
                            wait = -time;                   /* the first pulse */
                        else if (atime < TR)
                            wait = TR - time;               /* the end of the rise */
                        else if (atime < TR + PW)
                            wait = TR + PW - time;          /* the fall */
                        else if (atime < TR + PW + TF)
                            wait = TR + PW + TF - time;     /* the end of the fall */
                        else
                            wait = PER - time;              /* the next pulse */

                        here->ISRCbreak_time = ckt->CKTtime + wait;
                        error = CKTsetBreak(ckt, here->ISRCbreak_time);
                        if (error)
                            return error;
                        /* a step that ends just short of the corner must still
                         * ask for the one after it */
                        here->ISRCbreak_time -= ckt->CKTminBreak;
                    }
                    break;

                    case SINE: {
                        /* no  breakpoints (yet) */
                    }
                    break;

                    case EXP: {
                        /* no  breakpoints (yet) */
                    }
                    break;

                    case SFFM:{
                        /* no  breakpoints (yet) */
                    }
                    break;

                    case AM:{
                        /* no  breakpoints (yet) */
                    }
                    break;

                    case PWL: {
                        int i;
                        if(ckt->CKTtime < *(here->ISRCcoeffs)) {
                            if(ckt->CKTbreak) {
                                error = CKTsetBreak(ckt,*(here->ISRCcoeffs));
                                break;
                            }
                        }
                        for(i=0;i<(here->ISRCfunctionOrder/2)-1;i++) {
                            if ( ckt->CKTbreak && AlmostEqualUlps(*(here->ISRCcoeffs+2*i), ckt->CKTtime, 3 ) ) {
                                error = CKTsetBreak(ckt, *(here->ISRCcoeffs+2*i+2));
                                if(error) return(error);
                                goto bkptset;
                            }
                        }
                        break;
                    }

    /**** tansient noise routines:
    INoi2 2 0  DC 0 TRNOISE(10n 0.5n 0 0n) : generate gaussian distributed noise
                            rms value, time step, 0 0
    INoi1 1 0  DC 0 TRNOISE(0n 0.5n 1 10n) : generate 1/f noise
                            0,  time step, exponent < 2, rms value
    */
                    case TRNOISE: {

                        struct trnoise_state *state = here -> ISRCtrnoise_state;
                        double TS = state -> TS;
                        double RTSAM = state ->RTSAM;

                        if ((TS == 0.0) &&  (RTSAM == 0.0)) // no further breakpoint if value not given
                            break;

#ifndef HAVE_LIBFFTW3
                        /* FIXME, dont' want this here, over to aof_get or somesuch */
                        if (ckt->CKTtime == 0.0) {
                            if (ft_ngdebug)
                                printf("ISRC: free fft tables\n");
                            fftFree();
                        }
#endif

                        if(ckt->CKTbreak) {

                            int n = (int) floor(ckt->CKTtime / TS + 0.5);
                            volatile double nearest = n * TS;

                            if(AlmostEqualUlps(nearest, ckt->CKTtime, 3)) {
                                /* carefull calculate `next'
                                *  make sure it is really identical
                                *  with the next calculated `nearest' value
                                */
                                volatile double next = (n+1) * TS;
                                error = CKTsetBreak(ckt, next);
                                if(error)
                                    return(error);
                            }
                        }

                        if (RTSAM > 0) {
                            double RTScapTime = state->RTScapTime;
                            double RTSemTime = state->RTSemTime;
                            double RTSCAPT = state->RTSCAPT;
                            double RTSEMT = state->RTSEMT;

                            if (ckt->CKTtime == 0) {
                                /* initialzing here again needed for repeated calls to tran command */
                                state->RTScapTime = RTScapTime = exprand(RTSCAPT);
                                state->RTSemTime = RTSemTime = RTScapTime + exprand(RTSEMT);
                                if (ckt->CKTbreak) {
                                    error = CKTsetBreak(ckt, RTScapTime);
                                    if(error)
                                        return(error);
                                }
                            }

                            if(AlmostEqualUlps(RTScapTime, ckt->CKTtime, 3)) {
                                if (ckt->CKTbreak) {
                                    error = CKTsetBreak(ckt, RTSemTime);
                                    if(error)
                                        return(error);
                                }
                            }

                            if(AlmostEqualUlps(RTSemTime, ckt->CKTtime, 3)) {
                                /* new values */
                                RTScapTime = here -> ISRCtrnoise_state ->RTScapTime = ckt->CKTtime + exprand(RTSCAPT);
                                here -> ISRCtrnoise_state ->RTSemTime = RTScapTime + exprand(RTSEMT);

                                if (ckt->CKTbreak) {
                                    error = CKTsetBreak(ckt, RTScapTime);
                                    if(error)
                                        return(error);
                                }
                            }
                        }
                    }
                    break;

                    case TRRANDOM: {
                        struct trrandom_state *state = here -> ISRCtrrandom_state;
                        double TS = state -> TS;
                        double TD = state -> TD;

                        double time = ckt->CKTtime - TD;

                        if (time < 0) break;

                        if(ckt->CKTbreak) {

                            int n = (int) floor(time / TS + 0.5);
                            volatile double nearest = n * TS;

                            if(AlmostEqualUlps(nearest, time, 3)) {
                            /* carefully calculate `next'
                            *  make sure it is really identical
                            *  with the next calculated `nearest' value
                            */
                                volatile double next = (n+1) * TS + TD;
                                error = CKTsetBreak(ckt, next);
                                if(error)
                                    return(error);
                                state->value = trrandom_state_get(state);
                            }
                        }
                    }
                    break;

                    case PRBS: {
                        /* Enhancement-752: the bit stream's next corner, as
                           the voltage source schedules it; the current source
                           has no per-instance break time, so the state holds
                           it (re-armed per run by ISRCtemp). */
                        struct prbs_state *ps = here->ISRCprbs_state;
                        if (ckt->CKTtime >= ps->break_time) {
                            double next = prbs_next_edge(ps,
                                    ckt->CKTtime + ckt->CKTminBreak,
                                    ckt->CKTstep);
                            if (next < ckt->CKTfinalTime) {
                                error = CKTsetBreak(ckt, next);
                                if (error)
                                    return error;
                            }
                            ps->break_time = next - ckt->CKTminBreak;
                        }
                    }
                    break;

#ifdef SHARED_MODULE
                    case EXTERNAL: {
                        /* no  breakpoints (yet) */
                    }
                    break;
#endif

                } // switch
            } // if ... else
bkptset: ;
        } // for
    } // for

    return(OK);
}
