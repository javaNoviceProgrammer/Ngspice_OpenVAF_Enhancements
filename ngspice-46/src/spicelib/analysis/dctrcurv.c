/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 1999 Paolo Nenzi
**********/

#include "ngspice/ngspice.h"

#include "vsrc/vsrcdefs.h"
#include "isrc/isrcdefs.h"
#include "res/resdefs.h"

#include "ngspice/cktdefs.h"
#include "ngspice/const.h"
#include "ngspice/sperror.h"
#include "ngspice/fteext.h"
#include "ngspice/compatmode.h"

#ifdef XSPICE
#include "ngspice/evt.h"
#include "ngspice/mif.h"
#include "ngspice/evtproto.h"
#include "ngspice/ipctiein.h"
#endif

#include "ngspice/devdefs.h"

#ifdef OSDI
#include "ngspice/osdiitf.h"   /* Enhancement-53: OSDIfinalStep */
#endif

#ifdef HAS_PROGREP
static double actval, actdiff;
#endif

/* Enhancement-62: resolve a `@inst[param]` sweep variable to its instance,
   device type, and (settable, real-valued) instance-parameter id, through
   the generic DEVparam/DEVask tables. Returns OK on success. Instance
   lookup walks every device type comparing names case-insensitively (the
   sweep name is a raw token, not an interned IFuid, so the DEVnameHash
   cannot be used). */
static int
DCTfindInstParam(CKTcircuit *ckt, const char *name, GENinstance **instOut,
                 int *typeOut, int *parmOut, int *dtypeOut)
{
    char buf[1024];
    char alt[1026];                     /* Enhancement-410: `<letter>.` + buf */
    char *lbrack, *rbrack, *parname;
    GENmodel *model;
    GENinstance *inst;
    IFdevice *dev;
    int type, k, pass;

    if (!name || name[0] != '@' || strlen(name) >= sizeof(buf))
        return E_NODEV;
    strcpy(buf, name + 1);
    /* Enhancement-441: the fourth place the `@name[param]` split lives, and the
       one the array-instance work first missed. An array instance is named
       `r[2]`, so `@r[2][resistance]` has two bracket groups; splitting at the
       first '[' looked for a device `r` with a parameter `2`, and `.dc` failed
       fatally with "not in the circuit" -- for the CARD and the command alike --
       while `print`, `alter` and `sweep` had already been taught the name.
       ft_accessor_param_start() is the shared rule; the closing-bracket match
       below is Enhancement-408's and is unchanged. */
    lbrack = ft_accessor_param_start(buf);
    /* Enhancement-408: match the CLOSING bracket, so a parameter whose own
       name contains brackets -- a bus terminal current i_a[0], an array
       parameter element ap[0] -- resolves instead of being truncated at the
       inner ']' and reported as "no such parameter". */
    rbrack = NULL;
    if (lbrack) {
        char *s;
        int brdepth = 0;
        for (s = lbrack; *s; s++) {
            if (*s == '[') {
                brdepth++;
            } else if (*s == ']' && --brdepth == 0) {
                rbrack = s;
                break;
            }
        }
    }
    if (!lbrack || !rbrack || rbrack <= lbrack + 1 || lbrack == buf)
        return E_NODEV;
    *lbrack = '\0';
    *rbrack = '\0';
    parname = lbrack + 1;

    /* Enhancement-410: two passes -- the EXACT name first, so every spelling
       that resolves today keeps resolving to exactly the same instance, then
       the hierarchical form written without the device-type letter that
       subcircuit flattening prepends (`x1.r1` -> `r.x1.r1`). The letter is the
       leaf name's own first character, so no search is needed. */
    for (pass = 0; pass < 2; pass++) {
        const char *want = buf;

        if (pass == 1) {
            const char *local = strrchr(buf, '.');
            if (!local || !local[1] || local[1] == 'x' || local[1] == 'X')
                break;                  /* nothing to reconstruct */
            if (strlen(buf) + 3 > sizeof alt)
                break;
            (void) snprintf(alt, sizeof alt, "%c.%s", local[1], buf);
            want = alt;
        }

        for (type = 0; type < DEVmaxnum; type++) {
            if (!DEVices[type])
                continue;
            for (model = ckt->CKThead[type]; model; model = model->GENnextModel)
                for (inst = model->GENinstances; inst; inst = inst->GENnextInstance)
                    if (inst->GENname && cieq(inst->GENname, want)) {
                        dev = &DEVices[type]->DEVpublic;
                        for (k = 0; dev->instanceParms && k < *dev->numInstanceParms; k++) {
                            IFparm *prm = dev->instanceParms + k;
                            int vt = prm->dataType & IF_VARTYPES;
                            /* Enhancement-427: INTEGER instance parameters are
                             * sweepable too. Only IF_REAL matched before, so
                             * `dc @n1[n] 1 4 1` over `parameter integer n`
                             * fell through to E_BADPARM and was reported with
                             * the generic "not in the circuit" message -- while
                             * `alter @n1[n]=2.7` and the instance line both set
                             * the same parameter happily (rounding to 3). */
                            if ((prm->dataType & IF_SET)
                                && (vt == IF_REAL || vt == IF_INTEGER)
                                && cieq(prm->keyword, parname)) {
                                *instOut = inst;
                                *typeOut = type;
                                *parmOut = prm->id;
                                if (dtypeOut)
                                    *dtypeOut = vt;
                                return OK;
                            }
                        }
                        return E_BADPARM;
                    }
        }
    }
    return E_NODEV;
}

/* Enhancement-62: set the swept instance parameter to `val` and refresh the
   device (DEVtemperature re-runs per-model/per-instance setup -- for OSDI
   devices that is exactly the parameter-change path `alter` + a fresh
   analysis would take). */
/* Enhancement-427: this used to be `void` and threw away BOTH return values.
 *
 * The range a Verilog-A model declares -- `parameter real r = 1000 from
 * (0:inf)` -- is not checked when the value is WRITTEN. It is checked when the
 * device is set up again, i.e. inside DEVtemperature (OSDItemp ->
 * setup_instance, which prints "Parameter r is out of bounds!"). Both returns
 * were discarded, so `dc @n1[r] -2000 -1000 500` printed that message four
 * times and then published THREE data rows computed at R = -2000, -1500 and
 * -1000, exiting 0. Every other route to the same parameter refuses it: the
 * instance line, `alter` and the `sweep` command all abort.
 *
 * The test is deliberately "the DEVICE rejected this value", never "the value
 * looks wrong". A negative resistance is legitimate for a built-in resistor --
 * resparam.c has an explicit branch for one -- so a sign test here would break
 * decks that sweep a resistor negative on purpose. Only a device that says no
 * stops the sweep. */
static int
DCTsetInstParam(CKTcircuit *ckt, TRCV *job, int i, double val)
{
    IFvalue v;
    int type = job->TRCVvElt[i]->GENmodPtr->GENmodType;
    int err;

    /* Enhancement-427: an INTEGER parameter needs iValue, not rValue -- writing
     * the wrong union member would hand the device the bit pattern of a double.
     * Rounding matches what `alter` and the instance line already do (2.7 -> 3). */
    if (job->TRCVvParmType[i] == IF_INTEGER)
        v.iValue = (int) floor(val + 0.5);
    else
        v.rValue = val;
    err = DEVices[type]->DEVparam(job->TRCVvParmId[i], &v, job->TRCVvElt[i], NULL);
    if (err)
        return err;
    job->TRCVvNow[i] = val;
    if (DEVices[type]->DEVtemperature) {
        err = DEVices[type]->DEVtemperature(ckt->CKThead[type], ckt);
        if (err)
            return err;
    }
    return OK;
}

/* Enhancement-427: is this sweep endpoint a whole number? */
static int
DCTisWhole(double v)
{
    return v == floor(v) && fabs(v) < 2147483000.0;
}

/* Report a START value the device refused. Used only before the plot is opened
 * and before any device state has been changed, so there is nothing to restore;
 * the mid-sweep case exits through osdi_finish instead. The device has already
 * said WHAT is wrong ("Parameter r is out of bounds!"); this adds which sweep
 * and which value, which the bare message does not carry. */
static int
DCTrejected(TRCV *job, int i, double val)
{
    SPfrontEnd->IFerrorf(ERR_WARNING,
        "DC sweep %d: the device refused %s = %g -- the same value is refused "
        "on the instance line and by `alter`; sweep not started\n",
        i + 1, job->TRCVvName[i] ? job->TRCVvName[i] : "?", val);
    return E_PARMVAL;
}


int
DCtrCurv(CKTcircuit *ckt, int restart)
{
    TRCV *job = (TRCV *) ckt->CKTcurJob;

    int i;
    double *temp;
    int converged;
    int rcode;
    int vcode;
    int icode;
    int j;
    int error;
    IFuid varUid;
    IFuid *nameList;
    int numNames;
    int firstTime = 1;
    static runDesc *plot = NULL;
    /* Enhancement-427: a sweep point the device refused aborts the analysis,
     * but through the restore path below -- returning bare would leave the
     * instance holding the rejected value, the E-381/E-382/E-385
     * state-restoration class. */
    int dctrc = OK;
    double dct_rejected_val = 0.0;
    int dct_rejected_lvl = -1;

#ifdef WANT_SENSE2
    long save;
#ifdef SENSDEBUG
    if (ckt->CKTsenInfo && (ckt->CKTsenInfo->SENmode & DCSEN)) {
        printf("\nDC Sensitivity Results\n\n");
        CKTsenPrint(ckt);
    }
#endif
#endif

    rcode = CKTtypelook("Resistor");
    vcode = CKTtypelook("Vsource");
    icode = CKTtypelook("Isource");

    if (!restart && job->TRCVnestState >= 0) {
        /* continuing */
        i = job->TRCVnestState;
        /* resume to work? saj*/
        error = SPfrontEnd->OUTpBeginPlot (NULL, NULL,
                                           NULL,
                                           NULL, 0,
                                           666, NULL, 666,
                                           &plot);
        goto resume;
    }

    /* Enhancement-362: a .dc sweep advances by TRCVvStep and compares against
     * TRCVvStop -- there is no precomputed point count, so a step that is tiny
     * relative to the span (a `1e-30` where `1e-3` was meant) runs essentially
     * forever, with no diagnostic and nothing to distinguish it from a merely
     * slow circuit. A zero step is already refused; a count that cannot be
     * represented should be too, and .tran already declines the equivalent
     * request. Found by fuzzing analysis-card parameters. */
    for (i = 0; i <= job->TRCVnestLevel && i < TRCVNESTLEVEL; i++) {
        double step_ = job->TRCVvStep[i];
        double pts_;
        if (step_ == 0.0)
            continue;                  /* rejected on its own path */
        pts_ = fabs((job->TRCVvStop[i] - job->TRCVvStart[i]) / step_);
        if (!(pts_ == pts_) || pts_ > 2147483000.0)
            return(E_PARMVAL);
        /* ...and the step has to actually move the sweep value. Below the ULP of
         * the start point, `value += step` is a no-op in floating point and the
         * loop never advances at all -- `dc V1 1 1 1e-30` hangs on a zero-length
         * span, which the point count above cannot see. */
        if (job->TRCVvStart[i] + step_ == job->TRCVvStart[i])
            return(E_PARMVAL);
        /* Enhancement-426: ...and it has to move TOWARDS stop. `dc v1 0.6 0.4
         * 0.05` and its mirror `dc v1 0.4 0.6 -0.05` computed no points at all
         * and said nothing -- not an empty plot the caller could notice, but a
         * vector that never came into existence.
         *
         * The strict `< 0` product is the whole fix boundary. It is FALSE when
         * start == stop (product 0), which is the single-point sweep 13 decks
         * in examples/ rely on, and FALSE for a genuine descending sweep
         * (negative times negative) such as `dc v1 2 0 -0.001`. Only a step
         * pointing away from stop is refused. The step is NOT auto-negated:
         * guessing here would silently answer a question nobody asked. */
        if ((job->TRCVvStop[i] - job->TRCVvStart[i]) * step_ < 0.0) {
            SPfrontEnd->IFerrorf(ERR_WARNING,
                "DC sweep %d: step %g moves away from stop %g (start %g)"
                " -- no points would be computed\n",
                i + 1, step_, job->TRCVvStop[i], job->TRCVvStart[i]);
            return(E_PARMVAL);
        }
    }

    ckt->CKTtime = 0;
    ckt->CKTdelta = job->TRCVvStep[0];
    ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT;
    ckt->CKTorder = 1;

    /* Enhancement-380: a DC sweep must not inherit integration coefficients.
     *
     * dioload.c gates its charge branch on
     *     MODEDCTRANCURVE | MODETRAN | MODEAC | MODEINITSMSIG
     * so a charge-storing device DOES take that path during a .dc sweep, and it
     * ends in NIintegrate(), which returns geq = CKTag[0] * cap.
     *
     * In a fresh session CKTag[] has never been computed, so it is zero, geq is
     * zero, and charge contributes nothing to the sweep -- which is the correct
     * DC behaviour. But CKTag[] is plain circuit state: after any analysis that
     * drives the transient machinery -- `pss` (a shooting method, so many
     * transient cycles), `tran`, `envelope`, `qpss` -- it still holds THAT
     * analysis' coefficients, where ag[0] ~ 1/delta is large. The sweep then adds
     * a spurious geq = ag[0]*cap to every charge-storing device.
     *
     * Measured before this fix on a 1k/1k divider with a diode across it, where
     * v(mid) = V1/3 exactly:
     *
     *     op          ->  0.16666666452   correct
     *     pss ; dc    ->  0.09391732333   44% low, silently
     *
     * with the diode reporting gd some 3000x too large for its own vd. Setting
     * cjo=0 made it vanish, which is what identified the charge path; `op` was
     * always correct because MODEDCOP is not in that gate; and only `reset`
     * cleared it, because nothing else reinitialises CKTag[].
     *
     * NOTE: zeroing CKTstates[] here does NOT help -- that was tried and measured
     * unchanged. The stale value is the coefficient, not the stored charge.
     */
    for (j = 0; j < 7; j++)
        ckt->CKTag[j] = 0.0;

    /* Save the state of the circuit */
    for (j = 0; j < 7; j++)
        ckt->CKTdeltaOld[j] = ckt->CKTdelta;

    for (i = 0; i <= job->TRCVnestLevel; i++) {

        if (rcode >= 0) {
            /* resistances are in this version, so use them */
            RESinstance *here;
            RESmodel *model;

            for (model = (RESmodel *)ckt->CKThead[rcode]; model; model = RESnextModel(model))
                for (here = RESinstances(model); here; here = RESnextInstance(here))
                    if (here->RESname == job->TRCVvName[i]) {
                        job->TRCVvElt[i]  = (GENinstance *)here;
                        job->TRCVvSave[i] = here->RESresist;
                        job->TRCVgSave[i] = here->RESresGiven;
                        job->TRCVvType[i] = rcode;
                        here->RESresist   = job->TRCVvStart[i];
                        here->RESresGiven = 1;
                        CKTtemp(ckt);
                        goto found;
                    }
        }

        if (vcode >= 0) {
            /* voltage sources are in this version, so use them */
            VSRCinstance *here;
            VSRCmodel *model;

            for (model = (VSRCmodel *)ckt->CKThead[vcode]; model; model = VSRCnextModel(model))
                for (here = VSRCinstances(model); here; here = VSRCnextInstance(here))
                    if (here->VSRCname == job->TRCVvName[i]) {
                        job->TRCVvElt[i]  = (GENinstance *)here;
                        job->TRCVvSave[i] = here->VSRCdcValue;
                        job->TRCVgSave[i] = here->VSRCdcGiven;
                        job->TRCVvType[i] = vcode;
                        here->VSRCdcValue = job->TRCVvStart[i];
                        here->VSRCdcGiven = 1;
                        goto found;
                    }
        }

        if (icode >= 0) {
            /* current sources are in this version, so use them */
            ISRCinstance *here;
            ISRCmodel *model;

            for (model = (ISRCmodel *)ckt->CKThead[icode]; model; model = ISRCnextModel(model))
                for (here = ISRCinstances(model); here; here = ISRCnextInstance(here))
                    if (here->ISRCname == job->TRCVvName[i]) {
                        job->TRCVvElt[i]  = (GENinstance *)here;
                        job->TRCVvSave[i] = here->ISRCdcValue;
                        job->TRCVgSave[i] = here->ISRCdcGiven;
                        job->TRCVvType[i] = icode;
                        here->ISRCdcValue = job->TRCVvStart[i];
                        here->ISRCdcGiven = 1;
                        goto found;
                    }
        }

        if (cieq(job->TRCVvName[i], "temp")) {
            /* Enhancement-426: a `.dc temp` sweep writes ckt->CKTtemp directly
             * and so never passes the CKTsetOpt funnel that guards `.options
             * temp`. `dc temp -600 100 100` walked straight through absolute
             * zero and produced eight fully-formed rows without a word. Both
             * endpoints have to be physical -- -25 C is ordinary, -300 C is
             * not. Checked here rather than in the range loop above because
             * TRCVvType is not assigned until this point. */
            if (job->TRCVvStart[i] + CONSTCtoK <= 0.0 ||
                job->TRCVvStop[i] + CONSTCtoK <= 0.0) {
                SPfrontEnd->IFerrorf(ERR_WARNING,
                    "DC sweep %d: temperature range %g C .. %g C reaches at or"
                    " below absolute zero (-273.15 C)\n",
                    i + 1, job->TRCVvStart[i], job->TRCVvStop[i]);
                return(E_PARMVAL);
            }
            job->TRCVvSave[i] = ckt->CKTtemp; /* Saves the old circuit temperature */
            job->TRCVvType[i] = TEMP_CODE;    /* Set the sweep type code */
            ckt->CKTtemp = job->TRCVvStart[i] + CONSTCtoK; /* Set the new circuit temp */
            inp_evaluate_temper(ft_curckt);
            CKTtemp(ckt);
            goto found;
        }

        /* Enhancement-62: `.dc @inst[param] start stop step` -- sweep any
           settable real instance parameter of any device (incl. OSDI).
           Enhancement-427: integer parameters too. */
        if (job->TRCVvName[i] && job->TRCVvName[i][0] == '@') {
            GENinstance *pinst;
            int ptype, pid, pdtype = IF_REAL;
            int perr = DCTfindInstParam(ckt, job->TRCVvName[i], &pinst, &ptype,
                                        &pid, &pdtype);
            if (perr == OK) {
                IFvalue old_v;
                job->TRCVvElt[i] = pinst;
                job->TRCVvType[i] = PARAM_CODE;
                job->TRCVvParmId[i] = pid;
                job->TRCVvParmType[i] = pdtype;
                if (DEVices[ptype]->DEVask
                    && DEVices[ptype]->DEVask(ckt, pinst, pid, &old_v, NULL) == OK)
                    job->TRCVvSave[i] = (pdtype == IF_INTEGER)
                                            ? (double) old_v.iValue
                                            : old_v.rValue;
                else
                    job->TRCVvSave[i] = job->TRCVvStart[i];
                job->TRCVgSave[i] = 1;
                /* Enhancement-427: an INTEGER parameter may only be swept over
                 * whole numbers. Rounding happens at the DEVparam boundary, but
                 * the sweep ACCUMULATOR has to stay real (a rounded accumulator
                 * plus a 0.25 step never advances -- the non-advancing-loop
                 * class E-362 and E-426 already had to guard here). Allowing a
                 * fractional sweep would therefore publish duplicate operating
                 * points under an abscissa that disagrees with the value the
                 * device actually saw: the `sweep` command does exactly that
                 * today, writing 0, 0.25, 0.5, 0.75, 1 while the device saw
                 * 0, 0, 1, 1, 1. Refusing is the honest option. */
                if (pdtype == IF_INTEGER
                    && !(DCTisWhole(job->TRCVvStart[i])
                         && DCTisWhole(job->TRCVvStop[i])
                         && DCTisWhole(job->TRCVvStep[i]))) {
                    SPfrontEnd->IFerrorf(ERR_FATAL,
                        "DC sweep %d: %s is an integer parameter -- start, stop "
                        "and step must be whole numbers (got %g %g %g)",
                        i + 1, job->TRCVvName[i], job->TRCVvStart[i],
                        job->TRCVvStop[i], job->TRCVvStep[i]);
                    return(E_PARMVAL);
                }
                if (DCTsetInstParam(ckt, job, i, job->TRCVvStart[i]) != OK)
                    return DCTrejected(job, i, job->TRCVvStart[i]);
                goto found;
            }
            /* Enhancement-427: the device WAS found, the parameter was not.
               Saying "no such source" for that sends the reader looking in the
               wrong place -- it is the same message E_NODEV gets. */
            if (perr == E_BADPARM) {
                SPfrontEnd->IFerrorf (ERR_FATAL,
                        "DC sweep: %s names a device that exists, but not a "
                        "sweepable parameter of it (it must be a settable real "
                        "or integer instance parameter)",
                        job->TRCVvName[i]);
                return(E_BADPARM);
            }
        }

        SPfrontEnd->IFerrorf (ERR_FATAL,
                "DC Transfer Function: Voltage source, current source, or "
                "resistor named \"%s\" is not in the circuit",
                job->TRCVvName[i]);
        return(E_NODEV);

    found:;
    }

#ifdef HAS_PROGREP
    actval = job->TRCVvStart[job->TRCVnestLevel];
    actdiff = job->TRCVvStart[job->TRCVnestLevel] - job->TRCVvStop[job->TRCVnestLevel];
#endif

#ifdef XSPICE

    /* Tell the code models what mode we're in */
    g_mif_info.circuit.anal_type = MIF_DC;

    g_mif_info.circuit.anal_init = MIF_TRUE;

#endif

    error = CKTnames(ckt, &numNames, &nameList);
    if (error)
        return(error);

    if (job->TRCVvType[0] == vcode)
        SPfrontEnd->IFnewUid (ckt, &varUid, NULL, "v-sweep", UID_OTHER, NULL);
    else if (job->TRCVvType[0] == icode)
        SPfrontEnd->IFnewUid (ckt, &varUid, NULL, "i-sweep", UID_OTHER, NULL);
    else if (job->TRCVvType[0] == TEMP_CODE)
        SPfrontEnd->IFnewUid (ckt, &varUid, NULL, "temp-sweep", UID_OTHER, NULL);
    else if (job->TRCVvType[0] == rcode)
        SPfrontEnd->IFnewUid (ckt, &varUid, NULL, "res-sweep", UID_OTHER, NULL);
    else if (job->TRCVvType[0] == PARAM_CODE)
        SPfrontEnd->IFnewUid (ckt, &varUid, NULL, "param-sweep", UID_OTHER, NULL);
    else
        SPfrontEnd->IFnewUid (ckt, &varUid, NULL, "?-sweep", UID_OTHER, NULL);

    error = SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                                       ckt->CKTcurJob->JOBname,
                                       varUid, IF_REAL,
                                       numNames, nameList, IF_REAL,
                                       &plot);
    tfree(nameList);

    if (error)
        return(error);

    /* initialize CKTsoaCheck `warn' counters */
    if (ckt->CKTsoaCheck)
        error = CKTsoaInit();

    /* now have finished the initialization - can start doing hard part */

    i = 0;

 resume:

    for (;;) {

        if (job->TRCVvType[i] == vcode) { /* voltage source */
            if (SGN(job->TRCVvStep[i]) *
                (((VSRCinstance*)(job->TRCVvElt[i]))->VSRCdcValue -
                 job->TRCVvStop[i]) >
                DBL_EPSILON * 1e+03)
            {
                i++;
                firstTime = 1;
                ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT;
                if (i > job->TRCVnestLevel)
                    break;
                goto nextstep;
            }
        } else if (job->TRCVvType[i] == icode) { /* current source */
            if (SGN(job->TRCVvStep[i]) *
                (((ISRCinstance*)(job->TRCVvElt[i]))->ISRCdcValue -
                 job->TRCVvStop[i]) >
                DBL_EPSILON * 1e+03)
            {
                i++;
                firstTime = 1;
                ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT;
                if (i > job->TRCVnestLevel)
                    break;
                goto nextstep;
            }
        } else if (job->TRCVvType[i] == rcode) { /* resistance */
            if (SGN(job->TRCVvStep[i]) *
                (((RESinstance*)(job->TRCVvElt[i]))->RESresist -
                 job->TRCVvStop[i]) >
                DBL_EPSILON * 1e+03)
            {
                i++;
                firstTime = 1;
                ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT;
                if (i > job->TRCVnestLevel)
                    break;
                goto nextstep;
            }
        } else if (job->TRCVvType[i] == TEMP_CODE) { /* temp sweep */
            if (SGN(job->TRCVvStep[i]) *
                ((ckt->CKTtemp - CONSTCtoK) - job->TRCVvStop[i]) >
                DBL_EPSILON * 1e+03)
            {
                i++;
                firstTime = 1;
                ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT;
                if (i > job->TRCVnestLevel)
                    break;
                goto nextstep;
            }
        } else if (job->TRCVvType[i] == PARAM_CODE) { /* @inst[param] sweep */
            if (SGN(job->TRCVvStep[i]) *
                (job->TRCVvNow[i] - job->TRCVvStop[i]) >
                DBL_EPSILON * 1e+03)
            {
                i++;
                firstTime = 1;
                ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT;
                if (i > job->TRCVnestLevel)
                    break;
                goto nextstep;
            }
        }

        while (--i >= 0)
            if (job->TRCVvType[i] == vcode) { /* voltage source */
                ((VSRCinstance *)(job->TRCVvElt[i]))->VSRCdcValue =
                    job->TRCVvStart[i];
            } else if (job->TRCVvType[i] == icode) { /* current source */
                ((ISRCinstance *)(job->TRCVvElt[i]))->ISRCdcValue =
                    job->TRCVvStart[i];
            } else if (job->TRCVvType[i] == TEMP_CODE) {
                ckt->CKTtemp = job->TRCVvStart[i] + CONSTCtoK;
                inp_evaluate_temper(ft_curckt);
                CKTtemp(ckt);
            } else if (job->TRCVvType[i] == rcode) {
                ((RESinstance *)(job->TRCVvElt[i]))->RESresist =
                    job->TRCVvStart[i];
                RESupdate_conduct((RESinstance *)(job->TRCVvElt[i]), FALSE);
                DEVices[rcode]->DEVload(job->TRCVvElt[i]->GENmodPtr, ckt);
            } else if (job->TRCVvType[i] == PARAM_CODE) {
                if (DCTsetInstParam(ckt, job, i, job->TRCVvStart[i]) != OK)
                    return DCTrejected(job, i, job->TRCVvStart[i]);
            }

        /* Rotate state vectors. */
        temp = ckt->CKTstates[ckt->CKTmaxOrder + 1];
        for (j = ckt->CKTmaxOrder; j >= 0; j--)
            ckt->CKTstates[j + 1] = ckt->CKTstates[j];
        ckt->CKTstate0 = temp;

        /* do operation */
#ifdef XSPICE
/* gtri - begin - wbk - Do EVTop if event instances exist */
        if (ckt->evt->counts.num_insts == 0) {
            /* If no event-driven instances, do what SPICE normally does */
#endif

            if (newcompat.hs) {
                converged = CKTop(ckt,
                                  (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT,
                                  (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITFLOAT,
                                  ckt->CKTdcMaxIter);
                if (converged != 0)
                    return(converged);
            }
            else {
                /* Enhancement-258: the .dc sweep solves each point with a direct
                   NIiter (warm-started from the previous point) and only falls
                   back to CKTop on failure. The FIRST point of a segment is a
                   COLD start (firstTime) from the v=0-ish initial guess, so a
                   singular-derivative behavioral source can false-converge to a
                   spurious operating point here just like a plain .op (E-256).
                   Flag it as a first-try op so NIiter's KCL-residual guard fires;
                   on rejection `converged != 0` routes to the CKTop fallback
                   below (gmin/source stepping), which finds the true point. */
                ckt->CKTdcFirstTry = firstTime;
                converged = NIiter(ckt, ckt->CKTdcTrcvMaxIter);
                ckt->CKTdcFirstTry = 0;
                if (converged != 0) {
                    converged = CKTop(ckt,
                        (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT,
                        (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITFLOAT,
                        ckt->CKTdcMaxIter);
                    if (converged != 0)
                        return(converged);
                }
            }
#ifdef XSPICE
        }
        else {
            /* else do new algorithm */

            /* first get the current step in the analysis */
            if (job->TRCVvType[0] == vcode) {
                g_mif_info.circuit.evt_step =
                    ((VSRCinstance *)(job->TRCVvElt[0]))->VSRCdcValue;
            } else if (job->TRCVvType[0] == icode) {
                g_mif_info.circuit.evt_step =
                    ((ISRCinstance *)(job->TRCVvElt[0]))->ISRCdcValue;
            } else if (job->TRCVvType[0] == rcode) {
                g_mif_info.circuit.evt_step =
                    ((RESinstance*)(job->TRCVvElt[0]->GENmodPtr))->RESresist;
            } else if (job->TRCVvType[0] == TEMP_CODE) {
                g_mif_info.circuit.evt_step =
                    ckt->CKTtemp - CONSTCtoK;
            } else if (job->TRCVvType[0] == PARAM_CODE) {
                g_mif_info.circuit.evt_step = job->TRCVvNow[0];
            }

            /* if first time through, call EVTop immediately and save event results */
            if (firstTime) {
                converged = EVTop(ckt,
                                  (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT,
                                  (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITFLOAT,
                                  ckt->CKTdcMaxIter,
                                  MIF_TRUE);
                EVTdump(ckt, IPC_ANAL_DCOP, g_mif_info.circuit.evt_step);
                EVTop_save(ckt, MIF_FALSE, g_mif_info.circuit.evt_step);
                if (converged != 0)
                    return(converged);
            }
            /* else, call NIiter first with mode = MODEINITPRED */
            /* to attempt quick analog solution.  Then call all hybrids and call */
            /* EVTop only if event outputs have changed, or if non-converged */
            else {
                converged = NIiter(ckt, ckt->CKTdcTrcvMaxIter);
                EVTcall_hybrids(ckt);
                if ((converged != 0) || (ckt->evt->queue.output.num_changed != 0)) {
                    converged = EVTop(ckt,
                                      (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT,
                                      (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITFLOAT,
                                      ckt->CKTdcMaxIter,
                                      MIF_FALSE);
                    EVTdump(ckt, IPC_ANAL_DCTRCURVE, g_mif_info.circuit.evt_step);
                    EVTop_save(ckt, MIF_FALSE, g_mif_info.circuit.evt_step);
                    if (converged != 0)
                        return(converged);
                }
            }
        }
/* gtri - end - wbk - Do EVTop if event instances exist */
#endif

        ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITPRED;
        if (job->TRCVvType[0] == vcode)
            ckt->CKTtime = ((VSRCinstance *)(job->TRCVvElt[0]))->VSRCdcValue;
        else if (job->TRCVvType[0] == icode)
            ckt->CKTtime = ((ISRCinstance *)(job->TRCVvElt[0]))->ISRCdcValue;
        else if (job->TRCVvType[0] == rcode)
            ckt->CKTtime = ((RESinstance *)(job->TRCVvElt[0]))->RESresist;
        else if (job->TRCVvType[0] == PARAM_CODE)
            ckt->CKTtime = job->TRCVvNow[0];
        else if (job->TRCVvType[0] == TEMP_CODE)
            ckt->CKTtime = ckt->CKTtemp - CONSTCtoK;

#ifdef XSPICE
        /* If first time through, call CKTdump to output Operating Point info */
        if (wantevtdata && firstTime) {
            CKTdump(ckt, 0.0, plot);
        }
#endif

#ifdef WANT_SENSE2
/*
  if (!ckt->CKTsenInfo) printf("sensitivity structure does not exist\n");
*/
        if (ckt->CKTsenInfo && (ckt->CKTsenInfo->SENmode & DCSEN)) {
            int senmode;

#ifdef SENSDEBUG
            if (job->TRCVvType[0] == vcode) { /* voltage source */
                printf("Voltage Source Value : %.5e V\n",
                       ((VSRCinstance*) (job->TRCVvElt[0]))->VSRCdcValue);
            }
            if (job->TRCVvType[0] == icode) { /* current source */
                printf("Current Source Value : %.5e A\n",
                       ((ISRCinstance*)(job->TRCVvElt[0]))->ISRCdcValue);
            }
            if (job->TRCVvType[0] == rcode) { /* resistance */
                printf("Current Resistance Value : %.5e Ohm\n",
                       ((RESinstance*)(job->TRCVvElt[0]->GENmodPtr))->RESresist);
            }
            if (job->TRCVvType[0] == TEMP_CODE) { /* Temperature */
                printf("Current Circuit Temperature : %.5e C\n",
                       ckt->CKTtemp - CONSTCtoK);
            }
#endif

            senmode = ckt->CKTsenInfo->SENmode;
            save = ckt->CKTmode;
            ckt->CKTsenInfo->SENmode = DCSEN;
            error = CKTsenDCtran(ckt);
            if (error)
                return(error);

            ckt->CKTmode = save;
            ckt->CKTsenInfo->SENmode = senmode;
        }
#endif

        CKTdump(ckt,ckt->CKTtime,plot);

        if (ckt->CKTsoaCheck)
            error = CKTsoaCheck(ckt);

#ifdef OSDI
        /* Enhancement-55: deferred Verilog-A $finish/$stop, honored once the
           sweep point is accepted and output. $finish ends the sweep cleanly
           (through the normal restore/endplot path); $stop pauses resumably
           like the user-pause below. */
        {
            int osdi_req = OSDIpendingRequests(ckt);
            if (osdi_req & OSDI_REQ_FINISH) {
                fprintf(stdout, "\nNote: $finish requested by a Verilog-A device (sweep value %g).\n",
                        ckt->CKTtime);
                goto osdi_finish;
            }
            if (osdi_req & OSDI_REQ_STOP) {
                fprintf(stdout, "\nNote: $stop requested by a Verilog-A device (sweep value %g); pausing.\n",
                        ckt->CKTtime);
                job->TRCVnestState = 0;
                return(E_PAUSE);
            }
        }
#endif

        if (firstTime) {
            firstTime = 0;
            if (ckt->CKTstate1 && ckt->CKTstate0) {
                memcpy(ckt->CKTstate1, ckt->CKTstate0,
                       (size_t) ckt->CKTnumStates * sizeof(double));
            }
        }

        i = 0;

    nextstep:;

        if (job->TRCVvType[i] == vcode) { /* voltage source */
            ((VSRCinstance*)(job->TRCVvElt[i]))->VSRCdcValue +=
                job->TRCVvStep[i];
        } else if (job->TRCVvType[i] == icode) { /* current source */
            ((ISRCinstance*)(job->TRCVvElt[i]))->ISRCdcValue +=
                job->TRCVvStep[i];
        } else if (job->TRCVvType[i] == rcode) { /* resistance */
            ((RESinstance*)(job->TRCVvElt[i]))->RESresist +=
                job->TRCVvStep[i];
            RESupdate_conduct((RESinstance *)(job->TRCVvElt[i]), FALSE);
            DEVices[rcode]->DEVload(job->TRCVvElt[i]->GENmodPtr, ckt);
        } else if (job->TRCVvType[i] == PARAM_CODE) { /* @inst[param] */
            double next_ = job->TRCVvNow[i] + job->TRCVvStep[i];
            /* Enhancement-427: the loop top discards this point when it is past
             * `stop`, so do NOT hand it to the device first. The sweep has
             * always computed one value beyond the end -- harmless while
             * failures were ignored, but it means a sweep that legitimately
             * ENDS AT the edge of a model's `from` range steps one point
             * outside it. `parameter real k = 0.5 from [0:1]` with
             * `.dc @n1[k] 0 1 0.25` printed "Parameter k is out of bounds!"
             * once even before this enhancement, while producing five correct
             * rows; refusing that would have broken a valid sweep. The
             * TEMP_CODE arm just below already declines its own overshoot for
             * exactly this reason. */
            if (SGN(job->TRCVvStep[i]) * (next_ - job->TRCVvStop[i])
                    > DBL_EPSILON * 1e+03) {
                job->TRCVvNow[i] = next_;      /* advance; the point is dropped */
            } else if (DCTsetInstParam(ckt, job, i, next_) != OK) {
                dct_rejected_val = next_;
                dct_rejected_lvl = i;
                dctrc = E_PARMVAL;
                goto osdi_finish;   /* abort THROUGH the restore path */
            }
        } else if (job->TRCVvType[i] == TEMP_CODE) { /* temperature */
            ckt->CKTtemp += job->TRCVvStep[i];

            /* FIXME: Do the Temp check already here for the first time.
               If the stop criterion is fulfilled, discard Temp evaluation, because
               CKTtemp may report errors if a large extra Temp step is exercized. */
            if (SGN(job->TRCVvStep[i]) *
                ((ckt->CKTtemp - CONSTCtoK) - job->TRCVvStop[i]) > DBL_EPSILON * 1e+03) {
//                ckt->CKTtemp -= job->TRCVvStep[i]; // Undo the large step
//                ckt->CKTtemp += SGN(job->TRCVvStep[i]) * DBL_EPSILON * 2e+03; // Add just a small step
                continue; // Skip model evaluation
            }

            inp_evaluate_temper(ft_curckt);
            CKTtemp(ckt);
        }

        if (SPfrontEnd->IFpauseTest()) {
            /* user asked us to pause, so save state */
            job->TRCVnestState = i;
            return(E_PAUSE);
        }

#ifdef HAS_PROGREP
        if (i == job->TRCVnestLevel) {
            actval += job->TRCVvStep[job->TRCVnestLevel];
            SetAnalyse("dc", abs((int)((actval - job->TRCVvStart[job->TRCVnestLevel]) * 1000. / actdiff)));
        }
#endif

    }

    /* all done, lets put everything back */

/* Enhancement-427: no longer inside #ifdef OSDI. The label was added by E-55 for
 * the OSDI-only $finish/$stop exit, but the sweep-value rejection below reaches
 * it from the PARAM_CODE arm, which is not OSDI-gated -- so a --disable-osdi
 * build failed with "use of undeclared label 'osdi_finish'". Reaching the
 * restore path is the whole point of jumping here: returning where the
 * rejection happens would leave the instance holding the refused value. */
osdi_finish:
    for (i = 0; i <= job->TRCVnestLevel; i++)
        if (job->TRCVvType[i] == vcode) {   /* voltage source */
            ((VSRCinstance*)(job->TRCVvElt[i]))->VSRCdcValue = job->TRCVvSave[i];
            ((VSRCinstance*)(job->TRCVvElt[i]))->VSRCdcGiven = (job->TRCVgSave[i] != 0);
        } else  if (job->TRCVvType[i] == icode) { /*current source */
            ((ISRCinstance*)(job->TRCVvElt[i]))->ISRCdcValue = job->TRCVvSave[i];
            ((ISRCinstance*)(job->TRCVvElt[i]))->ISRCdcGiven = (job->TRCVgSave[i] != 0);
        } else  if (job->TRCVvType[i] == rcode) { /* Resistance */
            ((RESinstance*)(job->TRCVvElt[i]))->RESresist = job->TRCVvSave[i];
            ((RESinstance*)(job->TRCVvElt[i]))->RESresGiven = (job->TRCVgSave[i] != 0);
            RESupdate_conduct((RESinstance *)(job->TRCVvElt[i]), TRUE);
            DEVices[rcode]->DEVload(job->TRCVvElt[i]->GENmodPtr, ckt);
        } else if (job->TRCVvType[i] == TEMP_CODE) {
            ckt->CKTtemp = job->TRCVvSave[i];
            inp_evaluate_temper(ft_curckt);
            CKTtemp(ckt);
        } else if (job->TRCVvType[i] == PARAM_CODE) {
            /* value restored; the parameter stays marked "given" (the
               generic DEVparam interface has no way to clear that).
               Enhancement-427: deliberately NOT checked -- the sweep is over,
               its results are already published, and failing here would turn a
               completed analysis into an error. The value being put back was
               accepted once, so a refusal would itself be the anomaly. */
            (void) DCTsetInstParam(ckt, job, i, job->TRCVvSave[i]);
        }

#ifdef OSDI
    /* Enhancement-53: fire `@(final_step)` blocks at the last sweep point
       (results are not loaded into the matrix). */
    OSDIfinalStep(ckt);
#endif
    SPfrontEnd->OUTendPlot (plot);

    if (dct_rejected_lvl >= 0)
        SPfrontEnd->IFerrorf(ERR_WARNING,
            "DC sweep %d: the device refused %s = %g -- the same value is "
            "refused on the instance line and by `alter`; sweep abandoned "
            "there\n",
            dct_rejected_lvl + 1,
            job->TRCVvName[dct_rejected_lvl]
                ? job->TRCVvName[dct_rejected_lvl] : "?",
            dct_rejected_val);

    return(dctrc);
}
