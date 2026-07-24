/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/devdefs.h"


int
CKTic(CKTcircuit *ckt)
{
    int error;
    int size;
    int i;
    CKTnode *node;

    /* Enhancement-315: CKTic sets nodeset/IC values into the RHS vectors. When those
       vectors have not been allocated -- reachable by running a second .pz over a URC
       device, where the RHS is NULL when CKTic runs -- the zeroing loop below (which the
       compiler vectorises into memset(CKTrhs, 0, ...)) wrote through a NULL pointer and
       SIGSEGV'd. There are no initial conditions to place into vectors that do not exist,
       so return cleanly. */
    if (ckt->CKTrhs == NULL || ckt->CKTrhsOld == NULL || ckt->CKTmatrix == NULL)
        return(OK);

    size = SMPmatSize(ckt->CKTmatrix);
    for (i=0;i<=size;i++) {
        ckt->CKTrhs[i]=0;
    }

    for(node = ckt->CKTnodes;node != NULL; node = node->next) {
        if(node->nsGiven) {

#ifdef KLU
            if (ckt->CKTkluMODE) {
                node->ptr = (double *) SMPfindElt (ckt->CKTmatrix, node->number, node->number, 0) ;
                if (node->ptr == NULL) {
                    printf ("Warning: The needed element doesn't exist in the matrix, but KLU mode cannot create a new element. ") ;
                    printf ("Please specify an existing element for .nodeset\n") ;
                }
            } else {
#endif

                node->ptr = SMPmakeElt(ckt->CKTmatrix,node->number,node->number);

#ifdef KLU
            }
#endif

            if(node->ptr == NULL) return(E_NOMEM);
            ckt->CKThadNodeset = 1;
            ckt->CKTrhsOld[node->number] = ckt->CKTrhs[node->number] = node->nodeset;
        }
        if(node->icGiven) {
            if(! ( node->ptr)) {

#ifdef KLU
                if (ckt->CKTkluMODE) {
                    node->ptr = (double *) SMPfindElt (ckt->CKTmatrix, node->number, node->number, 0) ;
                    if (node->ptr == NULL) {
                        printf ("Warning: The needed element doesn't exist in the matrix, but KLU mode cannot create a new element. ") ;
                        printf ("Please specify an existing element for .ic\n") ;
                    }
                } else {
#endif

                    node->ptr = SMPmakeElt(ckt->CKTmatrix,node->number, node->number);

#ifdef KLU
                }
#endif

                if(node->ptr == NULL) return(E_NOMEM);
            }
            ckt->CKTrhsOld[node->number] = ckt->CKTrhs[node->number] = node->ic;
        }
    }

    if(ckt->CKTmode & MODEUIC) {
        for (i=0;i<DEVmaxnum;i++) {
            if( DEVices[i] && DEVices[i]->DEVsetic && ckt->CKThead[i] ) {
                error = DEVices[i]->DEVsetic (ckt->CKThead[i], ckt);
                if(error) return(error);
            }
        }
    }

    return(OK);
}
