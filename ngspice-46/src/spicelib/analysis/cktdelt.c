/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/tskdefs.h"
#include "ngspice/jobdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/cktdefs.h"


/* ARGSUSED */
int
CKTdelTask(CKTcircuit *ckt, TSKtask *task)
{
    JOB *job;
    JOB *old=NULL;

    /* Enhancement-840 (robustness and correctness campaign 2026-10-10, F3):
     * the circuit keeps CKTcurJob on the last job it ran, and an interactive
     * analysis command deletes the previous command's task before it parses
     * its own card. A card refused there -- `sens v(nosuch)`, `ac dec 0 1 1`,
     * `tran 1u`, `tf v(nosuch) v1` -- never reaches CKTdoJob, so the pointer
     * was left on a freed job, and the next `reset` read its JOBtype in
     * DCtran_step_quit: a use-after-free, SIGSEGV under Guard Malloc and
     * silent without it. A task's jobs die with it: if the circuit points at
     * one, a stepped transient's open plot is closed first, as `reset` would,
     * and the pointer goes. */
    if (ckt && ckt->CKTcurJob)
        for (job = task->jobs; job; job = job->JOBnextJob)
            if (job == ckt->CKTcurJob) {
                (void) DCtran_step_quit(ckt);
                ckt->CKTcurJob = NULL;
                break;
            }

    for(job = task->jobs; job; job=job->JOBnextJob){
        if(old) FREE(old);
        old=job;
    }
    if(old)FREE(old);
    FREE(task);
    return(OK);
}
