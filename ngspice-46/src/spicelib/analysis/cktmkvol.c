/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

/* CKTmkVolt
 *  make the given name a 'node' of type voltage in the 
 * specified circuit
 */

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "ngspice/sperror.h"
#include "ngspice/cktdefs.h"



/* ARGSUSED */
/* Enhancement-608: the one routine behind CKTmkVolt() and CKTmkCur().
 *
 * A device builds its internal nodes at setup, after the deck is parsed. A
 * card that named one of them -- `.ic v(n1#mid)=0.7`, `.tf v(n1#mid) v1`,
 * `.pz ... n1#mid ...` -- had the deck reader make a node of that name
 * (inp_analysis_node(), and INPpas3 now), and this routine, told by IFnewUid
 * that the name existed, went on and linked a SECOND node under it: the
 * deck's node floated ("held only by gmin", a singular matrix, an operating
 * point that needed gmin stepping), the card's .ic/.nodeset went to it,
 * `.print op v(n1#mid)` printed its 0, and E-429 refused the .tf/.pz
 * output as a node "no device connects to" -- which was true of that one.
 * The device now ADOPTS the deck's node as its internal node: it is a
 * parse-time node, so unsetup leaves it in place and the next setup adopts
 * it again, and every card that bound to it is bound to what the device
 * stamps.
 *
 * A device-local node of the same name retired at the last unsetup is
 * revived (same struct), so a job that bound to it stays bound; see
 * CKTdltNNum(). */
int
CKTmkSignal(CKTcircuit *ckt, CKTnode **node, IFuid basename, char *suffix,
            int type)
{
    IFuid uid;
    int error;
    CKTnode *mynode;
    CKTnode *checknode;
    char *name = basename ? tprintf("%s#%s", basename, suffix) : copy(suffix);

    mynode = CKTreviveNode(ckt, name);
    tfree(name);
    if (!mynode) {
        error = CKTmkNode(ckt,&mynode);
        if(error) return(error);
    }
    checknode = mynode;
    error = SPfrontEnd->IFnewUid (ckt, &uid, basename, suffix, UID_SIGNAL, &checknode);
    if(error) {
        FREE(mynode);
        if(node) *node = checknode;
        return(error);
    }
    if (checknode != mynode && ckt->prev_CKTlastNode &&
            checknode->number <= ckt->prev_CKTlastNode->number) {
        /* the name is a parse-time node's: adopt it */
        FREE(mynode);
        checknode->type = type;
        checknode->devRef = 1;
        checknode->adopted = 1;
        if(node) *node = checknode;
        return(OK);
    }
    mynode->name = uid;
    mynode->type = type;
    if(node) *node = mynode;
    error = CKTlinkEq(ckt,mynode);
    return(error);
}

int
CKTmkVolt(CKTcircuit *ckt, CKTnode **node, IFuid basename, char *suffix)
{
    return CKTmkSignal(ckt, node, basename, suffix, SP_VOLTAGE);
}
