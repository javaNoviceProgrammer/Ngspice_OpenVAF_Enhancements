#ifndef ngspice_COM_CHECKPOINT_H
#define ngspice_COM_CHECKPOINT_H

/* Enhancement-131: transient checkpoint / restart commands. */
void com_savestate(wordlist *wl);
void com_loadstate(wordlist *wl);

/* Enhancement-192: core checkpoint writer, shared by `savestate` and the
   auto-checkpoint-on-interrupt hook (`set autosave=<file>`). Returns TRUE on
   success. `ckt` must be the active circuit (ft_curckt->ci_ckt). */
struct CKTcircuit;
bool ckt_write_checkpoint(struct CKTcircuit *ckt, const char *fname);

#endif
