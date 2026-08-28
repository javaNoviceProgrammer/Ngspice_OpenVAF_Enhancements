/**********
Enhancement-207: `eye` -- eye-diagram / jitter analysis for high-speed links.

Post-processes a transient waveform into an eye diagram and the standard
serial-link quality metrics. Given a data signal and its unit interval (bit
period) UI, it

  * auto-detects the two logic rails (level0 / level1) and the decision threshold,
  * finds every threshold crossing (linearly interpolated),
  * estimates the UI phase and each crossing's time-interval error (TIE) ->
    jitter RMS and peak-to-peak,
  * measures the eye HEIGHT (vertical opening at the sampling instant) and the eye
    WIDTH (UI - jitter_pp), plus the eye width at BER 1e-12 (Gaussian-RJ tail), and
  * folds the waveform modulo 2*UI into the `eye_wave` vs `eye_t` vectors, whose
    scatter plot IS the eye diagram (`plot eye_wave vs eye_t`).

Usage:
  eye <expr> -ui <T> [-tstart <t0>] [-threshold <vth>] [-window <frac>]

All results are published as permanent vectors (eye_height, eye_width,
eye_jitter_rms, eye_jitter_pp, eye_level0, eye_level1, eye_amplitude,
eye_threshold, eye_crossings, eye_width_ber12, eye_ui).
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/wordlist.h"
#include "ngspice/fteext.h"
#include "ngspice/cpextern.h"

#include "com_eye.h"

/* SPICE-style number (understands k/meg/u/n/p... suffixes). */
static double eye_num(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}

/* Publish a scalar as a permanent length-1 vector + shell variable. */
static void eye_set(const char *name, double val)
{
    struct dvec *v;
    cp_vset(name, CP_REAL, &val);
    v = dvec_alloc(copy(name), SV_NOTYPE, (short) (VF_REAL | VF_PERMANENT), 1, NULL);
    if (v) { v->v_realdata[0] = val; vec_new(v); }
}

static int dcmp(const void *a, const void *b)
{
    double x = *(const double *) a, y = *(const double *) b;
    return (x < y) ? -1 : (x > y) ? 1 : 0;
}

void com_eye(wordlist *wl)
{
    char *expr = NULL;
    double ui = 0.0, tstart = 0.0, thresh = 0.0, window = 0.05;
    int have_thresh = 0;

    if (wl == NULL || wl->wl_word == NULL) {
        fprintf(cp_err, "Usage: eye <expr> -ui <T> [-tstart <t0>] [-threshold <vth>] "
                        "[-window <frac>]\n");
        return;
    }
    expr = copy(wl->wl_word);
    wl = wl->wl_next;
    while (wl && wl->wl_word) {
        const char *w = wl->wl_word;
        if (eq(w, "-ui")) {
            if (!wl->wl_next) { fprintf(cp_err, "eye: -ui needs a value\n"); goto done; }
            /* Enhancement-502: `-ui nan` walked through the `<= 0` test below
             * and reported an eye HEIGHT OF 0 -- a fully closed link -- with a
             * `nan` width. `-tstart nan` was worse: it was never checked at
             * all, and since the "skip samples before tstart" test is also a
             * comparison, NaN never skipped, so the startup transient the flag
             * exists to exclude was folded into the eye and RMS jitter came
             * back 660x larger, with no diagnostic. */
            wl = wl->wl_next;
            if (!ft_argpos("eye", "-ui", wl->wl_word, &ui)) goto done;
            wl = wl->wl_next;
        } else if (eq(w, "-tstart")) {
            if (!wl->wl_next) { fprintf(cp_err, "eye: -tstart needs a value\n"); goto done; }
            wl = wl->wl_next;
            if (!ft_argfinite("eye", "-tstart", wl->wl_word, &tstart)) goto done;
            wl = wl->wl_next;
        } else if (eq(w, "-threshold") || eq(w, "-thresh")) {
            if (!wl->wl_next) { fprintf(cp_err, "eye: -threshold needs a value\n"); goto done; }
            wl = wl->wl_next;
            if (!ft_argfinite("eye", "-threshold", wl->wl_word, &thresh)) goto done;
            have_thresh = 1; wl = wl->wl_next;
        } else if (eq(w, "-window")) {
            if (!wl->wl_next) { fprintf(cp_err, "eye: -window needs a value\n"); goto done; }
            wl = wl->wl_next;
            if (!ft_argpos("eye", "-window", wl->wl_word, &window)) goto done;
            wl = wl->wl_next;
        } else {
            fprintf(cp_err, "eye: unexpected token '%s'\n", w); goto done;
        }
    }
    if (!(ui > 0.0)) { fprintf(cp_err, "eye: -ui <bit period> is required (and > 0)\n"); goto done; }
    /* Enhancement-502: a window outside (0, 0.5) silently became the default,
     * so `-window 5` and `-window -1` measured the eye at 5% and said nothing.
     * The clamp stays -- it is the documented behaviour for the DEFAULT -- but
     * a value the user actually wrote and that cannot be used is now named. */
    if (!(window > 0.0) || window >= 0.5) {
        fprintf(cp_err, "eye: -window is the fraction of the UI sampled at the "
                        "eye centre and must be in (0, 0.5); using the default "
                        "0.05 instead of %g\n", window);
        window = 0.05;
    }

    /* ---- read the waveform (values) and its time scale ---- */
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    if (!pn) { fprintf(cp_err, "eye: cannot parse '%s'\n", expr); goto done; }
    struct dvec *dv = ft_evaluate(pn);
    if (!dv || dv->v_length < 4) {
        fprintf(cp_err, "eye: '%s' has no transient data\n", expr);
        if (pn) { if (!pn->pn_value && dv) vec_free(dv); free_pnode(pn); }
        goto done;
    }
    struct dvec *sc = dv->v_scale ? dv->v_scale : (plot_cur ? plot_cur->pl_scale : NULL);
    if (!sc) { fprintf(cp_err, "eye: no time scale for '%s'\n", expr);
               if (!pn->pn_value) vec_free(dv); free_pnode(pn); goto done; }

    int n = dv->v_length, i;
    double *t = TMALLOC(double, n), *y = TMALLOC(double, n);
    for (i = 0; i < n; i++) {
        y[i] = isreal(dv) ? dv->v_realdata[i]
                          : hypot(dv->v_compdata[i].cx_real, dv->v_compdata[i].cx_imag);
        t[i] = (i < sc->v_length)
               ? (isreal(sc) ? sc->v_realdata[i]
                  : hypot(sc->v_compdata[i].cx_real, sc->v_compdata[i].cx_imag))
               : (double) i;
    }
    if (!pn->pn_value) vec_free(dv);
    free_pnode(pn);

    /* first sample index at/after tstart */
    int i0 = 0;
    while (i0 < n && t[i0] < tstart) i0++;
    if (n - i0 < 4) { fprintf(cp_err, "eye: not enough data after tstart\n"); goto freeit; }

    /* ---- logic rails (level0/level1) from the 20th/80th percentiles ---- */
    int m = n - i0;
    double *ys = TMALLOC(double, m);
    for (i = 0; i < m; i++) ys[i] = y[i0 + i];
    qsort(ys, (size_t) m, sizeof(double), dcmp);
    int q = m / 5; if (q < 1) q = 1;
    double lo_sum = 0, hi_sum = 0;
    for (i = 0; i < q; i++) { lo_sum += ys[i]; hi_sum += ys[m - 1 - i]; }
    double level0 = lo_sum / q, level1 = hi_sum / q;
    double amp = level1 - level0;
    tfree(ys);
    if (!have_thresh) thresh = 0.5 * (level0 + level1);

    /* ---- threshold crossings (linear interpolation) ---- */
    double *tc = TMALLOC(double, m);
    int nc = 0;
    for (i = i0; i < n - 1; i++) {
        double a = y[i] - thresh, b = y[i + 1] - thresh;
        if ((a < 0 && b >= 0) || (a > 0 && b <= 0)) {
            double dt = t[i + 1] - t[i];
            double frac = (dt != 0.0) ? (thresh - y[i]) / (y[i + 1] - y[i]) : 0.0;
            tc[nc++] = t[i] + frac * dt;
        }
    }
    if (nc < 2) {
        fprintf(cp_err, "eye: only %d threshold crossing(s) -- check -ui / -threshold / signal\n", nc);
        tfree(tc); goto freeit;
    }

    /* ---- UI phase (circular mean of crossings mod UI) and TIE jitter ---- */
    double sx = 0, sy = 0;
    for (i = 0; i < nc; i++) {
        double frac = tc[i] / ui - floor(tc[i] / ui);   /* in [0,1) */
        sx += sin(2 * M_PI * frac); sy += cos(2 * M_PI * frac);
    }
    double phase = atan2(sx, sy) / (2 * M_PI) * ui;      /* in (-UI/2, UI/2] */
    if (phase < 0) phase += ui;

    double tie_min = 1e300, tie_max = -1e300, tie_sum = 0, tie_sq = 0;
    for (i = 0; i < nc; i++) {
        double k = floor((tc[i] - phase) / ui + 0.5);
        double tie = tc[i] - (phase + k * ui);
        tie_sum += tie; tie_sq += tie * tie;
        if (tie < tie_min) tie_min = tie;
        if (tie > tie_max) tie_max = tie;
    }
    double tie_mean = tie_sum / nc;
    double jvar = tie_sq / nc - tie_mean * tie_mean;
    double jitter_rms = jvar > 0 ? sqrt(jvar) : 0.0;
    double jitter_pp = tie_max - tie_min;

    /* ---- eye height: vertical opening at the sampling instant (eye centre) ---- */
    double samp = phase + 0.5 * ui;                      /* midway between transitions */
    double hi_min = 1e300, lo_max = -1e300;
    int nhi = 0, nlo = 0;
    for (i = i0; i < n; i++) {
        double tm = (t[i] - samp) / ui;
        tm -= floor(tm + 0.5);                            /* distance to nearest sampling instant, in UI */
        if (fabs(tm) <= window) {
            if (y[i] > thresh) { if (y[i] < hi_min) hi_min = y[i]; nhi++; }
            else               { if (y[i] > lo_max) lo_max = y[i]; nlo++; }
        }
    }
    double eye_height = (nhi > 0 && nlo > 0) ? (hi_min - lo_max) : 0.0;

    /* ---- eye width (at threshold) + eye width at BER 1e-12 (Gaussian RJ) ---- */
    double eye_width = ui - jitter_pp; if (eye_width < 0) eye_width = 0;
    double eye_width_ber12 = ui - 14.069 * jitter_rms;   /* +/-7.035 sigma each edge */
    if (eye_width_ber12 < 0) eye_width_ber12 = 0;

    /* ---- publish everything into a FRESH 'eye' plot (as `stb` does). The folded
     * eye_wave and its scale eye_t must live in their own plot: putting the length-m
     * eye vectors in the transient plot (scale = the full, much longer time vector)
     * makes `wrdata`/`plot` pair mismatched-length vectors and crash. The length-1
     * scalar metrics coexist in the same plot (montecarlo likewise stores length-1
     * results beside a longer scale). The plot is left current so the user's
     * `print eye_height` / `plot eye_wave vs eye_t` both resolve. ---- */
    {
        struct plot *pl = plot_alloc("eye");
        struct dvec *evt, *evw;
        double *et = TMALLOC(double, m), *ev = TMALLOC(double, m);
        pl->pl_name  = copy("Eye diagram");
        pl->pl_title = copy(ft_curckt && ft_curckt->ci_name ? ft_curckt->ci_name : "eye");
        plot_new(pl);
        plot_setcur(pl->pl_typename);
        for (i = 0; i < m; i++) {
            double tf = (t[i0 + i] - phase + 0.5 * ui);
            tf -= 2.0 * ui * floor(tf / (2.0 * ui));       /* fold into [0, 2 UI) */
            et[i] = tf; ev[i] = y[i0 + i];
        }
        evt = dvec_alloc(copy("eye_t"), SV_TIME, (short) (VF_REAL | VF_PERMANENT), m, NULL);
        for (i = 0; i < m; i++) evt->v_realdata[i] = et[i];
        vec_new(evt);                                      /* first permanent -> scale */
        evw = dvec_alloc(copy("eye_wave"), SV_VOLTAGE, (short) (VF_REAL | VF_PERMANENT), m, NULL);
        for (i = 0; i < m; i++) evw->v_realdata[i] = ev[i];
        vec_new(evw);
        tfree(et); tfree(ev);
    }
    eye_set("eye_ui", ui);
    eye_set("eye_level0", level0);
    eye_set("eye_level1", level1);
    eye_set("eye_amplitude", amp);
    eye_set("eye_threshold", thresh);
    eye_set("eye_crossings", (double) nc);
    eye_set("eye_height", eye_height);
    eye_set("eye_width", eye_width);
    eye_set("eye_width_ber12", eye_width_ber12);
    eye_set("eye_jitter_rms", jitter_rms);
    eye_set("eye_jitter_pp", jitter_pp);

    fprintf(cp_out,
            "eye: UI %.4g s, %d crossings, levels [%.4g, %.4g] (amp %.4g), threshold %.4g\n"
            "  eye height : %.4g  (%.1f%% of amplitude)\n"
            "  eye width  : %.4g s  (%.1f%% of UI);  at BER 1e-12: %.4g s\n"
            "  jitter     : %.4g s rms, %.4g s pp\n"
            "  folded eye in 'eye_wave' vs 'eye_t'  (plot eye_wave vs eye_t)\n",
            ui, nc, level0, level1, amp, thresh,
            eye_height, amp != 0 ? 100.0 * eye_height / amp : 0.0,
            eye_width, 100.0 * eye_width / ui, eye_width_ber12,
            jitter_rms, jitter_pp);

    tfree(tc);
freeit:
    tfree(t); tfree(y);
done:
    tfree(expr);
}
