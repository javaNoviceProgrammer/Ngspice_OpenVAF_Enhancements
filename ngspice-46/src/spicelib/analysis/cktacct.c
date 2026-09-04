/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/
/*
 */

    /*
     *  CKTacct
     *  get the specified accounting item into 'value' in the 
     *  given circuit 'ckt'.
     */

#include "ngspice/ngspice.h"
#include "ngspice/const.h"
#include "ngspice/optdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/cktdefs.h"
#include "ngspice/spmatrix.h"

#ifdef KLU
#include "ngspice/klu.h"
#endif

/* Francesco Lannutti
 * If ACCT is called before NIinit, the new SMPmatrix structure is not allocated
 * so the control must be performed on the CKTmatrix pointer to the SMPmatrix structure
*/

/* ARGSUSED */
int
CKTacct(CKTcircuit *ckt, JOB *anal, int which, IFvalue *val)
{
    NG_IGNORE(anal);

    switch(which) {
        
    case OPT_EQNS:
        val->iValue = ckt->CKTmaxEqNum;
        break;
    case OPT_ORIGNZ:
	if ( ckt->CKTmatrix != NULL ) {

#ifdef KLU
            if (ckt->CKTkluMODE)
                val->iValue = (int)ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNZ ;
            else
                val->iValue = spOriginalCount (ckt->CKTmatrix->SPmatrix) ;
#else
	    val->iValue = spOriginalCount(ckt->CKTmatrix->SPmatrix);
#endif

	} else {
	    val->iValue = 0;
	}
        break;
    case OPT_FILLNZ:
	if ( ckt->CKTmatrix != NULL ) {
#ifdef KLU
	    if (ckt->CKTmatrix->CKTkluMODE) {
                if (!ckt->CKTmatrix->SMPkluMatrix ||
                    !ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric) {
                    return -1;
                }
                /* 2026-09-04 large-circuit sweep, F3: the factor's size is
                 * not lnz + unz. KLU counts the diagonal in BOTH L (unit,
                 * stored) and U (klu_kernel: "1 added to lnz for diagonal",
                 * and again for unz; a singleton block adds one to each), and
                 * it keeps the entries outside the diagonal blocks of its
                 * block-triangular form in a separate array (`nzoff`). The
                 * old lnz + unz - nz reported the fill-in of a block-
                 * triangular matrix that has none as NEGATIVE ("fill-in
                 * non-zeroes = -1002" on a 1000-stage chain). */
		val->iValue =
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->lnz +
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->unz -
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->n +
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->nzoff -
                    (int)ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNZ ;
	    } else {
		val->iValue = spFillinCount(ckt->CKTmatrix->SPmatrix);
            }
#else
	    val->iValue = spFillinCount(ckt->CKTmatrix->SPmatrix);
#endif
	} else {
	    val->iValue = 0;
	}
        break;
    case OPT_TOTALNZ:
	if ( ckt->CKTmatrix != NULL ) {
#ifdef KLU
	    if (ckt->CKTmatrix->CKTkluMODE && ckt->CKTmatrix->SMPkluMatrix &&
                ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric) {
                /* F3 (see above): one diagonal, plus the off-block entries */
		val->iValue =
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->lnz +
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->unz -
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->n +
                    ckt->CKTmatrix->SMPkluMatrix->KLUmatrixNumeric->nzoff ;
            } else if (ckt->CKTmatrix->CKTkluMODE) {
		val->iValue = 0;
            } else {
                /* F3: in a KLU build the Sparse-mode total read 0 -- the
                 * default solver answered "Circuit total non-zeroes = 0" on
                 * every deck, while the plain build reports the count. */
		val->iValue = spElementCount(ckt->CKTmatrix->SPmatrix);
            }
#else
	    val->iValue = spElementCount(ckt->CKTmatrix->SPmatrix);
#endif
	} else {
	    val->iValue = 0;
	}
        break;
    case OPT_ITERS:
        val->iValue = ckt->CKTstat->STATnumIter;
        break;
    case OPT_TRANIT:
        val->iValue = ckt->CKTstat->STATtranIter;
        break;
    case OPT_TRANCURITER:
        val->iValue = ckt->CKTstat->STATnumIter - ckt->CKTstat->STAToldIter;
        break;
    case OPT_TRANPTS:
        val->iValue = ckt->CKTstat->STATtimePts;
        break;
    case OPT_TRANACCPT:
        val->iValue = ckt->CKTstat->STATaccepted;
        break;
    case OPT_TRANRJCT:
        val->iValue = ckt->CKTstat->STATrejected;
        break;
    case OPT_TOTANALTIME:
        val->rValue = ckt->CKTstat->STATtotAnalTime;
        break;
    case OPT_TRANTIME:
        val->rValue = ckt->CKTstat->STATtranTime;
        break;
    case OPT_ACTIME:
        val->rValue = ckt->CKTstat->STATacTime;
        break;
    case OPT_LOADTIME:
        val->rValue = ckt->CKTstat->STATloadTime;
        break;
    case OPT_SYNCTIME:
        val->rValue = ckt->CKTstat->STATsyncTime;
        break;
    case OPT_REORDTIME:
        val->rValue = ckt->CKTstat->STATreorderTime;
        break;
    case OPT_DECOMP:
        val->rValue = ckt->CKTstat->STATdecompTime;
        break;
    case OPT_SOLVE:
        val->rValue = ckt->CKTstat->STATsolveTime;
        break;
    case OPT_TRANLOAD:
        val->rValue = ckt->CKTstat->STATtranLoadTime;
        break;
    case OPT_TRANSYNC:
        val->rValue = ckt->CKTstat->STATtranSyncTime;
        break;
    case OPT_TRANDECOMP:
        val->rValue = ckt->CKTstat->STATtranDecompTime;
        break;
    case OPT_TRANSOLVE:
        val->rValue = ckt->CKTstat->STATtranSolveTime;
        break;
    case OPT_TRANTRUNC:
        val->rValue = ckt->CKTstat->STATtranTruncTime;
        break;
    case OPT_ACLOAD:
        val->rValue = ckt->CKTstat->STATacLoadTime;
        break;
    case OPT_ACSYNC:
        val->rValue = ckt->CKTstat->STATacSyncTime;
        break;
    case OPT_ACDECOMP:
        val->rValue = ckt->CKTstat->STATacDecompTime;
        break;
    case OPT_ACSOLVE:
        val->rValue = ckt->CKTstat->STATacSolveTime;
        break;
    case OPT_TEMP:
        val->rValue = ckt->CKTtemp - CONSTCtoK;
        break;
    case OPT_TNOM:
        val->rValue = ckt->CKTnomTemp - CONSTCtoK;
        break;
    default:
        return(-1);
    }
    return(0);
}
