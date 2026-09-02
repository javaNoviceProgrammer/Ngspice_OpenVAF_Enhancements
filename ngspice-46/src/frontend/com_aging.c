/**********
Enhancement-157: device aging (reliability degradation flow).

`aging <t_target>` ages every aging-capable device in the loaded circuit to a
target operating lifetime and re-stamps the circuit, so any analysis run
afterwards sees the degraded devices. It is the "stress -> degrade -> re-
simulate (fresh vs aged)" flow that reliability sign-off needs.

The mechanism is deliberately model-agnostic. A device opts in by exposing two
things in its Verilog-A / OSDI model:

  * a degradation-RATE operating-point variable (default name `agerate`): the
    instantaneous stress rate at the present bias, in "dose units per second"
    (whatever quantity the model integrates -- e.g. gate-overdrive-seconds for
    an NBTI threshold shift), and

  * a per-instance AGE parameter (default name `age`): the accumulated stress
    dose, written back by this command. The model owns the physics that maps
    `age` to a parameter shift (a sublinear power law, an Arrhenius factor,
    ...); the engine only integrates the rate and feeds back the dose.

Two modes:

  * static (default) -- read the rate at the DC operating point and multiply by
    the target lifetime:  age = agerate(op) * t_target.  Appropriate for a
    device held at a fixed stress bias.

  * dynamic (`dynamic <tstop> [tstep]`) -- run a transient over one
    representative window, integrate the rate over time, and extrapolate to the
    lifetime:  age = (INTEGRAL agerate dt / tstop) * t_target.  This captures
    duty cycle: a gate that is only biased on part of the time ages by its
    time-averaged stress.

Syntax (in a .control block, after the circuit is loaded):

  aging <t_target> [rate <opvar>] [param <ageparam>]
        [dynamic <tstop> [tstep]] [verbose]

The command runs the fresh operating point / transient first (leaving that
result as the current plot, a convenient "fresh" baseline), then applies the
per-device ages. Console chatter from the internal analysis is suppressed
unless `-verbose`. A device participates only if its model exposes BOTH the
rate opvar and the age parameter, so probing never errors on ordinary
resistors, sources, etc.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/wordlist.h"
#include "ngspice/fteext.h"
#include "ngspice/cpextern.h"
#include "ngspice/devdefs.h"
#include "ngspice/gendefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/osdiitf.h"   /* E-537 (hunt G): OSDImcMachineWrite */

#include "com_aging.h"

/* Run one command synchronously through the command table (as com_optimize's
 * opt_run_cmd does): cp_evloop would defer it to the outer interpreter, which
 * is too late here. */
/* E-537 (hunt D): did the analysis just run actually solve? ngspice leaves the
 * PREVIOUS run's plot in place when one fails, so reading a stress rate back
 * blind returns another run's numbers -- and aging then WRITES the resulting
 * dose into the devices and PERSISTS it (age_remember), so a failed stress
 * simulation silently ages the circuit from a foreign bias point. runcoms.c
 * publishes the verdict in `sim_status`; the same helper com_sweep.c and
 * com_optimize.c already use. */
static int age_run_failed(void)
{
    int st = 0;
    if (cp_getvar("sim_status", CP_NUM, &st, sizeof st))
        return st != 0;
    return 0;                    /* variable absent -- assume the run was fine */
}

static void age_run_cmd(const char *cmdstr)
{
    wordlist *wl = cp_lexer((char *) cmdstr);
    int i;

    if (!wl || !wl->wl_word) {
        if (wl) wl_free(wl);
        return;
    }
    for (i = 0; cp_coms[i].co_comname; i++)
        if (strcasecmp(cp_coms[i].co_comname, wl->wl_word) == 0)
            break;
    if (cp_coms[i].co_comname && cp_coms[i].co_func)
        cp_coms[i].co_func(wl->wl_next);
    else
        fprintf(cp_err, "aging: unknown command '%s'\n", wl->wl_word);
    wl_free(wl);
}


/* Enhancement-501: does this token read as a number end to end? Used to decide
 * whether `dynamic`'s next token is its stop time or the next option. */
/* Is this whole token a number `aging` would accept? ft_numparse, NOT strtod:
 * the stop time is a SPICE number and `dynamic 20u 0.05u` is how it is written
 * everywhere -- strtod stops at the `u` and would refuse the documented form. */
static int age_looks_numeric(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;

    if (!w || !*w)
        return 0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        return 0;
    while (*s == ' ' || *s == '\t')
        s++;
    return (*s == '\0');
}


/* Enhancement-501: remember what `aging` wrote, so a per-sample `reset` inside a
 * statistical command does not silently un-age the circuit.
 *
 * `age` is written into the instance at run time and has no representation in
 * the deck text, so re-sourcing the deck discards it. `montecarlo` escapes that
 * because Enhancement-346's fast path skips the per-sample reset whenever a
 * random value binds -- but `wcd`, `highsigma` and `optimize -center` have no
 * such path and re-source every evaluation, so they analysed FRESH devices after
 * the user had aged the circuit. Measured on the agestate suite's deck: a
 * 95-year dose moves the worst-case distance from 8.66 sigma to 1.81 sigma, and
 * `wcd` reported 8.66 for both -- a reliability margin that had not moved at
 * all, which is the one number such a run exists to produce.
 *
 * Enhancement-157 states the contract this restores: aging "re-stamps the
 * circuit -- so any analysis run afterwards (op, dc, tran, ac, ...) sees the
 * aged devices".
 *
 * Only the INTERNAL resets replay: a `reset` the user types still means "back to
 * the deck", which is what reset has always meant -- otherwise there is no way
 * back to a fresh device short of reloading the file. */

/* Nonzero while a loop command issues its own internal `reset`; com_rset() drops
 * the recorded doses only when this is clear. */
int aging_internal_reset = 0;

static char **age_writes = NULL;
static int    age_nwrites = 0;

static void age_forget(void)
{
    int k;
    for (k = 0; k < age_nwrites; k++)
        tfree(age_writes[k]);
    tfree(age_writes);
    age_writes = NULL;
    age_nwrites = 0;
}


static void age_remember(const char *cmd)
{
    age_writes = TREALLOC(char *, age_writes, age_nwrites + 1);
    age_writes[age_nwrites++] = copy(cmd);
}


/* Re-apply the last `aging` result. Silent, and a no-op when nothing was aged. */
/* Called from com_rset(): a user-typed `reset` forgets the accumulated dose. */
void aging_forget_writes(void)
{
    age_forget();
}


void aging_replay(void)
{
    int k, save;
    if (age_nwrites <= 0)
        return;
    save = ft_optimizing;
    ft_optimizing = TRUE;            /* keep `alter` quiet, as the writer does */
    OSDImcMachineWrite(TRUE);        /* E-537 (hunt G): a replay is not a user write */
    for (k = 0; k < age_nwrites; k++)
        age_run_cmd(age_writes[k]);
    OSDImcMachineWrite(FALSE);
    ft_optimizing = save;
}


/* parse a SPICE-style number (understands k / meg / u / n / p ... suffixes) */
static double age_num(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}


/* Does device type t expose an instance parameter / operating-point variable
 * whose keyword matches `key` (case-insensitive)? Opvars live in the same
 * instanceParms table as settable instance params, so this finds both. */
static int type_has_param(int t, const char *key)
{
    IFparm *p = DEVices[t]->DEVpublic.instanceParms;
    int np = DEVices[t]->DEVpublic.numInstanceParms
                 ? *DEVices[t]->DEVpublic.numInstanceParms : 0;
    int i;
    for (i = 0; i < np; i++)
        if (p[i].keyword && strcasecmp(p[i].keyword, key) == 0)
            return 1;
    return 0;
}


/* Evaluate an ngspice expression and return the LAST value of its result
 * (magnitude if complex), or a sentinel (NaN) if it cannot be evaluated. */
static double age_last(const char *expr)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    double f = 0.0 / 0.0;              /* NaN sentinel */

    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1) {
            if (isreal(v))
                f = v->v_realdata[v->v_length - 1];
            else
                f = hypot(v->v_compdata[v->v_length - 1].cx_real,
                          v->v_compdata[v->v_length - 1].cx_imag);
        }
        if (!pn->pn_value && v)       /* free a temporary ft_evaluate made */
            vec_free(v);
        free_pnode(pn);
    }
    return f;
}


/* Time-weighted mean of a per-timepoint opvar vector over a transient: the
 * trapezoidal integral of `@name[opvar]` against `time`, divided by the span.
 * Falls back to the plain point mean when there is no usable time base. */
static double age_time_mean(const char *expr)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    struct dvec *r = pn ? ft_evaluate(pn) : NULL;
    struct dvec *tv = vec_get("time");
    double mean = 0.0 / 0.0;

    if (r && r->v_length >= 1 && isreal(r)) {
        int L = r->v_length, i;
        if (tv && isreal(tv) && tv->v_length == L && L >= 2 &&
            (tv->v_realdata[L - 1] - tv->v_realdata[0]) > 0.0) {
            double integ = 0.0;
            for (i = 1; i < L; i++)
                integ += 0.5 * (r->v_realdata[i] + r->v_realdata[i - 1]) *
                         (tv->v_realdata[i] - tv->v_realdata[i - 1]);
            mean = integ / (tv->v_realdata[L - 1] - tv->v_realdata[0]);
        } else {
            double s = 0.0;
            for (i = 0; i < L; i++)
                s += r->v_realdata[i];
            mean = s / L;
        }
    }
    if (pn) {
        if (!pn->pn_value && r)
            vec_free(r);
        free_pnode(pn);
    }
    return mean;
}


void com_aging(wordlist *wl)
{
    CKTcircuit *ckt;
    const char *ratevar = "agerate";
    const char *agepar  = "age";
    double t_target = 0.0, tstop = 0.0, tstep = 0.0;
    int dynamic = 0, verbose = 0, got_t = 0;
    const char *dyn_bad = NULL;                  /* Enhancement-501 */

    char **name = NULL;
    double *rate = NULL, *dose = NULL;
    int ndev = 0, ncap = 0, aged = 0, t, k;
    GENmodel *mod; GENinstance *inst;

    /* --- parse --- */
    while (wl) {
        const char *w = wl->wl_word;
        if (eq(w, "rate") && wl->wl_next) {
            ratevar = wl->wl_next->wl_word; wl = wl->wl_next->wl_next; continue;
        } else if (eq(w, "param") && wl->wl_next) {
            agepar = wl->wl_next->wl_word; wl = wl->wl_next->wl_next; continue;
        } else if (eq(w, "dynamic")) {
            dynamic = 1;
            /* Enhancement-501: the token after `dynamic` is its tstop only if it
               LOOKS like a number. It used to be taken whenever it did not start
               with '-', so `aging 3.15e8 dynamic verbose` read "verbose" as the
               stop time, failed with "dynamic mode needs a positive <tstop>",
               and aged nothing; `dynamic rate agerate` reported the perfectly
               good `agerate` as an unrecognized token. The tstep test one line
               below already required a digit -- the two halves of one option
               disagreed about what a number looks like. */
            if (wl->wl_next && !age_looks_numeric(wl->wl_next->wl_word))
                dyn_bad = wl->wl_next->wl_word;   /* Enhancement-501: name it below */
            if (wl->wl_next && age_looks_numeric(wl->wl_next->wl_word)) {
                tstop = age_num(wl->wl_next->wl_word);
                wl = wl->wl_next->wl_next;
                if (wl && wl->wl_word[0] != '-' &&
                    (isdigit((unsigned char) wl->wl_word[0]) || wl->wl_word[0] == '.')) {
                    tstep = age_num(wl->wl_word);
                    wl = wl->wl_next;
                }
            } else {
                wl = wl->wl_next;
            }
            continue;
        } else if (eq(w, "verbose") || eq(w, "-verbose") || eq(w, "-v")) {
            verbose = 1; wl = wl->wl_next; continue;
        } else if (!got_t) {
            t_target = age_num(w); got_t = 1; wl = wl->wl_next; continue;
        } else {
            fprintf(cp_err, "aging: unrecognized token '%s'\n", w);
            wl = wl->wl_next; continue;
        }
    }

    /* Enhancement-501: `!(x > 0)` rather than `x <= 0`, because every comparison
       with NaN is false -- `aging nan` sailed through the old test and reported
       "aged to t = nan s (nan years)". The same shape let `highsigma -scale nan`
       past `lambda <= 1.0`. `sweep` has always demanded a finite number here. */
    if (!got_t || !(t_target > 0.0) || !finite(t_target)) {
        fprintf(cp_err, "usage: aging <t_target> [rate <opvar>] [param <ageparam>] "
                        "[dynamic <tstop> [tstep]] [verbose]\n");
        return;
    }
    if (dynamic && (!(tstop > 0.0) || !finite(tstop))) {   /* Enhancement-501 */
        if (dyn_bad)
            fprintf(cp_err, "aging: `dynamic` needs a stop time, and '%s' is not "
                            "a number -- write `dynamic <tstop> [tstep]`\n", dyn_bad);
        fprintf(cp_err, "aging: dynamic mode needs a positive <tstop>\n");
        return;
    }
    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "aging: no circuit loaded\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    /* --- collect instances of every ageable device type (has both the rate
     * opvar and the age parameter) --- */
    int agepar_warned = 0;       /* Enhancement-501: warn once, not per type */
    for (t = 0; t < DEVmaxnum; t++) {
        if (!DEVices[t] || !ckt->CKThead[t])
            continue;
        if (!type_has_param(t, ratevar) || !type_has_param(t, agepar))
            continue;
        /* Enhancement-501: `param <name>` picks WHERE the accumulated dose is
         * written. Any writable parameter of the right type accepts it, so a
         * mistyped or misremembered name lands the dose in something that is
         * not an aging state at all -- `param w` writes seconds of stress into
         * a MOSFET's WIDTH and the run continues, reporting devices aged. The
         * name is the user's to choose (some models spell their aging state
         * differently), so this warns and proceeds rather than refusing; but
         * when the very same device also exposes a plain `age`, choosing a
         * different parameter is far more likely a slip than an intent. */
        if (!agepar_warned && strcasecmp(agepar, "age") != 0 &&
            type_has_param(t, "age")) {
            fprintf(cp_err, "aging: writing the dose into '%s', but this device "
                            "also has an 'age' parameter -- if '%s' is not an "
                            "aging state, the dose is being written into an "
                            "unrelated device parameter\n", agepar, agepar);
            agepar_warned = 1;
        }
        for (mod = ckt->CKThead[t]; mod; mod = mod->GENnextModel)
            for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
                if (ndev >= ncap) {
                    ncap = ncap ? ncap * 2 : 64;
                    name = TREALLOC(char *, name, ncap);
                    rate = TREALLOC(double, rate, ncap);
                    dose = TREALLOC(double, dose, ncap);
                }
                name[ndev++] = copy((char *) inst->GENname);
            }
    }

    if (ndev == 0) {
        fprintf(cp_err, "aging: no ageable devices found (a model must expose the "
                        "'%s' operating-point variable and the '%s' instance "
                        "parameter)\n", ratevar, agepar);
        tfree(name); tfree(rate); tfree(dose);
        return;
    }

    /* --- fresh stress simulation (quiet unless verbose) --- */
    ft_optimizing = !verbose;

    if (dynamic) {
        char cmd[256];
        for (k = 0; k < ndev; k++) {
            (void) snprintf(cmd, sizeof cmd, "save @%s[%s]", name[k], ratevar);
            age_run_cmd(cmd);
        }
        if (tstep > 0.0)
            (void) snprintf(cmd, sizeof cmd, "tran %.10g %.10g", tstep, tstop);
        else
            (void) snprintf(cmd, sizeof cmd, "tran %.10g %.10g", tstop / 200.0, tstop);
        age_run_cmd(cmd);
        ft_optimizing = !verbose;     /* re-assert after the analysis banner */
        if (age_run_failed()) {       /* E-537 (hunt D) */
            ft_optimizing = FALSE;
            fprintf(cp_err, "aging: the stress simulation did not solve, so there "
                            "are no stress rates to age from; nothing was aged.\n");
            return;
        }
        for (k = 0; k < ndev; k++) {
            char e[256];
            (void) snprintf(e, sizeof e, "@%s[%s]", name[k], ratevar);
            rate[k] = age_time_mean(e);
        }
    } else {
        age_run_cmd("op");
        ft_optimizing = !verbose;
        if (age_run_failed()) {       /* E-537 (hunt D) */
            ft_optimizing = FALSE;
            fprintf(cp_err, "aging: the stress simulation did not solve, so there "
                            "are no stress rates to age from; nothing was aged.\n");
            return;
        }
        for (k = 0; k < ndev; k++) {
            char e[256];
            (void) snprintf(e, sizeof e, "@%s[%s]", name[k], ratevar);
            rate[k] = age_last(e);
        }
    }

    /* --- accumulate dose and write it back --- */
    age_forget();                                /* Enhancement-501: this run replaces the last */
    /* E-537 (hunt G): the dose is MACHINE-computed (from a stress simulation
     * that itself ran on a drawn sample), so it must not recenter an osdimc
     * statistical nominal the way a user's `alter` does -- E-531's rule. */
    OSDImcMachineWrite(TRUE);
    for (k = 0; k < ndev; k++) {
        char cmd[256];
        if (!finite(rate[k]) || rate[k] < 0.0)
            rate[k] = 0.0;
        dose[k] = rate[k] * t_target;
        (void) snprintf(cmd, sizeof cmd, "alter @%s[%s] = %.10g", name[k], agepar, dose[k]);
        age_run_cmd(cmd);
        age_remember(cmd);                       /* Enhancement-501 */
        aged++;
    }
    OSDImcMachineWrite(FALSE);                   /* E-537 (hunt G) */

    ft_optimizing = FALSE;

    /* --- report --- */
    fprintf(cp_out, "aging: %d device%s aged to t = %g s (%.3g years), %s stress "
                    "[rate '%s' -> param '%s']\n",
            aged, aged == 1 ? "" : "s", t_target, t_target / 3.15576e7,
            dynamic ? "dynamic" : "static", ratevar, agepar);
    fprintf(cp_out, "  %-16s %16s %16s\n", "device",
            dynamic ? "mean rate" : "rate", "age (dose)");
    for (k = 0; k < ndev; k++)
        fprintf(cp_out, "  %-16s %16.6g %16.6g\n", name[k], rate[k], dose[k]);

    for (k = 0; k < ndev; k++)
        tfree(name[k]);
    tfree(name); tfree(rate); tfree(dose);
}
