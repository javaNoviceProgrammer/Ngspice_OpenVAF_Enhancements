/**********
Copyright 1991 Regents of the University of California.  All rights reserved.
Modified: 2000 AlanFixes
**********/

#include "ngspice/ngspice.h"
#include "ngspice/fteext.h"
#include "ngspice/ifsim.h"
#include "ngspice/sperror.h"
#include "ngspice/spmatrix.h"
#include "ngspice/gendefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/sensdefs.h"
#include "ngspice/sensgen.h"
#include "ngspice/osdiitf.h"

/* #define ASDEBUG */
#ifdef ASDEBUG
#define DEBUG(X)	if ((X) < Sens_Debug)
static int Sens_Debug = 0;
#endif

static double Sens_Delta = 0.000001;
static double Sens_Abs_Delta = 0.000001;


/* Enhancement-468: replace a non-finite sensitivity with zero, once per name. */
static void
e468_undefined_sens(sgen *sg, double *rval, IFcomplex *cval)
{
    static char warned[128] = "";
    const char *pname = (sg && sg->ptable && sg->param >= 0)
                        ? sg->ptable[sg->param].keyword : "?";

    if (rval)
        *rval = 0.0;
    if (cval)
        cval->real = cval->imag = 0.0;

    if (pname && strcmp(pname, warned) != 0) {
        fprintf(stderr,
                "Warning: sens: the sensitivity to '%s' is not a number at this "
                "operating point (the parameter is inactive at its present "
                "value); reported as 0.\n", pname);
        strncpy(warned, pname, sizeof warned - 1);
        warned[sizeof warned - 1] = '\0';
    }
}

/* Enhancement-440: a model snapshot taken before the perturbation loop.
 *
 * `sens_setp` perturbs a parameter and then writes the original value back,
 * which restores the NUMBER but not the model's "given" state: every device
 * setter marks its parameter as supplied, and there is no un-set. For any
 * model whose behaviour is selected by whether a parameter was given -- rather
 * than by its value -- the model is left permanently reinterpreted.
 *
 * The BJT is the sharp case. `ibe`/`ibc` default to 0 and ungiven, and
 * bjttemp.c keys off `BJTBEsatCurGiven && BJTBCsatCurGiven`: ungiven, the
 * junction saturation currents fall back to `is`; given, they are taken
 * literally -- and `sens` had just made them given with the value 0. That
 * leaves BJTBEtSatCur = 0, i.e. a transistor with no saturation current at
 * all, so every later analysis in the session solves a dead device (measured
 * 12.8% wrong on a single stage, 101% on a differential pair, silently).
 *
 * Restoring the numeric value cannot fix this, because the damage is in the
 * given-bits, and no device API exposes them. Snapshotting the model structs
 * and putting them back does, generically, for every device type: parameters,
 * given-flags and cached model state all return to what the netlist set up.
 * Instances are NOT snapshotted -- their derived values are rebuilt by the
 * CKTtemp() that follows the restore.
 */
struct sens_modsave {
    GENmodel *model;
    void *copy;
    size_t size;
    struct sens_modsave *next;
};

static struct sens_modsave *
sens_save_models(CKTcircuit *ckt)
{
    struct sens_modsave *head = NULL;
    int type;

    for (type = 0; type < DEVmaxnum; type++) {
        GENmodel *m;

        if (!ckt->CKThead || !ckt->CKThead[type] || !DEVices[type] ||
                !DEVices[type]->DEVmodSize)
            continue;

        for (m = ckt->CKThead[type]; m; m = m->GENnextModel) {
            struct sens_modsave *s = TMALLOC(struct sens_modsave, 1);
            s->size = (size_t) *DEVices[type]->DEVmodSize;
            s->model = m;
            s->copy = tmalloc(s->size);
            memcpy(s->copy, m, s->size);
            s->next = head;
            head = s;
        }
    }

    return head;
}

/* Put the models back and rebuild every instance's derived values from them.
 * Safe to call with a NULL list. */
static void
sens_restore_models(CKTcircuit *ckt, struct sens_modsave *list)
{
    int restored = 0;

    while (list) {
        struct sens_modsave *next = list->next;

        if (memcmp(list->model, list->copy, list->size) != 0) {
            memcpy(list->model, list->copy, list->size);
            restored++;
        }
        FREE(list->copy);
        FREE(list);
        list = next;
    }

    /* Derived per-instance quantities (tSatCur and friends) were computed from
     * the altered models, so they have to be recomputed from the restored
     * ones. Only worth the pass if something actually changed. */
    if (restored)
        (void) CKTtemp(ckt);
}

static int sens_setp(sgen* sg, CKTcircuit* ckt, IFvalue* val);
static int sens_load(sgen* sg, CKTcircuit* ckt, int is_dc);
static int sens_temp(sgen* sg, CKTcircuit* ckt);
static int count_steps(int type, double low, double high, int steps, double* stepsize,
                       int* errp);
static double inc_freq(double freq, int type, double step_size);

char **Sens_filter;

/* Match a potential vector name against a filter string. */

static int scan(char *filter, char *name)
{
    while (*filter && *name) {
        if (*filter == '*') {
            if (!filter[1])
                return 1;       // Terminal '*' matches all.
            while (*name && !scan(filter + 1, name))
                ++name;
            return *name != '\0';
        }
        if (*filter == *name || *filter == '?')
            ++name, ++filter;
        else
            return 0;
    }

    /* Match if both strings exhausted. */

    return !*name && (!*filter || (*filter == '*' && !filter[1]));
}

static int check_filter(char *name)
{
    char **pp, *filter;

    for (pp = Sens_filter; (filter = *pp); pp++) {
        if (scan(filter, name))
            return 1;
    }
    return 0;
}

#define save_context(thing, place) {	    \
    place = thing;			    \
}

#define release_context(thing, place)	    \
    if(place) {				    \
    thing = place;			    \
    place = NULL;			    \
    }


/*
 *	Procedure:
 *
 *		Determine operating point (call CKTop)
 *
 *		For each frequency point:
 *			(for AC) call NIacIter to get base node voltages
 *			For each element/parameter in the test list:
 *				construct the perturbation matrix
 *				Solve for the sensitivities:
 *					delta_E = Y^-1 (delta_Y E - delta_I)
 *				save results
 */

static int	error;
int sens_sens(CKTcircuit* ckt, int restart)
{
    /*
    #ifdef KLU
        if (ckt->CKTkluMODE)
        {
            fprintf (stderr, "\n\n\tThe Sensitivity Analysis is not supported in KLU environment\n\tPlease add '.options sparse' in you netlist\n\n\n") ;
            return OK ;
        } else {
    #endif
    */
    SENS_AN* job = (SENS_AN*)ckt->CKTcurJob;

    static int	size;
    static double* delta_I, * delta_iI,
                 * delta_I_delta_Y, * delta_iI_delta_Y;
    sgen* sg;
    static double	freq;
    static int nfreqs;
    static int i;
    static SMPmatrix* delta_Y = NULL, * Y;
    static double step_size;
    double* E, * iE;
    IFvalue value, nvalue;
    double* output_values;
    IFcomplex* output_cvalues;
    double delta_var;
    struct sens_modsave *saved_models = NULL;   /* Enhancement-440 */
    void *mod_buf = NULL;                       /* per-parameter model snapshot */
    size_t mod_cap = 0, mod_size = 0;
    int    (*fn) (SMPmatrix*, GENmodel*, CKTcircuit*, int*);
    static int	is_dc;
    int k, j, n;
    int	num_vars, branch_eq = 0;
    runDesc* sen_data = NULL;
    IFuid *vec_names, *output_names, freq_name;
    int bypass;
    int type;
    double* saved_rhs = NULL,
          * saved_irhs = NULL;
    SMPmatrix* saved_matrix = NULL;

#ifdef KLU
    int size_CSC;
#endif

#ifndef notdef
#ifdef notdef
    for (sg = sgen_init(ckt, 0); sg; sgen_next(&sg)) {
        if (sg->is_instparam)
            printf("%s:%s:%s -> param %s\n",
                DEVices[sg->dev]->DEVpublic.name,
                sg->model->GENmodName,
                sg->instance->GENname,
                sg->ptable[sg->param].keyword);
        else
            printf("%s:%s:%s -> mparam %s\n",
                DEVices[sg->dev]->DEVpublic.name,
                sg->model->GENmodName,
                sg->instance->GENname,
                sg->ptable[sg->param].keyword);
    }
#endif
#ifdef ASDEBUG
    DEBUG(1)
        printf(">>> restart : %d\n", restart);
#endif

    /* get to work */

    restart = 1;
    if (restart) {

        freq = 0.0;
        is_dc = (job->step_type == SENS_DC);
        nfreqs = count_steps(job->step_type, job->start_freq,
            job->stop_freq, job->n_freq_steps,
            &step_size, &error);
        if (error)
            return error;

        if (!is_dc)
            freq = job->start_freq;

        error = CKTop(ckt,
            (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITJCT,
            (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITFLOAT,
            ckt->CKTdcMaxIter);

#ifdef notdef
        ckt->CKTmode = (ckt->CKTmode & MODEUIC)
            | MODEDCOP | MODEINITSMSIG;
#endif
        if (error)
            return error;

        size = SMPmatSize(ckt->CKTmatrix);

        /* Create the perturbation matrix */
        delta_Y = TMALLOC(SMPmatrix, 1);

        error = SMPnewMatrix(delta_Y, size);
        if (error)
            return error;

#ifdef KLU
        /* FIXME: needs better understanding what makes SMPkluMatrix NULL */
        if(delta_Y->SMPkluMatrix)
            delta_Y->SMPkluMatrix->KLUmatrixDiag = NULL;
#endif

        // SMPprint(delta_Y, NULL);
        size += 1;

        /* Create an extra rhs */
        delta_I = TMALLOC(double, size);
        delta_iI = TMALLOC(double, size);

        delta_I_delta_Y = TMALLOC(double, size);
        delta_iI_delta_Y = TMALLOC(double, size);

        num_vars = 0;
        for (sg = sgen_init(ckt, is_dc); sg; sgen_next(&sg)) {
            num_vars += 1;
        }

        if (!num_vars)
            return OK; /* XXXX Should be E_ something */

        output_names = TMALLOC(IFuid, num_vars);
        k = 0;
        num_vars = 0;
        for (sg = sgen_init(ckt, is_dc); sg; sgen_next(&sg)) {
            char namebuf[513];

            if (!sg->is_instparam) {
                snprintf(namebuf, sizeof namebuf, "%s:%s",
                         sg->instance->GENname,
                         sg->ptable[sg->param].keyword);
            }
            else if ((sg->ptable[sg->param].dataType
                & IF_PRINCIPAL) && sg->is_principle == 1)
            {
                snprintf(namebuf, sizeof namebuf, "%s", sg->instance->GENname);
            }
            else {
                snprintf(namebuf, sizeof namebuf, "%s_%s",
                         sg->instance->GENname,
                         sg->ptable[sg->param].keyword);
            }

            /* Check against the filter list. */

            if (!Sens_filter || check_filter(namebuf)) {
                num_vars++;
                SPfrontEnd->IFnewUid(ckt, output_names + k, NULL,
                                     namebuf, UID_OTHER, NULL);
            }
            k += 1;
        }
        if (num_vars == k) {
            vec_names = output_names;
        } else {
            if (!num_vars) {
                /* Enhancement-491: this returned OK having produced no plot and
                   said nothing.
                 
                   The trailing words on a `sens` line are FILTER patterns
                   naming which parameters to vary -- `sens v(b) r8` is a
                   legitimate restriction and works. When no pattern matches
                   anything, the analysis has nothing to compute, so it built no
                   plot, reported success, and left whatever plot was current in
                   place: a following `print` silently answered from the
                   PREVIOUS analysis. A mistyped or over-narrow filter was
                   indistinguishable from a filter that did its job.
                 
                   Say which patterns matched nothing. The run still ends
                   without a sensitivity plot -- there is nothing to put in one
                   -- but the reason is now on screen. */
                if (Sens_filter) {
                    char **pp;

                    fprintf(stderr,
                            "\nError: sens: no parameter of this circuit matches "
                            "the filter");
                    fprintf(stderr, "%s", Sens_filter[1] ? "s " : " ");
                    for (pp = Sens_filter; *pp; pp++)
                        fprintf(stderr, "%s'%s'", pp == Sens_filter ? "" : ", ",
                                *pp);
                    fprintf(stderr,
                            ",\n       so there is nothing to analyse and no "
                            "sensitivity plot is produced.\n"
                            "       A filter matches a parameter name as it "
                            "appears in the output:\n"
                            "       'r8' for the device's own value, 'r8:r' for "
                            "a model parameter,\n"
                            "       'r8_temp' for an instance parameter. Omit "
                            "the filter to vary them all.\n\n");
                } else {
                    fprintf(stderr,
                            "\nWarning: sens: this circuit has no parameter that "
                            "can be varied,\n         so no sensitivity plot is "
                            "produced.\n\n");
                }
                FREE(output_names);
                return OK;
            }

            /* Make a non-sparse array of names for OUTpBeginPlot(). */

            vec_names = TMALLOC(IFuid, num_vars);
            for (i = 0, j = 0; j < num_vars; ++i) {
                if (output_names[i])
                    vec_names[j++] = output_names[i];
            }
        }
        if (is_dc) {
            type = IF_REAL;
            freq_name = NULL;
        }
        else {
            type = IF_COMPLEX;
            SPfrontEnd->IFnewUid(ckt,
                &freq_name, NULL,
                "frequency", UID_OTHER, NULL);
        }

        error = SPfrontEnd->OUTpBeginPlot(ckt, ckt->CKTcurJob,
                                          ckt->CKTcurJob->JOBname,
                                          freq_name, IF_REAL,
                                          num_vars, vec_names,
                                          type, &sen_data);
        if (vec_names != output_names)
            FREE(vec_names);
        if (error) {
        err:
            /* Enhancement-440: the error paths leave through here too, and a
             * half-finished perturbation loop is exactly when the models are
             * most likely to be left altered. */
            sens_restore_models(ckt, saved_models);
            saved_models = NULL;
            FREE(mod_buf);
            FREE(output_names);
            return error;
        }
        if (is_dc) {
            output_values = TMALLOC(double, num_vars);
            output_cvalues = NULL;
        }
        else {
            output_values = NULL;
            output_cvalues = TMALLOC(IFcomplex, num_vars);
            if (job->step_type != SENS_LINEAR)
                SPfrontEnd->OUTattributes(sen_data, NULL, OUT_SCALE_LOG, NULL);

        }

    }
    else {
        /*XXX Restore saved state */
        output_values = NULL;
        output_cvalues = NULL;
        fprintf(stderr, "ERROR: restore is not implemented for cktsens\n");
        controlled_exit(1);
    }

#ifdef ASDEBUG
    DEBUG(1)
        printf("start: %f, num: %d, dc: %d\n", freq, nfreqs, is_dc);
#endif

    if (!job->output_volt)
        branch_eq = CKTfndBranch(ckt, job->output_src);
    bypass = ckt->CKTbypass;
    ckt->CKTbypass = 0;

    /* CKTop solves into CKTrhs and CKTmatrix->SPmatrix,
     *	 CKTirhs is hopefully zero (fresh allocated ?) */

    E = ckt->CKTrhs;
    iE = ckt->CKTirhs;
    Y = ckt->CKTmatrix;

#ifdef KLU
    if (ckt->CKTkluMODE) {

        /* Convert the KLU Circuit Matrix to Complex */
        for (i = 0; i < (int)Y->SMPkluMatrix->KLUmatrixNZ; i++) {
            Y->SMPkluMatrix->KLUmatrixAxComplex[2 * i] = Y->SMPkluMatrix->KLUmatrixAx[i];
            Y->SMPkluMatrix->KLUmatrixAxComplex[2 * i + 1] = 0.0;
        }

        Y->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex;

        SMPcReorder(Y, ckt->CKTpivotAbsTol, ckt->CKTpivotRelTol, &size_CSC); // size_CSC is just a placeholder here
    }
#endif

#ifdef ASDEBUG
    DEBUG(1) {
        printf("Operating point:\n");
        for (i = 0; i < size; i++)
            printf("          E [%d] = %20.15g\n", i, E[i]);
    }
#endif

#ifdef notdef
    for (j = 0; j <= ckt->CKTmaxOrder + 1; j++) {
        save_states[j] = ckt->CKTstates[j];
        ckt->CKTstates[j] = NULL;
    }
#endif

    /* Enhancement-440: snapshot the models before anything is perturbed. */
    saved_models = sens_save_models(ckt);

    for (i = 0; i < nfreqs; i++) {
        /* XXX handle restart */

        n = 0;

        if (SPfrontEnd->IFpauseTest()) {
            /* XXX Save State */
            error = E_PAUSE;
            goto err;
        }

        for (j = 0; j < size; j++) {
            delta_I[j] = 0.0;
            delta_iI[j] = 0.0;
        }

        if (freq != 0.0) {

            /* This generates Y in LU form */
            ckt->CKTomega = 2.0 * M_PI * freq;

            /* Yes, all this has to be re-done */
            /* XXX Free old states */
            error = CKTunsetup(ckt);
            if (error)
                goto err;

            /* XXX ckt->CKTmatrix->SPmatrix = Y; */

            error = CKTsetup(ckt);
            if (error)
                goto err;

#ifdef notdef
            for (j = 0; j <= ckt->CKTmaxOrder + 1; j++) {
                /* XXX Free new states */
                ckt->CKTstates[j] = save_states[j];
            }
#endif
            error = CKTtemp(ckt);
            if (error)
                goto err;
            error = CKTload(ckt); /* INITSMSIGS */
            if (error)
                goto err;

#ifdef KLU
            if (ckt->CKTmatrix->CKTkluMODE)
            {
                /* ReOrder */
                error = SMPpreOrder(ckt->CKTmatrix);

                /* Conversion from Real Circuit Matrix to Complex Circuit Matrix */
                if (!ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex)
                {
                    /* Enhancement-179: this loop used to reuse `i` -- the
                     * OUTER frequency-loop variable -- so after the first
                     * point `i` was DEVmaxnum and the AC sensitivity sweep
                     * silently stopped at ONE frequency under KLU. */
                    int di;
                    for (di = 0; di < DEVmaxnum; di++)
                        if (DEVices[di] && DEVices[di]->DEVbindCSCComplex && ckt->CKThead[di])
                            DEVices[di]->DEVbindCSCComplex(ckt->CKThead[di], ckt);

                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex;
                }
            }
#endif

            error = NIacIter(ckt);
            if (error)
                goto err;

#ifdef notdef
            /* XXX Why? */
            for (j = 0; j <= ckt->CKTmaxOrder + 1; j++) {
                ckt->CKTstates[j] = NULL;
            }
#endif

            /* NIacIter solves into CKTrhsOld, CKTirhsOld and CKTmatrix->SPmatrix */
            E = ckt->CKTrhsOld;
            iE = ckt->CKTirhsOld;
            Y = ckt->CKTmatrix;
        }

        /* Use a different vector & matrix */

        save_context(ckt->CKTrhs, saved_rhs);
        save_context(ckt->CKTirhs, saved_irhs);
        save_context(ckt->CKTmatrix, saved_matrix);

        ckt->CKTrhs = delta_I;
        ckt->CKTirhs = delta_iI;
        ckt->CKTmatrix = delta_Y;

        /* calc. effect of each param */

        k = 0;
        for (sg = sgen_init(ckt, is_dc /* job->plist */);
            sg; sgen_next(&sg))
        {
            if (!output_names[k++])
                continue;       // Ignore filtered parameters.
#ifdef ASDEBUG
            DEBUG(2) {
                printf("E/iE: %x/%x; delta_I/iI: %x/%x\n",
                    E, iE, delta_I, delta_iI);
                printf("cktrhs/irhs: %x/%x\n",
                    ckt->CKTrhs, ckt->CKTirhs);

                if (sg->is_instparam)
                    printf("%s:%s:%s -> param %s\n",
                        DEVices[sg->dev]->DEVpublic.name,
                        sg->model->GENmodName,
                        sg->instance->GENname,
                        sg->ptable[sg->param].keyword);
                else
                    printf("%s:%s:%s -> mparam %s\n",
                        DEVices[sg->dev]->DEVpublic.name,
                        sg->model->GENmodName,
                        sg->instance->GENname,
                        sg->ptable[sg->param].keyword);
            }
#endif

            SMPcClear(delta_Y);

            for (j = 0; j < size; j++) {
                delta_I[j] = 0.0;
                delta_iI[j] = 0.0;
            }

            /* ? should this just call CKTsetup
             * ? but then CKThead would have to get fiddled with */

            ckt->CKTnumStates = sg->istate;

            fn = DEVices[sg->dev]->DEVsetup;
            if (fn) {
                CKTnode* node = ckt->CKTlastNode;
                /* XXXX insert old state base here ?? */
                fn(delta_Y, sg->model, ckt, &ckt->CKTnumStates);
                if (node != ckt->CKTlastNode) {
                    fprintf(stderr, "Internal Error: node allocation in DEVsetup() during sensitivity analysis, this will cause serious troubles !, please report this issue !\n");
                    controlled_exit(EXIT_FAILURE);
                }
            }

#ifdef KLU
            /* delta_Y is a plain Sparse matrix (SMPnewMatrix leaves CKTkluMODE=0):
             * it is only multiplied (SMPmultiply -> spMultiply), never factored,
             * and DEVbindCSC always binds to ckt->CKTmatrix, not delta_Y -- so the
             * KLU-specific delta_Y setup below must NOT run when the *main* solver
             * is KLU. Gate on delta_Y's own flag (0) instead of the main matrix's,
             * so delta_Y behaves exactly as it does under the default Sparse solver. */
            if (delta_Y->CKTkluMODE)
            {
                /* Populate the delta_Y KLU Matrix */

                /* Convert the COO Storage to CSC for KLU and Fill the Binding Table */
                SMPconvertCOOtoCSC(delta_Y);

                /* KLU Pointers Assignment */
                if (DEVices[sg->dev]->DEVbindCSC)
                    DEVices[sg->dev]->DEVbindCSC(sg->model, ckt);

                delta_Y->SMPkluMatrix->KLUmatrixIsComplex = KLUmatrixReal;

                /* Clear KLU Vectors (local index: `i` is the outer
                 * frequency-loop variable -- see the E-179 fix above) */
                { int nzi;
                  for (nzi = 0; nzi < (int)delta_Y->SMPkluMatrix->KLUmatrixNZ; nzi++)
                  {
                    delta_Y->SMPkluMatrix->KLUmatrixAx[nzi] = 0;
                    delta_Y->SMPkluMatrix->KLUmatrixAxComplex[2 * nzi] = 0;
                    delta_Y->SMPkluMatrix->KLUmatrixAxComplex[2 * nzi + 1] = 0;
                  } }
            }
#endif

            /* ? CKTsetup would call NIreinit instead */
            ckt->CKTniState = NISHOULDREORDER | NIACSHOULDREORDER;

            /* XXX instead of calling temp here, just swap
             * back to the original states */
            (void)sens_temp(sg, ckt);

            /* XXX Leave original E until here!! so that temp reads
             * the right node voltages */

#ifdef KLU
            if (delta_Y->CKTkluMODE)   /* delta_Y is Sparse under KLU too -- see above */
            {
                if (!is_dc)
                {
                    if (DEVices[sg->dev]->DEVbindCSCComplex)
                        DEVices[sg->dev]->DEVbindCSCComplex(sg->model, ckt);

                    delta_Y->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex;
                }
            }
#endif
            if (sens_load(sg, ckt, is_dc)) {
                if (error && error != E_BADPARM)
                    goto err;
                continue;
            }

            /* Alter the parameter */

#ifdef ASDEBUG
            DEBUG(1) printf("Original value: %g\n", sg->value);
#endif

#ifdef ASDEBUG
            DEBUG(2) {
                printf("Effect of device:\n");
                SMPprint(delta_Y, NULL);
                printf("LHS:\n");
                for (j = 0; j < size; j++)
                    printf("%d: %g, %g\n", j,
                        delta_I[j], delta_iI[j]);
            }
#endif

            if (sg->value != 0.0)
                delta_var = sg->value * Sens_Delta;
            else
                delta_var = Sens_Abs_Delta;

            nvalue.rValue = sg->value + delta_var;

#ifdef ASDEBUG
            DEBUG(1)
                printf("New value: %g\n", nvalue.rValue);
#endif

            /* The device's own setter marks the parameter
             * GIVEN as a side effect, and writing the original value back does
             * not clear that flag. Where a model's defaults key off the flag
             * rather than off the value, the model's meaning changes for good:
             * once `ibe` and `ibc` have both been visited, bjttemp stops
             * falling back to `BJTtSatCur` and computes
             * BEtSatCur = area * BEsatCur * factor with BEsatCur back at 0, so
             * the transistor conducts nothing and EVERY parameter visited
             * after those two reports a sensitivity of exactly zero -- bf, nf
             * and vaf among them. Enhancement-440 already snapshots the
             * models, but only around the analysis as a whole, which protects
             * the session and not the rest of this loop. Snapshot the one
             * model being perturbed here and put it back byte for byte below,
             * so each parameter is measured against the model the user wrote. */
            mod_size = 0;
            if (DEVices[sg->dev]->DEVmodSize) {
                size_t mod_need = (size_t) *DEVices[sg->dev]->DEVmodSize;
                if (mod_need > mod_cap) {
                    mod_buf = TREALLOC(char, mod_buf, mod_need);
                    mod_cap = mod_need;
                }
                memcpy(mod_buf, sg->model, mod_need);
                mod_size = mod_need;
            }

            sens_setp(sg, ckt, &nvalue);
            if (error && error != E_BADPARM)
                goto err;

            SMPconstMult(delta_Y, -1.0);

            for (j = 0; j < size; j++) {
                delta_I[j] *= -1.0;
                delta_iI[j] *= -1.0;
            }

#ifdef ASDEBUG
            DEBUG(2) {
                printf("Effect of negating matrix:\n");
                SMPprint(delta_Y, NULL);
                for (j = 0; j < size; j++)
                    printf("%d: %g, %g\n", j,
                        delta_I[j], delta_iI[j]);
            }
#endif

            /* XXX swap back to temp states ??   Naw ... */
            (void)sens_temp(sg, ckt);

            /* Enhancement-417: if perturbing this parameter moved a Verilog-A
             * node collapse, the perturbed device stamps a topology the matrix
             * does not implement -- the collapsed pair still shares one matrix
             * element, so the branch's +g and -g land on the same diagonal and
             * cancel. What survives is the roundoff of that cancellation,
             * divided by the perturbation, which is `eps*E/(Y*delta^2)`: a
             * number with no relation to the derivative, and whose SIGN moves
             * with unrelated parameters.
             *
             * DEVsetup runs only at the base value (and must, since re-running
             * it here would allocate nodes and trip the CKTlastNode guard
             * above), so the mapping cannot be rebuilt. Report the parameter as
             * insensitive and say so, rather than print the roundoff. */
            if (OSDIcollapseChanged(sg->instance)) {
                fprintf(stderr,
                        "Warning: sens: %s:%s changes the model's node collapse "
                        "when perturbed, so its sensitivity cannot be computed "
                        "on the matrix built at setup; reported as 0.\n",
                        sg->instance->GENname, sg->ptable[sg->param].keyword);

                /* Put the parameter back, exactly as the normal path does. The
                 * restoring setup_instance re-decides the collapse a second
                 * time -- back to the setup value -- so clear the flag again
                 * afterwards or the NEXT parameter inherits it. */
                value.rValue = sg->value;
                sens_setp(sg, ckt, &value);
                if (mod_size) {                 /* undo the setter's side effects */
                    memcpy(sg->model, mod_buf, mod_size);
                    mod_size = 0;
                }
                (void)sens_temp(sg, ckt);
                (void)OSDIcollapseChanged(sg->instance);

                if (is_dc) {
                    output_values[n] = 0.0;
                } else {
                    output_cvalues[n].real = 0.0;
                    output_cvalues[n].imag = 0.0;
                }
                n += 1;         /* keep step with output_names[] */
                continue;
            }

#ifdef ASDEBUG
            DEBUG(1) {
                if (sens_getp(sg, ckt, &value)) {
                    continue;
                }

                printf("New value in device: %g\n",
                    value.rValue);
            }
#endif

            sens_load(sg, ckt, is_dc);

#ifdef ASDEBUG
            DEBUG(2) {
                printf("Effect of changing the parameter:\n");
                SMPprint(delta_Y, NULL);
                for (j = 0; j < size; j++)
                    printf("%d: %g, %g\n", j,
                        delta_I[j], delta_iI[j]);
            }
#endif
            /* Set the perturbed variable back to it's
             * original value
             */

            value.rValue = sg->value;
            sens_setp(sg, ckt, &value);
            if (mod_size) {                     /* undo the setter's side effects */
                memcpy(sg->model, mod_buf, mod_size);
                mod_size = 0;
            }
            (void)sens_temp(sg, ckt); /* XXX is this necessary? */

            /* Back to business . . . */

#ifdef ASDEBUG
            DEBUG(2)
                for (j = 0; j < size; j++)
                    printf("          E [%d] = %20.15g\n",
                        j, E[j]);
#endif

            /* delta_Y E */
//            fprintf(stderr, "\n\nPRIMA\n");
//            SMPprint(delta_Y, NULL);
            SMPmultiply(delta_Y, delta_I_delta_Y, E,
                delta_iI_delta_Y, iE);
//            fprintf(stderr, "\n\nDOPO\n");
//            SMPprint(delta_Y, NULL);

#ifdef ASDEBUG
            DEBUG(2)
                for (j = 0; j < size; j++)
                    printf("delta_Y * E [%d] = %20.15g\n",
                        j, delta_I_delta_Y[j]);
#endif

//                        fprintf (stderr, "\n\nPRIMA 1\n") ;
//                        for (j = 0 ; j < size ; j++)
//                        {
//                            fprintf (stderr, "RHS [%d]: %-.9g j%-.9g\n", j, delta_I [j], delta_iI [j]) ;
//                        }

            /* delta_I - delta_Y E */
            for (j = 0; j < size; j++) {
                delta_I[j] -= delta_I_delta_Y[j];
                delta_iI[j] -= delta_iI_delta_Y[j];
            }

//                        fprintf (stderr, "\n\nDOPO 1\n") ;
//                        for (j = 0 ; j < size ; j++)
//                        {
//                            fprintf (stderr, "RHS [%d]: %-.9g j%-.9g\n", j, delta_I [j], delta_iI [j]) ;
//                        }

#ifdef ASDEBUG
            DEBUG(2) {
                printf(">>> Y:\n");
                SMPprint(Y, NULL);
                for (j = 0; j < size; j++)
                    printf("%d: %g, %g\n", j,
                        delta_I[j], delta_iI[j]);
            }
#endif

//                        fprintf (stderr, "\n\nPRIMA\n") ;
//                        for (j = 0 ; j < size ; j++)
//                        {
//                            fprintf (stderr, "RHS [%d]: %-.14g j%-.14g\n", j, delta_I [j], delta_iI [j]) ;
//                        }

                        /* Solve; Y already factored */
            SMPcSolve(Y, delta_I, delta_iI, NULL, NULL);

//                        fprintf (stderr, "\n\nDOPO\n") ;
//                        for (j = 0 ; j < size ; j++)
//                        {
//                            fprintf (stderr, "RHS [%d]: %-.14g j%-.14g\n", j, delta_I [j], delta_iI [j]) ;
//                        }

            /* the special `0' node
            *    the matrix indizes are [1..n]
            *    yet the vector indizes are [0..n]
            *    with [0] being implicit === 0
            */
            delta_I[0] = 0.0;
            delta_iI[0] = 0.0;

#ifdef ASDEBUG
            DEBUG(2) {
                for (j = 1; j < size; j++) {

                    if (sg->is_instparam)
                        printf("%d/%s.%s = %g, %g\n",
                            j,
                            sg->instance->GENname,
                            sg->ptable[sg->param].keyword,
                            delta_I[j], delta_iI[j]);
                    else
                        printf("%d/%s:%s = %g, %g\n",
                            j,
                            sg->instance->GENname,
                            sg->ptable[sg->param].keyword,
                            delta_I[j], delta_iI[j]);

                }
            }
#endif

            /* delta_I is now equal to delta_E */

            if (is_dc) {
                if (job->output_volt) {
                    output_values[n] =
                        delta_I[job->output_pos->number]
                        - delta_I[job->output_neg->number];
//                                    fprintf (stderr, "Pos: %d\tNeg: %d\n", job->output_pos->number, job->output_neg->number) ;
                }
                else {
                    output_values[n] = delta_I[branch_eq];
                }
//                fprintf (stderr, "output_values real PRIMA: %-.14g\n", output_values [n]) ;
                output_values[n] /= delta_var;
//                fprintf(stderr, "output_values real DOPO: %-.14g - delta_var: %-.9g\n", output_values [n], delta_var);
            }
            else {
                if (job->output_volt) {
                    output_cvalues[n].real =
                        delta_I[job->output_pos->number]
                        - delta_I[job->output_neg->number];
                    output_cvalues[n].imag =
                        delta_iI[job->output_pos->number]
                        - delta_iI[job->output_neg->number];
                }
                else {
                    output_cvalues[n].real =
                        delta_I[branch_eq];
                    output_cvalues[n].imag =
                        delta_iI[branch_eq];
                }
//                                fprintf (stderr, "output_values complex: %-.9g j%-.9g\n", output_cvalues [n].real, output_cvalues [n].imag) ;
                output_cvalues[n].real /= delta_var;
                output_cvalues[n].imag /= delta_var;
            }
            /* Enhancement-468: never hand back a non-finite sensitivity.
             *
             * The engine perturbs every settable parameter by a relative step,
             * or by Sens_Abs_Delta when the value is zero. Zero is also how
             * several models spell "this effect is switched off", so the
             * perturbation can switch a branch ON with a degenerate parameter
             * and the resulting derivative is not a number: `sens v(mid)` on an
             * ordinary diode reported `d1:ikf = nan` for EVERY model that does
             * not set ikf -- that is, the default. It was the only non-finite
             * number produced across op, dc, ac, tran, noise, disto, tf and
             * sens, and across eight device types.
             *
             * A NaN here is worse than a missing number: it propagates through
             * any sum or plot the user builds from the table, and it reads as a
             * modelling result rather than an undefined derivative. Report zero
             * -- the parameter has no defined influence at this operating point
             * -- and say so once, naming the parameter, so the reader knows the
             * entry was not measured rather than measured as zero. */
            if (is_dc) {
                if (!finite(output_values[n]))
                    e468_undefined_sens(sg, &output_values[n], NULL);
            } else {
                if (!finite(output_cvalues[n].real) ||
                    !finite(output_cvalues[n].imag))
                    e468_undefined_sens(sg, NULL, &output_cvalues[n]);
            }

            n += 1;
        }

        release_context(ckt->CKTrhs, saved_rhs);
        release_context(ckt->CKTirhs, saved_irhs);
        release_context(ckt->CKTmatrix, saved_matrix);

        if (is_dc)
            nvalue.v.vec.rVec = output_values;
        else
            nvalue.v.vec.cVec = output_cvalues;

        value.rValue = freq;

        SPfrontEnd->OUTpData(sen_data, &value, &nvalue);

        freq = inc_freq(freq, job->step_type, step_size);

    }
    /* Enhancement-440: put the models back before returning to the shell, so
     * the next analysis in the session sees the circuit the netlist described. */
    sens_restore_models(ckt, saved_models);
    saved_models = NULL;

    FREE(output_names);

    SPfrontEnd->OUTendPlot(sen_data);

    if (is_dc) {
        FREE(output_values);	/* XXX free various vectors */
    }
    else {
        FREE(output_cvalues);	/* XXX free various vectors */
    }

    release_context(ckt->CKTrhs, saved_rhs);
    release_context(ckt->CKTirhs, saved_irhs);

    release_context(ckt->CKTmatrix, saved_matrix);

    SMPdestroy(delta_Y);
    FREE(delta_I);
    FREE(delta_iI);

    FREE(delta_I_delta_Y);
    FREE(delta_iI_delta_Y);

    ckt->CKTbypass = bypass;
    FREE(mod_buf);

#ifdef notdef
    for (j = 0; j <= ckt->CKTmaxOrder + 1; j++) {
        if (ckt->CKTstates[j])
            FREE(ckt->CKTstates[j]);
        ckt->CKTstates[j] = save_states[j];
    }
#endif
#endif

    return OK;
    /*
    #ifdef KLU
        }
    #endif
    */
}

double
inc_freq(double freq, int type, double step_size)
{
    if (type != LINEAR)
        freq *= step_size;
    else
        freq += step_size;

    return freq;
}
/*
static double
next_freq(int type, double freq, double stepsize)
{
    double	s=0;

    switch (type) {
    case SENS_DC:
        s = 0;
        break;

    case SENS_LINEAR:
        s = freq + stepsize;
        break;

    case SENS_DECADE:
    case SENS_OCTAVE:
        s = freq * stepsize;
        break;
    }
    return s;
}
*/
/* Enhancement-486: this function is declared to return a POINT COUNT, but
 * Enhancement-362's overflow guard signalled failure with `return(E_PARMVAL)`.
 * E_PARMVAL is 11, and the sole caller assigned the result straight to nfreqs
 * with no error test -- so an "impossible" sweep silently ran ELEVEN points.
 * Worse, that early return happened before `*stepsize = s`, so the step size was
 * never written and every frequency after the first collapsed to zero. An error
 * return that is indistinguishable from a valid answer is not a guard at all;
 * errors now travel out of band in *errp and the count stays a count.
 *
 * The two silent repairs were the other half. A DEC/OCT sweep starting at 0 Hz
 * had `low` rewritten to 1e-3, and a stop at or below the start had `high`
 * rewritten to a decade (or octave) above it. Both replaced a value the USER
 * STATED, and both wrote only the LOCAL copy: the count came from the repaired
 * bounds while the sweep itself still ran from job->start_freq, so with a start
 * of 0 `freq *= s` held every point at 0 Hz. `.sens ac dec 5 0 1meg` printed a
 * full table of 0 Hz rows, and `.sens ac dec 5 1k 1k` swept a full decade past
 * the stop that was asked for. .ac, .noise, .disto and .sp all get both cases
 * right, so the rules below are .ac's own (acan.c): refuse a logarithmic sweep
 * that starts at or below 0, treat stop == start as the single point .ac
 * produces, and let a LINEAR sweep start at 0 Hz, because there 0 Hz is a
 * legitimate DC point rather than log(0). */
int
count_steps(int type, double low, double high, int steps, double* stepsize,
            int* errp)
{
    double	s;
    int	n;

    if (errp)
        *errp = OK;

    if (steps < 1)
        steps = 1;

    /* A stop below the start never describes a sweep, whatever the type. */
    if (type != SENS_DC && high < low) {
        fprintf(stderr, "ERROR: SENS AC stop frequency %g is below the start "
                        "frequency %g\n", high, low);
        goto bad;
    }

    switch (type) {
    default:
    case SENS_DC:
        n = 0;
        s = 0;
        break;

    case SENS_LINEAR:
        if (high == low) {
            n = 1;              /* the single point .ac produces */
            s = 0.0;
        } else {
            n = steps;
            s = (high - low) / steps;
        }
        break;

    case SENS_DECADE:
        if (low <= 0.0) {
            fprintf(stderr, "ERROR: SENS AC startfreq <= 0\n");
            goto bad;
        }
        s = pow(10.0, 1.0 / steps);
        if (high == low) {
            n = 1;
        } else {
            double n_ = steps * log10(high / low) + 1.01;
            if (!(n_ == n_) || n_ < 1.0 || n_ > 2147483000.0) {
                fprintf(stderr, "ERROR: SENS AC number of points is not "
                                "representable\n");
                goto bad;
            }
            n = (int)n_;
        }
        break;

    case SENS_OCTAVE:
        if (low <= 0.0) {
            fprintf(stderr, "ERROR: SENS AC startfreq <= 0\n");
            goto bad;
        }
        s = pow(2.0, 1.0 / steps);
        if (high == low) {
            n = 1;
        } else {
            double n_ = steps * log(high / low) / M_LOG2E + 1.01;
            if (!(n_ == n_) || n_ < 1.0 || n_ > 2147483000.0) {
                fprintf(stderr, "ERROR: SENS AC number of points is not "
                                "representable\n");
                goto bad;
            }
            n = (int)n_;
        }
        break;
    }

    if (n <= 0)
        n = 1;

    *stepsize = s;
    return n;

bad:
    if (errp)
        *errp = E_PARMVAL;
    *stepsize = 0.0;            /* never leave the caller's step uninitialised */
    return 0;
}

static int
sens_load(sgen* sg, CKTcircuit* ckt, int is_dc)
{
//    fprintf (stderr, "LOAD - is_dc: %d\n", is_dc) ;
    int	(*fn) (GENmodel*, CKTcircuit*);

    error = 0;

    if (!is_dc)
        fn = DEVices[sg->dev]->DEVacLoad;
    else
        fn = DEVices[sg->dev]->DEVload;

    if (fn)
        error = fn(sg->model, ckt);
    else
        return 1;

    return error;
}


static int
sens_temp(sgen* sg, CKTcircuit* ckt)
{
    int	(*fn) (GENmodel*, CKTcircuit*);

    error = 0;

    fn = DEVices[sg->dev]->DEVtemperature;

    if (fn)
        error = fn(sg->model, ckt);
    else
        return 1;

    return error;
}

/* Get parameter value */
int
sens_getp(sgen* sg, CKTcircuit* ckt, IFvalue* val)
{
    int	pid;

    NG_IGNORE(ckt);

    error = 0;

    if (sg->is_instparam) {
        int (*fn) (CKTcircuit*, GENinstance*, int, IFvalue*, IFvalue*);
        fn = DEVices[sg->dev]->DEVask;
        pid = DEVices[sg->dev]->DEVpublic.instanceParms[sg->param].id;
        if (fn)
            error = fn(ckt, sg->instance, pid, val, NULL);
        else
            return 1;
    }
    else {
        int (*fn) (CKTcircuit*, GENmodel*, int, IFvalue*);
        fn = DEVices[sg->dev]->DEVmodAsk;
        pid = DEVices[sg->dev]->DEVpublic.modelParms[sg->param].id;
        if (fn)
            error = fn(ckt, sg->model, pid, val);
        else
            return 1;
    }

    if (error) {
        if (sg->is_instparam)
            printf("GET ERROR: %s:%s:%s -> param %s (%d)\n",
                DEVices[sg->dev]->DEVpublic.name,
                sg->model->GENmodName,
                sg->instance->GENname,
                sg->ptable[sg->param].keyword, pid);
        else
            printf("GET ERROR: %s:%s:%s -> mparam %s (%d)\n",
                DEVices[sg->dev]->DEVpublic.name,
                sg->model->GENmodName,
                sg->instance->GENname,
                sg->ptable[sg->param].keyword, pid);
    }

    return error;
}

/* Set parameter value */
int
sens_setp(sgen* sg, CKTcircuit* ckt, IFvalue* val)
{
    int	pid;

    NG_IGNORE(ckt);

    error = 0;

    if (sg->is_instparam) {
        int (*fn) (int, IFvalue*, GENinstance*, IFvalue*);
        fn = DEVices[sg->dev]->DEVparam;
        pid = DEVices[sg->dev]->DEVpublic.instanceParms[sg->param].id;
        if (fn)
            error = fn(pid, val, sg->instance, NULL);
        else
            return 1;
    }
    else {
        int (*fn) (int, IFvalue*, GENmodel*);
        fn = DEVices[sg->dev]->DEVmodParam;
        pid = DEVices[sg->dev]->DEVpublic.modelParms[sg->param].id;

        /* FIXME: just a preliminary hack.
         * Exclude bipolar parameter RCO, as it crashes ngspice
         * during sensitivity analysis due to missing node allocations */
        if (fn && !(sg->dev == 2 && pid == 147))
            error = fn(pid, val, sg->model);
        else
            return 1;
    }

    if (error) {
        if (sg->is_instparam)
            printf("SET ERROR: %s:%s:%s -> param %s (%d)\n",
                DEVices[sg->dev]->DEVpublic.name,
                sg->model->GENmodName,
                sg->instance->GENname,
                sg->ptable[sg->param].keyword, pid);
        else
            printf("SET ERROR: %s:%s:%s -> mparam %s (%d)\n",
                DEVices[sg->dev]->DEVpublic.name,
                sg->model->GENmodName,
                sg->instance->GENname,
                sg->ptable[sg->param].keyword, pid);
    }

    return error;
}
