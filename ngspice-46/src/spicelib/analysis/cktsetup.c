/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

    /* CKTsetup(ckt)
     * this is a driver program to iterate through all the various
     * setup functions provided for the circuit elements in the
     * given circuit
     */

#include "ngspice/ngspice.h"
#include "ngspice/smpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/fteext.h"

#ifdef XSPICE
#include "ngspice/enh.h"
#endif

#ifdef USE_OMP
#include <omp.h>
#include "ngspice/cpextern.h"
#endif

#define CKALLOC(var,size,type) \
    if(size && ((var = TMALLOC(type, size)) == NULL)){\
            return(E_NOMEM);\
}

/* Enhancement-266: announce the active direct linear solver once, and again
 * only when it changes.  CKTsetup (and CKTpzSetup) run once per analysis, so a
 * command that re-runs the analysis for many points -- `sweep`, Monte Carlo,
 * `optimize`, the pso/de/sa optimizers -- otherwise reprints
 * "Using ... Direct Linear Solver" on every iteration.  The last-announced
 * solver is tracked process-wide (not per-circuit): a `.param` sweep re-sources
 * the deck, rebuilding the circuit each point, so a per-circuit flag would still
 * repeat.  A genuine solver switch (`.option klu` / `.option sparse`) has a
 * different mode and re-announces.  A fresh ngspice process starts un-announced,
 * so batch runs and the dual-solver test harness still print it once. */
void
CKTannounceSolver(int klu)
{
    static int announced = -1;      /* -1 = none yet, 0 = SPARSE, 1 = KLU */
    int mode = klu ? 1 : 0;

    if (announced == mode)
        return;
    announced = mode;
    fprintf(stdout, klu ? "Using KLU as Direct Linear Solver\n"
                        : "Using SPARSE 1.3 as Direct Linear Solver\n");
}

int
CKTsetup(CKTcircuit *ckt)
{
    int i;
    int error;
#ifdef USE_OMP
    int nthreads = 2;
#endif
#ifdef XSPICE
 /* gtri - begin - Setup for adding rshunt option resistors */
    CKTnode *node;
    int     num_nodes;
 /* gtri - end - Setup for adding rshunt option resistors */

#ifdef KLU
    BindElement BindNode, *matched, *BindStruct ;
    size_t nz ;
#endif
#endif

    SMPmatrix *matrix;

    if (!ckt->CKThead) {
        fprintf(stderr, "Error: No model list found, device setup not possible!\n");
        if (ft_stricterror)
            controlled_exit(EXIT_BAD);
        return E_PANIC;
    }
    if (!DEVices) {
        fprintf(stderr, "Error: No device list found, device setup not possible!\n");
        if (ft_stricterror)
            controlled_exit(EXIT_BAD);
        return E_PANIC;
    }

    ckt->CKTnumStates=0;

#ifdef WANT_SENSE2
    if(ckt->CKTsenInfo){
        error = CKTsenSetup(ckt);
        if (error)
            return(error);
    }
#endif

    if (ckt->CKTisSetup)
        return E_NOCHANGE;

    error = NIinit(ckt);
    if (error) 
        return(error);

    ckt->CKTisSetup = 1;
    ckt->CKTbindStale = 0;  /* Enhancement-365: bindings are current again */

    matrix = ckt->CKTmatrix;

#ifdef USE_OMP
    if (!cp_getvar("num_threads", CP_NUM, &nthreads, 0))
        nthreads = 2;

    omp_set_num_threads(nthreads);
/*    if (nthreads == 1)
      printf("OpenMP: %d thread is requested in ngspice\n", nthreads);
    else
      printf("OpenMP: %d threads are requested in ngspice\n", nthreads);*/
#endif

#ifdef HAS_PROGREP
    SetAnalyse("Device Setup", 0);
#endif

    /* preserve CKTlastNode before invoking DEVsetup()
     * so we can check for incomplete CKTdltNNum() invocations
     * during DEVunsetup() causing an erronous circuit matrix
     *   when reinvoking CKTsetup()
     */
    ckt->prev_CKTlastNode = ckt->CKTlastNode;

    for (i=0;i<DEVmaxnum;i++) {
        if ( DEVices[i] && DEVices[i]->DEVsetup && ckt->CKThead[i] ) {
            error = DEVices[i]->DEVsetup (matrix, ckt->CKThead[i], ckt,
                    &ckt->CKTnumStates);
            if(error) return(error);
        }
    }

#ifdef XSPICE
  /* gtri - begin - Setup for adding rshunt option resistors */

    if(ckt->enh->rshunt_data.enabled) {

        /* Count number of voltage nodes in circuit */
        for(num_nodes = 0, node = ckt->CKTnodes; node; node = node->next)
            if((node->type == SP_VOLTAGE) && (node->number != 0))
                num_nodes++;

        /* Allocate space for the matrix diagonal data */
        if(num_nodes > 0) {
            FREE(ckt->enh->rshunt_data.diag);
            ckt->enh->rshunt_data.diag =
                 TMALLOC(double *, num_nodes);
        }

        /* Set the number of nodes in the rshunt data */
        ckt->enh->rshunt_data.num_nodes = num_nodes;

        /* Get/create matrix diagonal entry following what RESsetup does */
        for(i = 0, node = ckt->CKTnodes; node; node = node->next) {
            if((node->type == SP_VOLTAGE) && (node->number != 0)) {
                ckt->enh->rshunt_data.diag[i] =
                      SMPmakeElt(matrix,node->number,node->number);
                i++;
            }
        }
    }

    /* gtri - end - Setup for adding rshunt option resistors */
#endif

    /* F1/F2/F8 (2026-09-06): make the matrix agree with the node numbering.
     *
     * The matrix is created empty (NIinit) and grows only as devices stamp
     * it, so its size was the largest node index that carried an entry, not
     * the number of unknowns.  A node nothing conducts to -- fed only by a
     * current source, or the output of a controlled current source -- was
     * therefore either an empty column in the middle (which KLU's COO->CSC
     * conversion "collapsed", mis-addressing every other node's RHS) or,
     * numbered last, outside the matrix altogether: NIreinit sized the RHS
     * vectors one short, the device load wrote past them, and both solvers
     * printed the injected current as the node's voltage.
     *
     * Two things fix that at the one place where the count is final:
     *  - every node that owns no matrix entry at all gets a zero diagonal
     *    element, so it is a real (singular) column that gmin stepping can
     *    hold up -- the same thing Sparse already did for such a node once a
     *    .nodeset had created its diagonal -- and the user is told;
     *  - a node with a .nodeset/.ic gets its diagonal here too, so CKTic finds
     *    it under KLU instead of aborting the whole run as "out of memory"
     *    (nodes held only by inductor or voltage-source branches have none);
     *  - the solver is told the true size, so a trailing node is inside the
     *    matrix and the RHS vectors cover the numbering. */
    {
        int nunk = ckt->CKTmaxEqNum - 1;
        if (nunk > 0) {
            unsigned char *occupied = TMALLOC(unsigned char, (size_t) nunk + 2);
            CKTnode *nd;
            int nfloat = 0, anyoccupied = 0, k;
            memset(occupied, 0, (size_t) nunk + 2);
            SMPmarkOccupied(matrix, occupied, nunk);
            for (k = 1; k <= nunk; k++)
                anyoccupied |= occupied[k];
            /* A circuit with NO matrix at all (nothing conducts anywhere -- an
             * XSPICE digital-only deck, or a current source into a lone node)
             * keeps Enhancement-492's single "no matrix to solve" note rather
             * than one warning per node; only a floating node in an otherwise
             * connected circuit gets a diagonal here. */
            for (nd = ckt->CKTnodes; nd && anyoccupied; nd = nd->next) {
                if (nd->number <= 0 || nd->number > nunk)
                    continue;
                if (!occupied[nd->number]) {
                    if (nfloat < 5)
                        fprintf(stderr, "Warning: node '%s' is connected to nothing that conducts; "
                                "it is held only by gmin\n", CKTnodName(ckt, nd->number));
                    nfloat++;
                    SMPmakeElt(matrix, nd->number, nd->number);
                } else if (nd->nsGiven || nd->icGiven) {
                    SMPmakeElt(matrix, nd->number, nd->number);
                }
            }
            if (nfloat > 5)
                fprintf(stderr, "Warning: ... and %d more nodes like that\n", nfloat - 5);
            FREE(occupied);
        }
        SMPsizeHint(matrix, nunk);
    }

#ifdef KLU
    if (ckt->CKTmatrix->CKTkluMODE)
    {
        CKTannounceSolver (1) ;

        /* Convert the COO Storage to CSC for KLU and Fill the Binding Table */
        SMPconvertCOOtoCSC (matrix) ;

        /* Assign the KLU Pointers */
        for (i = 0 ; i < DEVmaxnum ; i++)
            if (DEVices [i] && DEVices [i]->DEVbindCSC && ckt->CKThead [i])
                DEVices [i]->DEVbindCSC (ckt->CKThead [i], ckt) ;

#ifdef XSPICE
        if (ckt->enh->rshunt_data.num_nodes > 0) {
            BindStruct = ckt->CKTmatrix->SMPkluMatrix->KLUmatrixBindStructCOO ;
            nz = (size_t)ckt->CKTmatrix->SMPkluMatrix->KLUmatrixLinkedListNZ ;
            for(i = 0, node = ckt->CKTnodes; node; node = node->next) {
                if((node->type == SP_VOLTAGE) && (node->number != 0)) {
                    BindNode.COO = ckt->enh->rshunt_data.diag [i] ;
                    BindNode.CSC = NULL ;
                    BindNode.CSC_Complex = NULL ;
                    matched = (BindElement *) bsearch (&BindNode, BindStruct, nz, sizeof (BindElement), BindCompare) ;
                    if (!matched) {
                        fprintf (stderr, "Error: Ptr %p not found in BindStruct Table\n", ckt->enh->rshunt_data.diag [i]) ;
                        ckt->enh->rshunt_data.diag[i] = NULL;
                    }
                    else
                        ckt->enh->rshunt_data.diag [i] = matched->CSC ;
                    i++;
                }
            }
        }
#endif

    } else {
        CKTannounceSolver (0) ;
    }
#endif

    for(i=0;i<=MAX(2,ckt->CKTmaxOrder)+1;i++) { /* dctran needs 3 states as minimum */
        CKALLOC(ckt->CKTstates[i],ckt->CKTnumStates,double);
    }
#ifdef WANT_SENSE2
    if(ckt->CKTsenInfo){
        /* to allocate memory to sensitivity structures if
         * it is not done before */

        error = NIsenReinit(ckt);
        if(error) return(error);
    }
#endif
    if(ckt->CKTniState & NIUNINITIALIZED) {
        error = NIreinit(ckt);
        if(error) return(error);
    }

    return(OK);
}

int
CKTunsetup(CKTcircuit *ckt)
{
    int i, error, e2;
    CKTnode *node;

    error = OK;
    if (!ckt->CKTisSetup)
        return OK;

    for(i=0;i<=ckt->CKTmaxOrder+1;i++) {
        tfree(ckt->CKTstates[i]);
    }

    /* added by HT 050802*/
    for(node=ckt->CKTnodes;node;node=node->next){
        if(node->icGiven || node->nsGiven) {
            node->ptr=NULL;
        }
    }

    for (i=0;i<DEVmaxnum;i++) {
        if ( DEVices[i] && DEVices[i]->DEVunsetup && ckt->CKThead[i] ) {
            e2 = DEVices[i]->DEVunsetup (ckt->CKThead[i], ckt);
            if (!error && e2)
                error = e2;
        }
    }

    if (ckt->prev_CKTlastNode != ckt->CKTlastNode) {
        fprintf(stderr, "Internal Error: incomplete CKTunsetup(), this will cause serious problems, please report this issue !\n");
        controlled_exit(EXIT_FAILURE);
    }
    ckt->prev_CKTlastNode = NULL;

    ckt->CKTisSetup = 0;
    if(error) return(error);

    NIdestroy(ckt);
    /*
    if (ckt->CKTmatrix)
        SMPdestroy(ckt->CKTmatrix);
    ckt->CKTmatrix = NULL;
    */

    return OK;
}
