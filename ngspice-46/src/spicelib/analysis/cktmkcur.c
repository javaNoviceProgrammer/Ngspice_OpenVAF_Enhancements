/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/
/*
 */

    /* CKTmkCur
     *  make the given name a 'node' of type current in the 
     * specified circuit
     */

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "ngspice/sperror.h"
#include "ngspice/cktdefs.h"



/* ARGSUSED */
int
CKTmkCur(CKTcircuit *ckt, CKTnode **node, IFuid basename, char *suffix)
{
    /* Enhancement-608: one routine with CKTmkVolt(), in cktmkvol.c */
    return CKTmkSignal(ckt, node, basename, suffix, SP_CURRENT);
}
