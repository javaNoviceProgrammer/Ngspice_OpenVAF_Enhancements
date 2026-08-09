/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 2000  AlansFixes
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/ifsim.h"

/* Enhancement-188: warm-start for repeated DC operating-point solves (the
 * Monte Carlo idiom, where each sample re-sources the deck and cold-solves a
 * bias point that has moved only slightly). When enabled, DCop preloads the
 * previous converged solution into CKTrhsOld and lets CKTop try a direct
 * Newton from it (MODEINITFLOAT) before any gmin/source stepping. If the guess
 * is poor, CKTop's first NIiter simply fails and it falls through to the usual
 * cold homotopy, so the converged result is identical -- only the iteration
 * count drops (measured ~52 -> ~5 on a diode ladder). The buffer lives outside
 * the CKTcircuit (which `reset` recreates) and is indexed by equation number,
 * which is stable across resets of an identical-topology deck. */
static double *dcop_warm = NULL;   /* [size+1] last converged CKTrhsOld       */
static int     dcop_warm_n = 0;    /* size the buffer was allocated for        */
static int     dcop_warm_valid = 0;/* is dcop_warm a usable guess?             */
static int     dcop_warm_enable = 0;

/* Enable/disable warm starting and invalidate any stale guess. Called by the
 * `montecarlo -warm` loop around its sampling. */
void CKTsetWarmStart(int enable)
{
    dcop_warm_enable = enable;
    dcop_warm_valid = 0;
    if (!enable)
        tfree(dcop_warm);
}

#ifdef XSPICE
/* gtri - add - wbk - 12/19/90 - Add headers */
#include "ngspice/mif.h"
#include "ngspice/evt.h"
#include "ngspice/evtproto.h"
#include "ngspice/ipctiein.h"
/* gtri - end - wbk */
#endif

#ifdef OSDI
#include "ngspice/osdiitf.h"   /* Enhancement-53: OSDIfinalStep */
#endif

int
DCop(CKTcircuit *ckt, int notused)
{
#ifdef WANT_SENSE2
    int i, senmode, size;
    long save;
#endif

    int converged;
    int error;
    IFuid *nameList; /* va: tmalloc'ed list */
    int numNames;
    runDesc *plot = NULL;
    int wsize, usewarm, wi;   /* Enhancement-188: warm-start */

    NG_IGNORE(notused);
  
#ifdef XSPICE

    /* Tell the code models what mode we're in */
    g_mif_info.circuit.anal_type = MIF_DC;

    g_mif_info.circuit.anal_init = MIF_TRUE;

#endif

    error = CKTnames(ckt,&numNames,&nameList);
    if(error) return(error);
    error = SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                                       ckt->CKTcurJob->JOBname,
                                       NULL, IF_REAL,
                                       numNames, nameList, IF_REAL,
                                       &plot);
    tfree(nameList); /* va: nameList not used any longer, it was a memory leak */
    if(error) return(error);

    /* initialize CKTsoaCheck `warn' counters */
    if (ckt->CKTsoaCheck)
        error = CKTsoaInit();

    /* Enhancement-211: the DC warm-start (below) needs the matrix size on BOTH the
       analog and the event-driven (XSPICE EVTop) paths -- the warm-start snapshot
       reads `wsize` unconditionally. The old code assigned it only inside the
       analog-only else body, so it was read uninitialised whenever EVTop ran. Set
       it here, before the branch. */
    wsize = SMPmatSize(ckt->CKTmatrix);

#ifdef XSPICE
/* gtri - begin - wbk - 6/10/91 - Call EVTop if event-driven instances exist */
    if(ckt->evt->counts.num_insts != 0) {
        /* use new DCOP algorithm */
        converged = EVTop(ckt,
                    (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITJCT,
                    (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITFLOAT,
                    ckt->CKTdcMaxIter,
                    MIF_TRUE);
        EVTdump(ckt, IPC_ANAL_DCOP, 0.0);
	
        EVTop_save(ckt, MIF_TRUE, 0.0);
	/* gtri - end - wbk - 6/10/91 - Call EVTop if event-driven instances exist */
	} else {
        /* If no event-driven instances, do what SPICE normally does */
#endif
    /* Enhancement-188: preload the previous sample's solution and warm-start
     * (MODEINITFLOAT) if a valid guess of the right size is available.
     * Enhancement-211: this preload and the CKTop analog solve below MUST stay
     * inside the (non-event-driven) else -- a braceless else previously let CKTop
     * run even after EVTop, redundantly re-solving the analog part and overwriting
     * the event-driven DC result (and left `wsize` read uninitialised on the EVTop
     * path). The added braces below close the else after CKTop. */
    usewarm = (dcop_warm_enable && dcop_warm_valid && dcop_warm_n == wsize);
    if (usewarm) {
        for (wi = 1; wi <= wsize; wi++)
            ckt->CKTrhsOld[wi] = dcop_warm[wi];
    }

    converged = CKTop(ckt,
            (ckt->CKTmode & MODEUIC) | MODEDCOP | (usewarm ? MODEINITFLOAT : MODEINITJCT),
            (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITFLOAT,
            ckt->CKTdcMaxIter);
#ifdef XSPICE
    }
#endif

    if(converged != 0) {
        fprintf(stdout,"\nDC solution failed -\n");
        CKTncDump(ckt);
        return(converged);
    }

    /* Enhancement-188: snapshot this converged solution as the next warm start. */
    if (dcop_warm_enable) {
        if (dcop_warm_n != wsize) {
            tfree(dcop_warm);
            dcop_warm = TMALLOC(double, wsize + 1);
            dcop_warm_n = wsize;
        }
        for (wi = 1; wi <= wsize; wi++)
            dcop_warm[wi] = ckt->CKTrhsOld[wi];
        dcop_warm_valid = 1;
    }

    ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITSMSIG;

#ifdef WANT_SENSE2
    if(ckt->CKTsenInfo && ((ckt->CKTsenInfo->SENmode&DCSEN) || 
            (ckt->CKTsenInfo->SENmode&ACSEN)) ){
#ifdef SENSDEBUG
         printf("\nDC Operating Point Sensitivity Results\n\n");
         CKTsenPrint(ckt);
#endif /* SENSDEBUG */
         senmode = ckt->CKTsenInfo->SENmode;
         save = ckt->CKTmode;
         ckt->CKTsenInfo->SENmode = DCSEN;
         size = SMPmatSize(ckt->CKTmatrix);
         for(i = 1; i<=size ; i++){
             ckt->CKTrhsOp[i] = ckt->CKTrhsOld[i];
         }
         error = CKTsenDCtran(ckt);
         if (error)
             return(error);

         ckt->CKTmode = save;
         ckt->CKTsenInfo->SENmode = senmode;

    }
#endif

    converged = CKTload(ckt);

    if(converged == 0) {
        CKTdump(ckt, 0.0, plot);
        if (ckt->CKTsoaCheck)
            error = CKTsoaCheck(ckt);
#ifdef OSDI
        /* Enhancement-53: an operating point is both the first and the last
           point of its analysis -- fire `@(final_step)` blocks. */
        OSDIfinalStep(ckt);

        /* Enhancement-426: report a deferred $finish/$stop here too. Unlike
         * .ac and .noise the request is NOT acted on: an operating point is a
         * single point, there is no sweep left to truncate, and the solution
         * has already been computed and dumped -- discarding it would delete a
         * legitimate result. Saying nothing at all, which is what happened
         * before, left the user's explicit stop request invisible. */
        {
            int osdi_req = OSDIpendingRequests(ckt);
            if (osdi_req & (OSDI_REQ_FINISH | OSDI_REQ_STOP))
                fprintf(stdout, "\nNote: %s requested by a Verilog-A device during the operating point; the operating point is complete and is reported.\n",
                        (osdi_req & OSDI_REQ_FINISH) ? "$finish" : "$stop");
        }
#endif
    } else {
         fprintf(stderr,"error: circuit reload failed.\n");
    }

    SPfrontEnd->OUTendPlot (plot);
    return(converged);
}
