/**********
Copyright 1991 Regents of the University of California.  All rights reserved.
**********/

#include "ngspice/ngspice.h"
#include <assert.h>
#include <stdint.h>

#ifdef _MSC_VER
#define llabs(x) ((x) < 0 ? -(x) : (x))
#endif


/* From Bruce Dawson, Comparing floating point numbers,
   http://www.cygnus-software.com/papers/comparingfloats/Comparing%20floating%20point%20numbers.htm
   Original this function is named AlmostEqual2sComplement but we leave it to AlmostEqualUlps
   and can leave the code (measure.c, dctran.c) unchanged. The transformation to the 2's complement
   prevent problems around 0.0. 
   One Ulp is equivalent to a maxRelativeError of between 1/4,000,000,000,000,000 and 1/8,000,000,000,000,000.
   Practical: 3 < maxUlps < some hundred's (or thousand's) - depending on numerical requirements. 
*/
bool AlmostEqualUlps(double A, double B, int maxUlps)
{
    int64_t aInt, bInt;
    uint64_t intDiff;

    union {
        double d;
        int64_t i;
    } uA, uB;

    if (A == B)
        return TRUE;

    /* If not - the entire method can not work */
    assert(sizeof(double) == sizeof(int64_t));

    /* Make sure maxUlps is non-negative and small enough that the */
    /* default NAN won't compare as equal to anything. */
    assert(maxUlps > 0 && maxUlps < 4 * 1024 * 1024);

    uA.d = A;
    aInt = uA.i;
    /* Make aInt lexicographically ordered as a twos-complement int */
    if (aInt < 0)
        aInt = INT64_MIN - aInt;

    uB.d = B;
    bInt = uB.i;
    /* Make bInt lexicographically ordered as a twos-complement int */
    if (bInt < 0)
        bInt = INT64_MIN - bInt;

    /* |aInt - bInt|.  The two lexicographic keys span nearly the full int64
     * range, so their signed difference can overflow int64 (undefined
     * behavior; UBSan flags it, and on overflow the wrapped `llabs` result
     * could land <= maxUlps and wrongly report two very different numbers as
     * "almost equal"). Subtract in uint64 -- larger minus smaller -- where the
     * modular wraparound is well defined and the true magnitude of a
     * difference of two int64 values always fits. */
    intDiff = (aInt >= bInt) ? (uint64_t) aInt - (uint64_t) bInt
                             : (uint64_t) bInt - (uint64_t) aInt;

/* printf("A:%e B:%e aInt:%lld bInt:%lld  diff:%llu\n", A, B, aInt, bInt, intDiff); */

    if (intDiff <= (uint64_t) maxUlps)
        return TRUE;
    return FALSE;
}
