/* Enhancement-157: device aging (reliability degradation flow) command. */
#ifndef ngspice_COM_AGING_H
#define ngspice_COM_AGING_H

void com_aging(wordlist *wl);
void aging_replay(void);          /* Enhancement-501 */
void aging_forget_writes(void);   /* Enhancement-501 */
extern int aging_internal_reset;  /* Enhancement-501 */

/* Enhancement-544: the user's `alter`/`altermod` writes are journaled and put
 * back after the loop commands' INTERNAL resets, exactly as the aging doses
 * are (Enhancement-501); a user-typed `reset` forgets them. */
struct dvec;
void alter_journal_dispatch(const char *cmdname, int begin); /* control.c: around a user command */
void alter_journal_arm(int on);           /* a machine writer whose writes are the user's circuit now */
void alter_journal_begin(void);           /* device.c: bracket one alter/altermod command */
void alter_journal_stage_real(const struct dvec *dv);
void alter_journal_stage_string(const char *s);
void alter_journal_end(int do_model, const char *orig_args);
void alter_journal_replay(void);          /* after an internal reset */
void alter_journal_forget(void);          /* a user reset, or a different deck */
int  alter_journal_count(void);

#endif
