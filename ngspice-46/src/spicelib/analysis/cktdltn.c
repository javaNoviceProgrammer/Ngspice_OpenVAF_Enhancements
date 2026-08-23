/**********
Copyright 1992 Regents of the University of California.  All rights reserved.
**********/

/* CKTdltNod
*/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/sperror.h"

/* ARGSUSED */
int
CKTdltNod(CKTcircuit* ckt, CKTnode* node)
{
    return CKTdltNNum(ckt, node->number);
}

int
CKTdltNNum(CKTcircuit* ckt, int num)
{
    CKTnode* n, * prev, * node;
    int	error;

    if (!ckt->prev_CKTlastNode->number || num <= ckt->prev_CKTlastNode->number) {
        fprintf(stderr, "Internal Error: CKTdltNNum() removing a non device-local node, this will cause serious problems, please report this issue !\n");
        controlled_exit(EXIT_FAILURE);
    }

    prev = NULL;
    node = NULL;

    for (n = ckt->CKTnodes; n; n = n->next) {
        if (n->number == num) {
            node = n;
            break;
        }
        prev = n;
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

    error = SPfrontEnd->IFdelUid(ckt, node->name, UID_SIGNAL);
    tfree(node);

    return error;
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
        if (n->number > floor_num && n->number <= maxnum && del[n->number]) {
            int e;
            if (prev)
                prev->next = next;
            else
                ckt->CKTnodes = next;
            if (n == ckt->CKTlastNode)
                ckt->CKTlastNode = prev;
            ckt->CKTmaxEqNum -= 1;
            e = SPfrontEnd->IFdelUid(ckt, n->name, UID_SIGNAL);
            if (e && !error)
                error = e;
            tfree(n);
        } else {
            prev = n;
        }
    }
    return error;
}
