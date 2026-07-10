/**********
 Author: 2010-05 Stefano Perticaroli ``spertica''
 First Review: 2012-02 Francesco Lannutti and Stefano Perticaroli ``spertica''
 Second Review: 2012-10 Stefano Perticaroli ``spertica'' and Francesco Lannutti
**********/

/* Include files for the PSS analysis */
#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "cktaccept.h"
#include "ngspice/pssdefs.h"
#include "ngspice/devdefs.h"   /* Enhancement-120: DEVbindCSCComplex for the KLU AC stamp */
#include "ngspice/smpdefs.h"   /* Enhancement-120: SMPfindElt to read the Jacobian */
#include "ngspice/spmatrix.h"  /* Enhancement-120: spSetComplex (Sparse complex mode) */
#include "ngspice/noisedef.h"  /* Enhancement-124: NOISEAN/Ndata + CKTnoise for pnoise */
#include "ngspice/sperror.h"
#include "ngspice/fteext.h"

#ifdef XSPICE
/* gtri - add - wbk - Add headers */
#include "ngspice/miftypes.h"

#include "ngspice/evt.h"
#include "ngspice/enh.h"
#include "ngspice/mif.h"
#include "ngspice/evtproto.h"
#include "ngspice/ipctiein.h"
/* gtri - end - wbk - Add headers */
#endif

#define INIT_STATS() \
do { \
    startTime = SPfrontEnd->IFseconds();        \
    startIters = ckt->CKTstat->STATnumIter;     \
    startdTime = ckt->CKTstat->STATdecompTime;  \
    startsTime = ckt->CKTstat->STATsolveTime;   \
    startlTime = ckt->CKTstat->STATloadTime;    \
    startkTime = ckt->CKTstat->STATsyncTime;    \
} while(0)

#define UPDATE_STATS(analysis) \
do { \
    ckt->CKTcurrentAnalysis = analysis; \
    ckt->CKTstat->STATtranTime += SPfrontEnd->IFseconds() - startTime; \
    ckt->CKTstat->STATtranIter += ckt->CKTstat->STATnumIter - startIters; \
    ckt->CKTstat->STATtranDecompTime += ckt->CKTstat->STATdecompTime - startdTime; \
    ckt->CKTstat->STATtranSolveTime += ckt->CKTstat->STATsolveTime - startsTime; \
    ckt->CKTstat->STATtranLoadTime += ckt->CKTstat->STATloadTime - startlTime; \
    ckt->CKTstat->STATtranSyncTime += ckt->CKTstat->STATsyncTime - startkTime; \
} while(0)


/* Define some useful macro */
#define HISTORY 1024
#define GF_LAST 313

/* Enhancement-117: gate the shooting-loop trace behind `set ngdebug`.
 * The PSS shooting method prints per-iteration diagnostics (frequency estimate,
 * residual, breakpoint bookkeeping, delta control) that are invaluable while
 * debugging the method but overwhelm normal use -- a single .pss run emitted
 * ~230 lines of trace. Routed through PSSDBG they stay available (ngdebug on)
 * without polluting production output; genuine results/errors remain plain
 * fprintf. */
#define PSSDBG(...) do { if (ft_ngdebug) fprintf(stderr, __VA_ARGS__); } while(0)


static int
DFT(long int, int, double *, double *, double *, double, double *, double *, double *, double *, double *);


/* Enhancement-120: periodic small-signal Jacobian harmonics.
 *
 * PAC/pnoise/PXF linearize around the periodic operating point and solve a
 * harmonic conversion matrix whose blocks are the harmonics G_k, C_k of the
 * periodically time-varying device Jacobian G(t) = dI/dV, C(t) = dQ/dV. This
 * routine builds the first piece: it walks the retained operating point (E-119),
 * and at each stored sample restores that instant's node voltages + device
 * states, recomputes the small-signal linearization (CKTload with MODEINITSMSIG),
 * and stamps G + jC into the complex matrix (CKTacLoad at omega = 1). The
 * (osc,osc) diagonal read back is the osc node's conductance g(t) (real part) and
 * capacitance c(t) (imag part); their DFT gives the periodic Jacobian's harmonics
 * -- flat (DC only) for a linear circuit, rich for a pumped nonlinear one. The
 * osc-node diagonal is reported as a verifiable slice of the full G_k/C_k the PAC
 * conversion matrix (E-121) will be assembled from. */
static void
pss_jacobian_report(CKTcircuit *ckt, PSSan *job)
{
    long P = job->PSSopPoints, s;
    int  msize = job->PSSopMsize, ns = job->PSSopNumStates;
    int  onode = job->PSSoscNode ? job->PSSoscNode->number : 0;
    int  i, K = ckt->CKTharms;
    double thd;
    double *gt, *ct, *tt, *frq, *mag, *phs, *nmag, *nphs;

    if (onode <= 0 || onode > msize || P <= 0 || K <= 0)
        return;

    gt  = TMALLOC(double, P);   ct   = TMALLOC(double, P);   tt   = TMALLOC(double, P);
    frq = TMALLOC(double, K);   mag  = TMALLOC(double, K);   phs  = TMALLOC(double, K);
    nmag= TMALLOC(double, K);   nphs = TMALLOC(double, K);

    /* the complex AC stamps need the matrix in complex mode, otherwise
     * SMPcClear (spClear) leaves the imaginary part uncleared and C(t)
     * accumulates across samples. */
#ifdef KLU
    if (ckt->CKTmatrix->CKTkluMODE) {
        if (!ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex) {
            for (i = 0; i < DEVmaxnum; i++)
                if (DEVices[i] && DEVices[i]->DEVbindCSCComplex && ckt->CKThead[i])
                    DEVices[i]->DEVbindCSCComplex(ckt->CKThead[i], ckt);
            ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex;
        }
    } else
#endif
        spSetComplex(ckt->CKTmatrix->SPmatrix);

    for (s = 0; s < P; s++) {
        double *e;
        for (i = 1; i <= msize; i++)
            ckt->CKTrhsOld[i] = job->PSSopVoltages[(i - 1) + s * msize];
        ckt->CKTrhsOld[0] = 0.0;
        if (ns > 0)
            memcpy(ckt->CKTstate0, job->PSSopStates + (size_t)s * (size_t)ns,
                   (size_t)ns * sizeof(double));

        /* recompute the device linearization at this instant's bias */
        ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITSMSIG;
        CKTload(ckt);

        /* stamp G + jC (omega = 1 so the imaginary part is exactly C) */
        ckt->CKTomega = 1.0;
        ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEAC;
        CKTacLoad(ckt);

        e = (double *) SMPfindElt(ckt->CKTmatrix, onode, onode, 0);
        gt[s] = e ? e[0] : 0.0;   /* Real = conductance  G(t) */
        ct[s] = e ? e[1] : 0.0;   /* Imag = capacitance  C(t) (omega = 1) */
        tt[s] = job->PSSopTimes[s];
    }

    fprintf(stderr, "periodic small-signal Jacobian at osc node (%ld samples, %d harmonics):\n", P, K);
    DFT(P, K, &thd, tt, gt, job->PSSopFreq, frq, mag, phs, nmag, nphs);
    fprintf(stderr, "  G(t): DC = %.6g S", mag[0]);
    for (i = 1; i < K && i < 4; i++) fprintf(stderr, ", |G%d| = %.4g", i, mag[i]);
    fprintf(stderr, "\n");
    DFT(P, K, &thd, tt, ct, job->PSSopFreq, frq, mag, phs, nmag, nphs);
    fprintf(stderr, "  C(t): DC = %.6g F", mag[0]);
    for (i = 1; i < K && i < 4; i++) fprintf(stderr, ", |C%d| = %.4g", i, mag[i]);
    fprintf(stderr, "\n");

    FREE(gt); FREE(ct); FREE(tt);
    FREE(frq); FREE(mag); FREE(phs); FREE(nmag); FREE(nphs);
}


/* Enhancement-121: dense complex linear solve A x = b (Gaussian elimination with
 * partial pivoting), used for the small harmonic conversion matrix below. A is
 * n x n row-major in split real/imag arrays (Ar, Ai); b is length n in (br, bi)
 * and is overwritten with the solution x. Returns 0 on success, 1 if singular.
 * The conversion matrix is (2K+1)*msize -- tiny for the circuits PAC targets, so
 * a direct dense factor is simplest and exact; a production PAC on large circuits
 * would assemble this as a sparse block system instead. */
static int
pss_csolve(int n, double *Ar, double *Ai, double *br, double *bi)
{
    int i, j, k, piv;

    for (k = 0; k < n; k++) {
        /* partial pivot: largest |A[i][k]| in the remaining column */
        double amax = -1.0;
        piv = k;
        for (i = k; i < n; i++) {
            double m = Ar[i*n+k]*Ar[i*n+k] + Ai[i*n+k]*Ai[i*n+k];
            if (m > amax) { amax = m; piv = i; }
        }
        if (amax <= 0.0)
            return 1;                       /* singular */
        if (piv != k) {                     /* swap rows piv <-> k */
            for (j = 0; j < n; j++) {
                double t;
                t = Ar[piv*n+j]; Ar[piv*n+j] = Ar[k*n+j]; Ar[k*n+j] = t;
                t = Ai[piv*n+j]; Ai[piv*n+j] = Ai[k*n+j]; Ai[k*n+j] = t;
            }
            { double t; t = br[piv]; br[piv] = br[k]; br[k] = t;
                       t = bi[piv]; bi[piv] = bi[k]; bi[k] = t; }
        }
        /* eliminate below the pivot */
        {
            double dr = Ar[k*n+k], di = Ai[k*n+k], den = dr*dr + di*di;
            for (i = k+1; i < n; i++) {
                double fr = (Ar[i*n+k]*dr + Ai[i*n+k]*di) / den;   /* A[i][k]/A[k][k] */
                double fi = (Ai[i*n+k]*dr - Ar[i*n+k]*di) / den;
                for (j = k; j < n; j++) {
                    double pr = fr*Ar[k*n+j] - fi*Ai[k*n+j];
                    double pi = fr*Ai[k*n+j] + fi*Ar[k*n+j];
                    Ar[i*n+j] -= pr; Ai[i*n+j] -= pi;
                }
                { double pr = fr*br[k] - fi*bi[k];
                  double pi = fr*bi[k] + fi*br[k];
                  br[i] -= pr; bi[i] -= pi; }
            }
        }
    }
    /* back-substitution */
    for (k = n-1; k >= 0; k--) {
        double sr = br[k], si = bi[k];
        double dr, di, den;
        for (j = k+1; j < n; j++) {
            sr -= Ar[k*n+j]*br[j] - Ai[k*n+j]*bi[j];
            si -= Ar[k*n+j]*bi[j] + Ai[k*n+j]*br[j];
        }
        dr = Ar[k*n+k]; di = Ai[k*n+k]; den = dr*dr + di*di;
        br[k] = (sr*dr + si*di) / den;
        bi[k] = (si*dr - sr*di) / den;
    }
    return 0;
}


/* Enhancement-121: periodic AC (PAC) conversion-matrix engine.
 *
 * A circuit linearized about its PSS steady state has a T-periodic Jacobian, so a
 * small tone at f_in produces responses not only at f_in but at every sideband
 * f_in + k*f0 (k = -M..M). Collecting the harmonics G_k, C_k of the periodic
 * Jacobian (E-120, now for every matrix entry, not just the osc diagonal) into a
 * block matrix gives the harmonic conversion matrix H, block (n,m):
 *
 *     H_{nm} = G_{n-m} + j*omega_m*C_{n-m},   omega_m = 2*pi*(f_in + m*f0)
 *
 * of size (2M+1)*N. Solving H X = B for a stimulus B injected at one sideband
 * yields the responses X at all sidebands -- the conversion gains. This routine
 * assembles H, injects a unit current at the osc node in the 0-th sideband, solves,
 * and reports the response magnitude at the -1/0/+1 sidebands. For a *linear*
 * circuit the off-diagonal harmonics G_k,C_k (k!=0) vanish, so H is block-diagonal,
 * the 0-block is exactly the ordinary AC matrix at f_in, and the result is the AC
 * driving-point response at f_in with zero conversion to the other sidebands --
 * the verifiable slice. A pumped nonlinear circuit fills the off-diagonal blocks
 * and mixes energy between sidebands (real conversion gain). */
/* Enhancement-122: the periodic Jacobian harmonics G_k, C_k, extracted once from
 * the retained operating point and shared by the single-frequency diagnostic
 * (E-121, .pss) and the frequency sweep (E-122, .pac). */
struct pac_harm {
    int N;                          /* matrix size (unknowns) */
    int M;                          /* sidebands each side; harmonics span -2M..2M */
    int H;                          /* max harmonic index = 2M */
    int nnz;                        /* structural nonzeros of the Jacobian */
    int Ntot;                       /* (2M+1)*N -- conversion-matrix dimension */
    int *rr, *cc;                   /* nonzero row/col (1-based) */
    double *Gmr, *Gmi, *Cmr, *Cmi;  /* [nnz*(H+1)] complex harmonics G_h, C_h */
    /* Enhancement-123: the small-signal source RHS captured from CKTacLoad (the AC
     * stamp of netlist `AC`-flagged sources), used as the sideband-0 stimulus B_0
     * when present -- the source-referenced PAC input, else a unit current at the
     * osc node is injected as a fallback. Bias-independent, so captured once. */
    double *B0r, *B0i;              /* [N] source AC RHS (0-based, node j -> row j+1) */
    int    has_src;                 /* 1 if any netlist source stamped an AC value */
};

/* Walk the retained operating point, sample every Jacobian nonzero's G(t), C(t)
 * over the period and complex-DFT them to harmonics G_h, C_h (h = 0..2M). On
 * success fills hd (which then owns its arrays) and returns 0; else returns 1. */
static int
pac_extract_harmonics(CKTcircuit *ckt, PSSan *job, int M, struct pac_harm *hd)
{
    long   P = job->PSSopPoints, s;
    int    N = job->PSSopMsize, ns = job->PSSopNumStates;
    int    H = 2 * M, i, r, c, e, h, nnz;
    int    *rr, *cc;
    double *Gt, *Ct, *cw, *sw, *Gmr, *Gmi, *Cmr, *Cmi, *B0r, *B0i;
    int    has_src = 0;

    memset(hd, 0, sizeof(*hd));
    if (P <= 0 || N <= 0 || M < 1)
        return 1;

    /* matrix must be in complex mode so CKTacLoad's SMPcClear clears the imag part
     * (else C(t) accumulates across samples -- see E-120). */
#ifdef KLU
    if (ckt->CKTmatrix->CKTkluMODE) {
        if (!ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex) {
            for (i = 0; i < DEVmaxnum; i++)
                if (DEVices[i] && DEVices[i]->DEVbindCSCComplex && ckt->CKThead[i])
                    DEVices[i]->DEVbindCSCComplex(ckt->CKThead[i], ckt);
            ckt->CKTmatrix->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex;
        }
    } else
#endif
        spSetComplex(ckt->CKTmatrix->SPmatrix);

    /* establish the matrix structure: stamp G + jC at sample 0's bias */
    for (i = 1; i <= N; i++)
        ckt->CKTrhsOld[i] = job->PSSopVoltages[(i - 1)];
    ckt->CKTrhsOld[0] = 0.0;
    if (ns > 0)
        memcpy(ckt->CKTstate0, job->PSSopStates, (size_t)ns * sizeof(double));
    ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITSMSIG;
    CKTload(ckt);
    ckt->CKTomega = 1.0;
    ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEAC;
    CKTacLoad(ckt);

    /* Enhancement-123: capture the small-signal source RHS. CKTacLoad clears
     * CKTrhs/CKTirhs then lets each device stamp; a netlist source with an `AC`
     * spec stamps its (bias-independent) AC value here -- that vector is the
     * source-referenced PAC stimulus B_0. */
    B0r = TMALLOC(double, N);
    B0i = TMALLOC(double, N);
    for (i = 1; i <= N; i++) {
        B0r[i - 1] = ckt->CKTrhs[i];
        B0i[i - 1] = ckt->CKTirhs[i];
        if (B0r[i - 1] != 0.0 || B0i[i - 1] != 0.0)
            has_src = 1;
    }

    /* enumerate the structural nonzeros (SMPfindElt does not create) */
    nnz = 0;
    for (r = 1; r <= N; r++)
        for (c = 1; c <= N; c++)
            if (SMPfindElt(ckt->CKTmatrix, r, c, 0))
                nnz++;
    if (nnz <= 0)
        return 1;
    rr = TMALLOC(int, nnz);
    cc = TMALLOC(int, nnz);
    e = 0;
    for (r = 1; r <= N; r++)
        for (c = 1; c <= N; c++)
            if (SMPfindElt(ckt->CKTmatrix, r, c, 0)) { rr[e] = r; cc[e] = c; e++; }

    /* sample every nonzero of the periodic Jacobian G(t) + jC(t) over one period */
    Gt = TMALLOC(double, (size_t)nnz * (size_t)P);
    Ct = TMALLOC(double, (size_t)nnz * (size_t)P);
    for (s = 0; s < P; s++) {
        for (i = 1; i <= N; i++)
            ckt->CKTrhsOld[i] = job->PSSopVoltages[(i - 1) + s * N];
        ckt->CKTrhsOld[0] = 0.0;
        if (ns > 0)
            memcpy(ckt->CKTstate0, job->PSSopStates + (size_t)s * (size_t)ns,
                   (size_t)ns * sizeof(double));
        ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITSMSIG;
        CKTload(ckt);
        ckt->CKTomega = 1.0;
        ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEAC;
        CKTacLoad(ckt);
        for (e = 0; e < nnz; e++) {
            double *el = (double *) SMPfindElt(ckt->CKTmatrix, rr[e], cc[e], 0);
            Gt[(size_t)e * (size_t)P + (size_t)s] = el ? el[0] : 0.0;
            Ct[(size_t)e * (size_t)P + (size_t)s] = el ? el[1] : 0.0;
        }
    }

    /* complex DFT of each entry: harmonics h = 0..H (G_{-h} = conj(G_h) for real
     * G(t)). Uniform sampling over the period, so index-based twiddles suffice. */
    cw = TMALLOC(double, (size_t)(H + 1) * (size_t)P);
    sw = TMALLOC(double, (size_t)(H + 1) * (size_t)P);
    for (h = 0; h <= H; h++)
        for (s = 0; s < P; s++) {
            double ang = 2.0 * M_PI * (double)h * (double)s / (double)P;
            cw[(size_t)h * (size_t)P + (size_t)s] = cos(ang);
            sw[(size_t)h * (size_t)P + (size_t)s] = sin(ang);
        }
    Gmr = TMALLOC(double, (size_t)nnz * (size_t)(H + 1));
    Gmi = TMALLOC(double, (size_t)nnz * (size_t)(H + 1));
    Cmr = TMALLOC(double, (size_t)nnz * (size_t)(H + 1));
    Cmi = TMALLOC(double, (size_t)nnz * (size_t)(H + 1));
    for (e = 0; e < nnz; e++)
        for (h = 0; h <= H; h++) {
            double gr = 0, gi = 0, cr = 0, ci = 0;
            for (s = 0; s < P; s++) {
                double cs = cw[(size_t)h * (size_t)P + (size_t)s];
                double sn = sw[(size_t)h * (size_t)P + (size_t)s];
                double gv = Gt[(size_t)e * (size_t)P + (size_t)s];
                double cv = Ct[(size_t)e * (size_t)P + (size_t)s];
                gr += gv * cs;  gi -= gv * sn;
                cr += cv * cs;  ci -= cv * sn;
            }
            Gmr[(size_t)e * (size_t)(H + 1) + (size_t)h] = gr / (double)P;
            Gmi[(size_t)e * (size_t)(H + 1) + (size_t)h] = gi / (double)P;
            Cmr[(size_t)e * (size_t)(H + 1) + (size_t)h] = cr / (double)P;
            Cmi[(size_t)e * (size_t)(H + 1) + (size_t)h] = ci / (double)P;
        }

    FREE(Gt); FREE(Ct); FREE(cw); FREE(sw);

    hd->N = N;  hd->M = M;  hd->H = H;  hd->nnz = nnz;  hd->Ntot = (2*M + 1) * N;
    hd->rr = rr;  hd->cc = cc;
    hd->Gmr = Gmr;  hd->Gmi = Gmi;  hd->Cmr = Cmr;  hd->Cmi = Cmi;
    hd->B0r = B0r;  hd->B0i = B0i;  hd->has_src = has_src;
    return 0;
}

static void
pac_free_harmonics(struct pac_harm *hd)
{
    FREE(hd->rr);  FREE(hd->cc);
    FREE(hd->Gmr); FREE(hd->Gmi); FREE(hd->Cmr); FREE(hd->Cmi);
    FREE(hd->B0r); FREE(hd->B0i);
}

/* Assemble the conversion matrix H_{nm} = G_{n-m} + j*omega_m*C_{n-m} at input
 * frequency f_in and solve for a stimulus injected in the 0-th sideband. When
 * `use_src` is set and the netlist supplied an `AC` source, the captured source
 * RHS B_0 is the stimulus; otherwise a unit current is injected at node `inode`.
 * The solution X (all sidebands, length Ntot) is written to Xr/Xi, which the caller
 * allocates. Returns 0 on success, 1 if the matrix is singular. */
static int
pac_solve_at(struct pac_harm *hd, double f0, double f_in, int inode, int use_src,
             double *Xr, double *Xi)
{
    int    N = hd->N, M = hd->M, H = hd->H, nnz = hd->nnz, Ntot = hd->Ntot;
    int    ni, mi, n, mm, e, rc, j;
    double *Ar, *Ai;

    Ar = TMALLOC(double, (size_t)Ntot * (size_t)Ntot);
    Ai = TMALLOC(double, (size_t)Ntot * (size_t)Ntot);
    memset(Ar, 0, (size_t)Ntot * (size_t)Ntot * sizeof(double));
    memset(Ai, 0, (size_t)Ntot * (size_t)Ntot * sizeof(double));
    for (ni = 0; ni <= 2*M; ni++) {
        n = ni - M;
        for (mi = 0; mi <= 2*M; mi++) {
            int dm;
            double omega;
            mm = mi - M;
            dm = n - mm;                                   /* harmonic index, -H..H */
            omega = 2.0 * M_PI * (f_in + (double)mm * f0);
            for (e = 0; e < nnz; e++) {
                double gr, gi, cr, ci;
                size_t hi = (size_t)e * (size_t)(H + 1) + (size_t)abs(dm);
                gr = hd->Gmr[hi]; gi = hd->Gmi[hi];
                cr = hd->Cmr[hi]; ci = hd->Cmi[hi];
                if (dm < 0) { gi = -gi; ci = -ci; }        /* conjugate for -h */
                {
                    double er = gr - omega * ci;           /* (g) + j*omega*(c) */
                    double ei = gi + omega * cr;
                    size_t row = (size_t)ni * (size_t)N + (size_t)(hd->rr[e] - 1);
                    size_t col = (size_t)mi * (size_t)N + (size_t)(hd->cc[e] - 1);
                    Ar[row * (size_t)Ntot + col] += er;
                    Ai[row * (size_t)Ntot + col] += ei;
                }
            }
        }
    }

    /* stimulus in the 0-th sideband: netlist AC source RHS, or a unit current */
    memset(Xr, 0, (size_t)Ntot * sizeof(double));
    memset(Xi, 0, (size_t)Ntot * sizeof(double));
    if (use_src && hd->has_src) {
        for (j = 0; j < N; j++) {
            Xr[(size_t)M * (size_t)N + (size_t)j] = hd->B0r[j];
            Xi[(size_t)M * (size_t)N + (size_t)j] = hd->B0i[j];
        }
    } else {
        Xr[(size_t)M * (size_t)N + (size_t)(inode - 1)] = 1.0;
    }
    rc = pss_csolve(Ntot, Ar, Ai, Xr, Xi);
    FREE(Ar); FREE(Ai);
    return rc;
}

/* pick sideband count M from the requested harmonics; conversion matrix is
 * (2M+1)*N, so cap M so the dense solve stays small. Returns 0 if unusable. */
static int
pac_choose_M(CKTcircuit *ckt, PSSan *job)
{
    int K = ckt->CKTharms, N = job->PSSopMsize, M;
    M = (K - 1 < 3) ? (K - 1) : 3;
    if (M < 1)
        return 0;
    while (M > 1 && (2*M + 1) * N > 400)     /* dense-solve guard */
        M--;
    if ((2*M + 1) * N > 400)
        return 0;
    return M;
}

/* Enhancement-121: single-frequency PAC diagnostic, reported for a plain .pss. */
static void
pss_pac_report(CKTcircuit *ckt, PSSan *job)
{
    int    N = job->PSSopMsize, onode = job->PSSoscNode ? job->PSSoscNode->number : 0;
    int    M, e, n;
    double f0 = job->PSSopFreq, f_in;
    struct pac_harm hd;
    double *Xr, *Xi;

    if (onode <= 0 || onode > N || f0 <= 0.0)
        return;
    M = pac_choose_M(ckt, job);
    if (M < 1 || pac_extract_harmonics(ckt, job, M, &hd))
        return;

    f_in = 0.5 * f0;                            /* probe input frequency */
    Xr = TMALLOC(double, hd.Ntot);
    Xi = TMALLOC(double, hd.Ntot);
    if (pac_solve_at(&hd, f0, f_in, onode, 0, Xr, Xi) == 0) {   /* unit-I probe */
        double g0 = 0, c0 = 0, zexp;
        for (e = 0; e < hd.nnz; e++)
            if (hd.rr[e] == onode && hd.cc[e] == onode) {
                g0 = hd.Gmr[(size_t)e * (size_t)(hd.H + 1)];   /* h = 0 */
                c0 = hd.Cmr[(size_t)e * (size_t)(hd.H + 1)];
            }
        zexp = 1.0 / hypot(g0, 2.0 * M_PI * f_in * c0);
        fprintf(stderr, "PAC conversion matrix: f_in = %.6g Hz, %d sidebands, "
                        "unit I at osc node\n", f_in, 2*M + 1);
        for (n = -1; n <= 1; n++) {
            size_t idx = (size_t)(n + M) * (size_t)N + (size_t)(onode - 1);
            fprintf(stderr, "  sideband %+d (%.6g Hz): |V| = %.6g\n",
                    n, f_in + (double)n * f0, hypot(Xr[idx], Xi[idx]));
        }
        fprintf(stderr, "  expected sideband-0 driving-point |Z| = %.6g Ohm "
                        "(linear, from G0/C0)\n", zexp);
    }
    FREE(Xr); FREE(Xi);
    pac_free_harmonics(&hd);
}

/* Enhancement-122/123: PAC frequency sweep (.pac). Extract the Jacobian harmonics
 * once, then sweep the input frequency and, at each point, solve the conversion
 * matrix and emit the response at each requested sideband f_in + k*f0 as a complex
 * plot vs frequency. The stimulus is a netlist-referenced small-signal `AC` source
 * when present (the periodic-AC transfer / conversion gain), else a unit current at
 * the osc node (a driving-point PAC). With `pac_maxsb = Ksb` the output vectors are
 * the base node names (sideband 0) plus `<node>_usb<k>` / `<node>_lsb<k>` for the
 * upper/lower conversion sidebands. */
static void
pac_sweep(CKTcircuit *ckt, PSSan *job)
{
    int    N = job->PSSopMsize, onode = job->PSSoscNode ? job->PSSoscNode->number : 0;
    int    M, Ksb, nsb, j, s, k, numNames, nout, error;
    int    stepType = job->PACstepType, np = job->PACpoints;
    double f0 = job->PSSopFreq, fstart = job->PACfStart, fstop = job->PACfStop;
    double freq, mult, linstep;
    struct pac_harm hd;
    double *Xr, *Xi;
    IFuid  freqUid, *nameList = NULL, *outNames = NULL;
    runDesc *pacPlot = NULL;

    if (onode <= 0 || onode > N || f0 <= 0.0 || fstart <= 0.0 ||
        fstop < fstart || np < 1)
        return;
    M = pac_choose_M(ckt, job);
    if (M < 1) {
        fprintf(stderr, "PAC: conversion matrix too large -- sweep skipped\n");
        return;
    }
    if (pac_extract_harmonics(ckt, job, M, &hd))
        return;

    /* number of output sidebands each side (clamped to what the matrix carries) */
    Ksb = job->PACmaxSideband;
    if (Ksb < 0)  Ksb = 0;
    if (Ksb > M)  Ksb = M;
    nsb = 2 * Ksb + 1;

    /* build the output name list: base node names for sideband 0, plus
     * <node>_usb<k> / <node>_lsb<k> for the upper/lower conversion sidebands. */
    error = CKTnames(ckt, &numNames, &nameList);
    if (error || numNames != N) { pac_free_harmonics(&hd); FREE(nameList); return; }
    nout = numNames * nsb;
    outNames = TMALLOC(IFuid, nout);
    for (s = 0; s < nsb; s++) {
        k = s - Ksb;
        for (j = 0; j < numNames; j++) {
            if (k == 0) {
                outNames[s * numNames + j] = nameList[j];   /* reuse base UID */
            } else {
                char nm[256];
                IFuid uid;
                (void) snprintf(nm, sizeof(nm), "%s_%csb%d",
                                (char *) nameList[j], (k > 0) ? 'u' : 'l', abs(k));
                if (SPfrontEnd->IFnewUid(ckt, &uid, NULL, nm, UID_OTHER, NULL))
                    uid = nameList[j];                      /* fallback on clash */
                outNames[s * numNames + j] = uid;
            }
        }
    }

    SPfrontEnd->IFnewUid(ckt, &freqUid, NULL, "frequency", UID_OTHER, NULL);
    error = SPfrontEnd->OUTpBeginPlot(ckt, ckt->CKTcurJob, "PAC Analysis",
                                      freqUid, IF_REAL, nout, outNames,
                                      IF_COMPLEX, &pacPlot);
    tfree(nameList);
    tfree(outNames);
    if (error) { pac_free_harmonics(&hd); return; }
    if (stepType != 0)      /* dec / oct -> log frequency axis */
        SPfrontEnd->OUTattributes(pacPlot, NULL, OUT_SCALE_LOG, NULL);

    Xr = TMALLOC(double, hd.Ntot);
    Xi = TMALLOC(double, hd.Ntot);
    mult    = (stepType == 1) ? pow(10.0, 1.0 / np) :
              (stepType == 2) ? pow(2.0,  1.0 / np) : 0.0;
    linstep = (np > 1) ? (fstop - fstart) / (np - 1) : 0.0;

    fprintf(stderr, "PAC sweep: %s from %.6g to %.6g Hz (%d pts/%s) around "
                    "f0 = %.6g Hz; stimulus: %s; %d sideband%s\n",
            (stepType == 1) ? "dec" : (stepType == 2) ? "oct" : "lin",
            fstart, fstop, np,
            (stepType == 0) ? "total" : (stepType == 1) ? "decade" : "octave", f0,
            hd.has_src ? "netlist AC source" : "unit I at osc node",
            nsb, (nsb == 1) ? "" : "s");

    for (freq = fstart; freq <= fstop * (1.0 + 1e-9); ) {
        if (pac_solve_at(&hd, f0, freq, onode, 1, Xr, Xi) == 0) {
            IFvalue freqData, valueData;
            IFcomplex *data = TMALLOC(IFcomplex, nout);
            freqData.rValue = freq;
            valueData.v.numValue = nout;
            valueData.v.vec.cVec = data;
            for (s = 0; s < nsb; s++) {
                size_t blk = (size_t)(s - Ksb + M) * (size_t)N;   /* sideband block */
                for (j = 0; j < numNames; j++) {
                    data[s * numNames + j].real = Xr[blk + (size_t)j];
                    data[s * numNames + j].imag = Xi[blk + (size_t)j];
                }
            }
            SPfrontEnd->OUTpData(pacPlot, &freqData, &valueData);
            FREE(data);
        }
        if (stepType == 0) { if (np <= 1) break; freq += linstep; }
        else               { freq *= mult; }
    }

    SPfrontEnd->OUTendPlot(pacPlot);
    FREE(Xr); FREE(Xi);
    pac_free_harmonics(&hd);
}


/* Enhancement-124: solve the ADJOINT conversion system Hᵀ Psi = e_{out,0}. Psi
 * then holds, for every (node j, sideband k), the transfer from a unit injection
 * at (j,k) to the output at sideband 0 -- the conversion transimpedance the noise
 * folding needs. Assembles Hᵀ (the transpose of the pac_solve_at matrix) and puts a
 * unit at the output node in the 0-th sideband. Returns 0 on success, 1 if singular. */
static int
pac_solve_adjoint(struct pac_harm *hd, double f0, double f_in, int outNode,
                  double *Psr, double *Psi)
{
    int    N = hd->N, M = hd->M, H = hd->H, nnz = hd->nnz, Ntot = hd->Ntot;
    int    ni, mi, n, mm, e, rc;
    double *Ar, *Ai;

    Ar = TMALLOC(double, (size_t)Ntot * (size_t)Ntot);
    Ai = TMALLOC(double, (size_t)Ntot * (size_t)Ntot);
    memset(Ar, 0, (size_t)Ntot * (size_t)Ntot * sizeof(double));
    memset(Ai, 0, (size_t)Ntot * (size_t)Ntot * sizeof(double));
    for (ni = 0; ni <= 2*M; ni++) {
        n = ni - M;
        for (mi = 0; mi <= 2*M; mi++) {
            int dm;
            double omega;
            mm = mi - M;
            dm = n - mm;
            omega = 2.0 * M_PI * (f_in + (double)mm * f0);
            for (e = 0; e < nnz; e++) {
                double gr, gi, cr, ci;
                size_t hi = (size_t)e * (size_t)(H + 1) + (size_t)abs(dm);
                gr = hd->Gmr[hi]; gi = hd->Gmi[hi];
                cr = hd->Cmr[hi]; ci = hd->Cmi[hi];
                if (dm < 0) { gi = -gi; ci = -ci; }
                {
                    double er = gr - omega * ci;
                    double ei = gi + omega * cr;
                    size_t row = (size_t)ni * (size_t)N + (size_t)(hd->rr[e] - 1);
                    size_t col = (size_t)mi * (size_t)N + (size_t)(hd->cc[e] - 1);
                    Ar[col * (size_t)Ntot + row] += er;   /* transpose: [col][row] */
                    Ai[col * (size_t)Ntot + row] += ei;
                }
            }
        }
    }

    memset(Psr, 0, (size_t)Ntot * sizeof(double));
    memset(Psi, 0, (size_t)Ntot * sizeof(double));
    Psr[(size_t)M * (size_t)N + (size_t)(outNode - 1)] = 1.0;
    rc = pss_csolve(Ntot, Ar, Ai, Psr, Psi);
    FREE(Ar); FREE(Ai);
    return rc;
}


/* Enhancement-124: periodic noise (.pnoise). Runs off the retained operating point:
 * folds every device's noise through the conversion-matrix adjoint over all
 * sidebands to get the output noise spectrum. The device noise routines
 * (DEVnoise/NevalSrc, OSDI load_noise) compute S*|dTransimp|^2 reading the
 * transimpedance from CKTrhs/CKTirhs -- so loading the sideband-k adjoint into
 * CKTrhs and summing over k = -M..M folds the noise exactly. A local NOISEAN job
 * gives those routines their expected context. For a linear (block-diagonal)
 * circuit only sideband 0 contributes, so the result reduces to ordinary .noise. */
static void
pnoise_sweep(CKTcircuit *ckt, PSSan *job)
{
    int    N = job->PSSopMsize, ns = job->PSSopNumStates;
    int    outNode = job->PnOutNode ? job->PnOutNode->number : 0;
    int    M, i, j, k, np = job->PACpoints, stepType = job->PACstepType, error;
    double f0 = job->PSSopFreq, fstart = job->PACfStart, fstop = job->PACfStop;
    double freq, mult, linstep;
    struct pac_harm hd;
    double *Psr, *Psi, *Xr, *Xi;
    NOISEAN nj;
    Ndata   data;
    JOB    *oldJob;
    IFuid   freqUid, nlist[2];
    runDesc *plot = NULL;

    if (outNode <= 0 || outNode > N || f0 <= 0.0 || fstart <= 0.0 ||
        fstop < fstart || np < 1)
        return;
    M = pac_choose_M(ckt, job);
    if (M < 1) {
        fprintf(stderr, "PNOISE: conversion matrix too large -- sweep skipped\n");
        return;
    }
    if (pac_extract_harmonics(ckt, job, M, &hd))
        return;

    /* set the device bias to the (sample-0) operating point so each noise PSD
     * (conductances, dc currents) is evaluated at the periodic operating point. */
    for (i = 1; i <= N; i++)
        ckt->CKTrhsOld[i] = job->PSSopVoltages[(i - 1)];
    ckt->CKTrhsOld[0] = 0.0;
    if (ns > 0)
        memcpy(ckt->CKTstate0, job->PSSopStates, (size_t)ns * sizeof(double));
    ckt->CKTmode = (ckt->CKTmode & MODEUIC) | MODEDCOP | MODEINITSMSIG;
    CKTload(ckt);

    /* output plot (onoise/inoise spectrum vs frequency), opened while CKTcurJob is
     * still the persistent PSS job. */
    SPfrontEnd->IFnewUid(ckt, &freqUid, NULL, "frequency", UID_OTHER, NULL);
    SPfrontEnd->IFnewUid(ckt, &nlist[0], NULL, "onoise_spectrum", UID_OTHER, NULL);
    SPfrontEnd->IFnewUid(ckt, &nlist[1], NULL, "inoise_spectrum", UID_OTHER, NULL);
    error = SPfrontEnd->OUTpBeginPlot(ckt, ckt->CKTcurJob, "PNoise Analysis",
                                      freqUid, IF_REAL, 2, nlist, IF_REAL, &plot);
    if (error) { pac_free_harmonics(&hd); return; }
    if (stepType != 0)
        SPfrontEnd->OUTattributes(plot, NULL, OUT_SCALE_LOG, NULL);

    /* a minimal NOISEAN context for the device noise routines (they cast
     * CKTcurJob to NOISEAN* and read NStpsSm / NstartFreq). */
    memset(&nj, 0, sizeof(nj));
    nj.output = job->PnOutNode;
    nj.outputRef = job->PnOutNode;
    nj.input = job->PnInSrc;
    nj.NstartFreq = fstart;
    nj.NstopFreq = fstop;
    nj.NnumSteps = np;
    nj.NstpType = stepType;
    nj.NStpsSm = 0;                 /* no per-device summary vectors */
    nj.JOBname = "pnoise";
    memset(&data, 0, sizeof(data));
    data.prtSummary = FALSE;        /* keep the routines from writing outpVector */

    oldJob = ckt->CKTcurJob;
    ckt->CKTcurJob = (JOB *) &nj;

    /* let each device set up its noise state (a no-op naming pass with NStpsSm=0) */
    for (i = 0; i < DEVmaxnum; i++)
        if (DEVices[i] && DEVices[i]->DEVnoise && ckt->CKThead[i]) {
            double dummy = 0.0;
            DEVices[i]->DEVnoise(N_DENS, N_OPEN, ckt->CKThead[i], ckt, &data, &dummy);
        }

    Psr = TMALLOC(double, hd.Ntot);  Psi = TMALLOC(double, hd.Ntot);
    Xr  = TMALLOC(double, hd.Ntot);  Xi  = TMALLOC(double, hd.Ntot);
    mult    = (stepType == 1) ? pow(10.0, 1.0 / np) :
              (stepType == 2) ? pow(2.0,  1.0 / np) : 0.0;
    linstep = (np > 1) ? (fstop - fstart) / (np - 1) : 0.0;

    fprintf(stderr, "PNOISE sweep: %s from %.6g to %.6g Hz around f0 = %.6g Hz; "
                    "output node %d; folding %d sidebands\n",
            (stepType == 1) ? "dec" : (stepType == 2) ? "oct" : "lin",
            fstart, fstop, f0, outNode, 2*M + 1);

    for (freq = fstart; freq <= fstop * (1.0 + 1e-9); ) {
        double onoise = 0.0, gain2 = 1.0, gsi;

        data.freq = freq;
        data.delFreq = 0.0;         /* density only -- we do not integrate here */
        data.prtSummary = FALSE;

        /* transfer from every (node, sideband) to the output at sideband 0 */
        if (pac_solve_adjoint(&hd, f0, freq, outNode, Psr, Psi) == 0) {
            for (k = -M; k <= M; k++) {
                double dens = 0.0;
                size_t blk = (size_t)(k + M) * (size_t)N;
                for (j = 1; j <= N; j++) {
                    ckt->CKTrhs[j]  = Psr[blk + (size_t)(j - 1)];
                    ckt->CKTirhs[j] = Psi[blk + (size_t)(j - 1)];
                }
                ckt->CKTrhs[0] = 0.0;  ckt->CKTirhs[0] = 0.0;
                for (i = 0; i < DEVmaxnum; i++)
                    if (DEVices[i] && DEVices[i]->DEVnoise && ckt->CKThead[i])
                        DEVices[i]->DEVnoise(N_DENS, N_CALC, ckt->CKThead[i],
                                             ckt, &data, &dens);
                onoise += dens;                 /* sum device noise over sidebands */
            }
        }

        /* input-referred: divide by the source->output conversion gain (sideband 0) */
        if (hd.has_src && pac_solve_at(&hd, f0, freq, outNode, 1, Xr, Xi) == 0) {
            size_t oidx = (size_t)M * (size_t)N + (size_t)(outNode - 1);
            gain2 = Xr[oidx] * Xr[oidx] + Xi[oidx] * Xi[oidx];
        }
        gsi = 1.0 / MAX(gain2, N_MINGAIN);

        {
            IFvalue refVal, valData;
            double out[2];
            out[0] = onoise;                    /* output noise density (V^2/Hz) */
            out[1] = onoise * gsi;              /* input-referred density */
            refVal.rValue = freq;
            valData.v.numValue = 2;
            valData.v.vec.rVec = out;
            SPfrontEnd->OUTpData(plot, &refVal, &valData);
        }

        if (stepType == 0) { if (np <= 1) break; freq += linstep; }
        else               { freq *= mult; }
    }

    SPfrontEnd->OUTendPlot(plot);
    ckt->CKTcurJob = oldJob;
    FREE(Psr); FREE(Psi); FREE(Xr); FREE(Xi);
    pac_free_harmonics(&hd);
}


int
DCpss(CKTcircuit *ckt,
       int restart)   /* forced restart flag */
{
    PSSan *job = (PSSan *) ckt->CKTcurJob;

    int i;
    double olddelta;
    double delta;
    double newdelta;
    double *temp;
    double startdTime;
    double startsTime;
    double startlTime;
    double startkTime;
    double startTime;
    int startIters;
    int converged;
    int firsttime;
    int error;
    int save_order;
    long save_mode;
    IFuid timeUid;
    IFuid *nameList;
    int numNames;
    double maxstepsize = 0.0;

    int ltra_num;
    CKTnode *node;

    /* New variables */
    int j, oscnNode;
    IFuid freqUid;

    enum {STABILIZATION, SHOOTING, PSS} pss_state = STABILIZATION;

    double err = 0, predsum = 0 ;
    double time_temp = 0, gf_history [HISTORY], rr_history [HISTORY], predsum_history [HISTORY], nextstep ;
    int msize, shooting_cycle_counter = 0;
    double *RHS_copy_se, *RHS_copy_der, *RHS_derivative, *pred, err_0 = HUGE_VAL ;
    double time_err_min_1 = 0, time_err_min_0 = 0, err_min_0 = HUGE_VAL, err_min_1 = 0 ;
    double err_1 = 0, err_max = HUGE_VAL ;
    int pss_points_cycle = 0, dynamic_test = 0 ;
    double gf_last_0 = HUGE_VAL, gf_last_1 = GF_LAST ;
    double thd = 0 ;
    double *psstimes, *pssvalues;
    double *pssstates;   /* Enhancement-119: device states captured per PSS sample */
    double *RHS_max, *RHS_min, *err_conv ;

    /* Francesco Lannutti's MOD */
    /* Stuff needed by frequency estimation reiteration, based on the DFT result */
    int position;
    double max_freq;

    /* Print some useful information */
    PSSDBG( "Periodic Steady State Analysis Started\n\n") ;
    PSSDBG( "PSS Guessed Frequency %g\n", ckt->CKTguessedFreq) ;
    PSSDBG( "PSS Points %ld\n", ckt->CKTpsspoints) ;
    PSSDBG( "PSS Harmonics number %d\n", ckt->CKTharms) ;
    PSSDBG( "PSS Steady Coefficient %g\n", ckt->CKTsteady_coeff) ;
    PSSDBG( "PSS sc_iter %d\n", ckt->CKTsc_iter) ;
    PSSDBG( "PSS Stabilization Time %g\n", ckt->CKTstabTime) ;


    oscnNode = job->PSSoscNode->number ;


    /* Variables and memory initialization */

    for (i = 0 ; i < HISTORY ; i++)
    {
        rr_history [i] = 0.0 ;
        gf_history [i] = 0.0 ;
    }

    msize = SMPmatSize (ckt->CKTmatrix) ;
    RHS_copy_se = TMALLOC (double, msize) ;  /* Set the current RHS reference for next Shooting Evaluation */
    RHS_copy_der = TMALLOC (double, msize) ; /* Used to compute current Derivative */
    RHS_derivative = TMALLOC (double, msize) ;
    pred = TMALLOC (double, msize) ;
    RHS_max = TMALLOC (double, msize) ;
    RHS_min = TMALLOC (double, msize) ;
    err_conv = TMALLOC (double, msize) ;
    
    for (i = 0 ; i < msize ; i++)
    {
        RHS_copy_se [i] = 0.0 ;
        RHS_copy_der [i] = 0.0 ;
        RHS_derivative [i] = 0.0 ;
        pred [i] = 0.0 ;
    }

    psstimes = TMALLOC (double, ckt->CKTpsspoints + 1) ;
    pssvalues = TMALLOC (double, msize * (ckt->CKTpsspoints + 1)) ;
    /* Enhancement-119: also capture the device states (charges/fluxes) per
     * sample -- CKTstate0 holds the accepted state alongside CKTrhsOld. */
    pssstates = TMALLOC (double, ckt->CKTnumStates * (ckt->CKTpsspoints + 1)) ;

    for (i = 0 ; i < ckt->CKTpsspoints + 1 ; i++)
        psstimes [i] = 0.0 ;

    for (i = 0 ; i < msize * (ckt->CKTpsspoints + 1) ; i++)
        pssvalues [i] = 0.0 ;

    for (i = 0 ; i < ckt->CKTnumStates * (ckt->CKTpsspoints + 1) ; i++)
        pssstates [i] = 0.0 ;

    /* Delta timestep and circuit time setup */
    delta = ckt->CKTstep ;
    ckt->CKTtime = ckt->CKTinitTime ;
    ckt->CKTfinalTime = ckt->CKTstabTime ;

    /* Starting PSS Algorithm, based on Transient Analysis */
    if(restart || ckt->CKTtime == 0) {
        delta = MIN (1 / ckt->CKTguessedFreq / 100, ckt->CKTstep) ;

#ifdef STEPDEBUG
        PSSDBG( "delta = %g    finalTime/200: %g    CKTstep: %g\n", delta, ckt->CKTfinalTime / 200, ckt->CKTstep) ;
#endif
        /* begin LTRA code addition */
        if (ckt->CKTtimePoints != NULL)
            FREE(ckt->CKTtimePoints);

        if (ckt->CKTstep >= ckt->CKTmaxStep)
            maxstepsize = ckt->CKTstep;
        else
            maxstepsize = ckt->CKTmaxStep;

        ckt->CKTsizeIncr = 100;
        ckt->CKTtimeIndex = -1; /* before the DC soln has been stored */
        ckt->CKTtimeListSize = (int)(1 / ckt->CKTguessedFreq / maxstepsize + 0.5);
        ltra_num = CKTtypelook("LTRA");
        if (ltra_num >= 0 && ckt->CKThead[ltra_num] != NULL)
            ckt->CKTtimePoints = TMALLOC(double, ckt->CKTtimeListSize);
        /* end LTRA code addition */

        /* Breakpoints initialization */
        if(ckt->CKTbreaks) FREE(ckt->CKTbreaks);
        ckt->CKTbreaks = TMALLOC(double, 2);
        if(ckt->CKTbreaks == NULL) return(E_NOMEM);
        ckt->CKTbreaks[0] = 0;
        ckt->CKTbreaks[1] = ckt->CKTfinalTime;
        ckt->CKTbreakSize = 2;

#ifdef XSPICE
/* gtri - begin - wbk - 12/19/90 - Modify setting of CKTminBreak */
        /* if (ckt->CKTminBreak == 0)
               ckt->CKTminBreak = ckt->CKTmaxStep * 5e-5 ; */

        /* Set to 10 times delmin for ATESSE 1 compatibity */
        if(ckt->CKTminBreak==0) ckt->CKTminBreak = 10.0 * ckt->CKTdelmin;
/* gtri - end - wbk - 12/19/90 - Modify setting of CKTminBreak */
#else
        /* Minimum Breakpoint Setup */
        if(ckt->CKTminBreak==0) ckt->CKTminBreak=ckt->CKTmaxStep*5e-5;
#endif

#ifdef XSPICE
        /* set anal_init and anal_type */

        /* Tell the code models what mode we're in */
        g_mif_info.circuit.anal_type = MIF_DC;

        g_mif_info.circuit.anal_init = MIF_TRUE;
#endif

	/* Time Domain plot start and prepared to be filled in later */
        error = CKTnames(ckt,&numNames,&nameList);
        if(error) return(error);
        SPfrontEnd->IFnewUid (ckt, &timeUid, NULL, "time", UID_OTHER, NULL);
        error = SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                                           "Time Domain Periodic Steady State Analysis",
                                           timeUid, IF_REAL,
                                           numNames, nameList, IF_REAL,
                                           &(job->PSSplot_td));
        tfree(nameList);
        if(error) return(error);

        /* Time initialization for Transient Analysis */
        ckt->CKTtime = 0;
        ckt->CKTdelta = 0;
        ckt->CKTbreak = 1;
        firsttime = 1;
        save_mode = (ckt->CKTmode&MODEUIC) | MODETRANOP | MODEINITJCT;
        save_order = ckt->CKTorder;

#ifdef XSPICE
/* gtri - begin - wbk - set a breakpoint at end of supply ramping time */
        /* must do this after CKTtime set to 0 above */
        if(ckt->enh->ramp.ramptime > 0.0)
            CKTsetBreak(ckt, ckt->enh->ramp.ramptime);
/* gtri - end - wbk - set a breakpoint at end of supply ramping time */

/* gtri - begin - wbk - Call EVTop if event-driven instances exist */
        if(ckt->evt->counts.num_insts != 0) {
            /* use new DCOP algorithm */
            converged = EVTop(ckt,
                        (ckt->CKTmode & MODEUIC) | MODETRANOP | MODEINITJCT,
                        (ckt->CKTmode & MODEUIC) | MODETRANOP | MODEINITFLOAT,
                        ckt->CKTdcMaxIter,
                        MIF_TRUE);
            EVTdump(ckt, IPC_ANAL_DCOP, 0.0);

            EVTop_save(ckt, MIF_FALSE, 0.0);

/* gtri - end - wbk - Call EVTop if event-driven instances exist */
        } else
#endif

        /* Looking for a working Operating Point */
            converged = CKTop(ckt,
                (ckt->CKTmode & MODEUIC) | MODETRANOP | MODEINITJCT,
                (ckt->CKTmode & MODEUIC) | MODETRANOP | MODEINITFLOAT,
                ckt->CKTdcMaxIter);

#ifdef STEPDEBUG
        if(converged != 0) {
            fprintf(stdout,"\nTransient solution failed -\n");
            CKTncDump(ckt);
            fprintf(stdout,"\n");
            fflush(stdout);
        } else if (!ft_noacctprint && !ft_noinitprint) {
            fprintf(stdout,"\nInitial Transient Solution\n");
            fprintf(stdout,"--------------------------\n\n");
            fprintf(stdout,"%-30s %15s\n", "Node", "Voltage");
            fprintf(stdout,"%-30s %15s\n", "----", "-------");
            for(node=ckt->CKTnodes->next;node;node=node->next) {
                if (strstr(node->name, "#branch") || !strchr(node->name, '#'))
                    fprintf(stdout,"%-30s %15g\n", node->name,
                                              ckt->CKTrhsOld[node->number]);
            }
            fprintf(stdout,"\n");
            fflush(stdout);
        }
#endif

        /* If no convergence reached - NO valid Operating Point */
        if(converged != 0)
            return(converged);

#ifdef XSPICE
        g_mif_info.circuit.anal_init = MIF_TRUE;

        /* Tell the code models what mode we're in */
        g_mif_info.circuit.anal_type = MIF_TRAN;

        /* Initialize the temporary breakpoint variables to infinity */
        g_mif_info.breakpoint.current = HUGE_VAL;
        g_mif_info.breakpoint.last    = HUGE_VAL;
#endif
        ckt->CKTstat->STATtimePts ++;

        /* Setting Integration Order to Backward Euler */
        ckt->CKTorder = 1;

        /* Copying the maxStep to every deltaOld */
        for(i=0;i<7;i++) {
            ckt->CKTdeltaOld[i]=ckt->CKTmaxStep;
        }

        /* Setting DELTA */
        ckt->CKTdelta = delta;
#ifdef STEPDEBUG
        PSSDBG( "delta initialized to %g\n", ckt->CKTdelta);
#endif

	ckt->CKTsaveDelta = ckt->CKTfinalTime/50;

        ckt->CKTmode = (ckt->CKTmode&MODEUIC) | MODETRAN | MODEINITTRAN;
        /* Changing Circuit MODE */
        /* modeinittran set here */
        ckt->CKTag[0]=ckt->CKTag[1]=0;

        /* State0 copied into State1 - DEPRECATED LEGACY function - to be replaced with memmove() */
        memcpy(ckt->CKTstate1, ckt->CKTstate0,
              (size_t) ckt->CKTnumStates * sizeof(double));

        /* Statistics Initialization using a macro at the beginning of this code */
        INIT_STATS();

    } else {
        /* saj As traninit resets CKTmode */
        ckt->CKTmode = (ckt->CKTmode&MODEUIC) | MODETRAN | MODEINITPRED;
        /* saj */
        INIT_STATS();
        if(ckt->CKTminBreak==0) ckt->CKTminBreak=ckt->CKTmaxStep*5e-5;
        firsttime=0;
        /* To get rawfile working saj*/
        error = SPfrontEnd->OUTpBeginPlot (NULL, NULL,
                                           NULL,
                                           NULL, 0,
                                           666, NULL, 666,
                                           &(job->PSSplot_td));
        if(error) {
            fprintf(stderr, "Couldn't relink rawfile\n");
            return error;
        }
        /* end saj*/

        /* Skip nextTime if it isn't the firsttime! :) */
        goto resume;
    }

/* 650 */
    nextTime:

    /* begin LTRA code addition */
    if (ckt->CKTtimePoints) {
    ckt->CKTtimeIndex++;
        if (ckt->CKTtimeIndex >= ckt->CKTtimeListSize) {
            /* need more space */
            int need;
            if (pss_state == STABILIZATION)
                need = (int) ceil((ckt->CKTstabTime - ckt->CKTtime) / maxstepsize ) ;
            else
                need = (int) ceil((time_temp + 1 / ckt->CKTguessedFreq - ckt->CKTtime) / maxstepsize) ;

            if (need < ckt->CKTsizeIncr)
                need = ckt->CKTsizeIncr;
            ckt->CKTtimeListSize += need;
            ckt->CKTtimePoints = TREALLOC(double, ckt->CKTtimePoints, ckt->CKTtimeListSize);
            ckt->CKTsizeIncr = (int) ceil(1.4 * ckt->CKTsizeIncr);
        }
        ckt->CKTtimePoints[ckt->CKTtimeIndex] = ckt->CKTtime;
    }
    /* end LTRA code addition */

    /* Check for the timepoint acceptance */
    error = CKTaccept(ckt);
    /* check if current breakpoint is outdated; if so, clear */
    if (ckt->CKTtime > ckt->CKTbreaks[0]) CKTclrBreak(ckt);

    /*
 * Breakpoint handling scheme:
 * When a timepoint t is accepted (by CKTaccept), clear all previous
 * breakpoints, because they will never be needed again.
 *
 * t may itself be a breakpoint, or indistinguishably close. DON'T
 * clear t itself; recognise it as a breakpoint and act accordingly
 *
 * if t is not a breakpoint, limit the timestep so that the next
 * breakpoint is not crossed
 */

#ifdef STEPDEBUG
    PSSDBG( "Delta %g accepted at time %g (finaltime: %g)\n", ckt->CKTdelta, ckt->CKTtime, ckt->CKTfinalTime) ;
    fflush(stdout);
#endif /* STEPDEBUG */
    ckt->CKTstat->STATaccepted ++;
    ckt->CKTbreak = 0;
    /* XXX Error will cause single process to bail. */
    if(error)  {
        UPDATE_STATS(DOING_TRAN);
        return(error);
    }
#ifdef XSPICE

    if (wantevtdata) {

        if (pss_state == PSS)
        {
            /* Send event-driven results */
            EVTdump(ckt, IPC_ANAL_TRAN, 0.0);
        }
    } else

#endif

    if (pss_state == PSS)
    {
        nextstep = time_temp + 1 / ckt->CKTguessedFreq * ((double)(pss_points_cycle) / (double)ckt->CKTpsspoints) ;

        /* If in_pss, store data for Time Domain Plot and gather ordered data for FFT computing */
	if ((AlmostEqualUlps (ckt->CKTtime, nextstep, 10)) || (ckt->CKTtime > time_temp + 1 / ckt->CKTguessedFreq))
        {

#ifdef STEPDEBUG
            PSSDBG( "IN_PSS: time point accepted in evolution for FFT calculations.\n") ;
            PSSDBG( "Circuit time %1.15g, final time %1.15g, point index %d and total requested points %ld\n",
                     ckt->CKTtime, nextstep, pss_points_cycle, ckt->CKTpsspoints) ;
#endif

            CKTdump (ckt, ckt->CKTtime, job->PSSplot_td) ;

            /* Store the Time Base for the DFT */
            psstimes [pss_points_cycle] = ckt->CKTtime ;

            /* Store values for the FFT calculation */
            for (i = 1 ; i <= msize ; i++)
                pssvalues [i - 1 + pss_points_cycle * msize] = ckt->CKTrhsOld [i] ;

            /* Enhancement-119: capture the device states at this sample */
            memcpy (pssstates + (size_t)pss_points_cycle * (size_t)ckt->CKTnumStates,
                    ckt->CKTstate0, (size_t)ckt->CKTnumStates * sizeof(double)) ;

            /* Update PSS counter cycle, used to stop the entire algorithm */
            pss_points_cycle++ ;

            /* Set the next BreakPoint for PSS */
            CKTsetBreak (ckt, time_temp + (1 / ckt->CKTguessedFreq) * ((double)pss_points_cycle / (double)ckt->CKTpsspoints)) ;

#ifdef STEPDEBUG
            PSSDBG( "Next breakpoint set in: %1.15g\n", time_temp + 1 / ckt->CKTguessedFreq * ((double)pss_points_cycle / (double)ckt->CKTpsspoints)) ;
#endif

        } else { 
            /* Algo can enter here but should do nothing */

#ifdef STEPDEBUG
            PSSDBG( "IN_PSS: time point accepted in evolution but dropped for FFT calculations\n") ;
#endif

        }
    }

#ifdef XSPICE
/* gtri - begin - wbk - Update event queues/data for accepted timepoint */
    /* Note: this must be done AFTER sending results to SI so it can't */
    /* go next to CKTaccept() above */
    if(ckt->evt->counts.num_insts > 0)
        EVTaccept(ckt, ckt->CKTtime);
/* gtri - end - wbk - Update event queues/data for accepted timepoint */
#endif
    ckt->CKTstat->STAToldIter = ckt->CKTstat->STATnumIter;

    /* ***********************************/
    /* ******* SHOOTING CODE BLOCK *******/
    /* ***********************************/
    switch(pss_state) {

    case STABILIZATION:
    {
        /* Test if stabTime has been reached */
        if (AlmostEqualUlps (ckt->CKTtime, ckt->CKTstabTime, 100))
        {
            time_temp = ckt->CKTtime ;

            /* Set the new Final Time - This is important because the last breakpoint is always CKTfinalTime */
            ckt->CKTfinalTime = time_temp + 2 / ckt->CKTguessedFreq ;
            PSSDBG( "Exiting from stabilization\n") ;
            PSSDBG( "Time of first shooting evaluation will be %1.10g\n", time_temp + 1 / ckt->CKTguessedFreq) ;

            /* Next time is no more in stabilization - Unset the flag */
            pss_state = SHOOTING;

            /* Save the RHS_copy_der as the NEW CKTrhsOld */
            for (i = 1 ; i <= msize ; i++)
                RHS_copy_der [i - 1] = ckt->CKTrhsOld [i] ;

            /* Print RHS on exiting from stabilization */
            PSSDBG( "RHS on exiting from stabilization: ") ;
            for (i = 1 ; i <= msize ; i++)
            {
                RHS_copy_se [i - 1] = ckt->CKTrhsOld [i] ;
                PSSDBG( "%-15g ", RHS_copy_se [i - 1]) ;
            }
            PSSDBG( "\n") ;

            /* RHS_max and RHS_min initialization - HUGE_VAL is the maximum machine error */
            for (i = 0 ; i < msize ; i++)
            {
                RHS_max [i] = -HUGE_VAL ;
                RHS_min [i] = HUGE_VAL ;
            }
	}
    }
    break;

    case SHOOTING:
    {
        double offset, interval, nextBreak ;
        /* Calculation of error norms of RHS solution of every accepted nextTime */
        err = 0 ;
        for (i = 0 ; i < msize ; i++)
        {
            /* Save max per node or branch of every estimated period */
            if (RHS_max [i] < ckt->CKTrhsOld [i + 1])
                RHS_max [i] = ckt->CKTrhsOld [i + 1] ;

            /* Save min per node or branch of every estimated period */
            if (RHS_min [i] > ckt->CKTrhsOld [i + 1])
                RHS_min [i] = ckt->CKTrhsOld [i + 1] ;

            /* CKTrhsOld is the last CORRECT value of RHS */
            err_conv [i] = ckt->CKTrhsOld [i + 1] - RHS_copy_se [i] ;
            err += err_conv [i] * err_conv [i] ;

            /* Compute and store derivative */
            RHS_derivative [i] = (ckt->CKTrhsOld [i + 1] - RHS_copy_der [i]) / ckt->CKTdelta ;

            /* Save the RHS_copy_der as the NEW CKTrhsOld */
            RHS_copy_der [i] = ckt->CKTrhsOld [i + 1] ;

#ifdef STEPDEBUG
            PSSDBG( "Pred is so high or so low! Diff is: %g\n", err_conv [i]) ;
#endif

        }
        err = sqrt (err) ;

        /* Start frequency estimation */
        if ((err < err_0) && (ckt->CKTtime >= time_temp + 0.5 / ckt->CKTguessedFreq)) /* far enough from time temp... */
        {
            if (err < err_min_0)
            {
                err_min_1 = err_min_0 ;            /* store previous minimum of RHS vector error */
                err_min_0 = err ;                  /* store minimum of RHS vector error */
                time_err_min_1 = time_err_min_0 ;  /* store previous minimum of RHS vector error time */
                time_err_min_0 = ckt->CKTtime ;    /* store minimum of RHS vector error time */
            }
        }
        err_0 = err ;

        if ((err > err_1) && (ckt->CKTtime >= time_temp + 0.1 / ckt->CKTguessedFreq)) /* far enough from time temp... */
        {
            if (err > err_max)
                err_max = err ;                /* store maximum of RHS vector error */
        }
        err_1 = err ;


        /* *************************************** */
        /* ********** Breakpoint update ********** */
        /* *************************************** */

        /* Force the tran analysis to evaluate requested breakpoints. Breakpoints are even more closer as
           the next occurence of guessed period is approaching. La lunga notte dei robot viventi... */

/*        double offset, interval, nextBreak ;
        int i ;
*/
        if ((ckt->CKTtime > time_temp + (1 / ckt->CKTguessedFreq) * 0.995) && (ckt->CKTtime <= time_temp + (1 / ckt->CKTguessedFreq)))
        {
            offset = time_temp + (1 / ckt->CKTguessedFreq) * 0.995 ;
            interval = (1 / ckt->CKTguessedFreq) * (1 - 0.995) * (ckt->CKTsteady_coeff / 10) ;
            i = (int)((ckt->CKTtime - offset) / interval) ;
            nextBreak = offset + (i + 1) * interval ;
            CKTsetBreak (ckt, nextBreak) ;
        }
        else if ((ckt->CKTtime > time_temp + (1 / ckt->CKTguessedFreq) * 0.8) && (ckt->CKTtime <= time_temp + (1 / ckt->CKTguessedFreq) * 0.995))
        {
            offset = time_temp + (1 / ckt->CKTguessedFreq) * 0.8 ;
            interval = (1 / ckt->CKTguessedFreq) * (0.995 - 0.8) * (ckt->CKTsteady_coeff / 5) ;
            i = (int)((ckt->CKTtime - offset) / interval) ;
            nextBreak = offset + (i + 1) * interval ;
            CKTsetBreak (ckt, nextBreak) ;
        }
        else if ((ckt->CKTtime > time_temp + (1 / ckt->CKTguessedFreq) * 0.5) && (ckt->CKTtime <= time_temp + (1 / ckt->CKTguessedFreq) * 0.8))
        {
            offset = time_temp + (1 / ckt->CKTguessedFreq) * 0.5 ;
            interval = (1 / ckt->CKTguessedFreq) * (0.8 - 0.5) * (ckt->CKTsteady_coeff / 3) ;
            i = (int)((ckt->CKTtime - offset) / interval) ;
            nextBreak = offset + (i + 1) * interval ;
            CKTsetBreak (ckt, nextBreak) ;
        }
        else if ((ckt->CKTtime > time_temp + (1 / ckt->CKTguessedFreq) * 0.1) && (ckt->CKTtime <= time_temp + (1 / ckt->CKTguessedFreq) * 0.5))
        {
            offset = time_temp + (1 / ckt->CKTguessedFreq) * 0.1 ;
            interval = (1 / ckt->CKTguessedFreq) * (0.5 - 0.1) * (ckt->CKTsteady_coeff / 2) ;
            i = (int)((ckt->CKTtime - offset) / interval) ;
            nextBreak = offset + (i + 1) * interval ;
            CKTsetBreak (ckt, nextBreak) ;
        }
        else if ((ckt->CKTtime > time_temp) && (ckt->CKTtime <= time_temp + (1 / ckt->CKTguessedFreq) * 0.1))
        {
            offset = time_temp ;
            interval = (1 / ckt->CKTguessedFreq) * (0.1) * (ckt->CKTsteady_coeff) ;
            i = (int)((ckt->CKTtime - offset) / interval) ;
            nextBreak = offset + (i + 1) * interval ;
            CKTsetBreak (ckt, nextBreak) ;
        } else {
            PSSDBG( "Strange behavior\n\n") ;
            PSSDBG( "CKTtime: %g\ntime_temp: %g\n\n", ckt->CKTtime, time_temp) ;
        }

        /* *************************************** */
        /* ******* END Breakpoint update ********* */
        /* *************************************** */


        /* If evolution is near shooting... */
        if ((AlmostEqualUlps (ckt->CKTtime, time_temp + 1 / ckt->CKTguessedFreq, 10)) || (ckt->CKTtime > time_temp + 1 / ckt->CKTguessedFreq))
        {
            int excessive_err_nodes = 0 ;

            /* Calculation of error norms of RHS solution of every accepted nextTime */
            predsum = 0 ;
            for (i = 0 ; i < msize ; i++)
            {
                /* Pitagora ha sempre ragione!!! :))) */
                /* pred is treated as FREQUENCY to avoid numerical overflow when derivative is close to ZERO */
                pred [i] = RHS_derivative [i] / err_conv [i] ;

#ifdef STEPDEBUG
                PSSDBG( "Pred is so high or so low! Diff is: %g\n", err_conv [i]) ;
#endif

                if ((fabs (pred [i]) > 1.0e6 * ckt->CKTguessedFreq) || (err_conv [i] == 0))
                {
                    if (pred [i] > 0)
                        pred [i] = 1.0e6 * ckt->CKTguessedFreq ;
                    else
                        pred [i] = -1.0e6 * ckt->CKTguessedFreq ;
                }

                predsum += pred [i] ;

#ifdef STEPDEBUG
                PSSDBG( "Predsum in time before to be divided by dynamic_test has value %g\n", 1 / predsum) ;
                PSSDBG( "Current Diff: %g, Derivative: %g, Frequency Projection: %g\n", err_conv [i], RHS_derivative [i], pred [i]) ;
#endif

            }

//            int excessive_err_nodes = 0 ;

            if (shooting_cycle_counter == 0)
            {
                /* If first time in shooting we warn about that ! */
                PSSDBG( "In shooting...\n") ;
            }

//#ifdef STEPDEBUG
            /* For debugging purpose */
            PSSDBG( "\n----------------\n") ;
            PSSDBG( "Shooting cycle iteration number: %3d ||", shooting_cycle_counter) ;

            if (shooting_cycle_counter > 0)
                PSSDBG( " rr: %g || predsum: %g\n", rr_history [shooting_cycle_counter - 1], 1 / predsum) ;
            else
                PSSDBG( " rr: %g || predsum: %g\n", 0.0, 1 / predsum) ;

//            PSSDBG( "Print of dynamically consistent nodes voltages or branches currents:\n") ;
            /* --------------------- */
//#endif

            for (i = 0, node = ckt->CKTnodes->next ; node ; i++, node = node->next)
            {
                /* Voltage Node */
                if (!strchr (node->name, '#'))
                {
                    if (fabs (err_conv [i]) > (fabs (RHS_max [i] - RHS_min [i]) * ckt->CKTreltol + ckt->CKTvoltTol) *
                        ckt->CKTtrtol * ckt->CKTsteady_coeff)
                    {
                        excessive_err_nodes++ ;
                    }

                    /* If the dynamic is below 10uV, it's dropped */
                    if (fabs (RHS_max [i] - RHS_min [i]) > 10 * 1e-6)
                    {
                        dynamic_test++ ; /* test on voltage dynamic consistence */
                    }

                /* Current Node */
                } else {
                    if (fabs (err_conv [i]) > (fabs (RHS_max [i] - RHS_min [i]) * ckt->CKTreltol + ckt->CKTabstol) *
                        ckt->CKTtrtol * ckt->CKTsteady_coeff)
                    {
                        excessive_err_nodes++ ;
                    }

                    /* If the dynamic is below 10nA, it's dropped */
                    if (fabs (RHS_max [i] - RHS_min [i]) > 10 * 1e-9)
                    {
                        dynamic_test++ ; /* test on current dynamic consistence */
                    }
                }
            }

            if (dynamic_test == 0)
            {
                /* Test for dynamic existence */
                fprintf(stderr, "No detectable dynamic on voltages nodes or currents branches. PSS analysis aborted\n") ;

                /* Terminates plot in Time Domain and frees the allocated memory */
                SPfrontEnd->OUTendPlot (job->PSSplot_td) ;
                FREE (RHS_copy_se) ;
                FREE (RHS_copy_der) ;
                FREE (RHS_max) ;
                FREE (RHS_min) ;
                FREE (err_conv) ;
                FREE (psstimes) ;
                FREE (pssvalues) ;
                FREE (pssstates) ;
                return (E_PANIC) ; /* to be corrected with definition of new error macro in iferrmsg.h */
            }
            else if ((time_err_min_0 - time_temp) < 0)
            {
                /* Something has gone wrong... */
                fprintf(stderr, "Cannot find a minimum for error vector in estimated period. Try to adjust tstab! PSS analysis aborted\n") ;

                /* Terminates plot in Time Domain and frees the allocated memory */
                SPfrontEnd->OUTendPlot (job->PSSplot_td) ;
                FREE (RHS_copy_se) ;
                FREE (RHS_copy_der) ;
                FREE (RHS_max) ;
                FREE (RHS_min) ;
                FREE (err_conv) ;
                FREE (psstimes) ;
                FREE (pssvalues) ;
                FREE (pssstates) ;
                return (E_PANIC) ; /* to be corrected with definition of new error macro in iferrmsg.h */
            }

//#ifdef STEPDEBUG
//            PSSDBG( "Global Convergence Error reference: %g, Time Projection: %g.\n",
//                     err_conv_ref / dynamic_test, predsum) ;
//#endif

            /* Take the mean value of time prediction trough the dynamic test variable - predsum becomes TIME */
            predsum = 1 / (predsum * dynamic_test) ;

            /* Store the predsum history as absolute value */
            predsum_history [shooting_cycle_counter] = fabs (predsum) ;

            /***********************************/
            /*** FREQUENCY ESTIMATION UPDATE ***/
            /***********************************/
            if ((err_min_0 == err) || (err_min_0 == HUGE_VAL))
            {
                /* Enters here if guessed frequency is higher than the 'real' value */
                ckt->CKTguessedFreq = 1 / (1 / ckt->CKTguessedFreq + fabs (predsum)) ;
                
#ifdef STEPDEBUG
                PSSDBG( "Frequency DOWN: est per %g, err min %g, err min 1 %g, err max %g, err %g\n",
                         time_err_min_0 - time_temp, err_min_0, err_min_1, err_max, err) ;
#endif

            } else {
                /* Enters here if guessed frequency is lower than the 'real' value */
                ckt->CKTguessedFreq = 1 / (time_err_min_0 - time_temp) ;

#ifdef STEPDEBUG
                PSSDBG( "Frequency UP:  est per %g, err min %g, err min 1 %g, err max %g, err %g\n",
                         time_err_min_0 - time_temp, err_min_0, err_min_1, err_max, err) ;
#endif

            }

            /* Temporary variables to store previous occurrence of guessed frequency */
            gf_last_1 = gf_last_0 ;
            gf_last_0 = ckt->CKTguessedFreq ;

            /* Next evaluation of shooting will be updated time (time_temp) summed to updated guessed period */
            time_temp = ckt->CKTtime ;

            /* Store error history */
            rr_history [shooting_cycle_counter] = err ;
            gf_history [shooting_cycle_counter] = ckt->CKTguessedFreq ;
            shooting_cycle_counter++ ;

            PSSDBG( "Updated guessed frequency: %1.10lg .\n", ckt->CKTguessedFreq) ;
            PSSDBG( "Next shooting evaluation time is %1.10g and current time is %1.10g.\n",
                     time_temp + 1 / ckt->CKTguessedFreq, ckt->CKTtime) ;

            /* Restore maximum and minimum error for next search */
            err_min_0 = HUGE_VAL ;
            err_max = -HUGE_VAL ;
            err_0 = HUGE_VAL ;
            err_1 = -HUGE_VAL ;
            dynamic_test = 0 ;

            /* Reset actual RHS reference for next shooting evaluation */
            for (i = 1 ; i <= msize ; i++)
                RHS_copy_se [i - 1] = ckt->CKTrhsOld [i] ;

#ifdef STEPDEBUG
            PSSDBG( "RHS on new shooting cycle: ") ;
            for (i = 0 ; i < msize ; i++)
                PSSDBG( "%-15g ", RHS_copy_se [i]) ;
            PSSDBG( "\n") ;
#endif

            for (i = 0 ; i < msize ; i++)
            {
                /* Reset max and min per node or branch on every shooting cycle */
                RHS_max [i] = -HUGE_VAL ;
                RHS_min [i] = HUGE_VAL ;
            }

            PSSDBG( "----------------\n\n") ;

            /* Shooting Exit Condition */
            if ((shooting_cycle_counter > ckt->CKTsc_iter) || (excessive_err_nodes == 0))
            {
                int k ;
                double minimum ;

                pss_state = PSS ;

#ifdef STEPDEBUG
                PSSDBG( "\nFrequency estimation (FE) and RHS period residual (PR) evolution\n") ;
#endif

//                minimum = rr_history [0] ;
                minimum = predsum_history [0] ;
                k = 0 ;
                for (i = 0 ; i < shooting_cycle_counter ; i++)
                {
                    /* Print some statistics */
                    PSSDBG( "%-3d -> FE: %-15.10g || RR: %15.10g", i, gf_history [i], rr_history [i]) ;

                    /* Take the minimum residual iteration */
//                    if (minimum > rr_history [i])
                    if (minimum > predsum_history [i])
                    {
//                        minimum = rr_history [i] ;
                        minimum = predsum_history [i] ;
                        k = i ;
                    }
                    PSSDBG( " || predsum/dynamic_test: %15.10g || minimum: %15.10g\n", predsum_history [i], minimum) ;
                }

                if (excessive_err_nodes == 0)  /* SHOOTING has converged  */
                    ckt->CKTguessedFreq = gf_history [shooting_cycle_counter - 1] ;
                else
                    ckt->CKTguessedFreq = gf_history [k] ;

                /* Save the current Time */
                time_temp = ckt->CKTtime ;

                /* Set the new Final Time - This is important because the last breakpoint is always CKTfinalTime */
                ckt->CKTfinalTime = time_temp + 1 / ckt->CKTguessedFreq ;

                /* Dump the first PSS point for the FFT */
                CKTdump (ckt, ckt->CKTtime, job->PSSplot_td) ;
                psstimes [pss_points_cycle] = ckt->CKTtime ;
                for (i = 1 ; i <= msize ; i++)
                    pssvalues [i - 1 + pss_points_cycle * msize] = ckt->CKTrhsOld [i] ;

                /* Enhancement-119: capture the device states at the first sample */
                memcpy (pssstates + (size_t)pss_points_cycle * (size_t)ckt->CKTnumStates,
                        ckt->CKTstate0, (size_t)ckt->CKTnumStates * sizeof(double)) ;

                /* Update the PSS points counter and set the next Breakpoint */
                pss_points_cycle++ ;
                CKTsetBreak (ckt, time_temp + (1 / ckt->CKTguessedFreq) * ((double)pss_points_cycle / (double)ckt->CKTpsspoints)) ;

                if (excessive_err_nodes == 0)
                    fprintf(stderr, "\nConvergence reached. Final circuit time is %1.10g seconds (iteration n° %d) and predicted fundamental frequency is %15.10g Hz\n", ckt->CKTtime, shooting_cycle_counter - 1, ckt->CKTguessedFreq) ;
                else
                    fprintf(stderr, "\nConvergence not reached. However the most near convergence iteration has predicted (iteration %d) a fundamental frequency of %15.10g Hz\n", k, ckt->CKTguessedFreq) ;

#ifdef STEPDEBUG
                PSSDBG( "time_temp %g\n", time_temp) ;
                PSSDBG( "IN_PSS: FIRST time point accepted in evolution for FFT calculations\n") ;
                PSSDBG( "Circuit time %1.15g, final time %1.15g, point index %d and total requested points %ld\n",
                         ckt->CKTtime, time_temp + 1 / ckt->CKTguessedFreq * ((double)pss_points_cycle / (double)ckt->CKTpsspoints),
                         pss_points_cycle, ckt->CKTpsspoints) ;
                PSSDBG( "Next breakpoint set in: %1.15g\n",
                         time_temp + 1 / ckt->CKTguessedFreq * ((double)pss_points_cycle / (double)ckt->CKTpsspoints)) ;
#endif

            } else {
                /* Set the new Final Time - This is important because the last breakpoint is always CKTfinalTime */
                ckt->CKTfinalTime = time_temp + 1 / ckt->CKTguessedFreq ;

                /* Set next the breakpoint */
                CKTsetBreak (ckt, time_temp + 1 / ckt->CKTguessedFreq) ;
            }
        }
    }
    break;

    case PSS:
    {
        /* The algorithm enters here when in_pss is set */

#ifdef STEPDEBUG
        PSSDBG( "ttemp %1.15g, final_time %1.15g, current_time %1.15g\n", time_temp, time_temp + 1 / ckt->CKTguessedFreq, ckt->CKTtime) ;
#endif

        if ((pss_points_cycle == ckt->CKTpsspoints + 1) || (ckt->CKTtime > ckt->CKTfinalTime))
        {
            double *pssfreqs   = TMALLOC (double, ckt->CKTharms);
            double *pssmags    = TMALLOC (double, ckt->CKTharms);
            double *pssphases  = TMALLOC (double, ckt->CKTharms);
            double *pssnmags   = TMALLOC (double, ckt->CKTharms);
            double *pssnphases = TMALLOC (double, ckt->CKTharms);
            double *pssValues  = TMALLOC (double, ckt->CKTpsspoints + 1);
            double *pssResults = TMALLOC (double, msize * ckt->CKTharms);

            /* End plot in Time Domain */
            SPfrontEnd->OUTendPlot (job->PSSplot_td) ;

            /* Frequency Plot Creation */
            error = CKTnames (ckt, &numNames, &nameList) ;
            if (error)
                return (error) ;
            SPfrontEnd->IFnewUid (ckt, &freqUid, NULL, "frequency", UID_OTHER, NULL) ;
            error = SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                                               "Frequency Domain Periodic Steady State Analysis",
                                               freqUid, IF_REAL,
                                               numNames, nameList, IF_REAL,
                                               &(job->PSSplot_fd)) ;
            tfree (nameList) ;
            SPfrontEnd->OUTattributes (job->PSSplot_fd, NULL, PLOT_COMB, NULL) ;

            /* ******************** */
            /* Starting DFT on data */
            /* ******************** */
            for (i = 0 ; i < msize ; i++)
            {
                for (j = 0 ; j < ckt->CKTpsspoints ; j++)
                    pssValues [j] = pssvalues [j * msize + i] ;

                DFT (ckt->CKTpsspoints, ckt->CKTharms, &thd, psstimes, pssValues, ckt->CKTguessedFreq,
                         pssfreqs, pssmags, pssphases, pssnmags, pssnphases) ;

                for (j = 0 ; j < ckt->CKTharms ; j++)
                    pssResults [j * msize + i] = pssmags [j] ;
            }

            for (j = 0 ; j < ckt->CKTharms ; j++)
            {
                for (i = 0 ; i < msize ; i++)
                    ckt->CKTrhsOld [i + 1] = pssResults [j * msize + i] ;

                CKTdump (ckt, pssfreqs [j], job->PSSplot_fd) ;
            }
            /* ****************** */
            /* Ending DFT on data */
            /* ****************** */

            /* Terminates plot in Frequency Domain and frees the allocated memory */
            SPfrontEnd->OUTendPlot (job->PSSplot_fd) ;



            /* Francesco Lannutti's MOD */

            /* Verify the frequency found */
            max_freq = pssResults [msize] ;             /* max_freq = pssResults [1 * msize + 0] ; */
            position = 1 ;
            for (j = 1 ; j < ckt->CKTharms ; j++)
            {
                for (i = 0 ; i < msize ; i++)
                {
                    if (max_freq < pssResults [j * msize + i])
                    {
                        max_freq = pssResults [j * msize + i] ;
                        position = j ;
                    }
                }
            }

            if (pssfreqs [position] != ckt->CKTguessedFreq)
            {
                ckt->CKTguessedFreq = pssfreqs [position] ;
                PSSDBG( "The predicted fundamental frequency is incorrect.\nRelaunching the analysis...\n\n") ;
                PSSDBG( "The new guessed fundamental frequency is: %.6g\n\n", ckt->CKTguessedFreq) ;
                DCpss (ckt, 1) ;
                /* the relaunched run retained its own (correct) operating point;
                 * this run's samples are stale -- fall through and free them. */
            }
            else
            {
                /* Enhancement-119: frequency confirmed -- retain this converged
                 * periodic operating point on the job for periodic small-signal
                 * reuse (PAC/pnoise/PXF). Ownership of the sample arrays is
                 * transferred to the job (set local ptrs NULL so the FREE below
                 * is a no-op); the DFT that produced the harmonic output above
                 * was taken from exactly these samples, so they are self-consistent. */
                FREE (job->PSSopTimes) ;
                FREE (job->PSSopVoltages) ;
                FREE (job->PSSopStates) ;
                job->PSSopPoints    = ckt->CKTpsspoints ;
                job->PSSopMsize     = msize ;
                job->PSSopNumStates = ckt->CKTnumStates ;
                job->PSSopFreq      = ckt->CKTguessedFreq ;
                job->PSSopTimes     = psstimes ;   psstimes  = NULL ;
                job->PSSopVoltages  = pssvalues ;  pssvalues = NULL ;
                job->PSSopStates    = pssstates ;  pssstates = NULL ;
                fprintf (stderr, "PSS periodic operating point retained: %ld samples x "
                                 "%d unknowns x %d states at f = %.10g Hz\n",
                         job->PSSopPoints, job->PSSopMsize, job->PSSopNumStates,
                         job->PSSopFreq) ;

                /* Self-check: report the osc-node voltage swing straight from the
                 * retained samples, so the retained data can be validated without
                 * a consumer yet (a periodic node must swing over the period). */
                {
                    int onode = job->PSSoscNode ? job->PSSoscNode->number : 0 ;
                    if (onode > 0 && onode <= job->PSSopMsize) {
                        double vmin = HUGE_VAL, vmax = -HUGE_VAL ;
                        long s ;
                        for (s = 0 ; s < job->PSSopPoints ; s++) {
                            double v = job->PSSopVoltages [(onode - 1) + s * job->PSSopMsize] ;
                            if (v < vmin) vmin = v ;
                            if (v > vmax) vmax = v ;
                        }
                        fprintf (stderr, "  retained op-point self-check: osc-node swing "
                                         "[%.6g, %.6g] over the period\n", vmin, vmax) ;
                    }
                }

                /* Enhancement-120: report the periodic small-signal Jacobian
                 * harmonics at the osc node, built from the retained op-point. */
                pss_jacobian_report (ckt, job) ;

                /* Enhancement-121: assemble the harmonic conversion matrix from
                 * the full periodic Jacobian and solve it -- the PAC engine. */
                pss_pac_report (ckt, job) ;

                /* Enhancement-122: for a .pac card, sweep the input frequency and
                 * emit the sideband-0 node responses as a complex plot. */
                if (job->PSSdoPAC)
                    pac_sweep (ckt, job) ;

                /* Enhancement-124: for a .pnoise card, fold each device's noise
                 * through the conversion matrix to get the output noise spectrum. */
                if (job->PSSdoPnoise)
                    pnoise_sweep (ckt, job) ;
            }
            /****************************/


            FREE (pssResults) ;
            FREE (pssValues) ;
            FREE (pssnphases) ;
            FREE (pssnmags) ;
            FREE (pssphases) ;
            FREE (pssmags) ;
            FREE (pssfreqs) ;

            FREE (RHS_copy_se) ;
            FREE (RHS_copy_der) ;
            FREE (RHS_max) ;
            FREE (RHS_min) ;
            FREE (err_conv) ;
            FREE (psstimes) ;
            FREE (pssvalues) ;
            FREE (pssstates) ;
            return (OK) ;
        }
    }
    break;

    } /* switch(pss_state) */

    /* ********************************** */
    /* **** END SHOOTING CODE BLOCK ***** */
    /* ********************************** */

    if(SPfrontEnd->IFpauseTest()) {
        /* user requested pause... */
        UPDATE_STATS(DOING_TRAN);
        return(E_PAUSE);
    }
    /* RESUME */
resume:
#ifdef STEPDEBUG
    if( (ckt->CKTdelta <= ckt->CKTfinalTime/50) &&
        (ckt->CKTdelta <= ckt->CKTmaxStep)) {
        ;
    } else {
        if(ckt->CKTfinalTime/50<ckt->CKTmaxStep) {
	    PSSDBG( "limited by Tstop/50\n");
        } else {
	    PSSDBG( "limited by Tmax == %g\n", ckt->CKTmaxStep);
        }
    }
#endif
#ifdef HAS_PROGREP
    if (ckt->CKTtime == 0.)
        SetAnalyse( "tran init", 0);
    else if ((pss_state != PSS) && (shooting_cycle_counter > 0))
        SetAnalyse("shooting", shooting_cycle_counter) ;
    else
        SetAnalyse( "tran", (int)((ckt->CKTtime * 1000.) / ckt->CKTfinalTime));
#endif
    ckt->CKTdelta =
            MIN(ckt->CKTdelta,ckt->CKTmaxStep);
#ifdef XSPICE
/* gtri - begin - wbk - Cut integration order if first timepoint after breakpoint */
    /* if(ckt->CKTtime == g_mif_info.breakpoint.last) */
    if ( AlmostEqualUlps( ckt->CKTtime, g_mif_info.breakpoint.last, 100 ) )
        ckt->CKTorder = 1;
/* gtri - end   - wbk - Cut integration order if first timepoint after breakpoint */

#endif

  /* are we at a breakpoint, or indistinguishably close? */
    /* if ((ckt->CKTtime == ckt->CKTbreaks[0]) || (ckt->CKTbreaks[0] - */
    if (ckt->CKTbreaks [0] - ckt->CKTtime <= ckt->CKTdelmin)
    {
        /*if ( AlmostEqualUlps( ckt->CKTtime, ckt->CKTbreaks[0], 100 ) || (ckt->CKTbreaks[0] -
        *    (ckt->CKTtime) <= ckt->CKTdelmin)) {*/
        /* first timepoint after a breakpoint - cut integration order */
        /* and limit timestep to .1 times minimum of time to next breakpoint,
         * and previous timestep
         */
        ckt->CKTorder = 1;
#ifdef STEPDEBUG
        if( (ckt->CKTdelta > .1*ckt->CKTsaveDelta) ||
            (ckt->CKTdelta > .1*(ckt->CKTbreaks[1] - ckt->CKTbreaks[0])) ) {
            if(ckt->CKTsaveDelta < (ckt->CKTbreaks[1] - ckt->CKTbreaks[0]))  {
                PSSDBG( "limited by pre-breakpoint delta (saveDelta: %1.10g, nxt_breakpt: %1.10g, curr_breakpt: %1.10g and CKTtime: %1.10g\n",
                         ckt->CKTsaveDelta, ckt->CKTbreaks [1], ckt->CKTbreaks [0], ckt->CKTtime) ;
            } else {
                PSSDBG( "limited by next breakpoint\n") ;
                PSSDBG( "(saveDelta: %1.10g, Delta: %1.10g, CKTtime: %1.10g and delmin: %1.10g\n",
                         ckt->CKTsaveDelta, ckt->CKTdelta, ckt->CKTtime, ckt->CKTdelmin) ;
	    }
	}
#endif

        if (ckt->CKTbreaks [1] - ckt->CKTbreaks [0] == 0)
            ckt->CKTdelta = ckt->CKTdelmin ;
        else
            ckt->CKTdelta = MIN (ckt->CKTdelta, .1 * MIN (ckt->CKTsaveDelta,
            ckt->CKTbreaks[1] - ckt->CKTbreaks[0]));

        if(firsttime) {
            ckt->CKTdelta /= 10;
#ifdef STEPDEBUG
            PSSDBG( "delta cut for initial timepoint\n");
#endif
        }

#ifndef XSPICE
        /* don't want to get below delmin for no reason */
        ckt->CKTdelta = MAX(ckt->CKTdelta, ckt->CKTdelmin*2.0);
#endif

    }

#ifndef XSPICE
    else if(ckt->CKTtime + ckt->CKTdelta >= ckt->CKTbreaks[0]) {
        ckt->CKTsaveDelta = ckt->CKTdelta;
        ckt->CKTdelta = ckt->CKTbreaks[0] - ckt->CKTtime;
        /* PSSDBG( "delta cut to %g to hit breakpoint\n" ,ckt->CKTdelta) ; */
        fflush(stdout);
        ckt->CKTbreak = 1; /* why? the current pt. is not a bkpt. */
    }
#endif /* !XSPICE */


#ifdef XSPICE
/* gtri - begin - wbk - Add Breakpoint stuff */

    if(ckt->CKTtime + ckt->CKTdelta >= g_mif_info.breakpoint.current) {
        /* If next time > temporary breakpoint, force it to the breakpoint */
        /* And mark that timestep was set by temporary breakpoint */
        ckt->CKTsaveDelta = ckt->CKTdelta;
        ckt->CKTdelta = g_mif_info.breakpoint.current - ckt->CKTtime;
        g_mif_info.breakpoint.last = ckt->CKTtime + ckt->CKTdelta;
    } else {
        /* Else, mark that timestep was not set by temporary breakpoint */
        g_mif_info.breakpoint.last = HUGE_VAL;
    }

/* gtri - end - wbk - Add Breakpoint stuff */

/* gtri - begin - wbk - Modify Breakpoint stuff */
    /* Throw out any permanent breakpoint times <= current time */
    for (;;) {
#ifdef STEPDEBUG
        PSSDBG( "    brk_pt: %g    ckt_time: %g    ckt_min_break: %g\n", ckt->CKTbreaks [0], ckt->CKTtime, ckt->CKTminBreak) ;
#endif
        if(AlmostEqualUlps(ckt->CKTbreaks[0], ckt->CKTtime, 100) ||
            ckt->CKTbreaks[0] <= ckt->CKTtime + ckt->CKTminBreak) {
#ifdef STEPDEBUG
            PSSDBG( "throwing out permanent breakpoint times <= current time (brk pt: %g)\n", ckt->CKTbreaks [0]) ;
            PSSDBG( "ckt_time: %g    ckt_min_break: %g\n", ckt->CKTtime, ckt->CKTminBreak) ;
#endif
            CKTclrBreak(ckt);
        } else {
            break;
        }
    }
    /* Force the breakpoint if appropriate */
    if(ckt->CKTtime + ckt->CKTdelta > ckt->CKTbreaks[0]) {
        ckt->CKTbreak = 1;
        ckt->CKTsaveDelta = ckt->CKTdelta;
        ckt->CKTdelta = ckt->CKTbreaks[0] - ckt->CKTtime;
    }

/* gtri - end - wbk - Modify Breakpoint stuff */

/* gtri - begin - wbk - Do event solution */

    if(ckt->evt->counts.num_insts > 0) {

        /* if time = 0 and op_alternate was specified as false during */
        /* dcop analysis, call any changed instances to let them */
        /* post their outputs with their associated delays */
        if((ckt->CKTtime == 0.0) && (! ckt->evt->options.op_alternate))
            EVTiter(ckt);

        /* while there are events on the queue with event time <= next */
        /* projected analog time, process them */
        while((g_mif_info.circuit.evt_step = EVTnext_time(ckt))
               <= (ckt->CKTtime + ckt->CKTdelta)) {

            /* Initialize temp analog bkpt to infinity */
            g_mif_info.breakpoint.current = HUGE_VAL;

            /* Pull items off queue and process them */
            EVTdequeue(ckt, g_mif_info.circuit.evt_step);
            EVTiter(ckt);

            /* If any instances have forced an earlier */
            /* next analog time, cut the delta */
            if(ckt->CKTbreaks[0] < g_mif_info.breakpoint.current)
                if(ckt->CKTbreaks[0] > ckt->CKTtime + ckt->CKTminBreak)
                    g_mif_info.breakpoint.current = ckt->CKTbreaks[0];
            if(g_mif_info.breakpoint.current < ckt->CKTtime + ckt->CKTdelta) {
                /* Breakpoint must be > last accepted timepoint */
                /* and >= current event time */
                if(g_mif_info.breakpoint.current >  ckt->CKTtime + ckt->CKTminBreak  &&
                   g_mif_info.breakpoint.current >= g_mif_info.circuit.evt_step) {
                    ckt->CKTsaveDelta = ckt->CKTdelta;
                    ckt->CKTdelta = g_mif_info.breakpoint.current - ckt->CKTtime;
                    g_mif_info.breakpoint.last = ckt->CKTtime + ckt->CKTdelta;
                }
            }

        } /* end while next event time <= next analog time */
    } /* end if there are event instances */

/* gtri - end - wbk - Do event solution */

#endif

    /* What is that??? */
    for(i=5; i>=0; i--)
        ckt->CKTdeltaOld[i+1] = ckt->CKTdeltaOld[i];
    ckt->CKTdeltaOld[0] = ckt->CKTdelta;

    temp = ckt->CKTstates[ckt->CKTmaxOrder+1];
    for(i=ckt->CKTmaxOrder;i>=0;i--) {
        ckt->CKTstates[i+1] = ckt->CKTstates[i];
    }
    ckt->CKTstates[0] = temp;

/* 600 */
    for (;;) {
#ifdef XSPICE
/* gtri - add - wbk - 4/17/91 - Fix Berkeley bug */
/* This is needed here to allow CAPask to output currents */
/* during Transient analysis.  A grep for CKTcurrentAnalysis */
/* indicates that it should not hurt anything else ... */

        ckt->CKTcurrentAnalysis = DOING_TRAN;

/* gtri - end - wbk - 4/17/91 - Fix Berkeley bug */
#endif
        olddelta=ckt->CKTdelta;
        /* time abort? */
        ckt->CKTtime += ckt->CKTdelta;
        ckt->CKTdeltaOld[0]=ckt->CKTdelta;
        NIcomCof(ckt);
#ifdef PREDICTOR
        error = NIpred(ckt);
#endif /* PREDICTOR */
        save_mode = ckt->CKTmode;
        save_order = ckt->CKTorder;
#ifdef XSPICE
/* gtri - begin - wbk - Add Breakpoint stuff */

        /* Initialize temporary breakpoint to infinity */
        g_mif_info.breakpoint.current = HUGE_VAL;

/* gtri - end - wbk - Add Breakpoint stuff */


/* gtri - begin - wbk - add convergence problem reporting flags */
        /* delta is forced to equal delmin on last attempt near line 650 */
        if(ckt->CKTdelta <= ckt->CKTdelmin)
            ckt->enh->conv_debug.last_NIiter_call = MIF_TRUE;
        else
            ckt->enh->conv_debug.last_NIiter_call = MIF_FALSE;
/* gtri - begin - wbk - add convergence problem reporting flags */


/* gtri - begin - wbk - Call all hybrids */

/* gtri - begin - wbk - Set evt_step */

        if(ckt->evt->counts.num_insts > 0) {
            g_mif_info.circuit.evt_step = ckt->CKTtime;
        }
/* gtri - end - wbk - Set evt_step */
#endif

        /* Enhancement-118: under KLU, force a full factorization every PSS
         * timestep. NIiter otherwise reuses `klu_refactor` (the previous pivot
         * ordering, values only) for speed; across PSS's very fine,
         * breakpoint-dense shooting timesteps that reused ordering accumulates
         * just enough numerical error to inflate the local truncation error,
         * which collapses the step size into a ~20-million-step run that never
         * finishes. Setting NISHOULDREORDER makes NIiter take the accurate
         * SMPreorder (`klu_factor`, re-pivoted) path, so KLU PSS converges to
         * the same result as Sparse. (Sparse's own factor is accurate enough to
         * not need this; a plain `.tran` under KLU is unaffected -- its steps
         * are coarse enough that the refactor error never matters.) */
        if (ckt->CKTmatrix->CKTkluMODE)
            ckt->CKTniState |= NISHOULDREORDER;
        converged = NIiter(ckt,ckt->CKTtranMaxIter);

#ifdef XSPICE
        if(ckt->evt->counts.num_insts > 0) {
            g_mif_info.circuit.evt_step = ckt->CKTtime;
            EVTcall_hybrids(ckt);
        }
/* gtri - end - wbk - Call all hybrids */

#endif
        ckt->CKTstat->STATtimePts ++;
        ckt->CKTmode = (ckt->CKTmode&MODEUIC)|MODETRAN | MODEINITPRED;
        if(firsttime) {
            memcpy(ckt->CKTstate2, ckt->CKTstate1,
                   (size_t) ckt->CKTnumStates * sizeof(double));
            memcpy(ckt->CKTstate3, ckt->CKTstate1,
                   (size_t) ckt->CKTnumStates * sizeof(double));
        }
        /* txl, cpl addition */
        if (converged == 1111) {
                return(converged);
        }

#ifdef STEPDEBUG
        if (pss_state == PSS)
            PSSDBG( "pss_state: %d, converged: %d\n", pss_state, converged) ;
#endif
        if(converged != 0) {
            ckt->CKTtime = ckt->CKTtime - ckt->CKTdelta;
            ckt->CKTstat->STATrejected++;
            ckt->CKTdelta = ckt->CKTdelta/8;
#ifdef STEPDEBUG
            PSSDBG( "delta cut to %g for non-convergence\n", ckt->CKTdelta) ;
            fflush(stdout);
#endif
            if(firsttime) {
                ckt->CKTmode = (ckt->CKTmode&MODEUIC) | MODETRAN | MODEINITTRAN;
            }
            ckt->CKTorder = 1;

#ifdef XSPICE
/* gtri - begin - wbk - Add Breakpoint stuff */

        /* Force backup if temporary breakpoint is < current time */
        } else if(g_mif_info.breakpoint.current < ckt->CKTtime) {
            ckt->CKTsaveDelta = ckt->CKTdelta;
            ckt->CKTtime -= ckt->CKTdelta;
            ckt->CKTdelta = g_mif_info.breakpoint.current - ckt->CKTtime;
            g_mif_info.breakpoint.last = ckt->CKTtime + ckt->CKTdelta;

            if(firsttime) {
                ckt->CKTmode = (ckt->CKTmode&MODEUIC)|MODETRAN | MODEINITTRAN;
            }
            ckt->CKTorder = 1;

/* gtri - end - wbk - Add Breakpoint stuff */
#endif

        } else {
            if (firsttime) {
                firsttime = 0;
                goto nextTime;  /* no check on
                                 * first time point
                                 */
            }
            newdelta = ckt->CKTdelta;
            error = CKTtrunc(ckt,&newdelta);
            if(error) {
                UPDATE_STATS(DOING_TRAN);
                return(error);
            }
            if (newdelta > .9 * ckt->CKTdelta) {
                if ((ckt->CKTorder == 1) && (ckt->CKTmaxOrder > 1)) { /* don't rise the order for backward Euler */
                    newdelta = ckt->CKTdelta;
                    ckt->CKTorder = 2;
                    error = CKTtrunc(ckt, &newdelta);
                    if (error) {
                        UPDATE_STATS(DOING_TRAN);
                        return(error);
                    }
                    if (newdelta <= 1.05 * ckt->CKTdelta) {
                        ckt->CKTorder = 1;
                    }
                }
                /* time point OK  - 630 */
                ckt->CKTdelta = newdelta;
#ifdef NDEV
                if (!ft_norefprint) {
                    /* show a time process indicator, by Gong Ding, gdiso@ustc.edu */
                    if (ckt->CKTtime / ckt->CKTfinalTime * 100 < 10.0)
                        PSSDBG( "%%%3.2lf\b\b\b\b\b", ckt->CKTtime / ckt->CKTfinalTime * 100);
                    else  if (ckt->CKTtime / ckt->CKTfinalTime * 100 < 100.0)
                        PSSDBG( "%%%4.2lf\b\b\b\b\b\b", ckt->CKTtime / ckt->CKTfinalTime * 100);
                    else
                        PSSDBG( "%%%5.2lf\b\b\b\b\b\b\b", ckt->CKTtime / ckt->CKTfinalTime * 100);
                    fflush(stdout);
                }
#endif

#ifdef STEPDEBUG
                PSSDBG( "delta set to truncation error result: %g. Point accepted at CKTtime: %g\n", ckt->CKTdelta, ckt->CKTtime) ;
                fflush(stdout);
#endif


                /* go to 650 - trapezoidal */
                goto nextTime;

            } else { /* newdelta <= .9 * ckt->CKTdelta */
                ckt->CKTtime = ckt->CKTtime -ckt->CKTdelta;
                ckt->CKTstat->STATrejected ++;
                ckt->CKTdelta = newdelta;
#ifdef STEPDEBUG
                PSSDBG( "delta set to truncation error result:point rejected\n") ;
#endif
            }
        }

        if (ckt->CKTdelta <= ckt->CKTdelmin) {
            if (olddelta > ckt->CKTdelmin) {
                ckt->CKTdelta = ckt->CKTdelmin;
#ifdef STEPDEBUG
                PSSDBG( "delta at delmin\n");
#endif
            } else {
                UPDATE_STATS(DOING_TRAN);
                errMsg = CKTtrouble(ckt, "Timestep too small");
                return(E_TIMESTEP);
            }
        }
#ifdef XSPICE
/* gtri - begin - wbk - Do event backup */

        if(ckt->evt->counts.num_insts > 0)
            EVTbackup(ckt, ckt->CKTtime + ckt->CKTdelta);

/* gtri - end - wbk - Do event backup */
#endif
    }
    /* NOTREACHED */
}

static int
DFT
(
    long int ndata,  /* number of entries in the Time and Value arrays */
    int numFreq,     /* number of harmonics to calculate */
    double *thd,     /* total harmonic distortion (percent) to be returned */
    double *Time,    /* times at which the voltage/current values were measured */
    double *Value,   /* voltage or current vector whose transform is desired */
    double FundFreq, /* the fundamental frequency of the analysis */
    double *Freq,    /* the frequency value of the various harmonics */
    double *Mag,     /* the Magnitude of the fourier transform */
    double *Phase,   /* the Phase of the fourier transform */
    double *nMag,    /* the normalized magnitude of the transform: nMag (fund) = 1 */
    double *nPhase   /* the normalized phase of the transform: Nphase (fund) = 0 */
)
{
    /* Note: we can consider these as a set of arrays.  The sizes are:
     * Time [ndata], Value [ndata], Freq [numFreq], Mag [numfreq],
     * Phase [numfreq], nMag [numfreq], nPhase [numfreq]
     *
     * The arrays must all be allocated by the caller.
     * The Time and Value array must be reasonably distributed over at
     * least one full period of the fundamental Frequency for the
     * fourier transform to be useful.  The function will take the
     * last period of the frequency as data for the transform.
     *
     * We are assuming that the caller has provided exactly one period
     * of the fundamental frequency.  */
    int i, j;
    double tmp;

    NG_IGNORE (Time);

    /* clear output/computation arrays */

    for (i = 0; i < numFreq; i++) {
        Mag [i] = 0;
        Phase [i] = 0;
    }

    for (i = 0; i < ndata; i++) {
        for (j = 0; j < numFreq; j++) {
            Mag [j] += (Value [i] * sin (j * 2.0 * M_PI * i / ((double)ndata)));
            Phase [j] += (Value [i] * cos (j * 2.0 * M_PI * i / ((double)ndata)));
        }
    }

    Mag [0] = Phase [0] / (double)ndata;
    Phase [0] = 0;
    nMag [0] = 0;
    nPhase [0] = 0;
    Freq [0] = 0;
    *thd = 0;

    for (i = 1; i < numFreq; i++) {
        tmp = Mag [i] * 2.0 / (double)ndata;
        Phase [i] *= 2.0 / (double)ndata;
        Freq [i] = i * FundFreq;
        Mag [i] = hypot (tmp, Phase [i]);
        Phase [i] = atan2 (Phase [i], tmp) * 180.0 / M_PI;
        nMag [i] = Mag [i] / Mag [1];
        nPhase [i] = Phase [i] - Phase [1];
        if (i > 1)
            *thd += nMag [i] * nMag [i];
    }

    *thd = 100 * sqrt (*thd);
    return (OK);
}
