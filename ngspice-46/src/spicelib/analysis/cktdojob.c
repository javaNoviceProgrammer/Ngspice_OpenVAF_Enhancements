/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 2000 AlansFixes
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/trandefs.h"
#include "ngspice/cpextern.h"
#include "ngspice/fteext.h"

#include "analysis.h"
#include "ngspice/osdiitf.h"   /* Enhancement-471 */

#ifdef XSPICE
/* gtri - add - wbk - 11/26/90 - add include for MIF and EVT global data */
#include "ngspice/mif.h"
#include "ngspice/evtproto.h"
/* gtri - end - wbk - 11/26/90 */
/* gtri - add - 12/12/90 - wbk - include ipc stuff */
#include "ngspice/ipctiein.h"
/* gtri - end - 12/12/90 */
#endif

extern SPICEanalysis* analInfo[];

/* Enhancement-471 -------------------------------------------------------------
 *
 * A repeated analysis (`sweep`, `optimize`, `montecarlo`) tears the whole
 * circuit down and builds it again for every point, even though only a
 * parameter VALUE changed. `.dc` -- including the parameter sweeps of
 * Enhancement-427 -- has never done that: it sets the circuit up once and walks
 * its points inside the analysis. This lets the repeated analyses do the same.
 *
 * The reason it cannot simply be done is NODE COLLAPSE. A device may decide, at
 * setup and from its parameters, to merge two of its nodes; the matrix is then
 * built for that topology. Reuse the setup and the topology is frozen at
 * whatever the first point decided, and the sweep quietly draws a flat line.
 *
 * Two things make it safe here:
 *
 *   - For an OSDI device the collapse is RE-DECIDED on every CKTtemp and
 *     compared against the snapshot the matrix was built from
 *     (Enhancement-417). Until now a mismatch could only be reported --
 *     "the matrix was built for the collapse decided at setup and cannot be
 *     rebuilt here". CKTdoJob now does exactly what that message said was
 *     impossible: it notices and rebuilds for real.
 *
 *   - A built-in device decides its collapse in DEVsetup and nowhere else, so
 *     there is nothing to re-check. Rather than guess, reuse is offered only to
 *     circuits built entirely from device types whose topology is known to be
 *     fixed: the linear elements and sources below, which create their branch
 *     equations unconditionally, plus OSDI. Anything else keeps the old
 *     behaviour exactly. The list grows as a type is verified, never by
 *     assumption.
 */
static const char * const e471_fixed_topology[] = {
    "Resistor", "Capacitor", "Inductor", "mutual",
    "Vsource", "Isource", "VCVS", "VCCS", "CCCS", "CCVS", "ASRC",
    NULL
};

/* Enhancement-503: the hazard is per-PARAMETER, but the gate above is per-TYPE.
 *
 * A built-in semiconductor decides its node collapse in DEVsetup, from a small,
 * knowable set of parameters -- and from nothing else. A BJT creates its
 * internal collector, base and emitter nodes only from `rc`, `rb`, `re` and
 * `rco` (bjtsetup.c:430-490 -- `rco` gates a FOURTH node through its *Given*
 * flag, which is easy to miss); a diode its `internal`, `internal_sw` and `qp`
 * nodes from `rs`, `rsw`, `vp` and `tt` (diosetup.c:385-432); a JFET from `rd`
 * and `rs`; the MOS1/2/3/6/9 family from `rd`, `rs`, `rsh` and the per-instance
 * squares `nrd`, `nrs`.
 *
 * Each entry was read off the device's own setup routine by auditing every
 * CKTmkVolt call and the condition guarding it -- not from the parameter
 * documentation, which does not say which parameters build nodes.
 *
 * So a deck containing these types has a FIXED topology across a sweep unless
 * the sweep varies one of those parameters. Excluding the whole type costs a
 * measured 3.5x at 300 sections and 10.1x at 1200 -- on exactly the decks people
 * sweep -- for a risk that is usually not present. The type list is still the
 * authority: a type absent from BOTH tables is still refused, and this table
 * grows only when a type's setup has actually been read, which is the rule
 * Enhancement-471 set for the list above.
 *
 * Verified against each device's own setup routine, 2026-08-28. */
static const struct {
    const char *type;
    const char *params[8];
} e503_topology_params[] = {
    { "BJT",    { "rc", "rb", "re", "rco", NULL } },
    { "Diode",  { "rs", "rsw", "vp", "tt", NULL } },
    { "JFET",   { "rd", "rs", NULL } },
    { "Mos1",   { "rd", "rs", "rsh", "nrd", "nrs", NULL } },
    { "Mos2",   { "rd", "rs", "rsh", "nrd", "nrs", NULL } },
    { "Mos3",   { "rd", "rs", "rsh", "nrd", "nrs", NULL } },
    { "Mos6",   { "rd", "rs", "rsh", "nrd", "nrs", NULL } },
    { "Mos9",   { "rd", "rs", "rsh", "nrd", "nrs", NULL } },
    { NULL,     { NULL } }
};


/* The declaration lives HERE, not on CKTcircuit, and that is deliberate.
 *
 * The first version of this change stored it as a `char[256]` inside
 * CKTcircuit, which grew the struct and shifted every field after it. That
 * alone -- 256 bytes of padding, with none of this logic -- made the
 * `argguard` suite's warn_physics count vary run to run, so SOMETHING ELSE in
 * ngspice is sensitive to the layout of that struct in a way it should not be.
 * That is a real latent defect and it is recorded as one; it is not this
 * enhancement's to fix, and this enhancement must not be the thing that makes
 * it reachable. Keeping the declaration out of the struct leaves the layout
 * byte-for-byte as it was.
 *
 * One current circuit runs at a time on this path, and every reuse request
 * rewrites the declaration (sw_request_reuse() clears it), so a single static
 * cannot go stale or leak across commands. */
static char e503_swept_params[256];


void CKTdeclareSweptParams(const char *decl)
{
    if (decl && *decl)
        (void) snprintf(e503_swept_params, sizeof e503_swept_params, "%s", decl);
    else
        e503_swept_params[0] = '\0';
}


/* Is `param` one of the names the sweep declared it is varying? The declaration
 * is space-bracketed (" rc rb ") so this matches whole tokens: a sweep of `rsh`
 * must not be read as a sweep of `rs`. */
static int
e503_param_swept(const char *param)
{
    char needle[64];

    if (!e503_swept_params[0] || !param)
        return 1;                            /* nothing declared: assume the worst */
    if (snprintf(needle, sizeof needle, " %s ", param) >= (int) sizeof needle)
        return 1;
    return strstr(e503_swept_params, needle) != NULL;
}


/* Does this type collapse nodes from a parameter the sweep is varying? */
static int
e503_topology_at_risk(const char *type)
{
    int t, k;

    for (t = 0; e503_topology_params[t].type; t++) {
        if (strcmp(type, e503_topology_params[t].type))
            continue;
        for (k = 0; e503_topology_params[t].params[k]; k++)
            if (e503_param_swept(e503_topology_params[t].params[k]))
                return 1;                    /* the collapse could move */
        return 0;                            /* known type, none of them swept */
    }
    return 1;                                /* type not verified: refuse */
}

static int
e471_reuse_safe(CKTcircuit *ckt)
{
    int i, k;

    for (i = 0; i < DEVmaxnum; i++) {
        if (!DEVices[i] || !ckt->CKThead[i])
            continue;                        /* type not present in this deck */
        if (DEVices[i]->DEVpublic.registry_entry)
            continue;                        /* OSDI: collapse is re-checked */
        if (!DEVices[i]->DEVpublic.name)
            return 0;
        for (k = 0; e471_fixed_topology[k]; k++)
            if (!strcmp(DEVices[i]->DEVpublic.name, e471_fixed_topology[k]))
                break;
        if (e471_fixed_topology[k])
            continue;                        /* topology fixed unconditionally */
        /* Enhancement-503: not unconditionally fixed -- but fixed for THIS
         * sweep if none of the parameters its setup branches on is varying. */
        if (e503_topology_at_risk(DEVices[i]->DEVpublic.name))
            return 0;                        /* unverified type, or one at risk */
    }
    return 1;
}


int
CKTdoJob(CKTcircuit* ckt, int reset, TSKtask* task)
{
    JOB* job;
    double	startTime;
    int		error, i, error2;

    int         ANALmaxnum = spice_num_analysis();

#ifdef WANT_SENSE2
    int		senflag;
    static int	sens_num = -1;

    /* Sensitivity is special */
    if (sens_num < 0) {
        for (i = 0; i < ANALmaxnum; i++)
            if (!strcmp("SENS2", analInfo[i]->if_analysis.name))
                break;
        sens_num = i;
    }
#endif

    startTime = SPfrontEnd->IFseconds();

    ckt->CKTtemp = task->TSKtemp;
    ckt->CKTnomTemp = task->TSKnomTemp;
    ckt->CKTmaxOrder = task->TSKmaxOrder;
    ckt->CKTintegrateMethod = task->TSKintegrateMethod;
    ckt->CKTindverbosity = task->TSKindverbosity;
    ckt->CKTxmu = task->TSKxmu;
    ckt->CKTtrGamma = task->TSKtrGamma;   /* Enhancement-419 */
    ckt->CKTtrStage = 0;
    NIsdirkInfo(&ckt->CKTsdirkStages, &ckt->CKTsdirkGamma);
    ckt->CKTsdirkStage = 0;
    /* Enhancement-419: the SDIRK tableau is order 3, so CKTterr walks divided
     * differences down to CKTstates[4] and the step needs one slot per stage
     * plus the value at t. Both are bounded by CKTmaxOrder, whose default is 2
     * -- leaving it there would have CKTterr read a slot the rotation never
     * refreshes, i.e. a stale LTE built from another timepoint entirely. */
    if (ckt->CKTintegrateMethod == SDIRK && ckt->CKTmaxOrder < 3)
        ckt->CKTmaxOrder = 3;
    ckt->CKTbypass = task->TSKbypass;
    ckt->CKTdcMaxIter = task->TSKdcMaxIter;
    ckt->CKTdcTrcvMaxIter = task->TSKdcTrcvMaxIter;
    ckt->CKTtranMaxIter = task->TSKtranMaxIter;
    ckt->CKTnumSrcSteps = task->TSKnumSrcSteps;
    ckt->CKTnumGminSteps = task->TSKnumGminSteps;
    ckt->CKTgminFactor = task->TSKgminFactor;
    ckt->CKTminBreak = task->TSKminBreak;
    ckt->CKTabstol = task->TSKabstol;
    ckt->CKTpivotAbsTol = task->TSKpivotAbsTol;
    ckt->CKTpivotRelTol = task->TSKpivotRelTol;
    ckt->CKTreltol = task->TSKreltol;
    ckt->CKTchgtol = task->TSKchgtol;
    ckt->CKTvoltTol = task->TSKvoltTol;
    ckt->CKTgmin = task->TSKgmin;
    ckt->CKTgshunt = task->TSKgshunt;
    ckt->CKTcshunt = task->TSKcshunt;
    ckt->CKTdelmin = task->TSKdelmin;
    ckt->CKTtrtol = task->TSKtrtol;
#ifdef XSPICE
    /* Lower value of trtol to give smaller stepsize and more accuracy,
       but only if there are 'A' devices in the circuit,
       may be overridden by 'set xtrtol=newval' */
    if (ckt->CKTadevFlag && (ckt->CKTtrtol > 1)) {
        int newtol;
        if (cp_getvar("xtrtol", CP_NUM, &newtol, 0)) {
            printf("Override trtol to %d for xspice 'A' devices\n", newtol);
            ckt->CKTtrtol = newtol;
        }
        else {
            printf("Reducing trtol to 1 for xspice 'A' devices\n");
            ckt->CKTtrtol = 1;
        }
    }
#endif
    ckt->CKTdefaultMosM = task->TSKdefaultMosM;
    ckt->CKTdefaultMosL = task->TSKdefaultMosL;
    ckt->CKTdefaultMosW = task->TSKdefaultMosW;
    ckt->CKTdefaultMosAD = task->TSKdefaultMosAD;
    ckt->CKTdefaultMosAS = task->TSKdefaultMosAS;
    ckt->CKTfixLimit = task->TSKfixLimit;
    ckt->CKTnoOpIter = task->TSKnoOpIter;
    ckt->CKTtryToCompact = task->TSKtryToCompact;
    ckt->CKTbadMos3 = task->TSKbadMos3;
    ckt->CKTkeepOpInfo = task->TSKkeepOpInfo;
    ckt->CKTcopyNodesets = task->TSKcopyNodesets;
    ckt->CKTnodeDamping = task->TSKnodeDamping;
    ckt->CKTlinesearch = task->TSKlinesearch; /* Enhancement-111 */
    ckt->CKTtrustregion = task->TSKtrustregion; /* Enhancement-153 */
    ckt->CKTptcont = task->TSKptcont; /* Enhancement-127 */
    ckt->CKTconvhelp = task->TSKconvhelp; /* Enhancement-204 */
    ckt->CKTdynorder = task->TSKdynorder; /* Enhancement-128 */
    ckt->CKTordFix = task->TSKordFix; /* Enhancement-181 */
    ckt->CKTabsDv = task->TSKabsDv;
    ckt->CKTrelDv = task->TSKrelDv;
    ckt->CKTtroubleNode = 0;
    ckt->CKTtroubleElt = NULL;
    ckt->CKTnoopac = task->TSKnoopac && ckt->CKTisLinear;
    ckt->CKTepsmin = task->TSKepsmin;

#ifdef KLU
    ckt->CKTkluMODE = task->TSKkluMODE;
    ckt->CKTpzEig = task->TSKpzEig;
    ckt->CKTkluMemGrowFactor = task->TSKkluMemGrowFactor ;
    ckt->CKTkluOrdering = task->TSKkluOrdering ;
    ckt->CKTkluScale = task->TSKkluScale ;
    ckt->CKTkluBTF = task->TSKkluBTF ;
#endif

    ckt->CKTlteReltol = task->TSKlteReltol;
    ckt->CKTlteAbstol = task->TSKlteAbstol;
    ckt->CKTlteTrtol = task->TSKlteTrtol;
    ckt->CKTnewtrunc = task->TSKnewtrunc;

    if (!ft_optimizing)    /* Enhancement-130: quiet during optimizer iterations */
        fprintf(stdout, "Doing analysis at TEMP = %f and TNOM = %f\n\n",
            ckt->CKTtemp - CONSTCtoK, ckt->CKTnomTemp - CONSTCtoK);

    if (ckt->CKTnewtrunc)
        fprintf(stdout, "Note: Voltage based truncation error correction selected\n");

    /* call altermod and alter on device and model parameters assembled in
       devtlist and modtlist (if using temper) because we have a new temperature */
    inp_evaluate_temper(ft_curckt);

    error = 0;

    if (!reset)
        ckt->CKTreuseSetup = 0;   /* Enhancement-471: never outlives its job */

    if (reset) {

        ckt->CKTdelta = 0.0;
        ckt->CKTtime = 0.0;
        ckt->CKTcurrentAnalysis = 0;

#ifdef WANT_SENSE2
        senflag = 0;
        if (sens_num < ANALmaxnum)
            for (job = task->jobs; !error && job; job = job->JOBnextJob) {
                if (job->JOBtype == sens_num) {
                    senflag = 1;
                    ckt->CKTcurJob = job;
                    ckt->CKTsenInfo = (SENstruct*)job;
                    error = analInfo[sens_num]->an_func(ckt, reset);
                }
            }

        if (ckt->CKTsenInfo && (!senflag || error))
            FREE(ckt->CKTsenInfo);
#endif

        /* make sure this is either up do date or NULL */
        ckt->CKTcurJob = NULL;

        /* normal reset -- unless Enhancement-471's reuse was requested and the
           circuit is still standing from the previous job */
        {
            int reuse = ckt->CKTreuseSetup && ckt->CKTisSetup
                        && e471_reuse_safe(ckt);

            if (!reuse) {
                ckt->CKTreuseSetup = 0;
                if (!error)
                    error = CKTunsetup(ckt);

                if (!error)
                    error = CKTsetup(ckt);
            }

            /* Run CKTtemp either way: for an OSDI device this is what
               re-decides the node collapse, which is the whole basis for
               reuse being safe. While the request is still set, OSDItemp
               keeps quiet about a mismatch instead of warning that the
               matrix cannot be rebuilt -- because here it can be. */
            if (!error)
                error = CKTtemp(ckt);

            if (reuse) {
                ckt->CKTreuseSetup = 0;      /* a request is good for one job */

                ckt->CKTreuseKept++;

                if (!error && OSDIanyCollapseChanged(ckt)) {
                    ckt->CKTreuseKept--;
                    ckt->CKTreuseRebuilt++;
                    /* The topology moved under us. The reused matrix is the
                       wrong shape, so build it again properly -- and let this
                       second CKTtemp warn if it still disagrees. */
                    error = CKTunsetup(ckt);

                    if (!error)
                        error = CKTsetup(ckt);

                    if (!error)
                        error = CKTtemp(ckt);
                }
            }
        }

        if (error) {
            return error;
        }
    }

    error2 = OK;

    /* Analysis order is important */
    for (i = 0; i < ANALmaxnum; i++) {

#ifdef WANT_SENSE2
        if (i == sens_num)
            continue;
#endif

        for (job = task->jobs; job; job = job->JOBnextJob) {
            if (job->JOBtype == i) {
                ckt->CKTcurJob = job;
                error = OK;
                if (analInfo[i]->an_init)
                    error = analInfo[i]->an_init(ckt, job);
                if (!error && analInfo[i]->do_ic)
                    error = CKTic(ckt);
                if (!error) {
#ifdef XSPICE
                    if (reset) {
                        /* gtri - begin - 6/10/91 - wbk - Setup event-driven data */
                        error = EVTsetup(ckt);
                        if (error) {
                            ckt->CKTstat->STATtotAnalTime +=
                                SPfrontEnd->IFseconds() - startTime;
                            return(error);
                        }
                        /* gtri - end - 6/10/91 - wbk - Setup event-driven data */
                    }
#endif
                    error = analInfo[i]->an_func(ckt, reset);
                    /* txl, cpl addition */
                    if (error == 1111) break;
                }
                if (error)
                    error2 = error;
            }
        }
    }

    ckt->CKTstat->STATtotAnalTime += SPfrontEnd->IFseconds() - startTime;

#ifdef WANT_SENSE2
    if (ckt->CKTsenInfo)
        SENdestroy(ckt->CKTsenInfo);
#endif

    return(error2);
}

