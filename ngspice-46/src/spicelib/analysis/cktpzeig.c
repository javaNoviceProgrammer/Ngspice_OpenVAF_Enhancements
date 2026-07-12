/* CKTpzEig -- eigenvalue-based pole-zero root finder.  Enhancement-173.
 *
 * The classic spice3 pole-zero driver hunts the roots of det(G + sC) with a
 * Muller iteration on determinant values -- famously fragile: iteration
 * limits, noise-floor stalls, spurious or missed roots.  This alternative
 * (enabled with `.options pzeig') computes the SAME roots directly as a dense
 * eigenvalue problem, using the same CKTpzSetup/CKTpzLoad machinery, so it
 * applies unchanged to both the poles and the zeros configuration and to both
 * linear solvers:
 *
 *   1. The PZ-configured MNA matrix is affine in s:  A(s) = G + s*C.
 *      Load at s=0 and s=1 and extract densely:  G = A(0), C = A(1) - A(0).
 *      (An extra load at an arbitrary third point verifies affinity, so a
 *      hypothetical non-polynomial device falls back cleanly.)
 *   2. Roots of det(G + sC) = 0 are the finite eigenvalues of the pencil
 *      (-G, C).  C is structurally singular (rows/columns without dynamic
 *      elements), so the pencil is solved by SHIFT-INVERT linearization:
 *      factor (G + sigma*C) at a non-root shift sigma -- one factorization
 *      with the circuit's own sparse solver -- and form the dense
 *          M = (G + sigma*C)^{-1} C           (n sparse solves).
 *      Then  (G + sC)v = 0  <=>  (G + sigma*C)v = (sigma - s)Cv
 *                           <=>  M v = mu v  with  mu = 1/(sigma - s) :
 *      every finite root is  s = sigma - 1/mu,  and the pencil's infinite
 *      eigenvalues land harmlessly at mu = 0.
 *   3. The eigenvalues of the real dense M come from the classical
 *      balance / Hessenberg / Francis double-shift QR chain (maths/dense/eig.c).
 *
 * Complexity is O(n^3) dense with O(n^2) memory -- fine for the small-signal
 * blocks PZ is used on (capped at PZEIG_MAXN).
 */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/complex.h"
#include "ngspice/pzdefs.h"
#include "ngspice/sperror.h"

#include <math.h>
#include <float.h>

extern int densereal_eig(int n, double *a, double *wr, double *wi);

#define PZEIG_MAXN 2000

/* comparison for sorting roots: ascending |s|, ties broken by imag part */
static int
root_cmp(const void *pa, const void *pb)
{
    const SPcomplex *a = (const SPcomplex *) pa;
    const SPcomplex *b = (const SPcomplex *) pb;
    double ma = hypot(a->real, a->imag), mb = hypot(b->real, b->imag);
    if (ma < mb) return -1;
    if (ma > mb) return 1;
    if (a->imag > b->imag) return -1;
    if (a->imag < b->imag) return 1;
    return 0;
}

int
CKTpzEig(CKTcircuit *ckt, PZtrial **rootinfo, int *rootcount)
{
    SPcomplex s;
    double *G = NULL, *C = NULL, *M = NULL, *wr = NULL, *wi = NULL;
    double *rhs = NULL, *irhs = NULL;
    SPcomplex *roots = NULL;
    PZtrial *head = NULL, **tailp = &head;
    double sigma = 0.0, normM, mu_tol;
    static const double shifts[] = { 0.0, 1.0e3, 1.0e6, 1.0e9, 1.0e12 };
    int n, i, j, k, nshift, numswaps, error = OK, nroots = 0, count = 0;

    *rootinfo = NULL;
    *rootcount = 0;

    n = SMPmatSize(ckt->CKTmatrix);
    if (n <= 0)
        return OK;
    if (n > PZEIG_MAXN) {
        fprintf(stderr, "Error: pzeig: circuit matrix too large for the dense "
                "eigenvalue pole-zero method (%d > %d unknowns); "
                "unset 'pzeig' to use the Muller iteration.\n", n, PZEIG_MAXN);
        return E_METHOD;
    }

    G = TMALLOC(double, (size_t) n * (size_t) n);
    C = TMALLOC(double, (size_t) n * (size_t) n);
    M = TMALLOC(double, (size_t) n * (size_t) n);
    wr = TMALLOC(double, n);
    wi = TMALLOC(double, n);
    rhs = TMALLOC(double, n + 1);
    irhs = TMALLOC(double, n + 1);
    roots = TMALLOC(SPcomplex, n);

    /* --- extract the pencil: G = A(0), C = A(1) - A(0) --------------------- */
    s.real = 0.0; s.imag = 0.0;
    error = CKTpzLoad(ckt, &s);
    if (error != OK) goto done;
    SMPdenseExtractReal(ckt->CKTmatrix, n, G);

    s.real = 1.0;
    error = CKTpzLoad(ckt, &s);
    if (error != OK) goto done;
    SMPdenseExtractReal(ckt->CKTmatrix, n, C);
    for (i = 0; i < n * n; i++)
        C[i] -= G[i];

    /* affinity check at an arbitrary third point: A(s2) == G + s2*C */
    s.real = 137.0;
    error = CKTpzLoad(ckt, &s);
    if (error != OK) goto done;
    SMPdenseExtractReal(ckt->CKTmatrix, n, M);
    for (i = 0; i < n * n; i++) {
        double want = G[i] + 137.0 * C[i];
        double scale = fabs(G[i]) + 137.0 * fabs(C[i]) + 1.0;
        if (fabs(M[i] - want) > 1e-9 * scale) {
            fprintf(stderr, "Error: pzeig: the small-signal matrix is not "
                    "affine in s (a device loads a non-polynomial frequency "
                    "dependence); unset 'pzeig' to use the Muller iteration.\n");
            error = E_METHOD;
            goto done;
        }
    }

    /* --- factor (G + sigma*C) at a non-root shift -------------------------- */
    nshift = (int) (sizeof shifts / sizeof shifts[0]);
    for (k = 0; k < nshift; k++) {
        sigma = shifts[k];
        s.real = sigma; s.imag = 0.0;
        error = CKTpzLoad(ckt, &s);
        if (error != OK) goto done;
        error = SMPcReorder(ckt->CKTmatrix, ckt->CKTpivotAbsTol, 0.0, &numswaps);
        if (error == OK)
            break;
        if (error != E_SINGULAR)
            goto done;
    }
    if (error != OK) {
        fprintf(stderr, "Error: pzeig: could not find a non-singular shift "
                "for the pencil (matrix singular at every trial shift).\n");
        goto done;
    }

    /* --- M = (G + sigma*C)^{-1} C  by n sparse solves ----------------------- */
    for (j = 0; j < n; j++) {
        rhs[0] = 0.0; irhs[0] = 0.0;
        for (i = 0; i < n; i++) {
            rhs[i + 1] = C[(size_t) i * (size_t) n + (size_t) j];
            irhs[i + 1] = 0.0;
        }
        SMPcSolve(ckt->CKTmatrix, rhs, irhs, NULL, NULL);
        for (i = 0; i < n; i++)
            M[(size_t) i * (size_t) n + (size_t) j] = rhs[i + 1];
    }

    /* infinity threshold: |mu| at or below the dense-eigenvalue noise floor
     * corresponds to the pencil's infinite eigenvalues */
    normM = 0.0;
    for (i = 0; i < n; i++) {
        double rsum = 0.0;
        for (j = 0; j < n; j++)
            rsum += fabs(M[(size_t) i * (size_t) n + (size_t) j]);
        if (rsum > normM)
            normM = rsum;
    }
    mu_tol = 64.0 * (double) n * DBL_EPSILON * normM;

    /* --- eigenvalues of M --------------------------------------------------- */
    if (densereal_eig(n, M, wr, wi) != 0) {
        fprintf(stderr, "Error: pzeig: the QR eigenvalue iteration failed to "
                "converge.\n");
        error = E_METHOD;
        goto done;
    }

    /* --- map mu -> s = sigma - 1/mu, drop infinite eigenvalues -------------- */
    for (k = 0; k < n; k++) {
        double m2 = wr[k] * wr[k] + wi[k] * wi[k];
        if (sqrt(m2) <= mu_tol)
            continue;                       /* infinite eigenvalue of the pencil */
        if (wi[k] < 0.0)
            continue;                       /* conjugate handled with its mate  */
        roots[nroots].real = sigma - wr[k] / m2;
        roots[nroots].imag = wi[k] / m2;    /* -1/mu: imag = +wi/|mu|^2 */
        nroots++;
    }

    qsort(roots, (size_t) nroots, sizeof(SPcomplex), root_cmp);

    /* --- build the PZtrial list PZpost expects ------------------------------ */
    for (k = 0; k < nroots; k++) {
        PZtrial *t = TMALLOC(PZtrial, 1);
        ZERO(t, PZtrial);
        t->s = roots[k];
        t->multiplicity = 1;
        *tailp = t;
        tailp = &t->next;
        count += (roots[k].imag != 0.0) ? 2 : 1;
    }

    *rootinfo = head;
    *rootcount = count;
    error = OK;

done:
    tfree(G); tfree(C); tfree(M);
    tfree(wr); tfree(wi);
    tfree(rhs); tfree(irhs);
    tfree(roots);
    if (error != OK) {
        while (head) {
            PZtrial *t = head;
            head = head->next;
            tfree(t);
        }
    }
    return error;
}
