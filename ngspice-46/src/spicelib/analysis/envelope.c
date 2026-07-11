/* Enhancement-154: Envelope Following analysis.
 *
 * The last remaining RF analysis. A carrier-driven circuit whose amplitude/phase
 * modulates slowly over MANY carrier periods (a ringing resonator, a settling PLL,
 * a modulated PA) is expensive to simulate with a plain `.tran` -- every one of the
 * thousands of fast carrier cycles must be integrated. Envelope following samples
 * the state once per carrier period T=1/fc and integrates the SLOW drift of those
 * samples, jumping M carrier periods at a time.
 *
 * The exact per-period map is  X_{n+1} = phi(X_n),  where phi(x) integrates the DAE
 * one carrier period T from x. Treating n as continuous, the envelope obeys
 * dX/dn ~ phi(X)-X. A naive FORWARD-Euler jump  X_{n+M} = X_n + M*(phi(X_n)-X_n)
 * is UNSTABLE for high-Q / oscillatory circuits (the one-period map has eigenvalues
 * on the unit circle, so I + M*(Phi-I) amplifies): it blows up. This analysis uses
 * the IMPLICIT backward-Euler jump
 *     X_{n+M} = X_n + M*(phi(X_{n+M}) - X_{n+M})
 *     G(Y) = Y - X_n - M*(phi(Y) - Y) = 0,   Newton:  [(1+M)I - M*Phi] dY = -G
 * with Phi = dphi/dY the one-period MONODROMY matrix (finite-differenced). The
 * implicit step is A-stable, so it tracks the envelope of a resonator without
 * blowing up, and its fixed point is the true per-period sequence -> the correct
 * steady state. The step size M is chosen by a step-doubling local-truncation-error
 * control (one jump of M vs two of M/2), like transient LTE step control.
 *
 * The one-period map is integrated with the ngspice transient primitives on a fixed
 * grid of `nppp` points, in TRAPEZOIDAL mode (backward-Euler numerically damps a
 * high-Q resonance -- trapezoidal does not). To keep phi(X) EXACT (no restart
 * damping), the full integrator state -- node/branch vector plus the charge/flux
 * history -- is snapshotted at the sample point and restored before each one-period
 * integration, so the trapezoidal history is consistent and no per-period re-init is
 * needed. The observable's fundamental Fourier coefficient over the period gives the
 * reported envelope amplitude 2|V1|. The monodromy is a dense N*N solve (N = matrix
 * size), capped for modest circuits -- like the PAC/HB conversion-matrix solves.
 */

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/sperror.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define EF_MAXN     400     /* dense-monodromy circuit-size cap */
#define EF_NEWTON   8       /* max implicit-envelope Newton iterations */

/* ---- small dense LU (partial pivoting), 1-based A[(i)*(n+1)+j] */
static int ef_lu(double *A, int *piv, int n)
{
    int i, j, k, p;
    for (i = 1; i <= n; i++) piv[i] = i;
    for (k = 1; k <= n; k++) {
        double amax = 0.0; p = k;
        for (i = k; i <= n; i++) {
            double a = fabs(A[i*(n+1)+k]);
            if (a > amax) { amax = a; p = i; }
        }
        if (amax == 0.0) return 1;
        if (p != k) {
            int t = piv[k]; piv[k] = piv[p]; piv[p] = t;
            for (j = 1; j <= n; j++) {
                double tmp = A[k*(n+1)+j]; A[k*(n+1)+j] = A[p*(n+1)+j]; A[p*(n+1)+j] = tmp;
            }
        }
        for (i = k+1; i <= n; i++) {
            double f = A[i*(n+1)+k] / A[k*(n+1)+k];
            A[i*(n+1)+k] = f;
            for (j = k+1; j <= n; j++) A[i*(n+1)+j] -= f * A[k*(n+1)+j];
        }
    }
    return 0;
}

static void ef_lusolve(const double *A, const int *piv, int n, const double *b, double *x)
{
    int i, j;
    double *y = TMALLOC(double, n+1);
    for (i = 1; i <= n; i++) y[i] = b[piv[i]];
    for (i = 2; i <= n; i++)
        for (j = 1; j < i; j++) y[i] -= A[i*(n+1)+j] * y[j];
    for (i = n; i >= 1; i--) {
        for (j = i+1; j <= n; j++) y[i] -= A[i*(n+1)+j] * y[j];
        y[i] /= A[i*(n+1)+i];
    }
    for (i = 1; i <= n; i++) x[i] = y[i];
    FREE(y);
}

/* one fixed sub-step of the transient integrator: rotate the state history, advance
 * by h, and Newton-solve. `order`=1 is backward-Euler (self-starting), 2 trapezoidal. */
static int ef_substep(CKTcircuit *ckt, double h, int order, long initmode)
{
    int i;
    double *tmp = ckt->CKTstates[ckt->CKTmaxOrder + 1];
    for (i = ckt->CKTmaxOrder; i >= 0; i--)
        ckt->CKTstates[i+1] = ckt->CKTstates[i];
    ckt->CKTstates[0] = tmp;
    ckt->CKTdelta = h;
    ckt->CKTdeltaOld[0] = h;
    ckt->CKTtime += h;
    ckt->CKTmode = MODETRAN | initmode;
    ckt->CKTorder = order;
    NIcomCof(ckt);
    return NIiter(ckt, ckt->CKTtranMaxIter) != 0 ? E_ITERLIM : OK;
}

/* phi(Y): SELF-STARTING one-period map -- set the node vector to Y at slow time t0
 * and integrate one carrier period. The integrator is re-initialized from Y so phi
 * is a true function of Y (no stale history). The first sub-step must be backward-
 * Euler (it is the only self-starting method), which numerically damps a high-Q
 * resonance; to make that damping negligible it is sub-divided into EF_RESTART tiny
 * BE steps, after which the period runs on non-dissipative trapezoidal. Accumulates
 * the observable's fundamental Fourier coefficient + DC. */
#define EF_RESTART 32
static int ef_phi(CKTcircuit *ckt, const double *Y, double t0, double fc, int nppp,
                  int obsNode, int N, double *xout,
                  double *amp, double *dc, double *re, double *im)
{
    double T = 1.0 / fc, h = T / nppp;
    double cre = 0.0, cim = 0.0, cdc = 0.0;
    int s, k, status;

    memcpy(ckt->CKTrhsOld, Y, (size_t)(N+1) * sizeof(double));
    ckt->CKTtime = t0;

    for (s = 0; s < nppp; s++) {
        if (s == 0) {
            /* self-start: EF_RESTART backward-Euler mini-steps spanning the first h */
            double hb = h / EF_RESTART;
            for (k = 0; k < EF_RESTART; k++) {
                status = ef_substep(ckt, hb, 1, k == 0 ? MODEINITTRAN : MODEINITPRED);
                if (status != OK) return status;
            }
        } else {
            status = ef_substep(ckt, h, 2, MODEINITPRED);
            if (status != OK) return status;
        }
        {
            double v  = ckt->CKTrhsOld[obsNode];
            double ph = 2.0 * M_PI * fc * (ckt->CKTtime - t0);
            cre += v * cos(ph);
            cim -= v * sin(ph);
            cdc += v;
        }
    }
    if (xout) memcpy(xout, ckt->CKTrhsOld, (size_t)(N+1) * sizeof(double));
    if (re)  *re  = cre / nppp;
    if (im)  *im  = cim / nppp;
    if (dc)  *dc  = cdc / nppp;
    if (amp) *amp = 2.0 * hypot(cre, cim) / nppp;
    return OK;
}

/* Phi = dphi/dY by forward finite differences (N period integrations). phiY=phi(Y). */
static int ef_monodromy(CKTcircuit *ckt, const double *Y, double t0,
                        double fc, int nppp, int obsNode, int N, double *phiY, double *Phi)
{
    double *Yp = TMALLOC(double, N+1);
    double *pp = TMALLOC(double, N+1);
    int j, i, status;

    status = ef_phi(ckt, Y, t0, fc, nppp, obsNode, N, phiY, NULL, NULL, NULL, NULL);
    if (status != OK) goto done;

    for (j = 1; j <= N; j++) {
        double d = 1e-6 * (fabs(Y[j]) + 1e-6);
        memcpy(Yp, Y, (size_t)(N+1) * sizeof(double));
        Yp[j] += d;
        status = ef_phi(ckt, Yp, t0, fc, nppp, obsNode, N, pp, NULL, NULL, NULL, NULL);
        if (status != OK) goto done;
        for (i = 1; i <= N; i++)
            Phi[i*(N+1)+j] = (pp[i] - phiY[i]) / d;
    }
done:
    FREE(Yp); FREE(pp);
    return status;
}

/* One implicit backward-Euler envelope jump of M carrier periods from node vector x
 * at slow time t0. Modified Newton: monodromy + LU factored once at the predictor,
 * correctors re-evaluate only phi. Result in xnew. */
static int ef_be_jump(CKTcircuit *ckt, const double *x, double t0,
                      double fc, int nppp, int obsNode, int N, double M, double *xnew)
{
    double *Y    = TMALLOC(double, N+1);
    double *phiY = TMALLOC(double, N+1);
    double *G    = TMALLOC(double, N+1);
    double *dY   = TMALLOC(double, N+1);
    double *Phi  = TMALLOC(double, (size_t)(N+1)*(size_t)(N+1));
    double *J    = TMALLOC(double, (size_t)(N+1)*(size_t)(N+1));
    int    *piv  = TMALLOC(int, N+1);
    int i, j, it, status;

    status = ef_phi(ckt, x, t0, fc, nppp, obsNode, N, phiY, NULL, NULL, NULL, NULL);
    if (status != OK) goto done;
    for (i = 1; i <= N; i++) Y[i] = x[i] + M * (phiY[i] - x[i]);   /* FE predictor seed */

    status = ef_monodromy(ckt, Y, t0, fc, nppp, obsNode, N, phiY, Phi);
    if (status != OK) goto done;
    for (i = 1; i <= N; i++)
        for (j = 1; j <= N; j++)
            J[i*(N+1)+j] = (i == j ? (1.0 + M) : 0.0) - M * Phi[i*(N+1)+j];
    if (ef_lu(J, piv, N)) { status = E_SINGULAR; goto done; }

    for (it = 0; it < EF_NEWTON; it++) {
        double nrm = 0.0, ynrm = 0.0;
        if (it > 0) {
            status = ef_phi(ckt, Y, t0, fc, nppp, obsNode, N, phiY, NULL, NULL, NULL, NULL);
            if (status != OK) goto done;
        }
        for (i = 1; i <= N; i++)
            G[i] = Y[i] - x[i] - M * (phiY[i] - Y[i]);
        ef_lusolve(J, piv, N, G, dY);
        for (i = 1; i <= N; i++) { Y[i] -= dY[i]; nrm += dY[i]*dY[i]; ynrm += Y[i]*Y[i]; }
        if (sqrt(nrm) <= 1e-10 * (sqrt(ynrm) + 1e-15))
            break;
    }
    memcpy(xnew, Y, (size_t)(N+1) * sizeof(double));
done:
    FREE(Y); FREE(phiY); FREE(G); FREE(dY); FREE(Phi); FREE(J); FREE(piv);
    return status;
}

/* ---- driver ------------------------------------------------------------------ */
int
EFanalysis(CKTcircuit *ckt, int obsNode, double fc, double tstop,
           int nppp, int M0, int Mmax, double reltol,
           double *o_time, double *o_amp, double *o_dc, double *o_re, double *o_im,
           int maxpts)
{
    double T = 1.0 / fc;
    int N = SMPmatSize(ckt->CKTmatrix);
    double *x, *Yb, *Yh, *Yh2;
    double t, t_start, M = M0, amp, dc, re, im;
    int npts = 0;
    long np_total, n_done = 0;
    int    save_method = ckt->CKTintegrateMethod, save_order = ckt->CKTorder;
    int    save_maxord = ckt->CKTmaxOrder;
    long   save_mode = ckt->CKTmode;
    double save_time = ckt->CKTtime, save_delta = ckt->CKTdelta, save_xmu = ckt->CKTxmu;

    if (N < 1 || N > EF_MAXN) {
        fprintf(stderr, "Error: envelope: matrix size %d out of range (1..%d).\n", N, EF_MAXN);
        return -1;
    }
    if (obsNode < 1 || obsNode > N) {
        fprintf(stderr, "Error: envelope: observable node index %d out of range.\n", obsNode);
        return -1;
    }

    ckt->CKTintegrateMethod = TRAPEZOIDAL;
    ckt->CKTxmu = 0.5;
    if (ckt->CKTmaxOrder < 2) ckt->CKTmaxOrder = 2;

    t_start = ckt->CKTtime;
    t = t_start;
    np_total = (long) floor(tstop * fc + 0.5);
    if (np_total < 1) np_total = 1;

    x   = TMALLOC(double, N+1);
    Yb  = TMALLOC(double, N+1);
    Yh  = TMALLOC(double, N+1);
    Yh2 = TMALLOC(double, N+1);

    /* start from the settled operating point */
    memcpy(x, ckt->CKTrhsOld, (size_t)(N+1) * sizeof(double));

    /* initial envelope sample: one self-started period from x */
    if (ef_phi(ckt, x, t_start, fc, nppp, obsNode, N, NULL, &amp, &dc, &re, &im) != OK) {
        fprintf(stderr, "Error: envelope: initial period integration failed to converge.\n");
        npts = -1; goto cleanup;
    }
    o_time[npts] = t_start; o_amp[npts] = amp; o_dc[npts] = dc;
    o_re[npts] = 2.0*re; o_im[npts] = 2.0*im; npts++;

    while (n_done < np_total && npts < maxpts) {
        double lte;
        long Ml;
        if (M > Mmax) M = Mmax;
        if (M > (double)(np_total - n_done)) M = (double)(np_total - n_done);
        if (M < 1.0) M = 1.0;
        Ml = (long) M;

        if (ef_be_jump(ckt, x, t, fc, nppp, obsNode, N, (double)Ml, Yb) != OK) {
            fprintf(stderr, "Error: envelope: envelope Newton failed at t=%g.\n", t);
            npts = -1; goto cleanup;
        }

        if (Ml >= 2) {
            long Ma = Ml/2, Mbb = Ml - Ma;
            double d = 0.0, ss = 0.0;
            int i;
            if (ef_be_jump(ckt, x, t, fc, nppp, obsNode, N, (double)Ma, Yh) != OK ||
                ef_be_jump(ckt, Yh, t + (double)Ma*T, fc, nppp, obsNode, N, (double)Mbb, Yh2) != OK) {
                npts = -1; goto cleanup;
            }
            for (i = 1; i <= N; i++) { d += (Yb[i]-Yh2[i])*(Yb[i]-Yh2[i]); ss += Yh2[i]*Yh2[i]; }
            lte = sqrt(d) / (sqrt(ss) + 1e-15);
            memcpy(Yb, Yh2, (size_t)(N+1) * sizeof(double));
        } else {
            lte = 0.0;
        }

        if (lte > reltol && Ml > 1) {
            M = floor(M / 2.0); if (M < 1.0) M = 1.0;
            continue;
        }

        memcpy(x, Yb, (size_t)(N+1) * sizeof(double));
        n_done += Ml;
        t = t_start + (double) n_done * T;

        /* record the amplitude at the jumped state (one self-started period) */
        if (ef_phi(ckt, x, t, fc, nppp, obsNode, N, NULL, &amp, &dc, &re, &im) != OK) {
            fprintf(stderr, "Error: envelope: period integration failed at t=%g.\n", t);
            npts = -1; goto cleanup;
        }
        o_time[npts] = t; o_amp[npts] = amp; o_dc[npts] = dc;
        o_re[npts] = 2.0*re; o_im[npts] = 2.0*im; npts++;

        if (lte < reltol / 4.0) M *= 2.0;
    }

cleanup:
    FREE(x); FREE(Yb); FREE(Yh); FREE(Yh2);
    ckt->CKTintegrateMethod = save_method;
    ckt->CKTorder = save_order;
    ckt->CKTmaxOrder = save_maxord;
    ckt->CKTmode = save_mode;
    ckt->CKTtime = save_time;
    ckt->CKTdelta = save_delta;
    ckt->CKTxmu = save_xmu;
    return npts;
}
