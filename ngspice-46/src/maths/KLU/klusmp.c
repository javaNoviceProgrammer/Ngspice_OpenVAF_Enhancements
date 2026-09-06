/* KLU to SMP Interface
 * Francesco Lannutti
 * July 2020
*/

#include "ngspice/config.h"
#include <assert.h>
#include <stdio.h>
#include <math.h>
#include "ngspice/spmatrix.h"
#include "../sparse/spdefs.h"
#include "ngspice/smpdefs.h"
#include "ngspice/fteext.h"

#if defined (_MSC_VER)
extern double scalbn(double, int);
#define logb _logb
extern double logb(double);
#endif

#ifdef HAS_WINGUI
#include "ngspice/wstdio.h"
#endif

#include "ngspice/mif.h"
#include "ngspice/evt.h"

/* Enhancement-492: an EMPTY matrix is a legitimate state, not an error.
 *
 * PreOrder already says so -- "XSPICE pure digital circuits produce empty KLU
 * matrix" -- and returns success for it; Factor returns success too. But all
 * three sites printed "Error (...): KLU Matrix is empty" every time they were
 * reached, and Solve then followed it with "KLUnumeric object is NULL" and
 * "KLUsymbolic object is NULL", which are CONSEQUENCES of the same empty matrix
 * rather than separate faults. Because the solve is re-entered per Newton
 * iteration, one such circuit produced nine or more lines, none of which named
 * what had actually happened.
 *
 * Say it once, in words that describe the state, and suppress the NULL-object
 * messages when an empty matrix is the reason those objects are NULL. The
 * counter is reset in PreOrder, which runs once per setup, so a second circuit
 * in the same session reports again. */
static int klu_empty_reported = 0;

static void klu_report_empty (void)
{
    if (!klu_empty_reported) {
        klu_empty_reported = 1 ;
        fprintf (stderr,
                 "\nNote: this circuit has no matrix to solve -- every node is "
                 "either grounded or\n      driven only by sources that "
                 "contribute nothing to the matrix. KLU has\n      nothing to "
                 "factor, so no node voltage can be computed for it.\n\n") ;
    }
}


static int
CircuitIsDigital (void)
{
#ifdef XSPICE
    return g_mif_info.ckt && g_mif_info.ckt->evt && g_mif_info.ckt->evt->counts.num_nodes != 0 ;
#else
    return 0 ;
#endif
}

static void LoadGmin_CSC (double **diag, unsigned int n, double Gmin) ;
static void LoadGmin (SMPmatrix *eMatrix, double Gmin) ;

typedef struct sElement {
    unsigned int row ;
    unsigned int col ;
    double *pointer ;
    unsigned int group ;
} Element ;

static int
CompareRow (const void *a, const void *b)
{
    Element *A = (Element *) a ;
    Element *B = (Element *) b ;

    return
        (A->row > B->row) ?  1 :
        (A->row < B->row) ? -1 :
        0 ;
}

static int
CompareColumn (const void *a, const void *b)
{
    Element *A = (Element *) a ;
    Element *B = (Element *) b ;

    return
        (A->col > B->col) ?  1 :
        (A->col < B->col) ? -1 :
        0 ;
}

static void
Compress (unsigned int *Ai, unsigned int *Bp, unsigned int n, unsigned int nz)
{
    unsigned int i, j ;

    for (i = 0 ; i <= Ai [0] ; i++)
        Bp [i] = 0 ;

    j = Ai [0] + 1 ;
    for (i = 1 ; i < nz ; i++)
    {
        if (Ai [i] == Ai [i - 1] + 1)
        {
            Bp [j] = i ;
            j++ ;
        }
        else if (Ai [i] > Ai [i - 1] + 1)
        {
            for ( ; j <= Ai [i] ; j++)
                Bp [j] = i ;
        }
    }

    for ( ; j <= n ; j++)
        Bp [j] = i ;
}

int
BindCompare (const void *a, const void *b)
{
    BindElement *A = (BindElement *) a ;
    BindElement *B = (BindElement *) b ;

    return
        (A->COO > B->COO) ?  1 :
        (A->COO < B->COO) ? -1 :
        0 ;
}

#ifdef CIDER
int
BindCompareKLUforCIDER (const void *a, const void *b)
{
    BindElementKLUforCIDER *A = (BindElementKLUforCIDER *) a ;
    BindElementKLUforCIDER *B = (BindElementKLUforCIDER *) b ;

    return
        (A->COO > B->COO) ?  1 :
        (A->COO < B->COO) ? -1 :
        0 ;
}

int
BindKluCompareCSCKLUforCIDER (const void *a, const void *b)
{
    BindElementKLUforCIDER *A = (BindElementKLUforCIDER *) a ;
    BindElementKLUforCIDER *B = (BindElementKLUforCIDER *) b ;

    return
        (A->CSC_Complex > B->CSC_Complex) ?  1 :
        (A->CSC_Complex < B->CSC_Complex) ? -1 :
        0 ;
}
#endif

void SMPconvertCOOtoCSC (SMPmatrix *Matrix)
{
    Element *MatrixCOO ;
    KluLinkedListCOO *current, *temp ;
    unsigned int *Ap_COO, current_group, i, j ;

    if (Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ == 0) {
        /* Assign N and NZ.  F8: the RHS span follows the size hint so NIreinit
         * still covers the node numbering; the matrix itself stays empty. */
        Matrix->SMPkluMatrix->KLUmatrixNrhs = Matrix->SMPkluMatrix->KLUmatrixN + 1 ;
        Matrix->SMPkluMatrix->KLUmatrixN = 0 ;
        Matrix->SMPkluMatrix->KLUmatrixNZ = 0 ;

        /* Allocate Diag Gmin CSC Vector */
        Matrix->SMPkluMatrix->KLUmatrixDiag = NULL ;

        /* Allocate the temporary COO Column Index */
        Ap_COO = NULL ;

        /* Allocate the needed KLU data structures */
        Matrix->SMPkluMatrix->KLUmatrixAp = (int *) malloc (sizeof (int)) ;
        Matrix->SMPkluMatrix->KLUmatrixAp [0] = 0 ;   /* F1 deck G: SMPfindElt read this uninitialised */
        Matrix->SMPkluMatrix->KLUmatrixAi = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructCOO = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAx = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAxComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixIntermediate = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex = NULL ;

        /* Set the Matrix as Real */
        Matrix->SMPkluMatrix->KLUmatrixIsComplex = KLUmatrixReal ;

        return ;
    }

    /* Allocate the compressed COO elements */
    MatrixCOO = (Element *) malloc (Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ * sizeof (Element)) ;

    /* Populate the compressed COO elements and COO value of Binding Table */
    /* Delete the Linked List in the meantime */
    i = 0 ;
    temp = Matrix->SMPkluMatrix->KLUmatrixLinkedListCOO ;
    while (temp != NULL) {
        MatrixCOO [i].row = temp->row ;
        MatrixCOO [i].col = temp->col ;
        MatrixCOO [i].pointer = temp->pointer ;
        MatrixCOO [i].group = 0 ;
        current = temp ;
        temp = temp->next ;
        free (current->pointer) ; // We need only the memory address, we don't need to access it
        free (current) ;
        current = NULL ;
        i++ ;
    }

    /* Order the MatrixCOO along the columns */
    qsort (MatrixCOO, Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ, sizeof (Element), CompareColumn) ;

    /* Order the MatrixCOO along the rows */
    i = 0 ;
    while (i < Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ)
    {
        /* Look for the next column */
        for (j = i + 1 ; j < Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ ; j++)
        {
            if (MatrixCOO [j].col != MatrixCOO [i].col)
            {
                break ;
            }
        }

        qsort (MatrixCOO + i, j - i, sizeof (Element), CompareRow) ;

        i = j ;
    }

    /* F1/F8 (2026-09-06): the matrix spans EVERY unknown the circuit has.
     *
     * The code that stood here sized the matrix from the largest column that
     * carried an entry and "collapsed" any empty column in between, renumbering
     * the columns (and the rows, whether or not the row was empty) and keeping a
     * new->old map that the solves consumed in the wrong index base.  A node
     * nothing conducts to therefore made every other node's voltage wrong with
     * no message (E-232/E-233 had called the path unreachable).  Now the size
     * is the larger of the hint CKTsetup/CKTpzSetup give through SMPsizeHint()
     * and the largest row or column index seen, and an empty column stays an
     * empty column: klu_analyze records the structural singularity, klu_factor
     * names it, and CKTsetup gives such a node a zero diagonal so gmin stepping
     * can hold it up.  Node i of the matrix is RHS entry i+1, full stop. */
    unsigned int n = MatrixCOO [Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ - 1].col + 1 ;
    for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ ; i++)
        if (MatrixCOO [i].row + 1 > n)
            n = MatrixCOO [i].row + 1 ;
    if (Matrix->SMPkluMatrix->KLUmatrixN > n)
        n = Matrix->SMPkluMatrix->KLUmatrixN ;
    Matrix->SMPkluMatrix->KLUmatrixNodeCollapsingNewToOld = NULL ;

    /* Assign labels to avoid duplicates */
    for (i = 0, j = 1 ; i < Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ - 1 ; i++, j++) {
        if ((MatrixCOO [i].col == MatrixCOO [j].col) && (MatrixCOO [i].row == MatrixCOO [j].row)) {
            // If col and row are the same
            MatrixCOO [j].group = MatrixCOO [i].group ;
        } else if ((MatrixCOO [i].col != MatrixCOO [j].col) || (MatrixCOO [i].row != MatrixCOO [j].row)) {
            // If or col either row are different, it isn't a duplicate, so assign the next label and store it in 'nz'
            MatrixCOO [j].group = MatrixCOO [i].group + 1 ;
        } else {
            printf ("Error: Strange behavior during label assignment\n") ;
        }
    }

    /* Assign N and NZ */
    Matrix->SMPkluMatrix->KLUmatrixN = n ;
    Matrix->SMPkluMatrix->KLUmatrixNrhs = Matrix->SMPkluMatrix->KLUmatrixN + 1 ;
    Matrix->SMPkluMatrix->KLUmatrixNZ = MatrixCOO [Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ - 1].group + 1 ;

    /* Allocate Diag Gmin CSC Vector */
    Matrix->SMPkluMatrix->KLUmatrixDiag = (double **) malloc (Matrix->SMPkluMatrix->KLUmatrixN * sizeof (double *)) ;
    for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
        Matrix->SMPkluMatrix->KLUmatrixDiag [i] = NULL ;
    }

    /* Allocate the temporary COO Column Index */
    Ap_COO = (unsigned int *) malloc (Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof (unsigned int)) ;

    /* Allocate the needed KLU data structures */
    Matrix->SMPkluMatrix->KLUmatrixAp = (int *) malloc ((Matrix->SMPkluMatrix->KLUmatrixN + 1) * sizeof (int)) ;
    Matrix->SMPkluMatrix->KLUmatrixAi = (int *) malloc (Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof (int)) ;
    Matrix->SMPkluMatrix->KLUmatrixBindStructCOO = (BindElement *) malloc (Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ * sizeof (BindElement)) ;
    Matrix->SMPkluMatrix->KLUmatrixAx = (double *) malloc (Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof (double)) ;
    Matrix->SMPkluMatrix->KLUmatrixAxComplex = (double *) malloc (2 * Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof (double)) ;
    Matrix->SMPkluMatrix->KLUmatrixIntermediate = (double *) malloc (Matrix->SMPkluMatrix->KLUmatrixN * sizeof (double)) ;
    Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex = (double *) malloc (2 * Matrix->SMPkluMatrix->KLUmatrixN * sizeof (double)) ;

    /* Copy back the Matrix in partial CSC */
    for (i = 0, current_group = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ ; i++)
    {
        if (MatrixCOO [i].group > current_group) {
            current_group = MatrixCOO [i].group ;
        }

        Ap_COO [current_group] = MatrixCOO [i].col ;
        Matrix->SMPkluMatrix->KLUmatrixAi [current_group] = (int)MatrixCOO [i].row ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructCOO [i].COO = MatrixCOO [i].pointer ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructCOO [i].CSC = &(Matrix->SMPkluMatrix->KLUmatrixAx [current_group]) ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructCOO [i].CSC_Complex = &(Matrix->SMPkluMatrix->KLUmatrixAxComplex [2 * current_group]) ;
        if (MatrixCOO [i].col == MatrixCOO [i].row) {
            Matrix->SMPkluMatrix->KLUmatrixDiag [MatrixCOO [i].col] = Matrix->SMPkluMatrix->KLUmatrixBindStructCOO [i].CSC ;
        }
    }

    /* Compress the COO Column Index to CSC Column Index */
    Compress (Ap_COO, (unsigned int *)Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixN, Matrix->SMPkluMatrix->KLUmatrixNZ) ;

    /* Free the temporary stuff */
    free (Ap_COO) ;
    free (MatrixCOO) ;

    /* Sort the Binding Table */
    qsort (Matrix->SMPkluMatrix->KLUmatrixBindStructCOO, Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ, sizeof (BindElement), BindCompare) ;

    /* Set the Matrix as Real */
    Matrix->SMPkluMatrix->KLUmatrixIsComplex = KLUmatrixReal ;

    return ;
}

#ifdef CIDER
typedef struct sElementKLUforCIDER {
    unsigned int row ;
    unsigned int col ;
    double *pointer ;
} ElementKLUforCIDER ;

void SMPconvertCOOtoCSCKLUforCIDER (SMPmatrix *Matrix)
{
    ElementKLUforCIDER *MatrixCOO ;
    unsigned int *Ap_COO, i, j, nz ;

    /* Count the non-zero elements and store it */
    nz = 0 ;
    for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN * Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
        if ((Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER [i] != -1) && (Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER [i] != -1)) {
            nz++ ;
        }
    }
    Matrix->SMPkluMatrix->KLUmatrixNZ = nz ;

    /* Allocate the compressed COO elements */
    MatrixCOO = (ElementKLUforCIDER *) malloc (nz * sizeof (ElementKLUforCIDER)) ;

    /* Allocate the temporary COO Column Index */
    Ap_COO = (unsigned int *) malloc (nz * sizeof (unsigned int)) ;

    /* Allocate the needed KLU data structures */
    Matrix->SMPkluMatrix->KLUmatrixAp = (int *) malloc ((Matrix->SMPkluMatrix->KLUmatrixN + 1) * sizeof (int)) ;
    Matrix->SMPkluMatrix->KLUmatrixAi = (int *) malloc (nz * sizeof (int)) ;
    Matrix->SMPkluMatrix->KLUmatrixBindStructForCIDER = (BindElementKLUforCIDER *) malloc (nz * sizeof (BindElementKLUforCIDER)) ;
    Matrix->SMPkluMatrix->KLUmatrixAxComplex = (double *) malloc (2 * nz * sizeof (double)) ;
    Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex = (double *) malloc (2 * Matrix->SMPkluMatrix->KLUmatrixN * sizeof (double)) ;

    /* Populate the compressed COO elements and COO value of Binding Table */
    j = 0 ;
    for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN * Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
        if ((Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER [i] != -1) && (Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER [i] != -1)) {
            MatrixCOO [j].row = (unsigned int)Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER [i] ;
            MatrixCOO [j].col = (unsigned int)Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER [i] ;
            MatrixCOO [j].pointer = &(Matrix->SMPkluMatrix->KLUmatrixValueComplexCOOforCIDER [2 * i]) ;
            j++ ;
        }
    }

    /* Order the MatrixCOO along the columns */
    qsort (MatrixCOO, nz, sizeof (ElementKLUforCIDER), CompareColumn) ;

    /* Order the MatrixCOO along the rows */
    i = 0 ;
    while (i < nz)
    {
        /* Look for the next column */
        for (j = i + 1 ; j < nz ; j++)
        {
            if (MatrixCOO [j].col != MatrixCOO [i].col)
            {
                break ;
            }
        }

        qsort (MatrixCOO + i, j - i, sizeof (ElementKLUforCIDER), CompareRow) ;

        i = j ;
    }

    /* Copy back the Matrix in partial CSC */
    for (i = 0 ; i < nz ; i++)
    {
        Ap_COO [i] = MatrixCOO [i].col ;
        Matrix->SMPkluMatrix->KLUmatrixAi [i] = (int)MatrixCOO [i].row ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructForCIDER [i].COO = MatrixCOO [i].pointer ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructForCIDER [i].CSC_Complex = &(Matrix->SMPkluMatrix->KLUmatrixAxComplex [2 * i]) ;
    }

    /* Compress the COO Column Index to CSC Column Index */
    Compress (Ap_COO, (unsigned int *)Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixN, nz) ;

    /* Free the temporary stuff */
    free (Ap_COO) ;
    free (MatrixCOO) ;

    /* Sort the Binding Table */
    qsort (Matrix->SMPkluMatrix->KLUmatrixBindStructForCIDER, nz, sizeof (BindElementKLUforCIDER), BindCompareKLUforCIDER) ;

    return ;
}
#endif

/*
 * SMPmakeElt()
 */
double *
SMPmakeElt (SMPmatrix *Matrix, int Row, int Col)
{
    KluLinkedListCOO *temp ;

    if (Matrix->CKTkluMODE) {
        if ((Row > 0) && (Col > 0)) {
            Row = Row - 1 ;
            Col = Col - 1 ;
            temp = (KluLinkedListCOO *) malloc (sizeof (KluLinkedListCOO)) ;
            temp->row = (unsigned int)Row ;
            temp->col = (unsigned int)Col ;
            temp->pointer = (double *) malloc (sizeof (double)) ;
            temp->next = Matrix->SMPkluMatrix->KLUmatrixLinkedListCOO ;
            Matrix->SMPkluMatrix->KLUmatrixLinkedListCOO = temp ;
            Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ++ ;
            return temp->pointer ;
        } else {
            return Matrix->SMPkluMatrix->KLUmatrixTrashCOO ;
        }
    } else {
        return spGetElement (Matrix->SPmatrix, Row, Col) ;
    }
}

#ifdef CIDER
double *
SMPmakeEltKLUforCIDER (SMPmatrix *Matrix, int Row, int Col)
{
    if (Matrix->CKTkluMODE) {
        if ((Row > 0) && (Col > 0)) {
            Row = Row - 1 ;
            Col = Col - 1 ;
            Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER [Row * (int)Matrix->SMPkluMatrix->KLUmatrixN + Col] = Row ;
            Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER [Row * (int)Matrix->SMPkluMatrix->KLUmatrixN + Col] = Col ;
            return &(Matrix->SMPkluMatrix->KLUmatrixValueComplexCOOforCIDER [2 * (Row * (int)Matrix->SMPkluMatrix->KLUmatrixN + Col)]) ;
        } else {
            return Matrix->SMPkluMatrix->KLUmatrixTrashCOO ;
        }
    } else {
        return spGetElement (Matrix->SPmatrix, Row, Col) ;
    }
}
#endif

/*
 * SMPcClear()
 */

void
SMPcClear (SMPmatrix *Matrix)
{
    unsigned int i ;

    if (Matrix->CKTkluMODE)
    {
        for (i = 0 ; i < 2 * Matrix->SMPkluMatrix->KLUmatrixNZ ; i++) {
            Matrix->SMPkluMatrix->KLUmatrixAxComplex [i] = 0 ;
        }
    } else {
        spClear (Matrix->SPmatrix) ;
    }
}

/*
 * SMPclear()
 */

void
SMPclear (SMPmatrix *Matrix)
{
    unsigned int i ;

    if (Matrix->CKTkluMODE)
    {
        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixNZ ; i++) {
            Matrix->SMPkluMatrix->KLUmatrixAx [i] = 0 ;
        }
    } else {
        spClear (Matrix->SPmatrix) ;
    }
}

#ifdef CIDER
void
SMPclearKLUforCIDER (SMPmatrix *Matrix)
{
    unsigned int i ;

    for (i = 0 ; i < 2 * Matrix->SMPkluMatrix->KLUmatrixNZ ; i++) {
        Matrix->SMPkluMatrix->KLUmatrixAxComplex [i] = 0 ;
    }
}
#endif

#define NG_IGNORE(x)  (void)x

/*
 * SMPcLUfac()
 */
/*ARGSUSED*/

#ifndef KLU_REFACTOR_RCOND_DROP
#define KLU_REFACTOR_RCOND_DROP 1e-6
#endif

/* F7 (2026-09-06): remember the rcond of a full COMPLEX factorization, the
 * reference for every klu_z_refactor that reuses its pivot order.  The twin of
 * klu_note_factor_rcond below, for the AC/noise/sp/disto path, which until now
 * had no guard at all: every frequency after the first reused the order chosen
 * at the first one and nothing ever asked NIacIter to re-pivot. */
static void
klu_note_zfactor_rcond (SMPmatrix *Matrix)
{
    Matrix->SMPkluMatrix->KLUmatrixRcondFactorComplex = 0.0 ;
    if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL &&
        Matrix->SMPkluMatrix->KLUmatrixSymbolic != NULL &&
        Matrix->SMPkluMatrix->KLUmatrixCommon != NULL &&
        Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_OK)
    {
        if (klu_z_rcond (Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                         Matrix->SMPkluMatrix->KLUmatrixNumeric,
                         Matrix->SMPkluMatrix->KLUmatrixCommon) &&
            Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_OK)
            Matrix->SMPkluMatrix->KLUmatrixRcondFactorComplex = Matrix->SMPkluMatrix->KLUmatrixCommon->rcond ;
        Matrix->SMPkluMatrix->KLUmatrixCommon->status = KLU_OK ;
    }
}

int
SMPcLUfac (SMPmatrix *Matrix, double PivTol)
{
    int ret ;
    int refactored = 0 ;   /* F7 */

    NG_IGNORE (PivTol) ;

    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return 0 ;
        }

        /* Enhancement-499: refactor only a Numeric that is already COMPLEX.
         *
         * klu_z_refactor refills an existing factorisation in place, walking the
         * L and U index arrays that klu_z_factor built. Handed a REAL Numeric it
         * walks half-sized arrays with complex strides: it reads and writes past
         * the ends, and a later klu_free_numeric frees whatever it scribbled --
         * the malloc abort names object 0x3ff0000000000000, the bit pattern of
         * the double 1.0, a matrix VALUE being freed as a pointer.
         *
         * The mismatch is reachable because a Numeric outlives the analysis that
         * built it. Every AC/SP/NOISE run is preceded by a real operating point,
         * and Enhancement-471's setup reuse keeps the matrix standing between
         * sweep points instead of rebuilding it -- so the second and later points
         * of `sweep -analysis ac` arrived here with the operating point's REAL
         * Numeric. Without reuse CKTsetup rebuilt the matrix and SMPcReorder did
         * a full complex factorisation first, which is why this was invisible.
         *
         * Symptoms: `sweep`/`optimize -analysis ac|noise|sp` under `.option klu`
         * returned 0.0 for every reused point, fitted a parameter 10x wrong while
         * reporting "converged", and crashed outright (SIGSEGV in klu_z_refactor)
         * on 9 of 10 `sp` runs. SPARSE was never affected. */
        if (Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL ||
            !Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL)
                klu_free_numeric (&(Matrix->SMPkluMatrix->KLUmatrixNumeric),
                                  Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            Matrix->SMPkluMatrix->KLUmatrixNumeric =
                klu_z_factor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi,
                              Matrix->SMPkluMatrix->KLUmatrixAxComplex,
                              Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                              Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex =
                (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL) ? 1 : 0 ;
            ret = (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL) ;
            klu_note_zfactor_rcond (Matrix) ;   /* F7: the reference for the refactors that follow */
        } else {
            ret = klu_z_refactor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAxComplex,
                                  Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            refactored = 1 ;
        }

        if (ret == 0)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon == NULL) {
                fprintf(stderr, "Error (ReFactor Complex): KLUcommon object is NULL. A problem occurred\n");
                return 0 ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR) {
                if (ft_ngdebug) {
                    fprintf(stderr, "Warning (ReFactor Complex): KLU Matrix is SINGULAR\n");
                    fprintf(stderr, "  Numerical Rank: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->numerical_rank);
                    fprintf(stderr, "  Singular Node: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1);
                }
                return E_SINGULAR ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX)
            {
                klu_report_empty () ;
                return 0 ;
            }
            if (!klu_empty_reported && Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL) {
                fprintf (stderr, "Error (ReFactor Complex): KLUnumeric object is NULL. A problem occurred\n") ;
            }
            return 1 ;
        } else {
            /* F7 (2026-09-06): a successful klu_z_refactor is not necessarily a
             * usable one -- the complex twin of Enhancement-439 and of the
             * large-circuit relative-rcond test in SMPluFac.  Across a wide AC
             * sweep the pivot order chosen at the first frequency can become
             * arbitrarily bad once jwC dominates: a ten-section ladder with
             * resistances over nine decades was 26 dB off at 1 THz (613 dB with
             * pivrel=1) while Sparse was exact, and nothing in the loop could
             * notice because the refactor tests only for an exact zero pivot.
             * klu_z_rcond is O(n); a zero, or a collapse by more than
             * KLU_REFACTOR_RCOND_DROP relative to the last full complex
             * factorization, is reported as E_SINGULAR, which NIacIter (and
             * NIdIter) answer with SMPcReorder: a fresh factorization that
             * pivots on the values of THIS frequency.  A stiff matrix's small
             * rcond passes: the test is relative to its own full-factor value. */
            if (refactored &&
                Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL &&
                Matrix->SMPkluMatrix->KLUmatrixSymbolic != NULL &&
                Matrix->SMPkluMatrix->KLUmatrixCommon != NULL)
            {
                klu_z_rcond (Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                             Matrix->SMPkluMatrix->KLUmatrixNumeric,
                             Matrix->SMPkluMatrix->KLUmatrixCommon) ;
                if (Matrix->SMPkluMatrix->KLUmatrixCommon->rcond == 0.0) {
                    if (ft_ngdebug)
                        fprintf (stderr, "Warning (ReFactor Complex): reuse of the existing "
                                 "pivot order produced a singular U; forcing a full factorization\n") ;
                    return E_SINGULAR ;
                }
                if (Matrix->SMPkluMatrix->KLUmatrixRcondFactorComplex > 0.0 &&
                    Matrix->SMPkluMatrix->KLUmatrixCommon->rcond <
                        KLU_REFACTOR_RCOND_DROP * Matrix->SMPkluMatrix->KLUmatrixRcondFactorComplex) {
                    if (ft_ngdebug)
                        fprintf (stderr, "Warning (ReFactor Complex): reuse of the existing pivot "
                                 "order lost %.1e in rcond (%.3e vs %.3e at the last full "
                                 "factorization); forcing a full factorization\n",
                                 Matrix->SMPkluMatrix->KLUmatrixCommon->rcond /
                                 Matrix->SMPkluMatrix->KLUmatrixRcondFactorComplex,
                                 Matrix->SMPkluMatrix->KLUmatrixCommon->rcond,
                                 Matrix->SMPkluMatrix->KLUmatrixRcondFactorComplex) ;
                    return E_SINGULAR ;
                }
            }
            return 0 ;
        }
    } else {
        spSetComplex (Matrix->SPmatrix) ;
        return spFactor (Matrix->SPmatrix) ;
    }
}

/*
 * SMPluFac()
 */
/*ARGSUSED*/

/* F1 (large-circuit sweep): remember the rcond of a full (pivoting)
 * factorization, so a later refactor -- which reuses its pivot order -- can
 * tell whether that order still suits the matrix it is being applied to. */
#define KLU_REFACTOR_RCOND_DROP 1e-6
static void
klu_note_factor_rcond (SMPmatrix *Matrix)
{
    Matrix->SMPkluMatrix->KLUmatrixRcondFactor = 0.0 ;
    if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL &&
        Matrix->SMPkluMatrix->KLUmatrixSymbolic != NULL &&
        Matrix->SMPkluMatrix->KLUmatrixCommon != NULL &&
        Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_OK)
    {
        /* klu_rcond resets Common->status to KLU_OK on its way in, so it is
         * only consulted when klu_factor's own verdict was OK -- a singular
         * verdict must reach the caller untouched. */
        if (klu_rcond (Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                       Matrix->SMPkluMatrix->KLUmatrixNumeric,
                       Matrix->SMPkluMatrix->KLUmatrixCommon) &&
            Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_OK)
            Matrix->SMPkluMatrix->KLUmatrixRcondFactor = Matrix->SMPkluMatrix->KLUmatrixCommon->rcond ;
        Matrix->SMPkluMatrix->KLUmatrixCommon->status = KLU_OK ;
    }
}

int
SMPluFac (SMPmatrix *Matrix, double PivTol, double Gmin)
{
    int ret ;

    NG_IGNORE (PivTol) ;

    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return 0 ;
        }

        if (Matrix->SMPkluMatrix->KLUloadDiagGmin) {
            LoadGmin_CSC (Matrix->SMPkluMatrix->KLUmatrixDiag, Matrix->SMPkluMatrix->KLUmatrixN, Gmin) ;
        }

        /* Enhancement-499: the mirror of the guard in SMPcLUfac -- a real
         * refactor of a COMPLEX Numeric is wrong the same way round. Reachable
         * whenever a transient or operating point follows an AC on a circuit
         * whose matrix was kept standing. */
        if (Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL ||
            Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL)
                klu_free_numeric (&(Matrix->SMPkluMatrix->KLUmatrixNumeric),
                                  Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            Matrix->SMPkluMatrix->KLUmatrixNumeric =
                klu_factor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi,
                            Matrix->SMPkluMatrix->KLUmatrixAx,
                            Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                            Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex = 0 ;
            ret = (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL) ;
            klu_note_factor_rcond (Matrix) ;
        } else {
            ret = klu_refactor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAx,
                                Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        }

        if (ret == 0)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon == NULL) {
                fprintf (stderr, "Error (ReFactor): KLUcommon object is NULL. A problem occurred\n") ;
                return 0 ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR) {
                if (ft_ngdebug) {
                    fprintf(stderr, "Warning (ReFactor): KLU Matrix is SINGULAR\n");
                    fprintf(stderr, "  Numerical Rank: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->numerical_rank);
                    fprintf(stderr, "  Singular Node: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1);
                }
                return E_SINGULAR ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX)
            {
                klu_report_empty () ;
                return 0 ;
            }
            if (!klu_empty_reported && Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL) {
                fprintf (stderr, "Error (ReFactor): KLUnumeric object is NULL. A problem occurred\n") ;
            }
            return 1 ;
        } else {
            /* Enhancement-439: a SUCCESSFUL klu_refactor is not necessarily a
             * USABLE factorization.
             *
             * klu_refactor reuses the pivot ordering chosen by the last full
             * klu_factor and only refills the values -- it performs no pivoting
             * and no singularity test. When the values have since drifted to a
             * numerically singular configuration it fills the LU with zero (or
             * Inf/NaN) pivots, returns SUCCESS, and leaves status = KLU_OK. The
             * next klu_solve then returns NaN, and NaN neither converges nor
             * trips any singularity check, so the Newton loop and every rung of
             * CKTop's homotopy ladder run to their full iteration budgets on a
             * factorization that was already useless.
             *
             * Measured on a node with no DC path (the midpoint of two series
             * capacitors, whose row has NO diagonal entry at all so Gmin can
             * never be applied to it): once gmin stepping reached 1e-12 the
             * refactor reported ret=1/status=0 while the solve returned
             * non-finite values -- then 33,835 further non-finite solves, with
             * refactor reporting OK 33,191 times, ending in a "timestep too
             * small" message that names neither the node nor the cause. SPARSE
             * solves the same circuit because its refactor path DOES detect the
             * zero pivot and forces a full reorder.
             *
             * klu_rcond is the cheap, exact test for this: it walks diag(U) and
             * sets rcond = 0 with status = KLU_SINGULAR the moment it finds a
             * zero or NaN pivot. Reporting E_SINGULAR here routes the caller
             * into the reorder-and-factor-again path it already has, which
             * pivots properly -- the same recovery SPARSE performs. */
            if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL &&
                Matrix->SMPkluMatrix->KLUmatrixSymbolic != NULL &&
                Matrix->SMPkluMatrix->KLUmatrixCommon != NULL)
            {
                klu_rcond (Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                           Matrix->SMPkluMatrix->KLUmatrixNumeric,
                           Matrix->SMPkluMatrix->KLUmatrixCommon) ;
                if (Matrix->SMPkluMatrix->KLUmatrixCommon->rcond == 0.0) {
                    if (ft_ngdebug)
                        fprintf (stderr, "Warning (ReFactor): reuse of the existing "
                                 "pivot order produced a singular U; forcing a "
                                 "full factorization\n") ;
                    return E_SINGULAR ;
                }
                /* 2026-09-04 large-circuit sweep, F1: the same reuse can be
                 * numerically terrible without being singular. SPARSE's
                 * refactor tests every reused pivot against its column
                 * (spSMALL_PIVOT) and the caller reorders; KLU's refactor
                 * tests nothing, so when the Jacobian has changed character
                 * since the pivots were chosen -- a Newton whose second
                 * iterate exploded and whose third is evaluated at limited
                 * voltages -- U's diagonal collapses, the solve returns a
                 * wrong direction with no error, and the iteration wanders
                 * until the operating point falls into gmin stepping (whose
                 * every rung reorders, and so converges). Measured on a
                 * 20x20 OSDI BSIM4 grid: 137 iterations with gmin stepping
                 * under KLU against 8 under SPARSE for the same matrices.
                 * rcond is already computed above; a collapse by more than
                 * KLU_REFACTOR_RCOND_DROP relative to the last full
                 * factorization's value is treated like a small pivot. A
                 * stiff circuit's tiny rcond passes unharmed: the test is
                 * relative to its own full-factor value. */
                if (Matrix->SMPkluMatrix->KLUmatrixRcondFactor > 0.0 &&
                    Matrix->SMPkluMatrix->KLUmatrixCommon->rcond <
                        KLU_REFACTOR_RCOND_DROP * Matrix->SMPkluMatrix->KLUmatrixRcondFactor) {
                    if (ft_ngdebug)
                        fprintf (stderr, "Warning (ReFactor): reuse of the existing pivot "
                                 "order lost %.1e in rcond (%.3e vs %.3e at the last full "
                                 "factorization); forcing a full factorization\n",
                                 Matrix->SMPkluMatrix->KLUmatrixCommon->rcond /
                                 Matrix->SMPkluMatrix->KLUmatrixRcondFactor,
                                 Matrix->SMPkluMatrix->KLUmatrixCommon->rcond,
                                 Matrix->SMPkluMatrix->KLUmatrixRcondFactor) ;
                    return E_SINGULAR ;
                }
            }
            return 0 ;
        }
    } else {
        spSetReal (Matrix->SPmatrix) ;
        LoadGmin (Matrix, Gmin) ;
        return spFactor (Matrix->SPmatrix) ;
    }
}

#ifdef CIDER
int
SMPluFacKLUforCIDER (SMPmatrix *Matrix)
{
    unsigned int i ;
    double *KLUmatrixAx ;
    int ret ;

    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return 0 ;
        }

        if (Matrix->SMPkluMatrix->KLUmatrixIsComplex) {
            ret = klu_z_refactor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAxComplex,
                                  Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        } else {
            /* Allocate the Real Matrix */
            KLUmatrixAx = (double *) malloc (Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof(double)) ;

            /* Copy the Complex Matrix into the Real Matrix */
            for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixNZ ; i++) {
                KLUmatrixAx [i] = Matrix->SMPkluMatrix->KLUmatrixAxComplex [2 * i] ;
            }

            /* Re-Factor the Real Matrix */
            ret = klu_refactor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, KLUmatrixAx,
                                Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

            /* Free the Real Matrix Storage */
            free (KLUmatrixAx) ;
        }

        if (ret == 0)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR) {
                if (ft_ngdebug) {
                    fprintf(stderr, "Warning (ReFactor for CIDER): KLU Matrix is SINGULAR\n");
                    fprintf(stderr, "  Numerical Rank: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->numerical_rank);
                    fprintf(stderr, "  Singular Node: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1);
                }
                return E_SINGULAR ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon == NULL) {
                fprintf (stderr, "Error (ReFactor for CIDER): KLUcommon object is NULL. A problem occurred\n") ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX)
            {
                klu_report_empty () ;
                return 0 ;
            }
            if (!klu_empty_reported && Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL) {
                fprintf (stderr, "Error (ReFactor for CIDER): KLUnumeric object is NULL. A problem occurred\n") ;
            }
            return 1 ;
        } else {
            return 0 ;
        }
    } else {
        return spFactor (Matrix->SPmatrix) ;
    }
}
#endif

/*
 * SMPcReorder()
 */

int
SMPcReorder (SMPmatrix *Matrix, double PivTol, double PivRel, int *NumSwaps)
{
    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return 0 ;
        }

        /* Sanitize the pivot threshold like Sparse's spOrderAndFactor does: an
         * in-range PivRel takes effect; an out-of-range one (pole-zero passes
         * 0.0) falls back to FULL partial pivoting (tol = 1.0) instead of being
         * used raw.  Two reasons.  (1) tol = 0.0 makes KLU accept an
         * EXACTLY-ZERO diagonal as pivot: at PZ's s = 0 trial an inductor
         * branch has a 0.0 diagonal, the factorization came back KLU_SINGULAR,
         * and PZ recorded a spurious root at the origin.  (2) KLU's ordering is
         * fixed at klu_analyze time (pattern-only); Sparse re-runs value-aware
         * Markowitz ordering every PZ trial, but KLU's only value-adaptive
         * lever is the within-block partial pivoting.  PZ sweeps |s| across
         * ~20 decades, and with the relaxed default tol = 0.001 the fixed
         * ordering picks catastrophically-cancelling pivots at extreme |s| --
         * the determinant came back with the wrong sign and magnitude (verified
         * against an exact rational determinant of the same loaded matrix),
         * minting spurious far-field roots.  Full partial pivoting keeps the
         * determinant accurate across the whole sweep. */
        if (PivRel > 0.0 && PivRel <= 1.0)
            Matrix->SMPkluMatrix->KLUmatrixCommon->tol = PivRel ;
        else
            Matrix->SMPkluMatrix->KLUmatrixCommon->tol = 1.0 ;

        if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL) {
            klu_free_numeric (&(Matrix->SMPkluMatrix->KLUmatrixNumeric), Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        }
        Matrix->SMPkluMatrix->KLUmatrixNumeric = klu_z_factor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi,
                                                               Matrix->SMPkluMatrix->KLUmatrixAxComplex, Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                                                               Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex = 1 ;   /* Enhancement-499 */
        klu_note_zfactor_rcond (Matrix) ;   /* F7: the reference for every refactor of this sweep */

        if (Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon == NULL) {
                fprintf (stderr, "Error (Factor Complex): KLUcommon object is NULL. A problem occurred\n") ;
                return 1 ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR) {
                if (ft_ngdebug) {
                    fprintf(stderr, "Warning (Factor Complex): KLU Matrix is SINGULAR\n");
                    fprintf(stderr, "  Numerical Rank: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->numerical_rank);
                    fprintf(stderr, "  Singular Node: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1);
                }
                return E_SINGULAR ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX) {
                klu_report_empty () ;
                return 0 ;
            }
            if (!klu_empty_reported && Matrix->SMPkluMatrix->KLUmatrixSymbolic == NULL) {
                fprintf (stderr, "Error (Factor Complex): KLUsymbolic object is NULL. A problem occurred\n") ;
            }
            return 1 ;
        } else {
            return 0 ;
        }
    } else {
        *NumSwaps = 1 ;
        spSetComplex (Matrix->SPmatrix) ;
        return spOrderAndFactor (Matrix->SPmatrix, NULL, (spREAL)PivRel, (spREAL)PivTol, YES) ;
    }
}

/*
 * SMPreorder()
 */

int
SMPreorder (SMPmatrix *Matrix, double PivTol, double PivRel, double Gmin)
{
    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return 0 ;
        }

        if (Matrix->SMPkluMatrix->KLUloadDiagGmin) {
            LoadGmin_CSC (Matrix->SMPkluMatrix->KLUmatrixDiag, Matrix->SMPkluMatrix->KLUmatrixN, Gmin) ;
        }
        /* Same threshold sanitization as SMPcReorder above. */
        if (PivRel > 0.0 && PivRel <= 1.0)
            Matrix->SMPkluMatrix->KLUmatrixCommon->tol = PivRel ;
        else
            Matrix->SMPkluMatrix->KLUmatrixCommon->tol = 1.0 ;

        if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL) {
            klu_free_numeric (&(Matrix->SMPkluMatrix->KLUmatrixNumeric), Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        }

        Matrix->SMPkluMatrix->KLUmatrixNumeric = klu_factor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi,
                                                             Matrix->SMPkluMatrix->KLUmatrixAx, Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                                                             Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex = 0 ;   /* Enhancement-499 */
        klu_note_factor_rcond (Matrix) ;   /* F1 (large-circuit sweep): the reference for every refactor */

        if (Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon == NULL) {
                fprintf (stderr, "Error (Factor): KLUcommon object is NULL. A problem occurred\n") ;
                return 1 ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR) {
                if (ft_ngdebug) {
                    fprintf(stderr, "Warning (Factor): KLU Matrix is SINGULAR\n");
                    fprintf(stderr, "  Numerical Rank: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->numerical_rank);
                    fprintf(stderr, "  Singular Node: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1);
                }
                return E_SINGULAR ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX) {
                klu_report_empty () ;
                return 0 ;
            }
            if (!klu_empty_reported && Matrix->SMPkluMatrix->KLUmatrixSymbolic == NULL) {
                fprintf (stderr, "Error (Factor): KLUsymbolic object is NULL. A problem occurred\n") ;
            }
            return 1 ;
        } else {
            return 0 ;
        }
    } else {
        spSetReal (Matrix->SPmatrix) ;
        LoadGmin (Matrix, Gmin) ;
        return spOrderAndFactor (Matrix->SPmatrix, NULL, (spREAL)PivRel, (spREAL)PivTol, YES) ;
    }
}

#ifdef CIDER
int
SMPreorderKLUforCIDER (SMPmatrix *Matrix)
{
    unsigned int i ;
    double *KLUmatrixAx ;

    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return 0 ;
        }

        if (Matrix->SMPkluMatrix->KLUmatrixNumeric != NULL) {
            klu_free_numeric (&(Matrix->SMPkluMatrix->KLUmatrixNumeric), Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        }
        if (Matrix->SMPkluMatrix->KLUmatrixIsComplex) {
            Matrix->SMPkluMatrix->KLUmatrixNumeric = klu_z_factor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi,
                                                                   Matrix->SMPkluMatrix->KLUmatrixAxComplex, Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                                                                   Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex = 1 ;   /* Enhancement-499 */
        } else {
            /* Allocate the Real Matrix */
            KLUmatrixAx = (double *) malloc (Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof(double)) ;

            /* Copy the Complex Matrix into the Real Matrix */
            for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixNZ ; i++) {
                KLUmatrixAx [i] = Matrix->SMPkluMatrix->KLUmatrixAxComplex [2 * i] ;
            }

            /* Factor the Real Matrix */
            Matrix->SMPkluMatrix->KLUmatrixNumeric = klu_factor (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi,
                                                                 KLUmatrixAx, Matrix->SMPkluMatrix->KLUmatrixSymbolic,
                                                                 Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex = 0 ;   /* Enhancement-499 */

            /* Free the Real Matrix Storage */
            free (KLUmatrixAx) ;
        }

        if (Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR) {
                if (ft_ngdebug) {
                    fprintf(stderr, "Warning (Factor for CIDER): KLU Matrix is SINGULAR\n");
                    fprintf(stderr, "  Numerical Rank: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->numerical_rank);
                    fprintf(stderr, "  Singular Node: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1);
                }
                return E_SINGULAR ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon == NULL) {
                fprintf (stderr, "Error (Factor for CIDER): KLUnumeric object is NULL. A problem occurred\n") ;
                fprintf (stderr, "Error (Factor for CIDER): KLUcommon object is NULL. A problem occurred\n") ;
            }
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX) {
                klu_report_empty () ;
                return 0 ;
            }
            if (!klu_empty_reported && Matrix->SMPkluMatrix->KLUmatrixSymbolic == NULL) {
                fprintf (stderr, "Error (Factor for CIDER): KLUnumeric object is NULL. A problem occurred\n") ;
                fprintf (stderr, "Error (Factor for CIDER): KLUsymbolic object is NULL. A problem occurred\n") ;
            }
            return 1 ;
        } else {
            return 0 ;
        }
    } else {
        return spFactor (Matrix->SPmatrix) ;
    }
}
#endif

/*
 * SMPcaSolve()
 */
void
SMPcaSolve (SMPmatrix *Matrix, double RHS[], double iRHS[], double Spare[], double iSpare[])
{
    int ret ;
    unsigned int i ;

    NG_IGNORE (iSpare) ;
    NG_IGNORE (Spare) ;

    if (Matrix->CKTkluMODE)
    {
        /* F1 (2026-09-06): node i of the matrix is RHS entry i+1; the
         * node-collapse map is gone (see SMPconvertCOOtoCSC). */
        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++)
        {
            Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i] = RHS [i + 1] ;
            Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i + 1] = iRHS [i + 1] ;
        }

        /* SMPcaSolve is the complex *adjoint* (transposed) solve -- the Sparse
         * branch below uses spSolveTransposed, so the KLU branch must solve
         * A.'x = b too (klu_z_tsolve, conj_solve = 0). The plain klu_z_solve
         * used here before silently produced WRONG results for any asymmetric
         * matrix (every circuit with a transistor or controlled source), which
         * is why KLU noise and pole-zero were disabled. */
        ret = klu_z_tsolve (Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, (int)Matrix->SMPkluMatrix->KLUmatrixN, 1,
                            Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex, 0, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixNrhs ; i++) {
            RHS [i] = 0 ;
            iRHS [i] = 0 ;
        }
        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++)
        {
            RHS [i + 1] = Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i] ;
            iRHS [i + 1] = Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i + 1] ;
        }
    } else {
        spSolveTransposed (Matrix->SPmatrix, RHS, RHS, iRHS, iRHS) ;
    }
}

/*
 * SMPcSolve()
 */

void
SMPcSolve (SMPmatrix *Matrix, double RHS[], double iRHS[], double Spare[], double iSpare[])
{
    int ret ;
    unsigned int i ;

    NG_IGNORE (iSpare) ;
    NG_IGNORE (Spare) ;

    if (Matrix->CKTkluMODE)
    {
        /* F1 (2026-09-06): node i of the matrix is RHS entry i+1. */
        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++)
        {
            Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i] = RHS [i + 1] ;
            Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i + 1] = iRHS [i + 1] ;
        }

        ret = klu_z_solve (Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, (int)Matrix->SMPkluMatrix->KLUmatrixN, 1,
                           Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixNrhs ; i++) {
            RHS [i] = 0 ;
            iRHS [i] = 0 ;
        }
        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++)
        {
            RHS [i + 1] = Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i] ;
            iRHS [i + 1] = Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i + 1] ;
        }
    } else {
        spSolve (Matrix->SPmatrix, RHS, RHS, iRHS, iRHS) ;
    }
}

/*
 * SMPsolve()
 */

void
SMPsolve (SMPmatrix *Matrix, double RHS[], double Spare[])
{
    int empty_matrix = 0 ;   /* Enhancement-492: see klu_report_empty() */
    int ret ;
    unsigned int i ;

    NG_IGNORE (Spare) ;

    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return ;
        }

        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
            Matrix->SMPkluMatrix->KLUmatrixIntermediate [i] = RHS [i + 1] ;   /* F1: identity, see SMPconvertCOOtoCSC */
        }

        ret = klu_solve (Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, (int)Matrix->SMPkluMatrix->KLUmatrixN, 1,
                         Matrix->SMPkluMatrix->KLUmatrixIntermediate, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

        if (ret == 0)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon == NULL) {
                fprintf (stderr, "Error (Solve): KLUcommon object is NULL. A problem occurred\n") ;
            } else {
                if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR) {
                    if (ft_ngdebug) {
                        fprintf(stderr, "Warning (Solve): KLU Matrix is SINGULAR\n");
                        fprintf(stderr, "  Numerical Rank: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->numerical_rank);
                        fprintf(stderr, "  Singular Node: %d\n", Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1);
                    }
                    /* FIXME: Do we need a 'return E_SINGULAR' here? */
                }
                if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX)
                {
                    klu_report_empty () ;
                    empty_matrix = 1 ;
                }
            }
            /* Enhancement-492: when the matrix is empty these two objects are
               NULL BECAUSE of that, so reporting them as separate faults told
               the reader three things about one condition. */
            if (!empty_matrix && Matrix->SMPkluMatrix->KLUmatrixNumeric == NULL) {
                fprintf (stderr, "Error (Solve): KLUnumeric object is NULL. A problem occurred\n") ;
            }
            if (!empty_matrix && Matrix->SMPkluMatrix->KLUmatrixSymbolic == NULL) {
                fprintf (stderr, "Error (Solve): KLUsymbolic object is NULL. A problem occurred\n") ;
            }
        }

        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixNrhs ; i++) {
            RHS [i] = 0 ;
        }

        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
            RHS [i + 1] = Matrix->SMPkluMatrix->KLUmatrixIntermediate [i] ;
        }
    } else {
        spSolve (Matrix->SPmatrix, RHS, RHS, NULL, NULL) ;
    }
}

#ifdef CIDER
void
SMPsolveKLUforCIDER (SMPmatrix *Matrix, double RHS[], double RHSsolution[], double iRHS[], double iRHSsolution[])
{
    int ret ;
    unsigned int i ;
    double *KLUmatrixIntermediate ;

    if (Matrix->CKTkluMODE)
    {
        if (Matrix->SMPkluMatrix->KLUmatrixIsComplex) {
            for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++)
            {
                Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i] = RHS [i + 1] ;
                Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i + 1] = iRHS [i + 1] ;
            }

            ret = klu_z_solve (Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, (int)Matrix->SMPkluMatrix->KLUmatrixN, 1,
                               Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

            for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++)
            {
                RHSsolution [i + 1] = Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i] ;
                iRHSsolution [i + 1] = Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex [2 * i + 1] ;
            }
        } else {
            /* Allocate the Intermediate Vector */
            KLUmatrixIntermediate = (double *) malloc (Matrix->SMPkluMatrix->KLUmatrixN * sizeof(double)) ;

            for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
                KLUmatrixIntermediate [i] = RHS [i + 1] ;
            }

            ret = klu_solve (Matrix->SMPkluMatrix->KLUmatrixSymbolic, Matrix->SMPkluMatrix->KLUmatrixNumeric, (int)Matrix->SMPkluMatrix->KLUmatrixN, 1,
                             KLUmatrixIntermediate, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

            for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
                RHSsolution [i + 1] = KLUmatrixIntermediate [i] ;
            }

            /* Free the Intermediate Vector */
            free (KLUmatrixIntermediate) ;
        }

    } else {

        spSolve (Matrix->SPmatrix, RHS, RHSsolution, iRHS, iRHSsolution) ;
    }
}
#endif

/*
 * SMPdenseExtractReal() -- Enhancement-173: copy the real parts of the loaded
 * (complex-stored) matrix into a dense n*n row-major array, in EXTERNAL node
 * indexing, for the eigenvalue-based pole-zero method.  Read-only; must be
 * called after a load and before a factorization (Sparse factors in place).
 */
void
SMPdenseExtractReal (SMPmatrix *eMatrix, int n, double *out)
{
    int i, j ;

    for (i = 0 ; i < n * n ; i++)
        out [i] = 0.0 ;

    if (eMatrix->CKTkluMODE)
    {
        int *Ap = eMatrix->SMPkluMatrix->KLUmatrixAp ;
        int *Ai = eMatrix->SMPkluMatrix->KLUmatrixAi ;
        double *Ax = eMatrix->SMPkluMatrix->KLUmatrixAxComplex ;

        for (j = 0 ; j < (int)eMatrix->SMPkluMatrix->KLUmatrixN && j < n ; j++)
            for (i = Ap [j] ; i < Ap [j + 1] ; i++)
                if (Ai [i] < n)
                    out [(size_t)Ai [i] * (size_t)n + (size_t)j] = Ax [2 * i] ;
    } else {
        MatrixPtr M = eMatrix->SPmatrix ;
        ElementPtr e ;

        for (j = 1 ; j <= M->Size ; j++)
            for (e = M->FirstInCol [j] ; e != NULL ; e = e->NextInCol) {
                int er = M->IntToExtRowMap [e->Row] - 1 ;
                int ec = M->IntToExtColMap [j] - 1 ;
                if (er >= 0 && er < n && ec >= 0 && ec < n)
                    out [(size_t)er * (size_t)n + (size_t)ec] = e->Real ;
            }
    }
}

/*
 * SMPmatSize()
 */
int
SMPmatSize (SMPmatrix *Matrix)
{
    if (Matrix->CKTkluMODE) {
        return (int)Matrix->SMPkluMatrix->KLUmatrixN ;
    } else {
        return spGetSize (Matrix->SPmatrix, 1) ;
    }
}

/*
 * SMPsizeHint() -- F8 (2026-09-06): the circuit has `n` unknowns (node numbers
 * 1..n).  Both solvers size themselves from the entries they receive, so a
 * node nothing stamps was outside the matrix; CKTsetup and CKTpzSetup call
 * this once the count is final.  KLU consumes the hint in SMPconvertCOOtoCSC;
 * Sparse maps every index up to n (Translate() without an element).
 */
void
SMPsizeHint (SMPmatrix *Matrix, int n)
{
    if (n <= 0)
        return ;
    if (Matrix->CKTkluMODE) {
        if ((unsigned int) n > Matrix->SMPkluMatrix->KLUmatrixN)
            Matrix->SMPkluMatrix->KLUmatrixN = (unsigned int) n ;
    } else {
        int e ;
        for (e = 1 ; e <= n ; e++)
            spEnsureNode (Matrix->SPmatrix, e) ;
    }
}

/*
 * SMPmarkOccupied() -- F1/F8, Enhancement-569: for every unknown e in 1..n
 * set rowocc[e] = 1 if its matrix ROW has an entry and colocc[e] = 1 if its
 * COLUMN has one.  A structurally solvable unknown needs both: the row is its
 * equation, the column is where it appears in the others'.  E-566 tested the
 * column alone, which catches a node nothing conducts to (a current source or
 * a controlled-current-source output: an equation with no unknown in it) but
 * not a node that a device only READS -- a B-source `v=2*v(x)` or an XSPICE
 * input port puts its derivative in the reader's row, column x, so x had a
 * column entry and an EMPTY row, no gmin could rescue it, and the operating
 * point failed on both solvers, Sparse blaming x and KLU the reader's branch.
 * Called by CKTsetup before the KLU conversion, so the KLU side reads the COO
 * list; the Sparse side walks every element of the indices translated so far.
 */
void
SMPmarkOccupied (SMPmatrix *Matrix, unsigned char *rowocc, unsigned char *colocc, int n)
{
    if (Matrix->CKTkluMODE) {
        KluLinkedListCOO *t ;
        for (t = Matrix->SMPkluMatrix->KLUmatrixLinkedListCOO ; t != NULL ; t = t->next) {
            if ((int) t->row + 1 <= n)
                rowocc [t->row + 1] = 1 ;
            if ((int) t->col + 1 <= n)
                colocc [t->col + 1] = 1 ;
        }
    } else {
        MatrixPtr M = Matrix->SPmatrix ;
        int ic ;
        for (ic = 1 ; ic <= M->Size ; ic++) {
            ElementPtr e ;
            int ec = M->IntToExtColMap [ic] ;
            for (e = M->FirstInCol [ic] ; e != NULL ; e = e->NextInCol) {
                int er = M->IntToExtRowMap [e->Row] ;
                if (er >= 1 && er <= n)
                    rowocc [er] = 1 ;
                if (ec >= 1 && ec <= n)
                    colocc [ec] = 1 ;
            }
        }
    }
}

/*
 * SMPdiagNorm() -- Enhancement-153: the largest magnitude on the loaded matrix
 * diagonal, used as the scale-invariant reference for the trust-region
 * (Levenberg-Marquardt) damping mu = lambda * ||diag||. Must be called after
 * CKTload and before factorization (the factor overwrites the matrix in place).
 */
double
SMPdiagNorm (SMPmatrix *Matrix)
{
    double norm = 0.0 ;
    if (Matrix->CKTkluMODE) {
        double **diag = Matrix->SMPkluMatrix->KLUmatrixDiag ;
        unsigned int i, n = Matrix->SMPkluMatrix->KLUmatrixN ;
        if (diag == NULL)
            return 0.0 ;
        for (i = 0 ; i < n ; i++)
            if (diag [i] != NULL && fabs (*(diag [i])) > norm)
                norm = fabs (*(diag [i])) ;
    } else {
        MatrixPtr M = Matrix->SPmatrix ;
        int I ;
        for (I = M->Size ; I > 0 ; I--)
            if (M->Diag [I] != NULL && fabs (M->Diag [I]->Real) > norm)
                norm = fabs (M->Diag [I]->Real) ;
    }
    return norm ;
}

/*
 * SMPnewMatrix()
 */
int
SMPnewMatrix (SMPmatrix *Matrix, int size)
{
    int Error ;

    if (Matrix->CKTkluMODE) {
        /* Allocate the KLU Matrix Data Structure */
        Matrix->SMPkluMatrix = (KLUmatrix *) malloc (sizeof (KLUmatrix)) ;
        Matrix->SMPkluMatrix->KLUmatrixLinkedListNZ = 0 ;
        Matrix->SMPkluMatrix->KLUmatrixLinkedListCOO = NULL ;

        /* Initialize the KLU Matrix Internal Pointers */
        Matrix->SMPkluMatrix->KLUmatrixCommon = (klu_common *) malloc (sizeof (klu_common)) ; ;
        Matrix->SMPkluMatrix->KLUmatrixSymbolic = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNumeric = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex = 0 ;   /* Enhancement-499 */
        Matrix->SMPkluMatrix->KLUmatrixAp = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAi = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAx = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAxComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixIsComplex = KLUmatrixReal ;
        Matrix->SMPkluMatrix->KLUmatrixIntermediate = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNZ = 0 ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructCOO = NULL ;
//        Matrix->SMPkluMatrix->KLUmatrixNodeCollapsingOldToNew = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNodeCollapsingNewToOld = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixDiag = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixRcondFactor = 0.0 ;          /* was left uninitialised */
        Matrix->SMPkluMatrix->KLUmatrixRcondFactorComplex = 0.0 ;   /* F7 */

        /* Initialize the KLU Common Data Structure */
        klu_defaults (Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        Matrix->SMPkluMatrix->KLUmatrixCommon->memgrow = Matrix->CKTkluMemGrowFactor ;
        /* Enhancement-152: honor .option klu_ordering / klu_scale / klu_btf
         * (defaults above match klu_defaults, so unchanged unless the user set them) */
        Matrix->SMPkluMatrix->KLUmatrixCommon->ordering = Matrix->CKTkluOrdering ;
        Matrix->SMPkluMatrix->KLUmatrixCommon->scale = Matrix->CKTkluScale ;
        Matrix->SMPkluMatrix->KLUmatrixCommon->btf = Matrix->CKTkluBTF ;

        /* Allocate KLU data structures */
        Matrix->SMPkluMatrix->KLUmatrixN = (unsigned int)size ;
        Matrix->SMPkluMatrix->KLUmatrixTrashCOO = (double *) malloc (2 * sizeof (double)) ;

        return spOKAY ;
    } else {
        Matrix->SPmatrix = spCreate (size, 1, &Error) ;
        return Error ;
    }
}

#ifdef CIDER
int
SMPnewMatrixKLUforCIDER (SMPmatrix *Matrix, int size, unsigned int KLUmatrixIsComplex)
{
    int Error ;
    unsigned int i ;

    if (Matrix->CKTkluMODE) {
        /* Allocate the KLU Matrix Data Structure */
        Matrix->SMPkluMatrix = (KLUmatrix *) malloc (sizeof (KLUmatrix)) ;

        /* Initialize the KLU Matrix Internal Pointers */
        Matrix->SMPkluMatrix->KLUmatrixCommon = (klu_common *) malloc (sizeof (klu_common)) ; ;
        Matrix->SMPkluMatrix->KLUmatrixSymbolic = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNumeric = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNumericIsComplex = 0 ;   /* Enhancement-499 */
        Matrix->SMPkluMatrix->KLUmatrixAp = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAi = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAxComplex = NULL ;
        if (KLUmatrixIsComplex) {
            Matrix->SMPkluMatrix->KLUmatrixIsComplex = KLUMatrixComplex ;
        } else {
            Matrix->SMPkluMatrix->KLUmatrixIsComplex = KLUmatrixReal ;
        }
        Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNZ = 0 ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructForCIDER = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixValueComplexCOOforCIDER = NULL ;

        Matrix->SMPkluMatrix->KLUmatrixDiag = NULL ;

        /* Initialize the KLU Common Data Structure */
        klu_defaults (Matrix->SMPkluMatrix->KLUmatrixCommon) ;

        /* Allocate KLU data structures */
        Matrix->SMPkluMatrix->KLUmatrixN = (unsigned int)size ;
        Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER = (int *) malloc (Matrix->SMPkluMatrix->KLUmatrixN * Matrix->SMPkluMatrix->KLUmatrixN * sizeof(int)) ;
        Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER = (int *) malloc (Matrix->SMPkluMatrix->KLUmatrixN * Matrix->SMPkluMatrix->KLUmatrixN * sizeof(int)) ;
        Matrix->SMPkluMatrix->KLUmatrixTrashCOO = (double *) malloc (2 * sizeof(double)) ;
        Matrix->SMPkluMatrix->KLUmatrixValueComplexCOOforCIDER = (double *) malloc (2 * Matrix->SMPkluMatrix->KLUmatrixN * Matrix->SMPkluMatrix->KLUmatrixN * sizeof(double)) ;

        /* Pre-set the values of Row and Col */
        for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixN * Matrix->SMPkluMatrix->KLUmatrixN ; i++) {
            Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER [i] = -1 ;
            Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER [i] = -1 ;
        }

        return spOKAY ;
    } else {
        Matrix->SPmatrix = spCreate (size, (int)KLUmatrixIsComplex, &Error) ;
        return Error ;
    }
}
#endif

/*
 * SMPdestroy()
 */

void
SMPdestroy (SMPmatrix *Matrix)
{
    if (Matrix->CKTkluMODE)
    {
        klu_free_numeric (&(Matrix->SMPkluMatrix->KLUmatrixNumeric), Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        klu_free_symbolic (&(Matrix->SMPkluMatrix->KLUmatrixSymbolic), Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        free (Matrix->SMPkluMatrix->KLUmatrixAp) ;
        free (Matrix->SMPkluMatrix->KLUmatrixAi) ;
        free (Matrix->SMPkluMatrix->KLUmatrixAx) ;
        free (Matrix->SMPkluMatrix->KLUmatrixAxComplex) ;
        free (Matrix->SMPkluMatrix->KLUmatrixIntermediate) ;
        free (Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex) ;
        free (Matrix->SMPkluMatrix->KLUmatrixBindStructCOO) ;
//        free (Matrix->SMPkluMatrix->KLUmatrixNodeCollapsingOldToNew) ;
        free (Matrix->SMPkluMatrix->KLUmatrixNodeCollapsingNewToOld) ;
        free (Matrix->SMPkluMatrix->KLUmatrixTrashCOO) ;
        Matrix->SMPkluMatrix->KLUmatrixAp = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAi = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAx = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAxComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixIntermediate = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructCOO = NULL ;
//        Matrix->SMPkluMatrix->KLUmatrixNodeCollapsingOldToNew = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixNodeCollapsingNewToOld = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixTrashCOO = NULL ;
        free (Matrix->SMPkluMatrix->KLUmatrixDiag) ;
        free (Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        free (Matrix->SMPkluMatrix) ;
    } else {
        spDestroy (Matrix->SPmatrix) ;
    }
}

#ifdef CIDER
void
SMPdestroyKLUforCIDER (SMPmatrix *Matrix)
{
    if (Matrix->CKTkluMODE)
    {
        klu_free_numeric (&(Matrix->SMPkluMatrix->KLUmatrixNumeric), Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        klu_free_symbolic (&(Matrix->SMPkluMatrix->KLUmatrixSymbolic), Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        free (Matrix->SMPkluMatrix->KLUmatrixAp) ;
        free (Matrix->SMPkluMatrix->KLUmatrixAi) ;
        free (Matrix->SMPkluMatrix->KLUmatrixAxComplex) ;
        free (Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex) ;
        free (Matrix->SMPkluMatrix->KLUmatrixBindStructForCIDER) ;
        free (Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER) ;
        free (Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER) ;
        free (Matrix->SMPkluMatrix->KLUmatrixValueComplexCOOforCIDER) ;
        free (Matrix->SMPkluMatrix->KLUmatrixTrashCOO) ;
        Matrix->SMPkluMatrix->KLUmatrixAp = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAi = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixAxComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixIntermediateComplex = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixBindStructForCIDER = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixColCOOforCIDER = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixRowCOOforCIDER = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixValueComplexCOOforCIDER = NULL ;
        Matrix->SMPkluMatrix->KLUmatrixTrashCOO = NULL ;
        free (Matrix->SMPkluMatrix->KLUmatrixDiag) ;
        free (Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        free (Matrix->SMPkluMatrix) ;
    } else {
        spDestroy (Matrix->SPmatrix) ;
    }
}
#endif

/*
 * SMPpreOrder()
 */


int
SMPpreOrder (SMPmatrix *Matrix)
{
    if (Matrix->CKTkluMODE)
    {
        if (CircuitIsDigital() && Matrix->SMPkluMatrix->KLUmatrixN == 0) {
          // XSPICE pure digital circuits produce empty KLU matrix
          return 0 ;
        }

        Matrix->SMPkluMatrix->KLUmatrixSymbolic = klu_analyze ((int)Matrix->SMPkluMatrix->KLUmatrixN, Matrix->SMPkluMatrix->KLUmatrixAp,
                                                               Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

        if (Matrix->SMPkluMatrix->KLUmatrixSymbolic == NULL)
        {
            if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_EMPTY_MATRIX)
            {
                klu_report_empty () ;
                return 0 ;
            } else {
                fprintf (stderr, "Error (PreOrder): KLUsymbolic object is NULL. A problem occurred\n") ;
                return 1 ;
            }
        } else {
            return 0 ;
        }
    } else {
        spMNA_Preorder (Matrix->SPmatrix) ;
        return spError (Matrix->SPmatrix) ;
    }
}

/*
 * SMPprintRHS()
 */

void
SMPprintRHS (SMPmatrix *Matrix, char *Filename, RealVector RHS, RealVector iRHS)
{
    if (!Matrix->CKTkluMODE)
        spFileVector (Matrix->SPmatrix, Filename, RHS, iRHS) ;
}

/*
 * SMPprint()
 */

void
SMPprint (SMPmatrix *Matrix, char *Filename)
{
    if (Matrix->CKTkluMODE)
    {
        if (Matrix->SMPkluMatrix->KLUmatrixIsComplex)
        {
            klu_z_print (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAxComplex,
                         (int)Matrix->SMPkluMatrix->KLUmatrixN, NULL, NULL) ;
        } else {
            klu_print (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAx,
                       (int)Matrix->SMPkluMatrix->KLUmatrixN, NULL, NULL) ;
        }
    } else {
        if (Filename)
            spFileMatrix (Matrix->SPmatrix, Filename, "Circuit Matrix", 0, 1, 1) ;
        else
            spPrint (Matrix->SPmatrix, 0, 1, 1) ;
    }
}

#ifdef CIDER
void
SMPprintKLUforCIDER (SMPmatrix *Matrix, char *Filename)
{
    unsigned int i ;
    double *KLUmatrixAx ;

    if (Matrix->CKTkluMODE)
    {
        if (Matrix->SMPkluMatrix->KLUmatrixIsComplex)
        {
            klu_z_print (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAxComplex,
                         (int)Matrix->SMPkluMatrix->KLUmatrixN, NULL, NULL) ;
        } else {
            /* Allocate the Real Matrix */
            KLUmatrixAx = (double *) malloc (Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof(double)) ;

            /* Copy the Complex Matrix into the Real Matrix */
            for (i = 0 ; i < Matrix->SMPkluMatrix->KLUmatrixNZ ; i++) {
                KLUmatrixAx [i] = Matrix->SMPkluMatrix->KLUmatrixAxComplex [2 * i] ;
            }

            /* Print the Real Matrix */
            klu_print (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, KLUmatrixAx, (int)Matrix->SMPkluMatrix->KLUmatrixN, NULL, NULL) ;

            /* Free the Real Matrix Storage */
            free (KLUmatrixAx) ;
        }
    } else {
        if (Filename)
            spFileMatrix (Matrix->SPmatrix, Filename, "Circuit Matrix", 0, 1, 1) ;
        else
            spPrint (Matrix->SPmatrix, 0, 1, 1) ;
    }
}
#endif

/*
 * SMPgetError()
 */
void
SMPgetError (SMPmatrix *Matrix, int *Col, int *Row)
{
    if (Matrix->CKTkluMODE)
    {
        if (Matrix->SMPkluMatrix->KLUmatrixNZ == 0) {
            *Row = 0 ;
            *Col = 0 ;
        } else {
            *Row = Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1 ;
            *Col = Matrix->SMPkluMatrix->KLUmatrixCommon->singular_col + 1 ;
        }
    } else {
        spWhereSingular (Matrix->SPmatrix, Row, Col) ;
    }
}

/* Parity of the permutation vector perm[0..n-1]: 0 if even, 1 if odd.
 * Computed exactly via cycle decomposition -- a cycle of length L contributes
 * L-1 transpositions.  (The previous code counted non-fixed points and halved,
 * which is wrong for any cycle longer than 2: a 3-cycle is an EVEN permutation
 * but was counted as odd, flipping the determinant's sign.) */
static unsigned int
PermutationParity (const int *perm, unsigned int n)
{
    unsigned char *visited = (unsigned char *) calloc ((size_t)n, 1) ;
    unsigned int i, j, parity = 0 ;

    if (visited == NULL)
        return 0 ;
    for (i = 0 ; i < n ; i++) {
        if (!visited [i]) {
            unsigned int len = 0 ;
            j = i ;
            while (!visited [j]) {
                visited [j] = 1 ;
                j = (unsigned int) perm [j] ;
                len++ ;
            }
            parity ^= (len - 1) & 1 ;
        }
    }
    free (visited) ;
    return parity ;
}

void
spDeterminant_KLU (SMPmatrix *Matrix, int *pExponent, RealNumber *pDeterminant, RealNumber *piDeterminant)
{
    int I, Size ;
    RealNumber Norm, nr, ni ;
    ComplexNumber Pivot, cDeterminant ;

    int *P, *Q ;
    double *Rs, *Ux, *Uz ;
    unsigned int nSwap ;

#define  NORM(a)     (nr = ABS((a).Real), ni = ABS((a).Imag), MAX (nr,ni))

    *pExponent = 0 ;

    if (Matrix->SMPkluMatrix->KLUmatrixCommon->status == KLU_SINGULAR)
    {
	*pDeterminant = 0.0 ;
        *piDeterminant = 0.0 ;
        return ;
    }

    Size = (int)Matrix->SMPkluMatrix->KLUmatrixN ;
    I = 0 ;

    P = (int *) malloc ((size_t)Matrix->SMPkluMatrix->KLUmatrixN * sizeof (int)) ;
    Q = (int *) malloc ((size_t)Matrix->SMPkluMatrix->KLUmatrixN * sizeof (int)) ;

    Ux = (double *) malloc ((size_t)Matrix->SMPkluMatrix->KLUmatrixN * sizeof (double)) ;

    Rs = (double *) malloc ((size_t)Matrix->SMPkluMatrix->KLUmatrixN * sizeof (double)) ;

    if (Matrix->SMPkluMatrix->KLUmatrixIsComplex == KLUMatrixComplex)        /* Complex Case. */
    {
	cDeterminant.Real = 1.0 ;
        cDeterminant.Imag = 0.0 ;

        Uz = (double *) malloc ((size_t)Matrix->SMPkluMatrix->KLUmatrixN * sizeof (double)) ;
/*
        int *Lp, *Li, *Up, *Ui, *Fp, *Fi, *P, *Q ;
        double *Lx, *Lz, *Ux, *Uz, *Fx, *Fz, *Rs ;
        Lp = (int *) malloc (((size_t)Matrix->CKTkluN + 1) * sizeof (int)) ;
        Li = (int *) malloc ((size_t)Matrix->CKTkluNumeric->lnz * sizeof (int)) ;
        Lx = (double *) malloc ((size_t)Matrix->CKTkluNumeric->lnz * sizeof (double)) ;
        Lz = (double *) malloc ((size_t)Matrix->CKTkluNumeric->lnz * sizeof (double)) ;
        Up = (int *) malloc (((size_t)Matrix->CKTkluN + 1) * sizeof (int)) ;
        Ui = (int *) malloc ((size_t)Matrix->CKTkluNumeric->unz * sizeof (int)) ;
        Ux = (double *) malloc ((size_t)Matrix->CKTkluNumeric->unz * sizeof (double)) ;
        Uz = (double *) malloc ((size_t)Matrix->CKTkluNumeric->unz * sizeof (double)) ;
        Fp = (int *) malloc (((size_t)Matrix->CKTkluN + 1) * sizeof (int)) ;
        Fi = (int *) malloc ((size_t)Matrix->CKTkluNumeric->Offp [Matrix->CKTkluN] * sizeof (int)) ;
        Fx = (double *) malloc ((size_t)Matrix->CKTkluNumeric->Offp [Matrix->CKTkluN] * sizeof (double)) ;
        Fz = (double *) malloc ((size_t)Matrix->CKTkluNumeric->Offp [Matrix->CKTkluN] * sizeof (double)) ;
        klu_z_extract (Matrix->CKTkluNumeric, Matrix->CKTkluSymbolic,
                       Lp, Li, Lx, Lz,
                       Up, Ui, Ux, Uz,
                       Fp, Fi, Fx, Fz,
                       P, Q, Rs, NULL,
                       Matrix->CKTkluCommon) ;
*/
        klu_z_extract_Udiag (Matrix->SMPkluMatrix->KLUmatrixNumeric, Matrix->SMPkluMatrix->KLUmatrixSymbolic, Ux, Uz, P, Q, Rs, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
/*
        for (I = 0 ; I < Matrix->CKTkluNumeric->lnz ; I++)
        {
            printf ("L - Value: %-.9g\t%-.9g\n", Lx [I], Lz [I]) ;
        }
        for (I = 0 ; I < Matrix->CKTkluNumeric->unz ; I++)
        {
            printf ("U - Value: %-.9g\t%-.9g\n", Ux [I], Uz [I]) ;
        }
        for (I = 0 ; I < Matrix->CKTkluNumeric->Offp [Matrix->CKTkluN] ; I++)
        {
            printf ("F - Value: %-.9g\t%-.9g\n", Fx [I], Fz [I]) ;
        }

        for (I = 0 ; I < Matrix->CKTkluN ; I++)
        {
            printf ("U - Value: %-.9g\t%-.9g\n", Ux [I], Uz [I]) ;
        }
*/
        nSwap = PermutationParity (P, Matrix->SMPkluMatrix->KLUmatrixN)
              ^ PermutationParity (Q, Matrix->SMPkluMatrix->KLUmatrixN) ;


        /* KLU factors R\A(P,Q) = L*U (block triangular; the off-diagonal F
         * blocks do not change the determinant), with L unit-diagonal and the
         * row scaling DIVIDING row i by Rs[i].  klu_z_extract_Udiag returns the
         * U diagonal AS STORED (KLU's solve divides by Udiag, so it is the
         * actual pivot, not a reciprocal).  Hence
         *     det(A) = sign(P)*sign(Q) * prod(Udiag[k] * Rs[k]).
         * The previous code built the bogus mixed quantity (1/(Ux*Rs), Uz*Rs)
         * and took its complex reciprocal -- correct ONLY for a real pivot
         * (Uz == 0), garbage otherwise, which silently broke every KLU
         * pole-zero analysis with complex poles or zeros. */
        I = 0 ;
        while (I < Size)
        {
            Pivot.Real = Ux [I] * Rs [I] ;
            Pivot.Imag = Uz [I] * Rs [I] ;
            CMPLX_MULT_ASSIGN (cDeterminant, Pivot) ;

	    /* Scale Determinant. */
            Norm = NORM (cDeterminant) ;
            if (Norm != 0.0 && isfinite (Norm))   /* F5: an Inf pivot would loop forever */
            {
		while (Norm >= 1.0e12)
                {
		    cDeterminant.Real *= 1.0e-12 ;
                    cDeterminant.Imag *= 1.0e-12 ;
                    *pExponent += 12 ;
                    Norm = NORM (cDeterminant) ;
                }
                while (Norm < 1.0e-12)
                {
		    cDeterminant.Real *= 1.0e12 ;
                    cDeterminant.Imag *= 1.0e12 ;
                    *pExponent -= 12 ;
                    Norm = NORM (cDeterminant) ;
                }
            }
            I++ ;
        }

	/* Scale Determinant again, this time to be between 1.0 <= x < 10.0. */
        Norm = NORM (cDeterminant) ;
        if (Norm != 0.0 && isfinite (Norm))
        {
	    while (Norm >= 10.0)
            {
		cDeterminant.Real *= 0.1 ;
                cDeterminant.Imag *= 0.1 ;
                (*pExponent)++ ;
                Norm = NORM (cDeterminant) ;
            }
            while (Norm < 1.0)
            {
		cDeterminant.Real *= 10.0 ;
                cDeterminant.Imag *= 10.0 ;
                (*pExponent)-- ;
                Norm = NORM (cDeterminant) ;
            }
        }
        if (nSwap % 2 != 0)
        {
            CMPLX_NEGATE (cDeterminant) ;
        }

        *pDeterminant = cDeterminant.Real ;
        *piDeterminant = cDeterminant.Imag ;

        free (Uz) ;
    }
    else
    {
	/* Real Case. */
        *pDeterminant = 1.0 ;
        *piDeterminant = 0.0 ;

        klu_extract_Udiag (Matrix->SMPkluMatrix->KLUmatrixNumeric, Matrix->SMPkluMatrix->KLUmatrixSymbolic, Ux, P, Q, Rs, Matrix->SMPkluMatrix->KLUmatrixCommon) ;

        nSwap = PermutationParity (P, Matrix->SMPkluMatrix->KLUmatrixN)
              ^ PermutationParity (Q, Matrix->SMPkluMatrix->KLUmatrixN) ;

        /* det(A) = sign(P)*sign(Q) * prod(Udiag[k] * Rs[k]) -- see the complex
         * branch.  The previous code (a) never reset I, so this loop NEVER RAN
         * (the parity for-loops above had left I == Size and the determinant
         * came out as +/-1.0 regardless of the matrix), (b) divided instead of
         * multiplying (copied from Sparse, whose Diag stores reciprocal pivots
         * -- KLU's extract returns the actual pivots), and (c) never wrote
         * *piDeterminant, so SMPcDProd consumed an uninitialized value. */
        I = 0 ;
        while (I < Size)
        {
            *pDeterminant *= (Ux [I] * Rs [I]) ;

	    /* Scale Determinant. */
            if (*pDeterminant != 0.0 && isfinite (*pDeterminant))   /* F5 */
            {
		while (ABS(*pDeterminant) >= 1.0e12)
                {
		    *pDeterminant *= 1.0e-12 ;
                    *pExponent += 12 ;
                }
                while (ABS(*pDeterminant) < 1.0e-12)
                {
		    *pDeterminant *= 1.0e12 ;
                    *pExponent -= 12 ;
                }
            }
            I++ ;
        }

	/* Scale Determinant again, this time to be between 1.0 <= x <
           10.0. */
        if (*pDeterminant != 0.0 && isfinite (*pDeterminant))
        {
	    while (ABS(*pDeterminant) >= 10.0)
            {
		*pDeterminant *= 0.1 ;
                (*pExponent)++ ;
            }
            while (ABS(*pDeterminant) < 1.0)
            {
		*pDeterminant *= 10.0 ;
                (*pExponent)-- ;
            }
        }
        if (nSwap % 2 != 0)
        {
            *pDeterminant = -*pDeterminant ;
        }
    }

    free (P) ;
    free (Q) ;
    free (Ux) ;
    free (Rs) ;
}

/*
 * SMPcProdDiag()
 *    note: obsolete for Spice3d2 and later
 */
int
SMPcProdDiag (SMPmatrix *Matrix, SPcomplex *pMantissa, int *pExponent)
{
    if (Matrix->CKTkluMODE)
    {
        spDeterminant_KLU (Matrix, pExponent, &(pMantissa->real), &(pMantissa->imag)) ;
    } else {
        spDeterminant (Matrix->SPmatrix, pExponent, &(pMantissa->real), &(pMantissa->imag)) ;
    }
    return spError (Matrix->SPmatrix) ;
}

/*
 * SMPcDProd()
 */
int
SMPcDProd (SMPmatrix *Matrix, SPcomplex *pMantissa, int *pExponent)
{
    double	re, im, x, y, z;
    int		p;

    if (Matrix->CKTkluMODE)
    {
        spDeterminant_KLU (Matrix, &p, &re, &im) ;
    } else {
        spDeterminant (Matrix->SPmatrix, &p, &re, &im) ;
    }

#ifndef M_LN2
#define M_LN2   0.69314718055994530942
#endif
#ifndef M_LN10
#define M_LN10  2.30258509299404568402
#endif

#ifdef debug_print
    printf ("Determinant 10: (%20g,%20g)^%d\n", re, im, p) ;
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
    printf (" ** base10 -> base2 int =  %g, frac = %20g\n", x, y) ;
#endif
    z = pow (2.0, y) ;
    re *= z ;
    im *= z ;
#ifdef debug_print
    printf (" ** multiplier = %20g\n", z) ;
#endif

    /* Re-normalize (re or im may be > 2.0 or both < 1.0 */
    if (re != 0.0)
    {
	y = logb (re) ;
	if (im != 0.0)
	    z = logb (im) ;
	else
	    z = 0 ;
    } else if (im != 0.0) {
	z = logb (im) ;
	y = 0 ;
    } else {
	/* Singular */
	/*printf("10 -> singular\n");*/
	y = 0 ;
	z = 0 ;
    }

#ifdef debug_print
    printf (" ** renormalize changes = %g,%g\n", y, z) ;
#endif
    if (y < z)
	y = z ;

    *pExponent = (int)(x + y) ;
    x = scalbn (re, (int) -y) ;
    z = scalbn (im, (int) -y) ;
#ifdef debug_print
    printf (" ** values are: re %g, im %g, y %g, re' %g, im' %g\n", re, im, y, x, z) ;
#endif
    pMantissa->real = scalbn (re, (int) -y) ;
    pMantissa->imag = scalbn (im, (int) -y) ;

#ifdef debug_print
    printf ("Determinant 10->2: (%20g,%20g)^%d\n", pMantissa->real, pMantissa->imag, *pExponent) ;
#endif

    if (Matrix->CKTkluMODE)
    {
        return 0 ;
    } else {
        return spError (Matrix->SPmatrix) ;
    }
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
LoadGmin_CSC (double **diag, unsigned int n, double Gmin)
{
    unsigned int i ;

    if (Gmin != 0.0) {
        for (i = 0 ; i < n ; i++) {
            if (diag [i] != NULL) {
                // Not all the elements on the diagonal are present, when the circuit is parsed
                *(diag [i]) += Gmin ;
            }
        }
    }
}

static void
LoadGmin (SMPmatrix *eMatrix, double Gmin)
{
    MatrixPtr Matrix = eMatrix->SPmatrix ;
    int I ;
    ArrayOfElementPtrs Diag ;
    ElementPtr diag ;

    /* Begin `LoadGmin'. */
    assert (IS_SPARSE (Matrix)) ;

    if (Gmin != 0.0) {
	Diag = Matrix->Diag ;
	for (I = Matrix->Size ; I > 0 ; I--)
        {
	    if ((diag = Diag [I]) != NULL)
		diag->Real += Gmin ;
	}
    }
    return ;
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
SMPfindElt (SMPmatrix *eMatrix, int Row, int Col, int CreateIfMissing)
{
    MatrixPtr Matrix = eMatrix->SPmatrix ;

    if (eMatrix->CKTkluMODE)
    {
        int i ;

        Row = Row - 1 ;
        Col = Col - 1 ;
        if (Col < 0) {
//            printf ("Information: Cannot find an element with row '%d' and column '%d' in the KLU matrix\n", Row, Col) ;
            return NULL ;
        }
        /* F1 deck E: a column beyond N read Ap[Col+1] past the allocation */
        if (Col >= (int) eMatrix->SMPkluMatrix->KLUmatrixN || eMatrix->SMPkluMatrix->KLUmatrixAp == NULL)
            return NULL ;
        for (i = eMatrix->SMPkluMatrix->KLUmatrixAp [Col] ; i < eMatrix->SMPkluMatrix->KLUmatrixAp [Col + 1] ; i++) {
            if (eMatrix->SMPkluMatrix->KLUmatrixAi [i] == Row) {
                if (eMatrix->SMPkluMatrix->KLUmatrixIsComplex == KLUmatrixReal) {
                    return (SMPelement *) &(eMatrix->SMPkluMatrix->KLUmatrixAx [i]) ;
                } else if (eMatrix->SMPkluMatrix->KLUmatrixIsComplex == KLUMatrixComplex) {
                    return (SMPelement *) &(eMatrix->SMPkluMatrix->KLUmatrixAxComplex [2 * i]) ;
                } else {
                    printf ("Information: Cannot find an element with row '%d' and column '%d' in the KLU matrix\n", Row, Col) ;
                    return NULL ;
                }
            }
        }
        return NULL ;
    } else {
        ElementPtr Element ;

        /* Begin `SMPfindElt'. */
        assert (IS_SPARSE (Matrix)) ;
        Row = Matrix->ExtToIntRowMap [Row] ;
        Col = Matrix->ExtToIntColMap [Col] ;
        Element = Matrix->FirstInCol [Col] ;
        Element = spcFindElementInCol (Matrix, &Element, Row, Col, CreateIfMissing) ;
        return (SMPelement *)Element ;
    }
}

/* XXX The following should probably be implemented in spUtils */

/*
 * SMPcZeroCol()
 */
int
SMPcZeroCol (SMPmatrix *eMatrix, int Col)
{
    MatrixPtr Matrix = eMatrix->SPmatrix ;
    ElementPtr	Element ;

    if (eMatrix->CKTkluMODE)
    {
        int i ;
        if (Col < 1)            /* ground / invalid column: nothing to zero (Ap[Col-1] would be Ap[-1]) */
            return 0 ;
        for (i = eMatrix->SMPkluMatrix->KLUmatrixAp [Col - 1] ; i < eMatrix->SMPkluMatrix->KLUmatrixAp [Col] ; i++)
        {
            eMatrix->SMPkluMatrix->KLUmatrixAxComplex [2 * i] = 0 ;
            eMatrix->SMPkluMatrix->KLUmatrixAxComplex [2 * i + 1] = 0 ;
        }
        return 0 ;
    } else {
        Col = Matrix->ExtToIntColMap [Col] ;
        for (Element = Matrix->FirstInCol [Col] ; Element != NULL ; Element = Element->NextInCol)
        {
            Element->Real = 0.0 ;
            Element->Imag = 0.0 ;
        }
        return spError (Matrix) ;
    }
}

/*
 * SMPcAddCol()
 */
int
SMPcAddCol (SMPmatrix *eMatrix, int Accum_Col, int Addend_Col)
{
    if (eMatrix->CKTkluMODE)
    {
        /* Fold column Addend_Col into column Accum_Col (complex values).  KLU's
         * CSC pattern is fixed, so every addend row must already exist in the
         * accumulator column -- CKTpzSetup reserves that union pattern for the
         * balanced (differential) pole-zero output before the COO->CSC
         * conversion.  Rows are sorted within each CSC column, so merge-walk. */
        int *Ap = eMatrix->SMPkluMatrix->KLUmatrixAp ;
        int *Ai = eMatrix->SMPkluMatrix->KLUmatrixAi ;
        double *Ax = eMatrix->SMPkluMatrix->KLUmatrixAxComplex ;
        int acc = Accum_Col - 1 ;
        int add = Addend_Col - 1 ;
        int i, j ;

        j = Ap [acc] ;
        for (i = Ap [add] ; i < Ap [add + 1] ; i++)
        {
            while ((j < Ap [acc + 1]) && (Ai [j] < Ai [i]))
                j++ ;
            if ((j < Ap [acc + 1]) && (Ai [j] == Ai [i])) {
                Ax [2 * j] += Ax [2 * i] ;
                Ax [2 * j + 1] += Ax [2 * i + 1] ;
            } else {
                /* cannot happen once CKTpzSetup reserved the union pattern */
                fprintf (stderr, "Error (SMPcAddCol): KLU pattern lacks element (%d, %d)\n",
                         Ai [i] + 1, Accum_Col) ;
                return 1 ;
            }
        }
        return 0 ;
    } else {
        MatrixPtr Matrix = eMatrix->SPmatrix ;
        ElementPtr	Accum, Addend, *Prev ;

        Accum_Col = Matrix->ExtToIntColMap [Accum_Col] ;
        Addend_Col = Matrix->ExtToIntColMap [Addend_Col] ;

        Addend = Matrix->FirstInCol [Addend_Col] ;
        Prev = &Matrix->FirstInCol [Accum_Col] ;
        Accum = *Prev;

        while (Addend != NULL)
        {
            while (Accum && Accum->Row < Addend->Row)
            {
                Prev = &Accum->NextInCol ;
                Accum = *Prev ;
            }
            if (!Accum || Accum->Row > Addend->Row)
            {
                Accum = spcCreateElement (Matrix, Addend->Row, Accum_Col, Prev, 0) ;
            }
            Accum->Real += Addend->Real ;
            Accum->Imag += Addend->Imag ;
            Addend = Addend->NextInCol ;
        }

        return spError (Matrix) ;
    }
}

/*
 * SMPzeroRow()
 */
int
SMPzeroRow (SMPmatrix *eMatrix, int Row)
{
    MatrixPtr Matrix = eMatrix->SPmatrix ;
    ElementPtr	Element ;

    Row = Matrix->ExtToIntColMap [Row] ;

    if (Matrix->RowsLinked == NO)
	spcLinkRows (Matrix) ;

    if (Matrix->PreviousMatrixWasComplex || Matrix->Complex)
    {
	for (Element = Matrix->FirstInRow[Row] ; Element != NULL; Element = Element->NextInRow)
	{
	    Element->Real = 0.0 ;
	    Element->Imag = 0.0 ;
	}
    } else {
	for (Element = Matrix->FirstInRow [Row] ; Element != NULL ; Element = Element->NextInRow)
	{
	    Element->Real = 0.0 ;
	}
    }

    return spError (Matrix) ;
}

/*
 * SMPconstMult()
 */
void
SMPconstMult (SMPmatrix *Matrix, double constant)
{
    if (Matrix->CKTkluMODE)
    {
        if (Matrix->SMPkluMatrix->KLUmatrixIsComplex)
        {
            klu_z_constant_multiply (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAxComplex,
                                     (int)Matrix->SMPkluMatrix->KLUmatrixN, Matrix->SMPkluMatrix->KLUmatrixCommon, constant) ;
        } else {
            klu_constant_multiply (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAx,
                                   (int)Matrix->SMPkluMatrix->KLUmatrixN, Matrix->SMPkluMatrix->KLUmatrixCommon, constant) ;
        }
    } else {
        spConstMult (Matrix->SPmatrix, constant) ;
    }
}

/*
 * SMPmultiplyAbs() -- Enhancement-568 (R1, operating-point robustness):
 * Out[i] = sum_j |A_ij| * |X_j|, the magnitude of the terms that make up row i of
 * A*X, in the external 1-based indexing SMPmultiply uses.  Enhancement-256's
 * false-convergence guard normalises each row's KCL residual by |(A*X)_i|, which
 * cancels to nothing on a high-gain branch equation (a VCVS of gain 1e6 in unity
 * feedback), so the round-off of million-sized terms read as a hundred-fold
 * tolerance violation and a converged operating point was declined into gmin
 * stepping -- 127 iterations instead of 4 under KLU, and under Sparse too from
 * gain 1e8.  NIiter uses this sum as the row's term traffic: a residual below one
 * part per million of it is the solve's rounding, not a KCL violation, whatever
 * the scale says.
 * The real matrix only (the guard runs in the DC operating point).
 */
void
SMPmultiplyAbs (SMPmatrix *Matrix, double *Out, double *X)
{
    if (Matrix->CKTkluMODE) {
        int *Ap = Matrix->SMPkluMatrix->KLUmatrixAp ;
        int *Ai = Matrix->SMPkluMatrix->KLUmatrixAi ;
        double *Ax = Matrix->SMPkluMatrix->KLUmatrixAx ;
        unsigned int j, n = Matrix->SMPkluMatrix->KLUmatrixN ;
        int p ;
        for (j = 0 ; j <= n ; j++)
            Out [j] = 0.0 ;
        if (Ap == NULL || Ai == NULL || Ax == NULL)
            return ;
        for (j = 0 ; j < n ; j++)
            for (p = Ap [j] ; p < Ap [j + 1] ; p++)
                Out [Ai [p] + 1] += fabs (Ax [p]) * fabs (X [j + 1]) ;
    } else {
        MatrixPtr M = Matrix->SPmatrix ;
        ElementPtr e ;
        int I, J ;
        for (I = 0 ; I <= M->ExtSize ; I++)
            Out [I] = 0.0 ;
        for (J = 1 ; J <= M->Size ; J++)
            for (e = M->FirstInCol [J] ; e != NULL ; e = e->NextInCol)
                Out [M->IntToExtRowMap [e->Row]] += fabs (e->Real) * fabs (X [M->IntToExtColMap [J]]) ;
    }
}

/*
 * SMPmultiply()
 */
void
SMPmultiply (SMPmatrix *Matrix, double *RHS, double *Solution, double *iRHS, double *iSolution)
{
    if (Matrix->CKTkluMODE)
    {
        int *Ap_CSR, *Ai_CSR ;
        double *Ax_CSR ;

        Ap_CSR = (int *) malloc ((size_t)(Matrix->SMPkluMatrix->KLUmatrixN + 1) * sizeof (int)) ;
        Ai_CSR = (int *) malloc ((size_t)Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof (int)) ;

        if (Matrix->SMPkluMatrix->KLUmatrixIsComplex)
        {
            Ax_CSR = (double *) malloc ((size_t)(2 * Matrix->SMPkluMatrix->KLUmatrixNZ) * sizeof (double)) ;
            klu_z_convert_matrix_in_CSR (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAxComplex, Ap_CSR,
                                         Ai_CSR, Ax_CSR, (int)Matrix->SMPkluMatrix->KLUmatrixN, (int)Matrix->SMPkluMatrix->KLUmatrixNZ, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            klu_z_matrix_vector_multiply (Ap_CSR, Ai_CSR, Ax_CSR, RHS, Solution, iRHS, iSolution, NULL, NULL,
                                          (int)Matrix->SMPkluMatrix->KLUmatrixN, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
        } else {
            Ax_CSR = (double *) malloc ((size_t)Matrix->SMPkluMatrix->KLUmatrixNZ * sizeof (double)) ;
            klu_convert_matrix_in_CSR (Matrix->SMPkluMatrix->KLUmatrixAp, Matrix->SMPkluMatrix->KLUmatrixAi, Matrix->SMPkluMatrix->KLUmatrixAx, Ap_CSR, Ai_CSR,
                                       Ax_CSR, (int)Matrix->SMPkluMatrix->KLUmatrixN, (int)Matrix->SMPkluMatrix->KLUmatrixNZ, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            klu_matrix_vector_multiply (Ap_CSR, Ai_CSR, Ax_CSR, RHS, Solution, NULL, NULL,
                                        (int)Matrix->SMPkluMatrix->KLUmatrixN, Matrix->SMPkluMatrix->KLUmatrixCommon) ;
            /* real matrix has no imaginary product (iRHS/iSolution unused here);
             * the former `iSolution = iRHS;` only reassigned a local and did nothing. */
        }

        free (Ap_CSR) ;
        free (Ai_CSR) ;
        free (Ax_CSR) ;
    } else {
        spMultiply (Matrix->SPmatrix, RHS, Solution, iRHS, iSolution) ;
    }
}

