/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
**********/

/* CKTpzSetup(ckt)
 * iterate through all the various
 * pzSetup functions provided for the circuit elements in the
 * given circuit, setup ...
 */

#include "ngspice/ngspice.h"
#include "ngspice/smpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/sperror.h"

int
CKTpzSetup(CKTcircuit *ckt, int type)
{
    PZAN *job = (PZAN *) ckt->CKTcurJob;

    SMPmatrix *matrix;
    int error;
    int i, solution_col, balance_col;
    int input_pos, input_neg, output_pos, output_neg;

    /* Enhancement-365: this destroys the matrix that CKTsetup bound every
     * device's element pointers into, and builds a different one. Those
     * pointers are now dangling for anything that runs after `pz`, yet
     * CKTisSetup still claims a valid setup -- so a consumer that trusts it
     * (com_hb did) loads the circuit through freed memory. Record the fact. */
    NIdestroy(ckt);
    ckt->CKTbindStale = 1;
    error = NIinit(ckt);
    if (error)
	return(error);
    matrix = ckt->CKTmatrix;

    /* Really awful . . . */
    ckt->CKTnumStates = 0;

    for (i = 0; i < DEVmaxnum; i++) {
        if (DEVices[i] && DEVices[i]->DEVpzSetup != NULL && ckt->CKThead[i] != NULL) {
            error = DEVices[i]->DEVpzSetup (matrix, ckt->CKThead[i],
		ckt, &ckt->CKTnumStates);
            if (error != OK)
	        return(error);
        }
    }

    solution_col = 0;
    balance_col = 0;

    input_pos = job->PZin_pos;
    input_neg = job->PZin_neg;

    if (type == PZ_DO_ZEROS) {
	/* Vo/Ii in Y */
	output_pos = job->PZout_pos;
	output_neg = job->PZout_neg;
    } else if (job->PZinput_type == PZ_IN_VOL) {
	/* Vi/Ii in Y */
	output_pos = job->PZin_pos;
	output_neg = job->PZin_neg;
    } else {
	/* Denominator */
	output_pos = 0;
	output_neg = 0;
	input_pos = 0;
	input_neg = 0;
    }

    if (output_pos) {
	solution_col = output_pos;
	if (output_neg)
	    balance_col = output_neg;
    } else {
	solution_col = output_neg;
	SWAP(int, input_pos, input_neg);
    }

    if (input_pos)
	job->PZdrive_pptr = SMPmakeElt(matrix, input_pos, solution_col);
    else
	job->PZdrive_pptr = NULL;

    if (input_neg)
	job->PZdrive_nptr = SMPmakeElt(matrix, input_neg, solution_col);
    else
	job->PZdrive_nptr = NULL;

    job->PZsolution_col = solution_col;
    job->PZbalance_col = balance_col;

    job->PZnumswaps = 1;

#ifdef KLU
    if (matrix->CKTkluMODE)
    {
        CKTannounceSolver (1) ;

        /* Balanced (differential) output: CKTpzLoad folds the solution column
         * into the balance column (SMPcAddCol) on every trial.  KLU's CSC
         * sparsity pattern is fixed at conversion time -- unlike Sparse, which
         * creates missing elements on the fly -- so reserve the union pattern
         * now: every row present in the solution column must also exist in the
         * balance column.  Duplicate (row, col) entries are folded into one CSC
         * slot by the COO->CSC conversion, so adding them blindly is safe. */
        if (balance_col && solution_col) {
            KluLinkedListCOO *node ;
            unsigned int *rows ;
            unsigned int nrows = 0, k ;

            rows = TMALLOC (unsigned int, matrix->SMPkluMatrix->KLUmatrixLinkedListNZ) ;
            for (node = matrix->SMPkluMatrix->KLUmatrixLinkedListCOO ; node ; node = node->next)
                if (node->col == (unsigned int) (solution_col - 1))
                    rows [nrows++] = node->row ;
            for (k = 0 ; k < nrows ; k++)
                SMPmakeElt (matrix, (int) rows [k] + 1, balance_col) ;
            tfree (rows) ;
        }

        /* Convert the COO Storage to CSC for KLU and Fill the Binding Table */
        SMPconvertCOOtoCSC (matrix) ;

        /* KLU Pointers Assignment */
        for (i = 0 ; i < DEVmaxnum ; i++)
            if (DEVices [i] && DEVices [i]->DEVbindCSC && ckt->CKThead [i])
                DEVices [i]->DEVbindCSC (ckt->CKThead [i], ckt) ;

        /* ReOrder */
        error = SMPpreOrder (matrix) ;
        if (error) {
            fprintf (stderr, "Error during ReOrdering\n") ;
        }

        /* Conversion from Real Circuit Matrix to Complex Circuit Matrix */
        for (i = 0 ; i < DEVmaxnum ; i++)
            if (DEVices [i] && DEVices [i]->DEVbindCSCComplex && ckt->CKThead [i])
                DEVices [i]->DEVbindCSCComplex (ckt->CKThead [i], ckt) ;

        matrix->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex ;

        /* Input Pos */
        if ((input_pos > 0) && (solution_col > 0))
        {
            BindElement j, *matched ;

            j.COO = job->PZdrive_pptr ;
            j.CSC = NULL ;
            j.CSC_Complex = NULL ;
            matched = (BindElement *) bsearch (&j, matrix->SMPkluMatrix->KLUmatrixBindStructCOO,
                      matrix->SMPkluMatrix->KLUmatrixLinkedListNZ, sizeof (BindElement), BindCompare) ;
            /* Enhancement-212: guard the bsearch miss instead of dereferencing
             * NULL (matching cktsetup.c). Unreachable today -- PZdrive_pptr was
             * just created by SMPmakeElt and is always in the bind table -- but
             * the former code printed the "not found" diagnostic and then
             * dereferenced matched anyway. */
            if (matched == NULL) {
                fprintf (stderr, "Error: Ptr %p not found in BindStruct Table\n", job->PZdrive_pptr) ;
                job->PZdrive_pptr = NULL ;
            } else {
                job->PZdrive_pptr = matched->CSC_Complex ;
            }
        }

        /* Input Neg */
        if ((input_neg > 0) && (solution_col > 0))
        {
            BindElement j, *matched ;

            j.COO = job->PZdrive_nptr ;
            j.CSC = NULL ;
            j.CSC_Complex = NULL ;
            matched = (BindElement *) bsearch (&j, matrix->SMPkluMatrix->KLUmatrixBindStructCOO,
                      matrix->SMPkluMatrix->KLUmatrixLinkedListNZ, sizeof (BindElement), BindCompare) ;
            /* Enhancement-212: see the PZdrive_pptr guard above. */
            if (matched == NULL) {
                fprintf (stderr, "Error: Ptr %p not found in BindStruct Table\n", job->PZdrive_nptr) ;
                job->PZdrive_nptr = NULL ;
            } else {
                job->PZdrive_nptr = matched->CSC_Complex ;
            }
        }
    } else {
        CKTannounceSolver (0) ;
    }
#endif

    error = NIreinit(ckt);
    if (error)
	return(error);

    return OK;
}

