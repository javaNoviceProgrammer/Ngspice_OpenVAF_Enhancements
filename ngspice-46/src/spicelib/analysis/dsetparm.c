/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1988 Jaijeet S Roychowdhury
**********/

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/cktdefs.h"
#include "ngspice/distodef.h"

#include "analysis.h"

/* ARGSUSED */
int 
DsetParm(CKTcircuit *ckt, JOB *anal, int which, IFvalue *value)
{
    DISTOAN *job = (DISTOAN *) anal;

    NG_IGNORE(ckt);

    switch(which) {

    case D_START:
	if (value->rValue <= 0.0) {
	    errMsg = copy("Frequency of 0 is invalid");
            job->DstartF1 = 1.0;
	    return(E_PARMVAL);
	}

        job->DstartF1 = value->rValue;
        break;

    case D_STOP:
	if (value->rValue <= 0.0) {
	    errMsg = copy("Frequency of 0 is invalid");
            /* Enhancement-497: this reset DstartF1 -- the START frequency --
             * when it was the STOP frequency that was refused. The same
             * copy-paste sits in nsetparm.c's N_STOP. Nothing observable
             * followed, because E_PARMVAL aborts the analysis before either
             * field is read, but the line said the opposite of what it did. */
            job->DstopF1 = 1.0;
	    return(E_PARMVAL);
	}

        job->DstopF1 = value->rValue;
        break;

    case D_STEPS:
        job->DnumSteps = value->iValue;
        break;

    case D_DEC:
        job->DstepType = DECADE;
        break;

    case D_OCT:
        job->DstepType = OCTAVE;
        break;

    case D_LIN:
        job->DstepType = LINEAR;
        break;

    case D_F2OVRF1:
        /* Enhancement-497: the one argument that DEFINES the two-tone analysis
         * was the one nothing checked.
         *
         * The manual is explicit -- f2overf1 "should be a real number between
         * (and not equal to) 0.0 and 1.0" -- and both neighbouring cases in
         * this very switch test their value and return E_PARMVAL. This one
         * stored whatever arrived. Measured on a reactive circuit, a ratio of
         * 0, 1, 1.5, 2 or -0.5 is accepted in silence and MOVES THE ANSWER:
         * the 2F1-F2 product read 1.695, 1.630, 1.477 and 1.580 against
         * 1.711 for a legal 0.5. At ratio 1, F2 == F1, so the plot ngspice
         * still labels "IM: f1-f2" holds a product at DC; at a negative ratio
         * the second tone sits at a negative frequency. The numbers look
         * ordinary either way, which is what makes the silence expensive.
         *
         * Refused rather than clamped: there is no defensible value to clamp
         * to -- the ratio is the experiment the user is asking for, and any
         * substitute would answer a different question without saying so.
         *
         * NARROWER THAN THE MANUAL, AND DELIBERATELY SO. The first version of
         * this guard took the manual at its word and refused everything outside
         * (0,1). Enhancement-255's suite caught that: it measures the two-tone
         * IM3 at f1 = 1.0 GHz and f2 = 1.3 GHz -- a ratio of 1.3 -- and proves
         * the result machine-exact against an independent QPSS harmonic-balance
         * engine. F2 above F1 leaves all three products at distinct non-zero
         * frequencies and is perfectly well posed; keeping F2 below F1 is a
         * convention, not a requirement, and a working verified deck is better
         * evidence of that than the sentence in the manual.
         *
         * What is refused is only what has no meaning:
         *   ratio <= 0  -- the second tone would sit at DC or at a negative
         *                  frequency;
         *   ratio == 1  -- F2 == F1, so F1-F2 is DC and 2F1-F2 is F1: the three
         *                  plots are then not intermodulation products at all,
         *                  though they are still labelled as such. */
        if (value->rValue <= 0.0 || value->rValue == 1.0) {
            errMsg = copy("f2overf1 must be greater than 0, and not exactly 1");
            job->Df2ovrF1 = 0.9;
            return(E_PARMVAL);
        }

        job->Df2ovrF1 = value->rValue;
        job->Df2wanted = 1;
        break;

    default:
        return(E_BADPARM);
    }
    return(OK);
}


static IFparm Dparms[] = {
    { "start",      D_START,   IF_SET|IF_REAL, "starting frequency" },
    { "stop",       D_STOP,    IF_SET|IF_REAL, "ending frequency" },
    { "numsteps",   D_STEPS,   IF_SET|IF_INTEGER,  "number of frequencies" },
    { "dec",        D_DEC,     IF_SET|IF_FLAG, "step by decades" },
    { "oct",        D_OCT,     IF_SET|IF_FLAG, "step by octaves" },
    { "lin",        D_LIN,     IF_SET|IF_FLAG, "step linearly" },
    { "f2overf1",   D_F2OVRF1, IF_SET|IF_REAL, "ratio of F2 to F1" },
};

SPICEanalysis DISTOinfo  = {
    { 
        "DISTO",
        "Small signal distortion analysis",

        NUMELEMS(Dparms),
        Dparms
    },
    sizeof(DISTOAN),
    FREQUENCYDOMAIN,
    1,
    DsetParm,
    DaskQuest,
    NULL,
    DISTOan
};
