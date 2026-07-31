/* Enhancement-198: the `stb` stability / loop-gain analysis.
 *
 * Middlebrook/Tian double injection measures a feedback loop's small-signal loop
 * gain T(f) WITHOUT breaking the loop's DC bias, correcting for the loading at
 * the break point (which a single injection cannot). The user marks the break
 * with a probe pair placed in the loop wire between the driving node A and the
 * loaded node B:
 *     Vprobe A B dc 0 ac 0     series 0 V source (carries the DC bias current)
 *     Iprobe 0 B dc 0 ac 0     shunt 0 A source, ground -> load node B
 * Both are DC-transparent. `stb <Vprobe> <Iprobe> <ac-sweep>` then runs two AC
 * sweeps and combines them:
 *     voltage injection (Vprobe ac=1, Iprobe ac=0):  Tv = -v(A)/v(B)
 *     current injection (Vprobe ac=0, Iprobe ac=1):  Ti = -i(Vprobe)/(i(Vprobe)+1)
 *     loop gain  T = (Tv*Ti - 1) / (Tv + Ti + 2)
 * T is stored as the complex vector `loopgain` (vs `frequency`) in a new `stb`
 * plot, and the phase margin (180 + phase(T) at |T| = 1) and gain margin
 * (-|T|_dB at phase = -180 deg) are reported. It reuses the AC analysis, so it
 * works under either linear solver.
 */

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/wordlist.h"
#include "ngspice/fteext.h"
#include "ngspice/cpextern.h"
#include "ngspice/cktdefs.h"
#include "ngspice/sim.h"

#include "com_stb.h"

/* ---- small complex helpers on ngcomplex_t ---- */
static ngcomplex_t stbcx(double re, double im) { ngcomplex_t r; r.cx_real = re; r.cx_imag = im; return r; }
static ngcomplex_t stbadd(ngcomplex_t a, ngcomplex_t b) { return stbcx(a.cx_real + b.cx_real, a.cx_imag + b.cx_imag); }
static ngcomplex_t stbmul(ngcomplex_t a, ngcomplex_t b)
{ return stbcx(a.cx_real * b.cx_real - a.cx_imag * b.cx_imag, a.cx_real * b.cx_imag + a.cx_imag * b.cx_real); }
static ngcomplex_t stbdiv(ngcomplex_t a, ngcomplex_t b)
{
    double d = b.cx_real * b.cx_real + b.cx_imag * b.cx_imag;
    if (d == 0.0) return stbcx(0.0, 0.0);
    return stbcx((a.cx_real * b.cx_real + a.cx_imag * b.cx_imag) / d,
              (a.cx_imag * b.cx_real - a.cx_real * b.cx_imag) / d);
}

/* Run one command synchronously, dispatching through the command table (as
 * com_optimize's opt_run_cmd -- cp_evloop would defer it). */
static void stb_run(const char *cmdstr)
{
    wordlist *wl = cp_lexer((char *) cmdstr);
    int i;
    if (!wl || !wl->wl_word) { if (wl) wl_free(wl); return; }
    for (i = 0; cp_coms[i].co_comname; i++)
        if (strcasecmp(cp_coms[i].co_comname, wl->wl_word) == 0)
            break;
    if (cp_coms[i].co_comname && cp_coms[i].co_func)
        cp_coms[i].co_func(wl->wl_next);
    wl_free(wl);
}

/* Evaluate an expression and copy its data into a fresh ngcomplex_t array (real
 * data promoted to complex). Returns NULL and *lenp = 0 on failure. */
static ngcomplex_t *stb_eval(const char *expr, int *lenp)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    ngcomplex_t *out = NULL;
    *lenp = 0;
    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1) {
            int n = v->v_length, i;
            out = TMALLOC(ngcomplex_t, n);
            for (i = 0; i < n; i++) {
                if (isreal(v)) { out[i] = stbcx(v->v_realdata[i], 0.0); }
                else           { out[i] = v->v_compdata[i]; }
            }
            *lenp = n;
        }
        if (v && !pn->pn_value)
            vec_free(v);
        free_pnode(pn);
    }
    return out;
}

void com_stb(wordlist *wl)
{
    CKTcircuit *ckt;
    char *vname, *iname, *vlookup, *sweep, *nA, *nB;
    char cmd[512], eA[256], eB[256], eI[256];
    GENinstance *inst;
    CKTnode *ndA, *ndB;
    IFuid uidA, uidB;
    ngcomplex_t *vA = NULL, *vB = NULL, *ibr = NULL, *freqc = NULL, *T = NULL;
    double *mag = NULL, *ph = NULL;
    int nA_len = 0, nB_len = 0, nI_len = 0, nF_len = 0, n, i;
    int have_pm = 0, have_gm = 0;
    double pm = 0.0, gm = 0.0, fpm = 0.0, fgm = 0.0;
    double vprobe_acmag = 0.0, iprobe_acmag = 0.0;  /* Enhancement-381 */
    wordlist *sw;

    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "stb: no circuit loaded.\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    if (!wl || !wl->wl_next || !wl->wl_next->wl_next) {
        fprintf(cp_err, "usage: stb <Vprobe> <Iprobe> "
                        "(dec|oct|lin <N> <fstart> <fstop>)\n"
                        "  Vprobe: series 0 V probe in the loop, +node = driver "
                        "(A), -node = load (B).\n"
                        "  Iprobe: shunt 0 A probe, ground -> load node B.\n");
        return;
    }
    vname = copy(wl->wl_word);
    iname = copy(wl->wl_next->wl_word);
    sw = wl->wl_next->wl_next;
    sweep = wl_flatten(sw);                 /* the AC sweep spec, verbatim */

    /* locate the voltage probe and its two terminal nodes (1 = +, 2 = -).
     * Do NOT use INPretrieve here: it replaces vlookup with the INTERNED symbol
     * table string (the same memory the source's own name field points at) and
     * does not free the old copy, so the tfree(vlookup) below would double-free
     * the source's live name (a latent use-after-free -- it never bit because
     * stb runs once with no re-setup, but it corrupts the symbol table).  ngspice
     * stores instance names lowercased, so lowercasing a private copy resolves
     * the probe (now also case-insensitively) without touching interned memory. */
    vlookup = copy(vname);
    { char *p; for (p = vlookup; *p; p++) *p = (char) tolower((unsigned char) *p); }
    inst = ft_sim->findInstance(ckt, vlookup);
    if (!inst) {
        fprintf(cp_err, "stb: no such probe source '%s'.\n", vname);
        goto done;
    }
    if (CKTinst2Node(ckt, inst, 1, &ndA, &uidA) != OK ||
        CKTinst2Node(ckt, inst, 2, &ndB, &uidB) != OK) {
        fprintf(cp_err, "stb: '%s' is not a two-terminal source.\n", vname);
        goto done;
    }
    nA = (char *) uidA;                     /* driver-side node */
    nB = (char *) uidB;                     /* load-side node   */
    (void) snprintf(eA, sizeof eA, "v(%s)", nA);
    (void) snprintf(eB, sizeof eB, "v(%s)", nB);
    (void) snprintf(eI, sizeof eI, "%s#branch", vname);

    /* Enhancement-381: remember what the probes were driving with. `stb` uses
     * two existing sources as injection probes, and used to hand them back set to
     * ZERO -- which is not "quiescent" unless they happened to start there. A
     * source carrying `ac 1` for the user's own following `.ac` had that value
     * destroyed, and every node of that `.ac` came back exactly 0.00000000e+00
     * with no warning. Only the magnitude is saved: the injection below writes
     * `ac = N`, which sets acmag and leaves acphase untouched.
     */
    {
        int mlen = 0;
        ngcomplex_t *m;
        (void) snprintf(cmd, sizeof cmd, "@%s[acmag]", vname);
        m = stb_eval(cmd, &mlen);
        if (m && mlen >= 1) { vprobe_acmag = realpart(m[0]); tfree(m); }
        (void) snprintf(cmd, sizeof cmd, "@%s[acmag]", iname);
        m = stb_eval(cmd, &mlen);
        if (m && mlen >= 1) { iprobe_acmag = realpart(m[0]); tfree(m); }
    }

    /* --- voltage injection: Vprobe ac=1, Iprobe ac=0 --- */
    (void) snprintf(cmd, sizeof cmd, "alter %s ac = 1", vname); stb_run(cmd);
    (void) snprintf(cmd, sizeof cmd, "alter %s ac = 0", iname); stb_run(cmd);
    (void) snprintf(cmd, sizeof cmd, "ac %s", sweep);           stb_run(cmd);
    vA    = stb_eval(eA, &nA_len);
    vB    = stb_eval(eB, &nB_len);
    freqc = stb_eval("frequency", &nF_len);

    /* --- current injection: Vprobe ac=0, Iprobe ac=1 --- */
    (void) snprintf(cmd, sizeof cmd, "alter %s ac = 0", vname); stb_run(cmd);
    (void) snprintf(cmd, sizeof cmd, "alter %s ac = 1", iname); stb_run(cmd);
    (void) snprintf(cmd, sizeof cmd, "ac %s", sweep);           stb_run(cmd);
    ibr = stb_eval(eI, &nI_len);

    /* Enhancement-381: hand the probes back EXACTLY as we found them, not zeroed */
    (void) snprintf(cmd, sizeof cmd, "alter %s ac = %.17g", vname, vprobe_acmag);
    stb_run(cmd);
    (void) snprintf(cmd, sizeof cmd, "alter %s ac = %.17g", iname, iprobe_acmag);
    stb_run(cmd);

    if (!vA || !vB || !ibr || !freqc ||
        nA_len != nB_len || nA_len != nI_len || nA_len != nF_len || nA_len < 2) {
        fprintf(cp_err, "stb: AC injection failed (check the probe wiring and the "
                        "sweep spec).\n");
        goto done;
    }
    n = nA_len;

    /* --- combine the two injections into the loop gain.
     * Tv = -v(A)/v(B); with a = i(Vprobe) during current injection the current
     * loop gain is Ti = -a/(a+1), and Tian's T = (Tv*Ti - 1)/(Tv + Ti + 2).
     * Substituting Ti and clearing the a+1 denominator gives the algebraically
     * identical but singularity-free form
     *     T = -(Tv*a + a + 1) / (Tv*a + Tv + a + 2),
     * which stays exact in the clean-break limit a -> -1 (Ti -> inf), where it
     * reduces to T = Tv. --- */
    T   = TMALLOC(ngcomplex_t, n);
    mag = TMALLOC(double, n);
    ph  = TMALLOC(double, n);
    for (i = 0; i < n; i++) {
        ngcomplex_t Tv  = stbmul(stbcx(-1.0, 0.0), stbdiv(vA[i], vB[i]));
        ngcomplex_t a   = ibr[i];
        ngcomplex_t Tva = stbmul(Tv, a);
        ngcomplex_t num = stbadd(stbadd(Tva, a), stbcx(1.0, 0.0));
        ngcomplex_t den = stbadd(stbadd(stbadd(Tva, Tv), a), stbcx(2.0, 0.0));
        T[i] = stbmul(stbcx(-1.0, 0.0), stbdiv(num, den));
        mag[i] = hypot(T[i].cx_real, T[i].cx_imag);
        ph[i]  = atan2(T[i].cx_imag, T[i].cx_real) * 180.0 / M_PI;
    }
    /* unwrap phase for a monotone Bode trace */
    for (i = 1; i < n; i++) {
        while (ph[i] - ph[i - 1] >  180.0) ph[i] -= 360.0;
        while (ph[i] - ph[i - 1] < -180.0) ph[i] += 360.0;
    }

    /* --- phase margin: first |T| = 1 (0 dB) crossing --- */
    for (i = 1; i < n && !have_pm; i++) {
        if ((mag[i - 1] - 1.0) * (mag[i] - 1.0) <= 0.0 && mag[i - 1] != mag[i]) {
            double l0 = log10(mag[i - 1]), l1 = log10(mag[i]);
            double t = (0.0 - l0) / (l1 - l0);          /* log-mag linear in log-f */
            double phc = ph[i - 1] + t * (ph[i] - ph[i - 1]);
            fpm = freqc[i - 1].cx_real *
                  pow(freqc[i].cx_real / freqc[i - 1].cx_real, t);
            pm = 180.0 + phc;
            have_pm = 1;
        }
    }
    /* --- gain margin: first phase = -180 deg crossing --- */
    for (i = 1; i < n && !have_gm; i++) {
        if ((ph[i - 1] + 180.0) * (ph[i] + 180.0) <= 0.0 && ph[i - 1] != ph[i]) {
            double t = (-180.0 - ph[i - 1]) / (ph[i] - ph[i - 1]);
            double m0 = 20.0 * log10(mag[i - 1]), m1 = 20.0 * log10(mag[i]);
            fgm = freqc[i - 1].cx_real *
                  pow(freqc[i].cx_real / freqc[i - 1].cx_real, t);
            gm = -(m0 + t * (m1 - m0));
            have_gm = 1;
        }
    }

    /* --- store the loop gain into a fresh `stb` plot --- */
    {
        struct plot *pl = plot_alloc("stb");
        struct dvec *sc, *lg;
        pl->pl_name  = copy("Loop gain");
        pl->pl_title = copy(ft_curckt->ci_name ? ft_curckt->ci_name : "stb");
        plot_new(pl);
        plot_setcur(pl->pl_typename);
        sc = dvec_alloc(copy("frequency"), SV_FREQUENCY,
                        (short) (VF_REAL | VF_PERMANENT), n, NULL);
        for (i = 0; i < n; i++) sc->v_realdata[i] = freqc[i].cx_real;
        vec_new(sc);                                    /* first permanent -> scale */
        lg = dvec_alloc(copy("loopgain"), SV_NOTYPE,
                        (short) (VF_COMPLEX | VF_PERMANENT), n, NULL);
        for (i = 0; i < n; i++) lg->v_compdata[i] = T[i];
        vec_new(lg);
    }

    /* --- report --- */
    fprintf(cp_out, "\nStability (loop gain via Tian double injection at %s):\n",
            vname);
    fprintf(cp_out, "  DC loop gain    : %.4g dB\n", 20.0 * log10(mag[0]));
    if (have_pm)
        fprintf(cp_out, "  phase margin    : %.2f deg  (at fc = %.5g Hz)\n", pm, fpm);
    else
        fprintf(cp_out, "  phase margin    : (no unity-gain crossover in the sweep)\n");
    if (have_gm)
        fprintf(cp_out, "  gain margin     : %.2f dB   (at f  = %.5g Hz)\n", gm, fgm);
    else
        fprintf(cp_out, "  gain margin     : (no -180 deg crossover in the sweep)\n");
    fprintf(cp_out, "  -> 'loopgain' stored; `plot db(loopgain)` / "
                    "`plot cph(loopgain)*180/pi` to view.\n");

done:
    tfree(vname); tfree(iname); tfree(vlookup); tfree(sweep);
    tfree(vA); tfree(vB); tfree(ibr); tfree(freqc);
    tfree(T); tfree(mag); tfree(ph);
}
