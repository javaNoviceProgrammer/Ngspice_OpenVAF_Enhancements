/* Enhancement-610: `.option savemc` -- the value of every parameter with
 * statistics, one row per analysis run, saved beside the netlist. */
#ifndef ngspice_MCSAVE_H
#define ngspice_MCSAVE_H

#include <stdio.h>
#include "ngspice/cpdefs.h"

struct circ;        /* a `struct circ *` in a prototype below, whatever is included first */

/* a draw of a parameter with statistics: a `.param` whose expression calls a
 * random function (agauss, gauss, unif, aunif, limit, mvnorm), scoped
 * `x1.name` inside a subcircuit instance; a device line's own brace draw,
 * `<instance>:{<expression>}`. Recorded whenever it is evaluated, whatever the
 * option says, so that the row a run emits carries the value in force.
 * Enhancement-617: `model` is 1 for a `.model` card's slot, 0 for a device's,
 * a subcircuit call's or a .param -- the xlsx header sets a model parameter's
 * name in bold. */
extern void MCSAVEparam(const char *name, double value, int model);

/* was this name recorded as a draw (a .param or subcircuit value with statistics)? */
extern int MCSAVEis_stochastic(const char *name);

/* a deck expansion begins: the numparam draws are about to be re-evaluated */
extern void MCSAVEnewDeck(void);
/* montecarlo's fast path re-derives the device values, without an expansion */
extern void MCSAVEredraw(void);

/* does this expression text call a random function? (a call, not a bare word) */
extern int MCSAVEexpr_is_random(const char *e);

/* Enhancement-624 (hunt F8): a run-class command is about to run (which plot
 * is current now tells whether the run made one of its own) */
extern void MCSAVErunBegin(void);
/* a run-class command has finished: emit the row. `ok` is MCS_OK, MCS_FAILED
 * or (Enhancement-625, hunt F9) MCS_PAUSED -- the run stopped at a breakpoint:
 * its draws are in force and its plot exists, so it is a row, marked paused */
enum { MCS_FAILED = 0, MCS_OK = 1, MCS_PAUSED = 2 };
extern void MCSAVErun(const char *analysis, int ok);
/* Enhancement-625 (hunt F9): a `resume` has ended -- completed (MCS_OK), or
 * failed (MCS_FAILED); a resume that pauses again does not call this. The
 * paused row of the run it continued (the one whose plot is current) takes
 * that status; nothing is done when no paused row is that run's. */
extern void MCSAVEresumed(int ok);

/* Enhancement-624 (hunt F8): may a value read off the current plot go onto
 * the last row? 1 yes; 0 no, with the reason in *why (freed by the caller):
 * the row's run failed before it made a plot, or the current plot was made
 * after the row by a run that has none. */
extern int MCSAVEplotIsRow(char **why);

/* Enhancement-611: is the recorder on (the option set)? */
extern int MCSAVEactive(void);

/* Enhancement-611: a value computed after the run, onto the run's row --
 * `writemc` and montecarlo's -writemc. 0 done; -1 no run to attach to;
 * -2 the recorder is off; -3 (Enhancement-613) no file could be opened for
 * this circuit; -4 (Enhancement-634) the name is one of the fixed columns
 * (trial, analysis, status). */
extern int MCSAVEappend(const char *name, double value);

/* the `writemc` command: writemc [name=]<expr> ... */
extern void com_writemc(wordlist *wl);
struct plot;
extern int MCSAVEappendPlot(struct plot *pl, const char *name, double value); /* E-666 */

/* ------------------------------------------------------------ Enhancement-701:
 * what the `.option savecorner` recorder (cornersave.c) shares with this one:
 * the option value's format parsing, the file naming beside the netlist, the
 * directory making and open probe, the session's used-name registry, the
 * csv/txt cell writers and the workbook writer with its font options. */
enum { MCS_FMT_CSV = 0, MCS_FMT_TXT = 1, MCS_FMT_XLSX = 2 };
/* `val` is the option's value (empty for a bare `.option <name>`): a format
 * word (csv, txt, excel) or a file name whose extension picks the format;
 * returns the MCS_FMT_* and, in *given, a private copy of the file name or
 * NULL for the dated default. An unusable value is said (naming `optname`)
 * and csv is used. */
extern int MCSAVEparseFormat(const char *optname, const char *val, char **given);
/* the file's path: `given` as is when absolute, else beside the netlist; NULL
 * for `<stem>_<date>_<time>.<ext>` there, unique within a second */
extern char *MCSAVEmakePath(const char *given, const char *stem, int fmt);
extern int MCSAVEmkdirs(const char *file, char **why);
extern int MCSAVEcanOpen(const char *file, int fmt, char **why);
extern const char *MCSAVEusedBy(const char *path);
extern void MCSAVEnoteUsed(const char *path, const char *title);
extern char *MCSAVEunusedVariant(const char *path);
extern void MCSAVEputName(FILE *f, const char *name, int csv);
extern void MCSAVEputValue(FILE *f, double v);
/* a workbook cell: a string when `s` is set, else the number (NAN: empty) */
struct mcs_xcell { const char *s; double v; };
/* one sheet named `sheet`: a header row whose column styles are 0 (plain),
 * 1 (a model parameter), 2 (an instance parameter) or 3 (a value written
 * after the run), then `nrows` rows of `ncols` cells; the fonts from the
 * `<prefix>_font`, `<prefix>_fontsize`, `<prefix>_model`, `<prefix>_instance`
 * and `<prefix>_writemc` (`savemc`) / `<prefix>_output` options, a recorder
 * other than savemc falling back to savemc's. 0, or -1 with errno set when
 * the file cannot be opened. */
extern int MCSAVExlsxWrite(const char *file, const char *sheet, const char *prefix,
                           int ncols, const char *const *hdr, const int *hdr_style,
                           int nrows, const struct mcs_xcell *const *rows);

/* the circuit is being freed / the program ends: the file is completed */
extern void MCSAVEcircuitFreed(struct circ *ci);
extern void MCSAVEfinish(void);

#endif
