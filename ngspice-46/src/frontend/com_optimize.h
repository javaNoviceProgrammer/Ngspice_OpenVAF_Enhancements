#ifndef ngspice_COM_OPTIMIZE_H
#define ngspice_COM_OPTIMIZE_H

void com_optimize(wordlist *wl);

/* Enhancement-788: `help optimize`'s full description, NULL-terminated */
extern const char *const com_optimize_help[];

#endif
