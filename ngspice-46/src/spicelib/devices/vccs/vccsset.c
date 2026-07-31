/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/
/*
 */

    /* load the current source structure with those pointers needed later 
     * for fast matrix loading 
     */

#include "ngspice/ngspice.h"
#include "ngspice/smpdefs.h"
#include "ngspice/cktdefs.h"
#include "vccsdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"


/*ARGSUSED*/
int
VCCSsetup(SMPmatrix *matrix, GENmodel *inModel, CKTcircuit *ckt, int *states)
{
    VCCSmodel *model = (VCCSmodel *)inModel;
    VCCSinstance *here;

    NG_IGNORE(states);
    NG_IGNORE(ckt);

    /*  loop through all the current source models */
    for( ; model != NULL; model = VCCSnextModel(model)) {

        /* loop through all the instances of the model */
        for (here = VCCSinstances(model); here != NULL ;
                here=VCCSnextInstance(here)) {

            /* Enhancement-385: materialise the multiplier default, the way
             * `res` does (`if(!here->RESmGiven) here->RESm = 1.0;`).
             *
             * VCCSmValue was left at 0 whenever `m` was not written on the
             * instance line, and VCCSparam folds it into the coefficient:
             *
             *     case VCCS_TRANS:  here->VCCScoeff = value->rValue;
             *                       if (here->VCCSmGiven)
             *                           here->VCCScoeff *= here->VCCSmValue;
             *
             * `sens` perturbs every settable real parameter, so it wrote `m` --
             * which set VCCSmGiven -- read it back as 0, and wrote that 0 back
             * as the "restore". The next write of `gain` then multiplied by
             * zero and the source went dead: @g1[gain] 1e-3 -> 0, and every
             * following `.ac` returned 0 where the answer was 1.0. Defaulting
             * m to 1 makes the perturb/restore round-trip exact. */
            if (!here->VCCSmGiven)
                here->VCCSmValue = 1.0;

/* macro to make elements with built in test for out of memory */
#define TSTALLOC(ptr,first,second) \
do { if((here->ptr = SMPmakeElt(matrix, here->first, here->second)) == NULL){\
    return(E_NOMEM);\
} } while(0)

            TSTALLOC(VCCSposContPosPtr, VCCSposNode, VCCScontPosNode);
            TSTALLOC(VCCSposContNegPtr, VCCSposNode, VCCScontNegNode);
            TSTALLOC(VCCSnegContPosPtr, VCCSnegNode, VCCScontPosNode);
            TSTALLOC(VCCSnegContNegPtr, VCCSnegNode, VCCScontNegNode);
        }
    }
    return(OK);
}
