/**********
Author: 2010-05 Stefano Perticaroli ``spertica''
Review: 2012-10 Francesco Lannutti
**********/

#ifndef ngspice_PSSDEFS_H
#define ngspice_PSSDEFS_H

#include "ngspice/jobdefs.h"
#include "ngspice/tskdefs.h"
    /*
     * PSSdefs.h - defs for pss analyses
     */

typedef struct {
    int JOBtype;
    JOB *JOBnextJob;
    char *JOBname;
    double PSSguessedFreq;
    CKTnode *PSSoscNode;
    double PSSstabTime;
    long PSSmode;
    long int PSSpoints;
    int PSSharms;
    runDesc *PSSplot_td;
    runDesc *PSSplot_fd;
    int sc_iter;
    double steady_coeff;

    /* Enhancement-119: the converged periodic operating point, retained past the
     * analysis as the substrate the periodic small-signal analyses (PAC / pnoise
     * / PXF) linearize around. PSS already samples the node voltages over one
     * period for its DFT but frees them; here they -- and the device states,
     * which the reactive Jacobian C(t) needs -- are kept on the job. Row-major
     * per sample: [unknown + sample*PSSopMsize] and [state + sample*PSSopNumStates]. */
    long   PSSopPoints;      /* number of time samples over one period */
    int    PSSopMsize;       /* matrix size (nodes + branch currents) */
    int    PSSopNumStates;   /* CKTnumStates captured per sample */
    double PSSopFreq;        /* converged fundamental frequency (Hz) */
    double *PSSopTimes;      /* [PSSopPoints] sample times across the period */
    double *PSSopVoltages;   /* [PSSopMsize * PSSopPoints] node voltages per sample */
    double *PSSopStates;     /* [PSSopNumStates * PSSopPoints] device states per sample */
} PSSan;

enum {
    GUESSED_FREQ = 1,
    STAB_TIME,
    OSC_NODE,
    PSS_POINTS,
    PSS_HARMS,
    PSS_UIC,
    SC_ITER,
    STEADY_COEFF,
};

#endif
