/* Enhancement-157: device aging (reliability degradation flow) command. */
#ifndef ngspice_COM_AGING_H
#define ngspice_COM_AGING_H

void com_aging(wordlist *wl);
void aging_replay(void);          /* Enhancement-501 */
void aging_forget_writes(void);   /* Enhancement-501 */
extern int aging_internal_reset;  /* Enhancement-501 */

#endif
