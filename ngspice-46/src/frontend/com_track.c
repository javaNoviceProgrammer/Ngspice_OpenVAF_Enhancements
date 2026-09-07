/* Enhancement-577: `track` -- every place a condition holds, as a plot.
 *
 *   track <expr> [<expr> ...] [-range x0 x1] [-spec <spec>] [-analysis <plot|type>]
 *         [-which all|first|last|N|-N] [-edge rise|fall|both] [-at entry|exit|mid]
 *         [-prominence p] [-raw] [-output name ...]
 *
 * `track` is a vector-valued `meas`: it turns a spec into a set of HITS on the
 * x-axis of an analysis, reads the tracked expressions there, and packages both
 * into a plot of its own, track1, track2, ... Every word before the first
 * -option is an expression (quote one that contains spaces); one spec drives
 * them all and each gets a vector in the plot: `value` for a single expression,
 * value1..valueN for several, or the names `-output` gives in order.
 *
 * The spec:
 *   (none)                   every sample in the range -- a crop into its own plot
 *   localmin ... globalmax   applied to the FIRST expression
 *   localmax(e2) ...         applied to e2; the expressions are read at the hits
 *   lhs==rhs                 a CROSSING: d = lhs - rhs changes sign between two
 *                            samples, or is exactly zero; x by linear interpolation
 *                            of d's zero, in log x when the scale carries a log grid
 *   lhs<rhs <= > >=          a REGION: a maximal run of samples where it holds,
 *                            entry and exit interpolated like a crossing
 *   anything else            a region from the boolean 0/1 vector the evaluator
 *                            returns, entry and exit at sample midpoints
 *
 * A local extremum is refined with the parabola through its three samples
 * unless -raw; a plateau is never refined. -prominence p applies the hysteresis
 * rule to local extrema. The plot's scale is named and typed after the source
 * scale, so `plot track1.value` draws against time; `index` is the bracketing
 * sample, regions add `x_out` and `width`, `-edge both` adds `edge`. plot_cur
 * is NOT switched to the new plot. Zero hits creates no plot and prints
 * `track failed!` -- Enhancement-475's rule for `meas`. See
 * docs/proposals/2026-09-07_dc-path-gmin.md's sibling,
 * docs/proposals/2026-09-06_track-command.md, for the design. */

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/fteext.h"
#include "ngspice/dvec.h"
#include "ngspice/plot.h"
#include "ngspice/sim.h"
#include "ngspice/grid.h"
#include "ngspice/stringutil.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpextern.h"
#include "com_track.h"

#include <math.h>
#include <string.h>

extern bool ft_batchmode;                    /* main.c */

enum { SPEC_ALL, SPEC_EXTREMUM, SPEC_CROSSING, SPEC_REGION, SPEC_BOOL };
enum { WHICH_ALL = 0, WHICH_FIRST, WHICH_LAST, WHICH_N };
enum { EDGE_BOTH, EDGE_RISE, EDGE_FALL };
enum { AT_ENTRY, AT_EXIT, AT_MID };

#define TRACK_MAX_EXPR 32

struct hit {
    double x;        /* where the condition holds (entry, for a region) */
    double x_out;    /* exit of a region */
    int index;       /* the bracketing sample: the one at or after x */
    int lo, hi;      /* the extremum's samples (a plateau spans several) */
    int edge;        /* +1 rising, -1 falling, for a crossing */
    double yext;     /* the refined extremum value, for the located expression */
};

/* ---------------------------------------------------------------- helpers */

int track_quiet = 0;                /* Enhancement-582 */
int track_error = 0;

static int
is_option(const char *w)
{
    return w && w[0] == '-' && w[1] && isalpha_c(w[1]);
}

static void
fail(const char *why)
{
    if (why)
        fprintf(cp_err, "Error: track: %s\n", why);
    fprintf(cp_out, "track failed!\n");
    track_error = 1;
}

/* Evaluate `expr` in the current plot. Returns a REAL data copy of the scale's
 * length (a scalar is broadcast), or NULL with a message. `what` names the
 * argument in messages. */
static double *
eval_real(const char *expr, int len, const char *what, int *vtype)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    struct dvec *v;
    double *out = NULL;
    int i;

    if (vtype)
        *vtype = SV_NOTYPE;

    if (!pn) {
        fprintf(cp_err, "Error: track: cannot parse %s '%s'\n", what, expr);
        return NULL;
    }
    v = ft_evaluate(pn);
    if (!v) {
        fprintf(cp_err, "Error: track: cannot evaluate %s '%s' in plot %s\n", what, expr,
                plot_cur ? plot_cur->pl_typename : "?");
        free_pnode(pn);
        return NULL;
    }
    if (!isreal(v)) {
        fprintf(cp_err, "Error: track: %s '%s' is complex-valued; wrap it in mag(), db(), ph() or real()\n",
                what, expr);
    } else if (v->v_numdims > 1) {
        fprintf(cp_err, "Error: track: %s '%s' is multi-dimensional (%d dims); track the "
                        "per-point plots `sweep` keeps instead\n", what, expr, v->v_numdims);
    } else if (v->v_length != len && v->v_length != 1) {
        fprintf(cp_err, "Error: track: %s '%s' has %d samples, the scale %d\n", what, expr,
                v->v_length, len);
    } else {
        out = TMALLOC(double, len);
        for (i = 0; i < len; i++)
            out[i] = v->v_realdata[v->v_length == 1 ? 0 : i];
        if (vtype)
            *vtype = (int) v->v_type;         /* the value vectors carry their expression's type */
    }
    if (!pn->pn_value)
        vec_free(v);
    free_pnode(pn);
    return out;
}

/* The ONE top-level comparison operator of a spec, or NULL when the spec is
 * a boolean: it carries a top-level &, |, ~ or !, or more than one
 * comparison, or none. Sets *op and *oplen. */
static const char *
find_comparison(const char *s, const char **op, int *oplen)
{
    int depth = 0, ncmp = 0;
    const char *p, *found = NULL;
    for (p = s; *p; p++) {
        if (*p == '(' || *p == '[' || *p == '{')
            depth++;
        else if (*p == ')' || *p == ']' || *p == '}')
            depth--;
        else if (depth == 0) {
            if (*p == '&' || *p == '|' || *p == '~' || (*p == '!' && p[1] != '='))
                return NULL;
            if (p[0] == '!' && p[1] == '=')
                return NULL;
            if (p[0] == '=' && p[1] == '=') { if (!found) { *op = "=="; *oplen = 2; found = p; } ncmp++; p++; }
            else if (p[0] == '<' && p[1] == '=') { if (!found) { *op = "<="; *oplen = 2; found = p; } ncmp++; p++; }
            else if (p[0] == '>' && p[1] == '=') { if (!found) { *op = ">="; *oplen = 2; found = p; } ncmp++; p++; }
            else if (p[0] == '<') { if (!found) { *op = "<"; *oplen = 1; found = p; } ncmp++; }
            else if (p[0] == '>') { if (!found) { *op = ">"; *oplen = 1; found = p; } ncmp++; }
        }
    }
    return ncmp == 1 ? found : NULL;
}

static char *
trim_copy(const char *s, size_t n)
{
    char *out;
    while (n && isspace_c(*s)) { s++; n--; }
    while (n && isspace_c(s[n - 1])) n--;
    out = TMALLOC(char, n + 1);
    memcpy(out, s, n);
    out[n] = '\0';
    return out;
}

/* x where d crosses zero between samples i-1 and i; log-x on a log grid */
static double
interp_zero(const double *x, const double *d, int i, int logx)
{
    double x0 = x[i - 1], x1 = x[i], d0 = d[i - 1], d1 = d[i];
    if (d1 == d0)
        return x1;
    if (logx && x0 > 0 && x1 > 0) {
        double l0 = log10(x0), l1 = log10(x1);
        return pow(10.0, l0 + (l1 - l0) * (0.0 - d0) / (d1 - d0));
    }
    return x0 + (x1 - x0) * (0.0 - d0) / (d1 - d0);
}

/* y at x by linear interpolation between samples i-1 and i (log-x aware) */
static double
interp_at(const double *x, const double *y, int i, double xq, int n, int logx)
{
    double x0, x1, t;
    if (i <= 0)
        return y[0];
    if (i >= n)
        return y[n - 1];
    x0 = x[i - 1]; x1 = x[i];
    if (x1 == x0)
        return y[i];
    if (logx && x0 > 0 && x1 > 0 && xq > 0)
        t = (log10(xq) - log10(x0)) / (log10(x1) - log10(x0));
    else
        t = (xq - x0) / (x1 - x0);
    return y[i - 1] + t * (y[i] - y[i - 1]);
}

/* the sample at or after xq, searching from the range */
static int
bracket_index(const double *x, int n, double xq, int ascending)
{
    int i;
    for (i = 1; i < n; i++)
        if (ascending ? x[i] >= xq : x[i] <= xq)
            return i;
    return n - 1;
}

/* the plot named or typed `name`: the newest whose typename `name` prefixes,
 * digits having to match -- the vec_get rule */
static int
plot_prefix_match(const char *pre, const char *str)
{
    if (!*pre)
        return 1;
    while (*pre && *str) {
        if (*pre != *str)
            break;
        pre++;
        str++;
    }
    return !(*pre || (*str && isdigit_c(pre[-1])));
}

static struct plot *
find_plot(const char *name)
{
    struct plot *pl;
    for (pl = plot_list; pl; pl = pl->pl_next)
        if (pl->pl_typename && plot_prefix_match(name, pl->pl_typename))
            return pl;
    return NULL;
}

/* ------------------------------------------------------------ the command */

void
com_track(wordlist *wl)
{
    /* Enhancement-581: `$track_plot` and `$track_hits` -- the plot the last
     * `track` made and how many hits it holds -- so a loop can reach the
     * result without naming `trackN` by number, which slips as soon as one
     * trial has no hits (a miss makes no plot and does not advance the count).
     * Cleared here so a refusal never leaves the previous call's answer;
     * `montecarlo` does the same with `$montecarlo_plot`. */
    {
        int zero = 0;
        cp_vset("track_plot", CP_STRING, "");
        cp_vset("track_hits", CP_NUM, &zero);
        track_error = 0;                     /* Enhancement-582 */
    }
    /* ---- arguments */
    char *exprs[TRACK_MAX_EXPR];
    char *outnames[TRACK_MAX_EXPR];
    int nexpr = 0, nout = 0;
    char *spec = NULL, *analysis = NULL;
    double r0 = 0, r1 = 0;
    int have_range = 0, which = WHICH_ALL, which_n = 0, edge = EDGE_BOTH, at = AT_ENTRY;
    int have_edge = 0, have_at = 0, raw = 0;
    double prominence = 0.0;
    wordlist *w;

    /* ---- the plot and its data */
    struct plot *saved_cur = plot_cur, *pl = NULL, *npl;
    struct dvec *scale;
    double *x = NULL, *xown = NULL;          /* xown: the real parts of a complex scale */
    int n, ascending, logx;
    double **vals = NULL;                    /* one array per expression */
    int vtypes[TRACK_MAX_EXPR];
    double *d = NULL, *loc = NULL;           /* the spec's difference / located expression */
    int i0, i1, i, k, e;

    /* ---- the hits */
    struct hit *hits = NULL;
    int nhits = 0, kind = SPEC_ALL, midpoints = 0;
    char *specname = NULL, *lhs = NULL, *rhs = NULL, *locexpr = NULL, *sname = NULL;
    const char *op = NULL;
    int oplen = 0, want_max = 0, global = 0;
    int ok = 0;

    for (e = 0; e < TRACK_MAX_EXPR; e++) {
        exprs[e] = NULL;
        outnames[e] = NULL;
    }

    /* ---- parse: expressions first, then dash options */
    w = wl;
    while (w && !is_option(w->wl_word)) {
        if (nexpr >= TRACK_MAX_EXPR) {
            fail("more than 32 expressions");
            goto done;
        }
        /* a quoted expression keeps its quotes through the lexer: "v(a) * v(b)"
           arrives as one word with the quotes on it; drop them */
        {
            const char *q = w->wl_word;
            size_t ql = strlen(q);
            if (ql >= 2 && (q[0] == '"' || q[0] == '\'') && q[ql - 1] == q[0])
                exprs[nexpr++] = trim_copy(q + 1, ql - 2);
            else
                exprs[nexpr++] = copy(q);
        }
        w = w->wl_next;
    }
    if (nexpr == 0) {
        fail("usage: track <expr> [<expr> ...] [-range x0 x1] [-spec <spec>] "
             "[-analysis <plot>] [-which all|first|last|N] [-edge rise|fall|both] "
             "[-at entry|exit|mid] [-prominence p] [-raw] [-output name ...]");
        goto done;
    }
    while (w) {
        const char *o = w->wl_word;
        if (cieq(o, "-range")) {
            double v0, v1;
            char *p0 = w->wl_next ? w->wl_next->wl_word : NULL;
            char *p1 = (w->wl_next && w->wl_next->wl_next) ? w->wl_next->wl_next->wl_word : NULL;
            /* ft_numparse advances the pointer it is handed: give it copies,
               never the wordlist's own word, which is freed after the command */
            if (!p0 || !p1 || ft_numparse(&p0, FALSE, &v0) < 0 || ft_numparse(&p1, FALSE, &v1) < 0) {
                fail("-range wants two numbers");
                goto done;
            }
            r0 = v0; r1 = v1; have_range = 1;
            w = w->wl_next->wl_next->wl_next;
        } else if (cieq(o, "-spec")) {
            /* every word up to the next -option, joined WITHOUT spaces: the
               lexer hands `<` and `>` over as words of their own (they are
               redirection characters everywhere else), so `v(b)<=-1.0`
               arrives in pieces, and an expression needs no spaces anyway */
            wordlist *s = w->wl_next;
            size_t total = 1;
            char *q;
            for (; s && !is_option(s->wl_word); s = s->wl_next)
                total += strlen(s->wl_word);
            if (total == 1) {
                fail("-spec wants a spec");
                goto done;
            }
            tfree(spec);
            spec = q = TMALLOC(char, total);
            *q = '\0';
            for (s = w->wl_next; s && !is_option(s->wl_word); s = s->wl_next)
                strcat(q, s->wl_word);
            w = s;
        } else if (cieq(o, "-analysis")) {
            if (!w->wl_next) { fail("-analysis wants a plot name or type"); goto done; }
            tfree(analysis);
            analysis = copy(w->wl_next->wl_word);
            w = w->wl_next->wl_next;
        } else if (cieq(o, "-which")) {
            const char *a = w->wl_next ? w->wl_next->wl_word : NULL;
            if (!a) { fail("-which wants all, first, last, N or -N"); goto done; }
            if (cieq(a, "all")) which = WHICH_ALL;
            else if (cieq(a, "first")) which = WHICH_FIRST;
            else if (cieq(a, "last")) which = WHICH_LAST;
            else {
                char *end;
                long v = strtol(a, &end, 10);
                if (*end || v == 0) { fail("-which wants all, first, last, N or -N"); goto done; }
                which = WHICH_N; which_n = (int) v;
            }
            w = w->wl_next->wl_next;
        } else if (cieq(o, "-edge")) {
            const char *a = w->wl_next ? w->wl_next->wl_word : NULL;
            if (!a) { fail("-edge wants rise, fall or both"); goto done; }
            if (cieq(a, "rise")) edge = EDGE_RISE;
            else if (cieq(a, "fall")) edge = EDGE_FALL;
            else if (cieq(a, "both")) edge = EDGE_BOTH;
            else { fail("-edge wants rise, fall or both"); goto done; }
            have_edge = 1;
            w = w->wl_next->wl_next;
        } else if (cieq(o, "-at")) {
            const char *a = w->wl_next ? w->wl_next->wl_word : NULL;
            if (!a) { fail("-at wants entry, exit or mid"); goto done; }
            if (cieq(a, "entry")) at = AT_ENTRY;
            else if (cieq(a, "exit")) at = AT_EXIT;
            else if (cieq(a, "mid")) at = AT_MID;
            else { fail("-at wants entry, exit or mid"); goto done; }
            have_at = 1;
            w = w->wl_next->wl_next;
        } else if (cieq(o, "-prominence")) {
            double p;
            char *pp = w->wl_next ? w->wl_next->wl_word : NULL;
            if (!pp || ft_numparse(&pp, FALSE, &p) < 0 || p < 0) {
                fail("-prominence wants a non-negative number");
                goto done;
            }
            prominence = p;
            w = w->wl_next->wl_next;
        } else if (cieq(o, "-raw")) {
            raw = 1;
            w = w->wl_next;
        } else if (cieq(o, "-output")) {
            wordlist *s = w->wl_next;
            while (s && !is_option(s->wl_word)) {
                if (nout < TRACK_MAX_EXPR)
                    outnames[nout++] = copy(s->wl_word);
                s = s->wl_next;
            }
            if (nout == 0) { fail("-output wants at least one name"); goto done; }
            w = s;
        } else {
            char buf[200];
            (void) snprintf(buf, sizeof buf, "unknown option '%s'", o);
            fail(buf);
            goto done;
        }
    }
    if (nout > nexpr) {
        fail("more -output names than expressions");
        goto done;
    }

    /* ---- the plot */
    if (analysis) {
        pl = find_plot(analysis);
        if (!pl) {
            struct plot *q;
            fprintf(cp_err, "Error: track: -analysis %s matches no plot; there are:", analysis);
            for (q = plot_list; q; q = q->pl_next)
                if (q->pl_typename && !cieq(q->pl_typename, "const"))
                    fprintf(cp_err, " %s", q->pl_typename);
            fprintf(cp_err, "\n");
            fail(NULL);
            goto done;
        }
    } else {
        pl = plot_cur;
    }
    if (!pl || !pl->pl_scale) {
        fail("no plot with a scale to track on");
        goto done;
    }
    if (pl->pl_scale->v_numdims > 1 || pl->pl_ndims > 1) {
        fail("the plot is multi-dimensional (a nested sweep); track the per-point plots `sweep` keeps instead");
        goto done;
    }
    scale = pl->pl_scale;
    n = scale->v_length;
    if (isreal(scale)) {
        x = scale->v_realdata;
    } else {
        /* an ac plot keeps `frequency` as a complex vector with zero imaginary
           parts; take the real parts, and refuse a scale that is truly complex */
        xown = TMALLOC(double, n > 0 ? n : 1);
        for (i = 0; i < n; i++) {
            if (scale->v_compdata[i].cx_imag != 0.0) {
                fail("the plot's scale is complex-valued");
                goto done;
            }
            xown[i] = scale->v_compdata[i].cx_real;
        }
        x = xown;
    }
    if (n < 2) {
        fail("the scale has fewer than two samples");
        goto done;
    }
    ascending = x[n - 1] >= x[0];
    /* a nested dc sweep comes out as ONE vector whose scale restarts at every
       outer step -- ngspice does not mark it multi-dimensional -- so a scale
       that turns back on itself is the sign of a multi-segment plot */
    for (i = 1; i < n; i++)
        if (ascending ? x[i] < x[i - 1] : x[i] > x[i - 1]) {
            fail("the scale is not monotonic (a nested sweep); track the per-point plots `sweep` keeps instead");
            goto done;
        }
    logx = (scale->v_gridtype == GRID_XLOG || scale->v_gridtype == GRID_LOGLOG);
    plot_cur = pl;                           /* evaluate in the chosen plot */

    /* ---- the range: the samples inside it plus one bracketing sample each side */
    if (have_range) {
        double lo = r0 < r1 ? r0 : r1, hi = r0 < r1 ? r1 : r0;
        i0 = -1; i1 = -1;
        for (i = 0; i < n; i++)
            if (x[i] >= lo && x[i] <= hi) {
                if (i0 < 0) i0 = i;
                i1 = i;
            }
        if (i0 < 0) {
            fail("no sample of the scale lies in -range");
            goto done;
        }
        if (i0 > 0) i0--;
        if (i1 < n - 1) i1++;
    } else {
        i0 = 0; i1 = n - 1;
    }

    /* ---- the expressions */
    vals = TMALLOC(double *, nexpr);
    for (e = 0; e < nexpr; e++)
        vals[e] = NULL;
    for (e = 0; e < nexpr; e++) {
        vals[e] = eval_real(exprs[e], n, "expression", &vtypes[e]);
        if (!vals[e]) { fail(NULL); goto done; }
    }

    /* ---- the spec */
    hits = TMALLOC(struct hit, n + 1);
    if (!spec) {
        kind = SPEC_ALL;
        specname = copy("every sample");
        for (i = i0; i <= i1; i++) {
            if (have_range) {
                double lo = r0 < r1 ? r0 : r1, hi = r0 < r1 ? r1 : r0;
                if (x[i] < lo || x[i] > hi)
                    continue;
            }
            hits[nhits].x = x[i]; hits[nhits].x_out = x[i]; hits[nhits].index = i;
            hits[nhits].lo = hits[nhits].hi = i; hits[nhits].edge = 0; hits[nhits].yext = 0;
            nhits++;
        }
    } else {
        char *s = spec;
        const char *cmp;
        int is_loc = 0;
        /* a bare locator, or a locator applied to another expression */
        for (k = 0; k < 4; k++) {
            static const char *names[4] = { "localmax", "localmin", "globalmax", "globalmin" };
            size_t ln = strlen(names[k]);
            if (strncasecmp(s, names[k], ln) == 0 && (s[ln] == '\0' || s[ln] == '(')) {
                const char *inner = s + ln;
                want_max = (k == 0 || k == 2);
                global = (k >= 2);
                is_loc = 1;
                if (*inner == '(') {
                    size_t il = strlen(inner);
                    if (il < 2 || inner[il - 1] != ')') { fail("unbalanced locator argument"); goto done; }
                    locexpr = trim_copy(inner + 1, il - 2);
                } else {
                    locexpr = copy(exprs[0]);
                }
                break;
            }
        }
        if (is_loc) {
            int *lo = TMALLOC(int, n), *hi = TMALLOC(int, n), nh;
            kind = SPEC_EXTREMUM;
            specname = copy(spec);
            loc = eval_real(locexpr, n, "locator argument", NULL);
            if (!loc) { tfree(lo); tfree(hi); fail(NULL); goto done; }
            if (!global && i1 - i0 + 1 < 3) {
                tfree(lo); tfree(hi);
                fail("a local extremum needs at least three samples in the range");
                goto done;
            }
            nh = cx_extrema_walk(loc, n, i0, i1, want_max, global, lo, hi);
            /* -prominence: the hysteresis rule. Walking the range, the signal
               must first move p away from a running extremum of the OTHER
               kind before a candidate is taken, and the candidate is
               confirmed only once the signal has moved p past it in the
               other direction again -- alternating turning points, order N,
               deterministic. Ripple riding on a flank never counts: every
               small peak there is followed by a higher one before the signal
               has fallen p below it, or is preceded by a higher one the
               signal has not risen p above. A confirmed extremum keeps the
               plateau the raw walk found for it, if any. */
            if (prominence > 0.0 && !global) {
                int *rlo = lo, *rhi = hi, nraw = nh, j;
                int *clo = TMALLOC(int, n), *chi = TMALLOC(int, n), nc = 0;
                int seeking = 0;                 /* 1: a candidate of the wanted kind is open */
                double cand = 0.0, other;
                int icand = -1;
                other = loc[i0];
                for (j = i0; j <= i1; j++) {
                    double y = loc[j];
                    if (!seeking) {
                        /* track the running extremum of the other kind; open a
                           candidate once the signal has moved p away from it */
                        if (want_max ? y < other : y > other)
                            other = y;
                        else if (want_max ? (y - other >= prominence) : (other - y >= prominence)) {
                            seeking = 1;
                            cand = y;
                            icand = j;
                        }
                    } else {
                        if (want_max ? y > cand : y < cand) {
                            cand = y;
                            icand = j;
                        } else if (want_max ? (cand - y >= prominence) : (y - cand >= prominence)) {
                            /* confirmed; keep its plateau if the raw walk saw one */
                            int a = icand, b = icand, r;
                            for (r = 0; r < nraw; r++)
                                if (rlo[r] <= icand && icand <= rhi[r]) {
                                    a = rlo[r]; b = rhi[r];
                                    break;
                                }
                            clo[nc] = a; chi[nc] = b; nc++;
                            seeking = 0;
                            other = y;
                        }
                    }
                }
                for (j = 0; j < nc; j++) {
                    lo[j] = clo[j];
                    hi[j] = chi[j];
                }
                nh = nc;
                tfree(clo); tfree(chi);
            }
            for (k = 0; k < nh; k++) {
                int a = lo[k], b = hi[k];
                double xh = 0.5 * (x[a] + x[b]), yh = loc[a];
                if (have_range) {
                    double rlo = r0 < r1 ? r0 : r1, rhi = r0 < r1 ? r1 : r0;
                    if (xh < rlo || xh > rhi)
                        continue;
                }
                if (a == b && !raw && !global && a > 0 && a < n - 1) {
                    /* the parabola through samples a-1, a, a+1 */
                    double xm = x[a - 1], x0 = x[a], xp = x[a + 1];
                    double ym = loc[a - 1], y0 = loc[a], yp = loc[a + 1];
                    double denom = (xm - x0) * (xm - xp) * (x0 - xp);
                    if (denom != 0.0) {
                        double A = (xp * (y0 - ym) + x0 * (ym - yp) + xm * (yp - y0)) / denom;
                        double B = (xp * xp * (ym - y0) + x0 * x0 * (yp - ym) + xm * xm * (y0 - yp)) / denom;
                        double C = (x0 * xp * (x0 - xp) * ym + xp * xm * (xp - xm) * y0 + xm * x0 * (xm - x0) * yp) / denom;
                        if (A != 0.0) {
                            double xv = -B / (2.0 * A);
                            if ((xv >= xm && xv <= xp) || (xv <= xm && xv >= xp)) {
                                xh = xv;
                                yh = A * xv * xv + B * xv + C;
                            }
                        }
                    }
                }
                hits[nhits].x = xh; hits[nhits].x_out = xh; hits[nhits].index = a;
                hits[nhits].lo = a; hits[nhits].hi = b; hits[nhits].edge = 0; hits[nhits].yext = yh;
                nhits++;
            }
            tfree(lo); tfree(hi);
        } else if ((cmp = find_comparison(s, &op, &oplen)) != NULL) {
            /* a crossing or a region: d = lhs - rhs */
            double *dl, *dr;
            lhs = trim_copy(s, (size_t) (cmp - s));
            rhs = trim_copy(cmp + oplen, strlen(cmp + oplen));
            if (!*lhs || !*rhs) { fail("the spec needs an expression on each side of the comparison"); goto done; }
            dl = eval_real(lhs, n, "spec left side", NULL);
            if (!dl) { fail(NULL); goto done; }
            dr = eval_real(rhs, n, "spec right side", NULL);
            if (!dr) { tfree(dl); fail(NULL); goto done; }
            d = TMALLOC(double, n);
            for (i = 0; i < n; i++)
                d[i] = dl[i] - dr[i];
            tfree(dl); tfree(dr);
            specname = copy(spec);
            if (op[0] == '=') {
                kind = SPEC_CROSSING;
                for (i = i0 + 1; i <= i1; i++) {
                    int sgn0 = (d[i - 1] > 0) - (d[i - 1] < 0), sgn1 = (d[i] > 0) - (d[i] < 0);
                    double xh;
                    int ed;
                    if (sgn1 == 0 && sgn0 == 0)
                        continue;
                    if (sgn1 == 0) {
                        xh = x[i]; ed = sgn0 < 0 ? +1 : -1;
                    } else if (sgn0 != 0 && sgn0 != sgn1) {
                        xh = interp_zero(x, d, i, logx); ed = sgn1 > 0 ? +1 : -1;
                    } else if (sgn0 == 0) {
                        continue;                /* the exact zero was reported at i-1 */
                    } else
                        continue;
                    if (have_range) {
                        double rlo = r0 < r1 ? r0 : r1, rhi = r0 < r1 ? r1 : r0;
                        if (xh < rlo || xh > rhi)
                            continue;
                    }
                    if (edge == EDGE_RISE && ed < 0) continue;
                    if (edge == EDGE_FALL && ed > 0) continue;
                    hits[nhits].x = xh; hits[nhits].x_out = xh; hits[nhits].index = i;
                    hits[nhits].lo = hits[nhits].hi = i; hits[nhits].edge = ed; hits[nhits].yext = 0;
                    nhits++;
                }
            } else {
                unsigned char *b = TMALLOC(unsigned char, n);
                kind = SPEC_REGION;
                for (i = 0; i < n; i++) {
                    if (op[0] == '<')
                        b[i] = oplen == 2 ? (d[i] <= 0) : (d[i] < 0);
                    else
                        b[i] = oplen == 2 ? (d[i] >= 0) : (d[i] > 0);
                }
                for (i = i0; i <= i1; i++) {
                    int j;
                    double xin, xout;
                    if (!b[i] || (i > i0 && b[i - 1]))
                        continue;
                    j = i;
                    while (j + 1 <= i1 && b[j + 1])
                        j++;
                    xin = (i > 0 && !b[i - 1]) ? interp_zero(x, d, i, logx) : x[i];
                    xout = (j < n - 1 && !b[j + 1]) ? interp_zero(x, d, j + 1, logx) : x[j];
                    if (have_range) {
                        double rlo = r0 < r1 ? r0 : r1, rhi = r0 < r1 ? r1 : r0;
                        if (xin < rlo) xin = rlo;
                        if (xout > rhi) xout = rhi;
                        if (xin > rhi || xout < rlo)
                            continue;
                    }
                    hits[nhits].x = xin; hits[nhits].x_out = xout; hits[nhits].index = i;
                    hits[nhits].lo = i; hits[nhits].hi = j; hits[nhits].edge = 0; hits[nhits].yext = 0;
                    nhits++;
                }
                tfree(b);
            }
        } else {
            /* a boolean spec: a region from the 0/1 vector, sample-midpoint boundaries */
            double *bv = eval_real(s, n, "spec", NULL);
            if (!bv) { fail(NULL); goto done; }
            kind = SPEC_BOOL;
            midpoints = 1;
            specname = copy(spec);
            for (i = i0; i <= i1; i++) {
                int j;
                double xin, xout;
                if (bv[i] == 0.0 || (i > i0 && bv[i - 1] != 0.0))
                    continue;
                j = i;
                while (j + 1 <= i1 && bv[j + 1] != 0.0)
                    j++;
                xin = (i > 0) ? 0.5 * (x[i - 1] + x[i]) : x[i];
                xout = (j < n - 1) ? 0.5 * (x[j] + x[j + 1]) : x[j];
                if (have_range) {
                    double rlo = r0 < r1 ? r0 : r1, rhi = r0 < r1 ? r1 : r0;
                    if (xin < rlo) xin = rlo;
                    if (xout > rhi) xout = rhi;
                    if (xin > rhi || xout < rlo)
                        continue;
                }
                hits[nhits].x = xin; hits[nhits].x_out = xout; hits[nhits].index = i;
                hits[nhits].lo = i; hits[nhits].hi = j; hits[nhits].edge = 0; hits[nhits].yext = 0;
                nhits++;
            }
            tfree(bv);
        }
    }
    if (have_edge && kind != SPEC_CROSSING) {
        fail("-edge applies to a crossing spec (lhs==rhs) only");
        goto done;
    }
    if (have_at && kind != SPEC_REGION && kind != SPEC_BOOL) {
        fail("-at applies to a region spec only");
        goto done;
    }
    if (prominence > 0.0 && kind != SPEC_EXTREMUM) {
        fail("-prominence applies to a local extremum spec only");
        goto done;
    }
    if (nhits == 0) {
        if (!track_quiet) {              /* a miss is a normal outcome under montecarlo -track */
            fprintf(cp_err, "Error: track: no hit of %s on %s%s\n", specname, pl->pl_typename,
                    have_range ? " in the range" : "");
            fail(NULL);
            track_error = 0;
        }
        goto done;
    }

    /* ---- -which */
    if (which != WHICH_ALL) {
        int sel;
        if (which == WHICH_FIRST) sel = 0;
        else if (which == WHICH_LAST) sel = nhits - 1;
        else sel = which_n > 0 ? which_n - 1 : nhits + which_n;
        if (sel < 0 || sel >= nhits) {
            char buf[120];
            (void) snprintf(buf, sizeof buf, "-which %d selects nothing: %d hit%s", which_n, nhits, nhits == 1 ? "" : "s");
            fail(buf);
            goto done;
        }
        hits[0] = hits[sel];
        nhits = 1;
    }

    /* ---- the plot */
    npl = plot_alloc("track");
    plot_new(npl);
    npl->pl_title = copy(pl->pl_title ? pl->pl_title : "track");
    npl->pl_name = tprintf("Track: %s on %s", specname, pl->pl_typename);
    /* Enhancement-584: a dc sweep's scale is `v-sweep`, a name no expression can
     * spell (`print track1.v-sweep` is a subtraction). The track plot's copy is
     * `v_sweep`; every other scale name (time, frequency) is already plain. */
    sname = copy(scale->v_name);
    for (char *q = sname; *q; q++)
        if (!isalnum_c(*q) && *q != '_')
            *q = '_';
    {
        struct dvec *sv = dvec_alloc(copy(sname), (int) scale->v_type,
                                     VF_REAL | VF_PERMANENT, nhits, NULL);
        struct dvec *iv, *xo = NULL, *wv = NULL, *ev = NULL;
        struct plot *keep = plot_cur;
        sv->v_gridtype = scale->v_gridtype;
        for (k = 0; k < nhits; k++)
            sv->v_realdata[k] = hits[k].x;
        plot_cur = npl;                      /* vec_new() files into plot_cur */
        vec_new(sv);
        npl->pl_scale = sv;
        for (e = 0; e < nexpr; e++) {
            char *nm;
            struct dvec *vv;
            if (e < nout)
                nm = copy(outnames[e]);
            else if (nexpr == 1)
                nm = copy("value");
            else
                nm = tprintf("value%d", e + 1);
            vv = dvec_alloc(nm, vtypes[e], VF_REAL | VF_PERMANENT, nhits, NULL);
            for (k = 0; k < nhits; k++) {
                double xq = hits[k].x;
                int idx = hits[k].index;
                if (kind == SPEC_REGION || kind == SPEC_BOOL) {
                    if (at == AT_EXIT) xq = hits[k].x_out;
                    else if (at == AT_MID) xq = 0.5 * (hits[k].x + hits[k].x_out);
                    idx = bracket_index(x, n, xq, ascending);
                }
                if (kind == SPEC_EXTREMUM && loc && strcmp(exprs[e], locexpr) == 0 && !raw && hits[k].lo == hits[k].hi)
                    vv->v_realdata[k] = hits[k].yext;      /* the refined extremum itself */
                else if (kind == SPEC_ALL || (kind == SPEC_EXTREMUM && (raw || hits[k].lo != hits[k].hi)))
                    vv->v_realdata[k] = vals[e][kind == SPEC_EXTREMUM ? (hits[k].lo + hits[k].hi) / 2 : idx];
                else
                    vv->v_realdata[k] = interp_at(x, vals[e], bracket_index(x, n, xq, ascending), xq, n, logx);
            }
            vec_new(vv);
        }
        iv = dvec_alloc(copy("index"), SV_NOTYPE, VF_REAL | VF_PERMANENT, nhits, NULL);
        for (k = 0; k < nhits; k++)
            iv->v_realdata[k] = hits[k].index;
        vec_new(iv);
        if (kind == SPEC_REGION || kind == SPEC_BOOL) {
            xo = dvec_alloc(copy("x_out"), (int) scale->v_type, VF_REAL | VF_PERMANENT, nhits, NULL);
            wv = dvec_alloc(copy("width"), (int) scale->v_type, VF_REAL | VF_PERMANENT, nhits, NULL);
            for (k = 0; k < nhits; k++) {
                xo->v_realdata[k] = hits[k].x_out;
                wv->v_realdata[k] = hits[k].x_out - hits[k].x;
            }
            vec_new(xo);
            vec_new(wv);
        }
        if (kind == SPEC_CROSSING && edge == EDGE_BOTH) {
            ev = dvec_alloc(copy("edge"), SV_NOTYPE, VF_REAL | VF_PERMANENT, nhits, NULL);
            for (k = 0; k < nhits; k++)
                ev->v_realdata[k] = hits[k].edge;
            vec_new(ev);
        }
        plot_cur = keep;
    }

    cp_vset("track_plot", CP_STRING, npl->pl_typename);   /* Enhancement-581 */
    cp_vset("track_hits", CP_NUM, &nhits);
    if (track_quiet)                                        /* Enhancement-582 */
        goto quiet;

    /* ---- the summary */
    fprintf(cp_out, "%s: %d hit%s of %s on %s", npl->pl_typename, nhits, nhits == 1 ? "" : "s",
            specname, pl->pl_typename);
    if (have_range)
        fprintf(cp_out, " in [%g, %g]", r0 < r1 ? r0 : r1, r0 < r1 ? r1 : r0);
    if (midpoints)
        fprintf(cp_out, " (boundaries at sample midpoints)");
    if (kind == SPEC_EXTREMUM && strcmp(locexpr, exprs[0]) == 0 && !strchr(spec, '('))
        fprintf(cp_out, " (applied to %s)", exprs[0]);
    fprintf(cp_out, "\n");
    if (nexpr > 1 || nout > 0) {
        fprintf(cp_out, "   ");
        for (e = 0; e < nexpr; e++) {
            if (e < nout)
                fprintf(cp_out, " %s=%s", outnames[e], exprs[e]);
            else if (nexpr == 1)
                fprintf(cp_out, " value=%s", exprs[e]);
            else
                fprintf(cp_out, " value%d=%s", e + 1, exprs[e]);
        }
        fprintf(cp_out, "\n");
    }
    if (ft_batchmode) {
        /* one row per hit, the vectors in the order they were made (the
           plot's list is newest-first) */
        struct dvec *vv, **order;
        int nv = 0;
        for (vv = npl->pl_dvecs; vv; vv = vv->v_next)
            nv++;
        order = TMALLOC(struct dvec *, nv > 0 ? nv : 1);
        for (vv = npl->pl_dvecs, i = nv - 1; vv; vv = vv->v_next, i--)
            order[i] = vv;
        for (k = 0; k < nhits && k < 50; k++) {
            fprintf(cp_out, "  %s=%.6g", sname, hits[k].x);
            for (i = 0; i < nv; i++)
                if (order[i] != npl->pl_scale)
                    fprintf(cp_out, " %s=%.6g", order[i]->v_name, order[i]->v_realdata[k]);
            fprintf(cp_out, "\n");
        }
        if (nhits > 50)
            fprintf(cp_out, "  ... and %d more (print %s.%s)\n", nhits - 50, npl->pl_typename, sname);
        tfree(order);
    }
quiet:
    ok = 1;

done:
    plot_cur = saved_cur;
    for (e = 0; e < nexpr; e++) {
        tfree(exprs[e]);
        if (vals) tfree(vals[e]);
    }
    for (e = 0; e < nout; e++)
        tfree(outnames[e]);
    tfree(vals);
    tfree(spec); tfree(analysis); tfree(d); tfree(loc); tfree(hits); tfree(xown);
    tfree(specname); tfree(lhs); tfree(rhs); tfree(locexpr); tfree(sname);
    NG_IGNORE(ok);
}
