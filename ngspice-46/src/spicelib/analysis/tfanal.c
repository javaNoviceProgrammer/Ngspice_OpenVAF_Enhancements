/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1988 Thomas L. Quarles
**********/

/* subroutine to do DC Transfer Function analysis     */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/sperror.h"
#include "ngspice/smpdefs.h"
#include "ngspice/inpdefs.h"
#include "ngspice/tfdefs.h"
#ifdef OSDI
#include "ngspice/osdiitf.h"
#endif


/* ARGSUSED */
int
TFanal(CKTcircuit *ckt, int restart) 
                    
                    /* forced restart flag */
{
    TFan *job = (TFan *) ckt->CKTcurJob;

    int size;
    int insrc = 0, outsrc = 0;
    double outputs[3];
    IFvalue outdata;    /* structure for output data vector, will point to 
                         * outputs vector above */
    IFvalue refval;     /* structure for 'reference' value (not used here) */
    int error;
    int converged;
    int i;
    runDesc *plotptr = NULL;   /* pointer to out plot */
    GENinstance *ptr = NULL;
    IFuid uids[3];
    char *name;
#define tfuid (uids[0]) /* unique id for the transfer function output */
#define inuid (uids[1]) /* unique id for the transfer function input imp. */
#define outuid (uids[2]) /* unique id for the transfer function out. imp. */

    NG_IGNORE(restart);

    /* first, find the operating point */
    converged = CKTop(ckt,
            (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITJCT,
            (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITFLOAT,
            ckt->CKTdcMaxIter);

    /* Enhancement-315: CKTop's return was ignored. When the operating point fails --
       e.g. a singular matrix from a dangling inductor (`l1 2 3 1` with 2,3 floating) --
       the matrix is never factored, and the SMPsolve() below asserts
       IS_FACTORED(Matrix) (spsolve.c:137, SIGABRT). Propagate the error instead of
       solving an unfactored matrix. A well-posed .tf returns 0 here and is unaffected. */
    if (converged)
        return converged;

    /* Enhancement-426: the SOURCE was checked (just below) and the OUTPUT NODE
     * was not -- and the consequence is worse than a wrong number. A node that
     * no device ever stamped still owns an equation number drawn from
     * CKTmaxEqNum, while CKTrhs/CKTrhsOld are sized from SMPmatSize(); indexing
     * the second with the first reads (and at :153-154 WRITES) off the end of
     * the heap block. Confirmed under ASAN as a heap-buffer-overflow at
     * tfanal.c:121 against the buffer allocated in nireinit.c:37; the shipped
     * binary printed the garbage it read as `transfer_function = 3.999110e+252`.
     *
     * The parser refuses such a name for a .control command (inp2dot.c), but a
     * DECK card may legitimately precede the devices that define its nodes, so
     * creation cannot be refused there -- which leaves this as the last line of
     * defence for a name no device ever defines. */
    if (job->TFoutIsV &&
        (job->TFoutPos->number > SMPmatSize(ckt->CKTmatrix) ||
         job->TFoutNeg->number > SMPmatSize(ckt->CKTmatrix))) {
        SPfrontEnd->IFerrorf(ERR_WARNING,
                             "Transfer function output node %s is not connected"
                             " to any device", job->TFoutName);
        return E_NOTFOUND;
    }

    /* Enhancement-429: ...and the same node named by a `.tf` CARD rather than a
     * .control command. The bounds test above only fires when the invented
     * node's equation number lands PAST the matrix, which happens on the
     * command path (the node is created after CKTsetup has sized everything).
     * A card is parsed BEFORE setup, so its phantom is inside the matrix, the
     * test never fired, and every unknown output node -- a plain typo, or a
     * device-internal node that no card can name -- was answered with a
     * confident `transfer_function = 0.000000e+00` and no diagnostic at all.
     *
     * Creating the node at parse time has to stay allowed: a `.tf` card may
     * legitimately precede the devices that define its nodes, which is
     * Enhancement-349's case and is pinned in examples/. So the question is not
     * "does this node exist" but "did anything other than this card ever refer
     * to it", which is what devRef records. */
    if (job->TFoutIsV
        && (CKTnodePhantom(job->TFoutPos) || CKTnodePhantom(job->TFoutNeg))) {
        SPfrontEnd->IFerrorf(ERR_WARNING,
                             "Transfer function output node %s does not exist "
                             "(no device connects to it)", job->TFoutName);
        return E_NOTFOUND;
    }

    ptr = CKTfndDev(ckt, job->TFinSrc);

    if (!ptr || ptr->GENmodPtr->GENmodType < 0) {
        SPfrontEnd->IFerrorf (ERR_WARNING,
                             "Transfer function source %s not in circuit",
                             job->TFinSrc);
        job->TFinIsV = 0;
        job->TFinIsI = 0;
        return E_NOTFOUND;
    }

    if (ptr->GENmodPtr->GENmodType == CKTtypelook("Vsource")) {
        job->TFinIsV = 1;
        job->TFinIsI = 0;
    } else if (ptr->GENmodPtr->GENmodType == CKTtypelook("Isource")) {
        job->TFinIsV = 0;
        job->TFinIsI = 1;
    } else {
        SPfrontEnd->IFerrorf (ERR_WARNING,
                             "Transfer function source %s not of proper type",
                             job->TFinSrc);
        return E_NOTFOUND;
    }

    size = SMPmatSize(ckt->CKTmatrix);
    for(i=0;i<=size;i++) {
        ckt->CKTrhs[i] = 0;
    }

    if (job->TFinIsI) {
        ckt->CKTrhs[GENnode(ptr)[0]] -= 1;
        ckt->CKTrhs[GENnode(ptr)[1]] += 1;
    } else {
        insrc = CKTfndBranch(ckt, job->TFinSrc);
        ckt->CKTrhs[insrc] += 1;
    }


    SMPsolve(ckt->CKTmatrix,ckt->CKTrhs,ckt->CKTrhsSpare);
    ckt->CKTrhs[0]=0;

    /* make a UID for the transfer function output */
    SPfrontEnd->IFnewUid (ckt, &tfuid, NULL, "Transfer_function", UID_OTHER, NULL);

    /* make a UID for the input impedance */
    SPfrontEnd->IFnewUid (ckt, &inuid, job->TFinSrc, "Input_impedance", UID_OTHER, NULL);

    /* make a UID for the output impedance */
    if (job->TFoutIsI) {
        SPfrontEnd->IFnewUid (ckt, &outuid, job->TFoutSrc ,"Output_impedance", UID_OTHER, NULL);
    } else {
        name = tprintf("output_impedance_at_%s", job->TFoutName);
        SPfrontEnd->IFnewUid (ckt, &outuid, NULL, name, UID_OTHER, NULL);
    }

    error = SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                                       job->JOBname,
                                       NULL, 0,
                                       3, uids, IF_REAL,
                                       &plotptr);
    if(error) return(error);

    /*find transfer function */
    if (job->TFoutIsV) {
        outputs[0] = ckt->CKTrhs[job->TFoutPos->number] -
            ckt->CKTrhs[job->TFoutNeg->number];
    } else {
        outsrc = CKTfndBranch(ckt, job->TFoutSrc);
        outputs[0] = ckt->CKTrhs[outsrc];
    }

    /* now for input resistance */
    if (job->TFinIsI) {
        outputs[1] = ckt->CKTrhs[GENnode(ptr)[1]] -
            ckt->CKTrhs[GENnode(ptr)[0]];
    } else {
        if(fabs(ckt->CKTrhs[insrc])<1e-20) {
            outputs[1]=1e20;
        } else {
            outputs[1] = -1/ckt->CKTrhs[insrc];
        }
    }

    if (job->TFoutIsI &&
            (job->TFoutSrc ==
            job->TFinSrc)) {
        outputs[2]=outputs[1];
        goto done;
        /* no need to compute output resistance when it is the same as 
           the input  */
    }
    /* now for output resistance */
    for(i=0;i<=size;i++) {
        ckt->CKTrhs[i] = 0;
    }
    if (job->TFoutIsV) {
        ckt->CKTrhs[job->TFoutPos->number] -= 1;
        ckt->CKTrhs[job->TFoutNeg->number] += 1;
    } else {
        ckt->CKTrhs[outsrc] += 1;
    }
    SMPsolve(ckt->CKTmatrix,ckt->CKTrhs,ckt->CKTrhsSpare);
    ckt->CKTrhs[0]=0;
    if (job->TFoutIsV) {
        outputs[2] = ckt->CKTrhs[job->TFoutNeg->number] -
            ckt->CKTrhs[job->TFoutPos->number];
    } else {
        /* Enhancement-179: the branch current drawn by the unit forcing is
         * NEGATIVE for a passive network (same convention as the input-
         * impedance solve above, which divides by -rhs), so clamping with
         * MAX(1e-20, rhs) pinned the output impedance of every current-
         * output .tf to 1e20 -- a bug inherited from Berkeley SPICE3. */
        if (fabs(ckt->CKTrhs[outsrc]) < 1e-20)
            outputs[2] = 1e20;
        else
            outputs[2] = -1/ckt->CKTrhs[outsrc];
    }
done:
    outdata.v.numValue=3;
    outdata.v.vec.rVec=outputs;
    refval.rValue = 0;
    SPfrontEnd->OUTpData (plotptr, &refval, &outdata);
    SPfrontEnd->OUTendPlot (plotptr);
#ifdef OSDI
    /* Enhancement-434: `.tf` computes an operating point and reports a result,
     * so it owes the user the same notice the operating point itself gives.
     * Enhancement-426 added that notice to dcop.c, and dctrcurv/acan/noisean/
     * dctran each have their own; tfanal was the analysis that produces a
     * result and says nothing, so a model's explicit stop request vanished.
     *
     * As in dcop.c the request is reported but NOT acted on: the transfer
     * function is a single computed point, there is no sweep left to truncate,
     * and discarding it would delete a legitimate result. */
    {
        int osdi_req = OSDIpendingRequests(ckt);
        if (osdi_req & (OSDI_REQ_FINISH | OSDI_REQ_STOP))
            fprintf(stdout, "\nNote: %s requested by a Verilog-A device during the transfer-function operating point; the result is complete and is reported.\n",
                    (osdi_req & OSDI_REQ_FINISH) ? "$finish" : "$stop");
    }
#endif
    return(OK);
}


