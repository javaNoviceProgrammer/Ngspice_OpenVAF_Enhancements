/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/inpdefs.h"
#include "ngspice/hash.h"
#include <string.h>

extern INPmodel *modtab;
extern NGHASHPTR modtabhash;


/*-----------------------------------------------------------------
 * This fcn accepts a pointer to the model name, and returns
 * the INPmodel * if it exist in the model table.
 *----------------------------------------------------------------*/

INPmodel *
INPlookMod(const char *name)
{
    INPmodel *i;

    /* Enhancement-824 (hunt 2026-10-08 F8): the hash INPmakeMod fills beside
     * the list, swapped with it per circuit. A `.model` inside a `.subckt` is
     * copied once per instance (`x1:gm`, `x2:gm`, ...), and INPpas2 looks each
     * instance's model up here: a linear strcmp walk of the whole list made
     * that N x N -- 32 000 wrappers spent 19 s in this loop. */
    if (modtabhash)
        return (INPmodel *) nghash_find(modtabhash, (void *) name);

    for (i = modtab; i; i = i->INPnextModel)
        if (strcmp(i->INPmodName, name) == 0)
            return i;

    return NULL;
}
