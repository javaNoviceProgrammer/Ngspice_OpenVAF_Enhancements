/* Enhancement-200: Touchstone (.sNp) -> Verilog-A n-port converter, in C.
 *
 * A C port of the pure-Python snp2va.py (Enhancement-199): parse a Touchstone
 * S-parameter file, convert S -> Y, fit every Y_ij(f) with a common-pole rational
 * (Gustavsen vector fitting), and emit a Verilog-A n-port realized with laplace_nd,
 * so through OpenVAF/OSDI it works in AC and transient. Used by the `pre_snp`
 * front-end command, which then invokes openvaf-r to compile the emitted .va.
 *
 * The numerical core is self-contained (only stdio/stdlib/string/math/complex),
 * so it does not pull in ngspice's own complex.h. Public entry point:
 *     int snp2va_convert(const char *snp, const char *va, const char *module,
 *                        char *msg, int msglen);
 * returns 0 on success, non-zero on failure (msg gets a one-line status).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <ctype.h>
#include <complex.h>

#include "snp2va.h"

typedef double _Complex cplx;

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* ============================ linear algebra ============================ */

/* Least-squares min||A x - b|| for a REAL overdetermined system (m>=n) via
 * Householder QR. A is row-major m*n, b length m, x length n. Returns 0 on ok. */
static int lstsq_real(double *A, double *b, int m, int n, double *x)
{
    int i, j, k;
    for (k = 0; k < n; k++) {
        double norm = 0.0;
        for (i = k; i < m; i++) norm += A[i*n+k]*A[i*n+k];
        norm = sqrt(norm);
        if (norm == 0.0) continue;
        double alpha = (A[k*n+k] >= 0.0) ? -norm : norm;
        double *v = (double*) calloc((size_t) m, sizeof(double));
        v[k] = A[k*n+k] - alpha;
        for (i = k+1; i < m; i++) v[i] = A[i*n+k];
        double vn2 = 0.0;
        for (i = k; i < m; i++) vn2 += v[i]*v[i];
        if (vn2 == 0.0) { free(v); continue; }
        for (j = k; j < n; j++) {
            double s = 0.0;
            for (i = k; i < m; i++) s += v[i]*A[i*n+j];
            s = s*2.0/vn2;
            for (i = k; i < m; i++) A[i*n+j] -= s*v[i];
        }
        double s = 0.0;
        for (i = k; i < m; i++) s += v[i]*b[i];
        s = s*2.0/vn2;
        for (i = k; i < m; i++) b[i] -= s*v[i];
        free(v);
    }
    for (i = n-1; i >= 0; i--) {
        double acc = b[i];
        for (j = i+1; j < n; j++) acc -= A[i*n+j]*x[j];
        x[i] = (A[i*n+i] != 0.0) ? acc/A[i*n+i] : 0.0;
    }
    return 0;
}

/* In-place inverse of an n x n complex matrix (row-major), Gauss-Jordan w/ pivot.
 * Returns 0 on ok, 1 if singular. */
static int mat_inv_c(cplx *M, int n)
{
    int i, j, c, p;
    cplx *A = (cplx*) malloc((size_t) n*2*n*sizeof(cplx));
    for (i = 0; i < n; i++) {
        for (j = 0; j < n; j++) A[i*2*n+j] = M[i*n+j];
        for (j = 0; j < n; j++) A[i*2*n+n+j] = (i==j) ? 1.0 : 0.0;
    }
    for (c = 0; c < n; c++) {
        p = c; double best = cabs(A[c*2*n+c]);
        for (i = c+1; i < n; i++) { double v = cabs(A[i*2*n+c]); if (v > best) { best = v; p = i; } }
        if (best == 0.0) { free(A); return 1; }
        if (p != c) for (j = 0; j < 2*n; j++) { cplx t = A[c*2*n+j]; A[c*2*n+j]=A[p*2*n+j]; A[p*2*n+j]=t; }
        cplx d = A[c*2*n+c];
        for (j = 0; j < 2*n; j++) A[c*2*n+j] /= d;
        for (i = 0; i < n; i++) if (i != c) {
            cplx f = A[i*2*n+c];
            if (f != 0.0) for (j = 0; j < 2*n; j++) A[i*2*n+j] -= f*A[c*2*n+j];
        }
    }
    for (i = 0; i < n; i++) for (j = 0; j < n; j++) M[i*n+j] = A[i*2*n+n+j];
    free(A);
    return 0;
}

/* Monic polynomial (DESCENDING, len nr+1) from roots. coef must hold nr+1. */
static void poly_from_roots(const cplx *roots, int nr, cplx *coef)
{
    int i, k;
    coef[0] = 1.0;
    for (i = 1; i <= nr; i++) coef[i] = 0.0;
    for (k = 0; k < nr; k++) {
        for (i = k+1; i >= 1; i--) coef[i] = coef[i] - roots[k]*coef[i-1];
    }
}

static cplx poly_eval(const cplx *c, int deg, cplx x)
{
    cplx r = 0.0; int i;
    for (i = 0; i <= deg; i++) r = r*x + c[i];
    return r;
}

/* All roots of a DESCENDING-coeff polynomial (deg = len-1) via Durand-Kerner.
 * roots[] must hold deg. Returns 0 on ok. */
static int poly_roots(const cplx *cin, int deg, cplx *roots)
{
    int i, j, it;
    if (deg <= 0) return 0;
    cplx *c = (cplx*) malloc((size_t)(deg+1)*sizeof(cplx));
    for (i = 0; i <= deg; i++) c[i] = cin[i] / cin[0];   /* monic */
    cplx seed = 0.4 + 0.9*I;
    for (i = 0; i < deg; i++) roots[i] = cpow(seed, (double) i);
    for (it = 0; it < 500; it++) {
        double maxstep = 0.0;
        for (i = 0; i < deg; i++) {
            cplx num = poly_eval(c, deg, roots[i]);
            cplx den = 1.0;
            for (j = 0; j < deg; j++) if (j != i) den *= (roots[i]-roots[j]);
            cplx step = (cabs(den) > 1e-300) ? num/den : 0.0;
            roots[i] -= step;
            if (cabs(step) > maxstep) maxstep = cabs(step);
        }
        if (maxstep < 1e-14) break;
    }
    free(c);
    return 0;
}

/* ============================ Touchstone I/O ============================ */

typedef struct { double *freqs; cplx *S; int nf; int N; double z0; char ptype; } TS;

static void ts_free(TS *t) { free(t->freqs); free(t->S); }

/* returns 0 on ok */
static int parse_touchstone(const char *fn, TS *out, char *msg, int msglen)
{
    FILE *f = fopen(fn, "r");
    if (!f) { snprintf(msg, (size_t) msglen, "cannot open '%s'", fn); return 1; }
    double fmul = 1e9, z0 = 50.0; char ptype = 'S'; char fmt[3] = "MA";
    /* collect all numeric tokens after the '#' options line(s) */
    double *nums = NULL; long ncap = 0, nn = 0;
    char line[4096];
    while (fgets(line, sizeof line, f)) {
        char *h = strchr(line, '!'); if (h) *h = '\0';
        char *p = line;
        while (*p && isspace((unsigned char)*p)) p++;
        if (*p == '\0') continue;
        if (*p == '#') {
            char *tok = strtok(p+1, " \t\r\n");
            while (tok) {
                if (!strcasecmp(tok,"HZ")) fmul=1.0;
                else if (!strcasecmp(tok,"KHZ")) fmul=1e3;
                else if (!strcasecmp(tok,"MHZ")) fmul=1e6;
                else if (!strcasecmp(tok,"GHZ")) fmul=1e9;
                else if (!strcasecmp(tok,"S")||!strcasecmp(tok,"Y")||!strcasecmp(tok,"Z")) ptype=toupper((unsigned char)tok[0]);
                else if (!strcasecmp(tok,"MA")||!strcasecmp(tok,"DB")||!strcasecmp(tok,"RI")) { fmt[0]=toupper((unsigned char)tok[0]); fmt[1]=toupper((unsigned char)tok[1]); }
                else if (!strcasecmp(tok,"R")) { char *z=strtok(NULL," \t\r\n"); if (z) z0=atof(z); }
                tok = strtok(NULL, " \t\r\n");
            }
            continue;
        }
        /* numeric data line */
        char *tok = strtok(p, " \t\r\n");
        while (tok) {
            char *end; double v = strtod(tok, &end);
            if (end != tok) {
                if (nn >= ncap) { ncap = ncap ? ncap*2 : 1024; nums = (double*) realloc(nums, (size_t) ncap*sizeof(double)); }
                nums[nn++] = v;
            }
            tok = strtok(NULL, " \t\r\n");
        }
    }
    fclose(f);
    /* infer port count N: try the file extension .sNp, else brute force */
    int N = 0;
    const char *dot = strrchr(fn, '.');
    if (dot && (dot[1]=='s'||dot[1]=='S') && (fn[strlen(fn)-1]=='p'||fn[strlen(fn)-1]=='P')) {
        N = atoi(dot+2);
    }
    if (N <= 0) {
        int c;
        for (c = 1; c <= 16; c++) if (nn % (1 + 2*c*c) == 0) { N = c; break; }
    }
    if (N <= 0) { free(nums); snprintf(msg,(size_t)msglen,"cannot determine port count"); return 1; }
    int rec = 1 + 2*N*N;
    int nf = (int)(nn / rec);
    if (nf < 2) { free(nums); snprintf(msg,(size_t)msglen,"too few frequency points (%d)", nf); return 1; }
    out->freqs = (double*) malloc((size_t) nf*sizeof(double));
    out->S = (cplx*) malloc((size_t) nf*N*N*sizeof(cplx));
    out->nf = nf; out->N = N; out->z0 = z0; out->ptype = ptype;
    int r, kk;
    for (r = 0; r < nf; r++) {
        double *chunk = nums + (long) r*rec;
        out->freqs[r] = chunk[0]*fmul;
        double *vals = chunk+1;
        cplx pv[16*16];
        for (kk = 0; kk < N*N; kk++) {
            double a = vals[2*kk], b = vals[2*kk+1];
            if (!strcmp(fmt,"MA")) pv[kk] = a*cexp(I*b*M_PI/180.0);
            else if (!strcmp(fmt,"DB")) pv[kk] = pow(10.0,a/20.0)*cexp(I*b*M_PI/180.0);
            else pv[kk] = a + I*b;
        }
        /* Touchstone: N=2 order is S11 S21 S12 S22; general is row-major */
        cplx *M = out->S + (long) r*N*N;
        if (N == 2) { M[0]=pv[0]; M[2]=pv[1]; M[1]=pv[2]; M[3]=pv[3]; }
        else for (kk = 0; kk < N*N; kk++) M[kk] = pv[kk];
    }
    free(nums);
    return 0;
}

/* S/Y/Z -> Y (row-major per frequency), Yout must hold nf*N*N. */
static int to_Y(const TS *t, cplx *Yout)
{
    int N = t->N, r, i, j;
    cplx *tmp = (cplx*) malloc((size_t) N*N*sizeof(cplx));
    for (r = 0; r < t->nf; r++) {
        const cplx *M = t->S + (long) r*N*N;
        cplx *Y = Yout + (long) r*N*N;
        if (t->ptype == 'Y') { for (i=0;i<N*N;i++) Y[i]=M[i]; }
        else if (t->ptype == 'Z') { for (i=0;i<N*N;i++) Y[i]=M[i]; if (mat_inv_c(Y,N)) { free(tmp); return 1; } }
        else { /* S -> Y = (1/z0)(I-S)(I+S)^-1 */
            cplx *IpS = tmp;
            for (i=0;i<N;i++) for (j=0;j<N;j++) IpS[i*N+j] = ((i==j)?1.0:0.0) + M[i*N+j];
            if (mat_inv_c(IpS,N)) { free(tmp); return 1; }
            for (i=0;i<N;i++) for (j=0;j<N;j++) {
                cplx acc = 0.0; int k;
                for (k=0;k<N;k++) acc += (((i==k)?1.0:0.0) - M[i*N+k]) * IpS[k*N+j];
                Y[i*N+j] = acc / t->z0;
            }
        }
    }
    free(tmp);
    return 0;
}

/* ============================ vector fitting ============================ */
/* layout: for each pole, 0='real', 1='cc-start' (its conjugate is the next). */
static int build_layout(const cplx *poles, int Np, int *lay)
{
    int i = 0, m = 0;
    while (i < Np) {
        if (fabs(cimag(poles[i])) < 1e-9*fabs(creal(poles[i]))+1e-30) { lay[m++] = 0; i += 1; }
        else { lay[m++] = 1; i += 2; }
    }
    return m;   /* number of blocks */
}

/* complex partial-fraction basis (real-valued cc combos), Ns x Np, row-major */
static void build_basis(const cplx *s, int Ns, const cplx *poles, int Np, cplx *A)
{
    int r, i;
    for (r = 0; r < Ns; r++) {
        i = 0;
        while (i < Np) {
            if (fabs(cimag(poles[i])) < 1e-9*fabs(creal(poles[i]))+1e-30) {
                A[r*Np+i] = 1.0/(s[r]-poles[i]); i += 1;
            } else {
                cplx p = poles[i];
                A[r*Np+i]   = 1.0/(s[r]-p) + 1.0/(s[r]-conj(p));
                A[r*Np+i+1] = I/(s[r]-p) - I/(s[r]-conj(p));
                i += 2;
            }
        }
    }
}

/* complex residues from real ctil coeffs, per real/cc layout */
static void ctil_to_cres(const double *ctil, const cplx *poles, int Np, cplx *cres)
{
    int i = 0;
    while (i < Np) {
        if (fabs(cimag(poles[i])) < 1e-9*fabs(creal(poles[i]))+1e-30) { cres[i] = ctil[i]; i += 1; }
        else { cres[i] = ctil[i] + I*ctil[i+1]; cres[i+1] = conj(cres[i]); i += 2; }
    }
}

/* One vector-fit run (fixed pole count). s,F normalized. Returns fit in poles/res/d/e. */
static void vector_fit(const cplx *s, int Ns, const cplx *F, int Nf, int Np,
                       cplx *poles, cplx *res, double *d, double *e, int n_iter)
{
    int iter, i, j, k, r;
    cplx *A = (cplx*) malloc((size_t) Ns*Np*sizeof(cplx));
    for (iter = 0; iter < n_iter; iter++) {
        build_basis(s, Ns, poles, Np, A);
        int ncol = Nf*(Np+2) + Np;
        int nrow = Ns*Nf;
        /* real-stacked LS: (2*nrow) x ncol */
        double *M = (double*) calloc((size_t)(2*nrow)*ncol, sizeof(double));
        double *b = (double*) calloc((size_t)(2*nrow), sizeof(double));
        for (k = 0; k < Nf; k++) {
            for (r = 0; r < Ns; r++) {
                int row = k*Ns + r;
                cplx Fkr = F[(long)k*Ns+r];
                for (j = 0; j < Np; j++) {
                    cplx a = A[r*Np+j];
                    M[(row)*ncol + k*(Np+2)+j]        = creal(a);
                    M[(row+nrow)*ncol + k*(Np+2)+j]   = cimag(a);
                    cplx neg = -Fkr*a;
                    M[(row)*ncol + Nf*(Np+2)+j]       = creal(neg);
                    M[(row+nrow)*ncol + Nf*(Np+2)+j]  = cimag(neg);
                }
                M[(row)*ncol + k*(Np+2)+Np]        = 1.0;   /* d (real) */
                M[(row)*ncol + k*(Np+2)+Np+1]      = creal(s[r]);   /* e*s */
                M[(row+nrow)*ncol + k*(Np+2)+Np+1] = cimag(s[r]);
                b[row]      = creal(Fkr);
                b[row+nrow] = cimag(Fkr);
            }
        }
        double *x = (double*) calloc((size_t) ncol, sizeof(double));
        lstsq_real(M, b, 2*nrow, ncol, x);
        double *ctil = x + Nf*(Np+2);
        cplx *cres = (cplx*) malloc((size_t) Np*sizeof(cplx));
        ctil_to_cres(ctil, poles, Np, cres);
        /* relocate: roots of  D(s) + sum cres_i * D(s)/(s-a_i) */
        cplx *D = (cplx*) malloc((size_t)(Np+1)*sizeof(cplx));
        poly_from_roots(poles, Np, D);
        cplx *numsig = (cplx*) malloc((size_t)(Np+1)*sizeof(cplx));
        for (i = 0; i <= Np; i++) numsig[i] = D[i];
        cplx *Di = (cplx*) malloc((size_t) Np*sizeof(cplx));
        cplx *sub = (cplx*) malloc((size_t) Np*sizeof(cplx));   /* poles minus i */
        for (i = 0; i < Np; i++) {
            int t = 0; for (j = 0; j < Np; j++) if (j != i) sub[t++] = poles[j];
            poly_from_roots(sub, Np-1, Di);                     /* len Np, degree Np-1 */
            for (j = 0; j < Np; j++) numsig[j+1] += cres[i]*Di[j]; /* align: Di is degree Np-1 (len Np), numsig degree Np (len Np+1) */
        }
        cplx *newp = (cplx*) malloc((size_t) Np*sizeof(cplx));
        poly_roots(numsig, Np, newp);
        for (i = 0; i < Np; i++) if (creal(newp[i]) > 0) newp[i] = -creal(newp[i]) + I*cimag(newp[i]);
        /* sort: real poles first, then by real, imag (keeps cc pairs adjacent-ish) */
        for (i = 0; i < Np; i++) for (j = i+1; j < Np; j++) {
            int swap = 0;
            double ki = (fabs(cimag(newp[i]))>1e-6)?1:0, kj = (fabs(cimag(newp[j]))>1e-6)?1:0;
            if (kj < ki) swap = 1;
            else if (kj == ki) { if (creal(newp[j]) < creal(newp[i]) - 1e-30) swap = 1;
                                 else if (fabs(creal(newp[j])-creal(newp[i]))<1e-30 && cimag(newp[j])<cimag(newp[i])) swap = 1; }
            if (swap) { cplx t = newp[i]; newp[i]=newp[j]; newp[j]=t; }
        }
        for (i = 0; i < Np; i++) poles[i] = newp[i];
        free(M); free(b); free(x); free(cres); free(D); free(numsig); free(Di); free(sub); free(newp);
    }
    /* final residues (fixed poles) */
    build_basis(s, Ns, poles, Np, A);
    for (k = 0; k < Nf; k++) {
        int ncol = Np+2, nrow = Ns;
        double *M = (double*) calloc((size_t)(2*nrow)*ncol, sizeof(double));
        double *b = (double*) calloc((size_t)(2*nrow), sizeof(double));
        for (r = 0; r < Ns; r++) {
            cplx Fkr = F[(long)k*Ns+r];
            for (j = 0; j < Np; j++) { M[r*ncol+j]=creal(A[r*Np+j]); M[(r+nrow)*ncol+j]=cimag(A[r*Np+j]); }
            M[r*ncol+Np]=1.0;
            M[r*ncol+Np+1]=creal(s[r]); M[(r+nrow)*ncol+Np+1]=cimag(s[r]);
            b[r]=creal(Fkr); b[r+nrow]=cimag(Fkr);
        }
        double *x = (double*) calloc((size_t) ncol, sizeof(double));
        lstsq_real(M, b, 2*nrow, ncol, x);
        cplx *cr = (cplx*) malloc((size_t) Np*sizeof(cplx));
        ctil_to_cres(x, poles, Np, cr);
        for (j = 0; j < Np; j++) res[(long)k*Np+j] = cr[j];
        d[k] = x[Np]; e[k] = x[Np+1];
        free(M); free(b); free(x); free(cr);
    }
    free(A);
}

static void seed_poles(double fmin, double fmax, int npair, cplx *p)
{
    int k;
    for (k = 0; k < npair; k++) {
        double beta = (npair==1) ? 2*M_PI*sqrt(fmin*fmax)
                                 : 2*M_PI*fmin*pow(fmax/fmin, (double)k/(npair-1));
        double a = beta/100.0;
        p[2*k]   = -a + I*beta;
        p[2*k+1] = -a - I*beta;
    }
}

/* ============================ emit VA ============================ */
/* strictly-proper numerator polynomial (ASCENDING, real) for Y_k = d + sum res/(s-p).
 * num = d*D + sum_i res_i * D/(s-p_i). out[] holds Np+1 (degree Np). */
static void num_proper(const cplx *poles, int Np, const cplx *res_k, double d_k, double *out_asc)
{
    int i, j, t;
    cplx *D = (cplx*) malloc((size_t)(Np+1)*sizeof(cplx));
    poly_from_roots(poles, Np, D);
    cplx *num = (cplx*) calloc((size_t)(Np+1), sizeof(cplx));
    for (i = 0; i <= Np; i++) num[i] = d_k*D[i];
    cplx *Di = (cplx*) malloc((size_t) Np*sizeof(cplx));
    cplx *sub = (cplx*) malloc((size_t) Np*sizeof(cplx));
    for (i = 0; i < Np; i++) {
        t = 0; for (j = 0; j < Np; j++) if (j != i) sub[t++] = poles[j];
        poly_from_roots(sub, Np-1, Di);           /* degree Np-1, len Np */
        for (j = 0; j < Np; j++) num[j+1] += res_k[i]*Di[j];
    }
    for (i = 0; i <= Np; i++) out_asc[Np-i] = creal(num[i]);   /* descending->ascending, real */
    free(D); free(num); free(Di); free(sub);
}

static void emit_arr(FILE *f, const double *v, int n)
{
    int i; fprintf(f, "'{");
    for (i = 0; i < n; i++) fprintf(f, "%s%.12g", i?", ":"", v[i]);
    fprintf(f, "}");
}

/* ============================ public API ============================ */
int snp2va_convert(const char *snpfile, const char *vafile, const char *module,
                   char *msg, int msglen)
{
    TS ts; int i, j, k, r;
    if (parse_touchstone(snpfile, &ts, msg, msglen)) return 1;
    int N = ts.N, nf = ts.nf;
    cplx *Y = (cplx*) malloc((size_t) nf*N*N*sizeof(cplx));
    if (to_Y(&ts, Y)) { snprintf(msg,(size_t)msglen,"S->Y conversion failed (singular)"); ts_free(&ts); free(Y); return 1; }
    /* Y entries in row-major i*N+j order, each a length-nf vector */
    int Nf = N*N;
    cplx *s = (cplx*) malloc((size_t) nf*sizeof(cplx));
    for (r = 0; r < nf; r++) s[r] = I*2*M_PI*ts.freqs[r];
    double wn = sqrt(cabs(s[0])*cabs(s[nf-1]));
    cplx *sn = (cplx*) malloc((size_t) nf*sizeof(cplx));
    for (r = 0; r < nf; r++) sn[r] = s[r]/wn;
    cplx *F = (cplx*) malloc((size_t) Nf*nf*sizeof(cplx));
    for (i = 0; i < N; i++) for (j = 0; j < N; j++) for (r = 0; r < nf; r++)
        F[(long)(i*N+j)*nf+r] = Y[(long)r*N*N + i*N+j];

    /* ---- order selection: climb, keep best STABLE fit, knee near a floor ---- */
    double fmin = ts.freqs[0], fmax = ts.freqs[nf-1], tol = 1e-3;
    cplx *bestP=NULL,*bestRes=NULL; double *bestD=NULL,*bestE=NULL; int bestNp=0; double bestErr=1e300;
    cplx *prevP=NULL,*prevRes=NULL; double *prevD=NULL,*prevE=NULL; int prevNp=0; double prevErr=-1, firstErr=-1;
    int chosenP=0; cplx *chP=NULL,*chRes=NULL; double *chD=NULL,*chE=NULL;
    int npair;
    for (npair = 1; npair <= 12; npair++) {
        int Np = 2*npair;
        cplx *P = (cplx*) malloc((size_t) Np*sizeof(cplx));
        cplx *res = (cplx*) malloc((size_t) Nf*Np*sizeof(cplx));
        double *dd = (double*) malloc((size_t) Nf*sizeof(double));
        double *ee = (double*) malloc((size_t) Nf*sizeof(double));
        cplx *p0 = (cplx*) malloc((size_t) Np*sizeof(cplx));
        seed_poles(fmin, fmax, npair, p0);
        for (i = 0; i < Np; i++) P[i] = p0[i]/wn;
        vector_fit(sn, nf, F, Nf, Np, P, res, dd, ee, 12);
        /* un-normalize */
        for (i = 0; i < Np; i++) P[i] *= wn;
        for (k = 0; k < Nf; k++) { for (i = 0; i < Np; i++) res[(long)k*Np+i] *= wn; ee[k] /= wn; }
        /* rms rel error + stability */
        double err = 0.0; int stable = 1;
        for (i = 0; i < Np; i++) if (creal(P[i]) > 1e-6) stable = 0;
        for (k = 0; k < Nf; k++) {
            double numr=0, denr=0;
            for (r = 0; r < nf; r++) {
                cplx fit = dd[k] + s[r]*ee[k];
                for (i = 0; i < Np; i++) fit += res[(long)k*Np+i]/(s[r]-P[i]);
                cplx dif = fit - F[(long)k*nf+r];
                numr += creal(dif)*creal(dif)+cimag(dif)*cimag(dif);
                cplx fv = F[(long)k*nf+r];
                denr += creal(fv)*creal(fv)+cimag(fv)*cimag(fv);
            }
            double e2 = sqrt(numr)/(sqrt(denr)+1e-300);
            if (e2 > err) err = e2;
        }
        if (!(err==err)) stable = 0;   /* NaN */
        free(p0);
                if (firstErr < 0) firstErr = err;
        int keep_best = stable && err < bestErr;
        if (keep_best) {
            free(bestP);free(bestRes);free(bestD);free(bestE);
            bestP=P;bestRes=res;bestD=dd;bestE=ee;bestNp=Np;bestErr=err;
        }
        if (!stable) { if(!keep_best){free(P);free(res);free(dd);free(ee);} break; }
        if (err < tol) { chosenP=Np; chP=P;chRes=res;chD=dd;chE=ee; if(keep_best){/*owned by best too*/} break; }
        int near_floor = (err < 0.1*firstErr) || (err < 0.05);
        if (prevErr >= 0 && err > 0.7*prevErr && near_floor) {  /* knee at floor -> use prev */
            chosenP=prevNp; chP=prevP;chRes=prevRes;chD=prevD;chE=prevE;
            if (!keep_best) { free(P);free(res);free(dd);free(ee); }
            break;
        }
        /* shift prev <- current (free old prev unless it is the best) */
        if (prevP && prevP!=bestP) { free(prevP);free(prevRes);free(prevD);free(prevE); }
        prevP=P;prevRes=res;prevD=dd;prevE=ee;prevNp=Np;prevErr=err;
    }
    /* pick chosen, else best, else prev */
    cplx *P; cplx *res; double *dd,*ee; int Np;
    if (chP) { P=chP;res=chRes;dd=chD;ee=chE;Np=chosenP; }
    else if (bestP) { P=bestP;res=bestRes;dd=bestD;ee=bestE;Np=bestNp; }
    else { P=prevP;res=prevRes;dd=prevD;ee=prevE;Np=prevNp; }

    /* ---- emit VA ---- */
    FILE *fo = fopen(vafile, "w");
    if (!fo) { snprintf(msg,(size_t)msglen,"cannot write '%s'", vafile); ts_free(&ts); return 1; }
    double *den = (double*) malloc((size_t)(Np+1)*sizeof(double));
    { cplx *D = (cplx*) malloc((size_t)(Np+1)*sizeof(cplx)); poly_from_roots(P, Np, D);
      for (i = 0; i <= Np; i++) den[Np-i] = creal(D[i]); free(D); }
    fprintf(fo, "`include \"disciplines.vams\"\n\n");
    fprintf(fo, "// Generated by pre_snp from %s\n", snpfile);
    fprintf(fo, "// %d-port, %d common poles; realized with laplace_nd (AC + transient).\n", N, Np);
    fprintf(fo, "module %s(", module);
    for (i = 0; i < N; i++) fprintf(fo, "%sp%d", i?", ":"", i+1);
    fprintf(fo, ");\n    inout ");
    for (i = 0; i < N; i++) fprintf(fo, "%sp%d", i?", ":"", i+1);
    fprintf(fo, ";\n    electrical ");
    for (i = 0; i < N; i++) fprintf(fo, "%sp%d", i?", ":"", i+1);
    fprintf(fo, ";\n    analog begin\n");
    double *nm = (double*) malloc((size_t)(Np+1)*sizeof(double));
    for (i = 0; i < N; i++) {
        fprintf(fo, "        I(p%d) <+ ", i+1);
        for (j = 0; j < N; j++) {
            int idx = i*N+j;
            num_proper(P, Np, res + (long) idx*Np, dd[idx], nm);
            if (j) fprintf(fo, "\n                 + ");
            fprintf(fo, "laplace_nd(V(p%d), ", j+1); emit_arr(fo, nm, Np+1);
            fprintf(fo, ", "); emit_arr(fo, den, Np+1); fprintf(fo, ")");
            if (fabs(ee[idx]) > 1e-30) fprintf(fo, "\n                 + (%.12g)*ddt(V(p%d))", ee[idx], j+1);
        }
        fprintf(fo, ";\n");
    }
    fprintf(fo, "    end\nendmodule\n");
    fclose(fo);
    snprintf(msg,(size_t)msglen,"%d-port, %d poles, rms rel err %.2e", N, Np, bestErr<1e300?bestErr:0.0);
    /* frees (leak-tolerant: one-shot tool) */
    free(den); free(nm); free(Y); free(s); free(sn); free(F); ts_free(&ts);
    return 0;
}

#ifdef SNP2VA_TEST
int main(int argc, char **argv)
{
    setbuf(stderr, NULL);
    if (argc < 3) { fprintf(stderr, "usage: %s file.sNp out.va [module]\n", argv[0]); return 2; }
    char msg[256];
    int rc = snp2va_convert(argv[1], argv[2], argc>3?argv[3]:"nport", msg, sizeof msg);
    fprintf(stderr, "snp2va: %s\n", msg);
    return rc;
}
#endif
