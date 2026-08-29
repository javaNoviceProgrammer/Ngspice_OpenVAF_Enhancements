/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1988 Wayne A. Christopher, U. C. Berkeley CAD Group
Modified: 2000 AlansFixes, 2013/2015 patch by Krzysztof Blaszkowski
**********/

/*
 * This module replaces the old "writedata" routines in nutmeg.
 * Unlike the writedata routines, the OUT routines are only called by
 * the simulator routines, and only call routines in nutmeg.  The rest
 * of nutmeg doesn't deal with OUT at all.
 */

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/plot.h"
#include "ngspice/sim.h"
#include "ngspice/inpdefs.h"        /* for INPtables */
#include "ngspice/ifsim.h"
#include "ngspice/jobdefs.h"
#include "ngspice/iferrmsg.h"
#include "circuits.h"
#include "outitf.h"
#include "variable.h"
#include <fcntl.h>
#include "ngspice/cktdefs.h"
#include "ngspice/acdefs.h"          /* Enhancement: ACAN for the sweep progress bar */
#include "ngspice/trcvdefs.h"        /* Enhancement: TRCV (DC sweep) for the progress bar */
#include "breakp2.h"
#include "runcoms.h"
#include "plotting/graf.h"
#include "../misc/misc_time.h"

extern char *spice_analysis_get_name(int index);
extern char *spice_analysis_get_description(int index);
extern int EVTsetup_plot(CKTcircuit* ckt, char* plotname);

extern IFsimulator SIMinfo;
extern char Spice_Build_Date[];

extern unsigned long long getMemorySize(void);
extern unsigned long long getPeakRSS(void);
extern unsigned long long getCurrentRSS(void);
extern unsigned long long getAvailableMemorySize(void);

static int beginPlot(JOB *analysisPtr, CKTcircuit *circuitPtr, char *cktName, char *analName,
                     char *refName, int refType, int numNames, char **dataNames, int dataType,
                     bool windowed, runDesc **runp);
static int addDataDesc(runDesc *run, char *name, int type, int ind, int meminit);
static int addSpecialDesc(runDesc *run, char *name, char *devname, char *param, int depind, int meminit);
static void fileInit(runDesc *run);
static void fileInit_pass2(runDesc *run);
static void fileStartPoint(FILE *fp, bool bin, int num);
static void fileAddRealValue(FILE *fp, bool bin, double value);
static void fileAddComplexValue(FILE *fp, bool bin, IFcomplex value);
static void fileEndPoint(FILE *fp, bool bin);
static void fileEnd(runDesc *run);
static void plotInit(runDesc *run);
static void plotAddRealValue(dataDesc *desc, double value);
static void plotAddComplexValue(dataDesc *desc, IFcomplex value);
static void plotEnd(runDesc *run);
static bool parseSpecial(char *name, char *dev, char *param, char *ind);
static bool name_eq(char *n1, char *n2);
static bool getSpecial(dataDesc *desc, runDesc *run, IFvalue *val);
static void freeRun(runDesc *run);
static int InterpFileAdd(runDesc *plotPtr, IFvalue *refValue, IFvalue *valuePtr);
static int InterpPlotAdd(runDesc *plotPtr, IFvalue *refValue, IFvalue *valuePtr);
static inline int vlength2delta(int len);

/*Output data to spice module*/
#ifdef TCL_MODULE
#include "ngspice/tclspice.h"
#elif defined SHARED_MODULE
extern int sh_ExecutePerLoop(void);
extern int sh_vecinit(runDesc *run);
#endif

/*Suppressing progress info in -o option */
#ifndef HAS_WINGUI
extern bool orflag;
#endif

/* Enhancement: live progress bar on the "Reference value" line.
 *
 * outp_progress_frac() returns the fraction (0..1) of a DC / AC / transient
 * sweep completed, or -1 when the running analysis has no well-defined span
 * (operating point, noise, ...). Transient uses the elapsed time against TSTOP;
 * AC uses the frequency against the (linear or log) start/stop band; DC sweeps
 * use the accepted-point count against the product of the nested step counts. */
#ifndef HAS_WINGUI
#define OUTP_BARLEN 24

/* Enhancement-184: state so the bar can be forced to 100% at end of run. The
 * throttled per-point print usually skips the final sweep point, leaving the
 * bar frozen just below 100%. */
static int outp_bar_shown = 0;      /* a sweep bar was drawn during this run */
static double outp_last_refval = 0.0;

static double
outp_progress_frac(runDesc *run, double refval)
{
    CKTcircuit *ckt = run ? run->circuit : NULL;
    JOB *job;
    const char *nm;

    if (!ckt || !ckt->CKTcurJob)
        return -1.0;
    job = ckt->CKTcurJob;
    nm = spice_analysis_get_name(job->JOBtype);
    if (!nm)
        return -1.0;

    if (strcmp(nm, "TRAN") == 0) {
        double span = ckt->CKTfinalTime - ckt->CKTinitTime;
        if (span > 0.0)
            return (ckt->CKTtime - ckt->CKTinitTime) / span;
    } else if (strcmp(nm, "AC") == 0) {
        ACAN *ac = (ACAN *) job;
        double f0 = ac->ACstartFreq, f1 = ac->ACstopFreq;
        if (ac->ACstepType == LINEAR) {
            if (f1 != f0)
                return (refval - f0) / (f1 - f0);
        } else {                        /* DECADE / OCTAVE: logarithmic band */
            if (f0 > 0.0 && f1 > 0.0 && refval > 0.0 && f1 != f0)
                return log(refval / f0) / log(f1 / f0);
        }
    } else if (strcmp(nm, "NOISE") == 0) {   /* frequency-swept, like AC */
        NOISEAN *ns = (NOISEAN *) job;
        double f0 = ns->NstartFreq, f1 = ns->NstopFreq;
        if (ns->NstpType == LINEAR) {
            if (f1 != f0)
                return (refval - f0) / (f1 - f0);
        } else {
            if (f0 > 0.0 && f1 > 0.0 && refval > 0.0 && f1 != f0)
                return log(refval / f0) / log(f1 / f0);
        }
    } else if (strcmp(nm, "DC") == 0) {
        TRCV *dc = (TRCV *) job;
        double total = 1.0;
        int i;
        for (i = 0; i <= dc->TRCVnestLevel; i++) {
            double s = dc->TRCVvStep[i];
            if (s != 0.0)
                total *= floor(fabs((dc->TRCVvStop[i] - dc->TRCVvStart[i]) / s)
                               + 1.0 + 0.5);
        }
        if (total > 0.0)
            return (double) run->pointCount / total;
    }
    return -1.0;
}

/* Enhancement-477: outer progress for the commands that run N analyses in a
 * loop -- sweep, montecarlo, highsigma, wcd.
 *
 * Those commands set `ft_optimizing` to silence per-point chatter (see the
 * early return in outp_print_reference below, Enhancement-130), so until now a
 * long sweep printed its banner and then nothing at all. The inner analysis's
 * own bar is the wrong thing to show: it runs 0 -> 100% for EVERY point, so on
 * a 40-point sweep it resets forty times and never says how far the sweep is,
 * and it redraws the same terminal line with '\r', so an outer bar and the
 * inner bar would overwrite each other.
 *
 * So one line carries both -- the outer point counter and bar, plus the inner
 * analysis's own fraction as a secondary field:
 *
 *     sweep: point  7/40  [=========               ]  17%   (tran 63%)
 *
 * BOTH DRIVERS ARE NEEDED. While a point runs, the loop command is blocked
 * inside the analysis and cannot refresh anything, so the intra-point updates
 * have to come from here, off the analysis's own data path. But the DEFAULT
 * analysis is `op`, which produces no swept data points at all and therefore
 * never reaches this code -- so the loop command also draws at each point
 * boundary. Neither alone covers both regimes: many fast points, or few slow
 * ones.
 *
 * `total <= 0` means indeterminate -- `wcd` iterates to convergence and has no
 * count known in advance, so it gets a counter and no percentage rather than a
 * bar against `maxiter` that would finish early and read as wrong. */
#define OUTP_LOOP_WIDTH 76

static const char *outp_loop_label = NULL;
static const char *outp_loop_noun = NULL;   /* "point" / "sample" / ... */
static int outp_loop_total = 0;         /* <= 0: indeterminate */
static int outp_loop_index = 0;
static int outp_loop_digits = 1;
static int outp_loop_active = 0;
static int outp_loop_show = 0;          /* resolved once in outp_loop_begin */
static int outp_loop_drawn = 0;
static clock_t outp_loop_lastdraw = 0;
/* Enhancement-478: how many loop commands are nested INSIDE the one that owns
 * the line. A loop command can run another as its `-analysis`
 * (`sweep ... -analysis "montecarlo ..."`), and this state is a single set of
 * statics: the inner begin() overwrote the outer's label, total and index, and
 * the inner end() cleared `outp_loop_active` for both. The outer sweep's bar
 * then vanished for the rest of the run, and the line was left reading
 * `montecarlo: sample 6/6 [====] 100%` while the outer sweep still had points
 * to go -- a completed bar for work that was not finished.
 *
 * The OUTER loop is the one worth showing, for exactly the reason this feature
 * does not reuse the per-analysis bar: the inner loop restarts from zero at
 * every outer point. So a nested begin() is counted and ignored, its end()
 * decrements, and the outer keeps the line throughout. */
static int outp_loop_nested = 0;

/* The running analysis's name, lower-cased for display ("tran", "ac", ...). */
static const char *
outp_loop_inner_name(runDesc *run, char *buf, size_t len)
{
    CKTcircuit *ckt = run ? run->circuit : NULL;
    const char *raw;
    size_t i;

    if (!ckt || !ckt->CKTcurJob)
        return NULL;
    raw = spice_analysis_get_name(ckt->CKTcurJob->JOBtype);
    if (!raw)
        return NULL;
    for (i = 0; i + 1 < len && raw[i]; i++)
        buf[i] = (char) tolower((unsigned char) raw[i]);
    buf[i] = '\0';
    return buf[0] ? buf : NULL;
}

static void
outp_loop_draw(int have_inner, double inner, const char *iname)
{
    char bar[OUTP_BARLEN + 1];
    char line[OUTP_LOOP_WIDTH + 64];
    int k, filled, n;

    if (!outp_loop_active || !outp_loop_show)
        return;
    if (have_inner) {
        if (inner < 0.0)
            inner = 0.0;
        if (inner > 1.0)
            inner = 1.0;
    }

    if (outp_loop_total > 0) {
        /* The inner fraction advances the OUTER bar within the point, so the
         * bar moves smoothly instead of stepping once per analysis. */
        double done = (double) outp_loop_index + (have_inner ? inner : 0.0);
        double frac = done / (double) outp_loop_total;

        if (frac < 0.0)
            frac = 0.0;
        if (frac > 1.0)
            frac = 1.0;
        filled = (int) (frac * OUTP_BARLEN + 0.5);
        for (k = 0; k < OUTP_BARLEN; k++)
            bar[k] = (k < filled) ? '=' : ' ';
        bar[OUTP_BARLEN] = '\0';
        n = snprintf(line, sizeof line, " %s: %s %*d/%d  [%s] %3.0f%%",
                     outp_loop_label, outp_loop_noun, outp_loop_digits,
                     outp_loop_index + 1, outp_loop_total, bar, frac * 100.0);
    } else {
        n = snprintf(line, sizeof line, " %s: %s %d",
                     outp_loop_label, outp_loop_noun, outp_loop_index + 1);
    }

    if (have_inner && iname && n > 0 && n < (int) sizeof line)
        (void) snprintf(line + n, sizeof line - (size_t) n, "   (%s %3.0f%%)",
                        iname, inner * 100.0);

    /* Padded AND truncated to one constant width. Padding stops '\r' leaving
     * stale tail characters from a longer previous line; truncating stops the
     * line exceeding it, which matters because a wrapped line puts the cursor
     * on the second row and '\r' would then redraw only that row, leaving the
     * first stuck on screen. " montecarlo: sample 100000/100000  [...] 100%
     * (tran 100%)" is about 80 characters, so this is reachable, and the inner
     * field is the part that gets clipped -- the right thing to lose. */
    fprintf(stdout, "%-*.*s\r", OUTP_LOOP_WIDTH, OUTP_LOOP_WIDTH, line);
    fflush(stdout);
    outp_loop_drawn = 1;
    outp_loop_lastdraw = clock();
}

/* Print the throttled "Reference value" status line, with a progress bar
 * appended when the sweep fraction is known. Redraws in place via '\r', like
 * the original line, and keeps a constant width so no stale characters remain. */
static void
outp_print_reference(runDesc *run, double refval)
{
    double frac;

    /* Enhancement-477: inside a loop command this is the only code that runs
     * while a point is in progress, so it drives the intra-point refresh.
     * Deliberately BEFORE the ft_optimizing return -- the loop commands set
     * that flag, and it is what used to make a sweep silent. `outp_bar_shown`
     * is left alone on purpose, so outp_finish_reference() stays a no-op and
     * cannot stamp a stray 100% "Reference value" line over the loop line at
     * the end of every point. */
    if (outp_loop_active) {
        char nm[16];
        const char *iname = outp_loop_inner_name(run, nm, sizeof nm);
        double ifrac = outp_progress_frac(run, refval);
        outp_loop_draw(ifrac >= 0.0, ifrac, iname);
        return;
    }

    if (ft_optimizing)          /* Enhancement-130: quiet during optimizer iterations */
        return;
    frac = outp_progress_frac(run, refval);
    outp_last_refval = refval;               /* Enhancement-184: remember the point */
    if (frac >= 0.0)
        outp_bar_shown = 1;

    if (frac >= 0.0) {
        char bar[OUTP_BARLEN + 1];
        int filled, k;
        if (frac > 1.0)
            frac = 1.0;
        filled = (int) (frac * OUTP_BARLEN + 0.5);
        for (k = 0; k < OUTP_BARLEN; k++)
            bar[k] = (k < filled) ? '=' : ' ';
        bar[OUTP_BARLEN] = '\0';
        fprintf(stdout, " Reference value : % 12.5e  [%s] %3.0f%%\r",
                refval, bar, frac * 100.0);
    } else {
        fprintf(stdout, " Reference value : % 12.5e\r", refval);
    }
    fflush(stdout);
}

/* Enhancement-184: force the bar to 100% once a swept run has finished. The
 * throttled per-point print usually skips the final point (it lands within the
 * 0.25 s window), so the last drawn bar sits below 100%; reprint it full, in
 * place, using the sweep's true endpoint, before the "No. of Data Rows" line.
 * A no-op unless a bar was actually shown (op-point / tf / ... never draw). */
static void
outp_finish_reference(runDesc *run)
{
    CKTcircuit *ckt = run ? run->circuit : NULL;
    double endref = outp_last_refval;
    char bar[OUTP_BARLEN + 1];
    int k;

    if (!outp_bar_shown)
        return;
    outp_bar_shown = 0;                 /* one-shot */
    if (ft_optimizing || ft_norefprint || cp_background)
        return;

    if (ckt && ckt->CKTcurJob) {        /* prefer the sweep's exact endpoint */
        const char *nm = spice_analysis_get_name(ckt->CKTcurJob->JOBtype);
        if (nm) {
            if (strcmp(nm, "TRAN") == 0)
                endref = ckt->CKTfinalTime;
            else if (strcmp(nm, "AC") == 0)
                endref = ((ACAN *) ckt->CKTcurJob)->ACstopFreq;
            else if (strcmp(nm, "NOISE") == 0)
                endref = ((NOISEAN *) ckt->CKTcurJob)->NstopFreq;
            /* DC: the last printed source value is the sweep endpoint */
        }
    }

    for (k = 0; k < OUTP_BARLEN; k++)
        bar[k] = '=';
    bar[OUTP_BARLEN] = '\0';
    fprintf(stdout, " Reference value : % 12.5e  [%s] %3.0f%%\r",
            endref, bar, 100.0);
    fflush(stdout);
}
#endif

/* Enhancement-477: the loop-progress entry points, called by the commands in
 * com_sweep.c. Defined unconditionally so the Windows GUI build still links;
 * there the status bar is fed by SetAnalyse() and this line has no place to go.
 *
 * `mode` is tri-state: 1 forced on, 0 forced off, -1 auto. Auto means "only
 * when stdout is a terminal", because the line is redrawn with '\r' and a
 * redirected run would otherwise collect one enormous line of bar frames in
 * the file. The existing per-analysis bar does NOT make that distinction --
 * that is why capturing a plain `tran` to a file yields a screenful of
 * "Reference value" frames -- but repeating the behaviour in new output is not
 * an improvement, and the regression suites capture stdout. */
void
outp_loop_begin(const char *label, const char *noun, int total, int mode)
{
#ifndef HAS_WINGUI
    int d = 1, t = total;

    if (outp_loop_active) {             /* Enhancement-478: nested -- see above */
        outp_loop_nested++;
        return;
    }

    outp_loop_label = label ? label : "loop";
    outp_loop_noun = noun ? noun : "point";
    outp_loop_total = total;
    outp_loop_index = 0;
    outp_loop_active = 1;
    outp_loop_drawn = 0;
    outp_loop_lastdraw = 0;
    while (t >= 10) { t /= 10; d++; }
    outp_loop_digits = d;

    outp_loop_show = (mode > 0) || (mode < 0 && isatty(fileno(stdout)));
    if (orflag || ft_norefprint || cp_background)
        outp_loop_show = 0;             /* same three mutes as the analysis bar */

    /* Deliberately NO draw here, and none for the first point either (see
     * outp_loop_point). A frame ends with '\r' and leaves the cursor at column
     * 0 of a line it has filled to OUTP_LOOP_WIDTH. Anything printed before the
     * next redraw overwrites only its LEADING columns and the rest of the frame
     * survives as a tail -- and the first analysis of a run prints the solver
     * announcement, which is shorter than the frame:
     *
     *   Using SPARSE 1.3 as Direct Linear Solver          ]   0%
     *
     * Every later point is safe because its frame is drawn AFTER the preceding
     * analysis has finished printing. Only the first one has nothing in front
     * of it, so it is the one that must wait. */
#else
    NG_IGNORE(label); NG_IGNORE(noun); NG_IGNORE(total); NG_IGNORE(mode);
#endif
}

void
outp_loop_point(int index)
{
#ifndef HAS_WINGUI
    if (!outp_loop_active)
        return;
    outp_loop_index = index;
    if (!outp_loop_show)
        return;
    /* The first point's frame would be drawn before ANY analysis has run, so
     * the solver announcement lands on top of it (see outp_loop_begin). Skip
     * it: the bar appears either from the first intra-point refresh, or at the
     * second point's boundary, both of which follow that output. */
    if (index == 0)
        return;
    /* Throttled like the analysis bar: a sweep may run up to SW_MAXPTS points
     * and one write per point would cost more than the solve on a fast deck.
     * The index is recorded above regardless, so the next draw is current. */
    if (outp_loop_drawn &&
        (clock() - outp_loop_lastdraw) < (clock_t) (0.25 * CLOCKS_PER_SEC))
        return;
    outp_loop_draw(0, 0.0, NULL);
#else
    NG_IGNORE(index);
#endif
}

void
outp_loop_end(void)
{
#ifndef HAS_WINGUI
    if (outp_loop_nested > 0) {         /* Enhancement-478: an inner loop ended */
        outp_loop_nested--;
        return;
    }
    if (!outp_loop_active)
        return;                         /* idempotent: every abort path may call */
    if (outp_loop_show) {
        if (outp_loop_total > 0) {
            outp_loop_index = outp_loop_total - 1;
            outp_loop_draw(1, 1.0, NULL);   /* finish at a full bar, not 97% */
        } else {
            outp_loop_draw(0, 0.0, NULL);
        }
        fputc('\n', stdout);            /* release the line for what follows */
        fflush(stdout);
    }
    outp_loop_active = 0;
    outp_loop_show = 0;
    outp_loop_drawn = 0;
    outp_loop_label = NULL;
    outp_loop_noun = NULL;
    outp_loop_nested = 0;
#endif
}

// fixme
//   ugly hack to work around missing api to specify the "type" of signals
int fixme_onoise_type = SV_NOTYPE;
int fixme_inoise_type = SV_NOTYPE;


#define DOUBLE_PRECISION    15


static clock_t lastclock, currclock, startclock;
static double *rowbuf;
static size_t column, rowbuflen;

static bool shouldstop = FALSE; /* Tell simulator to stop next time it asks. */

static bool interpolated = FALSE;
static double *valueold, *valuenew;

#ifdef SHARED_MODULE
static bool savenone = FALSE;
#endif

/* The two "begin plot" routines share all their internals... */

int
OUTpBeginPlot(CKTcircuit *circuitPtr, JOB *analysisPtr,
              IFuid analName,
              IFuid refName, int refType,
              int numNames, IFuid *dataNames, int dataType, runDesc **plotPtr)
{
    char *name;

    if (ft_curckt->ci_ckt == circuitPtr)
        name = ft_curckt->ci_name;
    else
        name = "circuit name";

    return (beginPlot(analysisPtr, circuitPtr, name,
                      analName, refName, refType, numNames,
                      dataNames, dataType, FALSE,
                      plotPtr));
}


static int
beginPlot(JOB *analysisPtr, CKTcircuit *circuitPtr, char *cktName, char *analName, char *refName, int refType, int numNames, char **dataNames, int dataType, bool windowed, runDesc **runp)
{
    runDesc *run;
    struct save_info *saves;
    bool *savesused = NULL;
    int numsaves;
    int i, j, depind = 0;
    char namebuf[BSIZE_SP], parambuf[BSIZE_SP], depbuf[BSIZE_SP];
    char *ch, tmpname[BSIZE_SP];
    bool saveall  = TRUE;
    bool savealli = FALSE;
    bool savenosub = FALSE;
    bool savenointernals = FALSE;
    char *an_name;
    int initmem;

    /*to resume a run, Reassign the file pointer and return
      (requires *runp to be NULL if this is not needed)*/
    if (dataType == 666 && numNames == 666) {
        run = *runp;
        run->writeOut = ft_getOutReq(&run->fp, &run->runPlot, &run->binary,
                                     run->type, run->name);

    } else {
        /*end saj*/

        /* Check to see if we want to print informational data. */
        if (cp_getvar("printinfo", CP_BOOL, NULL, 0))
            fprintf(cp_err, "(debug printing enabled)\n");

        /* Check to see if we want to save only interpolated data. */
        if (cp_getvar("interp", CP_BOOL, NULL, 0)) {
            interpolated = TRUE;
            fprintf(cp_out, "Warning: Interpolated raw file data!\n\n");
        }

        *runp = run = TMALLOC(struct runDesc, 1);

        /* First fill in some general information. */
        run->analysis = analysisPtr;
        run->circuit = circuitPtr;
        run->name = copy(cktName);
        run->type = copy(analName);
        run->windowed = windowed;
        run->numData = 0;

        an_name = spice_analysis_get_name(analysisPtr->JOBtype);
        ft_curckt->ci_last_an = an_name;

        /* Now let's see which of these things we need.  First toss in the
         * reference vector.  Then toss in anything that getSaves() tells
         * us to save that we can find in the name list.  Finally unpack
         * the remaining saves into parameters.
         */
        numsaves = ft_getSaves(&saves);
        if (numsaves) {
            savesused = TMALLOC(bool, numsaves);
            saveall = FALSE;
            for (i = 0; i < numsaves; i++) {
                if (saves[i].analysis && !cieq(saves[i].analysis, an_name)) {
                    /* ignore this one this time around */
                    savesused[i] = TRUE;
                    continue;
                }

                /*  Check for ".save all" and new synonym ".save allv"  */

                if (cieq(saves[i].name, "all") || cieq(saves[i].name, "allv")) {
                    saveall = TRUE;
                    savesused[i] = TRUE;
                    saves[i].used = 1;
                    continue;
                }

                /*  And now for the new ".save alli" option  */

                if (cieq(saves[i].name, "alli")) {
                    savealli = TRUE;
                    savesused[i] = TRUE;
                    saves[i].used = 1;
                    continue;
                }

                if (cieq(saves[i].name, "nosub")) {
                    savenosub = TRUE;
                    savesused[i] = TRUE;
                    saves[i].used = 1;
                    continue;
                }

                if (cieq(saves[i].name, "nointernals")) {
                    savenointernals = TRUE;
                    savesused[i] = TRUE;
                    saves[i].used = 1;
                    continue;
                }
#ifdef SHARED_MODULE
                /* this may happen if shared ngspice*/
                if (cieq(saves[i].name, "none")) {
                    savenone = TRUE;
                    saveall = TRUE;
                    savesused[i] = TRUE;
                    saves[i].used = 1;
                    continue;
                }
#endif
            }
        }

        if (numsaves && !saveall && !savenosub)
            initmem = numsaves;
        else
            initmem = numNames;

        /* Pass 0. */
        if (refName) {
            addDataDesc(run, refName, refType, -1, initmem);
            for (i = 0; i < numsaves; i++)
                if (!savesused[i] && name_eq(saves[i].name, refName)) {
                    savesused[i] = TRUE;
                    saves[i].used = 1;
                }
        } else {
            run->refIndex = -1;
        }


        /* Pass 1. */
        if (numsaves && !saveall && !savenosub && !savenointernals) {
            for (i = 0; i < numsaves; i++) {
                if (!savesused[i]) {
                    for (j = 0; j < numNames; j++) {
                        if (name_eq(saves[i].name, dataNames[j])) {
                            addDataDesc(run, dataNames[j], dataType, j, initmem);
                            savesused[i] = TRUE;
                            saves[i].used = 1;
                            break;
                        }
                        /* generate a vector of real time information */
                        else if (ft_ngdebug && refName && eq(refName, "time") && eq(saves[i].name, "speedcheck")) {
                            addDataDesc(run, "speedcheck", IF_REAL, j, initmem);
                            savesused[i] = TRUE;
                            saves[i].used = 1;
                            break;
                        }
                        else if (ft_ngdebug && refName && eq(refName, "time") && eq(saves[i].name, "deltacheck")) {
                            addDataDesc(run, "deltacheck", IF_REAL, j, initmem);
                            savesused[i] = TRUE;
                            saves[i].used = 1;
                            break;
                        }
                    }
                }
            }
        } else {
            for (i = 0; i < numNames; i++)
                if (!refName || !name_eq(dataNames[i], refName))
                    /*  Save the node (with restrictions) */
                        /* don't save subckt nodes */
                    if (!(savenosub && strchr(dataNames[i], '.')) &&
                        /* no internals at all, but still #branch */
                        (!(savenointernals && strstr(dataNames[i], "#")) || strstr(dataNames[i], "#branch")) &&
                        /* created by .probe */
                        !strstr(dataNames[i], "probe_int_") &&
                        /* don't save internal device nodes */
                        !strstr(dataNames[i], "#internal") &&
                        !strstr(dataNames[i], "#source") &&
                        !strstr(dataNames[i], "#drain") &&
                        !strstr(dataNames[i], "#collector") &&
                        !strstr(dataNames[i], "#collCX") &&
                        !strstr(dataNames[i], "#emitter") &&
                        !strstr(dataNames[i], "#base"))
                    {
                        addDataDesc(run, dataNames[i], dataType, i, initmem);
                    }
            /* generate a vector of real time information */
            if (ft_ngdebug && refName && eq(refName, "time")) {
                 addDataDesc(run, "speedcheck", IF_REAL, numNames, initmem);
                 addDataDesc(run, "deltacheck", IF_REAL, numNames, initmem);
            }
        }

        /* Pass 1 and a bit.
           This is a new pass which searches for all the internal device
           nodes, and saves the terminal currents instead  */

        if (savealli) {
            depind = 0;
            for (i = 0; i < numNames; i++) {
                if (strstr(dataNames[i], "#internal") ||
                    strstr(dataNames[i], "#source") ||
                    strstr(dataNames[i], "#drain") ||
                    strstr(dataNames[i], "#collector") ||
                    strstr(dataNames[i], "#collCX") ||
                    strstr(dataNames[i], "#emitter") ||
                    strstr(dataNames[i], "#base"))
                {
                    tmpname[0] = '@';
                    tmpname[1] = '\0';
                    strncat(tmpname, dataNames[i], BSIZE_SP-1);
                    ch = strchr(tmpname, '#');

                    if (strstr(ch, "#collector")) {
                        strcpy(ch, "[ic]");
                    } else if (strstr(ch, "#collCX")) {
                        strcpy(ch, "[ic]");
                    } else if (strstr(ch, "#base")) {
                        strcpy(ch, "[ib]");
                    } else if (strstr(ch, "#emitter")) {
                        strcpy(ch, "[ie]");
                        if (parseSpecial(tmpname, namebuf, parambuf, depbuf))
                            addSpecialDesc(run, tmpname, namebuf, parambuf, depind, initmem);
                        strcpy(ch, "[is]");
                    } else if (strstr(ch, "#drain")) {
                        strcpy(ch, "[id]");
                        if (parseSpecial(tmpname, namebuf, parambuf, depbuf))
                            addSpecialDesc(run, tmpname, namebuf, parambuf, depind, initmem);
                        strcpy(ch, "[ig]");
                    } else if (strstr(ch, "#source")) {
                        strcpy(ch, "[is]");
                        if (parseSpecial(tmpname, namebuf, parambuf, depbuf))
                            addSpecialDesc(run, tmpname, namebuf, parambuf, depind, initmem);
                        strcpy(ch, "[ib]");
                    } else if (strstr(ch, "#internal") && (tmpname[1] == 'd')) {
                        strcpy(ch, "[id]");
                    } else {
                        fprintf(cp_err,
                                "Debug: could output current for %s\n", tmpname);
                        continue;
                    }
                    if (parseSpecial(tmpname, namebuf, parambuf, depbuf)) {
                        if (*depbuf) {
                            fprintf(stderr,
                                    "Warning : unexpected dependent variable on %s\n", tmpname);
                        } else {
                            addSpecialDesc(run, tmpname, namebuf, parambuf, depind, initmem);
                        }
                    }
                }
            }
        }


        /* Pass 2. */
        for (i = 0; i < numsaves; i++) {

            if (savesused[i])
                continue;

            if (!parseSpecial(saves[i].name, namebuf, parambuf, depbuf)) {
                if (saves[i].analysis)
                    fprintf(cp_err, "Warning: can't parse '%s': ignored\n",
                            saves[i].name);
                continue;
            }

            /* Now, if there's a dep variable, do we already have it? */
            if (*depbuf) {
                for (j = 0; j < run->numData; j++)
                    if (name_eq(depbuf, run->data[j].name))
                        break;
                if (j == run->numData) {
                    /* Better add it. */
                    for (j = 0; j < numNames; j++)
                        if (name_eq(depbuf, dataNames[j]))
                            break;
                    if (j == numNames) {
                        fprintf(cp_err,
                                "Warning: can't find '%s': value '%s' ignored\n",
                                depbuf, saves[i].name);
                        continue;
                    }
                    addDataDesc(run, dataNames[j], dataType, j, initmem);
                    savesused[i] = TRUE;
                    saves[i].used = 1;
                    depind = j;
                } else {
                    depind = run->data[j].outIndex;
                }
            }

            /* Enhancement-418: resolve the device name, and say so when it does
             * not resolve.
             *
             * Nothing between `settrace` and the PER-POINT `INPaName` ever
             * looked a saved `@dev[param]` name up. `addSpecialDesc` only
             * interns the string, and `getSpecial`'s caller discards
             * INPaName's E_NODEV/E_BADPARM -- so a misspelled device, a bogus
             * parameter or an unexpanded wildcard produced a registered vector
             * that stayed 0 long, silently, while `print`, `meas` and `wrdata`
             * all report the same name loudly.
             *
             * Two things happen here. A hierarchical spelling is REWRITTEN to
             * the form that resolves: `@x1.r1[i]` is what Enhancement-410 made
             * work for `print`, `alter` and `show`, but the saved name needs
             * ngspice's flattened `r.x1.r1`, so the display name stays the
             * user's and only the lookup name changes. Anything still
             * unresolvable is WARNED about -- and then added anyway, because a
             * bracket-less `@name` is a simulator statistic served by a
             * different path and dropping entries here would change what the
             * plot contains. */
            if (*namebuf && *parambuf && circuitPtr &&
                ft_sim && ft_sim->findInstance) {
                if (strpbrk(namebuf, "*?")) {
                    fprintf(cp_err,
                            "Warning: save '%s': a wildcard device name is not "
                            "expanded here, so this vector will stay empty.\n"
                            "         Name each device, or use "
                            "`.options savecurrents` for every terminal current.\n",
                            saves[i].name);
                } else {
                    /* INPaName is the very routine the per-point read uses, so
                     * asking it here validates the device AND the parameter by
                     * exactly the rule that will apply later -- rather than
                     * duplicating a weaker test. Its E_NODEV/E_BADPARM is what
                     * getSpecial's caller has always thrown away. */
                    IFvalue tmpval;
                    GENinstance *tfast = NULL;
                    int tdev = -1, tdtype = 0, err;

                    err = INPaName(parambuf, &tmpval, circuitPtr, &tdev,
                                   namebuf, &tfast, ft_sim, &tdtype, NULL);

                    if (err != OK) {
                        /* Enhancement-410's reconstruction: an instance inside a
                         * subcircuit is flattened to `<type>.<path>`, the type
                         * letter being the first character of the LOCAL name.
                         * Retry there before giving up. */
                        const char *local = strrchr(namebuf, '.');
                        char hbuf[BSIZE_SP];

                        if (local && local[1] && tolower_c(local[1]) != 'x' &&
                            snprintf(hbuf, sizeof hbuf, "%c.%s", local[1],
                                     namebuf) < (int) sizeof hbuf) {
                            tfast = NULL;
                            tdev = -1;
                            if (INPaName(parambuf, &tmpval, circuitPtr, &tdev,
                                         hbuf, &tfast, ft_sim, &tdtype,
                                         NULL) == OK) {
                                strncpy(namebuf, hbuf, BSIZE_SP - 1);
                                namebuf[BSIZE_SP - 1] = '\0';
                                err = OK;
                            }
                        }
                    }

                    /* Enhancement-507: only E_BADPARM means the name is not
                     * one the device has.
                     *
                     * INPaName both FINDS the name and asks the device for its
                     * value, and any failure of the second half arrived here as
                     * the first half's message. An operating-point variable is
                     * registered IF_ASK like any other askable parameter, so the
                     * name resolves -- but at `save` time no analysis has run, so
                     * the ask fails and the user was told "device has no
                     * parameter 'gv'" about a name the device does have and that
                     * `print` and `meas` both resolve. The netlist `.save` form
                     * reported the same case correctly, so the two spellings of
                     * one request disagreed. */
                    if (err == E_NODEV)
                        fprintf(cp_err,
                                "Warning: save '%s': no such device, so this "
                                "vector will stay empty.\n", saves[i].name);
                    else if (err == E_BADPARM)
                        fprintf(cp_err,
                                "Warning: save '%s': device has no parameter "
                                "'%s', so this vector will stay empty.\n",
                                saves[i].name, parambuf);
                    else if (err != OK)
                        fprintf(cp_err,
                                "Warning: save '%s': '%s' has no value yet -- it "
                                "is an operating-point variable and no analysis "
                                "has computed one. It is recorded per point once "
                                "an analysis runs.\n",
                                saves[i].name, parambuf);
                }
            }

            addSpecialDesc(run, saves[i].name, namebuf, parambuf, depind, initmem);
        }

        /* Enhancement-493: a saved name that matched nothing was dropped in
         * silence.
         *
         * Pass 1 walks each `.save`/`.probe` item against the analysis's own
         * vector names and marks the ones it places; anything it fails to match
         * simply stayed unmarked, and the run continued without it. So
         * `.save v(n) v(nosuch)` recorded v(n), dropped the typo and said
         * nothing -- the analysis succeeded and the vector the user asked for
         * was merely absent. `.probe v(nosuch)` reaches the same path, which is
         * why a mistyped node there was silent while a mistyped SOURCE in the
         * same card is reported by the measure-source pass ("Could not find the
         * instance line for ...").
         *
         * Enhancement-418 already says this for the `@dev[param]` spelling --
         * "no such device, so this vector will stay empty" -- so the plain node
         * spelling was the one route left quiet. Warn rather than refuse: an
         * absent vector is not a wrong answer, and a deck that saves a node it
         * does not always build is a real idiom. */
        if (numsaves) {
            for (i = 0; i < numsaves; i++) {
                bool matched;

                if (!saves[i].name || strchr(saves[i].name, '@') ||
                    strchr(saves[i].name, '['))
                    continue;           /* E-418 already speaks for these */

                /* savesused[] is already set for the items the loop above
                   consumed -- the `all`/`allv` keywords themselves, and anything
                   belonging to another analysis -- so honour it first in either
                   mode. Under `save all`, which `.probe` turns on, Pass 1 never
                   runs, so an explicit name still has to be matched here;
                   everything real is saved in that mode, so a name matching
                   nothing is genuinely absent either way. */
                matched = savesused[i];
                if (!matched && (saveall || savenosub || savenointernals)) {
                    matched = (refName && name_eq(saves[i].name, refName));
                    for (j = 0; !matched && j < numNames; j++)
                        if (name_eq(saves[i].name, dataNames[j]))
                            matched = TRUE;
                }

                /* Enhancement-496: an INFERRED save is never reported.
                 * `.option saveused` registers what it believes the control
                 * block mentions, and deliberately over-collects; a name it
                 * guessed wrong is not something the author wrote, so telling
                 * them a vector is missing names a plot keyword as a signal.
                 * A name the deck really did write still reports, unchanged. */
                if (!matched && !saves[i].autosaved)
                    fprintf(cp_err,
                            "Warning: save '%s': nothing of that name is in this "
                            "analysis,\n         so no such vector is produced.\n",
                            saves[i].name);
            }
        }

        if (numsaves) {
            for (i = 0; i < numsaves; i++) {
                tfree(saves[i].analysis);
                tfree(saves[i].name);
            }
            tfree(saves);
            tfree(savesused);
        }

        if (numNames &&
            ((run->numData == 1 && run->refIndex != -1) ||
             (run->numData == 0 && run->refIndex == -1)))
        {
            fprintf(cp_err, "Error: no data saved for %s; analysis not run\n",
                    spice_analysis_get_description(analysisPtr->JOBtype));
            return E_NOTFOUND;
        }

        /* Now that we have our own data structures built up, let's see what
         * nutmeg wants us to do.
         */
        run->writeOut = ft_getOutReq(&run->fp, &run->runPlot, &run->binary,
                                     run->type, run->name);

        if (run->writeOut) {
            fileInit(run);
        } else {
            plotInit(run);
            if (refName)
                run->runPlot->pl_ndims = 1;
#ifdef XSPICE
            /* set the current plot name into the event job */
            if (run->runPlot->pl_typename)
                EVTsetup_plot(run->circuit, run->runPlot->pl_typename);
#endif
        }
    }

    /* define storage for old and new data, to allow interpolation */
    if (interpolated && run->circuit->CKTcurJob->JOBtype == 4) {
        valueold = TMALLOC(double, run->numData);
        for (i = 0; i < run->numData; i++)
            valueold[i] = 0.0;
        valuenew = TMALLOC(double, run->numData);
    }

    /*Start BLT, initilises the blt vectors saj*/
#ifdef TCL_MODULE
    blt_init(run);
#elif defined SHARED_MODULE
    sh_vecinit(run);
#endif

    startclock = clock();
#ifndef HAS_WINGUI
    outp_bar_shown = 0;         /* Enhancement-184: fresh progress state per run */
#endif
    return (OK);
}

/* Initialze memory for the list of all vectors in the current plot.
   Add a standard vector to this plot */
static int
addDataDesc(runDesc *run, char *name, int type, int ind, int meminit)
{
    dataDesc *data;

    /* initialize memory (for all vectors or given by 'save') */
    if (!run->numData) {
        /* even if input 0, do a malloc */
        run->data = TMALLOC(dataDesc, ++meminit);
        run->maxData = meminit;
    }
    /* If there is need for more memory */
    else if (run->numData == run->maxData) {
        run->maxData = (int)(run->maxData * 1.1) + 1;
        run->data = TREALLOC(dataDesc, run->data, run->maxData);
    }

    data = &run->data[run->numData];
    /* so freeRun will get nice NULL pointers for the fields we don't set */
    memset(data, 0, sizeof(dataDesc));

    data->name = copy(name);
    data->type = type;
    data->gtype = GRID_LIN;
    data->regular = TRUE;
    data->outIndex = ind;

    /* It's the reference vector. */
    if (ind == -1)
        run->refIndex = run->numData;

    run->numData++;

    return (OK);
}

/* Initialze memory for the list of all vectors in the current plot.
   Add a special vector (e.g. @q1[ib]) to this plot */
static int
addSpecialDesc(runDesc *run, char *name, char *devname, char *param, int depind, int meminit)
{
    dataDesc *data;
    char *unique, *freeunique;       /* unique char * from back-end */
    int ret;

    if (!run->numData) {
        /* even if input 0, do a malloc */
        run->data = TMALLOC(dataDesc, ++meminit);
        run->maxData = meminit;
    }
    else if (run->numData == run->maxData) {
        run->maxData = (int)(run->maxData * 1.1) + 1;
        run->data = TREALLOC(dataDesc, run->data, run->maxData);
    }

    data = &run->data[run->numData];
    /* so freeRun will get nice NULL pointers for the fields we don't set */
    memset(data, 0, sizeof(dataDesc));

    data->name = copy(name);

    freeunique = unique = copy(devname);

    /* unique will be overridden, if it already exists */
    ret = INPinsertNofree(&unique, ft_curckt->ci_symtab);
    data->specName = unique;

    if (ret == E_EXISTS)
        tfree(freeunique);

    data->specParamName = copy(param);

    data->specIndex = depind;
    data->specType = -1;
    data->specFast = NULL;
    data->regular = FALSE;

    run->numData++;

    return (OK);
}


static void
OUTpD_memory(runDesc *run, IFvalue *refValue, IFvalue *valuePtr)
{
    int i, n = run->numData;

    if (!cp_getvar("no_mem_check", CP_BOOL, NULL, 0)) {
        /* Estimate the required memory */
        size_t memrequ = (size_t)n * vlength2delta(0) * sizeof(double);
        size_t memavail = getAvailableMemorySize();

        if (memrequ > memavail) {
            fprintf(stderr, "\nError: memory required (%zu Bytes)\n"
                "       is more than memory available (%zu Bytes)!\n",
                memrequ, memavail);
            fprintf(stderr, "Setting the output memory is not possible.\n");
            controlled_exit(1);
        }
    }

    for (i = 0; i < n; i++) {

        dataDesc *d;

#ifdef TCL_MODULE
        /*Locks the blt vector to stop access*/
        blt_lockvec(i);
#endif

        d = &run->data[i];

        if (d->outIndex == -1) {
            if (d->type == IF_REAL)
                plotAddRealValue(d, refValue->rValue);
            else if (d->type == IF_COMPLEX)
                plotAddComplexValue(d, refValue->cValue);
        } else if (d->regular) {
            if (ft_ngdebug && d->type == IF_REAL && eq(d->name, "speedcheck")) {
                /* current time */
                clock_t cl = clock();
                double tt = ((double)cl - (double)startclock) / CLOCKS_PER_SEC;
                plotAddRealValue(d, tt);
            }
            else if (ft_ngdebug && d->type == IF_REAL && eq(d->name, "deltacheck")) {
                plotAddRealValue(d, ft_curckt->ci_ckt->CKTdeltaOld[0]);
            }
            else if (d->type == IF_REAL)
                plotAddRealValue(d, valuePtr->v.vec.rVec[d->outIndex]);
            else if (d->type == IF_COMPLEX)
                plotAddComplexValue(d, valuePtr->v.vec.cVec[d->outIndex]);
        } else {
            IFvalue val;

            /* should pre-check instance */
            if (!getSpecial(d, run, &val))
                continue;

            if (d->type == IF_REAL)
                plotAddRealValue(d, val.rValue);
            else if (d->type == IF_COMPLEX)
                plotAddComplexValue(d, val.cValue);
            else if (d->type == IF_INTEGER)
                /* Enhancement-32: integer instance params/opvars (e.g. OSDI event
                   counters) are recorded as reals, like every other plot vector */
                plotAddRealValue(d, (double) val.iValue);
            else
                fprintf(stderr, "OUTpData: unsupported data type\n");
        }

#ifdef TCL_MODULE
        /*relinks and unlocks vector*/
        blt_relink(i, d->vec);
#endif

    }
}


int
OUTpData(runDesc *plotPtr, IFvalue *refValue, IFvalue *valuePtr)
{
    runDesc *run = plotPtr;  // FIXME
    int i;

    run->pointCount++;

#ifdef TCL_MODULE
    steps_completed = run->pointCount;
#endif
    /* interpolated batch mode output to file/plot in transient analysis */
    if (interpolated && run->circuit->CKTcurJob->JOBtype == 4) {
        /* JOBtype == 4 means Transient Analysis.  FIX ME */

        if (run->writeOut) { /* To file */
            InterpFileAdd(run, refValue, valuePtr);
        }
        else { /* To plot */
            InterpPlotAdd(run, refValue, valuePtr);
        }
        return OK;
    } else if (run->writeOut) {
        /* standard batch mode output to file */

        if (run->pointCount == 1) {
            fileInit_pass2(run);
        }

        fileStartPoint(run->fp, run->binary, run->pointCount);

        if (run->refIndex != -1) {
            if (run->isComplex) {
                fileAddComplexValue(run->fp, run->binary, refValue->cValue);

                /*  While we're looking at the reference value, print it to the screen
                    every quarter of a second, to give some feedback without using
                    too much CPU time  */
#ifndef HAS_WINGUI
                if (!orflag && !ft_norefprint && !cp_background) {
                    currclock = clock();
                    if ((currclock-lastclock) > (0.25*CLOCKS_PER_SEC)) {
                        outp_print_reference(run, refValue->cValue.real);
                        lastclock = currclock;
                    }
                }
#endif
            }
            else { /* And the same for a non-complex (real) value  */
                fileAddRealValue(run->fp, run->binary, refValue->rValue);
#ifndef HAS_WINGUI
                if (!orflag && !ft_norefprint && !cp_background) {
                    currclock = clock();
                    if ((currclock-lastclock) > (0.25*CLOCKS_PER_SEC)) {
                        outp_print_reference(run, refValue->rValue);
                        lastclock = currclock;
                    }
                }
#endif
            }
        }

        for (i = 0; i < run->numData; i++) {
            /* we've already printed reference vec first */
            if (run->data[i].outIndex == -1) {
                continue;
            }

#ifdef TCL_MODULE
            blt_add(i, refValue ? refValue->rValue : NAN);
#endif

            if (run->data[i].regular) {
                if (ft_ngdebug && run->data[i].type == IF_REAL && eq(run->data[i].name, "speedcheck")) {
                    /* current time */
                    clock_t cl = clock();
                    double tt = ((double)cl - (double)startclock) / CLOCKS_PER_SEC;
                    fileAddRealValue(run->fp, run->binary, tt);
                }
                else if (ft_ngdebug && run->data[i].type == IF_REAL && eq(run->data[i].name, "deltacheck")) {
                    fileAddRealValue(run->fp, run->binary, ft_curckt->ci_ckt->CKTdeltaOld[0]);
                }
                else if (run->data[i].type == IF_REAL)
                    fileAddRealValue(run->fp, run->binary,
                            valuePtr->v.vec.rVec [run->data[i].outIndex]);
                else if (run->data[i].type == IF_COMPLEX)
                    fileAddComplexValue(run->fp, run->binary,
                            valuePtr->v.vec.cVec [run->data[i].outIndex]);
                else
                    fprintf(stderr, "OUTpData: unsupported data type\n");
            }
            else {
                IFvalue val;
                /* should pre-check instance */
                if (!getSpecial(&run->data[i], run, &val)) {

                    /*  If this is the first data point, print a warning for any unrecognized
                        variables, since this has not already been checked  */

                    if (run->pointCount == 1)
                        fprintf(stderr, "Warning: unrecognized variable - %s\n",
                                run->data[i].name);

                    if (run->isComplex) {
                        val.cValue.real = 0;
                        val.cValue.imag = 0;
                        fileAddComplexValue(run->fp, run->binary, val.cValue);
                    }
                    else {
                        val.rValue = 0;
                        fileAddRealValue(run->fp, run->binary, val.rValue);
                    }

                    continue;
                }

                if (run->data[i].type == IF_REAL)
                    fileAddRealValue(run->fp, run->binary, val.rValue);
                else if (run->data[i].type == IF_COMPLEX)
                    fileAddComplexValue(run->fp, run->binary, val.cValue);
                else if (run->data[i].type == IF_INTEGER)
                    /* Enhancement-32: integer instance params/opvars are written
                       as reals, like every other rawfile vector */
                    fileAddRealValue(run->fp, run->binary, (double) val.iValue);
                else
                    fprintf(stderr, "OUTpData: unsupported data type\n");
            }

#ifdef TCL_MODULE
            blt_add(i, valuePtr->v.vec.rVec [run->data[i].outIndex]);
#endif
        }

        fileEndPoint(run->fp, run->binary);

        /*  Check that the write to disk completed successfully, otherwise abort  */

        if (ferror(run->fp)) {
            fprintf(stderr, "Warning: rawfile write error !!\n");
            shouldstop = TRUE;
        }

    }
    else {
        OUTpD_memory(run, refValue, valuePtr);

        /*  This is interactive mode. Update the screen with the reference
            variable just the same  */

#ifndef HAS_WINGUI
        if (!orflag && !ft_norefprint && !cp_background) {
            currclock = clock();
            if ((currclock-lastclock) > (0.25*CLOCKS_PER_SEC)) {
                outp_print_reference(run, run->isComplex
                                     ? (refValue ? refValue->cValue.real : NAN)
                                     : (refValue ? refValue->rValue : NAN));
                lastclock = currclock;
            }
        }
#endif

        gr_iplot(run->runPlot);
    }

    if (ft_bpcheck(run->runPlot, run->pointCount) == FALSE)
        shouldstop = TRUE;

#ifdef TCL_MODULE
    Tcl_ExecutePerLoop();
#elif defined SHARED_MODULE
    sh_ExecutePerLoop();
#endif

    return OK;
} /* end of function OUTpData */


int
OUTendPlot(runDesc *plotPtr)
{
    if (plotPtr->writeOut) {
        fileEnd(plotPtr);
    } else {
        gr_end_iplot();
        plotEnd(plotPtr);
    }

    tfree(valueold);
    tfree(valuenew);

    freeRun(plotPtr);

    return (OK);
}


int
OUTattributes(runDesc *plotPtr, IFuid varName, int param, IFvalue *value)
{
    runDesc *run = plotPtr;  // FIXME
    GRIDTYPE type;

    struct dvec *d;

    NG_IGNORE(value);

    if (param == OUT_SCALE_LIN)
        type = GRID_LIN;
    else if (param == OUT_SCALE_LOG)
        type = GRID_XLOG;
    else
        return E_UNSUPP;

    if (run->writeOut) {
        if (varName) {
            int i;
            for (i = 0; i < run->numData; i++)
                if (!strcmp(varName, run->data[i].name))
                    run->data[i].gtype = type;
        } else {
            run->data[run->refIndex].gtype = type;
        }
    } else {
        if (varName) {
            for (d = run->runPlot->pl_dvecs; d; d = d->v_next)
                if (!strcmp(varName, d->v_name))
                    d->v_gridtype = type;
        } else if (param == PLOT_COMB) {
            for (d = run->runPlot->pl_dvecs; d; d = d->v_next)
                d->v_plottype = PLOT_COMB;
        } else {
            run->runPlot->pl_scale->v_gridtype = type;
        }
    }

    return (OK);
}


/* The file writing routines.
   Write a raw file in batch mode (-b and -r flags).
   Writing a raw file in interactive or control  mode is handled
   by raw_write() in rawfile.c */
static void
fileInit(runDesc *run)
{
    char buf[513];
    int i;
    size_t n;

    lastclock = clock();

    /* This is a hack. */
    run->isComplex = FALSE;
    for (i = 0; i < run->numData; i++)
        if (run->data[i].type == IF_COMPLEX)
            run->isComplex = TRUE;

    n = 0;
    sprintf(buf, "Title: %s\n", run->name);
    n += strlen(buf);
    fputs(buf, run->fp);
    sprintf(buf, "Date: %s\n", datestring());
    n += strlen(buf);
    fputs(buf, run->fp);
    sprintf(buf, "Command: %s-%s, Build %s\n", ft_sim->simulator, ft_sim->version, Spice_Build_Date);
    n += strlen(buf);
    fputs(buf, run->fp);
    sprintf(buf, "Plotname: %s\n", run->type);
    n += strlen(buf);
    fputs(buf, run->fp);
    sprintf(buf, "Flags: %s\n", run->isComplex ? "complex" : "real");
    n += strlen(buf);
    fputs(buf, run->fp);
    sprintf(buf, "No. Variables: %d\n", run->numData);
    n += strlen(buf);
    fputs(buf, run->fp);
    sprintf(buf, "No. Points: ");
    n += strlen(buf);
    fputs(buf, run->fp);

    fflush(run->fp);        /* Gotta do this for LATTICE. */
    if (run->fp == stdout || (run->pointPos = ftell(run->fp)) <= 0)
        run->pointPos = (long) n;
    fprintf(run->fp, "0       \n"); /* Save 8 spaces here. */

    fprintf(run->fp, "Variables:\n");

    printf("No. of Data Columns : %d  \n", run->numData);
}

/* Trying to guess the type of a vector, using either their special names
   or special parameter names for @ vectors. FIXME This guessing may fail
   due to the many options, especially for the @ vectors. pltypename
   may be run->type in batch mode or the plot name in control mode. */
static int
guess_type(const char *name, char* pltypename)
{
    int type;

    if (substring("#branch", name))
        type = SV_CURRENT;
    else if (cieq(name, "time"))
        type = SV_TIME;
    else if ( cieq(name, "speedcheck"))
        type = SV_TIME;
    else if ( cieq(name, "deltacheck"))
        type = SV_TIME;
    else if (cieq(name, "frequency"))
        type = SV_FREQUENCY;
    else if (ciprefix("inoise", name))
        type = fixme_inoise_type;
    else if (ciprefix("onoise", name))
        type = fixme_onoise_type;
    else if (cieq(name, "temp-sweep"))
        type = SV_TEMP;
    else if (cieq(name, "res-sweep"))
        type = SV_RES;
    else if (cieq(name, "i-sweep"))
        type = SV_CURRENT;
    else if (strstr(name, ":power\0"))
        type = SV_POWER;
    /* Special treatment if plot has been generated by S-parameter simulation */
    else if (pltypename && ciprefix("sp", pltypename) && ciprefix("S_", name))
        type = SV_SPARAM;
    else if (pltypename && ciprefix("sp", pltypename) && ciprefix("Y_", name))
        type = SV_ADMITTANCE;
    else if (pltypename && ciprefix("sp", pltypename) && ciprefix("Z_", name))
        type = SV_IMPEDANCE;
    else if (pltypename && ciprefix("sp", pltypename) && cieq(name, "NF"))
        type = SV_DB;
    else if (pltypename && ciprefix("sp", pltypename) && cieq(name, "NFmin"))
        type = SV_DB;
    else if (pltypename && ciprefix("sp", pltypename) && cieq(name, "Rn"))
        type = SV_IMPEDANCE;
    else if (pltypename && ciprefix("sp", pltypename) && cieq(name, "SOpt"))
        type = SV_NOTYPE;
    else if (pltypename && ciprefix("sp", pltypename) && ciprefix("Cy_", name))
        type = SV_CURRENT;
    /* current source ISRC parameters for current */
    else if (substring("@i", name) && (substring("[c]", name) || substring("[dc]", name) || substring("[current]", name)))
            type = SV_CURRENT;
    else if ((*name == '@') && substring("[g", name)) /* token starting with [g */
        type = SV_ADMITTANCE;
    else if ((*name == '@') && substring("[c", name))
        type = SV_CAPACITANCE;
    else if ((*name == '@') && substring("[i", name))
        type = SV_CURRENT;
    else if ((*name == '@') && substring("[q", name))
        type = SV_CHARGE;
    else if ((*name == '@') && substring("[p]", name)) /* token is exactly [p] */
        type = SV_POWER;
    else
        type = SV_VOLTAGE;

    return type;
}


static void
fileInit_pass2(runDesc *run)
{
    int i, type;

    bool keepbranch = cp_getvar("keep#branch", CP_BOOL, NULL, 0);

    for (i = 0; i < run->numData; i++) {

        char *name = run->data[i].name;

        /* Use run->type to detect SP analysis */
        type = guess_type(name, run->type);

        if (type == SV_CURRENT && !keepbranch) {
            char *branch = strstr(name, "#branch");
            if (branch)
                *branch = '\0';
            fprintf(run->fp, "\t%d\ti(%s)\t%s", i, name, ft_typenames(type));
            if (branch)
                *branch = '#';
        } else if (type == SV_VOLTAGE) {
            fprintf(run->fp, "\t%d\tv(%s)\t%s", i, name, ft_typenames(type));
        } else {
            fprintf(run->fp, "\t%d\t%s\t%s", i, name, ft_typenames(type));
        }

        if (run->data[i].gtype == GRID_XLOG)
            fprintf(run->fp, "\tgrid=3");

        fprintf(run->fp, "\n");
    }

    fprintf(run->fp, "%s:\n", run->binary ? "Binary" : "Values");
    fflush(run->fp);

    /*  Allocate Row buffer  */

    if (run->binary) {
        rowbuflen = (size_t) (run->numData);
        if (run->isComplex)
            rowbuflen *= 2;
        rowbuf = TMALLOC(double, rowbuflen);
    } else {
        rowbuflen = 0;
        rowbuf = NULL;
    }
}


static void
fileStartPoint(FILE *fp, bool bin, int num)
{
    if (!bin)
        fprintf(fp, "%d\t", num - 1);

    /*  reset buffer pointer to zero  */

    column = 0;
}


static void
fileAddRealValue(FILE *fp, bool bin, double value)
{
    if (bin)
        rowbuf[column++] = value;
    else
        fprintf(fp, "\t%.*e\n", DOUBLE_PRECISION, value);
}


static void
fileAddComplexValue(FILE *fp, bool bin, IFcomplex value)
{
    if (bin) {
        rowbuf[column++] = value.real;
        rowbuf[column++] = value.imag;
    } else {
        fprintf(fp, "\t%.*e,%.*e\n", DOUBLE_PRECISION, value.real,
                DOUBLE_PRECISION, value.imag);
    }
}


static void
fileEndPoint(FILE *fp, bool bin)
{
    /*  write row buffer to file  */
    /* otherwise the data has already been written */

    if (bin)
        fwrite(rowbuf, sizeof(double), rowbuflen, fp);
}


/* Here's the hack...  Run back and fill in the number of points. */

static void
fileEnd(runDesc *run)
{
    if (run->fp != stdout) {
        long place = ftell(run->fp);
        fseek(run->fp, run->pointPos, SEEK_SET);
        fprintf(run->fp, "%d", run->pointCount);
        if (!ft_optimizing) {   /* Enhancement-130 */
#ifndef HAS_WINGUI
            outp_finish_reference(run);   /* Enhancement-184: bar reaches 100% */
#endif
            fprintf(stdout, "\nNo. of Data Rows : %d\n", run->pointCount);
        }
        fseek(run->fp, place, SEEK_SET);
    } else {
        /* Yet another hack-around */
        fprintf(stderr, "@@@ %ld %d\n", run->pointPos, run->pointCount);
    }

    fflush(run->fp);

    tfree(rowbuf);
}


/* The plot maintenance routines. */

static void
plotInit(runDesc *run)
{
    struct plot *pl = plot_alloc(run->type);
    struct dvec *v;
    int i;

    pl->pl_title = copy(run->name);
    pl->pl_name = copy(run->type);
    pl->pl_ndims = 0;
    plot_new(pl);
    plot_setcur(pl->pl_typename);
    run->runPlot = pl;

    /* This is a hack. */
    /* if any of them complex, make them all complex */
    run->isComplex = FALSE;
    for (i = 0; i < run->numData; i++)
        if (run->data[i].type == IF_COMPLEX)
            run->isComplex = TRUE;

    for (i = 0; i < run->numData; i++) {
        dataDesc *dd = &run->data[i];
        char *name;

        if (isdigit_c(dd->name[0]))
            name = tprintf("V(%s)", dd->name);
        else
            name = copy(dd->name);

        /* Use pl->pl_typename to detect SP analysis */
        v = dvec_alloc(name,
                       guess_type(name, pl->pl_typename),
                       run->isComplex
                       ? (VF_COMPLEX | VF_PERMANENT)
                       : (VF_REAL | VF_PERMANENT),
                       0, NULL);

        vec_new(v);
        dd->vec = v;
    }
}

/* prepare the vector length data for memory allocation
   If new, and tran or pss, length is TSTOP / TSTEP plus some margin.
   If allocated length is exceeded, check progress. When > 20% then extrapolate memory needed,
   if less than 20% then just double the size.
   If not tran or pss, return fixed value (1024) of memory to be added.
   */
static inline int
vlength2delta(int len)
{
#ifdef SHARED_MODULE
    if (savenone)
        /* We need just a vector length of 1 */
        return 1;
#endif
    /* TSTOP / TSTEP */
    int points = ft_curckt->ci_ckt->CKTtimeListSize;
    /* transient and pss analysis (points > 0) upon start */
    if ((ft_curckt->ci_ckt->CKTmode & MODETRAN) && len == 0 && points > 0) {
        /* number of timesteps plus some overhead */
        return points + 100;
    }
    /* transient and pss if original estimate is exceeded */
    else if ((ft_curckt->ci_ckt->CKTmode & MODETRAN) && points > 0) {
        /* check where we are */
        double timerel = ft_curckt->ci_ckt->CKTtime / ft_curckt->ci_ckt->CKTfinalTime;
        /* return an estimate of the appropriate number of time points, if more than 20% of
           the anticipated total time has passed */
        if (timerel > 0.2) {
            int proposed = (int)(len / timerel) - len + 1;

            if (proposed > 0)
                return proposed;
            return 16; // Probably enough as past end of simulation.
        } else {
            /* If not, just double the available memory */

            return len;
        }
    }
    /* op */
    else if (ft_curckt->ci_ckt->CKTmode & MODEDCOP) {
        /* op with length 1 */
        return 1;
    }
    /* other analysis types that do not set CKTtimeListSize */
    else
        return 1024;
}

void
AddRealValueToVector(struct dvec *v, double value)
{
#ifdef SHARED_MODULE
    if (savenone)
        /* always save new data to same location */
        v->v_length = 0;
#endif

    if (v->v_length >= v->v_alloc_length)
        dvec_extend(v, v->v_length + vlength2delta(v->v_length));

    if (isreal(v)) {
        v->v_realdata[v->v_length] = value;
    } else {
        /* a real parading as a VF_COMPLEX */
        v->v_compdata[v->v_length].cx_real = value;
        v->v_compdata[v->v_length].cx_imag = 0.0;
    }

    v->v_length++;
    v->v_dims[0] = v->v_length; /* va, must be updated */
}

static void
plotAddRealValue(dataDesc *desc, double value)
{
    AddRealValueToVector(desc->vec, value);
}

static void
plotAddComplexValue(dataDesc *desc, IFcomplex value)
{
    struct dvec *v = desc->vec;

#ifdef SHARED_MODULE
    if (savenone)
        v->v_length = 0;
#endif

    if (v->v_length >= v->v_alloc_length)
        dvec_extend(v, v->v_length + vlength2delta(v->v_length));

    v->v_compdata[v->v_length].cx_real = value.real;
    v->v_compdata[v->v_length].cx_imag = value.imag;

    v->v_length++;
    v->v_dims[0] = v->v_length; /* va, must be updated */
}


static void
plotEnd(runDesc *run)
{
    if (!ft_optimizing) {       /* Enhancement-130 */
#ifndef HAS_WINGUI
        outp_finish_reference(run);   /* Enhancement-184: bar reaches 100% */
#endif
        fprintf(stdout, "\nNo. of Data Rows : %d\n", run->pointCount);
    }
}


/* ParseSpecial takes something of the form "@name[param,index]" and rips
 * out name, param, andstrchr.
 */

static bool
parseSpecial(char *name, char *dev, char *param, char *ind)
{
    char *s;

    *dev = *param = *ind = '\0';

    if (*name != '@')
        return FALSE;
    name++;

    /* Enhancement-441: the save side of the `@name[param]` split, and the last
     * of the five places it lives. An array instance is named `r[2]`, so
     * `save @r[2][i]` has two bracket groups; taking everything before the
     * first '[' as the device gave device `r`, parameter `2`, which matched no
     * produced vector -- and because a save list that matches nothing loses the
     * WHOLE plot, `save @r[1][i]` ended the run with "no data saved ... analysis
     * not run" rather than merely dropping that one vector.
     *
     * ft_accessor_param_start() is the shared rule; when it finds no parameter
     * bracket at all the whole token is the device name, as before. */
    {
        char *pstart = ft_accessor_param_start(name);
        s = dev;
        while (*name && name != pstart)
            *s++ = *name++;
        *s = '\0';
    }

    if (!*name)
        return TRUE;
    name++;

    s = param;
    if (*name == '[') {
        /* Enhancement-269's wildcard alias `@*[[param]]` depends on the
           original first-']' split leaving `[param`, so a name that starts
           with '[' keeps exactly the old behaviour. */
        while (*name && (*name != ',') && (*name != ']'))
            *s++ = *name++;
    } else {
        /* A parameter NAME may itself contain brackets: a bus terminal current
           `i_a[1]` (Enhancement-394) or an element of an array parameter
           `ap[0]`. Stopping at the FIRST ']' truncated the name to `i_a[1`, so
           parseSpecial reported failure and the save was dropped SILENTLY --
           `.save @nd1[i_a[1]]` produced no vector and no diagnostic, while
           `.save @nd1[i_c]` beside it worked, and `.options savecurrents` on a
           bus-terminal device therefore captured only its scalar terminals.
           The scalar read of the same name was always correct
           (Enhancement-408), which is what made the gap invisible.

           Track the bracket depth and stop at the ']' that closes the `@dev[`
           bracket; a ',' still separates the optional index at depth 0. */
        int brdepth = 0;
        while (*name) {
            if (brdepth == 0 && (*name == ']' || *name == ','))
                break;
            if (*name == '[')
                brdepth++;
            else if (*name == ']')
                brdepth--;
            *s++ = *name++;
        }
    }
    *s = '\0';

    if (*name == ']')
        return (!name[1] ? TRUE : FALSE);
    else if (!*name)
        return FALSE;
    name++;

    s = ind;
    while (*name && (*name != ']'))
        *s++ = *name++;
    *s = '\0';

    if (*name && !name[1])
        return TRUE;
    else
        return FALSE;
}


/* This routine must match two names with or without a V() around them. */

static bool
name_eq(char *n1, char *n2)
{
    char buf1[BSIZE_SP], buf2[BSIZE_SP], *s;

    if ((s = strchr(n1, '(')) != NULL) {
        strcpy(buf1, s);
        if ((s = strchr(buf1, ')')) == NULL)
            return FALSE;
        *s = '\0';
        n1 = buf1;
    }

    if ((s = strchr(n2, '(')) != NULL) {
        strcpy(buf2, s);
        if ((s = strchr(buf2, ')')) == NULL)
            return FALSE;
        *s = '\0';
        n2 = buf2;
    }

    if (strcmp(n1, n2) == 0)
        return TRUE;

    /* Enhancement-428: accept the obvious spelling of an internal node inside a
     * subcircuit. `.save v(x1.n1#mid)` names the same vector the simulator calls
     * `n.x1.n1#mid`; without this the save silently matched nothing and the run
     * ended with "no data saved for Transient analysis" -- the whole plot lost,
     * not just that one vector. `findvec` accepts the same spelling; this is the
     * second, independent resolution path (the Enhancement-408 lesson). */
    {
        bool eq = FALSE;
        char *alt = cp_hier_devname(n1);
        if (alt) {
            eq = (strcmp(alt, n2) == 0);
            tfree(alt);
        }
        if (!eq && (alt = cp_hier_devname(n2)) != NULL) {
            eq = (strcmp(n1, alt) == 0);
            tfree(alt);
        }
        return eq;
    }
}


static bool
getSpecial(dataDesc *desc, runDesc *run, IFvalue *val)
{
    IFvalue selector;
    struct variable *vv;

    selector.iValue = desc->specIndex;
    if (INPaName(desc->specParamName, val, run->circuit, &desc->specType,
                 desc->specName, &desc->specFast, ft_sim, &desc->type,
                 &selector) == OK) {
        /* Enhancement-32: keep IF_INTEGER too — integer instance params/opvars
           (e.g. OSDI event counters) are recorded as reals downstream */
        desc->type &= (IF_REAL | IF_COMPLEX | IF_INTEGER);   /* mask out other bits */
        return TRUE;
    }

    if ((vv = if_getstat(run->circuit, &desc->name[1])) != NULL) {
        /* skip @ sign */
        desc->type = IF_REAL;
        if (vv->va_type == CP_REAL)
            val->rValue = vv->va_real;
        else if (vv->va_type == CP_NUM)
            val->rValue = vv->va_num;
        else if (vv->va_type == CP_BOOL)
            val->rValue = (vv->va_bool ? 1.0 : 0.0);
        else
            return FALSE; /* not a real */
        tfree(vv);
        return TRUE;
    }

    return FALSE;
}


static void
freeRun(runDesc *run)
{
    int i;

    for (i = 0; i < run->numData; i++) {
        tfree(run->data[i].name);
        tfree(run->data[i].specParamName);
    }

    tfree(run->data);
    tfree(run->type);
    tfree(run->name);

    tfree(run);
}


int
OUTstopnow(void)
{
    if (ft_intrpt || shouldstop) {
        ft_intrpt = shouldstop = FALSE;
        return (1);
    }

    return (0);
}


/* Print out error messages. */

static struct mesg {
    char *string;
    long flag;
} msgs[] = {
    { "Warning", ERR_WARNING } ,
    { "Fatal error", ERR_FATAL } ,
    { "Panic", ERR_PANIC } ,
    { "Note", ERR_INFO } ,
    { NULL, 0 }
};


void
OUTerror(int flags, char *format, IFuid *names)
{
    struct mesg *m;
    char buf[BSIZE_SP], *s, *bptr;
    int nindex = 0;

    if ((flags == ERR_INFO) && cp_getvar("printinfo", CP_BOOL, NULL, 0))
        return;

    for (m = msgs; m->flag; m++)
        if (flags & m->flag)
            fprintf(cp_err, "%s: ", m->string);

    for (s = format, bptr = buf; *s; s++) {
        if (*s == '%' && (s == format || s[-1] != '%') && s[1] == 's') {
            if (names[nindex])
                strcpy(bptr, names[nindex]);
            else
                strcpy(bptr, "(null)");
            bptr += strlen(bptr);
            s++;
            nindex++;
        } else {
            *bptr++ = *s;
        }
    }

    *bptr = '\0';
    fprintf(cp_err, "%s\n", buf);
    fflush(cp_err);
}


void
OUTerrorf(int flags, const char *format, ...)
{
    struct mesg *m;
    va_list args;

    if ((flags == ERR_INFO) && cp_getvar("printinfo", CP_BOOL, NULL, 0))
        return;

    for (m = msgs; m->flag; m++)
        if (flags & m->flag)
            fprintf(cp_err, "%s: ", m->string);

    va_start (args, format);

    vfprintf(cp_err, format, args);
    fputc('\n', cp_err);

    fflush(cp_err);

    va_end(args);
}


static int
InterpFileAdd(runDesc *run, IFvalue *refValue, IFvalue *valuePtr)
{
    int i;
    static double timeold = 0.0, timenew = 0.0, timestep = 0.0;
    bool nodata = FALSE;
    bool interpolatenow = FALSE;

    if (run->pointCount == 1) {
        fileInit_pass2(run);
        timestep = run->circuit->CKTinitTime + run->circuit->CKTstep;
    }

    if (run->refIndex != -1) {
        /*  Save first time step  */
        if (refValue->rValue == run->circuit->CKTinitTime) {
            fileStartPoint(run->fp, run->binary, run->pointCount);
            fileAddRealValue(run->fp, run->binary, run->circuit->CKTinitTime);
            interpolatenow = nodata = FALSE;
        }
        /*  Save last time step  */
        else if (refValue->rValue == run->circuit->CKTfinalTime) {
            fileStartPoint(run->fp, run->binary, run->pointCount);
            fileAddRealValue(run->fp, run->binary, run->circuit->CKTfinalTime);
            interpolatenow = nodata = FALSE;
        }
        /*  Save exact point  */
        else if (refValue->rValue == timestep) {
            fileStartPoint(run->fp, run->binary, run->pointCount);
            fileAddRealValue(run->fp, run->binary, timestep);
            timestep += run->circuit->CKTstep;
            interpolatenow = nodata = FALSE;
        }
        else if (refValue->rValue > timestep) {
            /* add the next time step value to the vector */
            fileStartPoint(run->fp, run->binary, run->pointCount);
            timenew = refValue->rValue;
            fileAddRealValue(run->fp, run->binary, timestep);
            timestep += run->circuit->CKTstep;
            nodata = FALSE;
            interpolatenow = TRUE;
        }
        else {
            /* Do not save this step */
            run->pointCount--;
            nodata = TRUE;
            interpolatenow = FALSE;
        }
#ifndef HAS_WINGUI
        if (!orflag && !ft_norefprint && !cp_background) {
            currclock = clock();
            if ((currclock-lastclock) > (0.25*CLOCKS_PER_SEC)) {
                outp_print_reference(run, refValue->rValue);
                lastclock = currclock;
            }
        }
#endif

    }

    for (i = 0; i < run->numData; i++) {
        /* we've already printed reference vec first */
        if (run->data[i].outIndex == -1)
            continue;

#ifdef TCL_MODULE
        blt_add(i, refValue ? refValue->rValue : NAN);
#endif

        if (run->data[i].regular) {
        /*  Store value or interpolate and store or do not store any value to file */
            if (!interpolatenow && !nodata) {
                /* store the first or last value */
                valueold[i] = valuePtr->v.vec.rVec [run->data[i].outIndex];
                fileAddRealValue(run->fp, run->binary, valueold[i]);
            }
            else if (interpolatenow) {
            /*  Interpolate time if actual time is greater than proposed next time step  */
                double newval;
                valuenew[i] = valuePtr->v.vec.rVec [run->data[i].outIndex];
                newval = (timestep -  run->circuit->CKTstep - timeold)/(timenew - timeold) * (valuenew[i] - valueold[i]) + valueold[i];
                fileAddRealValue(run->fp, run->binary, newval);
                valueold[i] = valuenew[i];
            }
            else if (nodata)
                /* Just keep the transient output value corresponding to timeold, 
                    but do not store to file */
                valueold[i] = valuePtr->v.vec.rVec [run->data[i].outIndex];
        } else {
            IFvalue val;
            /* should pre-check instance */
            if (!getSpecial(&run->data[i], run, &val)) {

                /*  If this is the first data point, print a warning for any unrecognized
                    variables, since this has not already been checked  */
                if (run->pointCount == 1)
                fprintf(stderr, "Warning: unrecognized variable - %s\n",
                        run->data[i].name);
                val.rValue = 0;
                fileAddRealValue(run->fp, run->binary, val.rValue);
                continue;
            }
            if (!interpolatenow && !nodata) {
                /* store the first or last value */
                valueold[i] = val.rValue;
                fileAddRealValue(run->fp, run->binary, valueold[i]);
            }
            else if (interpolatenow) {
            /*  Interpolate time if actual time is greater than proposed next time step  */
                double newval;
                valuenew[i] = val.rValue;
                newval = (timestep -  run->circuit->CKTstep - timeold)/(timenew - timeold) * (valuenew[i] - valueold[i]) + valueold[i];
                fileAddRealValue(run->fp, run->binary, newval);
                valueold[i] = valuenew[i];
            }
            else if (nodata)
                /* Just keep the transient output value corresponding to timeold, 
                    but do not store to file */
                valueold[i] = val.rValue;
        }

#ifdef TCL_MODULE
        blt_add(i, valuePtr->v.vec.rVec [run->data[i].outIndex]);
#endif

    }
    timeold = refValue->rValue;
    fileEndPoint(run->fp, run->binary);

    /*  Check that the write to disk completed successfully, otherwise abort  */
    if (ferror(run->fp)) {
        fprintf(stderr, "Warning: rawfile write error !!\n");
        shouldstop = TRUE;
    }

    if (ft_bpcheck(run->runPlot, run->pointCount) == FALSE)
        shouldstop = TRUE;

#ifdef TCL_MODULE
    Tcl_ExecutePerLoop();
#elif defined SHARED_MODULE
    sh_ExecutePerLoop();
#endif
    return(OK);
}

static int
InterpPlotAdd(runDesc *run, IFvalue *refValue, IFvalue *valuePtr)
{
    int i, iscale = -1;
    static double timeold = 0.0, timenew = 0.0, timestep = 0.0;
    bool nodata = FALSE;
    bool interpolatenow = FALSE;

    if (run->pointCount == 1)
        timestep = run->circuit->CKTinitTime + run->circuit->CKTstep;

    /* find the scale vector */
    for (i = 0; i < run->numData; i++)
        if (run->data[i].outIndex == -1) {
            iscale = i;
            break;
        }
    if (iscale == -1)
        fprintf(stderr, "Error: no scale vector found\n");

#ifdef TCL_MODULE
    /*Locks the blt vector to stop access*/
    blt_lockvec(iscale);
#endif

    /*  Save first time step  */
    if (refValue->rValue == run->circuit->CKTinitTime) {
        plotAddRealValue(&run->data[iscale], refValue->rValue);
        interpolatenow = nodata = FALSE;
    }
    /*  Save last time step  */
    else if (refValue->rValue == run->circuit->CKTfinalTime) {
        plotAddRealValue(&run->data[iscale], run->circuit->CKTfinalTime);
        interpolatenow = nodata = FALSE;
    }
    /*  Save exact point  */
    else if (refValue->rValue == timestep) {
        plotAddRealValue(&run->data[iscale], timestep);
        timestep += run->circuit->CKTstep;
        interpolatenow = nodata = FALSE;
    }
    else if (refValue->rValue > timestep) {
        /* add the next time step value to the vector */
        timenew = refValue->rValue;
        plotAddRealValue(&run->data[iscale], timestep);
        timestep += run->circuit->CKTstep;
        nodata = FALSE;
        interpolatenow = TRUE;
    }
    else {
        /* Do not save this step */
        run->pointCount--;
        nodata = TRUE;
        interpolatenow = FALSE;
    }

#ifdef TCL_MODULE
    /*relinks and unlocks vector*/
    blt_relink(iscale, (run->data[iscale]).vec);
#endif

#ifndef HAS_WINGUI
    if (!orflag && !ft_norefprint && !cp_background) {
        currclock = clock();
        if ((currclock-lastclock) > (0.25*CLOCKS_PER_SEC)) {
            outp_print_reference(run, refValue->rValue);
            lastclock = currclock;
        }
    }
#endif

    for (i = 0; i < run->numData; i++) {
        if (i == iscale)
            continue;

#ifdef TCL_MODULE
        /*Locks the blt vector to stop access*/
        blt_lockvec(i);
#endif

        if (run->data[i].regular) {
        /*  Store value or interpolate and store or do not store any value to file */
            if (!interpolatenow && !nodata) {
                /* store the first or last value */
                valueold[i] = valuePtr->v.vec.rVec [run->data[i].outIndex];
                plotAddRealValue(&run->data[i], valueold[i]);
            }
            else if (interpolatenow) {
            /*  Interpolate time if actual time is greater than proposed next time step  */
                double newval;
                valuenew[i] = valuePtr->v.vec.rVec [run->data[i].outIndex];
                newval = (timestep -  run->circuit->CKTstep - timeold)/(timenew - timeold) * (valuenew[i] - valueold[i]) + valueold[i];
                plotAddRealValue(&run->data[i], newval);
                valueold[i] = valuenew[i];
            }
            else if (nodata)
                /* Just keep the transient output value corresponding to timeold, 
                    but do not store to file */
                valueold[i] = valuePtr->v.vec.rVec [run->data[i].outIndex];
        } else {
            IFvalue val;
            /* should pre-check instance */
            if (!getSpecial(&run->data[i], run, &val))
                continue;
            if (!interpolatenow && !nodata) {
                /* store the first or last value */
                valueold[i] = val.rValue;
                plotAddRealValue(&run->data[i], valueold[i]);
            }
            else if (interpolatenow) {
            /*  Interpolate time if actual time is greater than proposed next time step  */
                double newval;
                valuenew[i] = val.rValue;
                newval = (timestep -  run->circuit->CKTstep - timeold)/(timenew - timeold) * (valuenew[i] - valueold[i]) + valueold[i];
                plotAddRealValue(&run->data[i], newval);
                valueold[i] = valuenew[i];
            }
            else if (nodata)
                /* Just keep the transient output value corresponding to timeold, 
                    but do not store to file */
                valueold[i] = val.rValue;
        }

#ifdef TCL_MODULE
        /*relinks and unlocks vector*/
        blt_relink(i, (run->data[i]).vec);
#endif

    }
    timeold = refValue->rValue;
    gr_iplot(run->runPlot);

    if (ft_bpcheck(run->runPlot, run->pointCount) == FALSE)
        shouldstop = TRUE;

#ifdef TCL_MODULE
    Tcl_ExecutePerLoop();
#elif defined SHARED_MODULE
    sh_ExecutePerLoop();
#endif

    return(OK);
}
