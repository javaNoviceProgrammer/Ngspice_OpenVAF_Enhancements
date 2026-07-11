/* Enhancement-155/156: RC network reduction (TICER) for post-layout parasitics.
 *
 * Extracted post-layout netlists carry enormous linear parasitic RC networks
 * (10^5-10^6 interior nodes). This engine reduces such a network to a small,
 * electrically equivalent one that preserves the port behaviour over a band of
 * interest, using TICER (Time-Constant Equilibration Reduction): Schur-complement
 * elimination of interior nodes of Y(s)=G+sC, kept first order in s so the result is
 * realizable as ordinary R's and C's -- no model-order black box, no passive-synthesis
 * step.
 *
 * E-156 makes it SPARSE and scalable: the network is stored as per-node adjacency
 * lists (not a dense N*N matrix), and interior nodes are eliminated in a
 * MINIMUM-DEGREE order (like sparse LU) so fill-in stays tiny -- a degree-2 chain node
 * merges two series elements with ZERO fill. A FILL GUARD (`maxdeg`) refuses to
 * eliminate a node once its degree grows past a threshold, so a dense mesh core is
 * left intact instead of blowing up (the Schur complement of a 2D-mesh boundary is
 * dense). This lifts the node cap from ~2500 (the old dense build) into the millions.
 *
 * Eliminating node n updates, for every ordered neighbour pair (a,b), a!=b:
 *     g_ab += g_na*g_nb/Gn
 *     c_ab += (g_na*c_nb + c_na*g_nb)/Gn - g_na*g_nb*Cn/Gn^2
 * (Gn, Cn = node n's total conductance/capacitance = its edge sums). The conductance
 * update is the exact Schur complement, so DC is preserved EXACTLY; the diagonal
 * bookkeeping is automatic in the edge representation. A node is eliminated only when
 * its self time-constant frequency f_n = Gn/(2*pi*Cn) > factor*fmax (quasi-static
 * in-band). Ports (kept nodes) are auto-detected as every node touched by a non-R/C
 * device, plus ground and user `keep` nodes.
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

#define RC_MAXN 5000000     /* sanity cap on RC-network node count */

extern IFuid CKTnodName(CKTcircuit *, int);
extern int   CKTtypelook(char *);

/* ---- sparse adjacency: per node, a growable list of (neighbour, g, c) edges ---- */
typedef struct { int nbr; double g, c; } RCedge;
typedef struct { RCedge *e; int n, cap; } RCadj;

static int rc_find(RCadj *a, int nbr)
{
    int k;
    for (k = 0; k < a->n; k++) if (a->e[k].nbr == nbr) return k;
    return -1;
}

static void rc_bump(RCadj *a, int nbr, double g, double c)
{
    int k = rc_find(a, nbr);
    if (k >= 0) { a->e[k].g += g; a->e[k].c += c; return; }
    if (a->n == a->cap) {
        a->cap = a->cap ? a->cap * 2 : 4;
        a->e = TREALLOC(RCedge, a->e, a->cap);
    }
    a->e[a->n].nbr = nbr; a->e[a->n].g = g; a->e[a->n].c = c; a->n++;
}

static void rc_addedge(RCadj *adj, int a, int b, double g, double c)
{
    rc_bump(&adj[a], b, g, c);
    rc_bump(&adj[b], a, g, c);
}

static void rc_del(RCadj *a, int nbr)
{
    int k = rc_find(a, nbr);
    if (k >= 0) { a->e[k] = a->e[a->n - 1]; a->n--; }
}

/* ---- minimum-degree binary heap of (degree, node) with lazy stale entries ---- */
typedef struct { int deg, node; } HeapItem;

static void h_push(HeapItem *H, int *Hn, int deg, int node)
{
    int i = (*Hn)++; H[i].deg = deg; H[i].node = node;
    while (i > 0) {
        int p = (i - 1) / 2;
        if (H[p].deg <= H[i].deg) break;
        HeapItem t = H[p]; H[p] = H[i]; H[i] = t; i = p;
    }
}

static HeapItem h_pop(HeapItem *H, int *Hn)
{
    HeapItem top = H[0];
    H[0] = H[--(*Hn)];
    int i = 0, N = *Hn;
    for (;;) {
        int l = 2*i + 1, r = 2*i + 2, m = i;
        if (l < N && H[l].deg < H[m].deg) m = l;
        if (r < N && H[r].deg < H[m].deg) m = r;
        if (m == i) break;
        HeapItem t = H[m]; H[m] = H[i]; H[i] = t; i = m;
    }
    return top;
}

/* node n's total conductance/capacitance (edge sums) */
static void rc_gc(RCadj *adj, int n, double *G, double *C)
{
    int k; double g = 0.0, c = 0.0;
    for (k = 0; k < adj[n].n; k++) { g += adj[n].e[k].g; c += adj[n].e[k].c; }
    *G = g; *C = c;
}

static int rc_eligible(RCadj *adj, char *alive, int *isport, int n, double thr)
{
    double G, C;
    if (!alive[n] || n == 0 || isport[n]) return 0;
    rc_gc(adj, n, &G, &C);
    if (G <= 0.0) return 0;
    return (C <= 0.0) ? 1 : (G / (2.0 * M_PI * C) > thr);
}

int
CKTreduceRC(CKTcircuit *ckt, double fmax, double factor, int maxdeg,
            int *keep, int nkeep, const char *fname, const char *subname)
{
    int rcode = CKTtypelook("Resistor");
    int ccode = CKTtypelook("Capacitor");
    int Nnodes = ckt->CKTmaxEqNum;
    int *cidx = NULL, *rcnode = NULL, *isport = NULL;
    RCadj *adj = NULL;
    int i, j, t, n = 0, nrem = 0, status = OK;
    GENmodel *mod; GENinstance *inst;
    FILE *fp = NULL;
    long r_out = 0, c_out = 0;

    if (rcode < 0 || ccode < 0) {
        fprintf(stderr, "Error: reduce: this build lacks resistors/capacitors.\n");
        return -1;
    }
    if (maxdeg < 3) maxdeg = 3;

    cidx = TMALLOC(int, Nnodes);
    isport = TMALLOC(int, Nnodes);
    for (i = 0; i < Nnodes; i++) { cidx[i] = -1; isport[i] = 0; }

    /* compact-index every node that appears in a resistor or capacitor (index 0 = ground) */
    for (mod = ckt->CKThead[rcode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            RESinstance *r = (RESinstance *) inst;
            if (r->RESposNode > 0 && cidx[r->RESposNode] < 0) cidx[r->RESposNode] = ++n;
            if (r->RESnegNode > 0 && cidx[r->RESnegNode] < 0) cidx[r->RESnegNode] = ++n;
        }
    for (mod = ckt->CKThead[ccode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            CAPinstance *c = (CAPinstance *) inst;
            if (c->CAPposNode > 0 && cidx[c->CAPposNode] < 0) cidx[c->CAPposNode] = ++n;
            if (c->CAPnegNode > 0 && cidx[c->CAPnegNode] < 0) cidx[c->CAPnegNode] = ++n;
        }
    if (n < 1) { fprintf(stderr, "Error: reduce: no RC network found.\n"); status = -1; goto done; }
    if (n > RC_MAXN) {
        fprintf(stderr, "Error: reduce: RC network has %d nodes, over the %d cap.\n", n, RC_MAXN);
        status = -1; goto done;
    }
    rcnode = TMALLOC(int, n + 1);                       /* compact idx (1..n) -> orig node */
    for (i = 1; i < Nnodes; i++) if (cidx[i] > 0) rcnode[cidx[i]] = i;

    /* ports: every node touched by a non-R/C device, plus user keeps */
    for (t = 0; t < DEVmaxnum; t++) {
        if (t == rcode || t == ccode || !DEVices[t] || !ckt->CKThead[t]) continue;
        int nterm = DEVices[t]->DEVpublic.numNames ? *DEVices[t]->DEVpublic.numNames : 0;
        for (mod = ckt->CKThead[t]; mod; mod = mod->GENnextModel)
            for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance)
                for (j = 0; j < nterm; j++) {
                    int nd = GENnode(inst)[j];
                    if (nd > 0 && nd < Nnodes && cidx[nd] > 0) isport[cidx[nd]] = 1;
                }
    }
    for (i = 0; i < nkeep; i++)
        if (keep[i] > 0 && keep[i] < Nnodes && cidx[keep[i]] > 0) isport[cidx[keep[i]]] = 1;

    /* build sparse adjacency over compact indices (0 = ground) */
    adj = TMALLOC(RCadj, n + 1);
    for (i = 0; i <= n; i++) { adj[i].e = NULL; adj[i].n = 0; adj[i].cap = 0; }
    for (mod = ckt->CKThead[rcode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            RESinstance *r = (RESinstance *) inst;
            double g = r->RESconduct;
            int a, b;
            if (g == 0.0 && r->RESresist != 0.0) g = 1.0 / r->RESresist;
            a = r->RESposNode > 0 ? cidx[r->RESposNode] : 0;
            b = r->RESnegNode > 0 ? cidx[r->RESnegNode] : 0;
            if (a != b) rc_addedge(adj, a, b, g, 0.0);
        }
    for (mod = ckt->CKThead[ccode]; mod; mod = mod->GENnextModel)
        for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
            CAPinstance *c = (CAPinstance *) inst;
            int a = c->CAPposNode > 0 ? cidx[c->CAPposNode] : 0;
            int b = c->CAPnegNode > 0 ? cidx[c->CAPnegNode] : 0;
            if (a != b) rc_addedge(adj, a, b, 0.0, c->CAPcapac);
        }

    /* ---- TICER: minimum-degree elimination with fill guard + frequency criterion ---- */
    {
        double thr = factor * fmax;
        char *alive = TMALLOC(char, n + 1);
        HeapItem *H = TMALLOC(HeapItem, 4 * (n + 1));
        int Hn = 0;
        for (i = 0; i <= n; i++) alive[i] = 1;
        for (i = 1; i <= n; i++)
            if (rc_eligible(adj, alive, isport, i, thr)) h_push(H, &Hn, adj[i].n, i);

        while (Hn > 0) {
            HeapItem it = h_pop(H, &Hn);
            int nn = it.node, d, a, b;
            double Gn, Cn;
            RCedge *nb;
            if (!alive[nn] || it.deg != adj[nn].n || !rc_eligible(adj, alive, isport, nn, thr))
                continue;
            if (adj[nn].n > maxdeg) continue;              /* fill guard: keep dense-core node */
            rc_gc(adj, nn, &Gn, &Cn);
            d = adj[nn].n;
            nb = TMALLOC(RCedge, d);                       /* snapshot: the list mutates below */
            for (a = 0; a < d; a++) nb[a] = adj[nn].e[a];
            for (a = 0; a < d; a++) {
                double gna = nb[a].g, cna = nb[a].c;
                for (b = 0; b < d; b++) {
                    double gnb, cnb, dg, dc;
                    if (a == b) continue;
                    gnb = nb[b].g; cnb = nb[b].c;
                    dg = gna * gnb / Gn;
                    dc = (gna * cnb + cna * gnb) / Gn - gna * gnb * Cn / (Gn * Gn);
                    rc_bump(&adj[nb[a].nbr], nb[b].nbr, dg, dc);  /* (b,a) pass does the mirror */
                }
            }
            for (a = 0; a < d; a++) rc_del(&adj[nb[a].nbr], nn);   /* detach n */
            adj[nn].n = 0; alive[nn] = 0;
            for (a = 0; a < d; a++)
                if (rc_eligible(adj, alive, isport, nb[a].nbr, thr))
                    h_push(H, &Hn, adj[nb[a].nbr].n, nb[a].nbr);
            FREE(nb);
        }
        FREE(H);

        for (i = 1; i <= n; i++) if (alive[i]) nrem++;

        /* ---- emit the reduced .subckt (R's and C's) ---- */
        fp = fopen(fname, "w");
        if (!fp) { fprintf(stderr, "Error: reduce: cannot open '%s'.\n", fname); status = -1; FREE(alive); goto done; }
        fprintf(fp, "* reduced RC network (TICER), band DC..%g Hz, factor %g, maxdeg %d\n",
                fmax, factor, maxdeg);
        fprintf(fp, ".subckt %s", subname);
        for (i = 1; i <= n; i++)
            if (alive[i] && isport[i]) fprintf(fp, " %s", (char *) CKTnodName(ckt, rcnode[i]));
        fprintf(fp, "\n");
        for (i = 1; i <= n; i++) {
            const char *ni;
            if (!alive[i]) continue;
            ni = (char *) CKTnodName(ckt, rcnode[i]);
            for (j = 0; j < adj[i].n; j++) {
                int b = adj[i].e[j].nbr;
                const char *nbn;
                double gij, cij;
                if (b != 0 && b <= i) continue;            /* node-node edge: emit once (from lower i) */
                nbn = (b == 0) ? "0" : (char *) CKTnodName(ckt, rcnode[b]);
                gij = adj[i].e[j].g; cij = adj[i].e[j].c;
                if (fabs(gij) > 1e-18) fprintf(fp, "R%ld %s %s %.9g\n", ++r_out, ni, nbn, 1.0 / gij);
                if (fabs(cij) > 1e-21) fprintf(fp, "C%ld %s %s %.9g\n", ++c_out, ni, nbn, cij);
            }
        }
        fprintf(fp, ".ends %s\n", subname);
        fclose(fp);
        fprintf(stdout, "reduce: RC network %d nodes -> %d nodes (%.1fx), "
                        "%ld R + %ld C written to %s\n",
                n, nrem, nrem ? (double) n / nrem : 0.0, r_out, c_out, fname);
        /* the .subckt terminal order is significant -- show how to instantiate it */
        fprintf(stdout, "reduce: instantiate as  x1");
        for (i = 1; i <= n; i++)
            if (alive[i] && isport[i]) fprintf(stdout, " %s", (char *) CKTnodName(ckt, rcnode[i]));
        fprintf(stdout, " %s\n", subname);
        FREE(alive);
    }

done:
    if (adj) { for (i = 0; i <= n; i++) FREE(adj[i].e); FREE(adj); }
    FREE(cidx); FREE(isport); FREE(rcnode);
    return status == OK ? nrem : status;
}
