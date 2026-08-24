/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/trandefs.h"
#include "ngspice/cktdefs.h"

#include "analysis.h"

/* ARGSUSED */
int 
TRANsetParm(CKTcircuit *ckt, JOB *anal, int which, IFvalue *value)
{
    TRANan *job = (TRANan *) anal;

    NG_IGNORE(ckt);

    switch(which) {

    case TRAN_TSTOP:
        if (value->rValue <= 0.0) {
	        errMsg = copy("TSTOP is invalid, must be greater than zero.");
                job->TRANfinalTime = 1.0;
	        return(E_PARMVAL);
	    }
        job->TRANfinalTime = value->rValue;
        break;
    case TRAN_TSTEP:
          if (value->rValue <= 0.0) {
           errMsg = copy( "TSTEP is invalid, must be greater than zero." );
           job->TRANstep = 1.0;
	       return(E_PARMVAL);
	    }
        job->TRANstep = value->rValue;
        break;
    case TRAN_TSTART:
        if (value->rValue >= job->TRANfinalTime) {
	        errMsg = copy("TSTART is invalid, must be less than TSTOP.");
                job->TRANinitTime = 0.0;
	        return(E_PARMVAL);
	    }
        job->TRANinitTime = value->rValue;
        break;
    case TRAN_TMAX:
        /* Enhancement-475: TMAX was the one `tran` argument with no check at
         * all, and its failure mode pointed away from the mistake: a negative
         * TMAX reached the integrator and came back as
         * "singular matrix: check node b" -- blaming the user's circuit for
         * what is an invalid argument, on a divider that solves fine with any
         * other TMAX. TSTEP, TSTOP and TSTART all say so plainly; this now
         * does too. Zero stays legal, because zero is how TMAX is spelled
         * when you want the default. */
        if (value->rValue < 0.0) {
            errMsg = copy("TMAX is invalid, must not be negative "
                          "(use 0 for the default).");
            job->TRANmaxStep = 0.0;
            return(E_PARMVAL);
        }
        job->TRANmaxStep = value->rValue;
        break;
    case TRAN_UIC:
        if(value->iValue) {
            job->TRANmode |= MODEUIC;
        }
        break;

    default:
        return(E_BADPARM);
    }
    return(OK);
}


static IFparm TRANparms[] = {
    { "tstart",     TRAN_TSTART,    IF_SET|IF_REAL, "starting time" },
    { "tstop",      TRAN_TSTOP,     IF_SET|IF_REAL, "ending time" },
    { "tstep",      TRAN_TSTEP,     IF_SET|IF_REAL, "time step" },
    { "tmax",       TRAN_TMAX,      IF_SET|IF_REAL, "maximum time step" },
    { "uic",        TRAN_UIC,       IF_SET|IF_FLAG, "use initial conditions" },
};

SPICEanalysis TRANinfo  = {
    { 
        "TRAN",
        "Transient analysis",

        NUMELEMS(TRANparms),
        TRANparms
    },
    sizeof(TRANan),
    TIMEDOMAIN,
    1,
    TRANsetParm,
    TRANaskQuest,
    TRANinit,
    DCtran
};
