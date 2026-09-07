/* Enhancement-577: `track` -- every place a condition holds, as a plot */
#ifndef ngspice_COM_TRACK_H
#define ngspice_COM_TRACK_H

#include "ngspice/wordlist.h"

void com_track(wordlist *wl);

/* Enhancement-582: set by `montecarlo -track`, which runs `track` once per sample
 * and records the plots itself -- the per-call summary and batch rows would be
 * N copies of noise. `$track_plot`/`$track_hits` are still set. */
extern int track_quiet;
/* 1 after a `track` that failed for a reason other than "no hit" (bad
 * arguments, an expression that does not evaluate): montecarlo -track stops
 * on it instead of repeating the message once per sample */
extern int track_error;

#endif
