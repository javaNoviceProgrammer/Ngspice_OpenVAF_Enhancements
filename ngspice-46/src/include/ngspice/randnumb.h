#ifndef ngspice_RANDNUMB_H
#define ngspice_RANDNUMB_H

#include "ngspice/wordlist.h"
extern void com_sseed(wordlist *wl);
extern void setseedinfo(void);

/* initialize random number generators */
extern void initw(void);

extern void checkseed(void);    /* seed random or set by 'set rndseed=value'*/
extern double drand(void);
extern double gauss0(void);
extern double gauss1(void);
extern int poisson(double);
extern double exprand(double);

extern void TausSeed(void);
extern unsigned int CombLCGTausInt(void);
extern unsigned int CombLCGTausInt2(void);

/* Enhancement-149: Latin-Hypercube (LHS) low-discrepancy Monte Carlo sampling.
   The `mcsample` command configures a stratified sampler that the netlist
   stochastic functions (agauss/gauss/aunif/unif/limit) draw from instead of the
   plain PRNG, so N `reset`-driven samples cover each random dimension's range
   evenly (one sample per stratum). mc_sample_advance() is called once per deck
   re-evaluation pass (the NUPADECKCOPY edge) to step to the next sample. */
extern void com_mcsample(wordlist *wl);
extern int  mc_sample_active(void);      /* nonzero when LHS mode is engaged   */
extern void mc_sample_advance(void);     /* step to the next sample (per pass) */
extern double mc_sample_uniform(void);   /* next stratified U in [0,1)         */
extern double mc_sample_gauss(void);     /* next stratified standard normal    */
extern double inv_normal_cdf(double p);  /* probit: standard-normal quantile   */

/* Enhancement-150: scaled-sigma importance sampling for rare-event (high-sigma)
 * probability. `highsigma` engages it, runs its N-sample loop (each `reset`
 * redraws the lambda-inflated Gaussian .params), and reads each sample's
 * likelihood-ratio weight to form an unbiased failure-probability estimate. */
extern void com_highsigma(wordlist *wl);
extern void mc_sss_config(int nsamples, double lambda, unsigned seed);
extern void mc_sss_off(void);
extern double mc_sample_weight(void);    /* importance weight of current sample */
extern void mc_lhs_config(int nsamples, unsigned seed);  /* engage LHS directly */

/* Enhancement-151: correlated (process/mismatch) sampling and packaged yield.
 * `mccorr` registers a k x k correlation matrix; `mvnorm(i)` in a .param returns
 * the i-th correlated standard normal. `montecarlo` runs a spec-based yield MC. */
extern void com_mccorr(wordlist *wl);
extern void com_montecarlo(wordlist *wl);
extern int  mc_corr_config(int k, const double *mat);

/* Enhancement-305: worst-case-distance / most-probable-failure-point high sigma.
 * `wcd` walks standardised normal space to the closest point of the failure
 * region (the MPFP), reports that distance beta and the first-order probability
 * Phi(-beta), and can refine it with mean-shift importance sampling centred
 * there. mc_wcd_config() makes every Gaussian draw deterministic so the deck is
 * a plain function g(u); mc_wcd_shift() samples N(u*, I) carrying the exact
 * likelihood ratio; mc_wcd_ndim() reports how many draws an evaluation used. */
extern void com_wcd(wordlist *wl);
extern void mc_wcd_config(const double *u, int n);
extern void mc_wcd_shift(const double *u, int n, unsigned seed);
extern int  mc_wcd_ndim(void);
extern void mc_wcd_off(void);
extern double mc_corr_component(int idx);   /* i-th correlated normal (1-based)  */
extern int    mc_corr_size(void);           /* k of the registered matrix, 0 if none */

#endif
