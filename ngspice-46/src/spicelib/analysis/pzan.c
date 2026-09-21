/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/complex.h"
#include "ngspice/cktdefs.h"
#include "ngspice/inpdefs.h"      /* Enhancement-690: CKTnodePhantom */
#include "ngspice/smpdefs.h"
#include "ngspice/pzdefs.h"
#include "ngspice/trandefs.h"   /* only to get the 'mode' definitions */
#include "ngspice/sperror.h"
#ifdef OSDI
#include "ngspice/osdiitf.h"   /* Enhancement-683: OSDIfinalStep */
#endif


#define DEBUG	if (0)

/* ARGSUSED */
int
PZan(CKTcircuit *ckt, int reset)
{
    PZAN *job = (PZAN *) ckt->CKTcurJob;

    int error;
    int numNames;
    IFuid *nameList;
    runDesc *plot = NULL;

    NG_IGNORE(reset);

    /* Pole-zero runs fully under both solvers.  Under KLU this took three
     * fixes: the complex-pivot determinant formula and the PivRel=0.0 pivot
     * tolerance in the KLU<->SMP bridge (which had made every complex-plane
     * determinant evaluation garbage and the s=0 trial spuriously singular),
     * and a KLU branch for SMPcAddCol plus a union-pattern reservation in
     * CKTpzSetup so the balanced/differential-output column fold works on
     * KLU's fixed CSC sparsity pattern. */

    error = PZinit(ckt);
    if (error != OK) return error;

    /* Enhancement-690 (hunt F8): a `.pz` card, or a `pz` command typed before
     * the first setup naming a device's internal node, invents that node
     * before CKTsetup; a name no device adopted is a phantom (E-429's rule,
     * as tfanal.c and noisean.c apply it) and the run is refused rather than
     * computed against a node nothing connects to. */
    {
        static const char *const which[4] = { "input", "input", "output", "output" };
        const int nums[4] = { job->PZin_pos, job->PZin_neg, job->PZout_pos, job->PZout_neg };
        int k;
        for (k = 0; k < 4; k++) {
            CKTnode *nd = CKTnum2nod(ckt, nums[k]);
            if (CKTnodePhantom(nd)) {
                SPfrontEnd->IFerrorf(ERR_WARNING,
                                     "Pole-zero %s node %s does not exist "
                                     "(no device connects to it)", which[k],
                                     nd->name ? nd->name : "?");
                return E_NOTFOUND;
            }
        }
    }

    /* Calculate small signal parameters at the operating point */
    error = CKTop(ckt, (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITJCT,
            (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITFLOAT,
            ckt->CKTdcMaxIter);
    if (error)
	return(error);

    ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITSMSIG;
    error = CKTload(ckt); /* Make sure that all small signal params are
			       * set */
    if (error)
	return(error);

    if (ckt->CKTkeepOpInfo) {
	/* Dump operating point. */
	error = CKTnames(ckt,&numNames,&nameList);
	if(error) return(error);
        error = SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                                           "Distortion Operating Point",
                                           NULL, IF_REAL,
                                           numNames, nameList, IF_REAL,
                                           &plot);
	if(error) return(error);
	CKTdump(ckt, 0.0, plot);
	SPfrontEnd->OUTendPlot (plot);
    }

    if (job->PZwhich & PZ_DO_POLES) {
	error = CKTpzSetup(ckt, PZ_DO_POLES);
	if (error != OK)
	    return error;
        if (ckt->CKTpzEig)      /* Enhancement-173: .options pzeig */
            error = CKTpzEig(ckt, &job->PZpoleList, &job->PZnPoles);
        else
            error = CKTpzFindZeros(ckt, &job->PZpoleList, &job->PZnPoles);
        if (error != OK)
	    return(error);
    }

    if (job->PZwhich & PZ_DO_ZEROS) {
	error = CKTpzSetup(ckt, PZ_DO_ZEROS);
	if (error != OK)
	    return error;
        if (ckt->CKTpzEig)      /* Enhancement-173: .options pzeig */
            error = CKTpzEig(ckt, &job->PZzeroList, &job->PZnZeros);
        else
            error = CKTpzFindZeros(ckt, &job->PZzeroList, &job->PZnZeros);
	/* (An earlier KLU-specific E_SHORT remap lived here: the KLU zero
	 * search used to go spuriously singular.  Root causes fixed in the
	 * KLU<->SMP bridge -- the determinant's complex-pivot formula and the
	 * unsanitized PivRel=0.0 pivot tolerance -- so the finite-zero search
	 * now works under KLU and a genuine E_SHORT reports the same "input
	 * shorted" diagnostic as the Sparse solver.) */
        if (error != OK)
	    return(error);
    }

#ifdef OSDI
    /* Enhancement-683 (hunt F2 of 2026-09-21): the poles and zeros are found;
     * fire @(final_step) at the operating point, as the other analyses do. */
    OSDIfinalStep(ckt);
#endif
    return PZpost(ckt);
}

/*
 * Perform error checking
 */

int
PZinit(CKTcircuit *ckt)
{
    PZAN *job = (PZAN *) ckt->CKTcurJob;
    int	i;

    i = CKTtypelook("transmission line");
    if (i == -1) {
	    i = CKTtypelook("Tranline");
	    if (i == -1)
		i = CKTtypelook("LTRA");
    }
    if (i != -1 && ckt->CKThead[i] != NULL)
	MERROR(E_XMISSIONLINE, "Transmission lines not supported");

    job->PZpoleList = NULL;
    job->PZzeroList = NULL;
    job->PZnPoles = 0;
    job->PZnZeros = 0;

    if (job->PZin_pos == job->PZin_neg)
	MERROR(E_SHORT, "Input is shorted");

    if (job->PZout_pos == job->PZout_neg)
	MERROR(E_SHORT, "Output is shorted");

    if (job->PZin_pos == job->PZout_pos
        && job->PZin_neg == job->PZout_neg
	&& job->PZinput_type == PZ_IN_VOL)
	MERROR(E_INISOUT, "Transfer function is unity");
    else if (job->PZin_pos == job->PZout_neg
        && job->PZin_neg == job->PZout_pos
	&& job->PZinput_type == PZ_IN_VOL)
	MERROR(E_INISOUT, "Transfer function is -1");

    return(OK);
}

/*
 * PZpost  Post-processing of the pole-zero analysis results
 */

int
PZpost(CKTcircuit *ckt)
{
    PZAN	*job = (PZAN *) ckt->CKTcurJob;
    runDesc	*pzPlotPtr = NULL; /* the plot pointer for front end */
    IFcomplex	*out_list;
    IFvalue	outData;    /* output variable (points to out_list) */
    IFuid	*namelist;
    PZtrial	*root;
    char	name[50];
    int		i, j;

    namelist = TMALLOC(IFuid, job->PZnPoles + job->PZnZeros);
    out_list = TMALLOC(IFcomplex, job->PZnPoles + job->PZnZeros);

    j = 0;
    for (i = 0; i < job->PZnPoles; i++) {
	sprintf(name, "pole(%-u)", i+1);
	SPfrontEnd->IFnewUid (ckt, &(namelist[j++]), NULL, name, UID_OTHER, NULL);
    }
    for (i = 0; i < job->PZnZeros; i++) {
	sprintf(name, "zero(%-u)", i+1);
	SPfrontEnd->IFnewUid (ckt, &(namelist[j++]), NULL, name, UID_OTHER, NULL);
    }

    SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                               ckt->CKTcurJob->JOBname,
                               NULL, 0,
                               job->PZnPoles + job->PZnZeros, namelist, IF_COMPLEX,
                               &pzPlotPtr);

    j = 0;
    if (job->PZnPoles > 0) {
	for (root = job->PZpoleList; root != NULL; root = root->next) {
	    for (i = 0; i < root->multiplicity; i++) {
		out_list[j].real = root->s.real;
		out_list[j].imag = root->s.imag;
		j += 1;
		if (root->s.imag != 0.0) {
		    out_list[j].real = root->s.real;
		    out_list[j].imag = -root->s.imag;
		    j += 1;
		}
	    }
	    DEBUG printf("LIST pole: (%g,%g) x %d\n",
		root->s.real, root->s.imag, root->multiplicity);
	}
    }

    if (job->PZnZeros > 0) {
	for (root = job->PZzeroList; root != NULL; root = root->next) {
	    for (i = 0; i < root->multiplicity; i++) {
		out_list[j].real = root->s.real;
		out_list[j].imag = root->s.imag;
		j += 1;
		if (root->s.imag != 0.0) {
		    out_list[j].real = root->s.real;
		    out_list[j].imag = -root->s.imag;
		    j += 1;
		}
	    }
	    DEBUG printf("LIST zero: (%g,%g) x %d\n",
		root->s.real, root->s.imag, root->multiplicity);
	}
    }

    outData.v.numValue = job->PZnPoles + job->PZnZeros;
    outData.v.vec.cVec = out_list;

    SPfrontEnd->OUTpData (pzPlotPtr, NULL, &outData);
    SPfrontEnd->OUTendPlot (pzPlotPtr);

    return(OK);
}
