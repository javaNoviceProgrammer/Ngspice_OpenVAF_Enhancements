/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified 1999 Emmanuel Rouat
**********/

    /*
     * NIacIter(ckt)
     *
     *  This subroutine performs the actual numerical iteration.
     *  It uses the sparse matrix stored in the NIstruct by NIinit,
     *  along with the matrix loading program, the load data, the
     *  convergence test function, and the convergence parameters
     * - return value is non-zero for convergence failure 
     */

#include "ngspice/ngspice.h"
#include "ngspice/trandefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sperror.h"

#include <float.h>


/* Enhancement-860: one step of iterative refinement after the ac solve.
 *
 * The factorization takes a pivot down to pivrel (1e-3) of its column's
 * largest entry, and Sparse orders the matrix at the first frequency only.
 * On inductive networks at a few hertz -- a 1 nH branch row carries jwL ~ 1e-8
 * beside entries of order 1 -- that cost up to 6 digits on matrices of
 * condition 5: 22 of 300 networks under Sparse (3.4e-6), 5 under KLU (2e-7),
 * where any backward-stable solve gives 1e-15 and pivrel=1 gave 2e-16.
 *
 * The loaded matrix is copied before it is factored (Sparse factors it in
 * place). After the solve the residual r = b - A x gives the componentwise
 * backward error max |r_i| / (|A| |x| + |b|)_i; where that is above rounding
 * (AC_REFINE_TOL), A d = r is solved with the same factors and x + d is kept
 * if its backward error is smaller. A point that was solved well costs one
 * pass over the matrix's entries. */
#define AC_REFINE_TOL   (64.0 * DBL_EPSILON)
#define AC_REFINE_STEPS 2

static SMPcCopy ac_copy;
static double *ac_buf;
static int ac_buf_n;

static double *
ac_scratch(int n)
{
    if (n + 1 > ac_buf_n) {
        ac_buf = TREALLOC(double, ac_buf, 7 * (size_t) (n + 1));
        ac_buf_n = n + 1;
    }
    return ac_buf;
}

/* the residual b - A x into (rr, ri), and x's componentwise backward error */
static double
ac_residual(CKTcircuit *ckt, int n, const double *br, const double *bi,
            const double *xr, const double *xi,
            double *rr, double *ri, double *den)
{
    double w = 0.0;
    int i;

    SMPcResidual(ckt->CKTmatrix, &ac_copy, n, br, bi, xr, xi, rr, ri, den);
    for (i = 1; i <= n; i++) {
        double num = fabs(rr[i]) + fabs(ri[i]);
        /* a row whose terms are down where doubles lose precision (a deep
         * stopband, 1e-300) has no measurable backward error */
        if (num > 0.0 && den[i] >= DBL_MIN / DBL_EPSILON) {
            double q = num / den[i];
            if (q > w)
                w = q;
        }
    }
    return w;
}

/* x = CKTrhs/CKTirhs, the solution of A x = b with b in (br, bi) */
static void
ac_refine(CKTcircuit *ckt, double *buf, int n)
{
    double *br = buf, *bi = br + (n + 1);
    double *rr = bi + (n + 1), *ri = rr + (n + 1), *den = ri + (n + 1);
    double *yr = den + (n + 1), *yi = yr + (n + 1);
    double *xr = ckt->CKTrhs, *xi = ckt->CKTirhs;
    double w, w1;
    int i, step;

    xr[0] = xi[0] = 0.0;
    w = ac_residual(ckt, n, br, bi, xr, xi, rr, ri, den);
    for (step = 0; step < AC_REFINE_STEPS && w > AC_REFINE_TOL; step++) {
        rr[0] = ri[0] = 0.0;
        SMPcSolve(ckt->CKTmatrix, rr, ri, ckt->CKTrhsSpare, ckt->CKTirhsSpare);
        for (i = 1; i <= n; i++) {
            yr[i] = xr[i] + rr[i];
            yi[i] = xi[i] + ri[i];
        }
        yr[0] = yi[0] = 0.0;
        w1 = ac_residual(ckt, n, br, bi, yr, yi, rr, ri, den);
        if (!(w1 < w))
            break;
        memcpy(xr, yr, (size_t) (n + 1) * sizeof(double));
        memcpy(xi, yi, (size_t) (n + 1) * sizeof(double));
        w = w1;
    }
}

/* before the factorization: the loaded matrix */
static void
ac_copy_matrix(CKTcircuit *ckt)
{
    SMPcCopyLoaded(ckt->CKTmatrix, &ac_copy,
                   (ckt->CKTniState & NIACSHOULDREORDER) != 0);
}

/* before the solve: b; after it, the refinement */
static double *
ac_save_rhs(CKTcircuit *ckt, int *pn)
{
    int n = SMPmatSize(ckt->CKTmatrix);
    double *buf = ac_scratch(n);
    memcpy(buf, ckt->CKTrhs, (size_t) (n + 1) * sizeof(double));
    memcpy(buf + (n + 1), ckt->CKTirhs, (size_t) (n + 1) * sizeof(double));
    buf[0] = buf[n + 1] = 0.0;
    *pn = n;
    return buf;
}

#ifdef RFSPICE
     // We don't need to reload the AC matrix for every port analysis
     // So we split the NIacIter in two functions
int NIspPreload(CKTcircuit* ckt)
{

    int error;
    int ignore;
    double startTime;

retry:
    ckt->CKTnoncon = 0;

    error = CKTacLoad(ckt);

    if (error) return(error);

    ac_copy_matrix(ckt);        /* Enhancement-860 */

    if (ckt->CKTniState & NIACSHOULDREORDER) {
        startTime = SPfrontEnd->IFseconds();
        error = SMPcReorder(ckt->CKTmatrix, ckt->CKTpivotAbsTol,
            ckt->CKTpivotRelTol, &ignore);
        ckt->CKTstat->STATreorderTime +=
            SPfrontEnd->IFseconds() - startTime;
        ckt->CKTniState &= ~NIACSHOULDREORDER;
        if (error != 0) {
            /* either singular equations or no memory, in either case,
             * let caller handle problem
             */

            int i, j ;
            SMPgetError(ckt->CKTmatrix, &i, &j);
            if(eq(NODENAME(ckt, i), NODENAME(ckt, j)))
                SPfrontEnd->IFerrorf(ERR_WARNING, "singular matrix:  check node %s\n", NODENAME(ckt, i));
            else
                SPfrontEnd->IFerrorf(ERR_WARNING, "singular matrix:  check nodes %s and %s\n", NODENAME(ckt, i), NODENAME(ckt, j));

            return(error);
        }
        NIsmallPivot(ckt);   /* Enhancement-736 */
    }
    else {
        startTime = SPfrontEnd->IFseconds();
        error = SMPcLUfac(ckt->CKTmatrix, ckt->CKTpivotAbsTol);
        ckt->CKTstat->STATdecompTime +=
            SPfrontEnd->IFseconds() - startTime;
        if (error != 0) {
            if (error == E_SINGULAR) {
                /* the problem is that the matrix can't be solved with the
                 * current LU factorization.  Maybe if we reload and
                 * try to reorder again it will help...
                 *
                 * F7 (2026-09-06): under KLU this is also how SMPcLUfac asks for
                 * a fresh pivot order when the reused one has lost its accuracy
                 * (klu_z_rcond collapsed relative to the last full complex
                 * factorization) -- not a singular matrix at all.  Do not warn
                 * here; the retry goes through SMPcReorder above, which names
                 * the node if the matrix really is singular. */
                ckt->CKTniState |= NIACSHOULDREORDER;
                goto retry;
            }
            return(error); /* can't handle E_BADMATRIX, so let caller */
        }
    }

    return (OK);
}

int NIspSolve(CKTcircuit* ckt)
{
    double startTime;
    int n;
    double *b = ac_save_rhs(ckt, &n);      /* Enhancement-860 */
    startTime = SPfrontEnd->IFseconds();
    SMPcSolve(ckt->CKTmatrix, ckt->CKTrhs,
        ckt->CKTirhs, ckt->CKTrhsSpare,
        ckt->CKTirhsSpare);
    ac_refine(ckt, b, n);
    ckt->CKTstat->STATsolveTime += SPfrontEnd->IFseconds() - startTime;

    ckt->CKTrhs[0] = 0;
    ckt->CKTrhsSpare[0] = 0;
    ckt->CKTrhsOld[0] = 0;
    ckt->CKTirhs[0] = 0;
    ckt->CKTirhsSpare[0] = 0;
    ckt->CKTirhsOld[0] = 0;

    SWAP(double*, ckt->CKTirhs, ckt->CKTirhsOld);

    SWAP(double*, ckt->CKTrhs, ckt->CKTrhsOld);
    return (OK);
}

#endif

int
NIacIter(CKTcircuit *ckt)
{
    int error;
    int ignore;
    double startTime;

retry:
    ckt->CKTnoncon=0;

    error = CKTacLoad(ckt);
    if(error) return(error);

    ac_copy_matrix(ckt);        /* Enhancement-860 */
    
    if(ckt->CKTniState & NIACSHOULDREORDER) {
	startTime = SPfrontEnd->IFseconds();
        error = SMPcReorder(ckt->CKTmatrix,ckt->CKTpivotAbsTol,
                ckt->CKTpivotRelTol,&ignore);
	ckt->CKTstat->STATreorderTime +=
		SPfrontEnd->IFseconds()- startTime;
        ckt->CKTniState &= ~NIACSHOULDREORDER;
        if(error != 0) {
            /* either singular equations or no memory, in either case,
             * let caller handle problem
             */
            return(error);
        }
        NIsmallPivot(ckt);   /* Enhancement-736 */
    } else {
	startTime = SPfrontEnd->IFseconds();
        error = SMPcLUfac(ckt->CKTmatrix,ckt->CKTpivotAbsTol);
	ckt->CKTstat->STATdecompTime += 
		SPfrontEnd->IFseconds()-startTime;
        if(error != 0) {
            if(error == E_SINGULAR) {
                /* the problem is that the matrix can't be solved with the
                 * current LU factorization.  Maybe if we reload and
                 * try to reorder again it will help...
                 */
                ckt->CKTniState |= NIACSHOULDREORDER;
                goto retry;
            }
            return(error); /* can't handle E_BADMATRIX, so let caller */
        }
    } 
    {
        int n;
        double *b = ac_save_rhs(ckt, &n);  /* Enhancement-860 */
        startTime = SPfrontEnd->IFseconds();
        SMPcSolve(ckt->CKTmatrix,ckt->CKTrhs, 
                ckt->CKTirhs, ckt->CKTrhsSpare,
                ckt->CKTirhsSpare);
        ac_refine(ckt, b, n);
        ckt->CKTstat->STATsolveTime += SPfrontEnd->IFseconds() - startTime;
    }

    ckt->CKTrhs[0] = 0;
    ckt->CKTrhsSpare[0] = 0;
    ckt->CKTrhsOld[0] = 0;
    ckt->CKTirhs[0] = 0;
    ckt->CKTirhsSpare[0] = 0;
    ckt->CKTirhsOld[0] = 0;

    SWAP(double *, ckt->CKTirhs, ckt->CKTirhsOld);

    SWAP(double *, ckt->CKTrhs, ckt->CKTrhsOld);

    return(OK);
}
