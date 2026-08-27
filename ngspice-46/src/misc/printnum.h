/*************
 * Header file for printnum.c
 * 1999 E. Rouat
 ************/

#ifndef ngspice_PRINTNUM_H
#define ngspice_PRINTNUM_H

#include "ngspice/dstring.h"

/* Enhancement-491: `size` is the capacity of `buf`; the precision is clamped
   to what fits rather than overrunning it. */
void printnum(char *buf, size_t size, double num);
int printnum_fit(int n, size_t size);
int printnum_ds(DSTRING *p_dstring, double num);

#endif
