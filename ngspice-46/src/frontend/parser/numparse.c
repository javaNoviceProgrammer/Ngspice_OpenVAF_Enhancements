/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/

/* This routine parses a number.  */
#include <ctype.h>
#include <limits.h>
#include <math.h>

#include "ngspice/ngspice.h"
#include "ngspice/bool.h"
#include "ngspice/ftedefs.h"
#include "numparse.h"


bool ft_strictnumparse = FALSE;


static int get_decimal_number(const char **p_str, double *p_val);


/* Parse a number. This will handle things like 10M, etc... If the number
 * must not end before the end of the string, then whole is TRUE.
 * If whole is FALSE and there is more left to the number, the argument
 * is advanced to the end of the word. Returns -1.
 * if no number can be found or if there are trailing characters when
 * whole is TRUE.
 *
 * If ft_strictnumparse is TRUE, and whole is FALSE, the first of the
 * trailing characters must be a '_'.
 *
 * Return codes
 * +1: String represented an integer number that was converted to a double
 *      but which can be stored as an int without loss of data
 * 0: String represented a non-integer number that was converted to a double
 *      that may not be expressed as an integer.
 * -1: Conversion failure
 */
int ft_numparse(char **p_str, bool whole, double *p_val)
{
    double mant;
    double expo;
    const char *p_cur = *p_str; /* position in string */

    /* Parse the mantissa (or decimal number if no exponent) */
    if (get_decimal_number(&p_cur, &mant) < 0) {
        return -1;
    }

    /* Now look for the scale factor or the exponent (can't have both). */
    switch (*p_cur) {
    case 'e':
    case 'E':
        /* Parse another number. Note that a decimal number such as 1.23
         * is allowed as the exponent */
        ++p_cur;
        if (get_decimal_number(&p_cur, &expo) < 0) {
            expo = 0.0;
            --p_cur; /* The "E" was not part of the number */
        }
        break;
    case 't':
    case 'T':
        expo = 12.0;
        ++p_cur;
        break;
    case 'g':
    case 'G':
        expo = 9.0;
        ++p_cur;
        break;
    case 'k':
    case 'K':
        expo = 3.0;
        ++p_cur;
        break;
    case 'u':
    case 'U':
        expo = -6.0;
        ++p_cur;
        break;
    case 'n':
    case 'N':
        expo = -9.0;
        ++p_cur;
        break;
    case 'p':
    case 'P':
        expo = -12.0;
        ++p_cur;
        break;
    case 'f':
    case 'F':
        expo = -15.0;
        ++p_cur;
        break;
    case 'a':
    case 'A':
        expo = -18.0;
        ++p_cur;
        break;
    case 'm':
    case 'M': {
        char ch_cur;

        /* Can be either m, mil, or meg. */
        if (((ch_cur = p_cur[1]) == 'e' || ch_cur == 'E') &&
                (((ch_cur = p_cur[2]) == 'g') || ch_cur == 'G')) {
            expo = 6.0;
            p_cur += 3;
        }
        else if (((ch_cur = p_cur[1]) == 'i' || ch_cur == 'I') &&
                (((ch_cur = p_cur[2]) == 'l') || ch_cur == 'L')) {
            expo = -6.0;
            mant *= 25.4;
            p_cur += 3;
        }
        else { /* plain m for milli */
            expo = -3.0;
            ++p_cur;
        }
        break;
    }
    default:
        expo = 0.0;
    }

    /* p_cur is now pointing to the fist char after the number */
    {
        /* If whole is true, it must be the end of the string */
        const char ch_cur = *p_cur;
        if (whole && ch_cur != '\0') {
            return -1;
        }

        /* If ft_strictnumparse is true, the first character after the
         * string representing the number, if any, must be '_' */
        if (ft_strictnumparse && ch_cur != '\0' && ch_cur != '_') {
            return -1;
        }
    }

    /* Remove the alpha and '_' characters after the number */
    for ( ; ; ++p_cur) {
        const char ch_cur = *p_cur;
        if (!isalpha(ch_cur) && ch_cur != '_') {
            break;
        }
    }

    /* Return results */
    {
       /* Value of number. Ternary operator used to prevent avoidable
        * calls to pow(). */
       const double val = *p_val = mant *
                (expo == 0.0 ? 1.0 : pow(10.0, expo));
        *p_str = (char *) p_cur; /* updated location in string */

        if (ft_parsedb) { /* diagnostics for parsing the number */
            fprintf(cp_err, "numparse: got %e, left = \"%s\"\n",
                    val, p_cur);
        }

        /* Test if the number can be represented as an integer. The round-trip
         * `(double)(int)val == val` is only valid when `val` is already within
         * int range: casting an out-of-range double to int is undefined
         * behavior (UBSan flags it for any control-language literal >= 2^31,
         * e.g. `let x = 3e9`). Range-check first; a value outside int range is
         * by definition not an int-representable number. The bounds use
         * 2147483648.0 (= 2^31, exactly representable as a double) rather than
         * INT_MAX, which rounds up to 2^31 when converted to double. */
        return val >= -2147483648.0 && val < 2147483648.0 &&
               (double) (int) val == val;
    }
} /* end of function ft_numparse */



/* This function converts the string form of a decimal number at *p_str to
 * its value and returns it in *p_val. The location in *p_str is advanced
 * to the first character after the number if the conversion is OK and
 * is unchanged otherwise.
 *
 * Return codes
 * -1: Conversion failure. *p_val is unchanged
 * 0: Conversion OK. The string was not the representation of an integer
 * +1: Conversion OK. The string was an integer */
static int get_decimal_number(const char **p_str, double *p_val)
{
    double sign = 1.0; /* default sign multiplier if missing is 1.0 */
    const char *p_cur = *p_str;
    char ch_cur = *p_cur; /* 1st char */
    bool f_is_integer = TRUE; /* assume integer */

    /* Test for a sign */
    if (ch_cur == '+') { /* Advance position in string. Sign unchanged */
        ch_cur = *++p_cur;
    }
    else if (ch_cur == '-') { /* Advance position in string. Sign = -1 */
        ch_cur = *++p_cur;
        sign = -1.0;
    }

    /* Ensure string either starts with a digit or a decimal point followed
     * by a digit */
    if ((!isdigit(ch_cur) && ch_cur != '.') ||
            ((ch_cur == '.') && !isdigit_c(p_cur[1]))) {
        return -1;
    }

    /* Parse and compute the number. Assuming 0-9 digits are contiguous and
     * increasing in char representation (true for ASCII and EBCDIC) */
    double val = 0.0;
    for ( ; ; p_cur++) {
        const unsigned int digit =
                (unsigned int) *p_cur - (unsigned int) '0';
        if (digit > 9) { /* not digit */
            break;
        }
        val = val * 10.0 + (double) digit;
    }

    /* Handle fraction, if any */
    if (*p_cur == '.') {
        const char *p0 = ++p_cur; /* start of fraction */
        double numerator = 0.0;

        /* Not an integer expression (even if no fraction after the '.') */
        f_is_integer = FALSE;

        /* Add the fractional part of the number */
        for ( ; ; p_cur++) {
            const unsigned int digit =
                    (unsigned int) *p_cur - (unsigned int) '0';
            if (digit > 9) { /* not digit */
                /* Add fractional part to intergral part from earlier */
                val += numerator * pow(10, (double) (p0 - p_cur));
                break;
            }
            numerator = numerator * 10.0 + (double) digit;
        }
    } /* end of case of fraction */

    /* Return the value and update the position in the string */
    *p_val = sign * val;
    *p_str = p_cur;
    return (int) f_is_integer;
} /* end of function get_decimal_number */





/* ------------------------------------------------------------------------
 * Enhancement-502: validated command arguments.
 *
 * Round 60 swept the commands that produce a REPORT -- emir, eye, reduce,
 * envelope, qpss, hbosc -- and found the same guard in every one of them:
 *
 *     if (x <= 0.0) { refuse; }
 *
 * Every comparison with NaN is false, so that test refuses the wrong value and
 * ADMITS NaN. It is one `!` away from correct, and what walked through it was
 * not harmless: `emir jmax nan` reported "0 segments over Jmax" on a grid with
 * two genuine violations, `reduce nan` reported "26 nodes -> 26 nodes (1.0x)"
 * and wrote a reduced netlist that reduced nothing, `qpss ... maxorder nan`
 * silently dropped every intermodulation product, and `envelope <n> nan <t>`
 * built an internal `tran nan nan 0 nan`, which ngspice refuses -- leaving the
 * matrix unbuilt for a SIGSEGV one call later.
 *
 * These three take the raw token so the diagnostic can name what the user
 * actually typed, and they parse with ft_numparse rather than strtod, because
 * these are SPICE numbers: `-ui 0.5n`, `thick 0.5u`, `jmax 3.5e11` are how the
 * documentation writes them, and a check built on strtod would refuse the
 * documented spelling (Enhancement-501 shipped exactly that mistake and the
 * aging suite caught it).
 * ------------------------------------------------------------------------ */

/* Parse `tok` whole, with SPICE suffixes. 0 on junk or trailing text. */
static int arg_parse(const char *tok, double *out)
{
    char *s = (char *) tok;
    double v = 0.0;

    if (!tok || !*tok)
        return 0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        return 0;
    while (*s == ' ' || *s == '\t')
        s++;
    if (*s)                              /* trailing junk: `5x`, `2e2q` */
        return 0;
    *out = v;
    return 1;
}


/* A number that must be POSITIVE and FINITE. */
int ft_argpos(const char *cmd, const char *what, const char *tok, double *out)
{
    double v;

    if (!arg_parse(tok, &v)) {
        fprintf(cp_err, "%s: %s must be a number, not '%s'\n", cmd, what,
                tok ? tok : "");
        return 0;
    }
    if (!(v > 0.0) || !finite(v)) {       /* NOT `v <= 0.0`: that admits NaN */
        fprintf(cp_err, "%s: %s must be a positive finite number (got %s)\n",
                cmd, what, tok);
        return 0;
    }
    *out = v;
    return 1;
}


/* A number that may be negative or zero but must be FINITE -- a limit, a
 * threshold, a start time. A non-finite one is never exceeded and never
 * reached, so it is indistinguishable from having supplied nothing. */
int ft_argfinite(const char *cmd, const char *what, const char *tok, double *out)
{
    double v;

    if (!arg_parse(tok, &v)) {
        fprintf(cp_err, "%s: %s must be a number, not '%s'\n", cmd, what,
                tok ? tok : "");
        return 0;
    }
    if (!finite(v)) {
        fprintf(cp_err, "%s: %s must be finite (got %s)\n", cmd, what, tok);
        return 0;
    }
    *out = v;
    return 1;
}


/* A COUNT: an integer in [lo, hi]. Casting a double to int is undefined when
 * the value is NaN or out of range, so the value is checked BEFORE the cast --
 * `emir top nan` used to land on 1 through that undefined conversion, and
 * `compose lin=1e12` clamped to INT_MAX and really allocated 17 GB. */
int ft_argcount(const char *cmd, const char *what, const char *tok,
                int lo, int hi, int *out)
{
    double v;

    if (!arg_parse(tok, &v)) {
        fprintf(cp_err, "%s: %s must be a number, not '%s'\n", cmd, what,
                tok ? tok : "");
        return 0;
    }
    if (!finite(v) || v < (double) lo || v > (double) hi) {
        fprintf(cp_err, "%s: %s must be a whole number between %d and %d "
                        "(got %s)\n", cmd, what, lo, hi, tok);
        return 0;
    }
    *out = (int) v;
    return 1;
}
