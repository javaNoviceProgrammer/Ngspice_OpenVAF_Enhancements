/* Dense real nonsymmetric eigenvalues (eigenvalues only), for the
 * eigenvalue-based pole-zero method (Enhancement-173).
 *
 * densereal_eig(n, a, wr, wi): all n eigenvalues of the n*n row-major real
 * matrix `a` (contents destroyed), real parts into wr[], imaginary parts into
 * wi[]. Complex eigenvalues come in conjugate pairs, stored adjacently with
 * the +imag member first. Returns 0 on success, 1 if the QR iteration failed
 * to converge on some eigenvalue.
 *
 * The classical three-stage dense algorithm (Wilkinson; the EISPACK
 * balanc/elmhes/hqr chain), written fresh:
 *   1. balance     -- diagonal similarity scaling to equalize row/column norms
 *                     (radix-2 exact scaling, no rounding error);
 *   2. Hessenberg  -- reduction by stabilized elementary similarity
 *                     transformations (Gaussian eliminations with pivoting);
 *   3. Francis QR  -- implicit double-shift QR iteration on the Hessenberg
 *                     form, deflating converged 1x1 / 2x2 trailing blocks.
 */

#include "ngspice/ngspice.h"
#include <math.h>

#define A(i,j) a[(size_t)(i) * (size_t)n + (size_t)(j)]

/* ---- stage 1: balance (radix-2, exact) ----------------------------------- */
static void eig_balance(int n, double *a)
{
    int i, j, done = 0;
    while (!done) {
        done = 1;
        for (i = 0; i < n; i++) {
            double r = 0.0, c = 0.0;
            for (j = 0; j < n; j++) {
                if (j != i) {
                    c += fabs(A(j, i));
                    r += fabs(A(i, j));
                }
            }
            if (c != 0.0 && r != 0.0) {
                double g = r / 2.0, f = 1.0, s = c + r;
                while (c < g) { f *= 2.0; c *= 4.0; }
                g = r * 2.0;
                while (c > g) { f /= 2.0; c /= 4.0; }
                if ((c + r) / f < 0.95 * s) {
                    done = 0;
                    g = 1.0 / f;
                    for (j = 0; j < n; j++) A(i, j) *= g;   /* row i /= f */
                    for (j = 0; j < n; j++) A(j, i) *= f;   /* col i *= f */
                }
            }
        }
    }
}

/* ---- stage 2: Hessenberg by stabilized elementary transformations -------- */
static void eig_hessenberg(int n, double *a)
{
    int m, i, j;
    for (m = 1; m < n - 1; m++) {
        double x = 0.0;
        int piv = m;
        for (i = m; i < n; i++) {          /* find pivot in column m-1 */
            if (fabs(A(i, m - 1)) > fabs(x)) {
                x = A(i, m - 1);
                piv = i;
            }
        }
        if (piv != m) {                    /* swap rows and columns piv <-> m */
            for (j = m - 1; j < n; j++) {
                double t = A(piv, j); A(piv, j) = A(m, j); A(m, j) = t;
            }
            for (j = 0; j < n; j++) {
                double t = A(j, piv); A(j, piv) = A(j, m); A(j, m) = t;
            }
        }
        if (x != 0.0) {
            for (i = m + 1; i < n; i++) {
                double y = A(i, m - 1);
                if (y != 0.0) {
                    y /= x;
                    A(i, m - 1) = y;       /* store multiplier (harmless) */
                    for (j = m; j < n; j++) A(i, j) -= y * A(m, j);
                    for (j = 0; j < n; j++) A(j, m) += y * A(j, i);
                }
            }
        }
    }
    /* zero the sub-subdiagonal (multipliers) so hqr sees a clean Hessenberg */
    for (i = 2; i < n; i++)
        for (j = 0; j < i - 1; j++)
            A(i, j) = 0.0;
}

/* ---- stage 3: Francis implicit double-shift QR (eigenvalues only) -------- */
static int eig_hqr(int n, double *a, double *wr, double *wi)
{
    int nn, m, l, k, j, i, its, mmin;
    double z, y, x, w, v, u, t, s, r = 0.0, q = 0.0, p = 0.0, anorm;

    anorm = 0.0;                            /* norm for small-element tests */
    for (i = 0; i < n; i++)
        for (j = (i > 0 ? i - 1 : 0); j < n; j++)
            anorm += fabs(A(i, j));
    if (anorm == 0.0) {
        for (i = 0; i < n; i++) { wr[i] = 0.0; wi[i] = 0.0; }
        return 0;
    }

    nn = n - 1;
    t = 0.0;
    while (nn >= 0) {
        its = 0;
        do {
            for (l = nn; l >= 1; l--) {     /* find small subdiagonal element */
                s = fabs(A(l - 1, l - 1)) + fabs(A(l, l));
                if (s == 0.0) s = anorm;
                if (fabs(A(l, l - 1)) + s == s) {
                    A(l, l - 1) = 0.0;
                    break;
                }
            }
            x = A(nn, nn);
            if (l == nn) {                  /* one real root found */
                wr[nn] = x + t;
                wi[nn] = 0.0;
                nn--;
            } else {
                y = A(nn - 1, nn - 1);
                w = A(nn, nn - 1) * A(nn - 1, nn);
                if (l == nn - 1) {          /* a 2x2 block: two roots */
                    p = 0.5 * (y - x);
                    q = p * p + w;
                    z = sqrt(fabs(q));
                    x += t;
                    if (q >= 0.0) {         /* real pair */
                        z = p + (p >= 0.0 ? z : -z);
                        wr[nn - 1] = wr[nn] = x + z;
                        if (z != 0.0) wr[nn] = x - w / z;
                        wi[nn - 1] = wi[nn] = 0.0;
                    } else {                /* complex conjugate pair */
                        wr[nn - 1] = wr[nn] = x + p;
                        wi[nn - 1] = z;
                        wi[nn] = -z;
                    }
                    nn -= 2;
                } else {                    /* no root yet: QR step */
                    if (its == 60)
                        return 1;
                    if (its == 10 || its == 20) {   /* exceptional shift */
                        t += x;
                        for (i = 0; i <= nn; i++) A(i, i) -= x;
                        s = fabs(A(nn, nn - 1)) + fabs(A(nn - 1, nn - 2));
                        y = x = 0.75 * s;
                        w = -0.4375 * s * s;
                    }
                    ++its;
                    for (m = nn - 2; m >= l; m--) { /* find two consecutive small
                                                       subdiagonals */
                        z = A(m, m);
                        r = x - z;
                        s = y - z;
                        p = (r * s - w) / A(m + 1, m) + A(m, m + 1);
                        q = A(m + 1, m + 1) - z - r - s;
                        r = A(m + 2, m + 1);
                        s = fabs(p) + fabs(q) + fabs(r);
                        p /= s; q /= s; r /= s;
                        if (m == l)
                            break;
                        u = fabs(A(m, m - 1)) * (fabs(q) + fabs(r));
                        v = fabs(p) * (fabs(A(m - 1, m - 1)) + fabs(z) + fabs(A(m + 1, m + 1)));
                        if (u + v == v)
                            break;
                    }
                    for (i = m + 2; i <= nn; i++) {
                        A(i, i - 2) = 0.0;
                        if (i != m + 2) A(i, i - 3) = 0.0;
                    }
                    for (k = m; k <= nn - 1; k++) { /* double QR sweep */
                        if (k != m) {
                            p = A(k, k - 1);
                            q = A(k + 1, k - 1);
                            r = 0.0;
                            if (k != nn - 1) r = A(k + 2, k - 1);
                            x = fabs(p) + fabs(q) + fabs(r);
                            if (x != 0.0) { p /= x; q /= x; r /= x; }
                        }
                        s = sqrt(p * p + q * q + r * r);
                        if (p < 0.0) s = -s;
                        if (s == 0.0)
                            continue;
                        if (k == m) {
                            if (l != m)
                                A(k, k - 1) = -A(k, k - 1);
                        } else {
                            A(k, k - 1) = -s * x;
                        }
                        p += s;
                        x = p / s; y = q / s; z = r / s;
                        q /= p;   r /= p;
                        for (j = k; j <= nn; j++) {     /* row modification */
                            p = A(k, j) + q * A(k + 1, j);
                            if (k != nn - 1) {
                                p += r * A(k + 2, j);
                                A(k + 2, j) -= p * z;
                            }
                            A(k + 1, j) -= p * y;
                            A(k, j) -= p * x;
                        }
                        mmin = (nn < k + 3) ? nn : k + 3;
                        for (i = l; i <= mmin; i++) {   /* column modification */
                            p = x * A(i, k) + y * A(i, k + 1);
                            if (k != nn - 1) {
                                p += z * A(i, k + 2);
                                A(i, k + 2) -= p * r;
                            }
                            A(i, k + 1) -= p * q;
                            A(i, k) -= p;
                        }
                    }
                }
            }
        } while (l < nn);
    }
    return 0;
}

int
densereal_eig(int n, double *a, double *wr, double *wi)
{
    if (n <= 0)
        return 0;
    if (n == 1) {
        wr[0] = a[0];
        wi[0] = 0.0;
        return 0;
    }
    eig_balance(n, a);
    eig_hessenberg(n, a);
    return eig_hqr(n, a, wr, wi);
}
