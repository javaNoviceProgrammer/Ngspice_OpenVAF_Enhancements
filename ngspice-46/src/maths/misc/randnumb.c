/**********
Copyright 2008 Holger Vogt
**********/
/* Care about random numbers
   The seed value is set as random number in main.c, line 746.
   A fixed seed value may be set by 'set rndseed=value'.
*/


/*
	CombLCGTaus()
	Combined Tausworthe & LCG random number generator
	Algorithm has been suggested in: 
	GPUGems 3, Addison Wesley, 2008, Chapter 37.
	It combines a three component Tausworthe generator taus88 
	(see P. L’Ecuyer: "Maximally equidistributed combined Tausworthe
	generators", Mathematics of Computation, 1996, 
	http://www.iro.umontreal.ca/~lecuyer/myftp/papers/tausme.ps )
	and a quick linear congruent generator (LCG), decribed in:
	Press: "Numerical recipes in C", Cambridge, 1992, p. 284.
	Generator has passed the bbattery_SmallCrush(gen) test of the
	TestU01 library from Pierre L’Ecuyer and Richard Simard,
	http://www.iro.umontreal.ca/~simardr/testu01/tu01.html
*/


/* TausSeed creates three start values for Tausworthe state variables.
   Uses rand() from <stdlib.h>, therefore values depend on the value of 
   seed in srand(seed). A constant seed will result in a reproducible
   series of random variates.
   
   Calling sequence:
   srand(seed);
   TausSeed();
   double randvar = CombLCGTaus(void);
*/
//#define HVDEBUG

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/randnumb.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#ifdef _MSC_VER
#include <process.h>
#else
#include <unistd.h>
#endif
#include <stdarg.h>			// var. argumente

/* Tausworthe state variables for double variates*/
static unsigned CombState1 = 129, CombState2 = 130, CombState3 = 131;  
static unsigned CombState4 = 132; /* LCG state variable */ 

/* Tausworthe state variables for integer variates*/
static unsigned CombState5 = 133, CombState6 = 135, CombState7 = 137;  
static unsigned CombState8 = 138; /* LCG state variable */ 

static unsigned TauS(unsigned *state, int C1, int C2, int C3, unsigned m);
static unsigned LGCS(unsigned *state, unsigned A1, unsigned A2);

double CombLCGTaus(void);
float  CombLCGTaus2(void);

void rgauss(double* py1, double* py2);
static bool seedinfo = FALSE;


/* Check if a seed has been set by the command 'set rndseed=value'
   in spinit, .spiceinit or in a .control section
   with integer value > 0. If available, call srand(value).
   rndseed set in main.c to 1, if no 'set rndseed=val' is given.
   Called from functions in cmath2.c.
*/
void checkseed(void)
{
   int newseed;
   static int oldseed;
/*   printf("Enter checkseed()\n"); */
   if (cp_getvar("rndseed", CP_NUM, &newseed, 0)) {
      if ((newseed > 0) && (oldseed != newseed)) {
         srand((unsigned int)newseed);
         TausSeed();
         if (oldseed > 0) /* no printout upon start-up */
             printf("Seed value for random number generator is set to %d\n", newseed);
         oldseed = newseed;
      }
   }
   
}

/* uniform random number generator, interval [-1 .. +1[ */
double drand(void)
{
   return 2.0 * CombLCGTaus() - 1.0;
}


void TausSeed(void)
{    
   /* The Tausworthe initial states should be greater than 128.
      We restrict the values up to 32767. 
      Here we use the standard random functions srand, called in main.c
      upon ngspice startup or later in fcn checkseed(),
      rand() and the maximum return value RAND_MAX*/
   CombState1 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;
   CombState2 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;
   CombState3 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;
   CombState4 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;
   CombState5 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;
   CombState6 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;
   CombState7 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;
   CombState8 = (unsigned int)((double)rand()/(double)RAND_MAX * 32638.) + 129;

#ifdef HVDEBUG
   printf("\nTausworthe Double generator init states: %d, %d, %d, %d\n", 
      CombState1, CombState2, CombState3, CombState4);
   printf("Tausworthe Integer generator init states: %d, %d, %d, %d\n", 
      CombState5, CombState6, CombState7, CombState8);
#endif
}   

static unsigned TauS(unsigned *state, int C1, int C2, int C3, unsigned m)
{
   unsigned b = (((*state << C1) ^ *state) >> C2);
   return *state = (((*state & m) << C3) ^ b);
}

static unsigned LGCS(unsigned *state, unsigned A1, unsigned A2)
{
   return *state = (A1 * *state + A2);
}

/* generate random variates randvar uniformly distributed in 
   [0.0 .. 1.0[ by calls to CombLCGTaus() like:
   double randvar = CombLCGTaus(); 
*/
double CombLCGTaus(void)
{
   return 2.3283064365387e-10 * (
   TauS(&CombState1, 13, 19, 12, 4294967294UL) ^
   TauS(&CombState2, 2, 25, 4, 4294967288UL) ^
   TauS(&CombState3, 3, 11, 17, 4294967280UL) ^
   LGCS(&CombState4, 1664525, 1013904223UL)
   );
}

/* generate random variates randvarint uniformly distributed in 
   [0 .. 4294967296[ (32 bit unsigned int) by calls to CombLCGTausInt() like:
   unsigned int randvarint = CombLCGTausInt(); 
*/   
unsigned int CombLCGTausInt(void)
{
   return (
   TauS(&CombState5, 13, 19, 12, 4294967294UL) ^
   TauS(&CombState6, 2, 25, 4, 4294967288UL) ^
   TauS(&CombState7, 3, 11, 17, 4294967280UL) ^
   LGCS(&CombState8, 1664525, 1013904223UL)
   );
}
  
/* test versions of the generators listed above */
float CombLCGTaus2(void)
{
   unsigned long b;
   b = (((CombState1 << 13) ^ CombState1) >> 19);
   CombState1 = (unsigned int)(((CombState1 & 4294967294UL) << 12) ^ b);
   b = (((CombState2 << 2) ^ CombState2) >> 25);
   CombState2 = (unsigned int)(((CombState2 & 4294967288UL) << 4) ^ b);   
   b = (((CombState3 << 3) ^ CombState3) >> 11);
   CombState3 = (unsigned int)(((CombState3 & 4294967280UL) << 17) ^ b);
   CombState4 = (unsigned int)(1664525 * CombState4 + 1013904223UL);   
   return ((float)(CombState1 ^ CombState2 ^ CombState3 ^ CombState4) *  2.3283064365387e-10f);
}


unsigned int CombLCGTausInt2(void)
{
   unsigned long b;
   b = (((CombState5 << 13) ^ CombState5) >> 19);
   CombState5 = (unsigned int)(((CombState5 & 4294967294UL) << 12) ^ b);
   b = (((CombState6 << 2) ^ CombState6) >> 25);
   CombState6 = (unsigned int)(((CombState6 & 4294967288UL) << 4) ^ b);   
   b = (((CombState7 << 3) ^ CombState7) >> 11);
   CombState7 = (unsigned int)(((CombState7 & 4294967280UL) << 17) ^ b);
   CombState8 = (unsigned int)(1664525 * CombState8 + 1013904223UL);   
   return (CombState5 ^ CombState6 ^ CombState7 ^ CombState8);
}


/***  gauss  ***
 for speed reasons get two values per pass */
double gauss0(void)
{
  static bool gliset = TRUE;
  static double glgset = 0.0;
  double fac,r,v1,v2;
  if (gliset) {
    do {
      v1 = 2.0 * CombLCGTaus() - 1.0;
      v2 = 2.0 * CombLCGTaus() - 1.0;
      r = v1*v1 + v2*v2;
    } while (r >= 1.0);
/*    printf("v1 %f, v2 %f\n", v1, v2); */
    fac = sqrt(-2.0 * log(r) / r);
    glgset = v1 * fac;
    gliset = FALSE;
    return v2 * fac;
  } else {
    gliset = TRUE;
    return glgset;
  }
}


/***  gauss  ***
to be reproducible, we just use one value per pass */
double gauss1(void)
{
    double fac, r, v1, v2;
    do {
        v1 = 2.0 * CombLCGTaus() - 1.0;
        v2 = 2.0 * CombLCGTaus() - 1.0;
        r = v1 * v1 + v2 * v2;
    } while (r >= 1.0);
    /*    printf("v1 %f, v2 %f\n", v1, v2); */
    fac = sqrt(-2.0 * log(r) / r);
    return v2 * fac;
}


/* Polar form of the Box-Muller generator for Gaussian distributed
   random variates.
   Generator will be fed with two uniformly distributed random variates.
   Delivers two values per call
*/

void rgauss(double* py1, double* py2)
{
    double x1, x2, w;

    do {
        x1 = 2.0 * CombLCGTaus() - 1.0;
        x2 = 2.0 * CombLCGTaus() - 1.0;
        w = x1 * x1 + x2 * x2;
    } while ( w >= 1.0 );

     w = sqrt( (-2.0 * log( w ) ) / w );

    *py1 = x1 * w;
    *py2 = x2 * w;
}



/** Code by: Inexpensive
    http://everything2.com/title/Generating+random+numbers+with+a+Poisson+distribution **/
int poisson(double lambda)
{
  int k=0;                          //Counter
  const int max_k = 1000;           //k upper limit
  double p = CombLCGTaus();         //uniform random number
  double P = exp(-lambda);        //probability
  double sum=P;                     //cumulant
  if (sum>=p) return 0;             //done allready
  for (k=1; k<max_k; ++k) {         //Loop over all k:s
    P*=lambda/(double)k;           //Calc next prob
    sum+=P;                         //Increase cumulant
    if (sum>=p) break;              //Leave loop
  }
  return k;                         //return random number
}


/* return an exponentially distributed random number */
double exprand(double mean)
{
    double expval;
    expval = -log(CombLCGTaus()) * mean;
    return expval;
}


/* seed random number generators immediately
* command "setseed"
*   take value of variable rndseed as seed
* command "setseed <n>"
*   seed with number <n>
*/
void
com_sseed(wordlist *wl)
{
    int newseed;

    if (wl == NULL) {
        if (!cp_getvar("rndseed", CP_NUM, &newseed, 0)) {
            newseed = getpid();
            cp_vset("rndseed", CP_NUM, &newseed);
        }
        srand((unsigned int)newseed);
        TausSeed();
    }
    else if ((sscanf(wl->wl_word, " %d ", &newseed) != 1) ||
        (newseed <= 0) || (newseed > INT_MAX))
    {
        fprintf(cp_err,
            "\nWarning: Cannot use %s as seed!\n"
            "    Command 'setseed %s' ignored.\n\n",
            wl->wl_word, wl->wl_word);
        return;
    }
    else {
        srand((unsigned int)newseed);
        TausSeed();
        cp_vset("rndseed", CP_NUM, &newseed);
    }

    if (seedinfo)
        printf("\nSeed value for random number generator is set to %d\n", newseed);
}


void
setseedinfo(void)
{
    seedinfo = TRUE;
}


/* =====================================================================
 * Enhancement-149: Latin-Hypercube (LHS) low-discrepancy Monte Carlo
 * sampling.
 *
 * Plain Monte Carlo draws each random parameter independently from the PRNG,
 * so with a modest number of runs the samples clump and leave gaps, and the
 * estimated mean / yield converges only as 1/sqrt(N). Latin-Hypercube sampling
 * instead partitions every random dimension's [0,1) range into N equal strata
 * and guarantees exactly one sample per stratum (with an independent random
 * permutation across dimensions), which removes the clumping and typically cuts
 * the variance of the estimate substantially for the same N.
 *
 * Integration model. The netlist Monte Carlo idiom is a `reset`-driven loop:
 * each `reset` re-evaluates the `.param` expressions, and the stochastic
 * functions agauss/gauss/aunif/unif/limit (numparam/xpressn.c) draw one value
 * apiece. So within one pass the k-th stochastic call is "dimension k", and each
 * pass is one "sample". mc_sample_advance() (called from the NUPADECKCOPY pass
 * edge in spicenum.c) steps the sample index and rewinds the dimension counter;
 * every draw then returns the stratified value for (dimension, sample).
 *
 * Each dimension's stratum permutation and per-sample jitter are generated
 * lazily on first use, from a splitmix64 seeded by (user seed, dimension), so
 * the whole sequence is reproducible and independent of evaluation order.
 * ===================================================================== */

/* MC_MODE_SSS (Enhancement-150): scaled-sigma importance sampling -- Gaussian
 * .param draws are inflated by `sss_lambda` (fatter tails, so rare failures are
 * sampled often) and each sample carries the likelihood-ratio weight
 * exp(sss_logw) so an unbiased rare-event probability can be recovered. */
enum { MC_MODE_RANDOM = 0, MC_MODE_LHS = 1, MC_MODE_SSS = 2 };

static int      lhs_mode = MC_MODE_RANDOM;
static int      lhs_N = 0;         /* number of samples / strata            */
static int      lhs_sample = -1;   /* current sample index in [0, N)        */
static int      lhs_dim = 0;       /* dimension counter within this sample  */
static unsigned lhs_seed = 1;
static int    **lhs_perm = NULL;   /* [dim][N] stratum permutation          */
static double **lhs_jit = NULL;    /* [dim][N] in-stratum jitter in [0,1)   */
static int      lhs_dim_cap = 0;   /* allocated length of lhs_perm/lhs_jit  */
static double   sss_lambda = 1.0;  /* SSS variance-inflation factor (>1)    */
static double   sss_logw = 0.0;    /* accumulated log importance weight     */

/* splitmix64 -- a tiny, self-contained, reproducible generator used only to
 * build the per-dimension strata, kept independent of the global PRNG state. */
static uint64_t sm_next(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static double sm_unif(uint64_t *s)   /* [0,1) with 53-bit resolution */
{
    return (double)(sm_next(s) >> 11) * (1.0 / 9007199254740992.0);
}

static void lhs_free_tables(void)
{
    int d;
    for (d = 0; d < lhs_dim_cap; d++) {
        tfree(lhs_perm[d]);
        tfree(lhs_jit[d]);
    }
    tfree(lhs_perm);
    tfree(lhs_jit);
    lhs_dim_cap = 0;
}

/* Build the stratum permutation and jitter for dimension d (grows the tables as
 * needed). Fisher-Yates over 0..N-1, then N jitters, from a per-dimension seed. */
static void lhs_gen_dim(int d)
{
    int i;
    if (d >= lhs_dim_cap) {
        int newcap = (d + 1) * 2;
        lhs_perm = TREALLOC(int *, lhs_perm, newcap);
        lhs_jit = TREALLOC(double *, lhs_jit, newcap);
        for (i = lhs_dim_cap; i < newcap; i++) {
            lhs_perm[i] = NULL;
            lhs_jit[i] = NULL;
        }
        lhs_dim_cap = newcap;
    }
    if (lhs_perm[d] != NULL)
        return;

    int *p = TMALLOC(int, lhs_N);
    double *j = TMALLOC(double, lhs_N);
    uint64_t s = (uint64_t)lhs_seed * 0x2545F4914F6CDD1DULL +
                 (uint64_t)(d + 1) * 0x9E3779B97F4A7C15ULL;
    for (i = 0; i < lhs_N; i++)
        p[i] = i;
    for (i = lhs_N - 1; i > 0; i--) {
        int k = (int)(sm_unif(&s) * (double)(i + 1));
        if (k > i)
            k = i;
        int tmp = p[i];
        p[i] = p[k];
        p[k] = tmp;
    }
    for (i = 0; i < lhs_N; i++)
        j[i] = sm_unif(&s);
    lhs_perm[d] = p;
    lhs_jit[d] = j;
}

/* Nonzero when a stratified/importance sampler (LHS or SSS) is engaged, so the
 * netlist stochastic functions route their draws through it. */
int mc_sample_active(void)
{
    return lhs_mode != MC_MODE_RANDOM && lhs_N > 0;
}

/* Step to the next sample: rewind the per-sample dimension counter and, under
 * SSS, reset the accumulated importance weight. Called once per deck
 * re-evaluation pass. */
void mc_sample_advance(void)
{
    if (!mc_sample_active())
        return;
    lhs_sample++;
    lhs_dim = 0;
    sss_logw = 0.0;
}

/* Next uniform in [0,1) for the current draw. LHS returns the stratified value;
 * SSS and out-of-range fall back to a plain PRNG uniform (uniform .params are
 * bounded, so SSS does not inflate them -- they carry weight 1). */
double mc_sample_uniform(void)
{
    if (lhs_mode != MC_MODE_LHS || lhs_sample < 0 || lhs_sample >= lhs_N)
        return 0.5 * (drand() + 1.0);
    int d = lhs_dim++;
    lhs_gen_dim(d);
    return ((double)lhs_perm[d][lhs_sample] + lhs_jit[d][lhs_sample]) /
           (double)lhs_N;
}

/* Next standard-normal draw. LHS stratifies in uniform space then maps through
 * the inverse normal CDF; SSS draws from the lambda-inflated normal (z = lambda*u)
 * and accumulates this dimension's log likelihood ratio into sss_logw. */
double mc_sample_gauss(void)
{
    if (lhs_mode == MC_MODE_SSS && lhs_sample >= 0 && lhs_sample < lhs_N) {
        double z = sss_lambda * gauss1();
        /* log w_d = log(lambda) - (z^2/2)(1 - 1/lambda^2) */
        sss_logw += log(sss_lambda) -
                    0.5 * z * z * (1.0 - 1.0 / (sss_lambda * sss_lambda));
        return z;
    }
    if (lhs_mode != MC_MODE_LHS || lhs_sample < 0 || lhs_sample >= lhs_N)
        return gauss1();
    double u = mc_sample_uniform();
    if (u < 1e-12)
        u = 1e-12;
    else if (u > 1.0 - 1e-12)
        u = 1.0 - 1e-12;
    return inv_normal_cdf(u);
}

/* The importance weight p_nominal/p_sampling of the current sample (product over
 * its Gaussian draws). 1.0 outside SSS, so plain/LHS runs are unweighted. */
double mc_sample_weight(void)
{
    return (lhs_mode == MC_MODE_SSS) ? exp(sss_logw) : 1.0;
}

/* Engage scaled-sigma importance sampling for N samples with inflation lambda.
 * Called by the `highsigma` command around its sampling loop. */
void mc_sss_config(int nsamples, double lambda, unsigned seed)
{
    lhs_free_tables();
    lhs_mode = MC_MODE_SSS;
    lhs_N = nsamples;
    sss_lambda = (lambda > 1.0) ? lambda : 1.0;
    lhs_seed = seed;
    lhs_sample = -1;
    lhs_dim = 0;
    sss_logw = 0.0;
    /* SSS draws through gauss1() (the global PRNG); seed it so a given seed
     * reproduces the sample sequence bit-for-bit. */
    srand(seed);
    TausSeed();
}

/* Revert to plain independent sampling (called by `highsigma` when done). */
void mc_sss_off(void)
{
    lhs_free_tables();
    lhs_mode = MC_MODE_RANDOM;
    lhs_N = 0;
    lhs_sample = -1;
    lhs_dim = 0;
    sss_logw = 0.0;
    sss_lambda = 1.0;
}

/* Peter Acklam's rational approximation to the inverse standard-normal CDF
 * (relative error < 1.15e-9 across (0,1)). Maps a uniform in (0,1) to the
 * corresponding standard-normal quantile. */
double inv_normal_cdf(double p)
{
    static const double a[6] = {
        -3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
        1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00};
    static const double b[5] = {
        -5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
        6.680131188771972e+01, -1.328068155288572e+01};
    static const double c[6] = {
        -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
        -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00};
    static const double d[4] = {
        7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
        3.754408661907416e+00};
    const double p_low = 0.02425, p_high = 1.0 - 0.02425;
    double q, r;
    if (p <= 0.0)
        return -HUGE_VAL;
    if (p >= 1.0)
        return HUGE_VAL;
    if (p < p_low) {
        q = sqrt(-2.0 * log(p));
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q +
                c[5]) /
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
    } else if (p <= p_high) {
        q = p - 0.5;
        r = q * q;
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r +
                a[5]) *
               q /
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r +
                1.0);
    } else {
        q = sqrt(-2.0 * log(1.0 - p));
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q +
                 c[5]) /
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0);
    }
}

/* mcsample lhs <N> [seed <s>]   -- engage Latin-Hypercube sampling for N runs
 * mcsample random | off         -- revert to independent PRNG sampling         */
void com_mcsample(wordlist *wl)
{
    if (wl == NULL) {
        if (mc_sample_active())
            printf("Monte Carlo sampling: Latin-Hypercube, N = %d, seed = %u "
                   "(sample %d).\n", lhs_N, lhs_seed, lhs_sample);
        else
            printf("Monte Carlo sampling: random (independent PRNG).\n");
        return;
    }

    char *method = wl->wl_word;
    if (cieq(method, "off") || cieq(method, "random")) {
        lhs_free_tables();
        lhs_mode = MC_MODE_RANDOM;
        lhs_N = 0;
        lhs_sample = -1;
        lhs_dim = 0;
        printf("Monte Carlo sampling reset to random (independent PRNG).\n");
        return;
    }

    if (!cieq(method, "lhs")) {
        fprintf(cp_err, "Error: unknown sampling method '%s' "
                        "(use 'lhs', 'random', or 'off').\n", method);
        return;
    }

    if (wl->wl_next == NULL) {
        fprintf(cp_err, "Error: 'mcsample lhs' needs a sample count N.\n");
        return;
    }
    int nsamp = atoi(wl->wl_next->wl_word);
    if (nsamp < 2) {
        fprintf(cp_err, "Error: LHS sample count must be >= 2 (got '%s').\n",
                wl->wl_next->wl_word);
        return;
    }

    /* optional: seed <s> */
    unsigned seed = 1;
    wordlist *w = wl->wl_next->wl_next;
    if (w != NULL) {
        if (cieq(w->wl_word, "seed") && w->wl_next != NULL) {
            seed = (unsigned)strtoul(w->wl_next->wl_word, NULL, 10);
        } else {
            fprintf(cp_err, "Warning: ignoring trailing 'mcsample' arguments "
                            "starting at '%s'.\n", w->wl_word);
        }
    }

    lhs_free_tables();
    lhs_mode = MC_MODE_LHS;
    lhs_N = nsamp;
    lhs_seed = seed;
    lhs_sample = -1;
    lhs_dim = 0;
    printf("Monte Carlo sampling: Latin-Hypercube, N = %d, seed = %u.\n"
           "  Each of the next %d reset-driven passes draws one stratified "
           "sample per random parameter.\n", lhs_N, lhs_seed, lhs_N);
}
