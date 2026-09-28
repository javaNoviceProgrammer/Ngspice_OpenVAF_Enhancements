/* Enhancement-752: a pseudo-random bit sequence (PRBS) source function for
 * the independent voltage and current sources, and its four-level form,
 *
 *     Vtx tx 0 PRBS(v1 v2 tbit [td [tr [tf [order [seed]]]]])
 *     Vtx tx 0 PAM4(v1 v2 tsym [td [tr [tf [order [seed]]]]])
 *
 * PAM4 consumes the same register two bits per symbol, Gray coded as IEEE
 * 802.3 clause 120 and OIF-CEI define PRBS13Q and PRBS31Q (00, 01, 11, 10 are
 * the levels v1, v1 + (v2 - v1)/3, v1 + 2(v2 - v1)/3, v2), and order 13 is
 * that clause's x^13 + x^12 + x^2 + x + 1.  Below, "bit" reads "symbol" for it.
 *
 * v1 is the level of a 0 bit, v2 of a 1 bit, tbit the bit period, td the delay
 * before the first bit (v1 is held until then), tr and tf the rise and fall
 * times of a transition (a value of 0 or less takes the analysis's own step,
 * as PULSE does), order the length of the linear-feedback shift register
 * (2..31, default 7: the sequence repeats every 2^order - 1 bits) and seed its
 * nonzero initial contents (default: all ones).  The bits come from a
 * Fibonacci LFSR with the standard maximal-length taps (ITU-T O.150 for the
 * orders it names, Xilinx XAPP052 for the rest), so PRBS7, PRBS9, PRBS11,
 * PRBS15, PRBS23 and PRBS31 are the sequences test equipment sends.
 *
 * Bit k occupies [td + k*tbit, td + (k+1)*tbit); a transition begins at the
 * bit boundary and takes tr or tf; a run of equal bits has no corner, so no
 * breakpoint.  The value at any time is a pure function of the time (the
 * register after bit k is cached, with a ring of the last PRBS_RING bits for
 * the stepper's backward moves), so a rejected timestep costs nothing and a
 * re-run from t=0 reproduces the run. */
#ifndef ngspice_PRBS_H
#define ngspice_PRBS_H

#define PRBS_RING 64

struct prbs_state {
    double v1, v2, tbit, td, tr, tf;   /* as written; tr/tf <= 0 = default */
    int levels;                        /* 2 (PRBS) or 4 (PAM4) */
    const char *kw;                    /* "prbs" or "pam4", for messages */
    int order;                         /* register length n, 2..31 */
    unsigned long seed;                /* initial register, n bits, nonzero */
    unsigned long mask;                /* (1 << n) - 1 */
    int taps[4];                       /* tap positions, 1..n, taps[0] == n */
    int ntaps;
    long k_cached;                     /* bit index the register stands after */
    unsigned long st_cached;           /* register after bit k_cached (bit k in its LSB) */
    long ring_k[PRBS_RING];            /* (k, register) of the last PRBS_RING bits */
    unsigned long ring_st[PRBS_RING];
    double break_time;                 /* the next scheduled corner, per run */
};

/* parse the coefficient list (n values); prints the refusal and returns NULL
 * on a bad list.  `kind` is "voltage" or "current", `name` the instance. */
struct prbs_state *prbs_state_init(const double *c, int n, const char *kind,
                                   const char *name, int levels);
/* re-arm for a new run: the register back to the seed, no corner scheduled */
void prbs_state_reset(struct prbs_state *s);
/* bit k of the sequence (0 for k < 0: the level before the delay is v1) */
int prbs_bit(struct prbs_state *s, long k);
/* the level index of symbol k: bit k for two levels, the Gray-coded pair of
 * bits 2k (first) and 2k + 1 for four; 0 for k < 0 */
int prbs_level(struct prbs_state *s, long k);
/* the source's value at `time`; `defstep` replaces a tr/tf of 0 or less */
double prbs_value(struct prbs_state *s, double time, double defstep);
/* the first corner of the waveform strictly after `after`, or 1e99 */
double prbs_next_edge(struct prbs_state *s, double after, double defstep);
/* the tap table: fills taps[] for `order`, returns the count or 0 */
int prbs_taps(int order, int *taps);

#endif
