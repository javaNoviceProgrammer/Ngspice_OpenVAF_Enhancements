/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
Modified: 2001 Paolo Nenzi
**********/

/* Paolo Nenzi 2001: printnum  does not returns static data anymore. 
 * It is up to the caller to allocate space for strings.
 */

#include <stdio.h>

#include "ngspice/ngspice.h"
#include "printnum.h"

int cp_numdgt = -1;


static inline int get_num_width(double num)
{
    int n;

    if (cp_numdgt > 1) {
        n = cp_numdgt;
    }
    else {
        n = 6;
    }
    if (num < 0.0 && n > 1) {
        n--;
    }

    return n;
} /* end of function get_num_width */



/* Enhancement-491: the precision that "%.*e" can actually deliver into `size`
 * bytes.
 *
 * `%.*e` writes an optional sign, one leading digit, '.', `n` fraction digits,
 * 'e', an exponent sign and up to three exponent digits, plus the NUL: n + 9 in
 * the worst case. `cp_numdgt` is whatever the user typed and nothing bounded
 * it, so the value became a length for a buffer it had never been measured
 * against. `set numdgt=510` wrote ~519 bytes into the BSIZE_SP buffers every
 * caller of printnum() passes and aborted on the stack guard; `set numdgt=94`
 * did the same to evtprint's 100-byte step_str and trapped. Both are reachable
 * from a plain batch deck, and printnum()'s own comment had recorded the hazard
 * without bounding it.
 *
 * Clamp rather than truncate: snprintf alone would stop mid-number and hand the
 * reader a value that is not the one computed. Beyond DBL_DIG+2 significant
 * digits the extra places are zero padding anyway, so a clamped column is the
 * same number, just narrower. */
int printnum_fit(int n, size_t size)
{
    long room = (long) size - 9;

    if (room < 1)
        room = 1;
    if ((long) n > room)
        n = (int) room;
    return n;
} /* end of function printnum_fit */


/* Say so once, so a wide `print` does not repeat it per value per row. */
static void warn_clamped(int asked, int used)
{
    static int warned = 0;

    if (!warned) {
        warned = 1;
        fprintf(stderr,
                "\nWarning: numdgt = %d does not fit the output field; using %d "
                "digits.\n         Digits beyond about 17 are zero padding -- a "
                "double holds no more.\n\n", asked, used);
    }
}


/* This function writes num to buf, which holds `size` bytes. */
void printnum(char *buf, size_t size, double num)
{
    int want = get_num_width(num);
    int n = printnum_fit(want, size);

    if (n < want)
        warn_clamped(want, n);
    (void) snprintf(buf, size, "%.*e", n, num);
} /* end of function printnum */



/* A DSTRING grows, so this one never overran -- which is why `fourier`,
   `wrdata`, `write`, `display` and `diff` were unaffected while `print` and
   `eprint` crashed. It is bounded to the same width regardless, so the two
   spellings of "print a number" cannot disagree about how wide a column is. */
int printnum_ds(DSTRING *p_ds, double num)
{
    const int n = printnum_fit(get_num_width(num), BSIZE_SP);
    return ds_cat_printf(p_ds, "%.*e", n, num);
} /* end of function printnum_ds */



