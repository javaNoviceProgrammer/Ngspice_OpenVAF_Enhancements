/*************
 * Header file for spiceif.c
 * 1999 E. Rouat
 ************/

#ifndef ngspice_SPICEIF_H
#define ngspice_SPICEIF_H

CKTcircuit * if_inpdeck(struct card *deck, INPtables **tab);
int if_run(CKTcircuit *t, char *what, wordlist *args, INPtables *tab);
/* Enhancement-632 (hunt F20): the circuit is stale after `osdi -f` -- said, TRUE */
bool if_refuse_stale(const char *what);
int if_option(CKTcircuit *ckt, char *name, enum cp_types type, void *value);
/* Enhancement-756: set option variables across `reset` and `unset` */
int if_is_task_option(const char *name);
void if_option_note_set(const char *name, bool isset);
void if_option_forget_sets(void);
struct variable *if_option_vars_snapshot(void);
void if_option_vars_restore(struct variable *keep);
int if_option_rebuild(CKTcircuit *ckt, const char *except);
void if_dump(CKTcircuit *ckt, FILE *file);
void if_cktfree(CKTcircuit *ckt, INPtables *tab);
int  if_analQbyName(CKTcircuit *ckt, int which, JOB *anal, char *name, IFvalue *parm);

void com_snload(wordlist *wl);
void com_snsave(wordlist *wl);

#endif
