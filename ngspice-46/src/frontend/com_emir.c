/**********
Enhancement-158: EMIR -- power-grid electromigration + IR-drop reliability check.

`emir` analyses the power-distribution network (PDN) of the loaded circuit after
a DC solve and reports the two classic power-grid reliability metrics:

  * IR-drop  -- how far each node has sagged below the ideal supply rail under
    load (the resistive grid drops `I*R` between the pad and each tap). Reports
    the worst-case drop and every node past a threshold.

  * Electromigration (EM) -- for each wire-segment resistor, the current DENSITY
    `J = |I| / (w * thickness)` and a Black's-equation lifetime. EM is driven by
    current density, not current, so a narrow wire can be the bottleneck even at
    modest current. Reports the worst-density segment, a ranked table, and every
    segment past the current-density limit, with a relative mean-time-to-failure
    `MTTF/ref = (Jmax/J)^n` (Black: MTTF ~ J^-n; a segment at exactly `Jmax` has
    MTTF = the reference lifetime).

Syntax (in a .control block, after the circuit is loaded):

  emir [rail <V>] [thresh <frac>] [thick <m>] [jmax <A/m2>] [n <exp>]
       [tref <s>] [top <k>] [verbose]

`rail` defaults to the highest node voltage (the supply pad); `thresh` to 0.1
(10% of the rail); `thick` to 0.5 um; `jmax` to 1e10 A/m^2 (~1 MA/cm^2); the
Black exponent `n` to 2; `tref` to 10 years; `top` (table length) to 10.

The command runs a fresh `op` first (leaving it as the current plot). Segments
without a width are skipped for EM (reported as a count). Solver-independent:
it reads a DC solution and per-resistor currents/widths.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/plot.h"
#include "ngspice/sim.h"
#include "ngspice/wordlist.h"
#include "ngspice/fteext.h"
#include "ngspice/cpextern.h"
#include "ngspice/devdefs.h"
#include "ngspice/gendefs.h"
#include "ngspice/cktdefs.h"

#include "../spicelib/devices/res/resdefs.h"   /* Enhancement-502: RESwidthGiven */

#include "com_emir.h"

/* Run one command synchronously through the command table (com_optimize's
 * opt_run_cmd pattern). */
/* E-537 (hunt D): ngspice keeps the previous run's plot when an analysis
 * fails, so reading node voltages and branch currents back blind produces a
 * complete, plausible IR-drop and electromigration verdict computed on a bias
 * point that does not exist for this circuit -- a reliability sign-off on
 * another run's numbers. `sim_status` carries the verdict (runcoms.c). */
static int emir_run_failed(void)
{
    int st = 0;
    if (cp_getvar("sim_status", CP_NUM, &st, sizeof st))
        return st != 0;
    return 0;                    /* variable absent -- assume the run was fine */
}

static void emir_run_cmd(const char *cmdstr)
{
    wordlist *wl = cp_lexer((char *) cmdstr);
    int i;
    if (!wl || !wl->wl_word) { if (wl) wl_free(wl); return; }
    for (i = 0; cp_coms[i].co_comname; i++)
        if (strcasecmp(cp_coms[i].co_comname, wl->wl_word) == 0)
            break;
    if (cp_coms[i].co_comname && cp_coms[i].co_func)
        cp_coms[i].co_func(wl->wl_next);
    else
        fprintf(cp_err, "emir: unknown command '%s'\n", wl->wl_word);
    wl_free(wl);
}

/* Enhancement-502: emir_num() is gone. It parsed a SPICE number and handed it
 * over unexamined, which is how `jmax nan` reached a `<= 0.0` guard that admits
 * NaN. Arguments now go through ft_argpos/ft_argfinite/ft_argcount, which parse
 * with the same ft_numparse (so `thick 0.5u` still works) and then say no. */

/* Evaluate an ngspice expression, returning the LAST value (magnitude if
 * complex), or NaN if it cannot be evaluated. */
static double emir_eval(const char *expr)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    double f = 0.0 / 0.0;
    if (pn) {
        struct dvec *v = ft_evaluate(pn);
        if (v && v->v_length >= 1) {
            if (isreal(v))
                f = v->v_realdata[v->v_length - 1];
            else
                f = hypot(v->v_compdata[v->v_length - 1].cx_real,
                          v->v_compdata[v->v_length - 1].cx_imag);
        }
        if (!pn->pn_value && v)
            vec_free(v);
        free_pnode(pn);
    }
    return f;
}

/* one IR-drop node record and one EM segment record */
typedef struct { char *name; double v, drop; } IRrec;
typedef struct { char *name; double i, w, j, mttf; int fail; } EMrec;

static int cmp_ir(const void *a, const void *b)   /* by drop, descending */
{
    double d = ((const IRrec *) b)->drop - ((const IRrec *) a)->drop;
    return (d > 0) - (d < 0);
}
static int cmp_em(const void *a, const void *b)   /* by current density, desc */
{
    double d = ((const EMrec *) b)->j - ((const EMrec *) a)->j;
    return (d > 0) - (d < 0);
}


void com_emir(wordlist *wl)
{
    CKTcircuit *ckt;
    double rail = 0.0, thresh = 0.1, thick = 5e-7, jmax = 1e10;
    double nexp = 2.0, tref = 3.15576e8;
    int top = 10, verbose = 0, user_rail = 0;

    IRrec *ir = NULL; int nir = 0, nircap = 0;
    EMrec *em = NULL; int nem = 0, nemcap = 0, nnowidth = 0, nbadwidth = 0;
    struct dvec *d;
    int t, k, ir_viol = 0, em_viol = 0;

    /* --- parse --- */
    while (wl) {
        const char *w = wl->wl_word;
        /* Enhancement-502: every one of these was taken on trust. `thick` and
         * `jmax` had a `<= 0.0` guard, which admits NaN and then reported "0
         * segments over Jmax" on a grid with two genuine violations; the rest
         * had no check at all, so `rail nan` printed "worst drop nan V" and
         * `top nan` reached 1 through an undefined double->int conversion. */
        if (eq(w, "rail") && wl->wl_next) {
            if (!ft_argfinite("emir", "rail", wl->wl_next->wl_word, &rail)) return;
            user_rail = 1; wl = wl->wl_next->wl_next;
        } else if (eq(w, "thresh") && wl->wl_next) {
            if (!ft_argpos("emir", "thresh", wl->wl_next->wl_word, &thresh)) return;
            wl = wl->wl_next->wl_next;
        } else if (eq(w, "thick") && wl->wl_next) {
            if (!ft_argpos("emir", "thick", wl->wl_next->wl_word, &thick)) return;
            wl = wl->wl_next->wl_next;
        } else if (eq(w, "jmax") && wl->wl_next) {
            if (!ft_argpos("emir", "jmax", wl->wl_next->wl_word, &jmax)) return;
            wl = wl->wl_next->wl_next;
        } else if (eq(w, "n") && wl->wl_next) {
            if (!ft_argpos("emir", "n", wl->wl_next->wl_word, &nexp)) return;
            wl = wl->wl_next->wl_next;
        } else if (eq(w, "tref") && wl->wl_next) {
            if (!ft_argpos("emir", "tref", wl->wl_next->wl_word, &tref)) return;
            wl = wl->wl_next->wl_next;
        } else if (eq(w, "top") && wl->wl_next) {
            if (!ft_argcount("emir", "top", wl->wl_next->wl_word, 1, 1000000, &top)) return;
            wl = wl->wl_next->wl_next;
        } else if (eq(w, "verbose") || eq(w, "-verbose") || eq(w, "-v")) {
            verbose = 1; wl = wl->wl_next;
        } else {
            fprintf(cp_err, "emir: unrecognized token '%s'\n", w);
            wl = wl->wl_next;
        }
    }

    if (!(thick > 0.0) || !(jmax > 0.0)) {   /* NOT `<= 0`: that admits NaN */
        fprintf(cp_err, "emir: thick and jmax must be positive\n");
        return;
    }
    if (thresh > 1.0)
        fprintf(cp_err, "emir: warning: thresh is a FRACTION of the rail, so %g "
                        "means %g%% -- no node can be that far down\n",
                thresh, 100.0 * thresh);
    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "emir: no circuit loaded\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    /* --- fresh DC solve (quiet unless verbose) --- */
    ft_optimizing = !verbose;
    emir_run_cmd("op");
    ft_optimizing = !verbose;
    if (emir_run_failed()) {          /* E-537 (hunt D) */
        ft_optimizing = FALSE;
        fprintf(cp_err, "emir: the operating point did not solve, so there is no "
                        "bias to analyse; no IR-drop or electromigration report.\n");
        return;
    }

    /* --- IR-drop: gather node voltages from the current plot --- */
    for (d = plot_cur ? plot_cur->pl_dvecs : NULL; d; d = d->v_next) {
        if (d->v_type != SV_VOLTAGE || d->v_length < 1 || !d->v_realdata)
            continue;
        if (nir >= nircap) {
            nircap = nircap ? nircap * 2 : 64;
            ir = TREALLOC(IRrec, ir, nircap);
        }
        ir[nir].name = copy(d->v_name);
        ir[nir].v = d->v_realdata[d->v_length - 1];
        nir++;
    }
    if (!user_rail) {
        rail = 0.0;
        for (k = 0; k < nir; k++)
            if (ir[k].v > rail) rail = ir[k].v;
    }
    for (k = 0; k < nir; k++) {
        ir[k].drop = rail - ir[k].v;
        if (rail > 0.0 && ir[k].drop > thresh * rail) ir_viol++;
    }

    /* --- EM: per-resistor current density + Black's-equation MTTF --- */
    for (t = 0; t < DEVmaxnum; t++) {
        GENmodel *mod; GENinstance *inst;
        if (!DEVices[t] || !ckt->CKThead[t] || !DEVices[t]->DEVpublic.name)
            continue;
        if (strcasecmp(DEVices[t]->DEVpublic.name, "Resistor") != 0)
            continue;
        for (mod = ckt->CKThead[t]; mod; mod = mod->GENnextModel)
            for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
                char e[256];
                const char *nm = (char *) inst->GENname;
                double cur, wid, area, jj;
                (void) snprintf(e, sizeof e, "@%s[i]", nm);
                cur = fabs(emir_eval(e));
                (void) snprintf(e, sizeof e, "@%s[w]", nm);
                wid = emir_eval(e);
                /* Enhancement-502: `@r[w]` answers with the resistor's DEFAULT
                 * width (1e-5 m) when the deck never gave one, and emir could
                 * not tell that from a width the user wrote. So an
                 * undimensioned segment -- the one most likely to be the
                 * oversight -- was analysed as a comfortable 10 um wire and
                 * reported `ok`, while the header of this file says such
                 * segments are skipped. Ask the instance whether the width was
                 * given, as rcreduce.c already reads resistor internals for the
                 * `reduce` command. */
                if (!((RESinstance *) inst)->RESwidthGiven) { nnowidth++; continue; }
                if (!finite(cur) || !finite(wid) || wid <= 0.0) { nbadwidth++; continue; }
                area = wid * thick;
                jj = cur / area;
                if (nem >= nemcap) {
                    nemcap = nemcap ? nemcap * 2 : 64;
                    em = TREALLOC(EMrec, em, nemcap);
                }
                em[nem].name = copy(nm);
                em[nem].i = cur;
                em[nem].w = wid;
                em[nem].j = jj;
                em[nem].mttf = pow(jmax / jj, nexp);   /* Black, relative to tref */
                em[nem].fail = (jj > jmax);
                if (em[nem].fail) em_viol++;
                nem++;
            }
    }

    qsort(ir, (size_t) nir, sizeof(IRrec), cmp_ir);
    qsort(em, (size_t) nem, sizeof(EMrec), cmp_em);

    ft_optimizing = FALSE;

    /* --- report: IR-drop --- */
    fprintf(cp_out, "emir: IR-drop  (rail = %g V, threshold %g%%)\n", rail, thresh * 100.0);
    if (nir > 0)
        fprintf(cp_out, "  worst drop  %.4g V  (%.1f%% of rail)  at  %s\n",
                ir[0].drop, rail > 0 ? 100.0 * ir[0].drop / rail : 0.0, ir[0].name);
    fprintf(cp_out, "  %d node%s over threshold%s\n", ir_viol, ir_viol == 1 ? "" : "s",
            ir_viol ? ":" : "");
    if (ir_viol) {
        fprintf(cp_out, "  %-16s %12s %12s %8s\n", "node", "V", "drop", "%rail");
        for (k = 0; k < nir && k < top; k++) {
            if (!(rail > 0.0 && ir[k].drop > thresh * rail)) break;
            fprintf(cp_out, "  %-16s %12.5g %12.5g %8.1f\n",
                    ir[k].name, ir[k].v, ir[k].drop, 100.0 * ir[k].drop / rail);
        }
    }

    /* --- report: electromigration --- */
    fprintf(cp_out, "emir: electromigration  (thickness = %g m, Jmax = %g A/m2, Black n = %g)\n",
            thick, jmax, nexp);
    if (nem > 0)
        fprintf(cp_out, "  worst J  %.4g A/m2  at  %s   (MTTF %.3g x ref)\n",
                em[0].j, em[0].name, em[0].mttf);
    fprintf(cp_out, "  %d segment%s over Jmax%s", em_viol, em_viol == 1 ? "" : "s",
            em_viol ? ":\n" : "\n");
    if (nem > 0) {
        fprintf(cp_out, "  %-16s %10s %10s %12s %14s %8s\n",
                "segment", "I(A)", "w(m)", "J(A/m2)", "MTTF(x ref)", "status");
        for (k = 0; k < nem && k < top; k++)
            fprintf(cp_out, "  %-16s %10.4g %10.4g %12.4g %14.4g %8s\n",
                    em[k].name, em[k].i, em[k].w, em[k].j, em[k].mttf,
                    em[k].fail ? "FAIL" : "ok");
    }
    /* Enhancement-502: report the two reasons separately. The old message said
     * "no width given" for BOTH, so a resistor written `w=-0.5u` was reported
     * as missing the width its author had just supplied. */
    if (nnowidth)
        fprintf(cp_out, "  (%d resistor%s skipped for EM: no width given -- add "
                        "`w=<m>` to check %s for electromigration)\n",
                nnowidth, nnowidth == 1 ? "" : "s",
                nnowidth == 1 ? "it" : "them");
    if (nbadwidth)
        fprintf(cp_out, "  (%d resistor%s skipped for EM: the width given is not "
                        "a positive finite number)\n",
                nbadwidth, nbadwidth == 1 ? "" : "s");

    for (k = 0; k < nir; k++) tfree(ir[k].name);
    for (k = 0; k < nem; k++) tfree(em[k].name);
    tfree(ir); tfree(em);
}
