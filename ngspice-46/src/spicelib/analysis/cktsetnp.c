/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

    /*
     *CKTsetNodPm
     *
     *   set a parameter on a node.
     */

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/cktdefs.h"
#ifdef OSDI
#include "ngspice/osdiitf.h"   /* Enhancement-688: OSDIcollapsedNode */
#endif



/* ARGSUSED */
int
CKTsetNodPm(CKTcircuit *ckt, CKTnode *node, int parm, IFvalue *value, IFvalue *selector)
{
    NG_IGNORE(ckt);
    NG_IGNORE(selector);

    if(!node) return(E_BADPARM);
    switch(parm) {

    case PARM_NS:
        node->nodeset = value->rValue;
        node->nsGiven = 1;
        break;

    case PARM_IC:
        node->ic = value->rValue;
        node->icGiven = 1;
        break;

    case PARM_NODETYPE:
        node->type = value->iValue;
        break;

    default:
        return(E_BADPARM);
    }
    return(OK);
}


/* Enhancement-608: a `.ic` or `.nodeset` on a device's INTERNAL node.
 *
 * `v(n1#mid)` names a node the device builds at setup, after INPpas3 reads
 * the card, so the entry was refused ("on non-existent node, ignored").
 * INPpas3 keeps such an entry here by name -- when the part before the '#'
 * names an instance of the deck -- and CKTsetup() places it once the devices
 * have built their nodes, at every setup (a device-local node is rebuilt, or
 * revived, each time). A name no setup can place is reported once, in the
 * words INPpas3 would have used. */
void
CKTpendNodPm(CKTcircuit *ckt, const char *name, int parm, double value)
{
    struct CKTpendingNodeParm *p = TMALLOC(struct CKTpendingNodeParm, 1);

    p->name = copy(name);
    p->parm = parm;
    p->value = value;
    p->reported = 0;
    p->next = ckt->CKTpendingNodeParms;
    ckt->CKTpendingNodeParms = p;
}

void
CKTapplyPendingNodPm(CKTcircuit *ckt)
{
    struct CKTpendingNodeParm *p;
    CKTnode *n;

    for (p = ckt->CKTpendingNodeParms; p; p = p->next) {
        for (n = ckt->CKTnodes; n; n = n->next)
            if (n->name && eq(n->name, p->name))
                break;
        if (n) {
            IFvalue v;
            v.rValue = p->value;
            CKTsetNodPm(ckt, n, p->parm, &v, NULL);
            continue;
        }
        {
            const char *inst_end = strchr(p->name, '#');
            int into = -1, collapsed = 0;
#ifdef OSDI
            /* Enhancement-688 (hunt F6 of 2026-09-21): the node exists in the
             * module and the model collapsed it into another node (or into
             * ground). The two are one node, so the entry belongs on the node
             * it was collapsed into; say so once. Only a name that is no
             * internal node of the instance gets the old refusal. */
            collapsed = OSDIcollapsedNode(ckt, p->name, &into);
#endif
            if (collapsed && into > 0) {
                CKTnode *tgt = CKTnum2nod(ckt, into);
                if (tgt) {
                    IFvalue v;
                    v.rValue = p->value;
                    CKTsetNodPm(ckt, tgt, p->parm, &v, NULL);
                }
                if (!p->reported)
                    fprintf(stderr,
                            "Note: %s on %s: the model collapses %.*s's internal node "
                            "'%s' into '%s', so it is applied to '%s'.\n",
                            p->parm == PARM_IC ? "IC" : "Nodeset", p->name,
                            inst_end ? (int) (inst_end - p->name) : 0, p->name,
                            inst_end ? inst_end + 1 : "",
                            tgt ? (char *) tgt->name : "?", tgt ? (char *) tgt->name : "?");
            } else if (collapsed) {
                if (!p->reported)
                    fprintf(stderr,
                            "Warning : %s on %s, ignored: the model collapses %.*s's "
                            "internal node '%s' into ground (or leaves it unconnected).\n",
                            p->parm == PARM_IC ? "IC" : "Nodeset", p->name,
                            inst_end ? (int) (inst_end - p->name) : 0, p->name,
                            inst_end ? inst_end + 1 : "");
            } else if (!p->reported) {
                fprintf(stderr,
                        "Warning : %s on non-existent node - %s, ignored\n"
                        "   (%.*s has no internal node '%s')\n",
                        p->parm == PARM_IC ? "IC" : "Nodeset", p->name,
                        inst_end ? (int) (inst_end - p->name) : 0, p->name,
                        inst_end ? inst_end + 1 : "");
            }
            p->reported = 1;
        }
    }
}

void
CKTfreePendingNodPm(CKTcircuit *ckt)
{
    struct CKTpendingNodeParm *p, *next;

    for (p = ckt->CKTpendingNodeParms; p; p = next) {
        next = p->next;
        tfree(p->name);
        tfree(p);
    }
    ckt->CKTpendingNodeParms = NULL;
}
