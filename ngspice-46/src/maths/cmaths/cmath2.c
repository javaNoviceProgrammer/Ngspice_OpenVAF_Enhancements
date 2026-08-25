/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/

/** \file cmath2.c
    \brief functions for the control language parser: norm, uminus, rnd, sunif, sgauss, poisson, exponential, mean, stddev, length, vector, cvector, unitvec, plus, minus, times, mod, max, min, d, avg, floor, ceil, nint

    Routines to do complex mathematical functions. These routines require
    the -lm libraries. We sacrifice a lot of space to be able
    to avoid having to do a seperate call for every vector element,
    but it pays off in time savings.  These routines should never
    allow FPE's to happen.

    Complex functions are called as follows:
     cx_something(data, type, length, &newlength, &newtype),
     and return a char * that is cast to complex or double.
*/


#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/dvec.h"
#include "ngspice/randnumb.h"

#include "cmath.h"
#include "cmath2.h"


static double
cx_max_local(void *data, short int type, int length)
{
    double largest = 0.0;

    if (type == VF_COMPLEX) {
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        for (i = 0; i < length; i++)
            if (largest < cmag(cc[i]))
                largest = cmag(cc[i]);
    } else {
        double *dd = (double *) data;
        int i;

        for (i = 0; i < length; i++)
            if (largest < fabs(dd[i]))
                largest = fabs(dd[i]);
    }
    return largest;
}


/* Normalize the data so that the magnitude of the greatest value is 1. */

void *
cx_norm(void *data, short int type, int length, int *newlength, short int *newtype)
{
    double largest = 0.0;

    largest = cx_max_local(data, type, length);
    if (largest == 0.0) {
        fprintf(cp_err, "Error: can't normalize a 0 vector\n");
        return (NULL);
    }

    *newlength = length;
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;

        for (i = 0; i < length; i++) {
            realpart(c[i]) = realpart(cc[i]) / largest;
            imagpart(c[i]) = imagpart(cc[i]) / largest;
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;

        for (i = 0; i < length; i++)
            d[i] = dd[i] / largest;
        return ((void *) d);
    }
}


void *
cx_uminus(void *data, short int type, int length, int *newlength, short int *newtype)
{
    *newlength = length;
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = - realpart(cc[i]);
            imagpart(c[i]) = - imagpart(cc[i]);
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++)
            d[i] = - dd[i];
        return ((void *) d);
    }
}


/* Enhancement-276: (int)floor(x) is undefined behaviour for x outside int range
 * (rnd(1e30), inf, NaN); clamp to int range (NaN -> 0) before the cast. */
static int
cx_rnd_i(double x)
{
    double f = floor(x);
    if (f != f)                 return 0;    /* NaN */
    if (f >= (double) INT_MAX)  return INT_MAX;
    if (f <= (double) INT_MIN)  return INT_MIN;
    return (int) f;
}

/* random integers drawn from a uniform distribution
 *   data in: integer numbers, their absolut values are used,
 *            maximum is RAND_MAX (32767)
 *   data out: random integers in interval [0, data[i][
 *             standard library function rand() is used
 */

void *
cx_rnd(void *data, short int type, int length, int *newlength, short int *newtype)
{
    *newlength = length;
    checkseed();
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            int j, k;
            j = cx_rnd_i(realpart(cc[i]));   /* Enhancement-276 */
            k = cx_rnd_i(imagpart(cc[i]));
            realpart(c[i]) = j ? rand() % j : 0;
            imagpart(c[i]) = k ? rand() % k : 0;
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++) {
            int j;
            j = cx_rnd_i(dd[i]);             /* Enhancement-276 */
            d[i] = j ? rand() % j : 0;
        }
        return ((void *) d);
    }
}


/* random numbers drawn from a uniform distribution
 *   data out: random numbers in interval [-1, 1[
 */

void *
cx_sunif(void *data, short int type, int length, int *newlength, short int *newtype)
{
    NG_IGNORE(data);

    *newlength = length;
    checkseed();
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = drand();
            imagpart(c[i]) = drand();
        }
        return ((void *) c);
    } else {
        double *d;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++) {
            d[i] = drand();
        }
        return ((void *) d);
    }
}


/* random numbers drawn from a poisson distribution
 *   data in:  lambda
 *   data out: random integers according to poisson distribution,
 *             with lambda given by each vector element
 */

void *
cx_poisson(void *data, short int type, int length, int *newlength, short int *newtype)
{
    *newlength = length;
    checkseed();
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = poisson (realpart(cc[i]));
            imagpart(c[i]) = poisson (imagpart(cc[i]));
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++) {
            d[i] = poisson(dd[i]);
        }
        return ((void *) d);
    }
}


/* random numbers drawn from an exponential distribution
 *   data in:  Mean values
 *   data out: exponentially distributed random numbers,
 *             with mean given by each vector element
 */

void *
cx_exponential(void *data, short int type, int length, int *newlength, short int *newtype)
{
    *newlength = length;
    checkseed();
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = exprand(realpart(cc[i]));
            imagpart(c[i]) = exprand(imagpart(cc[i]));
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++) {
            d[i] = exprand(dd[i]);
        }
        return ((void *) d);
    }
}


/* random numbers drawn from a Gaussian distribution
   mean 0, std dev 1
*/

void *
cx_sgauss(void *data, short int type, int length, int *newlength, short int *newtype)
{
    NG_IGNORE(data);

    *newlength = length;
    checkseed();
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = gauss0();
            imagpart(c[i]) = gauss0();
        }
        return ((void *) c);
    } else {
        double *d;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++) {
            d[i] = gauss1();
        }
        return ((void *) d);
    }
}


/* Compute the avg of a vector.
 * Created by A.M.Roldan 2005-05-21
 */

void *
cx_avg(void *data, short int type, int length, int *newlength, short int *newtype)
{
    double sum_real = 0.0, sum_imag = 0.0;
    int i;

    if (type == VF_REAL) {

        double *d = alloc_d(length);
        double *dd = (double *) data;

        *newtype = VF_REAL;
        *newlength = length;

        for (i = 0; i < length; i++) {
            sum_real += dd[i];
            d[i] = sum_real / ((double) i + 1.0);
        }

        return ((void *) d);

    } else {

        ngcomplex_t *c = alloc_c(length);
        ngcomplex_t *cc = (ngcomplex_t *) data;

        *newtype = VF_COMPLEX;
        *newlength = length;

        for (i = 0; i < length; i++) {
            sum_real += realpart(cc[i]);
            realpart(c[i]) = sum_real / ((double) i + 1.0);

            sum_imag += imagpart(cc[i]);
            imagpart(c[i]) = sum_imag / ((double) i + 1.0);
        }

        return ((void *) c);

    }
}

/* Compute the moving average of a vector.
 * Using three elements ((n-1)/2 + n + (n+1)/2)/2
 * Useful for removing trap ringing.
 */

void*
cx_m3avg(void* data, short int type, int length, int* newlength, short int* newtype)
{
    int i;

    if (type == VF_REAL) {

        double* d = alloc_d(length);
        double* dd = (double*)data;

        int nlen = length - 1;

        *newtype = VF_REAL;
        *newlength = length;

        d[0] = dd[0];

        for (i = 1; i < nlen; i++) {
            d[i] = (dd[i-1] + dd[i+1]) / 4. + dd[i] / 2.;
        }

        d[nlen] = dd[nlen];

        return ((void*)d);

    }
    else {

        ngcomplex_t* c = alloc_c(length);
        ngcomplex_t* cc = (ngcomplex_t*)data;

        int nlen = length - 1;

        *newtype = VF_COMPLEX;
        *newlength = length;

        realpart(c[0]) = realpart(cc[0]);

        for (i = 0; i < length; i++) {
            realpart(c[i]) = (realpart(cc[i - 1]) + realpart(cc[i + 1])) / 4. + realpart(cc[i]) / 2.;
            imagpart(c[i]) = (imagpart(cc[i - 1]) + imagpart(cc[i + 1])) / 4. + imagpart(cc[i]) / 2.;
        }

        realpart(c[nlen]) = realpart(cc[nlen]);
        imagpart(c[nlen]) = imagpart(cc[nlen]);

        return ((void*)c);

    }
}

/* Compute the mean of a vector. */

void *cx_mean(void *data, short int type, int length,
        int *newlength, short int *newtype)
{
    if (length == 0) {
        (void) fprintf(cp_err, "mean calculation requires "
                "at least one element.\n");
        return NULL;
    }

    *newlength = 1;

    if (type == VF_REAL) {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(1);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++)
            *d += dd[i];
        *d /= length;
        return ((void *) d);
    }
    else {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(1);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(*c) += realpart(cc[i]);
            imagpart(*c) += imagpart(cc[i]);
        }
        realpart(*c) /= length;
        imagpart(*c) /= length;
        return ((void *) c);
    }
}


/* Compute the standard deviation of all elements of a vector. */

void *cx_stddev(void *data, short int type, int length,
        int *newlength, short int *newtype)
{
    if (length == 0) {
        (void) fprintf(cp_err, "standard deviation calculation requires "
                "at least one element.\n");
        return NULL;
    }

    *newlength = 1;

    if (type == VF_REAL) {
        double *p_mean = (double *) cx_mean(data, type, length,
                newlength, newtype);
        double mean = *p_mean;
        double *d, sum = 0.0;
        double *dd = (double *) data;

        d = alloc_d(1);
        *newtype = VF_REAL;
        int i;
        for (i = 0; i < length; i++) {
            const double tmp = dd[i] - mean;
            sum += tmp * tmp;
        }

        *d = sqrt(sum / ((double) length - 1.0));
        txfree(p_mean);
        return (void *) d;
    }
    else {
        ngcomplex_t * const p_cmean = (ngcomplex_t *) cx_mean(data, type, length,
                newlength, newtype);
        const ngcomplex_t cmean = *p_cmean;
        const double rmean = realpart(cmean);
        const double imean = imagpart(cmean);
        double *d, sum = 0.0;
        ngcomplex_t *cc = (ngcomplex_t *) data;

        d = alloc_d(1);
        *newtype = VF_REAL;
        int i;
        for (i = 0; i < length; i++) {
            const double a = realpart(cc[i]) - rmean;
            const double b = imagpart(cc[i]) - imean;
            sum += a * a + b * b;
        }
        *d = sqrt(sum / ((double) length - 1.0));
        txfree(p_cmean);
        return (void *) d;
    }
} /* end of function cx_stddev */



void *
cx_length(void *data, short int type, int length, int *newlength, short int *newtype)
{
    double *d;

    NG_IGNORE(data);
    NG_IGNORE(type);

    *newlength = 1;
    *newtype = VF_REAL;
    d = alloc_d(1);
    *d = length;
    return ((void *) d);
}


/* Return a vector from 0 to the magnitude of the argument. Length of the
 * argument is irrelevant.
 */

/* Enhancement-273: a vector-length argument is converted to int with a plain
 * (int) cast, which is undefined behaviour when the value is non-finite or
 * outside int range -- vector(1e30) / unitvec(1e30) then produced a garbage
 * (typically INT_MAX-saturated) length and ran away allocating/filling it.
 * Validate first; on an out-of-range length the caller (apply_func) gets a
 * NULL and reports the error. fabs()/cmag() are >= 0, so one upper check (which
 * also rejects NaN/inf) suffices. */
static int cx_veclen(const double *dd, const ngcomplex_t *cc,
                     short int type, int *ok)
{
    double dl = (type == VF_REAL) ? fabs(*dd) : cmag(*cc);
    if (!(dl <= (double) INT_MAX)) {
        fprintf(cp_err, "Error: vector length argument (%g) is out of range\n", dl);
        *ok = 0;
        return 0;
    }
    *ok = 1;
    return (int) dl;
}

void *
cx_vector(void *data, short int type, int length, int *newlength, short int *newtype)
{
    ngcomplex_t *cc = (ngcomplex_t *) data;
    double *dd = (double *) data;
    int i, len;
    double *d;

    NG_IGNORE(length);

    {
        int ok;
        len = cx_veclen(dd, cc, type, &ok);   /* Enhancement-273 */
        if (!ok)
            return NULL;
    }
    if (len == 0)
        len = 1;
    d = alloc_d(len);
    *newlength = len;
    *newtype = VF_REAL;
    for (i = 0; i < len; i++)
        d[i] = i;
    return ((void *) d);
}

/* Return a complex vector. Argument sets the length of the vector.
The real part ranges from 0 to the magnitude of the argument. The imaginary
part is set to 0.
 */

void*
cx_cvector(void* data, short int type, int length, int* newlength, short int* newtype)
{
    ngcomplex_t* cc = (ngcomplex_t*)data;
    double* dd = (double*)data;
    int i, len;
    ngcomplex_t* d;

    NG_IGNORE(length);

    {
        int ok;
        len = cx_veclen(dd, cc, type, &ok);   /* Enhancement-273 */
        if (!ok)
            return NULL;
    }
    if (len == 0)
        len = 1;
    d = alloc_c(len);
    *newlength = len;
    *newtype = VF_COMPLEX;
    for (i = 0; i < len; i++) {
        realpart(d[i]) = i;
        imagpart(d[i]) = 0;
    }
    return ((void*)d);
}



/* Create a vector of the given length composed of all ones. */

void *
cx_unitvec(void *data, short int type, int length, int *newlength, short int *newtype)
{
    ngcomplex_t *cc = (ngcomplex_t *) data;
    double *dd = (double *) data;
    int i, len;
    double *d;

    NG_IGNORE(length);

    {
        int ok;
        len = cx_veclen(dd, cc, type, &ok);   /* Enhancement-273 */
        if (!ok)
            return NULL;
    }
    if (len == 0)
        len = 1;
    d = alloc_d(len);
    *newlength = len;
    *newtype = VF_REAL;
    for (i = 0; i < len; i++)
        d[i] = 1;
    return ((void *) d);
}


/* Calling methods for these functions are:
 *  cx_something(data1, data2, datatype1, datatype2, length)
 *
 * The length of the two data vectors is always the same, and is the length
 * of the result. The result type is complex if one of the args is
 * complex.
 */

void *
cx_plus(void *data1, void *data2, short int datatype1, short int datatype2, int length)
{
    double *dd1 = (double *) data1;
    double *dd2 = (double *) data2;
    double *d;
    ngcomplex_t *cc1 = (ngcomplex_t *) data1;
    ngcomplex_t *cc2 = (ngcomplex_t *) data2;
    ngcomplex_t *c, c1, c2;
    int i;

    if ((datatype1 == VF_REAL) && (datatype2 == VF_REAL)) {
        d = alloc_d(length);
        for (i = 0; i < length; i++)
            d[i] = dd1[i] + dd2[i];
        return ((void *) d);
    } else {
        c = alloc_c(length);
        for (i = 0; i < length; i++) {
            if (datatype1 == VF_REAL) {
                realpart(c1) = dd1[i];
                imagpart(c1) = 0.0;
            } else {
                c1 = cc1[i];
            }
            if (datatype2 == VF_REAL) {
                realpart(c2) = dd2[i];
                imagpart(c2) = 0.0;
            } else {
                c2 = cc2[i];
            }
            realpart(c[i]) = realpart(c1) + realpart(c2);
            imagpart(c[i]) = imagpart(c1) + imagpart(c2);
        }
        return ((void *) c);
    }
}


void *
cx_minus(void *data1, void *data2, short int datatype1, short int datatype2, int length)
{
    double *dd1 = (double *) data1;
    double *dd2 = (double *) data2;
    double *d;
    ngcomplex_t *cc1 = (ngcomplex_t *) data1;
    ngcomplex_t *cc2 = (ngcomplex_t *) data2;
    ngcomplex_t *c, c1, c2;
    int i;

    if ((datatype1 == VF_REAL) && (datatype2 == VF_REAL)) {
        d = alloc_d(length);
        for (i = 0; i < length; i++)
            d[i] = dd1[i] - dd2[i];
        return ((void *) d);
    } else {
        c = alloc_c(length);
        for (i = 0; i < length; i++) {
            if (datatype1 == VF_REAL) {
                realpart(c1) = dd1[i];
                imagpart(c1) = 0.0;
            } else {
                c1 = cc1[i];
            }
            if (datatype2 == VF_REAL) {
                realpart(c2) = dd2[i];
                imagpart(c2) = 0.0;
            } else {
                c2 = cc2[i];
            }
            realpart(c[i]) = realpart(c1) - realpart(c2);
            imagpart(c[i]) = imagpart(c1) - imagpart(c2);
        }
        return ((void *) c);
    }
}


void *
cx_times(void *data1, void *data2, short int datatype1, short int datatype2, int length)
{
    double *dd1 = (double *) data1;
    double *dd2 = (double *) data2;
    double *d;
    ngcomplex_t *cc1 = (ngcomplex_t *) data1;
    ngcomplex_t *cc2 = (ngcomplex_t *) data2;
    ngcomplex_t *c, c1, c2;
    int i;

    if ((datatype1 == VF_REAL) && (datatype2 == VF_REAL)) {
        d = alloc_d(length);
        for (i = 0; i < length; i++)
            d[i] = dd1[i] * dd2[i];
        return ((void *) d);
    } else {
        c = alloc_c(length);
        for (i = 0; i < length; i++) {
            if (datatype1 == VF_REAL) {
                realpart(c1) = dd1[i];
                imagpart(c1) = 0.0;
            } else {
                c1 = cc1[i];
            }
            if (datatype2 == VF_REAL) {
                realpart(c2) = dd2[i];
                imagpart(c2) = 0.0;
            } else {
                c2 = cc2[i];
            }
            realpart(c[i]) =
                realpart(c1) * realpart(c2) - imagpart(c1) * imagpart(c2);
            imagpart(c[i]) =
                imagpart(c1) * realpart(c2) + realpart(c1) * imagpart(c2);
        }
        return ((void *) c);
    }
}


void *cx_mod(void *data1, void *data2, short int datatype1, short int datatype2,
        int length)
{
    int xrc = 0;
    void *rv;
    double *dd1 = (double *) data1;
    double *dd2 = (double *) data2;

    if ((datatype1 == VF_REAL) && (datatype2 == VF_REAL)) {
        double *d;
        rv = d = alloc_d(length);

        int i;
        for (i = 0; i < length; i++) {
            /* Enhancement-480: `%` is REAL modulo, as `fmod()` computes it and
             * as the other two evaluators in this simulator already did.
             *
             * This used to take `floor(fabs())` of BOTH operands and do an
             * integer `%`, so it discarded the fractional part and the sign of
             * the dividend -- and disagreed with `.param` and a B-source, which
             * both call fmod, on the same written expression:
             *
             *     (0.5) % 3     .param 0.5    let 0      (the value vanished)
             *     (5.5) % 3     .param 2.5    let 2
             *     (-5) % 3      .param -2     let 2
             *
             * The manual lists `%` as "modulo" and gives a SEPARATE operator,
             * `\`, for "integer divide", so integer truncation was never what
             * this one meant. A zero divisor stays an error, as before; the
             * old `>= 1.0` test also rejected every fractional divisor, which
             * `fmod` handles perfectly well. */
            rcheck(fabs(dd1[i]) <= (double) INT_MAX, "mod");
            rcheck(dd2[i] != 0.0 && fabs(dd2[i]) <= (double) INT_MAX, "mod");
            d[i] = fmod(dd1[i], dd2[i]);
        }
    }
    else {
        ngcomplex_t *c, c1, c2;
        ngcomplex_t *cc1 = (ngcomplex_t *) data1;
        ngcomplex_t *cc2 = (ngcomplex_t *) data2;
        rv = c = alloc_c(length);

        int i;
        for (i = 0; i < length; i++) {
            if (datatype1 == VF_REAL) {
                realpart(c1) = dd1[i];
                imagpart(c1) = 0.0;
            }
            else {
                c1 = cc1[i];
            }
            if (datatype2 == VF_REAL) {
                realpart(c2) = dd2[i];
                imagpart(c2) = 0.0;
            } else {
                c2 = cc2[i];
            }
            /* Enhancement-480: real modulo per component -- see the real
             * branch above for why the integer truncation is gone. */
            rcheck(fabs(realpart(c1)) <= (double) INT_MAX, "mod");
            rcheck(fabs(imagpart(c1)) <= (double) INT_MAX, "mod");
            rcheck(realpart(c2) != 0.0 && fabs(realpart(c2)) <= (double) INT_MAX, "mod");
            rcheck(imagpart(c2) != 0.0 && fabs(imagpart(c2)) <= (double) INT_MAX, "mod");
            realpart(c[i]) = fmod(realpart(c1), realpart(c2));
            imagpart(c[i]) = fmod(imagpart(c1), imagpart(c2));
        }
    }

EXITPOINT:
    if (xrc != 0) { /* Free resources on error */
        txfree(rv);
        rv = NULL;
    }

    return rv;
} /* end of function cx_mod */



/* Routoure JM : Compute the max of a vector. */

void *cx_max(void *data, short int type, int length,
        int *newlength, short int *newtype)
{
    if (length == 0) {
        (void) fprintf(cp_err, "maximum calculation requires "
                "at least one element.\n");
        return NULL;
    }

    *newlength = 1;

    if (type == VF_REAL) {
        double largest = 0.0;
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(1);
        *newtype = VF_REAL;
        largest = dd[0];
        for (i = 1; i < length; i++) {
            const double tmp = dd[i];
            if (largest < tmp) {
                largest = tmp;
            }
        }
        *d = largest;
        return (void *) d;
    }
    else {
        double largest_real = 0.0;
        double largest_complex = 0.0;
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(1);
        *newtype = VF_COMPLEX;
        largest_real = realpart(*cc);
        largest_complex = imagpart(*cc);
        for (i = 1; i < length; i++) {
            const double tmpr = realpart(cc[i]);
            if (largest_real < tmpr) {
                largest_real = tmpr;
            }
            const double tmpi = imagpart(cc[i]);
            if (largest_complex < tmpi) {
                largest_complex = tmpi;
            }
        }
        realpart(*c) = largest_real;
        imagpart(*c) = largest_complex;
        return (void *) c;
    }
} /* end of function cx_max */



/* Routoure JM : Compute the min of a vector. */

void *cx_min(void *data, short int type, int length,
        int *newlength, short int *newtype)
{
    if (length == 0) {
        (void) fprintf(cp_err, "minimum calculation requires "
                "at least one element.\n");
        return NULL;
    }

    *newlength = 1;

    if (type == VF_REAL) {
        double smallest;
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(1);
        *newtype = VF_REAL;
        smallest = dd[0];
        for (i = 1; i < length; i++) {
            const double tmp = dd[i];
            if (smallest > tmp) {
                smallest = tmp;
            }
        }
        *d = smallest;
        return (void *) d;
    }
    else {
        double smallest_real;
        double smallest_complex;
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(1);
        *newtype = VF_COMPLEX;
        smallest_real = realpart(*cc);
        smallest_complex = imagpart(*cc);
        for (i = 1; i < length; i++) {
            const double tmpr = realpart(cc[i]);
            if (smallest_real > tmpr) {
                smallest_real = tmpr;
            }
            const double tmpi = imagpart(cc[i]);
            if (smallest_complex > tmpi) {
                smallest_complex = tmpi;
            }
        }
        realpart(*c) = smallest_real;
        imagpart(*c) = smallest_complex;
        return (void *) c;
    }
} /* end of function cx_min */


/* Routoure JM : Compute the differential  of a vector. */

void *cx_d(void *data, short int type, int length,
        int *newlength, short int *newtype)
{
    if (length == 0) {
        (void) fprintf(cp_err, "differential calculation requires "
                "at least one element.\n");
        return NULL;
    }

    *newlength = length;

    if (type == VF_REAL) {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        d[0] = dd[1] - dd[0];
        d[length-1] = dd[length-1] - dd[length-2];
        for (i = 1; i < length - 1; i++) {
            d[i] = dd[i+1] - dd[i-1];
        }

        return (void *) d;
    }
    else {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        realpart(*c) = realpart(cc[1]) - realpart(cc[0]);
        imagpart(*c) = imagpart(cc[1]) - imagpart(cc[0]);
        realpart(c[length-1]) = realpart(cc[length-1]) - realpart(cc[length-2]);
        imagpart(c[length-1]) = imagpart(cc[length-1]) - imagpart(cc[length-2]);


        for (i = 1; i < length - 1; i++) {
            realpart(c[i]) = realpart(cc[i+1]) - realpart(cc[i-1]);
            imagpart(c[i]) = imagpart(cc[i+1]) - imagpart(cc[i-1]);
        }

        return (void *) c;
    }
} /* end of function cx_d */


void *
cx_floor(void *data, short int type, int length, int *newlength, short int *newtype)
{
    *newlength = length;
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = floor(realpart(cc[i]));
            imagpart(c[i]) = floor(imagpart(cc[i]));
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++)
            d[i] = floor(dd[i]);
        return ((void *) d);
    }
}


void *
cx_ceil(void *data, short int type, int length, int *newlength, short int *newtype)
{
    *newlength = length;
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = ceil(realpart(cc[i]));
            imagpart(c[i]) = ceil(imagpart(cc[i]));
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++)
            d[i] = ceil(dd[i]);
        return ((void *) d);
    }
}


void *
cx_nint(void *data, short int type, int length, int *newlength, short int *newtype)
{
    *newlength = length;
    if (type == VF_COMPLEX) {
        ngcomplex_t *c;
        ngcomplex_t *cc = (ngcomplex_t *) data;
        int i;

        c = alloc_c(length);
        *newtype = VF_COMPLEX;
        for (i = 0; i < length; i++) {
            realpart(c[i]) = nearbyint(realpart(cc[i]));
            imagpart(c[i]) = nearbyint(imagpart(cc[i]));
        }
        return ((void *) c);
    } else {
        double *d;
        double *dd = (double *) data;
        int i;

        d = alloc_d(length);
        *newtype = VF_REAL;
        for (i = 0; i < length; i++)
            d[i] = nearbyint(dd[i]);
        return ((void *) d);
    }
}
