/**********
Enhancement-154: Envelope Following.

  envelope <node> <fc> <tstop> [nppp N] [m M0] [maxm Mmax] [reltol t] [settle ts]

The last remaining RF analysis. For a carrier-driven circuit whose amplitude/phase
modulates slowly over many carrier periods (a ringing resonator, a settling PLL, a
modulated PA), a plain `.tran` must integrate every fast cycle. Envelope following
samples the state once per carrier period T=1/fc and integrates the slow drift of
those samples, jumping M periods at a time with an IMPLICIT (backward-Euler +
monodromy) step -- the naive explicit jump blows up on high-Q circuits.

The command runs a short transient to settle the fast dynamics and initialize the
integrator, then hands off to EFanalysis() (spicelib/analysis/envelope.c), and emits
a plot named `envelope`: the observable's amplitude (2|V1|), DC/mean, and the in-phase
and quadrature fundamental components, versus (slow) time.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/fteext.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpextern.h"
#include "ngspice/plot.h"

#include "circuits.h"
#include "com_envelope.h"

static void envelope_run_cmd(const char *cmdstr)
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

static double envnum(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}

static int env_node(CKTcircuit *ckt, const char *name)
{
    int numNames = 0, i, num = 0;
    IFuid *nameList = NULL;
    if (CKTnames(ckt, &numNames, &nameList) != OK || !nameList)
        return 0;
    for (i = 0; i < numNames; i++)
        if (nameList[i] && strcmp((const char *) nameList[i], name) == 0) { num = i + 1; break; }
    tfree(nameList);
    return num;
}

/* build the `envelope` plot: a time scale + amplitude/dc/re/im data vectors */
static void env_emit_plot(double *tt, double *amp, double *dc, double *re, double *im,
                          int npts, const char *nodename)
{
    struct plot *pl = plot_alloc("envelope");
    struct dvec *sc;
    char vname[128];
    int p;
    pl->pl_name  = copy("Envelope Following");
    pl->pl_title = copy("Envelope Following Analysis");
    plot_new(pl);
    plot_setcur(pl->pl_typename);

    sc = dvec_alloc(copy("time"), SV_TIME, (short)(VF_REAL | VF_PERMANENT), npts, NULL);
    for (p = 0; p < npts; p++) sc->v_realdata[p] = tt[p];
    vec_new(sc);

    (void) snprintf(vname, sizeof vname, "%s_amp", nodename);
    { struct dvec *v = dvec_alloc(copy(vname), SV_VOLTAGE, (short)(VF_REAL | VF_PERMANENT), npts, NULL);
      for (p = 0; p < npts; p++) v->v_realdata[p] = amp[p]; vec_new(v); }
    (void) snprintf(vname, sizeof vname, "%s_dc", nodename);
    { struct dvec *v = dvec_alloc(copy(vname), SV_VOLTAGE, (short)(VF_REAL | VF_PERMANENT), npts, NULL);
      for (p = 0; p < npts; p++) v->v_realdata[p] = dc[p]; vec_new(v); }
    (void) snprintf(vname, sizeof vname, "%s_re", nodename);
    { struct dvec *v = dvec_alloc(copy(vname), SV_VOLTAGE, (short)(VF_REAL | VF_PERMANENT), npts, NULL);
      for (p = 0; p < npts; p++) v->v_realdata[p] = re[p]; vec_new(v); }
    (void) snprintf(vname, sizeof vname, "%s_im", nodename);
    { struct dvec *v = dvec_alloc(copy(vname), SV_VOLTAGE, (short)(VF_REAL | VF_PERMANENT), npts, NULL);
      for (p = 0; p < npts; p++) v->v_realdata[p] = im[p]; vec_new(v); }
}

void
com_envelope(wordlist *wl)
{
    CKTcircuit *ckt;
    char *nodename;
    double fc, tstop, settle, reltol = 0.01;
    int    nppp = 128, M0 = 4, Mmax = 256;
    double T, tstep, Tsettle;
    long   nperiods, maxpts;
    double *tt, *amp, *dc, *re, *im;
    int    obsNode, npts;
    char   cmd[256];
    wordlist *w;

    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "Error: envelope: there is no circuit loaded.\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    if (!wl || !wl->wl_word || !wl->wl_next || !wl->wl_next->wl_next) {
        fprintf(cp_err, "Usage: envelope <node> <fc> <tstop> "
                        "[nppp N] [m M0] [maxm Mmax] [reltol t] [settle ts]\n");
        return;
    }

    nodename = wl->wl_word;
    fc    = envnum(wl->wl_next->wl_word);
    tstop = envnum(wl->wl_next->wl_next->wl_word);
    if (fc <= 0.0 || tstop <= 0.0) {
        fprintf(cp_err, "Error: envelope: fc and tstop must be positive.\n");
        return;
    }
    T = 1.0 / fc;
    settle = 2.0 * T;                      /* default: settle two carrier periods */

    /* optional keyword arguments */
    for (w = wl->wl_next->wl_next->wl_next; w && w->wl_next; w = w->wl_next->wl_next) {
        const char *k = w->wl_word, *v = w->wl_next->wl_word;
        if      (strcasecmp(k, "nppp")   == 0) nppp   = (int) envnum(v);
        else if (strcasecmp(k, "m")      == 0) M0     = (int) envnum(v);
        else if (strcasecmp(k, "maxm")   == 0) Mmax   = (int) envnum(v);
        else if (strcasecmp(k, "reltol") == 0) reltol = envnum(v);
        else if (strcasecmp(k, "settle") == 0) settle = envnum(v);
        else fprintf(cp_err, "Warning: envelope: unknown option '%s' ignored.\n", k);
    }
    if (nppp < 8)   nppp = 8;
    if (M0 < 1)     M0 = 1;
    if (Mmax < M0)  Mmax = M0;
    if (reltol <= 0.0) reltol = 0.02;

    obsNode = env_node(ckt, nodename);
    if (obsNode < 1) {
        fprintf(cp_err, "Error: envelope: node '%s' not found.\n", nodename);
        return;
    }

    /* settle: round up to a whole number of carrier periods so the hand-off lands
     * on a period boundary (the carrier is then in phase for the period jumps). */
    nperiods = (long) ceil(settle / T);
    if (nperiods < 1) nperiods = 1;
    Tsettle = (double) nperiods * T;
    tstep = T / nppp;

    /* run a short transient: initializes the transient state machine and settles the
     * fast dynamics; leaves CKTtime = Tsettle and the state vector at that instant. */
    (void) snprintf(cmd, sizeof cmd, "tran %.10g %.10g 0 %.10g", tstep, Tsettle, tstep);
    envelope_run_cmd(cmd);

    maxpts = (long) floor(tstop * fc + 0.5) + 8;   /* worst case: one sample per period */
    if (maxpts < 8) maxpts = 8;
    tt  = TMALLOC(double, maxpts);
    amp = TMALLOC(double, maxpts);
    dc  = TMALLOC(double, maxpts);
    re  = TMALLOC(double, maxpts);
    im  = TMALLOC(double, maxpts);

    npts = EFanalysis(ckt, obsNode, fc, tstop, nppp, M0, Mmax, reltol,
                      tt, amp, dc, re, im, (int) maxpts);

    if (npts > 0) {
        env_emit_plot(tt, amp, dc, re, im, npts, nodename);
        fprintf(cp_out,
                "envelope: %d envelope samples over %g s (fc = %g Hz, ~%ld carrier periods)\n"
                "  final amplitude 2|V1|(%s) = %g,  DC = %g\n"
                "  new plot `envelope` is current; `plot %s_amp` to view the envelope.\n",
                npts, tstop, fc, (long) floor(tstop * fc + 0.5),
                nodename, amp[npts-1], dc[npts-1], nodename);
    } else {
        fprintf(cp_err, "envelope: analysis did not complete.\n");
    }

    FREE(tt); FREE(amp); FREE(dc); FREE(re); FREE(im);
}
