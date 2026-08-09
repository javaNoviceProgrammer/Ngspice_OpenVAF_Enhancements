/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include <stdio.h>
#include <ctype.h>
#include "ngspice/inpdefs.h"
#include "inpxx.h"


double
INPevaluate(char **line, int *error, int gobble)
/* gobble: non-zero to gobble rest of token, zero to leave it alone */
{
    char *token;
    char *here;
    double mantis;
    int expo1;
    int expo2;
    int sign;
    int expsgn;
    char *tmpline;

    /* setup */
    tmpline = *line;

    if (gobble) {
        /* MW. INPgetUTok should be called with gobble=0 or it make
         * errors in v(1,2) exp */
        *error = INPgetUTok(line, &token, 0);
        if (*error)
            return (0.0);
    } else {
        token = *line;
        *error = 0;
    }

    mantis = 0;
    expo1 = 0;
    expo2 = 0;
    sign = 1;
    expsgn = 1;

    /* loop through all of the input token */
    here = token;

    if (*here == '+')
        here++;                 /* plus, so do nothing except skip it */
    else if (*here == '-') {    /* minus, so skip it, and change sign */
        here++;
        sign = -1;
    }

    if ((*here == '\0') || ((!(isdigit_c(*here))) && (*here != '.'))) {
        /* number looks like just a sign! */
        *error = 1;
        if (gobble) {
            FREE(token);
            /* back out the 'gettok' operation */
            *line = tmpline;
        }
        return (0);
    }

    while (isdigit_c(*here)) {
        /* digit, so accumulate it. */
        mantis = 10 * mantis + *here - '0';
        here++;
    }

    if (*here == '\0') {
        /* reached the end of token - done. */
        if (gobble) {
            FREE(token);
        } else {
            *line = here;
        }
        return ((double) mantis * sign);
    }

    if (*here == ':') {
        /* ':' is no longer used for subcircuit node numbering
           but is part of ternary function a?b:c
           FIXME : subcircuit models still use ':' for model numbering
           Will this hurt somewhere? */
        if (gobble) {
            FREE(token);
        } else {
            *line = here;
        }
        return ((double) mantis * sign);
    }

    /* after decimal point! */
    if (*here == '.') {
        /* found a decimal point! */
        here++;                 /* skip to next character */

        if (*here == '\0') {
            /* number ends in the decimal point */
            if (gobble) {
                FREE(token);
            } else {
                *line = here;
            }
            return ((double) mantis * sign);
        }

        while (isdigit_c(*here)) {
            /* digit, so accumulate it. */
            mantis = 10 * mantis + *here - '0';
            expo1 = expo1 - 1;
            here++;
        }
    }

    /* now look for "E","e",etc to indicate an exponent */
    if ((*here == 'E') || (*here == 'e') || (*here == 'D') || (*here == 'd')) {

        /* Enhancement-426: remember where the marker was. If no exponent digit
         * follows it, this is not an exponent at all and the marker has to go
         * back to being ordinary trailing text -- src/ngspice.txt:499 says
         * "letters immediately following a number that are not scale factors
         * are ignored". Swallowing it instead let the NEXT letter be read as a
         * scale factor, so `10Emitter` came out as 1.000000e-02 (the `m` taken
         * as milli) and `1em` as 1.000000e-03, both contradicting that rule. */
        char *expmark = here;
        int expdigits = 0;

        /* have an exponent, so skip the e */
        here++;

        /* now look for exponent sign */
        if (*here == '+')
            here++;             /* just skip + */
        else if (*here == '-') {
            here++;             /* skip over minus sign */
            expsgn = -1;        /* and make a negative exponent */
            /* now look for the digits of the exponent */
        }

        while (isdigit_c(*here)) {
            /* Enhancement-426: saturate rather than wrap. expo2 is a plain int,
             * so `1e2147483648` was signed overflow -- undefined behaviour that
             * happened to yield pow(10, INT_MIN) == 0, and `1e21474836480`
             * wrapped to exactly 0 and returned the bare mantissa. Both were
             * silent. 100000 is far outside the double range, so no
             * representable value changes; the digits are still consumed so
             * `here` lands correctly, and the finite-but-huge exponent then
             * trips the representability check below with a real message.
             * Deliberately NOT clamped to 308: that would turn an overflow into
             * a plausible finite answer, the mistake E-361/362 recorded. */
            if (expo2 < 100000)
                expo2 = 10 * expo2 + *here - '0';
            here++;
            expdigits++;
        }

        if (expdigits == 0) {
            here = expmark;     /* not an exponent -- ignorable trailing text */
            expsgn = 1;
            expo2 = 0;
        }
    }

    /* now we have all of the numeric part of the number, time to
     * look for the scale factor (alphabetic)
     */
    switch (*here) {
    case 't':
    case 'T':
        expo1 = expo1 + 12;
        break;
    case 'g':
    case 'G':
        expo1 = expo1 + 9;
        break;
    case 'k':
    case 'K':
        expo1 = expo1 + 3;
        break;
    case 'u':
    case 'U':
        expo1 = expo1 - 6;
        break;
    case 'n':
    case 'N':
        expo1 = expo1 - 9;
        break;
    case 'p':
    case 'P':
        expo1 = expo1 - 12;
        break;
    case 'f':
    case 'F':
        expo1 = expo1 - 15;
        break;
    case 'a':
    case 'A':
        expo1 = expo1 - 18;
        break;
    case 'm':
    case 'M':
        if (((here[1] == 'E') || (here[1] == 'e')) &&
            ((here[2] == 'G') || (here[2] == 'g')))
        {
            expo1 = expo1 + 6;  /* Meg */
        } else if (((here[1] == 'I') || (here[1] == 'i')) &&
                   ((here[2] == 'L') || (here[2] == 'l')))
        {
            expo1 = expo1 - 6;
            mantis *= 25.4;     /* Mil */
        } else {
            expo1 = expo1 - 3;  /* m, milli */
        }
        break;
    default:
        break;
    }

    /* Enhancement-426: a netlist literal that overflows a double was returned
     * as +-inf -- `r1 in a 1e400` made a resistor an open circuit in silence --
     * and `0e400` produced NaN, after which the OP failed five levels away with
     * "Dynamic gmin stepping failed" and printed nan for every node.
     *
     * This product has already ruled on exactly this twice: Enhancement-425
     * refuses `r = 1e309;` in Verilog-A source and Enhancement-396 refuses
     * `1e400` in a $table_model data file, both because a LITERAL that cannot
     * be represented is a mis-written constant. A netlist literal is the same
     * mistake. Underflow stays untouched, as E-425 also decided: `1e-400` is
     * 0.0 and `1e-320` is a subnormal, and both are defined by IEEE 754. */
    {
        double result = sign * mantis *
                        pow(10.0, (double) (expo1 + expsgn * expo2));

        if (!isfinite(result)) {
            fprintf(stderr,
                    "Error: '%s' is not a representable number (overflows to "
                    "%s)\n",
                    token, (result != result) ? "NaN" : "infinity");
            *error = 1;
            /* back out the 'gettok' exactly as the "just a sign" branch above
             * does, so an unrepresentable literal is refused by the same route
             * as any other malformed value at the same call site -- otherwise
             * `1e400` merely warned and fell through to the device's
             * value-not-given default while `abc` and `--5` aborted. */
            if (gobble)
                FREE(token);
            *line = tmpline;
            return (0.0);
        }

        if (gobble) {
            FREE(token);
        } else {
            *line = here;
        }

        return result;
    }
}


/* In addition to fcn INPevaluate() above, allow values like 4k7,
   similar to the RKM code (used by inp2r) */
double
INPevaluateRKM_R(char** line, int* error, int gobble)
/* gobble: non-zero to gobble rest of token, zero to leave it alone */
{
    char* token;
    char* here;
    double mantis;
    double deci;
    int expo1;
    int expo2;
    int expo3;
    int sign;
    int expsgn;
    char* tmpline;
    bool hasmulti = FALSE;

    /* setup */
    tmpline = *line;

    if (gobble) {
        /* MW. INPgetUTok should be called with gobble=0 or it leads to
         * errors in v(1,2) expression */
        *error = INPgetUTok(line, &token, 0);
        if (*error)
            return (0.0);
    }
    else {
        token = *line;
        *error = 0;
    }

    mantis = 0;
    deci = 0;
    expo1 = 0;
    expo2 = 0;
    expo3 = 0;
    sign = 1;
    expsgn = 1;

    /* loop through all of the input token */
    here = token;

    if (*here == '+')
        here++;                 /* plus, so do nothing except skip it */
    else if (*here == '-') {    /* minus, so skip it, and change sign */
        here++;
        sign = -1;
    }

    if ((*here == '\0') || ((!(isdigit_c(*here))) && (*here != '.') && (*here != 'r'))) {
        /* number looks like just a sign! */
        *error = 1;
        if (gobble) {
            FREE(token);
            /* back out the 'gettok' operation */
            *line = tmpline;
        }
        return (0);
    }

    while (isdigit_c(*here)) {
        /* digit, so accumulate it. */
        mantis = 10 * mantis + *here - '0';
        here++;
    }

    if (*here == '\0') {
        /* reached the end of token - done. */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    if (*here == ':') {
        /* ':' is no longer used for subcircuit node numbering
           but is part of ternary function a?b:c
           FIXME : subcircuit models still use ':' for model numbering
           Will this hurt somewhere? */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    /* after decimal point! */
    if (*here == '.') {
        /* found a decimal point! */
        here++;                 /* skip to next character */

        if (*here == '\0') {
            /* number ends in the decimal point */
            if (gobble) {
                FREE(token);
            }
            else {
                *line = here;
            }
            return ((double)mantis * sign);
        }

        while (isdigit_c(*here)) {
            /* digit, so accumulate it. */
            mantis = 10 * mantis + *here - '0';
            expo1 = expo1 - 1;
            here++;
        }
    }

    /* now look for "E","e",etc to indicate an exponent */
    if ((*here == 'E') || (*here == 'e') || (*here == 'D') || (*here == 'd')) {

        /* have an exponent, so skip the e */
        here++;

        /* now look for exponent sign */
        if (*here == '+')
            here++;             /* just skip + */
        else if (*here == '-') {
            here++;             /* skip over minus sign */
            expsgn = -1;        /* and make a negative exponent */
            /* now look for the digits of the exponent */
        }

        while (isdigit_c(*here)) {
            expo2 = 10 * expo2 + *here - '0';
            here++;
        }
    }

    /* now we have all of the numeric part of the number, time to
     * look for the scale factor (alphabetic)
     */
    switch (*here) {
    case 't':
    case 'T':
        expo1 = expo1 + 12;
        hasmulti = TRUE;
        break;
    case 'g':
    case 'G':
        expo1 = expo1 + 9;
        hasmulti = TRUE;
        break;
    case 'k':
    case 'K':
        expo1 = expo1 + 3;
        hasmulti = TRUE;
        break;
    case 'u':
    case 'U':
        expo1 = expo1 - 6;
        hasmulti = TRUE;
        break;
    case 'r':
    case 'R':
        /* This should be R150, i.e. R followed by an integer number */
        {
            int num;
            char ch;
            if (sscanf(here + 1, "%i%c", &num, &ch) == 1) {
                //expo1 = expo1;
                hasmulti = TRUE;
            }
            else {
                *error = 1;
                if (gobble) {
                    FREE(token);
                    /* back out the 'gettok' operation */
                    *line = tmpline;
                }
                return (0);
            }
        }
        break;
    case 'n':
    case 'N':
        expo1 = expo1 - 9;
        hasmulti = TRUE;
        break;
    case 'p':
    case 'P':
        expo1 = expo1 - 12;
        hasmulti = TRUE;
        break;
    case 'm':
    case 'M':
        if (((here[1] == 'E') || (here[1] == 'e')) &&
            ((here[2] == 'G') || (here[2] == 'g')))
        {
            expo1 = expo1 + 6;  /* Meg */
            here += 2;
            hasmulti = TRUE;
        }
        else if (((here[1] == 'I') || (here[1] == 'i')) &&
            ((here[2] == 'L') || (here[2] == 'l')))
        {
            expo1 = expo1 - 6;
            mantis *= 25.4;     /* Mil */
        }
        else {
            expo1 = expo1 - 3;  /* m, M for milli */
            hasmulti = TRUE;
        }
        break;
    case 'l':
    case 'L':
        expo1 = expo1 - 3;  /* m, milli */
        hasmulti = TRUE;
        break;
    default:
        break;
    }

    /* read a digit after multiplier */
    if (hasmulti) {
        here++;
        while (isdigit_c(*here)) {
            deci = 10 * deci + *here - '0';
            expo3 = expo3 - 1;
            here++;
        }
        mantis = mantis + deci * pow(10.0, (double)expo3);
    }

    if (gobble) {
        FREE(token);
    }
    else {
        *line = here;
    }

    return (sign * mantis *
        pow(10.0, (double)(expo1 + expsgn * expo2)));
}

/* In addition to fcn INPevaluate() above, allow values like 4k7,
   similar to the RKM code (used by inp2r) */
double
INPevaluateRKM_C(char** line, int* error, int gobble)
/* gobble: non-zero to gobble rest of token, zero to leave it alone */
{
    char* token;
    char* here;
    double mantis;
    double deci;
    int expo1;
    int expo2;
    int expo3;
    int sign;
    int expsgn;
    char* tmpline;
    bool hasmulti = FALSE;

    /* setup */
    tmpline = *line;

    if (gobble) {
        /* MW. INPgetUTok should be called with gobble=0 or it make
         * errors in v(1,2) exp */
        *error = INPgetUTok(line, &token, 0);
        if (*error)
            return (0.0);
    }
    else {
        token = *line;
        *error = 0;
    }

    mantis = 0;
    deci = 0;
    expo1 = 0;
    expo2 = 0;
    expo3 = 0;
    sign = 1;
    expsgn = 1;

    /* loop through all of the input token */
    here = token;

    if (*here == '+')
        here++;                 /* plus, so do nothing except skip it */
    else if (*here == '-') {    /* minus, so skip it, and change sign */
        here++;
        sign = -1;
    }

    if ((*here == '\0') || ((!(isdigit_c(*here))) && (*here != '.') && (*here != 'r'))) {
        /* number looks like just a sign! */
        *error = 1;
        if (gobble) {
            FREE(token);
            /* back out the 'gettok' operation */
            *line = tmpline;
        }
        return (0);
    }

    while (isdigit_c(*here)) {
        /* digit, so accumulate it. */
        mantis = 10 * mantis + *here - '0';
        here++;
    }

    if (*here == '\0') {
        /* reached the end of token - done. */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    if (*here == ':') {
        /* ':' is no longer used for subcircuit node numbering
           but is part of ternary function a?b:c
           FIXME : subcircuit models still use ':' for model numbering
           Will this hurt somewhere? */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    /* after decimal point! */
    if (*here == '.') {
        /* found a decimal point! */
        here++;                 /* skip to next character */

        if (*here == '\0') {
            /* number ends in the decimal point */
            if (gobble) {
                FREE(token);
            }
            else {
                *line = here;
            }
            return ((double)mantis * sign);
        }

        while (isdigit_c(*here)) {
            /* digit, so accumulate it. */
            mantis = 10 * mantis + *here - '0';
            expo1 = expo1 - 1;
            here++;
        }
    }

    /* now look for "E","e",etc to indicate an exponent */
    if ((*here == 'E') || (*here == 'e') || (*here == 'D') || (*here == 'd')) {

        /* have an exponent, so skip the e */
        here++;

        /* now look for exponent sign */
        if (*here == '+')
            here++;             /* just skip + */
        else if (*here == '-') {
            here++;             /* skip over minus sign */
            expsgn = -1;        /* and make a negative exponent */
            /* now look for the digits of the exponent */
        }

        while (isdigit_c(*here)) {
            expo2 = 10 * expo2 + *here - '0';
            here++;
        }
    }

    /* now we have all of the numeric part of the number, time to
     * look for the scale factor (alphabetic)
     */
    switch (*here) {
    case 't':
    case 'T':
        expo1 = expo1 + 12;
        hasmulti = TRUE;
        break;
    case 'g':
    case 'G':
        expo1 = expo1 + 9;
        hasmulti = TRUE;
        break;
    case 'k':
    case 'K':
        expo1 = expo1 + 3;
        hasmulti = TRUE;
        break;
    case 'u':
    case 'U':
        expo1 = expo1 - 6;
        hasmulti = TRUE;
        break;
    case 'r':
    case 'R':

        //expo1 = expo1;
        hasmulti = TRUE;
        break;
    case 'n':
    case 'N':
        expo1 = expo1 - 9;
        hasmulti = TRUE;
        break;
    case 'p':
    case 'P':
        expo1 = expo1 - 12;
        hasmulti = TRUE;
        break;
    case 'f':
    case 'F':
        expo1 = expo1 - 15;
        hasmulti = TRUE;
        break;
    case 'a':
    case 'A':
        expo1 = expo1 - 18;
        break;
    case 'm':
    case 'M':
        if (((here[1] == 'E') || (here[1] == 'e')) &&
            ((here[2] == 'G') || (here[2] == 'g')))
        {
            expo1 = expo1 + 6;  /* Meg */
            here += 2;
            hasmulti = TRUE;
        }
        else if (((here[1] == 'I') || (here[1] == 'i')) &&
            ((here[2] == 'L') || (here[2] == 'l')))
        {
            expo1 = expo1 - 6;
            mantis *= 25.4;     /* Mil */
        }
        else {
            expo1 = expo1 - 3;  /* Meg as well */
            hasmulti = TRUE;
        }
        break;
    case 'l':
    case 'L':
        expo1 = expo1 - 3;  /* m, milli */
        hasmulti = TRUE;
        break;
    default:
        break;
    }

    /* read a digit after multiplier */
    if (hasmulti) {
        here++;
        while (isdigit_c(*here)) {
            deci = 10 * deci + *here - '0';
            expo3 = expo3 - 1;
            here++;
        }
        mantis = mantis + deci * pow(10.0, (double)expo3);
    }

    if (gobble) {
        FREE(token);
    }
    else {
        *line = here;
    }

    return (sign * mantis *
        pow(10.0, (double)(expo1 + expsgn * expo2)));
}

/* In addition to fcn INPevaluate() above, allow values like 4k7,
   similar to the RKM code (used by inp2l) */
double
INPevaluateRKM_L(char** line, int* error, int gobble)
/* gobble: non-zero to gobble rest of token, zero to leave it alone */
{
    char* token;
    char* here;
    double mantis;
    double deci;
    int expo1;
    int expo2;
    int expo3;
    int sign;
    int expsgn;
    char* tmpline;
    bool hasmulti = FALSE;

    /* setup */
    tmpline = *line;

    if (gobble) {
        /* MW. INPgetUTok should be called with gobble=0 or it make
         * errors in v(1,2) exp */
        *error = INPgetUTok(line, &token, 0);
        if (*error)
            return (0.0);
    }
    else {
        token = *line;
        *error = 0;
    }

    mantis = 0;
    deci = 0;
    expo1 = 0;
    expo2 = 0;
    expo3 = 0;
    sign = 1;
    expsgn = 1;

    /* loop through all of the input token */
    here = token;

    if (*here == '+')
        here++;                 /* plus, so do nothing except skip it */
    else if (*here == '-') {    /* minus, so skip it, and change sign */
        here++;
        sign = -1;
    }

    if ((*here == '\0') || ((!(isdigit_c(*here))) && (*here != '.') && (*here != 'r'))) {
        /* number looks like just a sign! */
        *error = 1;
        if (gobble) {
            FREE(token);
            /* back out the 'gettok' operation */
            *line = tmpline;
        }
        return (0);
    }

    while (isdigit_c(*here)) {
        /* digit, so accumulate it. */
        mantis = 10 * mantis + *here - '0';
        here++;
    }

    if (*here == '\0') {
        /* reached the end of token - done. */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    if (*here == ':') {
        /* ':' is no longer used for subcircuit node numbering
           but is part of ternary function a?b:c
           FIXME : subcircuit models still use ':' for model numbering
           Will this hurt somewhere? */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    /* after decimal point! */
    if (*here == '.') {
        /* found a decimal point! */
        here++;                 /* skip to next character */

        if (*here == '\0') {
            /* number ends in the decimal point */
            if (gobble) {
                FREE(token);
            }
            else {
                *line = here;
            }
            return ((double)mantis * sign);
        }

        while (isdigit_c(*here)) {
            /* digit, so accumulate it. */
            mantis = 10 * mantis + *here - '0';
            expo1 = expo1 - 1;
            here++;
        }
    }

    /* now look for "E","e",etc to indicate an exponent */
    if ((*here == 'E') || (*here == 'e') || (*here == 'D') || (*here == 'd')) {

        /* have an exponent, so skip the e */
        here++;

        /* now look for exponent sign */
        if (*here == '+')
            here++;             /* just skip + */
        else if (*here == '-') {
            here++;             /* skip over minus sign */
            expsgn = -1;        /* and make a negative exponent */
            /* now look for the digits of the exponent */
        }

        while (isdigit_c(*here)) {
            expo2 = 10 * expo2 + *here - '0';
            here++;
        }
    }

    /* now we have all of the numeric part of the number, time to
     * look for the scale factor (alphabetic)
     */
    switch (*here) {
    case 't':
    case 'T':
        expo1 = expo1 + 12;
        hasmulti = TRUE;
        break;
    case 'g':
    case 'G':
        expo1 = expo1 + 9;
        hasmulti = TRUE;
        break;
    case 'k':
    case 'K':
        expo1 = expo1 + 3;
        hasmulti = TRUE;
        break;
    case 'u':
    case 'U':
        expo1 = expo1 - 6;
        hasmulti = TRUE;
        break;
    case 'r':
    case 'R':

        //expo1 = expo1;
        hasmulti = TRUE;
        break;
    case 'n':
    case 'N':
        expo1 = expo1 - 9;
        hasmulti = TRUE;
        break;
    case 'p':
    case 'P':
        expo1 = expo1 - 12;
        hasmulti = TRUE;
        break;
    case 'f':
    case 'F':
        expo1 = expo1 - 15;
        hasmulti = TRUE;
        break;
    case 'a':
    case 'A':
        expo1 = expo1 - 18;
        break;
    case 'm':
    case 'M':
        if (((here[1] == 'E') || (here[1] == 'e')) &&
            ((here[2] == 'G') || (here[2] == 'g')))
        {
            expo1 = expo1 + 6;  /* Meg */
            here += 2;
            hasmulti = TRUE;
        }
        else if (((here[1] == 'I') || (here[1] == 'i')) &&
            ((here[2] == 'L') || (here[2] == 'l')))
        {
            expo1 = expo1 - 6;
            mantis *= 25.4;     /* Mil */
        }
        else {
            expo1 = expo1 - 3;  /* Meg as well */
            hasmulti = TRUE;
        }
        break;
    case 'l':
    case 'L':
        expo1 = expo1 - 3;  /* m, milli */
        hasmulti = TRUE;
        break;
    default:
        break;
    }

    /* read a digit after multiplier */
    if (hasmulti) {
        here++;
        while (isdigit_c(*here)) {
            deci = 10 * deci + *here - '0';
            expo3 = expo3 - 1;
            here++;
        }
        mantis = mantis + deci * pow(10.0, (double)expo3);
    }

    if (gobble) {
        FREE(token);
    }
    else {
        *line = here;
    }

    return (sign * mantis *
        pow(10.0, (double)(expo1 + expsgn * expo2)));
}


/* This version will move past the scale factor for the rest of the token */
double
INPevaluate2(char** line, int* error, int gobble)
/* gobble: non-zero to gobble rest of token, zero to leave it alone */
{
    char* token;
    char* here;
    double mantis;
    int expo1;
    int expo2;
    int sign;
    int expsgn;
    char* tmpline;

    /* setup */
    tmpline = *line;

    if (gobble) {
        /* MW. INPgetUTok should be called with gobble=0 or it make
         * errors in v(1,2) exp */
        *error = INPgetUTok(line, &token, 0);
        if (*error)
            return (0.0);
    }
    else {
        token = *line;
        *error = 0;
    }

    mantis = 0;
    expo1 = 0;
    expo2 = 0;
    sign = 1;
    expsgn = 1;

    /* loop through all of the input token */
    here = token;

    if (*here == '+')
        here++;                 /* plus, so do nothing except skip it */
    else if (*here == '-') {    /* minus, so skip it, and change sign */
        here++;
        sign = -1;
    }

    if ((*here == '\0') || ((!(isdigit_c(*here))) && (*here != '.'))) {
        /* number looks like just a sign! */
        *error = 1;
        if (gobble) {
            FREE(token);
            /* back out the 'gettok' operation */
            *line = tmpline;
        }
        return (0);
    }

    while (isdigit_c(*here)) {
        /* digit, so accumulate it. */
        mantis = 10 * mantis + *here - '0';
        here++;
    }

    if (*here == '\0') {
        /* reached the end of token - done. */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    if (*here == ':') {
        /* ':' is no longer used for subcircuit node numbering
           but is part of ternary function a?b:c
           FIXME : subcircuit models still use ':' for model numbering
           Will this hurt somewhere? */
        if (gobble) {
            FREE(token);
        }
        else {
            *line = here;
        }
        return ((double)mantis * sign);
    }

    /* after decimal point! */
    if (*here == '.') {
        /* found a decimal point! */
        here++;                 /* skip to next character */

        if (*here == '\0') {
            /* number ends in the decimal point */
            if (gobble) {
                FREE(token);
            }
            else {
                *line = here;
            }
            return ((double)mantis * sign);
        }

        while (isdigit_c(*here)) {
            /* digit, so accumulate it. */
            mantis = 10 * mantis + *here - '0';
            expo1 = expo1 - 1;
            here++;
        }
    }

    /* now look for "E","e",etc to indicate an exponent */
    if ((*here == 'E') || (*here == 'e') || (*here == 'D') || (*here == 'd')) {

        /* have an exponent, so skip the e */
        here++;

        /* now look for exponent sign */
        if (*here == '+')
            here++;             /* just skip + */
        else if (*here == '-') {
            here++;             /* skip over minus sign */
            expsgn = -1;        /* and make a negative exponent */
            /* now look for the digits of the exponent */
        }

        while (isdigit_c(*here)) {
            expo2 = 10 * expo2 + *here - '0';
            here++;
        }
    }

    /* now we have all of the numeric part of the number, time to
     * look for the scale factor (alphabetic)
     */
    switch (*here) {
    case 't':
    case 'T':
        expo1 = expo1 + 12;
        here++;
        break;
    case 'g':
    case 'G':
        expo1 = expo1 + 9;
        here++;
        break;
    case 'k':
    case 'K':
        expo1 = expo1 + 3;
        here++;
        break;
    case 'u':
    case 'U':
        expo1 = expo1 - 6;
        here++;
        break;
    case 'n':
    case 'N':
        expo1 = expo1 - 9;
        here++;
        break;
    case 'p':
    case 'P':
        expo1 = expo1 - 12;
        here++;
        break;
    case 'f':
    case 'F':
        expo1 = expo1 - 15;
        here++;
        break;
    case 'a':
    case 'A':
        expo1 = expo1 - 18;
        here++;
        break;
    case 'm':
    case 'M':
        if (((here[1] == 'E') || (here[1] == 'e')) &&
            ((here[2] == 'G') || (here[2] == 'g')))
        {
            expo1 = expo1 + 6;  /* Meg */
            here += 3;
        }
        else if (((here[1] == 'I') || (here[1] == 'i')) &&
            ((here[2] == 'L') || (here[2] == 'l')))
        {
            expo1 = expo1 - 6;
            mantis *= 25.4;     /* Mil */
            here += 3;
        }
        else {
            expo1 = expo1 - 3;  /* m, milli */
            here++;
        }
        break;
    default:
        break;
    }

    if (gobble) {
        FREE(token);
    }
    else {
        *line = here;
    }

    return (sign * mantis *
        pow(10.0, (double)(expo1 + expsgn * expo2)));
}



