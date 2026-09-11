/**********
Copyright 1992 Regents of the University of California.  All rights reserved.
**********/

/* CKTdltNod
*/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/hash.h"      /* Enhancement-608 */
#include "ngspice/ifsim.h"
#include "ngspice/sperror.h"

/* ARGSUSED */
int
CKTdltNod(CKTcircuit* ckt, CKTnode* node)
{
    return CKTdltNNum(ckt, node->number);
}

/* Enhancement-608: a device-local node is not freed when its device lets go
 * of it at unsetup; it is RETIRED under its name, and CKTmkVolt()/CKTmkCur()
 * of that name at the next setup revives the same struct. A job that bound
 * to the node -- `tf v(n1#mid) v1` typed after an `op` binds to the live
 * internal node -- used to keep a pointer into freed memory once the run's
 * own unsetup/setup had rebuilt the node, and reported whatever it read
 * there (a transfer function of -5e-4 for a divider's mid node). The name
 * is a private copy: IFdelUid() frees the symbol table's. */
static void
CKTretireNode(CKTcircuit *ckt, CKTnode *node)
{
    char *keep = node->name ? copy(node->name) : NULL;
    int error = SPfrontEnd->IFdelUid(ckt, node->name, UID_SIGNAL);

    NG_IGNORE(error);
    node->name = NULL;
    node->next = NULL;
    if (!keep) {
        tfree(node);
        return;
    }
    if (!ckt->CKTretiredNodes)
        ckt->CKTretiredNodes = nghash_init(64);
    nghash_insert(ckt->CKTretiredNodes, keep, node);   /* the key is copied */
    tfree(keep);
}

CKTnode *
CKTreviveNode(CKTcircuit *ckt, const char *name)
{
    CKTnode *n;

    if (!ckt || !name || !ckt->CKTretiredNodes)
        return NULL;
    n = nghash_delete(ckt->CKTretiredNodes, (void *) name);
    if (n) {
        n->next = NULL;
        n->name = NULL;
        n->ptr = NULL;
        n->natabstol = 0.0;
        n->devRef = 0;
        n->adopted = 0;
    }
    return n;
}

static void
free_retired(void *node)
{
    tfree(node);
}

void
CKTfreeRetiredNodes(CKTcircuit *ckt)
{
    if (ckt->CKTretiredNodes)
        nghash_free(ckt->CKTretiredNodes, free_retired, NULL);
    ckt->CKTretiredNodes = NULL;
}

int
CKTdltNNum(CKTcircuit* ckt, int num)
{
    CKTnode* n, * prev, * node;

    prev = NULL;
    node = NULL;

    for (n = ckt->CKTnodes; n; n = n->next) {
        if (n->number == num) {
            node = n;
            break;
        }
        prev = n;
    }

    /* Enhancement-608: a parse-time node the device took over as its
     * internal node stays -- it is the deck's, and the device takes it over
     * again at the next setup. */
    if (node && node->adopted)
        return OK;

    if (!ckt->prev_CKTlastNode->number || num <= ckt->prev_CKTlastNode->number) {
        fprintf(stderr, "Internal Error: CKTdltNNum() removing a non device-local node, this will cause serious problems, please report this issue !\n");
        controlled_exit(EXIT_FAILURE);
    }

    if (!node)
        return OK;

    ckt->CKTmaxEqNum -= 1;

    if (!prev) {
        ckt->CKTnodes = node->next;
    }
    else {
        prev->next = node->next;
    }
    if (node == ckt->CKTlastNode)
        ckt->CKTlastNode = prev;

    CKTretireNode(ckt, node);       /* Enhancement-608: kept, not freed */

    return OK;
}


/* Enhancement-470: delete a SET of device-local nodes in ONE pass.
 *
 * CKTdltNNum() finds its node by scanning the circuit's node list from the
 * head, so unsetting a device that owns k internal nodes costs O(k*N). A
 * profile of a 1001-point parameter sweep over a 2448-unknown circuit spent
 * 77% of the entire run inside it -- not in the solve, not in setup, but in
 * tearing the circuit down between points, once per point:
 *
 *     10083 com_sweep -> sw_run_cmd -> dosim -> if_run
 *       8092 CKTdoJob
 *         8083 CKTunsetup
 *           8056 OSDIunsetup
 *             7808 CKTdltNNum          <- 77% of total
 *
 * and the quadratic shows in the wall clock: 1.6 / 4.1 / 31 ms per sweep point
 * for 5 / 10 / 25 stack periods, growing faster than the circuit does.
 *
 * The caller knows every number it wants gone before it deletes any of them, so
 * it can mark them and let one walk of the list remove them all: O(N) for the
 * whole unsetup instead of O(k*N). `del` is indexed by node number and `maxnum`
 * is its highest valid index, taken before any deletion since CKTmaxEqNum moves
 * as nodes go.
 *
 * Nodes at or below `prev_CKTlastNode` are external and are skipped, the same
 * boundary CKTdltNNum enforces with a fatal error; a caller that marks one is
 * simply ignored here rather than killing the run mid-teardown. */
int
CKTdltNodeSet(CKTcircuit *ckt, const char *del, int maxnum)
{
    CKTnode *n, *next, *prev = NULL;
    int error = OK;
    int floor_num;

    if (!ckt || !del)
        return OK;
    floor_num = ckt->prev_CKTlastNode ? ckt->prev_CKTlastNode->number : 0;

    for (n = ckt->CKTnodes; n; n = next) {
        next = n->next;
        /* Enhancement-608: an adopted node is the deck's, not the device's */
        if (n->number > floor_num && n->number <= maxnum && del[n->number] &&
                !n->adopted) {
            if (prev)
                prev->next = next;
            else
                ckt->CKTnodes = next;
            if (n == ckt->CKTlastNode)
                ckt->CKTlastNode = prev;
            ckt->CKTmaxEqNum -= 1;
            CKTretireNode(ckt, n);      /* Enhancement-608: kept, not freed */
        } else {
            prev = n;
        }
    }
    return error;
}
