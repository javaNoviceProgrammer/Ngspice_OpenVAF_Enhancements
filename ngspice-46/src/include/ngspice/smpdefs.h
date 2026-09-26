#ifndef ngspice_SMPDEFS_H
#define ngspice_SMPDEFS_H

/* Typedef removed by Francesco Lannutti (2012-02) to create the new SMPmatrix structure */
/*
typedef  struct MatrixFrame     SMPmatrix;
*/
typedef  struct MatrixFrame     MatrixFrame;
typedef  struct MatrixElement  *SMPelement;

/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 2000  AlansFixes
**********/

#include <stdio.h>
#include <math.h>
#include "ngspice/complex.h"

#ifdef KLU
#include "ngspice/klu.h"
#include "ngspice/spmatrix.h"
#endif

/* SMPmatrix structure - Francesco Lannutti (2012-02) */
typedef struct sSMPmatrix {
    MatrixFrame *SPmatrix ;                /* pointer to sparse matrix */

#ifdef KLU
    KLUmatrix *SMPkluMatrix ;              /* KLU Pointer to the KLU Matrix Data Structure (only for CIDER, for the moment) */
    unsigned int CKTkluMODE:1 ;            /* KLU MODE parameter to enable KLU or not from the heuristic */
    #define CKTkluON 1                     /* KLU MODE ON definition */
    #define CKTkluOFF 0                    /* KLU MODE OFF definition */
    double CKTkluMemGrowFactor ;           /* KLU Memory Grow Factor - default = 1.2 */
    int CKTkluOrdering ;                   /* Enhancement-152: 0=AMD, 1=COLAMD        */
    int CKTkluScale ;                      /* Enhancement-152: 0=none, 1=sum, 2=max   */
    int CKTkluBTF ;                        /* Enhancement-152: 1=BTF on, 0=off        */
#endif
    /* Enhancement-736: the first pivot the last SMPreorder / SMPcReorder took
     * at or below pivtol (external row and column, 0 when none) and its
     * magnitude; SMPsmallPivot() reads them, NIsmallPivot() reports them. */
    int SMPsmallPivotRow ;
    int SMPsmallPivotCol ;
    double SMPsmallPivotMag ;
    /* Enhancement-738: under Sparse the diagonal gmin goes to the stamped
     * diagonal of every row, as under KLU -- &Element.Real of the external
     * (e,e) element present before the first factorization, NULL for a row
     * without one (a voltage source's branch); NULL array before the first
     * preorder.  Sparse's Diag[] is by internal index and follows the pivot
     * order, so gmin used to land on the +-1 twins the MNA preorder swapped
     * onto the diagonal and on whatever the Markowitz exchanges put there. */
    double **SMPgminDiag ;
    int SMPgminDiagSize ;
} SMPmatrix ;


#ifdef KLU
void spDeterminant_KLU (SMPmatrix *, int *, double *, double *) ;
void SMPconvertCOOtoCSC (SMPmatrix *) ;

#ifdef CIDER
void SMPsolveKLUforCIDER (SMPmatrix *, double [], double [], double [], double []) ;
int SMPreorderKLUforCIDER (SMPmatrix *) ;
double *SMPmakeEltKLUforCIDER (SMPmatrix *, int, int) ;
void SMPclearKLUforCIDER (SMPmatrix *) ;
void SMPconvertCOOtoCSCKLUforCIDER (SMPmatrix *) ;
void SMPdestroyKLUforCIDER (SMPmatrix *) ;
int SMPnewMatrixKLUforCIDER (SMPmatrix *, int, unsigned int) ;
int SMPluFacKLUforCIDER (SMPmatrix *) ;
void SMPprintKLUforCIDER (SMPmatrix *, char *) ;
#endif

#else
int SMPaddElt (SMPmatrix *, int, int, double) ;
#endif

double * SMPmakeElt( SMPmatrix * , int , int );
void SMPcClear( SMPmatrix *);
void SMPclear( SMPmatrix *);
int SMPcLUfac( SMPmatrix *, double );
int SMPluFac( SMPmatrix *, double , double );
int SMPcReorder( SMPmatrix * , double , double , int *);
int SMPreorder( SMPmatrix * , double , double , double );
int SMPsmallPivot( SMPmatrix *, int *, int *, double * );   /* Enhancement-736: the last reorder's pivot below pivtol, if any */
void SMPcaSolve(SMPmatrix *Matrix, double RHS[], double iRHS[],
		double Spare[], double iSpare[]);
void SMPcSolve( SMPmatrix *, double [], double [], double [], double []);
void SMPsolve( SMPmatrix *, double [], double []);
int SMPmatSize( SMPmatrix *);
void SMPdenseExtractReal(SMPmatrix *Matrix, int n, double *out);
int SMPnewMatrix( SMPmatrix *, int );
void SMPsizeHint( SMPmatrix *, int );                   /* F8: the matrix spans this many unknowns */
int  SMPzeroLines( SMPmatrix *, unsigned char *, unsigned char *, int ); /* Enhancement-571: mark all-zero rows / columns, 1-based external */
int  SMPzeroLine( SMPmatrix * );   /* Enhancement-570: first all-zero row (else column) of the loaded matrix, 1-based external; 0 if none */
void SMPmarkOccupied( SMPmatrix *, unsigned char *, unsigned char *, int ); /* F1/F8, E-569: 1-based unknowns whose row / column has an entry */
double SMPdiagNorm( SMPmatrix * );   /* Enhancement-153: max |diagonal| (pre-factor) */
void SMPdestroy( SMPmatrix *);
int SMPpreOrder( SMPmatrix *);
void SMPprint( SMPmatrix * , char *);
void SMPprintRHS( SMPmatrix * , char *, double*, double*);
void SMPgetError( SMPmatrix *, int *, int *);
int SMPcProdDiag( SMPmatrix *, SPcomplex *, int *);
int SMPcDProd(SMPmatrix *Matrix, SPcomplex *pMantissa, int *pExponent);
SMPelement * SMPfindElt( SMPmatrix *, int , int , int );
int SMPcZeroCol(SMPmatrix *Matrix, int Col);
int SMPcAddCol(SMPmatrix *Matrix, int Accum_Col, int Addend_Col);
int SMPzeroRow(SMPmatrix *Matrix, int Row);
void SMPconstMult(SMPmatrix *, double);
void SMPmultiply(SMPmatrix *, double *, double *, double *, double *);
void SMPmultiplyAbs(SMPmatrix *, double *, double *);   /* Enhancement-568: Out[i] = sum_j |A_ij| |X_j| */

#ifdef CIDER
void SMPcSolveForCIDER (SMPmatrix *, double [], double [], double [], double []) ;
int SMPluFacForCIDER (SMPmatrix *) ;
int SMPnewMatrixForCIDER (SMPmatrix *, int, int) ;
void SMPsolveForCIDER (SMPmatrix *, double [], double []) ;
#endif

#endif

