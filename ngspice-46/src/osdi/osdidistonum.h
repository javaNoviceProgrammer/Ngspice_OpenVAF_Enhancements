/* Enhancement-359: numerical distortion tensors -- see osdidistonum.c. */
#ifndef OSDI_DISTO_NUM_H
#define OSDI_DISTO_NUM_H

#include "ngspice/cktdefs.h"
#include "ngspice/gendefs.h"
#include "osdi.h"

/* Entries carry the same (row, col...) shape the analytic path produced, so the
 * Volterra contraction is unchanged. The cols are indices into `gnodes`, i.e.
 * DISTINCT GLOBAL nodes -- collapsed instance nodes share one. */
typedef struct {
    uint32_t row, c1, c2;
    double resist, react;
} OsdiNumT2;

typedef struct {
    uint32_t row, c1, c2, c3;
    double resist, react;
} OsdiNumT3;

typedef struct {
    uint32_t n2, n3;
    uint32_t K;             /* number of distinct global nodes  */
    uint32_t *gnodes;       /* K global solution indices        */
    uint32_t *g_of_node;    /* num_nodes -> gnode slot, or MAX  */
    OsdiNumT2 *t2;
    OsdiNumT3 *t3;
} OsdiNumDisto;

int osdi_numdisto_build(CKTcircuit *ckt, const OsdiDescriptor *descr,
                        GENinstance *gi, void *inst, void *model,
                        const uint32_t *node_mapping, OsdiSimInfo *base_info,
                        OsdiNumDisto *nd);
void osdi_numdisto_free(OsdiNumDisto *nd);

#endif
