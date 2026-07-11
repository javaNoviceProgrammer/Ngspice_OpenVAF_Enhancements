/* Enhancement-155: RC network reduction (TICER) for post-layout parasitics.
 *
 * Extracted post-layout netlists contain enormous linear RC networks (parasitic
 * resistors and capacitors) with huge numbers of internal nodes. This engine
 * reduces such a network to a much smaller, ELECTRICALLY EQUIVALENT one that
 * preserves the port behaviour over a band of interest, using TICER
 * (Time-Constant Equilibration Reduction): Gaussian (Schur-complement) elimination
 * of interior nodes, kept first-order in s so the result is realizable as ordinary
 * R's and C's -- no model-order-reduction black box, no passive-synthesis step.
 *
 * The admittance among the nodes is Y(s) = G + s*C. Eliminating an interior node n
 * updates, for every neighbour pair (a,b) (including a==b):
 *     G[a,b] -= G[a,n]*G[n,b] / G[n,n]
 *     C[a,b] -= (G[a,n]*C[n,b] + C[a,n]*G[n,b])/G[n,n] - G[a,n]*G[n,b]*C[n,n]/G[n,n]^2
 * The conductance update is the exact Schur complement (so DC is preserved
 * exactly); the capacitance update matches Y to first order in s. A node is
 * eliminated only when its self time-constant frequency f_n = G_n/(2*pi*C_n) lies
 * well ABOVE the band of interest (f_n > factor*fmax): such a node is quasi-static
 * in-band and can be collapsed without losing in-band accuracy. `factor` trades
 * reduction against accuracy (small -> more reduction, larger -> tighter fit).
 *
 * PORTS (nodes that must be kept) are auto-detected as every node touched by a
 * device that is NOT a resistor or capacitor (sources, transistors, OSDI devices,
 * ...) -- i.e. the terminals where the parasitic network meets real devices --
 * plus ground and any user-named nodes. Only interior RC-only nodes are removed.
 *
 * The reduced network is written as a `.subckt` of R's and C's, ready to be
 * `.include`d in place of the original parasitics.
 */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/gendefs.h"
#include "ngspice/sperror.h"
#include "../devices/res/resdefs.h"
#include "../devices/cap/capdefs.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define RC_MAXN 2500     /* dense-matrix node cap (sparse TICER is a follow-up) */

extern IFuid CKTnodName(CKTcircuit *, int);
extern int   CKTtypelook(char *);

/* dense symmetric matrices over the compact RC-node index space */
#define GG(i,j) (G[(size_t)(i)*(size_t)n + (size_t)(j)])
#define CC(i,j) (Cm[(size_t)(i)*(size_t)n + (size_t)(j)])

int
CKTreduceRC(CKTcircuit *ckt, double fmax, double factor,
            int *keep, int nkeep, const char *fname, const char *subname)
{
    int rcode = CKTtypelook("Resistor");
    int ccode = CKTtypelook("Capacitor");
    int Nnodes = ckt->CKTmaxEqNum;           /* 0 = ground, 1 .. Nnodes-1 unknowns */
    int *isrc = NULL, *cidx = NULL, *rcnode = NULL;
    int i, j, t, n = 0, nrem = 0, status = OK;
    double *G = NULL, *Cm = NULL;
    GENmodel *mod; GENinstance *inst;
    FILE *fp = NULL;
    long r_out = 0, c_out = 0;

    if (rcode < 0 || ccode < 0) {
        fprintf(stderr, "Error: reduce: this build lacks resistors/capacitors.\n");
        return -1;
    }

    /* isrc[node] = 1 if the node is an RC-network node; cidx[node] = compact index */
    isrc = TMALLOC(int, Nnodes);
    cidx = TMALLOC(int, Nnodes);
    int *isport = TMALLOC(int, Nnodes);
    for (i = 0; i < Nnodes; i++) { isrc[i] = 0; cidx[i] = -1; isport[i] = 0; }

    /* collect the set of nodes that appear in a resistor or capacitor */
    for (mod = ckt->CKThead[rcode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            RESinstance *r = (RESinstance *) inst;
            if (r->RESposNode) isrc[r->RESposNode] = 1;
            if (r->RESnegNode) isrc[r->RESnegNode] = 1;
        }
    for (mod = ckt->CKThead[ccode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            CAPinstance *c = (CAPinstance *) inst;
            if (c->CAPposNode) isrc[c->CAPposNode] = 1;
            if (c->CAPnegNode) isrc[c->CAPnegNode] = 1;
        }
    for (i = 1; i < Nnodes; i++)
        if (isrc[i]) { cidx[i] = n; n++; }

    if (n < 1) { fprintf(stderr, "Error: reduce: no RC network found.\n"); status = -1; goto done; }
    if (n > RC_MAXN) {
        fprintf(stderr, "Error: reduce: RC network has %d nodes, over the %d cap "
                        "for this dense implementation.\n", n, RC_MAXN);
        status = -1; goto done;
    }
    rcnode = TMALLOC(int, n);                /* compact index -> original node number */
    for (i = 1; i < Nnodes; i++) if (cidx[i] >= 0) rcnode[cidx[i]] = i;

    /* PORTS: every node touched by a non-R/C device, plus user keeps (ground = 0) */
    for (t = 0; t < DEVmaxnum; t++) {
        if (t == rcode || t == ccode || !DEVices[t] || !ckt->CKThead[t]) continue;
        int nterm = DEVices[t]->DEVpublic.numNames ? *DEVices[t]->DEVpublic.numNames : 0;
        for (mod = ckt->CKThead[t]; mod; mod = mod->GENnextModel)
            for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance)
                for (j = 0; j < nterm; j++) {
                    int nd = GENnode(inst)[j];
                    if (nd > 0 && nd < Nnodes) isport[nd] = 1;
                }
    }
    for (i = 0; i < nkeep; i++)
        if (keep[i] > 0 && keep[i] < Nnodes) isport[keep[i]] = 1;

    /* build dense G, C over the RC nodes */
    G  = TMALLOC(double, (size_t) n * (size_t) n);
    Cm = TMALLOC(double, (size_t) n * (size_t) n);
    { size_t sz = (size_t) n * (size_t) n, q; for (q = 0; q < sz; q++) { G[q] = 0.0; Cm[q] = 0.0; } }

    for (mod = ckt->CKThead[rcode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            RESinstance *r = (RESinstance *) inst;
            double g = r->RESconduct;
            if (g == 0.0 && r->RESresist != 0.0) g = 1.0 / r->RESresist;
            int a = r->RESposNode, b = r->RESnegNode;
            int ia = a ? cidx[a] : -1, ib = b ? cidx[b] : -1;
            if (ia >= 0) GG(ia, ia) += g;
            if (ib >= 0) GG(ib, ib) += g;
            if (ia >= 0 && ib >= 0) { GG(ia, ib) -= g; GG(ib, ia) -= g; }
        }
    for (mod = ckt->CKThead[ccode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            CAPinstance *c = (CAPinstance *) inst;
            double cap = c->CAPcapac;
            int a = c->CAPposNode, b = c->CAPnegNode;
            int ia = a ? cidx[a] : -1, ib = b ? cidx[b] : -1;
            if (ia >= 0) CC(ia, ia) += cap;
            if (ib >= 0) CC(ib, ib) += cap;
            if (ia >= 0 && ib >= 0) { CC(ia, ib) -= cap; CC(ib, ia) -= cap; }
        }

    /* TICER: eliminate interior nodes whose f_n = G_n/(2*pi*C_n) > factor*fmax */
    {
        char *alive = TMALLOC(char, n);
        for (i = 0; i < n; i++) alive[i] = 1;
        int changed = 1;
        while (changed) {
            changed = 0;
            for (i = 0; i < n; i++) {
                if (!alive[i] || isport[rcnode[i]]) continue;
                double Gn = GG(i, i), Cn = CC(i, i);
                double fn = (Cn > 0.0) ? Gn / (2.0 * M_PI * Cn) : HUGE_VAL;
                if (Gn <= 0.0) continue;
                if (fn <= factor * fmax) continue;      /* in-band pole: keep it */
                /* eliminate node i (Schur complement, first order in s) */
                for (j = 0; j < n; j++) {
                    if (j == i || !alive[j] || (GG(i, j) == 0.0 && CC(i, j) == 0.0)) continue;
                    double gji = GG(j, i), cji = CC(j, i);
                    int k;
                    for (k = 0; k < n; k++) {
                        if (k == i || !alive[k] || (GG(i, k) == 0.0 && CC(i, k) == 0.0)) continue;
                        double gik = GG(i, k), cik = CC(i, k);
                        GG(j, k) -= gji * gik / Gn;
                        CC(j, k) -= (gji * cik + cji * gik) / Gn - gji * gik * Cn / (Gn * Gn);
                    }
                }
                alive[i] = 0; changed = 1;
            }
        }
        /* count remaining */
        nrem = 0;
        for (i = 0; i < n; i++) if (alive[i]) nrem++;

        /* emit reduced subckt */
        fp = fopen(fname, "w");
        if (!fp) { fprintf(stderr, "Error: reduce: cannot open '%s'.\n", fname); status = -1; FREE(alive); goto done; }
        /* port list = surviving nodes that are ports (subckt terminals) */
        fprintf(fp, "* reduced RC network (TICER), band of interest DC..%g Hz, factor %g\n", fmax, factor);
        fprintf(fp, ".subckt %s", subname);
        for (i = 0; i < n; i++)
            if (alive[i] && isport[rcnode[i]])
                fprintf(fp, " %s", (char *) CKTnodName(ckt, rcnode[i]));
        fprintf(fp, "\n");
        for (i = 0; i < n; i++) {
            if (!alive[i]) continue;
            const char *ni = (char *) CKTnodName(ckt, rcnode[i]);
            /* branch elements to higher-index survivors */
            for (j = i + 1; j < n; j++) {
                if (!alive[j]) continue;
                const char *nj = (char *) CKTnodName(ckt, rcnode[j]);
                double gij = -GG(i, j), cij = -CC(i, j);
                if (fabs(gij) > 1e-18)
                    fprintf(fp, "R%ld %s %s %.9g\n", ++r_out, ni, nj, 1.0 / gij);
                if (fabs(cij) > 1e-21)
                    fprintf(fp, "C%ld %s %s %.9g\n", ++c_out, ni, nj, cij);
            }
            /* element to ground: g_i0 = row sum of G; c_i0 = row sum of C */
            double grow = 0.0, crow = 0.0;
            for (j = 0; j < n; j++) if (alive[j]) { grow += GG(i, j); crow += CC(i, j); }
            if (fabs(grow) > 1e-18)
                fprintf(fp, "R%ld %s 0 %.9g\n", ++r_out, ni, 1.0 / grow);
            if (fabs(crow) > 1e-21)
                fprintf(fp, "C%ld %s 0 %.9g\n", ++c_out, ni, crow);
        }
        fprintf(fp, ".ends %s\n", subname);
        fclose(fp);
        FREE(alive);

        fprintf(stdout, "reduce: RC network %d nodes -> %d nodes (%.1fx), "
                        "%ld R + %ld C written to %s (.subckt %s)\n",
                n, nrem, nrem ? (double) n / nrem : 0.0, r_out, c_out, fname, subname);
    }

done:
    FREE(isrc); FREE(cidx); FREE(isport); FREE(rcnode); FREE(G); FREE(Cm);
    return status == OK ? nrem : status;
}
