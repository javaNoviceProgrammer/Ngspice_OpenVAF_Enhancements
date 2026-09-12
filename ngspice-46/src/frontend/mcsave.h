/* Enhancement-610: `.option savemc` -- the value of every parameter with
 * statistics, one row per analysis run, saved beside the netlist. */
#ifndef ngspice_MCSAVE_H
#define ngspice_MCSAVE_H

#include "ngspice/cpdefs.h"

struct circ;        /* a `struct circ *` in a prototype below, whatever is included first */

/* a draw of a parameter with statistics: a `.param` whose expression calls a
 * random function (agauss, gauss, unif, aunif, limit, mvnorm), scoped
 * `x1.name` inside a subcircuit instance; a device line's own brace draw,
 * `<instance>:{<expression>}`. Recorded whenever it is evaluated, whatever the
 * option says, so that the row a run emits carries the value in force. */
extern void MCSAVEparam(const char *name, double value);

/* was this name recorded as a draw (a .param or subcircuit value with statistics)? */
extern int MCSAVEis_stochastic(const char *name);

/* a deck expansion begins: the numparam draws are about to be re-evaluated */
extern void MCSAVEnewDeck(void);
/* montecarlo's fast path re-derives the device values, without an expansion */
extern void MCSAVEredraw(void);

/* does this expression text call a random function? (a call, not a bare word) */
extern int MCSAVEexpr_is_random(const char *e);

/* a run-class command has finished: emit the row */
extern void MCSAVErun(const char *analysis, int ok);

/* Enhancement-611: is the recorder on (the option set)? */
extern int MCSAVEactive(void);

/* Enhancement-611: a value computed after the run, onto the run's row --
 * `writemc` and montecarlo's -writemc. 0 done; -1 no run to attach to;
 * -2 the recorder is off; -3 (Enhancement-613) no file could be opened for
 * this circuit. */
extern int MCSAVEappend(const char *name, double value);

/* the `writemc` command: writemc [name=]<expr> ... */
extern void com_writemc(wordlist *wl);

/* the circuit is being freed / the program ends: the file is completed */
extern void MCSAVEcircuitFreed(struct circ *ci);
extern void MCSAVEfinish(void);

#endif
