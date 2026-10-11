/*
 *  Spice3 COMPATIBILITY MODULE
 *
 *  Author:                     Advising professor:
 *     Kenneth S. Kundert           Alberto Sangiovanni-Vincentelli
 *     UC Berkeley
 *
 *  This module contains routines that make Sparse1.3 a direct
 *  replacement for the SMP sparse matrix package in Spice3c1 or Spice3d1.
 *  Sparse1.3 is in general a faster and more robust package than SMP.
 *  These advantages become significant on large circuits.
 *
 *  >>> User accessible functions contained in this file:
 *  SMPaddElt
 *  SMPmakeElt
 *  SMPcClear
 *  SMPclear
 *  SMPcLUfac
 *  SMPluFac
 *  SMPcReorder
 *  SMPreorder
 *  SMPcaSolve
 *  SMPcSolve
 *  SMPsolve
 *  SMPmatSize
 *  SMPnewMatrix
 *  SMPdestroy
 *  SMPpreOrder
 *  SMPprint
 *  SMPgetError
 *  SMPcProdDiag
 *  LoadGmin
 *  SMPfindElt
 */

/*
 *  To replace SMP with Sparse, rename the file spSpice3.h to
 *  spMatrix.h and place Sparse in a subdirectory of SPICE called
 *  `sparse'.  Then on UNIX compile Sparse by executing `make spice'.
 *  If not on UNIX, after compiling Sparse and creating the sparse.a
 *  archive, compile this file (spSMP.c) and spSMP.o to the archive,
 *  then copy sparse.a into the SPICE main directory and rename it
 *  SMP.a.  Finally link SPICE.
 *
 *  To be compatible with SPICE, the following Sparse compiler options
 *  (in spConfig.h) should be set as shown below:
 *
 *      EXPANDABLE                      YES
 *      TRANSLATE                       NO
 *      INITIALIZE                      NO or YES, YES for use with test prog.
 *      DIAGONAL_PIVOTING               YES
 *      MODIFIED_MARKOWITZ              NO
 *      DELETE                          NO
 *      STRIP                           NO
 *      MODIFIED_NODAL                  YES
 *      QUAD_ELEMENT                    NO
 *      TRANSPOSE                       YES
 *      SCALING                         NO
 *      DOCUMENTATION                   YES
 *      MULTIPLICATION                  NO
 *      DETERMINANT                     YES
 *      STABILITY                       NO
 *      CONDITION                       NO
 *      PSEUDOCONDITION                 NO
 *      DEBUG                           YES
 *
 *      spREAL  double
 */

/*
 *  Revision and copyright information.
 *
 *  Copyright (c) 1985,86,87,88,89,90
 *  by Kenneth S. Kundert and the University of California.
 *
 *  Permission to use, copy, modify, and distribute this software and its
 *  documentation for any purpose and without fee is hereby granted, provided
 *  that the above copyright notice appear in all copies and supporting
 *  documentation and that the authors and the University of California
 *  are properly credited.  The authors and the University of California
 *  make no representations as to the suitability of this software for
 *  any purpose.  It is provided `as is', without express or implied warranty.
 */

/*
 *  IMPORTS
 *
 *  >>> Import descriptions:
 *  spMatrix.h
 *     Sparse macros and declarations.
 *  SMPdefs.h
 *     Spice3's matrix macro definitions.
 */

#include "ngspice/config.h"
#include <assert.h>
#include <stdio.h>
#include <math.h>
#include "ngspice/spmatrix.h"
#include "spdefs.h"
#include "ngspice/smpdefs.h"

#if defined (_MSC_VER)
extern double scalbn(double, int);
#define logb _logb
extern double logb(double);
#endif

static void LoadGmin(SMPmatrix *eMatrix, double Gmin);
static void smp_copy_sparse_real(MatrixPtr M, SMPcCopy *copy, int fresh);   /* Enhancement-867 */


/*
 * SMPaddElt()
 */
int
SMPaddElt(SMPmatrix *Matrix, int Row, int Col, double Value)
{
    *spGetElement( Matrix->SPmatrix, Row, Col ) = Value;
    return spError( Matrix->SPmatrix );
}

/*
 * SMPmakeElt()
 */
double *
SMPmakeElt(SMPmatrix *Matrix, int Row, int Col)
{
    return spGetElement( Matrix->SPmatrix, Row, Col );
}

/*
 * SMPcClear()
 */
void
SMPcClear(SMPmatrix *Matrix)
{
    spClear( Matrix->SPmatrix );
}

/*
 * SMPclear()
 */
void
SMPclear(SMPmatrix *Matrix)
{
    spClear( Matrix->SPmatrix );
}

#define NG_IGNORE(x)  (void)x

/*
 * SMPcLUfac()
 */
/*ARGSUSED*/
int
SMPcLUfac(SMPmatrix *Matrix, double PivTol)
{
    NG_IGNORE(PivTol);

    spSetComplex( Matrix->SPmatrix );
    return spFactor( Matrix->SPmatrix );
}

/*
 * SMPluFac()
 */
/*ARGSUSED*/
int
SMPluFac(SMPmatrix *Matrix, double PivTol, double Gmin)
{
    NG_IGNORE(PivTol);
    spSetReal( Matrix->SPmatrix );
    LoadGmin( Matrix, Gmin );
    if (Matrix->SMPloadCopy)   /* Enhancement-867 */
        smp_copy_sparse_real( Matrix->SPmatrix, Matrix->SMPloadCopy, 0 );
    return spFactor( Matrix->SPmatrix );
}

#ifdef CIDER
int
SMPluFacForCIDER (SMPmatrix *Matrix)
{
    return spFactor (Matrix->SPmatrix) ;
}
#endif

/*
 * SMPcReorder()
 */
int
SMPcReorder(SMPmatrix *Matrix, double PivTol, double PivRel,
	    int *NumSwaps)
{
    int error;
    *NumSwaps = 1;
    spSetComplex( Matrix->SPmatrix );
    error = spOrderAndFactor( Matrix->SPmatrix, NULL,
                              PivRel, PivTol, YES );
    /* Enhancement-736 */
    spWhereSmallPivot( Matrix->SPmatrix, &Matrix->SMPsmallPivotRow,
                       &Matrix->SMPsmallPivotCol, &Matrix->SMPsmallPivotMag );
    return error;
}

/*
 * SMPsmallPivot()  -- Enhancement-736: the last reorder's pivot below pivtol
 */
int
SMPsmallPivot(SMPmatrix *Matrix, int *Row, int *Col, double *Mag)
{
    *Row = Matrix->SMPsmallPivotRow;
    *Col = Matrix->SMPsmallPivotCol;
    *Mag = Matrix->SMPsmallPivotMag;
    return (Matrix->SMPsmallPivotCol > 0);
}

/*
 * SMPreorder()
 */
int
SMPreorder(SMPmatrix *Matrix, double PivTol, double PivRel, double Gmin)
{
    int error;
    spSetReal( Matrix->SPmatrix );
    LoadGmin( Matrix, Gmin );
    if (Matrix->SMPloadCopy)   /* Enhancement-867 */
        smp_copy_sparse_real( Matrix->SPmatrix, Matrix->SMPloadCopy, 1 );
    error = spOrderAndFactor( Matrix->SPmatrix, NULL,
                              PivRel, PivTol, YES );
    /* Enhancement-736 */
    spWhereSmallPivot( Matrix->SPmatrix, &Matrix->SMPsmallPivotRow,
                       &Matrix->SMPsmallPivotCol, &Matrix->SMPsmallPivotMag );
    return error;
}

/*
 * SMPcaSolve()
 */
void
SMPcaSolve(SMPmatrix *Matrix, double RHS[], double iRHS[],
	   double Spare[], double iSpare[])
{
    NG_IGNORE(iSpare);
    NG_IGNORE(Spare);

    spSolveTransposed( Matrix->SPmatrix, RHS, RHS, iRHS, iRHS );
}

/*
 * SMPcSolve()
 */
void
SMPcSolve(SMPmatrix *Matrix, double RHS[], double iRHS[],
	  double Spare[], double iSpare[])
{
    NG_IGNORE(iSpare);
    NG_IGNORE(Spare);

    spSolve( Matrix->SPmatrix, RHS, RHS, iRHS, iRHS );
}

#ifdef CIDER
void
SMPcSolveForCIDER (SMPmatrix *Matrix, double RHS[], double RHSsolution[], double iRHS[], double iRHSsolution[])
{
    spSolve (Matrix->SPmatrix, RHS, RHSsolution, iRHS, iRHSsolution) ;
}
#endif

/*
 * SMPsolve()
 */
void
SMPsolve(SMPmatrix *Matrix, double RHS[], double Spare[])
{
    NG_IGNORE(Spare);

    spSolve( Matrix->SPmatrix, RHS, RHS, NULL, NULL );
}

#ifdef CIDER
void
SMPsolveForCIDER (SMPmatrix *Matrix, double RHS[], double RHSsolution[])
{
    spSolve (Matrix->SPmatrix, RHS, RHSsolution, NULL, NULL) ;
}
#endif

/*
 * SMPcCopyLoaded() -- Enhancement-860: copy the loaded complex matrix, before
 * it is factored, with 1-based external indices (see smpdefs.h)
 */
static void
smp_copy_put (SMPcCopy *copy, int row, int col, void *elt)
{
    if (copy->n >= copy->cap) {
        copy->cap = copy->cap ? 2 * copy->cap : 256 ;
        copy->row = (int *) realloc (copy->row, (size_t) copy->cap * sizeof (int)) ;
        copy->col = (int *) realloc (copy->col, (size_t) copy->cap * sizeof (int)) ;
        copy->re = (double *) realloc (copy->re, (size_t) copy->cap * sizeof (double)) ;
        copy->im = (double *) realloc (copy->im, (size_t) copy->cap * sizeof (double)) ;
        copy->elt = (void **) realloc (copy->elt, (size_t) copy->cap * sizeof (void *)) ;
    }
    copy->row [copy->n] = row ;
    copy->col [copy->n] = col ;
    copy->elt [copy->n] = elt ;
    copy->n++ ;
}

/* Sparse factors in place: copy the loaded values. The list of elements is
 * built once per matrix -- an element keeps its external row and column
 * through a reordering, and a fill-in, which nothing loads, holds 0 here */
static void
smp_copy_sparse (MatrixPtr M, SMPcCopy *copy, int fresh)
{
    ElementPtr e ;
    int j, k ;

    if (fresh || copy->owner != (const void *) M || copy->owner_elts != M->Elements) {
        copy->n = 0 ;
        for (j = 1 ; j <= M->Size ; j++)
            for (e = M->FirstInCol [j] ; e != NULL ; e = e->NextInCol)
                smp_copy_put (copy, M->IntToExtRowMap [e->Row],
                              M->IntToExtColMap [j], (void *) e) ;
        copy->owner = (const void *) M ;
        copy->owner_elts = M->Elements ;
    }
    for (k = 0 ; k < copy->n ; k++) {
        e = (ElementPtr) copy->elt [k] ;
        copy->re [k] = e->Real ;
        copy->im [k] = e->Imag ;
    }
}

void
SMPcCopyLoaded (SMPmatrix *eMatrix, SMPcCopy *copy, int fresh)
{
    smp_copy_sparse (eMatrix->SPmatrix, copy, fresh) ;
}


static void
smp_residual_copy (const SMPcCopy *copy, int n, const double *xr, const double *xi,
                   double *rr, double *ri, double *den)
{
    int k ;

    for (k = 0 ; k < copy->n ; k++) {
        int r = copy->row [k], c = copy->col [k] ;
        double ar = copy->re [k], ai = copy->im [k] ;
        if (r < 1 || r > n || c < 1 || c > n)
            continue ;
        rr [r] -= ar * xr [c] - ai * xi [c] ;
        ri [r] -= ar * xi [c] + ai * xr [c] ;
        den [r] += (fabs (ar) + fabs (ai)) * (fabs (xr [c]) + fabs (xi [c])) ;
    }
}

static void
smp_residual_start (int n, const double *br, const double *bi,
                    double *rr, double *ri, double *den)
{
    int i ;

    for (i = 0 ; i <= n ; i++) {
        rr [i] = br [i] ;
        ri [i] = bi [i] ;
        den [i] = fabs (br [i]) + fabs (bi [i]) ;
    }
}

void
SMPcResidual (SMPmatrix *eMatrix, const SMPcCopy *copy, int n,
              const double *br, const double *bi,
              const double *xr, const double *xi,
              double *rr, double *ri, double *den)
{
    (void) eMatrix ;
    smp_residual_start (n, br, bi, rr, ri, den) ;
    smp_residual_copy (copy, n, xr, xi, rr, ri, den) ;
}

/*
 * Enhancement-867: the real twin for NIiter (see klusmp.c): the values copied
 * between LoadGmin and the factorization, and the residual over them
 */
static void
smp_copy_sparse_real (MatrixPtr M, SMPcCopy *copy, int fresh)
{
    ElementPtr e ;
    int j, k ;

    if (fresh || M->NeedsOrdering || copy->owner != (const void *) M ||
        copy->owner_elts != M->Elements) {
        copy->n = 0 ;
        for (j = 1 ; j <= M->Size ; j++)
            for (e = M->FirstInCol [j] ; e != NULL ; e = e->NextInCol)
                smp_copy_put (copy, M->IntToExtRowMap [e->Row],
                              M->IntToExtColMap [j], (void *) e) ;
        copy->owner = (const void *) M ;
        copy->owner_elts = M->Elements ;
    }
    for (k = 0 ; k < copy->n ; k++)
        copy->re [k] = ((ElementPtr) copy->elt [k])->Real ;
}

void
SMPresidual (SMPmatrix *eMatrix, int n, const double *b, const double *x,
             const double *s, double *r, double *den, double *fl)
{
    const SMPcCopy *copy = eMatrix->SMPloadCopy ;
    int i, k ;

    for (i = 0 ; i <= n ; i++) {
        r [i] = b [i] ;
        den [i] = fabs (b [i]) ;
        fl [i] = 0.0 ;
    }
    if (copy == NULL || copy->owner != (const void *) eMatrix->SPmatrix)
        return ;
    for (k = 0 ; k < copy->n ; k++) {
        int row = copy->row [k], col = copy->col [k] ;
        if (row < 1 || row > n || col < 1 || col > n)
            continue ;
        r [row] -= copy->re [k] * x [col] ;
        den [row] += fabs (copy->re [k]) * fabs (x [col]) ;
        fl [row] += fabs (copy->re [k]) * s [col] ;
    }
}

/* Enhancement-856: out[i] = max_j |Re A_ij| over row i (0-based external)
 * of the loaded matrix, for i < n */
void
SMProwMaxReal(SMPmatrix *eMatrix, int n, double *out)
{
    MatrixPtr M = eMatrix->SPmatrix;
    ElementPtr e;
    int i, j;

    for (i = 0; i < n; i++)
        out[i] = 0.0;
    for (j = 1; j <= M->Size; j++)
        for (e = M->FirstInCol[j]; e != NULL; e = e->NextInCol) {
            int er = M->IntToExtRowMap[e->Row] - 1;
            if (er >= 0 && er < n && fabs(e->Real) > out[er])
                out[er] = fabs(e->Real);
        }
}

/*
 * SMPmatSize()
 */
int
SMPmatSize(SMPmatrix *Matrix)
{
    return spGetSize( Matrix->SPmatrix, 1 );
}

/*
 * SMPnewMatrix()
 */
int
SMPnewMatrix(SMPmatrix *Matrix, int size)
{
    Matrix->SMPgminDiag = NULL;      /* Enhancement-738 */
    Matrix->SMPgminDiagSize = 0;
    int Error;
    Matrix->SPmatrix = spCreate( size, 1, &Error );
    return Error;
}

#ifdef CIDER
int
SMPnewMatrixForCIDER (SMPmatrix *Matrix, int size, int complex)
{
    int error ;

    Matrix->SPmatrix = spCreate (size, complex, &error) ;

    return error ;
}

#endif

/*
 * SMPdestroy()
 */
void
SMPdestroy(SMPmatrix *Matrix)
{
    free(Matrix->SMPgminDiag);      /* Enhancement-738 */
    Matrix->SMPgminDiag = NULL;
    spDestroy( Matrix->SPmatrix );
}


/* Enhancement-738: record the stamped diagonals for LoadGmin, before the MNA
 * preorder swaps columns and before any factorization, while internal and
 * external numbering still agree. */
static void
SparseGminDiag(SMPmatrix *eMatrix)
{
    MatrixPtr Matrix = eMatrix->SPmatrix;
    int I, Size = Matrix->Size;

    if(Matrix->RowsLinked)
        return;                /* already reordered: keep what was recorded */
    free(eMatrix->SMPgminDiag);
    eMatrix->SMPgminDiag =(double **) calloc((size_t) Size + 1, sizeof(double *));
    eMatrix->SMPgminDiagSize = Size;
    for(I = 1; I <= Size; I++)
        eMatrix->SMPgminDiag [I] = Matrix->Diag [I] ? &Matrix->Diag [I]->Real : NULL;
}

/*
 * SMPpreOrder()
 */
int
SMPpreOrder(SMPmatrix *Matrix)
{
    SparseGminDiag(Matrix);               /* Enhancement-738 */
    spMNA_Preorder( Matrix->SPmatrix );
    return spError( Matrix->SPmatrix );
}

/*
 * SMPprintRHS()
 */

void
SMPprintRHS(SMPmatrix *Matrix, char *Filename, RealVector RHS, RealVector iRHS)
{
    spFileVector( Matrix->SPmatrix, Filename, RHS, iRHS );
}

/*
 * SMPprint()
 */

void
SMPprint(SMPmatrix *Matrix, char *Filename)
{
    if (Filename)
        spFileMatrix(Matrix->SPmatrix, Filename, "Circuit Matrix", 0, 1, 1 );
    else
        spPrint( Matrix->SPmatrix, 0, 1, 1 );
}

/*
 * SMPgetError()
 */
void
SMPgetError(SMPmatrix *Matrix, int *Col, int *Row)
{
    spWhereSingular( Matrix->SPmatrix, Row, Col );
}

/*
 * SMPcProdDiag()
 *    note: obsolete for Spice3d2 and later
 */
int
SMPcProdDiag(SMPmatrix *Matrix, SPcomplex *pMantissa, int *pExponent)
{
    spDeterminant ( Matrix->SPmatrix, pExponent, &(pMantissa->real),
                                              &(pMantissa->imag) );
    return spError( Matrix->SPmatrix );
}

/*
 * SMPcDProd()
 */
int
SMPcDProd(SMPmatrix *Matrix, SPcomplex *pMantissa, int *pExponent)
{
    double	re, im, x, y, z;
    int		p;

    spDeterminant( Matrix->SPmatrix, &p, &re, &im);

#ifndef M_LN2
#define M_LN2   0.69314718055994530942
#endif
#ifndef M_LN10
#define M_LN10  2.30258509299404568402
#endif

#ifdef debug_print
    printf("Determinant 10: (%20g,%20g)^%d\n", re, im, p);
#endif

    /* Convert base 10 numbers to base 2 numbers, for comparison */
    y = p * M_LN10 / M_LN2;
    x = (int) y;
    y -= x;

    /* ASSERT
     *	x = integral part of exponent, y = fraction part of exponent
     */

    /* Fold in the fractional part */
#ifdef debug_print
    printf(" ** base10 -> base2 int =  %g, frac = %20g\n", x, y);
#endif
    z = pow(2.0, y);
    re *= z;
    im *= z;
#ifdef debug_print
    printf(" ** multiplier = %20g\n", z);
#endif

    /* Re-normalize (re or im may be > 2.0 or both < 1.0 */
    if (re != 0.0) {
	y = logb(re);
	if (im != 0.0)
	    z = logb(im);
	else
	    z = 0;
    } else if (im != 0.0) {
	z = logb(im);
	y = 0;
    } else {
	/* Singular */
	/*printf("10 -> singular\n");*/
	y = 0;
	z = 0;
    }

#ifdef debug_print
    printf(" ** renormalize changes = %g,%g\n", y, z);
#endif
    if (y < z)
	y = z;

    *pExponent = (int)(x + y);
    x = scalbn(re, (int) -y);
    z = scalbn(im, (int) -y);
#ifdef debug_print
    printf(" ** values are: re %g, im %g, y %g, re' %g, im' %g\n",
	    re, im, y, x, z);
#endif
    pMantissa->real = scalbn(re, (int) -y);
    pMantissa->imag = scalbn(im, (int) -y);

#ifdef debug_print
    printf("Determinant 10->2: (%20g,%20g)^%d\n", pMantissa->real,
	pMantissa->imag, *pExponent);
#endif
    return spError( Matrix->SPmatrix );
}



/*
 *  The following routines need internal knowledge of the Sparse data
 *  structures.
 */

/*
 *  LOAD GMIN
 *
 *  This routine adds Gmin to each diagonal element.  Because Gmin is
 *  added to the current diagonal, which may bear little relation to
 *  what the outside world thinks is a diagonal, and because the
 *  elements that are diagonals may change after calling spOrderAndFactor,
 *  use of this routine is not recommended.  It is included here simply
 *  for compatibility with Spice3.
 */

static void
LoadGmin(SMPmatrix *eMatrix, double Gmin)
{
    MatrixPtr Matrix = eMatrix->SPmatrix;
    int I;
    ArrayOfElementPtrs Diag;
    ElementPtr diag;

    /* Begin `LoadGmin'. */
    assert( IS_SPARSE( Matrix ) );

    if (Gmin != 0.0) {
        /* Enhancement-738: the stamped diagonals, whatever the pivot order. */
        if (eMatrix->SMPgminDiag != NULL && eMatrix->SMPgminDiagSize == Matrix->Size) {
            for (I = Matrix->Size; I > 0; I--)
                if (eMatrix->SMPgminDiag[I] != NULL)
                    *eMatrix->SMPgminDiag[I] += Gmin;
            return;
        }
	Diag = Matrix->Diag;
	for (I = Matrix->Size; I > 0; I--) {
	    if ((diag = Diag[I]) != NULL)
		diag->Real += Gmin;
	}
    }
    return;
}




/*
 *  FIND ELEMENT
 *
 *  This routine finds an element in the matrix by row and column number.
 *  If the element exists, a pointer to it is returned.  If not, then NULL
 *  is returned unless the CreateIfMissing flag is TRUE, in which case a
 *  pointer to the new element is returned.
 */

SMPelement *
SMPfindElt(SMPmatrix *eMatrix, int Row, int Col, int CreateIfMissing)
{
    MatrixPtr Matrix = eMatrix->SPmatrix;
    ElementPtr Element;

    /* Begin `SMPfindElt'. */
    assert( IS_SPARSE( Matrix ) );
    Row = Matrix->ExtToIntRowMap[Row];
    Col = Matrix->ExtToIntColMap[Col];

    if (Col == -1)
    /* No element available */
        return NULL;

    Element = Matrix->FirstInCol[Col];
    Element = spcFindElementInCol(Matrix, &Element, Row, Col, CreateIfMissing);
    return (SMPelement *)Element;
}

/* XXX The following should probably be implemented in spUtils */

/*
 * SMPcZeroCol()
 */
int
SMPcZeroCol(SMPmatrix *eMatrix, int Col)
{
    MatrixPtr Matrix = eMatrix->SPmatrix;
    ElementPtr	Element;

    Col = Matrix->ExtToIntColMap[Col];

    for (Element = Matrix->FirstInCol[Col];
	Element != NULL;
	Element = Element->NextInCol)
    {
	Element->Real = 0.0;
	Element->Imag = 0.0;
    }

    return spError( Matrix );
}

/*
 * SMPcAddCol()
 */
int
SMPcAddCol(SMPmatrix *eMatrix, int Accum_Col, int Addend_Col)
{
    MatrixPtr Matrix = eMatrix->SPmatrix;
    ElementPtr	Accum, Addend, *Prev;

    Accum_Col = Matrix->ExtToIntColMap[Accum_Col];
    Addend_Col = Matrix->ExtToIntColMap[Addend_Col];

    Addend = Matrix->FirstInCol[Addend_Col];
    Prev = &Matrix->FirstInCol[Accum_Col];
    Accum = *Prev;

    while (Addend != NULL) {
	while (Accum && Accum->Row < Addend->Row) {
	    Prev = &Accum->NextInCol;
	    Accum = *Prev;
	}
	if (!Accum || Accum->Row > Addend->Row) {
	    Accum = spcCreateElement(Matrix, Addend->Row, Accum_Col, Prev, 0);
	}
	Accum->Real += Addend->Real;
	Accum->Imag += Addend->Imag;
	Addend = Addend->NextInCol;
    }

    return spError( Matrix );
}

/*
 * SMPzeroRow()
 */
int
SMPzeroRow(SMPmatrix *eMatrix, int Row)
{
    MatrixPtr Matrix = eMatrix->SPmatrix;
    ElementPtr	Element;

    Row = Matrix->ExtToIntColMap[Row];

    if (Matrix->RowsLinked == NO)
	spcLinkRows(Matrix);

    if (Matrix->PreviousMatrixWasComplex || Matrix->Complex) {
	for (Element = Matrix->FirstInRow[Row];
	    Element != NULL;
	    Element = Element->NextInRow)
	{
	    Element->Real = 0.0;
	    Element->Imag = 0.0;
	}
    } else {
	for (Element = Matrix->FirstInRow[Row];
	    Element != NULL;
	    Element = Element->NextInRow)
	{
	    Element->Real = 0.0;
	}
    }

    return spError( Matrix );
}

/*
 * SMPconstMult()
 */
void
SMPconstMult(SMPmatrix *Matrix, double constant)
{
    spConstMult(Matrix->SPmatrix, constant);
}

/*
 * SMPmultiply()
 */
void
SMPmultiply(SMPmatrix *Matrix, double *RHS, double *Solution, double *iRHS, double *iSolution)
{
    spMultiply(Matrix->SPmatrix, RHS, Solution, iRHS, iSolution);
}
