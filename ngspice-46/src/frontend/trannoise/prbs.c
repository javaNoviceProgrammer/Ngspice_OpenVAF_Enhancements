/* Enhancement-752: the PRBS source function -- see ngspice/prbs.h. */
#include "ngspice/ngspice.h"
#include "ngspice/prbs.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

/* Maximal-length feedback taps, one polynomial per register length: the
 * ITU-T O.150 polynomials for 7, 9, 11, 15, 23 and 31, IEEE 802.3 clause
 * 120's x^13 + x^12 + x^2 + x + 1 for 13 (PRBS13Q's), and Xilinx XAPP052's
 * for the others (its XNOR taps are maximal for XOR feedback as well; only the
 * lock-up state differs, all ones there, all zeros here). */
static const int prbs_tap_table[32][4] = {
    {0}, {0}, {2, 1}, {3, 2}, {4, 3}, {5, 3}, {6, 5}, {7, 6}, {8, 6, 5, 4},
    {9, 5}, {10, 7}, {11, 9}, {12, 6, 4, 1}, {13, 12, 2, 1}, {14, 5, 3, 1},
    {15, 14}, {16, 15, 13, 4}, {17, 14}, {18, 11}, {19, 6, 2, 1}, {20, 17},
    {21, 19}, {22, 21}, {23, 18}, {24, 23, 22, 17}, {25, 22}, {26, 6, 2, 1},
    {27, 5, 2, 1}, {28, 25}, {29, 27}, {30, 6, 4, 1}, {31, 28}
};

int
prbs_taps(int order, int *taps)
{
    int n = 0;
    if (order < 2 || order > 31)
        return 0;
    while (n < 4 && prbs_tap_table[order][n] > 0) {
        taps[n] = prbs_tap_table[order][n];
        n++;
    }
    return n;
}

static int
prbs_is_integer(double x)
{
    return isfinite(x) && floor(x) == x;
}

struct prbs_state *
prbs_state_init(const double *c, int n, const char *kind, const char *name,
                int levels)
{
    struct prbs_state *s;
    double order = 7.0, seed = -1.0;
    const char *kw = levels == 4 ? "pam4" : "prbs";
    const char *unit = levels == 4 ? "symbol" : "bit";

    if (n < 3) {
        fprintf(stderr,
                "\nError: %s source %s: %s needs at least v1, v2 and the %s "
                "time -- %s(v1 v2 t%s [td [tr [tf [order [seed]]]]]) -- "
                "but %d value%s given.\n\n",
                kind, name, kw, unit, kw, levels == 4 ? "sym" : "bit",
                n, n == 1 ? " was" : "s were");
        return NULL;
    }
    if (!(c[2] > 0.0) || !isfinite(c[2])) {
        fprintf(stderr,
                "\nError: %s source %s: %s %s time %g is not positive.\n\n",
                kind, name, kw, unit, c[2]);
        return NULL;
    }
    if (n > 3 && (c[3] < 0.0 || !isfinite(c[3]))) {
        fprintf(stderr,
                "\nError: %s source %s: %s delay %g is negative.\n\n",
                kind, name, kw, c[3]);
        return NULL;
    }
    if (n > 4 && c[4] > c[2]) {
        fprintf(stderr,
                "\nError: %s source %s: %s rise time %g is longer than the "
                "%s time %g.\n\n", kind, name, kw, c[4], unit, c[2]);
        return NULL;
    }
    if (n > 5 && c[5] > c[2]) {
        fprintf(stderr,
                "\nError: %s source %s: %s fall time %g is longer than the "
                "%s time %g.\n\n", kind, name, kw, c[5], unit, c[2]);
        return NULL;
    }
    if (n > 6)
        order = c[6];
    if (!prbs_is_integer(order) || order < 2.0 || order > 31.0) {
        fprintf(stderr,
                "\nError: %s source %s: %s order %g is not a register "
                "length between 2 and 31 (7 is PRBS7, 2^7 - 1 bits).\n\n",
                kind, name, kw, order);
        return NULL;
    }
    s = TMALLOC(struct prbs_state, 1);
    memset(s, 0, sizeof *s);
    s->levels = levels == 4 ? 4 : 2;
    s->kw = kw;
    s->v1 = c[0];
    s->v2 = c[1];
    s->tbit = c[2];
    s->td = n > 3 ? c[3] : 0.0;
    s->tr = n > 4 ? c[4] : 0.0;
    s->tf = n > 5 ? c[5] : 0.0;
    s->order = (int) order;
    s->mask = (s->order >= 31) ? 0x7fffffffUL : ((1UL << s->order) - 1UL);
    s->ntaps = prbs_taps(s->order, s->taps);
    if (n > 7) {
        seed = c[7];
        if (!prbs_is_integer(seed) || seed < 1.0 || seed > 2147483647.0
            || (((unsigned long) seed) & s->mask) == 0UL) {
            fprintf(stderr,
                    "\nError: %s source %s: %s seed %g is not a positive "
                    "integer with a nonzero low %d bits (the register's "
                    "initial contents; omit it for all ones).\n\n",
                    kind, name, kw, seed, s->order);
            tfree(s);
            return NULL;
        }
        s->seed = ((unsigned long) seed) & s->mask;
    } else {
        s->seed = s->mask;
    }
    prbs_state_reset(s);
    return s;
}

void
prbs_state_reset(struct prbs_state *s)
{
    int i;
    s->k_cached = -1;
    s->st_cached = s->seed;
    for (i = 0; i < PRBS_RING; i++)
        s->ring_k[i] = -1;
    s->break_time = -1.0;
}

static unsigned long
prbs_step(const struct prbs_state *s, unsigned long st)
{
    unsigned long nb = 0UL;
    int i;
    for (i = 0; i < s->ntaps; i++)
        nb ^= (st >> (s->taps[i] - 1)) & 1UL;
    return ((st << 1) | nb) & s->mask;
}

static void
prbs_advance_to(struct prbs_state *s, long k)
{
    while (s->k_cached < k) {
        s->st_cached = prbs_step(s, s->st_cached);
        s->k_cached++;
        s->ring_k[s->k_cached % PRBS_RING] = s->k_cached;
        s->ring_st[s->k_cached % PRBS_RING] = s->st_cached;
    }
}

int
prbs_bit(struct prbs_state *s, long k)
{
    if (k < 0)
        return 0;
    if (k == s->k_cached)
        return (int) (s->st_cached & 1UL);
    if (k > s->k_cached) {
        prbs_advance_to(s, k);
        return (int) (s->st_cached & 1UL);
    }
    if (s->ring_k[k % PRBS_RING] == k)
        return (int) (s->ring_st[k % PRBS_RING] & 1UL);
    /* further back than the ring: restart from the seed (the stepper's
     * backward moves are a few bits at most, so this is the rare road) */
    {
        unsigned long st = s->seed;
        long i;
        for (i = 0; i <= k; i++)
            st = prbs_step(s, st);
        return (int) (st & 1UL);
    }
}

int
prbs_level(struct prbs_state *s, long k)
{
    int b0, b1;
    if (k < 0)
        return 0;
    if (s->levels != 4)
        return prbs_bit(s, k);
    b0 = prbs_bit(s, 2 * k);        /* the first bit of the pair is the MSB */
    b1 = prbs_bit(s, 2 * k + 1);
    return b0 ? (b1 ? 2 : 3) : (b1 ? 1 : 0);   /* Gray: 00 01 11 10 */
}

static double
prbs_edge_time(const struct prbs_state *s, int rising, double defstep)
{
    double te = rising ? s->tr : s->tf;
    if (te <= 0.0)
        te = defstep;
    if (te <= 0.0)
        te = s->tbit * 1e-3;
    if (te > s->tbit)
        te = s->tbit;
    return te;
}

double
prbs_value(struct prbs_state *s, double time, double defstep)
{
    double t = time - s->td, u, te, lev, levp, span;
    long k;
    int b, bp;

    if (t <= 0.0)
        return s->v1;
    k = (long) floor(t / s->tbit);
    u = t - (double) k * s->tbit;
    b = prbs_level(s, k);
    bp = prbs_level(s, k - 1);
    span = (s->v2 - s->v1) / (double) (s->levels - 1);
    lev = s->v1 + span * b;
    if (b == bp)
        return lev;
    levp = s->v1 + span * bp;
    te = prbs_edge_time(s, b > bp, defstep);
    if (u >= te)
        return lev;
    return levp + (lev - levp) * u / te;
}

double
prbs_next_edge(struct prbs_state *s, double after, double defstep)
{
    double t = after - s->td;
    long k, kend;

    if (t < 0.0)
        k = 0;
    else
        k = (long) floor(t / s->tbit);
    /* a maximal sequence has no run longer than its order, so a corner lies
     * within order + 1 bits; look a little further to be safe */
    kend = k + s->order + 4;
    for (; k <= kend; k++) {
        int b = prbs_level(s, k), bp = prbs_level(s, k - 1);
        double t0, t1;
        if (b == bp)
            continue;
        t0 = s->td + (double) k * s->tbit;
        t1 = t0 + prbs_edge_time(s, b > bp, defstep);
        if (t0 > after)
            return t0;
        if (t1 > after)
            return t1;
    }
    return 1e99;
}
