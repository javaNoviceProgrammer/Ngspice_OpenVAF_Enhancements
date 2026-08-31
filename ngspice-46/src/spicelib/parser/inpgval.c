/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include <stdio.h>
#include <limits.h>
#include "ngspice/ifsim.h"
#include "ngspice/inpdefs.h"
#include "ngspice/inpptree.h"
#include "inpxx.h"

extern bool ft_ngdebug;

/* Enhancement-507: whether the SCALAR numeric conversion in the most recent
 * INPgetValue() call failed.
 *
 * The IF_REALVEC path already tests INPevaluate's `error` and refuses the value.
 * The IF_REAL and IF_INTEGER paths took the same `error` and threw it away, so a
 * token INPevaluate cannot parse became 0 and was applied as if the deck had
 * asked for zero. That is reachable from an ordinary netlist: numparam
 * substitutes the TEXT of an expression, and `{1/0}` substitutes `inf`, which is
 * not a number this parser accepts. `.model nm nmos ... kp={1/0}` therefore set
 * kp = 0 -- a transistor that conducts nothing, drain current 1e-12 against
 * 1.25e-4, exit code 0, no diagnostic. Writing `inf` or `nan` DIRECTLY on the
 * same card is refused, and so is `{1/0}` on an instance line or as a built-in
 * device's value; only the model card took it.
 *
 * INPgetValue cannot simply return NULL for these types the way the vector path
 * does: none of its ~40 call sites test for NULL, so that would trade a wrong
 * number for a null dereference. The failure is recorded here instead and the
 * model-card path asks for it, which is the one caller that had no other way to
 * find out. */
static int inp_scalar_value_error;
static int inp_scalar_range_error;   /* Enhancement-509 */
/* LRM-audit (3.4.1): a non-integral value given to an integer parameter is
 * rounded per the LRM rule and applied -- but silently, which hid the case of
 * an untyped Verilog-A parameter whose type froze as integer from its default
 * (`parameter untyped = 1;` given `untyped=2.5` simulated with 3). The round
 * still happens; this flag lets the parameter-applying call sites SAY so. */
static int inp_scalar_round_warn;

int INPlastValueError(void) { return inp_scalar_value_error; }
int INPlastRangeError(void) { return inp_scalar_range_error; }
int INPlastRoundWarn(void) { return inp_scalar_round_warn; }

IFvalue *
INPgetValue(CKTcircuit *ckt, char **line, int type, INPtables *tab)
{
    double *list;
    int *ilist;
    double tmp;
    char *word;
    int error;
    static IFvalue temp;
    INPparseTree *pt;
    char *compline = *line;

    /* make sure we get rid of extra bits in type */
    type &= IF_VARTYPES;
    inp_scalar_value_error = 0;                 /* Enhancement-507 */
    inp_scalar_range_error = 0;                 /* Enhancement-509 */
    inp_scalar_round_warn = 0;
    if (type == IF_INTEGER) {
        tmp = INPevaluate(line, &error, 1);
        inp_scalar_value_error = error;         /* Enhancement-507 */
        /* Enhancement-399: round half AWAY FROM ZERO, not half up.
         *
         * `floor(0.5 + x)` rounds .5 toward +infinity, which is asymmetric:
         * 2.5 -> 3 but -2.5 -> -2, and -0.5 -> 0. That disagreed with the
         * conversion Verilog-A performs INSIDE a model for the very same value
         * -- assigning -2.5 to an integer variable yields -3 there, per the
         * LRM's round-half-away-from-zero rule -- so an integer model parameter
         * took a different value depending on whether it was supplied from the
         * netlist or computed in the model. Every negative half-boundary
         * disagreed (-0.5, -1.5, -2.5, -3.5); positives always agreed.
         *
         * `round()` is exactly the LRM rule and fixes the disagreement.
         *
         * This is a GENERIC parser path: it converts the integer parameters of
         * every device, not just OSDI ones. The two forms differ ONLY at exact
         * negative half-integers, which no built-in device uses as a meaningful
         * parameter value, and where the old result was the surprising one.
         */
        /* Enhancement-509: a value that does not FIT an integer parameter.
         *
         * `(int) round(tmp)` is undefined behaviour once the rounded value is
         * outside the integer range; on this target it saturates, so a model
         * card saying `n=1e300` silently applied 2147483647 -- 291 orders of
         * magnitude from what was written, with no diagnostic.
         *
         * The saturation also happened BEFORE the parameter's own range check,
         * which is what made it dangerous rather than merely surprising: a
         * parameter declared `from [0:2147483647]` -- the idiomatic way to say
         * "any non-negative integer" -- accepted 1e300, because the clamped
         * value landed exactly on the upper bound and passed. `n=200` against
         * `[0:100]` was refused correctly the whole time; only the values that
         * overflowed slipped through, and those are the absurd ones.
         *
         * Flag it instead, the same way Enhancement-507 flags a `{...}` that
         * evaluates non-finite: the model-card path reports it and keeps the
         * parameter's default rather than applying a fabricated number. The
         * comparison is written so that a NaN fails it too.
         */
        {
            double rounded = round(tmp);
            if (rounded >= (double) INT_MIN && rounded <= (double) INT_MAX) {
                temp.iValue = (int) rounded;
                if (rounded != tmp)
                    inp_scalar_round_warn = 1;
            } else {
                inp_scalar_range_error = 1;
                temp.iValue = 0;
            }
        }
        /* printf(" returning integer value %d\n",temp.iValue); */
    } else if (type == IF_REAL) {
        temp.rValue = INPevaluate(line, &error, 1);
        inp_scalar_value_error = error;         /* Enhancement-507 */
        /* printf(" returning real value %e\n",temp.rValue); */
    } else if (type == IF_REALVEC) {
        /* read until error occurs. If error, and first
           character of remaining line is ')', everything is o.k.
           If first token is already in error, return NULL.*/
        temp.v.numValue = 0;
        list = TMALLOC(double, 1);
        tmp = INPevaluate(line, &error, 1);
        if (error) {
            if(ft_ngdebug)
                fprintf(stderr, "\nError: Could not read parameter in front of\n    %s\n", *line);
            tfree(list);
            return NULL;
        }
        while (error == 0) {
            /* printf(" returning vector value %g\n",tmp); */
            temp.v.numValue++;
            list = TREALLOC(double, list, temp.v.numValue);
            list[temp.v.numValue - 1] = tmp;
            tmp = INPevaluate(line, &error, 1);
        }
        if (error && ft_ngdebug && !eq(*line, "") && !prefix(")", *line) &&
            temp.v.numValue > 1) {
            fprintf(stderr, "\nWarning: Reading a vector without limiting parens may be dangerous\n%s\nat\n", compline);
            fprintf(stderr, "%*s%s\n", (int)(*line - compline)," ", *line);
        }
        temp.v.vec.rVec = list;
    } else if (type == IF_INTVEC) {
        /* read until error occurs. If error, and first 
           character of remaining line is ')', everything is o.k. 
           If first token is already in error, return NULL.*/
        temp.v.numValue = 0;
        ilist = TMALLOC(int, 1);
        tmp = INPevaluate(line, &error, 1);
        if (error) {
            tfree(ilist);
            return NULL;
        }
        while (error == 0) {
            /* printf(" returning vector value %g\n",tmp); */
            temp.v.numValue++;
            ilist = TREALLOC(int, ilist, temp.v.numValue);
            ilist[temp.v.numValue - 1] = (int) floor(0.5 + tmp);
            tmp = INPevaluate(line, &error, 1);
        }
        if (error && ft_ngdebug && !eq(*line, "") && !prefix(")", *line) &&
            temp.v.numValue > 1) {
            fprintf(stderr, "\nWarning: Reading a vector without limiting parens may be dangerous\n%s\nat\n", compline);
            fprintf(stderr, "%*s%s\n", (int)(*line - compline), " ", *line);
        }
        temp.v.vec.iVec = ilist;
    } else if (type == IF_FLAG) {
        temp.iValue = 1;
    } else if (type == IF_NODE) {
        INPgetNetTok(line, &word, 1);
        INPtermInsert(ckt, &word, tab, &(temp.nValue));
    } else if (type == IF_INSTANCE) {
        INPgetNetTok(line, &word, 1);
        INPinsert(&word, tab);
        temp.uValue = word;
    } else if (type == IF_STRING) {
        INPgetStr(line, &word, 1);
        temp.sValue = word;
    } else if (type == IF_PARSETREE) {
        INPgetTree(line, &pt, ckt, tab);
        if (!pt)
            return NULL;
        temp.tValue = (IFparseTree *) pt;
        /* INPptPrint("Parse tree is: ", temp.tValue); */
    } else {
        /* don't know what type of parameter caller is talking about! */
        return NULL;
    }

    return &temp;
}
