/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1987 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/

/*
 * All the functions used in the B-source parse tree.  These functions return HUGE
 * if their argument is out of range.
 */

#include "ngspice/ngspice.h"
#include <stdio.h>
#include "ngspice/fteext.h"
#include "ngspice/ifsim.h"
#include "ngspice/inpptree.h"
#include "ngspice/cktdefs.h"
#include "inpxx.h"
#include "ngspice/compatmode.h"

double PTfudge_factor;

#define MODULUS(NUM,LIMIT) ((NUM) - ((int) ((NUM) / (LIMIT))) * (LIMIT))

double
PTabs(double arg)
{
    return fabs(arg);
}

double
PTsgn(double arg)
{
    return arg > 0.0 ? 1.0 : arg < 0.0 ? -1.0 : 0.0;
}

double
PTplus(double arg1, double arg2)
{
    return (arg1 + arg2);
}

double
PTminus(double arg1, double arg2)
{
    return (arg1 - arg2);
}

double
PTtimes(double arg1, double arg2)
{
    return (arg1 * arg2);
}

double
PTdivide(double arg1, double arg2)
{
    if (arg2 >= 0.0)
        arg2 += PTfudge_factor;
    else
        arg2 -= PTfudge_factor;

    if (arg2 == 0.0)
        return (HUGE);

    return (arg1 / arg2);
}

/* Enhancement-440: 0 raised to a negative power is +inf, and every OTHER route
 * to a singular value in this file is clamped to HUGE instead -- PTdivide for
 * x/0, PTsqrt for sqrt(negative), PTln/PTlog for log(0), and PTpwr for exactly
 * this case since Enhancement-256. `pow()` and `**` were the two that were not,
 * so `B1 nb 0 v='pow(0,-1)'` put a raw inf on a node: the operating point
 * "converged" and reported v(nb) = inf with no diagnostic, and a transient then
 * carried it through to maximum(v(nb)) = inf.
 *
 * Clamping keeps the Jacobian finite, which is what lets NIiter's
 * false-convergence guard notice the pinned point and reach for gmin or source
 * stepping, exactly as E-256 reasoned for pwr(). */
static double pt_pow_guard(double arg1, double arg2, int *guarded)
{
    *guarded = (arg1 == 0.0 && arg2 < 0.0);
    return *guarded ? HUGE : 0.0;
}

double
PTpower(double arg1, double arg2)
{
    double res;
    int guarded;
    res = pt_pow_guard(arg1, arg2, &guarded);
    if (guarded)
        return res;
    if (newcompat.lt) {
        if (arg1 == 0)
            res = 0;
        else if(arg1 > 0)
            res = pow(arg1, arg2);
        else {
            /* If arg2 is quasi an integer, round it to have pow not fail
               when arg1 is negative. Takes into account the double 
               representation which sometimes differs in the last digit(s). */
            if (AlmostEqualUlps(nearbyint(arg2), arg2, 10))
                res = pow(arg1, round(arg2));
            else
                /* As per LTSPICE specification for ** */
                res = 0;
        }
    }
    else
        res = pow(fabs(arg1), arg2);
    return res;
}

double
PTpowerH(double arg1, double arg2)
{
    double res;
    int guarded;

    res = pt_pow_guard(arg1, arg2, &guarded);   /* Enhancement-440 */
    if (guarded)
        return res;

    if (newcompat.hs) {
        if (arg1 < 0)
            res = pow(arg1, round(arg2));
        else if (arg1 == 0){
            res = 0;
        }
        else
        {
            res = pow(arg1, arg2);
        }
    }
    else if (newcompat.lt) {
        if (arg1 >= 0)
            res = pow(arg1, arg2);
        else {
            /* If arg2 is quasi an integer, round it to have pow not fail
               when arg1 is negative. Takes into account the double
               representation which sometimes differs in the last digit(s). */
            if (AlmostEqualUlps(nearbyint(arg2), arg2, 10))
                res = pow(arg1, round(arg2));
            else
                /* As per LTSPICE specification for ** */
                res = 0;
        }
    }
    else
        res = pow(fabs(arg1), arg2);
    return res;
}


double
PTpwr(double arg1, double arg2)
{
    /* Enhancement-256: pwr(0, negative) = 0^negative is +inf; a raw inf here
       poisons the Newton Jacobian (the .disto/AC/DC derivative of v^b uses
       pwr(v, b-1)), turning the operating-point solve into NaN. Guard it like
       PTdivide (/0 -> HUGE) and PTsqrt (sqrt(neg) -> HUGE) so a singular
       derivative stays FINITE -- then the false-convergence guard in NIiter can
       recognize the pinned point and steer to gmin/source stepping.  (PSPICE
       compat already nudged arg1 by a fudge factor; keep that exact path.) */
    if (arg1 == 0.0 && arg2 < 0.0) {
        if (newcompat.ps)
            arg1 += PTfudge_factor;
        else
            return HUGE;
    }

    if (arg1 < 0.0)
        return (-pow(-arg1, arg2));
    else
        return (pow(arg1, arg2));
}

double
PTmin(double arg1, double arg2)
{
    return arg1 > arg2 ? arg2 : arg1;
}

double
PTmax(double arg1, double arg2)
{
    return arg1 > arg2 ? arg1 : arg2;
}

double
PTacos(double arg)
{
    return (acos(arg));
}

double
PTacosh(double arg)
{
    return (acosh(arg));
}

double
PTasin(double arg)
{
    return (asin(arg));
}

double
PTasinh(double arg)
{
    return (asinh(arg));
}

double
PTatan(double arg)
{
    return (atan(arg));
}

double
PTatanh(double arg)
{
    return (atanh(arg));
}

double
PTustep(double arg)
{
    if (arg < 0.0)
        return 0.0;
    else if (arg > 0.0)
        return 1.0;
    else
        return 0.5; /* Ick! */
}

/* MW. PTcif is like "C" if - 0 for (arg<=0), 1 elsewhere */

double
PTustep2(double arg)
{
    if (arg <= 0.0)
        return 0.0;
    else if (arg <= 1.0)
        return arg;
    else /* if (arg > 1.0) */
        return 1.0;
}

double
PTeq0(double arg)
{
    return (arg == 0.0) ? 1.0 : 0.0;
}

double
PTne0(double arg)
{
    return (arg != 0.0) ? 1.0 : 0.0;
}

double
PTgt0(double arg)
{
    return (arg > 0.0) ? 1.0 : 0.0;
}

double
PTlt0(double arg)
{
    return (arg < 0.0) ? 1.0 : 0.0;
}

double
PTge0(double arg)
{
    return (arg >= 0.0) ? 1.0 : 0.0;
}

double
PTle0(double arg)
{
    return (arg <= 0.0) ? 1.0 : 0.0;
}

double
PTuramp(double arg)
{
    if (arg < 0.0)
        return 0.0;
    else
        return arg;
}

double
PTcos(double arg)
{
    return (cos(MODULUS(arg, 2 * M_PI)));
}

double
PTcosh(double arg)
{
    return (cosh(arg));
}

/* Limit the exp: If arg > EXPARGMAX (arbitrarily selected to 14), continue with linear output,
   if compatmode PSPICE is selected.
   If arg exceeds 227.9559242, output its exp value 1e99. */
double
PTexp(double arg)
{
    if (newcompat.ps && arg > EXPARGMAX)
        return EXPMAX * (arg - EXPARGMAX + 1.);
    else if (arg > 227.9559242)
        return 1e99;
    else
        return (exp(arg));
}

/* If arg < , returning HUGE will lead to an error message.
   If arg == 0, don't bail out, but return an arbitrarily very negative value (-1e99).
   Arg 0 may happen, when starting iteration for op or dc simulation. */
double
PTlog(double arg)
{
    if (arg < 0.0)
        return (HUGE);
    if (arg == 0)
        return -1e99;
    return (log(arg));
}

double
PTlog10(double arg)
{
    if (arg < 0.0)
        return (HUGE);
    if (arg == 0)
        return -1e99;
    return (log10(arg));
}

double
PTsin(double arg)
{
    return (sin(MODULUS(arg, 2 * M_PI)));
}

double
PTsinh(double arg)
{
    return (sinh(arg));
}

double
PTsqrt(double arg)
{
    if (arg < 0.0)
        return (HUGE);
    return (sqrt(arg));
}

double
PTtan(double arg)
{
    return (tan(MODULUS(arg, M_PI)));
}

double
PTtanh(double arg)
{
    return (tanh(arg));
}

double
PTuminus(double arg)
{
    return (- arg);
}

double
PTpwl(double arg, void *data)
{
  struct pwldata { int n; double *vals; } *thing = (struct pwldata *) data;

  double y;

  int k0 = 0;
  int k1 = thing->n/2 - 1;

  /* monotonically increasing abscissa */
  if (thing->vals[0] < thing->vals[2]) {
      while (k1 - k0 > 1) {
          int k = (k0 + k1) / 2;
          if (thing->vals[2 * k] > arg)
              k1 = k;
          else
              k0 = k;
      }
  }
  /* monotonically decreasing abscissa */
  else {
      while (k1 - k0 > 1) {
          int k = (k0 + k1) / 2;
          if (thing->vals[2 * k] < arg)
              k1 = k;
          else
              k0 = k;
      }
  }
  /* interpolate the ordinate */
  y = thing->vals[2*k0+1] +
    (thing->vals[2*k1+1] - thing->vals[2*k0+1]) *
    (arg - thing->vals[2*k0]) / (thing->vals[2*k1] - thing->vals[2*k0]);

  return y;
}

double
PTpwl_derivative(double arg, void *data)
{
  struct pwldata { int n; double *vals; } *thing = (struct pwldata *) data;

  double y;

  int k0 = 0;
  int k1 = thing->n/2 - 1;

  while(k1-k0 > 1) {
    int k = (k0+k1)/2;
    if(thing->vals[2*k] > arg)
      k1 = k;
    else
      k0 = k;
  }

  y =
    (thing->vals[2*k1+1] - thing->vals[2*k0+1]) /
    (thing->vals[2*k1]   - thing->vals[2*k0]);

  return y;
}

double
PTceil(double arg1)
{
    return (ceil(arg1));
}

double
PTfloor(double arg1)
{
    return (floor(arg1));
}

double
PTnint(double arg1)
{
    /* round to "nearest integer",
     *   round half-integers to the nearest even integer
     *   rely on default rounding mode of IEEE 754 to do so
     */
    return nearbyint(arg1);
}


/* Calculate the derivative during a transient simulation.
   If time == 0, return 0.
   If not transient sim, return 0.
   The derivative is then (y2-y1)/(t2-t1).
   */
double
PTddt(double arg, void* data)
{
    struct ddtdata { int n; double* vals; } *thing = (struct ddtdata*)data;
    double y, time;

    CKTcircuit* ckt = ft_curckt->ci_ckt;

    time = ckt->CKTtime;

    if (time == 0) {
        thing->vals[3] = arg;
        return 0;
    }

    if (!(ckt->CKTmode & MODETRAN))
        return 0;

    if (time > thing->vals[0]) {
        thing->vals[4] = thing->vals[2];
        thing->vals[5] = thing->vals[3];
        thing->vals[2] = thing->vals[0];
        thing->vals[3] = thing->vals[1];
        thing->vals[0] = time;
        thing->vals[1] = arg;

/*      // Some less effective smoothing option
        if (thing->vals[2] > 0) {
            thing->vals[6] = 0.5 * ((arg - thing->vals[3]) / (time - thing->vals[2]) + thing->vals[6]);
        }
*/
        if (thing->n > 1) {
            thing->vals[6] = (thing->vals[1] - thing->vals[3]) / (thing->vals[2] - thing->vals[4]);
        }
        else {
            thing->vals[6] = 0;
            thing->vals[3] = arg;
        }
        thing->n += 1;
    }

    y = thing->vals[6];

    return y;
}
