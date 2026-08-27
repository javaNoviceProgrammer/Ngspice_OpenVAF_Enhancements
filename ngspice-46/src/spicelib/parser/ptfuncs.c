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

/* Enhancement-491: the range reduction this macro performed was both undefined
 * and less accurate than the libm it fed.
 *
 * `(int)(NUM/LIMIT)` overflows a signed int once |NUM| exceeds 2^31 * 2*pi
 * (~1.35e10), which is undefined behaviour; past that the reduced argument was
 * arbitrary. `sin(1e20)` in a B-source returned +0.9993 where the answer is
 * -0.6453 -- wrong sign, wrong magnitude, no diagnostic. Even inside int range
 * the naive subtraction lost ~1e-7 against libm, which does Payne-Hanek.
 *
 * BOTH other expression evaluators in this simulator were already right:
 * numparam and a Verilog-A model's own sin() each match libm exactly. Only the
 * B-source disagreed, which is precisely what Enhancement-399 forbids -- an
 * expression must not mean different things depending on who computed it. libm
 * reduces correctly for every finite double, so the reduction is simply gone. */

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
/* Enhancement-491: the nudge is a guard against dividing by EXACTLY zero, and
 * it was being applied to every divisor.
 *
 * PTfudge_factor is gmin * 1e-20, so it was not even a fixed perturbation: it
 * scaled with an unrelated convergence option. Adding it to an ordinary small
 * divisor moved the answer by the ratio of the two, silently --
 * `B0 n 0 V=1/1.38064852e-23` (one over Boltzmann's constant, an everyday
 * quantity) came out 42% low under `.option gmin=1e-3` and 88% low under
 * `gmin=1e-2`, while `1/0` returned 1e26, 1e32 or 1e50 depending on gmin alone.
 * A deck's arithmetic must not move because the user reached for a convergence
 * aid.
 *
 * Nudge only the case the guard exists for. A non-zero divisor is now used
 * exactly as written, and an exact zero gets a FIXED epsilon rather than a
 * gmin-derived one, so `1/0` is the same number in every deck. The value keeps
 * the default gmin's 1e-32, so no deck that was already correct changes. */
#define PTDIV_EPS 1.0e-32       /* the historical gmin(1e-12) * 1e-20 */

/* Enhancement-494: the sign of the nudge was chosen from the NUMERATOR, which
 * inverted the sign of the QUOTIENT. Enhancement-491 wrote
 *
 *     arg2 = (arg1 >= 0.0) ? PTDIV_EPS : -PTDIV_EPS;
 *
 * intending to keep the sign of arg1, but a negative arg1 was then divided by a
 * NEGATIVE epsilon, so every x/0 came out POSITIVE: `B0 b0 0 v=v(p)/0` with
 * v(p) = -3 returned +3e+32 instead of -3e+32.
 *
 * A divisor of exactly zero has no sign to recover, so pick one convention and
 * apply it unconditionally: approach zero from the POSITIVE side. The quotient
 * then keeps the sign of the numerator, which is the limit of x/eps as eps->0+
 * and what the E-491 comment above describes. Decks whose numerator is positive
 * -- every case E-491 measured -- are unchanged. */
PTdivide(double arg1, double arg2)
{
    if (arg2 == 0.0)
        arg2 = PTDIV_EPS;

    return (arg1 / arg2);
}

/* Enhancement-440: 0 raised to a negative power is +inf, and `pow()`/`**` were
 * the two routes to a singular value here that did not say so, so
 * `B1 nb 0 v='pow(0,-1)'` put a raw inf on a node: the operating point
 * "converged" and reported v(nb) = inf with no diagnostic, and a transient then
 * carried it through to maximum(v(nb)) = inf.
 *
 * Enhancement-491 corrected what this comment used to claim about the outcome,
 * because the claim did not match the code. It said the other singular routes
 * "clamp to HUGE" and that clamping "keeps the Jacobian finite, which is what
 * lets NIiter reach for gmin or source stepping". Neither is what happens:
 *
 *   - PTeval() in ifeval.c treats a result equal to HUGE as an ERROR FLAG, not
 *     as a value -- it reports "out of range for pow" and returns E_PARMVAL, so
 *     returning HUGE ABORTS the analysis rather than letting it continue. That
 *     is a defensible outcome, and better than the silent inf this replaced,
 *     but it is the opposite of what was written here.
 *   - The routes are not uniform either. PTsqrt(negative) and PTpwr do return
 *     HUGE and so abort. PTln/PTlog return -1e99 for log(0) -- not HUGE -- and
 *     the analysis runs on with that sentinel on the node. PTdivide no longer
 *     returns HUGE at all: E-491 made it nudge only an exact zero, so x/0 is a
 *     large finite number and the run continues.
 *
 * Recorded rather than unified: making log(0) abort, or making pow(0,-1) not
 * abort, would each change the answer a working deck gets today. What was wrong
 * was the description, and a reader trusting it would have drawn exactly the
 * wrong conclusion about which of these keeps a simulation alive. */
static double pt_pow_guard(double arg1, double arg2, int *guarded)
{
    *guarded = (arg1 == 0.0 && arg2 < 0.0);
    return *guarded ? HUGE : 0.0;
}

/* Enhancement-446: the default `**`, `^` and pow() evaluated pow(fabs(x), y),
 * which DROPS THE SIGN of a negative base. `(-2)**3` came out +8, and `(-2)**1`
 * came out +2 -- raising to the first power did not return the base. Odd
 * exponents were wrong and even ones coincided, so it was silent on half the
 * inputs.
 *
 * Everything else in this simulator disagreed with it: `pwr(-2,3)` returns -8
 * (PTpwr below negates explicitly), a Verilog-A model's own pow(-2,3) returns
 * -8, and BOTH the LTspice and HSPICE compatibility branches above preserve the
 * sign. Only PSPICE mode agreed, and there |x|^y is that dialect's documented
 * PWR convention. Enhancement-399's rule applies: an expression must not mean
 * different things depending on whether the netlist or the model computed it.
 *
 * For a negative base the real-valued answer exists only when the exponent is
 * an integer, and there it is returned with its proper sign. When it is not an
 * integer there IS no real result; the historical magnitude is kept rather than
 * returning NaN, because a NaN here poisons the Newton Jacobian -- the same
 * reasoning E-256 and E-440 used for pwr() and pow(0,-1). */
static double pt_pow_default(double arg1, double arg2)
{
    if (arg1 >= 0.0)
        return pow(arg1, arg2);
    if (AlmostEqualUlps(nearbyint(arg2), arg2, 10))
        return pow(arg1, nearbyint(arg2));
    return pow(fabs(arg1), arg2);
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
        res = pt_pow_default(arg1, arg2);   /* Enhancement-446 */
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
        res = pt_pow_default(arg1, arg2);   /* Enhancement-446 */
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
    return (cos(arg));
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
    return (sin(arg));
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
    return (tan(arg));
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
