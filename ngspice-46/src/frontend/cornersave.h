/* Enhancement-701: `.option savecorner` -- the corner runs of a circuit whose
 * Verilog-A models declare process corners, one row per corner run, in a
 * file beside the netlist: the corner's name, the value in force of every
 * cornered parameter, and what the run computed. */
#ifndef ngspice_CORNERSAVE_H
#define ngspice_CORNERSAVE_H

#include "ngspice/cpdefs.h"
#include "mcsave.h"         /* MCS_OK / MCS_FAILED / MCS_PAUSED */

struct circ;
struct plot;

/* a run-class command is about to run; it has finished (a row when the run
 * is a corner run: outside a loop command, or inside the `corners` loop) */
extern void CSAVErunBegin(void);
extern void CSAVErun(const char *analysis, int ok);
/* a `resume` has ended: the paused row of its run takes the outcome */
extern void CSAVEresumed(int ok);

/* is the recorder on (the option set)? */
extern int CSAVEactive(void);

/* `corners -mc N` holds the recorder around its montecarlo per corner: the
 * nested loop keeps the outer `corners` label, so the samples would read as
 * corner runs; a depth counter, on/off */
extern void CSAVEhold(int on);
/* `corners -mc N`: the montecarlo per corner made no rows of its own (a
 * sample is not a corner run); this is the corner's row, with the values
 * `names[i]` = `values[i]` (NAN: an empty cell) written after the parameters */
extern void CSAVEsummaryRow(const char *corner, const char *analysis, int ok,
                            const char *const names[], const double values[], int n);

/* a value computed after a run, onto that run's row -- `writemc`, the
 * `corners -output` values. 0 done; -1 no row; -2 the recorder is off; -3 no
 * file could be opened for this circuit; -4 the name is a fixed column
 * (corner, analysis, status) */
extern int CSAVEappend(const char *name, double value);
/* ... onto the row of the run that made plot `pl` (an autocorner pass's
 * corner plots each have a row); -5 when no row is that plot's */
extern int CSAVEappendPlot(struct plot *pl, const char *name, double value);
/* may a value read off the current plot go onto the last row? */
extern int CSAVEplotIsRow(char **why);

/* the circuit is being freed / the program ends: the file is completed */
extern void CSAVEcircuitFreed(struct circ *ci);
extern void CSAVEfinish(void);

#endif
