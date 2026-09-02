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
#include "ngspice/devdefs.h"
#ifdef OSDI
#include "ngspice/osdiitf.h"   /* Enhancement-495: OSDIanyCollapseChanged */
#endif

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
/* Enhancement-495 ---------------------------------------------------------
 *
 * `.dc` sets the circuit up ONCE and walks its points inside the analysis --
 * Enhancement-471's own comment says so, and says what follows from it: reuse
 * the setup and "the topology is frozen at whatever the first point decided,
 * and the sweep quietly draws a flat line". E-471 gave the `sweep` command the
 * machinery to notice and rebuild. `.dc` never got it, so a device-parameter
 * sweep that moves a device across a structural boundary is silently wrong:
 *
 *   - a swept `l` or `w` that leaves the model bin the device was PARSED into
 *     keeps the old bin, and every point past the boundary is computed with the
 *     wrong model (measured 2.9x out);
 *   - a swept parameter that changes an OSDI device's node collapse keeps the
 *     matrix built for the old topology, and the sweep returns a FLAT LINE at
 *     the value the first point decided.
 *
 * `alter` and `sweep` both get these right -- `alter` re-selects the bin through
 * if_set_binned_model(), and `sweep` runs a whole job per point -- which is the
 * same siblings-disagree shape Enhancement-427 recorded two comments above.
 *
 * Rebuilding the matrix in the middle of a running analysis is a far larger
 * change than the evidence supports, and the correct command already exists. So
 * `.dc` now REFUSES the point it cannot compute, and says which command does it,
 * rather than publishing a number that is wrong without saying so -- E-485's
 * rule that a wrong answer is worse than a refusal.
 *
 * The check is "did the DEVICE's structure actually move", never "does this
 * value look odd": a sweep that stays inside one bin, or never changes a
 * collapse, is untouched and costs nothing but the comparison. */

/* read a real MODEL parameter by keyword; 0 if the device has no such parameter */
static int
DCTmodelReal(CKTcircuit *ckt, GENmodel *mod, const char *key, double *out)
{
    SPICEdev *sdev;
    IFdevice *dev;
    int k;

    if (!mod)
        return 0;
    sdev = DEVices[mod->GENmodType];
    if (!sdev || !sdev->DEVmodAsk)
        return 0;
    dev = &sdev->DEVpublic;
    if (!dev->modelParms || !dev->numModelParms)
        return 0;
    for (k = 0; k < *dev->numModelParms; k++) {
        IFparm *prm = dev->modelParms + k;
        IFvalue v;
        if (!prm->keyword || !cieq(prm->keyword, (char *) key))
            continue;
        if (sdev->DEVmodAsk(ckt, mod, prm->id, &v) != OK)
            return 0;
        *out = v.rValue;
        return 1;
    }
    return 0;
}


/* read a real INSTANCE parameter by keyword; 0 if there is no such parameter */
static int
DCTinstReal(CKTcircuit *ckt, GENinstance *inst, const char *key, double *out)
{
    SPICEdev *sdev;
    IFdevice *dev;
    int k;

    if (!inst || !inst->GENmodPtr)
        return 0;
    sdev = DEVices[inst->GENmodPtr->GENmodType];
    if (!sdev || !sdev->DEVask)
        return 0;
    dev = &sdev->DEVpublic;
    if (!dev->instanceParms || !dev->numInstanceParms)
        return 0;
    for (k = 0; k < *dev->numInstanceParms; k++) {
        IFparm *prm = dev->instanceParms + k;
        IFvalue v;
        if (!prm->keyword || !cieq(prm->keyword, (char *) key))
            continue;
        if (sdev->DEVask(ckt, inst, prm->id, &v, NULL) != OK)
            return 0;
        *out = v.rValue;
        return 1;
    }
    return 0;
}


/* Has the instance been swept out of the bin its model card describes?
 *
 * Only a model that was chosen by binning is asked -- INPgetModBin binds the
 * `<base>.<n>` card, so the dot is the marker -- and only when that card states
 * all four limits. Anything else answers "no" and the sweep proceeds exactly as
 * before. The rule matches INPgetModBin's strict pass: min <= value < max. */
static int
DCTleftItsBin(CKTcircuit *ckt, GENinstance *inst)
{
    double l, w, lmin, lmax, wmin, wmax;
    GENmodel *mod;

    if (!inst || !inst->GENmodPtr)
        return 0;
    mod = inst->GENmodPtr;
    if (!mod->GENmodName || !strchr(mod->GENmodName, '.'))
        return 0;                       /* not a binned model card */

    if (!DCTmodelReal(ckt, mod, "lmin", &lmin) ||
        !DCTmodelReal(ckt, mod, "lmax", &lmax) ||
        !DCTmodelReal(ckt, mod, "wmin", &wmin) ||
        !DCTmodelReal(ckt, mod, "wmax", &wmax))
        return 0;                       /* no limits to be outside of */
    if (lmax <= lmin || wmax <= wmin)
        return 0;                       /* degenerate card -- not ours to judge */

    if (!DCTinstReal(ckt, inst, "l", &l) || !DCTinstReal(ckt, inst, "w", &w))
        return 0;

    return !(l >= lmin && l < lmax && w >= wmin && w < wmax);
}


/* Enhancement-495: set when the refusal came from the topology/bin check
 * below rather than from the device. Enhancement-427's message says "the
 * device refused ... the same value is refused on the instance line and by
 * `alter`", and here that would be false on both counts: the device took the
 * value, and `alter` computes this case correctly. The caller reads this to
 * leave the specific message standing on its own. */
/* Enhancement-534: the overshoot slack for a parameter sweep. The classic
 * arms use an ABSOLUTE 1e3*DBL_EPSILON, which is right at source scale
 * (volts, ohms) and catastrophically wrong at device-parameter scale: a
 * saturation current swept to 5e-14 sat BELOW the absolute slack the whole
 * way, so the walk ran on to 2.7e-13 -- five times past stop -- publishing
 * rows the user never asked for (latent in E-62's @inst[param] sweeps since
 * the day tiny parameters could be swept). Scale the slack to the sweep's
 * own magnitudes; at classic scales (>= 1) it is bit-identical to the old
 * constant. */
static double
dct_over_slack(TRCV *job, int i)
{
    double m = fabs(job->TRCVvStop[i]);
    if (fabs(job->TRCVvStart[i]) > m)
        m = fabs(job->TRCVvStart[i]);
    if (fabs(job->TRCVvStep[i]) > m)
        m = fabs(job->TRCVvStep[i]);
    if (m < 1.0)
        return DBL_EPSILON * 1e+03 * (m > 0.0 ? m : 1.0);
    return DBL_EPSILON * 1e+03;
}

static int dct_topology_refusal = 0;


static int
DCTsetInstParam(CKTcircuit *ckt, TRCV *job, int i, double val, int check)
{
    IFvalue v;
    int type = job->TRCVvElt[i]->GENmodPtr->GENmodType;
    int err;

    dct_topology_refusal = 0;

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

    /* Enhancement-495: the DEVtemperature above is exactly where an OSDI device
     * re-decides its node collapse and records a mismatch against the snapshot
     * the matrix was built from (Enhancement-417). The flag was being set all
     * along and nobody asked. Consume it even when not reporting, so a restore
     * cannot leave it set for a later analysis to misread. */
    {
        int moved = 0;
#ifdef OSDI
        moved = OSDIanyCollapseChanged(ckt);
#endif
        if (check && moved) {
            SPfrontEnd->IFerrorf(ERR_WARNING,
                "DC sweep %d: %s = %g changes this device's node collapse, and "
                "the matrix was built for the collapse decided at setup -- the "
                "remaining points would be computed for the wrong topology. Use "
                "the `sweep` command, which rebuilds for each point\n",
                i + 1, job->TRCVvName[i] ? job->TRCVvName[i] : "?", val);
            dct_topology_refusal = 1;
            return E_PARMVAL;
        }
        if (check && DCTleftItsBin(ckt, job->TRCVvElt[i])) {
            SPfrontEnd->IFerrorf(ERR_WARNING,
                "DC sweep %d: %s = %g takes the device outside model bin %s, and "
                "`.dc` selects the bin once, at parse time -- the remaining "
                "points would be computed with the wrong model. Use the `sweep` "
                "command, which re-selects the bin for each point\n",
                i + 1, job->TRCVvName[i] ? job->TRCVvName[i] : "?", val,
                job->TRCVvElt[i]->GENmodPtr->GENmodName);
            dct_topology_refusal = 1;
            return E_PARMVAL;
        }
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


/* ================= Enhancement-534: extended parameter sweeps =============
 *
 * `.dc` learns the rest of the parameter surface the `sweep`/`altermod`
 * family established: a MODEL parameter (`@mod[p]`, with the subcircuit
 * spelling `@x1.rmod[p]` resolved through the same if_find_model_hier funnel
 * E-433 taught the frontend), and the wildcard families `@*[p]` (every model
 * with p), `@#*[p]` / `@*[[p]]` (every instance with p), `@*:leaf[p]` /
 * `@*.leaf[p]` (every model named leaf, wherever expansion put it).
 *
 * Targets are collected ONCE at resolution and written per point through the
 * DEV tables directly -- DEVparam/DEVmodParam, the MACHINE-write path. The
 * frontend's own wildcard setters were deliberately NOT reused for the
 * per-point writes: they run doset_user(), which is `alter`'s recentering
 * hook for `.option osdimc` statistical parameters, and Enhancement-531
 * established that sweeps must never recenter a nominal; they also
 * controlled_exit() on a CKTtemp error, which would turn one refused sweep
 * point into a dead process. One CKTtemp() per point propagates the change
 * and re-runs the E-495 collapse guard, however many targets moved. */

/* the settable IFparm id for `key` in a type's model/instance table, its
 * readable twin, and the value type. Mirrors spiceif's parmlookup: keyword
 * match, IF_SET to write, IF_ASK to capture the nominal, real or integer. */
static int
dct_parm_ids(int type, const char *key, int do_model,
             int *set_id, int *ask_id, int *ptype)
{
    IFdevice *dev;
    IFparm *table;
    int n, k, vt;
    int sid = -1, aid = -1, pt = IF_REAL;

    if (type < 0 || !DEVices[type])
        return 0;
    dev = &DEVices[type]->DEVpublic;
    table = do_model ? dev->modelParms : dev->instanceParms;
    n = do_model ? (dev->numModelParms ? *dev->numModelParms : 0)
                 : (dev->numInstanceParms ? *dev->numInstanceParms : 0);
    if (!table || n <= 0)
        return 0;
    for (k = 0; k < n; k++) {
        if (!table[k].keyword || !cieq(table[k].keyword, (char *) key))
            continue;
        vt = table[k].dataType & IF_VARTYPES;
        if (vt != IF_REAL && vt != IF_INTEGER)
            continue;
        if ((table[k].dataType & IF_SET) && sid < 0) {
            sid = table[k].id;
            pt = vt;
        }
        if ((table[k].dataType & IF_ASK) && aid < 0)
            aid = table[k].id;
    }
    if (sid < 0 || aid < 0)
        return 0;
    *set_id = sid;
    *ask_id = aid;
    *ptype = pt;
    return 1;
}

/* the leaf a flattened model name carries: expansion renames a subcircuit's
 * `.model rmod` to `<path>:rmod`, the top-level card keeps its plain name */
static const char *
dct_model_leaf(const char *name)
{
    const char *p = name ? strrchr(name, ':') : NULL;
    return p ? p + 1 : name;
}

/* classify a wildcard knob -- the exact grammar sw_wildcard_knob() and
 * `altermod` accept, lowercased the way the device tables store keywords:
 *   `@*[p]`         every MODEL with p          (do_model = 1)
 *   `@#*[p]`        every INSTANCE with p       (do_model = 0)
 *   `@*[[p]]`       every INSTANCE with p       (alias)
 *   `@*:leaf[p]`    every model named leaf      (do_model = 1, leaf set)
 *   `@*.leaf[p]`    same, the dotted spelling
 * Returns 1 for a wildcard. */
static int
dct_wildcard_knob(const char *name, char *param, size_t plen,
                  int *do_model, char *leaf, size_t llen)
{
    const char *p, *end;
    size_t i, n;

    if (leaf && llen)
        leaf[0] = '\0';
    if (!name || name[0] != '@' || !param || plen == 0 || !do_model)
        return 0;
    p = name + 1;
    if (p[0] == '#' && p[1] == '*' && p[2] == '[') {
        *do_model = 0;
        p += 3;
    } else if (p[0] == '*' && p[1] == '[' && p[2] == '[') {
        *do_model = 0;
        p += 3;
    } else if (p[0] == '*' && p[1] == '[') {
        *do_model = 1;
        p += 2;
    } else if (p[0] == '*' && (p[1] == ':' || p[1] == '.') &&
               p[2] && p[2] != '[') {
        const char *lp = p + 2;
        const char *lend = strchr(lp, '[');
        size_t ln;
        if (!lend || lend == lp || !leaf || llen == 0)
            return 0;
        ln = (size_t) (lend - lp);
        if (ln >= llen)
            return 0;
        for (i = 0; i < ln; i++)
            leaf[i] = (char) tolower_c(lp[i]);
        leaf[ln] = '\0';
        *do_model = 1;
        p = lend + 1;
    } else {
        return 0;
    }
    end = strchr(p, ']');
    if (!end || end == p)
        return 0;
    n = (size_t) (end - p);
    if (n >= plen)
        return 0;
    for (i = 0; i < n; i++)
        param[i] = (char) tolower_c(p[i]);
    param[n] = '\0';
    return 1;
}

/* append one target, nominal captured through the ask twin */
static int
dct_xtarg_add(CKTcircuit *ckt, TRCV *job, int i, GENinstance *inst,
              GENmodel *mod, int type, int set_id, int ask_id, int ptype)
{
    IFvalue v;
    DCTxtarget *t;
    int n = job->TRCVxN[i];

    job->TRCVxTarg[i] = TREALLOC(DCTxtarget, job->TRCVxTarg[i], n + 1);
    t = &job->TRCVxTarg[i][n];
    t->inst = inst;
    t->mod = mod;
    t->type = type;
    t->set_id = set_id;
    t->ptype = ptype;
    t->save = 0.0;
    if (inst) {
        if (!DEVices[type]->DEVask ||
            DEVices[type]->DEVask(ckt, inst, ask_id, &v, NULL) != OK)
            return 0;
    } else {
        if (!DEVices[type]->DEVmodAsk ||
            DEVices[type]->DEVmodAsk(ckt, mod, ask_id, &v) != OK)
            return 0;
    }
    t->save = (ptype == IF_INTEGER) ? (double) v.iValue : v.rValue;
    job->TRCVxN[i] = n + 1;
    return 1;
}

/* write every target and propagate. `check` arms the E-495 topology guard,
 * exactly as DCTsetInstParam does for the single-instance sweep. */
static int
DCTsetXParam(CKTcircuit *ckt, TRCV *job, int i, double val, int check)
{
    int k, err;

    dct_topology_refusal = 0;
    for (k = 0; k < job->TRCVxN[i]; k++) {
        DCTxtarget *t = &job->TRCVxTarg[i][k];
        IFvalue v;
        if (t->ptype == IF_INTEGER)
            v.iValue = (int) floor(val + 0.5);
        else
            v.rValue = val;
        err = t->inst
                  ? DEVices[t->type]->DEVparam(t->set_id, &v, t->inst, NULL)
                  : DEVices[t->type]->DEVmodParam(t->set_id, &v, t->mod);
        if (err)
            return err;
    }
    job->TRCVvNow[i] = val;
    err = CKTtemp(ckt);
    if (err)
        return err;
    {
        int moved = 0;
#ifdef OSDI
        moved = OSDIanyCollapseChanged(ckt);
#endif
        if (check && moved) {
            SPfrontEnd->IFerrorf(ERR_WARNING,
                "DC sweep %d: %s = %g changes a device's node collapse, and "
                "the matrix was built for the collapse decided at setup -- the "
                "remaining points would be computed for the wrong topology. Use "
                "the `sweep` command, which rebuilds for each point\n",
                i + 1, job->TRCVvName[i] ? job->TRCVvName[i] : "?", val);
            dct_topology_refusal = 1;
            return E_PARMVAL;
        }
    }
    return OK;
}

/* put the nominals back, unchecked (the sweep is over, its results are
 * published -- the same reasoning as the PARAM_CODE restore), and drop the
 * target list. */
static void
DCTrestoreXParam(CKTcircuit *ckt, TRCV *job, int i)
{
    int k;

    for (k = 0; k < job->TRCVxN[i]; k++) {
        DCTxtarget *t = &job->TRCVxTarg[i][k];
        IFvalue v;
        if (t->ptype == IF_INTEGER)
            v.iValue = (int) floor(t->save + 0.5);
        else
            v.rValue = t->save;
        if (t->inst)
            (void) DEVices[t->type]->DEVparam(t->set_id, &v, t->inst, NULL);
        else
            (void) DEVices[t->type]->DEVmodParam(t->set_id, &v, t->mod);
    }
    if (job->TRCVxN[i] > 0)
        (void) CKTtemp(ckt);
    tfree(job->TRCVxTarg[i]);
    job->TRCVxTarg[i] = NULL;
    job->TRCVxN[i] = 0;
}

/* resolve an `@...` name as a model parameter or a wildcard family.
 * Returns OK with the target list built and the START value applied;
 * E_NODEV when the spelling is not this kind (the caller keeps looking);
 * any other error after printing why. */
static int
DCTresolveXParam(CKTcircuit *ckt, TRCV *job, int i)
{
    const char *name = job->TRCVvName[i];
    char param[128], leaf[128];
    int do_model = 0, t, any_int = 0, k;
    GENmodel *cmod = NULL;
    int cmod_type = -1;

    /* a re-run of a still-loaded .dc card resolves again: drop the old list */
    tfree(job->TRCVxTarg[i]);
    job->TRCVxTarg[i] = NULL;
    job->TRCVxN[i] = 0;

    if (!name || name[0] != '@')
        return E_NODEV;

    if (dct_wildcard_knob(name, param, sizeof param, &do_model,
                          leaf, sizeof leaf)) {
        for (t = 0; t < DEVmaxnum; t++) {
            int sid, aid, pt;
            GENmodel *mod;
            if (!DEVices[t] || !ckt->CKThead[t])
                continue;
            if (!dct_parm_ids(t, param, do_model, &sid, &aid, &pt))
                continue;
            for (mod = ckt->CKThead[t]; mod; mod = mod->GENnextModel) {
                if (leaf[0] && !(mod->GENmodName &&
                                 cieq((char *) dct_model_leaf(mod->GENmodName),
                                      leaf)))
                    continue;
                if (do_model) {
                    if (!dct_xtarg_add(ckt, job, i, NULL, mod, t, sid, aid, pt))
                        goto askfail;
                } else {
                    GENinstance *inst;
                    for (inst = mod->GENinstances; inst;
                         inst = inst->GENnextInstance)
                        if (!dct_xtarg_add(ckt, job, i, inst, NULL, t,
                                           sid, aid, pt))
                            goto askfail;
                }
            }
        }
        if (job->TRCVxN[i] == 0) {
            if (leaf[0])
                SPfrontEnd->IFerrorf(ERR_FATAL,
                    "DC sweep %d: no loaded model named '%s' has parameter "
                    "'%s' (a model inside a subcircuit is flattened to "
                    "<instance>:%s)", i + 1, leaf, param, leaf);
            else if (do_model)
                SPfrontEnd->IFerrorf(ERR_FATAL,
                    "DC sweep %d: no loaded model has a settable parameter "
                    "'%s'", i + 1, param);
            else
                SPfrontEnd->IFerrorf(ERR_FATAL,
                    "DC sweep %d: no loaded instance has a settable parameter "
                    "'%s'", i + 1, param);
            return E_BADPARM;
        }
    } else {
        /* a concrete `@name[p]` whose name is a MODEL (the instance
         * interpretation was already tried and failed): split exactly the
         * way DCTfindInstParam splits, then the E-433 hierarchy funnel */
        char buf[1024];
        char *lbrack, *rbrack, *s;
        int brdepth = 0, sid, aid, pt;

        if (strlen(name) >= sizeof buf)
            return E_NODEV;
        strcpy(buf, name + 1);
        lbrack = ft_accessor_param_start(buf);
        rbrack = NULL;
        if (lbrack)
            for (s = lbrack; *s; s++) {
                if (*s == '[')
                    brdepth++;
                else if (*s == ']' && --brdepth == 0) {
                    rbrack = s;
                    break;
                }
            }
        if (!lbrack || !rbrack || rbrack <= lbrack + 1 || lbrack == buf)
            return E_NODEV;
        *lbrack = '\0';
        *rbrack = '\0';
        if (strlen(lbrack + 1) >= sizeof param)
            return E_NODEV;
        for (k = 0; (lbrack + 1)[k]; k++)
            param[k] = (char) tolower_c((lbrack + 1)[k]);
        param[k] = '\0';

        for (t = 0; t < DEVmaxnum && !cmod; t++) {
            GENmodel *mod;
            if (!DEVices[t] || !ckt->CKThead[t])
                continue;
            for (mod = ckt->CKThead[t]; mod; mod = mod->GENnextModel)
                if (mod->GENmodName && cieq(mod->GENmodName, buf)) {
                    cmod = mod;
                    cmod_type = t;
                    break;
                }
        }
        if (!cmod) {
            cmod = if_find_model_hier(ckt, buf);
            if (cmod)
                cmod_type = cmod->GENmodType;
        }
        if (!cmod)
            return E_NODEV;
        if (!dct_parm_ids(cmod_type, param, 1, &sid, &aid, &pt)) {
            SPfrontEnd->IFerrorf(ERR_FATAL,
                "DC sweep %d: %s names a model that exists, but not a "
                "sweepable parameter of it (it must be a settable real or "
                "integer model parameter)",
                i + 1, name);
            return E_BADPARM;
        }
        if (!dct_xtarg_add(ckt, job, i, NULL, cmod, cmod_type, sid, aid, pt))
            goto askfail;
    }

    /* Enhancement-534/503: a BUILT-IN target whose swept parameter builds
     * internal nodes decides its topology in DEVsetup, and a running dc
     * cannot rebuild -- refuse up front, naming the instrument that can.
     * (OSDI targets are guarded at run time instead: OSDItemp re-decides the
     * collapse each point and E-495 refuses when it moves.) */
    for (k = 0; k < job->TRCVxN[i]; k++) {
        DCTxtarget *tt = &job->TRCVxTarg[i][k];
        if (DEVices[tt->type]->DEVpublic.registry_entry)
            continue;                  /* OSDI: run-time guard */
        if (CKTbuiltinTopologyParamRisk(DEVices[tt->type]->DEVpublic.name,
                                        param)) {
            SPfrontEnd->IFerrorf(ERR_FATAL,
                "DC sweep %d: %s reaches a parameter that builds internal "
                "nodes at setup time (a '%s' device), and `.dc` sets the "
                "circuit up once -- the points would be computed for a frozen "
                "topology. Use the `sweep` command, which re-runs setup for "
                "each point",
                i + 1, name, DEVices[tt->type]->DEVpublic.name
                                 ? DEVices[tt->type]->DEVpublic.name : "?");
            tfree(job->TRCVxTarg[i]);
            job->TRCVxTarg[i] = NULL;
            job->TRCVxN[i] = 0;
            return E_PARMVAL;
        }
    }

    for (k = 0; k < job->TRCVxN[i]; k++)
        if (job->TRCVxTarg[i][k].ptype == IF_INTEGER)
            any_int = 1;
    if (any_int) {
        /* Enhancement-427's whole-number rule, extended: a fractional point
         * would publish an abscissa the device never saw. The keyword scales
         * generate fractional values by construction, so an integer target
         * refuses them outright. */
        if (job->TRCVscale[i] != DCT_SCALE_LEGACY) {
            SPfrontEnd->IFerrorf(ERR_FATAL,
                "DC sweep %d: %s reaches an integer parameter -- lin/dec/oct "
                "point generation is fractional; use whole-number start stop "
                "step instead",
                i + 1, name);
            /* E-536 (hunt bug 11): drop the collected list, exactly as the
             * sibling error paths do -- a stale list with TRCVxN > 0 and
             * dangling owner pointers otherwise outlives this refusal. */
            tfree(job->TRCVxTarg[i]);
            job->TRCVxTarg[i] = NULL;
            job->TRCVxN[i] = 0;
            return E_PARMVAL;
        }
        if (!(DCTisWhole(job->TRCVvStart[i]) && DCTisWhole(job->TRCVvStop[i])
              && DCTisWhole(job->TRCVvStep[i]))) {
            SPfrontEnd->IFerrorf(ERR_FATAL,
                "DC sweep %d: %s reaches an integer parameter -- start, stop "
                "and step must be whole numbers (got %g %g %g)",
                i + 1, name, job->TRCVvStart[i], job->TRCVvStop[i],
                job->TRCVvStep[i]);
            tfree(job->TRCVxTarg[i]);      /* E-536 (hunt bug 11) */
            job->TRCVxTarg[i] = NULL;
            job->TRCVxN[i] = 0;
            return E_PARMVAL;
        }
    }

    job->TRCVvType[i] = XPARAM_CODE;
    job->TRCVvSave[i] = job->TRCVxTarg[i][0].save;
    job->TRCVgSave[i] = 1;
    if (DCTsetXParam(ckt, job, i, job->TRCVvStart[i], 1) != OK) {
        int topo = dct_topology_refusal;
        DCTrestoreXParam(ckt, job, i);
        return topo ? E_PARMVAL : DCTrejected(job, i, job->TRCVvStart[i]);
    }
    return OK;

askfail:
    SPfrontEnd->IFerrorf(ERR_FATAL,
        "DC sweep %d: a nominal of %s could not be read back, so the sweep "
        "could not be restored afterwards; sweep not started",
        i + 1, name);
    tfree(job->TRCVxTarg[i]);
    job->TRCVxTarg[i] = NULL;
    job->TRCVxN[i] = 0;
    return E_BADPARM;
}

/* Enhancement-534: the value of a COUNTED (lin/dec/oct) level at its current
 * index. lin interpolates the way the sweep command does, so the endpoint is
 * exact; dec/oct multiply iteratively from the previous value, so the point
 * set is bit-identical to sweep's own generation. */
static double
dct_scale_value(TRCV *job, int i)
{
    if (job->TRCVscale[i] == DCT_SCALE_LIN) {
        int n = job->TRCVnTotal[i];
        return (n <= 1) ? job->TRCVvStart[i]
                        : job->TRCVvStart[i]
                          + (job->TRCVvStop[i] - job->TRCVvStart[i])
                            * job->TRCVidx[i] / (n - 1);
    }
    return job->TRCVvNow[i] * job->TRCVratio[i];   /* dec / oct: next point */
}

/* Enhancement-534: set level i of ANY sweep-variable kind to `val` -- the
 * per-type bodies of the classic advance arms, gathered so the counted walk
 * can drive every kind through one call. `check` arms the mid-sweep guards
 * for the parameter kinds, exactly as the legacy arms do. */
static int
DCTapplyLevel(CKTcircuit *ckt, TRCV *job, int i, double val, int check,
              int vcode, int icode, int rcode)
{
    int err = OK;

    if (job->TRCVvType[i] == vcode) {
        ((VSRCinstance *) (job->TRCVvElt[i]))->VSRCdcValue = val;
    } else if (job->TRCVvType[i] == icode) {
        ((ISRCinstance *) (job->TRCVvElt[i]))->ISRCdcValue = val;
    } else if (job->TRCVvType[i] == rcode) {
        ((RESinstance *) (job->TRCVvElt[i]))->RESresist = val;
        RESupdate_conduct((RESinstance *) (job->TRCVvElt[i]), FALSE);
        DEVices[rcode]->DEVload(job->TRCVvElt[i]->GENmodPtr, ckt);
    } else if (job->TRCVvType[i] == TEMP_CODE) {
        ckt->CKTtemp = val + CONSTCtoK;
        inp_evaluate_temper(ft_curckt);
        err = CKTtemp(ckt);
    } else if (job->TRCVvType[i] == PARAM_CODE) {
        err = DCTsetInstParam(ckt, job, i, val, check);
    } else if (job->TRCVvType[i] == XPARAM_CODE) {
        err = DCTsetXParam(ckt, job, i, val, check);
    }
    job->TRCVvNow[i] = val;
    return err;
}


/* E-536 fix (hunt bug 10): resolution APPLIES each level's start value as it
 * walks the levels (a temperature is set and propagated through
 * inp_evaluate_temper + CKTtemp, a source's dc value overwritten, a
 * parameter written through the DEV tables) -- so a failure at a LATER level
 * must put every earlier level back, or the error leaves the circuit
 * silently changed: `dc v1 0.5 1.5 0.5 @r1[bogus] 1 2 0.5` left v1 parked at
 * 0.5 V, and a temp outer level left every temper-baked expression at the
 * sweep's start temperature. Restore from `from` down to 0, in REVERSE
 * order, so an aliased knob lands back on its true pre-sweep value (levels
 * above `from` were never resolved this run and their job fields may be
 * stale -- they are deliberately not touched). The clash refusal and every
 * resolution-failure return share this path. */
static void
DCTunwindLevels(CKTcircuit *ckt, TRCV *job, int from,
                int vcode, int icode, int rcode)
{
    int i;
    for (i = from; i >= 0; i--) {
        if (job->TRCVvType[i] == XPARAM_CODE)
            DCTrestoreXParam(ckt, job, i);
        else if (job->TRCVvType[i] == PARAM_CODE)
            (void) DCTsetInstParam(ckt, job, i, job->TRCVvSave[i], 0);
        else if (job->TRCVvType[i] == TEMP_CODE) {
            ckt->CKTtemp = job->TRCVvSave[i];
            inp_evaluate_temper(ft_curckt);
            CKTtemp(ckt);
        } else if (rcode >= 0 && job->TRCVvType[i] == rcode) {
            ((RESinstance *)(job->TRCVvElt[i]))->RESresist =
                job->TRCVvSave[i];
            ((RESinstance *)(job->TRCVvElt[i]))->RESresGiven =
                (job->TRCVgSave[i] != 0);
            RESupdate_conduct((RESinstance *)(job->TRCVvElt[i]), TRUE);
            DEVices[rcode]->DEVload(job->TRCVvElt[i]->GENmodPtr, ckt);
        } else if (vcode >= 0 && job->TRCVvType[i] == vcode) {
            ((VSRCinstance *)(job->TRCVvElt[i]))->VSRCdcValue =
                job->TRCVvSave[i];
            ((VSRCinstance *)(job->TRCVvElt[i]))->VSRCdcGiven =
                (job->TRCVgSave[i] != 0);
        } else if (icode >= 0 && job->TRCVvType[i] == icode) {
            ((ISRCinstance *)(job->TRCVvElt[i]))->ISRCdcValue =
                job->TRCVvSave[i];
            ((ISRCinstance *)(job->TRCVvElt[i]))->ISRCdcGiven =
                (job->TRCVgSave[i] != 0);
        }
    }
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
    int dct_rejected_topo = 0;   /* Enhancement-495 */

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
        /* Enhancement-534: a counted (lin/dec/oct) level never accumulates by
         * step -- its point count is validated at resolution */
        if (job->TRCVscale[i] != DCT_SCALE_LEGACY)
            continue;
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
        /* Enhancement-480: the step points the right way but is LARGER than the
         * span, so the sweep cannot take even one step and the analysis
         * produces no rows at all -- `dc v1 0 0.1 1` printed an empty table and
         * exited 0. That is a plausible typo (a step and a stop transposed, or
         * a unit slipped) and it is indistinguishable from a working run unless
         * the reader counts the rows.
         *
         * A WARNING, not a refusal: the sweep is well-formed, and the start
         * point is arguably a legitimate single sample. `start == stop` is
         * deliberately NOT included -- E-426 records that 13 decks in examples/
         * depend on it being accepted, and this must not change what they do. */
        if (job->TRCVvStop[i] != job->TRCVvStart[i] &&
            fabs(job->TRCVvStop[i] - job->TRCVvStart[i]) < fabs(step_)) {
            SPfrontEnd->IFerrorf(ERR_WARNING,
                "DC sweep %d: step %g is larger than the span %g to %g,"
                " so no points are computed\n",
                i + 1, step_, job->TRCVvStart[i], job->TRCVvStop[i]);
        }
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
                DCTunwindLevels(ckt, job, i - 1, vcode, icode, rcode);   /* E-536 (hunt bug 10) */
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
                    DCTunwindLevels(ckt, job, i - 1, vcode, icode, rcode);   /* E-536 (hunt bug 10) */
                    return(E_PARMVAL);
                }
                if (DCTsetInstParam(ckt, job, i, job->TRCVvStart[i], 1) != OK) {
                    DCTunwindLevels(ckt, job, i - 1, vcode, icode, rcode);   /* E-536 (hunt bug 10) */
                    return dct_topology_refusal
                        ? E_PARMVAL       /* Enhancement-495 already said why */
                        : DCTrejected(job, i, job->TRCVvStart[i]);
                }
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
                DCTunwindLevels(ckt, job, i - 1, vcode, icode, rcode);   /* E-536 (hunt bug 10) */
                return(E_BADPARM);
            }
        }

        /* Enhancement-534: a MODEL parameter or a wildcard family */
        if (job->TRCVvName[i] && job->TRCVvName[i][0] == '@') {
            int xerr = DCTresolveXParam(ckt, job, i);
            if (xerr == OK)
                goto found;
            if (xerr != E_NODEV) {
                DCTunwindLevels(ckt, job, i - 1, vcode, icode, rcode);   /* E-536 (hunt bug 10) */
                return xerr;           /* the resolver already said why */
            }
        }

        SPfrontEnd->IFerrorf (ERR_FATAL,
                "DC Transfer Function: Voltage source, current source, or "
                "resistor named \"%s\" is not in the circuit",
                job->TRCVvName[i]);
        DCTunwindLevels(ckt, job, i - 1, vcode, icode, rcode);   /* E-536 (hunt bug 10) */
        return(E_NODEV);

    found:;
        /* Enhancement-534: convert a keyword scale into a counted walk, with
         * the sweep command's own point generation (lin: interpolated, both
         * endpoints exact; dec/oct: N per decade/octave, iterative multiply
         * up to stop*(1+1e-9)). The start value was applied by the
         * resolution above; TRCVvNow seeds the multiplicative walk. */
        if (job->TRCVscale[i] != DCT_SCALE_LEGACY) {
            double f0 = job->TRCVvStart[i], f1 = job->TRCVvStop[i];
            job->TRCVidx[i] = 0;
            job->TRCVvNow[i] = f0;
            if (job->TRCVscale[i] == DCT_SCALE_LIN) {
                if (job->TRCVnPts[i] < 1) {
                    SPfrontEnd->IFerrorf(ERR_FATAL,
                        "DC sweep %d: lin needs at least 1 point", i + 1);
                    DCTunwindLevels(ckt, job, i, vcode, icode, rcode);
                    return(E_PARMVAL);
                }
                job->TRCVnTotal[i] = job->TRCVnPts[i];
            } else {
                double per = (job->TRCVscale[i] == DCT_SCALE_DEC) ? 10.0 : 2.0;
                double mul, x;
                int nv = 0;
                if (f0 <= 0.0 || f1 <= 0.0 || f1 < f0) {
                    SPfrontEnd->IFerrorf(ERR_FATAL,
                        "DC sweep %d: dec/oct need positive endpoints with "
                        "start <= stop (got %g .. %g)", i + 1, f0, f1);
                    DCTunwindLevels(ckt, job, i, vcode, icode, rcode);
                    return(E_PARMVAL);
                }
                mul = pow(per, 1.0 / job->TRCVnPts[i]);
                for (x = f0; x <= f1 * (1 + 1e-9); x *= mul) {
                    if (++nv > 100000) {
                        SPfrontEnd->IFerrorf(ERR_FATAL,
                            "DC sweep %d: too many points (> 100000); check "
                            "<N> and the start/stop range", i + 1);
                        DCTunwindLevels(ckt, job, i, vcode, icode, rcode);
                        return(E_PARMVAL);
                    }
                }
                job->TRCVratio[i] = mul;
                job->TRCVnTotal[i] = nv;   /* E-535: TRCVnPts stays as parsed */
            }
        }
    }

    /* Enhancement-535 (hunt N4): the same knob on BOTH nest levels fought
     * itself in silence -- the first point was computed with the OUTER level's
     * start while labeled with the inner's value (resolution applies inner
     * then outer), and the restore left the knob at the inner level's START,
     * because the outer level had captured that as its "nominal". The aliasing
     * is as old as the nested sweep (a duplicated vsrc behaves the same); the
     * @-parameter kinds just made it easy to reach. Refuse the overlap: same
     * element for the source/resistor/instance kinds (any spelling -- `v1`
     * and `@v1[dc]` are the same knob), same element AND parameter for the
     * parameter kinds, any shared target for the XPARAM lists. */
    if (job->TRCVnestLevel >= 1) {
        int clash = 0;
        if (job->TRCVvType[0] == job->TRCVvType[1]) {
            if (job->TRCVvType[0] == TEMP_CODE) {
                clash = 1;
            } else if (job->TRCVvType[0] == PARAM_CODE) {
                clash = (job->TRCVvElt[0] == job->TRCVvElt[1] &&
                         job->TRCVvParmId[0] == job->TRCVvParmId[1]);
            } else if (job->TRCVvType[0] != XPARAM_CODE) {
                clash = (job->TRCVvElt[0] == job->TRCVvElt[1]);
            }
        }
        /* cross-KIND aliasing: `v1` and `@v1[dc]` are the same knob (so are
         * `r2` and `@r2[resistance]`) -- a source/resistor level clashes with
         * a PARAM level on the same element when the parameter IS the
         * principal one that kind sweeps */
        if (!clash) {
            int a;
            for (a = 0; a < 2; a++) {
                int o = 1 - a;
                const char *principal = NULL;
                if (job->TRCVvType[o] != PARAM_CODE ||
                    job->TRCVvElt[a] != job->TRCVvElt[o])
                    continue;
                if (job->TRCVvType[a] == vcode || job->TRCVvType[a] == icode)
                    principal = "dc";
                else if (job->TRCVvType[a] == rcode)
                    principal = "resistance";
                if (principal && job->TRCVvElt[a]) {
                    IFdevice *dev = &DEVices[job->TRCVvElt[a]->GENmodPtr
                                                 ->GENmodType]->DEVpublic;
                    int k, n = dev->numInstanceParms ? *dev->numInstanceParms : 0;
                    for (k = 0; k < n; k++)
                        if (dev->instanceParms[k].id == job->TRCVvParmId[o] &&
                            dev->instanceParms[k].keyword &&
                            cieq(dev->instanceParms[k].keyword,
                                 (char *) principal)) {
                            clash = 1;
                            break;
                        }
                }
            }
        }
        if (job->TRCVvType[0] == XPARAM_CODE || job->TRCVvType[1] == XPARAM_CODE) {
            int a, b;
            for (a = 0; a < job->TRCVxN[0] && !clash; a++)
                for (b = 0; b < job->TRCVxN[1] && !clash; b++) {
                    DCTxtarget *ta = &job->TRCVxTarg[0][a];
                    DCTxtarget *tb = &job->TRCVxTarg[1][b];
                    if (ta->set_id == tb->set_id && ta->type == tb->type &&
                        ta->inst == tb->inst && ta->mod == tb->mod)
                        clash = 1;
                }
            /* an XPARAM level can also collide with a PARAM level's target */
            for (a = 0; a < 2 && !clash; a++) {
                int o = 1 - a;
                if (job->TRCVvType[a] == XPARAM_CODE &&
                    job->TRCVvType[o] == PARAM_CODE) {
                    for (b = 0; b < job->TRCVxN[a] && !clash; b++) {
                        DCTxtarget *t = &job->TRCVxTarg[a][b];
                        if (t->inst == job->TRCVvElt[o] &&
                            t->set_id == job->TRCVvParmId[o])
                            clash = 1;
                    }
                }
            }
            /* E-536 fix (hunt bug 9): a wildcard's INSTANCE targets can also
             * cover a SOURCE/RESISTOR level's element through its principal
             * parameter -- `dc v1 0.5 1.5 0.5 @#*[dc] 0 2 1` moved v1's dc
             * from both levels, passed the guard, and left v1 parked at the
             * sweep start. Same principal-keyword identity the cross-KIND
             * check above uses. */
            for (a = 0; a < 2 && !clash; a++) {
                int o = 1 - a;
                const char *principal = NULL;
                if (job->TRCVvType[a] != XPARAM_CODE || !job->TRCVvElt[o])
                    continue;
                if (job->TRCVvType[o] == vcode || job->TRCVvType[o] == icode)
                    principal = "dc";
                else if (job->TRCVvType[o] == rcode)
                    principal = "resistance";
                if (!principal)
                    continue;
                for (b = 0; b < job->TRCVxN[a] && !clash; b++) {
                    DCTxtarget *t = &job->TRCVxTarg[a][b];
                    IFdevice *dev;
                    int k, n;
                    if (t->inst != job->TRCVvElt[o])
                        continue;
                    dev = &DEVices[job->TRCVvElt[o]->GENmodPtr
                                       ->GENmodType]->DEVpublic;
                    n = dev->numInstanceParms ? *dev->numInstanceParms : 0;
                    for (k = 0; k < n; k++)
                        if (dev->instanceParms[k].id == t->set_id &&
                            dev->instanceParms[k].keyword &&
                            cieq(dev->instanceParms[k].keyword,
                                 (char *) principal)) {
                            clash = 1;
                            break;
                        }
                }
            }
        }
        if (clash) {
            SPfrontEnd->IFerrorf(ERR_FATAL,
                "DC sweep: \"%s\" and \"%s\" move the same knob -- the two "
                "levels would fight over one value, mislabel the first point "
                "and corrupt the restore. Sweep it once",
                job->TRCVvName[0] ? job->TRCVvName[0] : "?",
                job->TRCVvName[1] ? job->TRCVvName[1] : "?");
            /* undo what resolution already applied, in reverse
             * (E-536: the shared unwind every failure path now uses) */
            DCTunwindLevels(ckt, job, job->TRCVnestLevel, vcode, icode, rcode);
            return(E_PARMVAL);
        }
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
    else if (job->TRCVvType[0] == PARAM_CODE ||
             job->TRCVvType[0] == XPARAM_CODE)      /* Enhancement-534 */
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

        /* Enhancement-534: a counted (lin/dec/oct) level of ANY kind pops on
         * its index -- the value-overshoot tests below belong to the legacy
         * accumulate-by-step walk only (a descending lin would trip them). */
        if (job->TRCVscale[i] != DCT_SCALE_LEGACY) {
            if (job->TRCVidx[i] >= job->TRCVnTotal[i]) {
                i++;
                firstTime = 1;
                ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCTRANCURVE | MODEINITJCT;
                if (i > job->TRCVnestLevel)
                    break;
                goto nextstep;
            }
        } else if (job->TRCVvType[i] == vcode) { /* voltage source */
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
        } else if (job->TRCVvType[i] == PARAM_CODE ||
                   job->TRCVvType[i] == XPARAM_CODE) { /* @...[param] sweep */
            if (SGN(job->TRCVvStep[i]) *
                (job->TRCVvNow[i] - job->TRCVvStop[i]) >
                dct_over_slack(job, i))
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
            if (job->TRCVscale[i] != DCT_SCALE_LEGACY) {
                /* Enhancement-534: rewind a counted level to its first point */
                job->TRCVidx[i] = 0;
                if (DCTapplyLevel(ckt, job, i, job->TRCVvStart[i], 1,
                                  vcode, icode, rcode) != OK) {
                    dct_rejected_val = job->TRCVvStart[i];
                    dct_rejected_lvl = i;
                    dct_rejected_topo = dct_topology_refusal;
                    dctrc = E_PARMVAL;
                    goto osdi_finish;
                }
            } else if (job->TRCVvType[i] == vcode) { /* voltage source */
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
                if (DCTsetInstParam(ckt, job, i, job->TRCVvStart[i], 1) != OK)
                    return dct_topology_refusal
                        ? E_PARMVAL       /* Enhancement-495 already said why */
                        : DCTrejected(job, i, job->TRCVvStart[i]);
            } else if (job->TRCVvType[i] == XPARAM_CODE) {
                /* Enhancement-534 */
                if (DCTsetXParam(ckt, job, i, job->TRCVvStart[i], 1) != OK)
                    return dct_topology_refusal
                        ? E_PARMVAL
                        : DCTrejected(job, i, job->TRCVvStart[i]);
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
        else if (job->TRCVvType[0] == XPARAM_CODE)   /* Enhancement-534 */
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

#ifdef OSDI
        /* LRM 9.4.6/9.5.9: this sweep point converged -- flush the deferred
           Verilog-A display/file output of its final iteration (each point of
           a .dc sweep is an accepted solution; Table 4-22 treats every point
           as its own operating point). */
        OSDIpendingFlush(ckt);
#endif

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

        if (job->TRCVscale[i] != DCT_SCALE_LEGACY) {
            /* Enhancement-534: a counted level advances by index; the value
             * comes from the generator (lin interpolation / dec-oct multiply).
             * Past the last point nothing is applied -- the loop top pops. A
             * mid-sweep refusal (a parameter kind saying no, or the E-495
             * topology guard) aborts through the restore path, exactly as the
             * legacy PARAM arm does. */
            job->TRCVidx[i]++;
            if (job->TRCVidx[i] < job->TRCVnTotal[i]) {
                double next_ = dct_scale_value(job, i);
                if (DCTapplyLevel(ckt, job, i, next_, 1,
                                  vcode, icode, rcode) != OK) {
                    dct_rejected_val = next_;
                    dct_rejected_lvl = i;
                    dct_rejected_topo = dct_topology_refusal;
                    dctrc = E_PARMVAL;
                    goto osdi_finish;
                }
            }
        } else if (job->TRCVvType[i] == vcode) { /* voltage source */
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
                    > dct_over_slack(job, i)) {
                job->TRCVvNow[i] = next_;      /* advance; the point is dropped */
            } else if (DCTsetInstParam(ckt, job, i, next_, 1) != OK) {
                dct_rejected_val = next_;
                dct_rejected_lvl = i;
                /* Enhancement-495: the restore below clears the flag, so keep
                 * what caused THIS refusal before it goes. */
                dct_rejected_topo = dct_topology_refusal;
                dctrc = E_PARMVAL;
                goto osdi_finish;   /* abort THROUGH the restore path */
            }
        } else if (job->TRCVvType[i] == XPARAM_CODE) { /* Enhancement-534 */
            double next_ = job->TRCVvNow[i] + job->TRCVvStep[i];
            /* the same drop-before-set overshoot rule as the PARAM arm:
             * a sweep ending at the edge of a `from` range must not probe
             * one step outside it */
            if (SGN(job->TRCVvStep[i]) * (next_ - job->TRCVvStop[i])
                    > dct_over_slack(job, i)) {
                job->TRCVvNow[i] = next_;      /* advance; the point is dropped */
            } else if (DCTsetXParam(ckt, job, i, next_, 1) != OK) {
                dct_rejected_val = next_;
                dct_rejected_lvl = i;
                dct_rejected_topo = dct_topology_refusal;
                dctrc = E_PARMVAL;
                goto osdi_finish;
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
            if (job->TRCVscale[i] != DCT_SCALE_LEGACY) {   /* Enhancement-534 */
                if (job->TRCVnTotal[i] > 0)
                    SetAnalyse("dc",
                        (int) (1000.0 * job->TRCVidx[i] / job->TRCVnTotal[i]));
            } else {
                actval += job->TRCVvStep[job->TRCVnestLevel];
                SetAnalyse("dc", abs((int)((actval - job->TRCVvStart[job->TRCVnestLevel]) * 1000. / actdiff)));
            }
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
            (void) DCTsetInstParam(ckt, job, i, job->TRCVvSave[i], 0);
        } else if (job->TRCVvType[i] == XPARAM_CODE) {
            /* Enhancement-534: every target's own nominal back, unchecked */
            DCTrestoreXParam(ckt, job, i);
        }

#ifdef OSDI
    /* Enhancement-53: fire `@(final_step)` blocks at the last sweep point
       (results are not loaded into the matrix). */
    OSDIfinalStep(ckt);
#endif
    SPfrontEnd->OUTendPlot (plot);

    if (dct_rejected_lvl >= 0 && !dct_rejected_topo)
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
