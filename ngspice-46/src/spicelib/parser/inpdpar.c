/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

/*
 * INPdevParse()
 *
 *  parse a given input according to the standard rules - look
 *  for the parameters given in the parmlists, In addition,
 *  an optional leading numeric parameter is handled.
 */

#include "ngspice/ngspice.h"
#include <stdio.h>
#include "ngspice/ifsim.h"
#include "ngspice/inpdefs.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/cpdefs.h"
#include "ngspice/fteext.h"
#include "inpxx.h"

static IFparm *
find_instance_parameter(char *name, IFdevice *device)
{
    IFparm *p = device->instanceParms;
    IFparm *p_end = p + *(device->numInstanceParms);

    for (; p < p_end; p++)
        if (strcmp(name, p->keyword) == 0)
            return p;
    return NULL;
}


char *
INPdevParse(char **line, CKTcircuit *ckt, int dev, GENinstance *fast,
            double *leading, int *waslead, INPtables *tab)
/* the line to parse */
/* the circuit this device is a member of */
/* the device type code to the device being parsed */
/* direct pointer to device being parsed */
/* the optional leading numeric parameter */
/* flag - 1 if leading double given, 0 otherwise */
{
    IFdevice *device = ft_sim->devices[dev];

    /* Enhancement-395: an OSDI parameter and each of its `aliasparam` names are
     * registered as separate IFparm entries that all carry the SAME .id, so
     * `n1 ... w=1u width=2u` writes one slot twice and the last spelling on the
     * line silently wins. Setting a parameter twice under one name does the
     * same. Both are modelling errors that produced no diagnostic at all.
     *
     * Track the ids written by THIS instance line and report a repeat, naming
     * both spellings. Scoped to OSDI devices because `aliasparam` is a
     * Verilog-A construct -- no built-in device's parsing changes.
     *
     * Instance-line only: model-card defaults are applied in the loop below
     * and an instance line overriding one of them is legitimate, not a repeat.
     * `alter` does not come through here, so re-setting a parameter after the
     * deck is parsed stays silent, as it should. */
    const int track_repeats = (device->registry_entry != NULL);
    const int n_track = track_repeats ? *(device->numInstanceParms) : 0;
    char **seen_as = n_track ? TMALLOC(char *, n_track) : NULL;
    if (seen_as)
        memset(seen_as, 0, (size_t)n_track * sizeof(char *));

    int error;                  /* int to store evaluate error return codes in */
    char *parm = NULL;
    char *errbuf;
    IFvalue *val;
    char *rtn = NULL;

    /* check for leading value */
    *waslead = 0;
    *leading = INPevaluate(line, &error, 1);

    if (error == 0)             /* found a good leading number */
        *waslead = 1;
    else
        *leading = 0.0;

    wordlist *x = fast->GENmodPtr->defaults;
    for (; x; x = x->wl_next->wl_next) {
        char *parameter = x->wl_word;
        char *value = x->wl_next->wl_word;

        IFparm *p = find_instance_parameter(parameter, device);

        if (!p) {
            if (cieq(parameter, "$")) {
                errbuf = copy("  unknown parameter ($). Check the compatibility flag!\n");
            }
            else {
                errbuf = tprintf("  unknown instance parameter (%s) \n", parameter);
            }
            rtn = errbuf;
            goto quit;
        }

        val = INPgetValue(ckt, &value, p->dataType, tab);
        if (!val) {
            rtn = INPerror(E_PARMVAL);
            goto quit;
        }

        error = ft_sim->setInstanceParm (ckt, fast, p->id, val, NULL);
        if (error) {
            rtn = INPerror(error);
            if (rtn && error == E_BADPARM) {
                /* add the parameter name to error message */
                char* extended_rtn = tprintf("%s: %s", p->keyword, rtn);
                tfree(rtn);
                rtn = extended_rtn;
            }
            goto quit;
        }

        /* delete the union val */
        switch (p->dataType & IF_VARTYPES) {
        case IF_REALVEC:
            tfree(val->v.vec.rVec);
            break;
        case IF_INTVEC:
            tfree(val->v.vec.iVec);
            break;
        default:
            break;
        }
    }

    while (**line != '\0') {
        error = INPgetTok(line, &parm, 1);
        if (!*parm) {
            FREE(parm);
            continue;
        }
        if (error) {
            rtn  = INPerror(error);
            goto quit;
        }

        IFparm *p = find_instance_parameter(parm, device);

        if (!p) {
            if (eq(parm, "$")) {
                errbuf = copy("  unknown parameter ($). Check the compatibility flag!\n");
            }
            else {
                errbuf = tprintf("  unknown parameter (%s) \n", parm);
            }
            rtn = errbuf;
            goto quit;
        }

        /* Enhancement-395: same parameter slot written twice on one line. */
        if (seen_as && p->id >= 0 && p->id < n_track) {
            if (seen_as[p->id]) {
                if (strcmp(seen_as[p->id], p->keyword) == 0)
                    fprintf(stderr,
                            "Warning: %s: parameter '%s' is set more than once "
                            "on this line; the last value is used.\n",
                            device->name, p->keyword);
                else
                    fprintf(stderr,
                            "Warning: %s: '%s' and '%s' are the same parameter "
                            "(aliasparam); both are set on this line and the "
                            "last value is used.\n",
                            device->name, seen_as[p->id], p->keyword);
            } else {
                seen_as[p->id] = p->keyword;
            }
        }

        val = INPgetValue(ckt, line, p->dataType, tab);
        if (!val) {
            rtn = INPerror(E_PARMVAL);
            goto quit;
        }
        error = ft_sim->setInstanceParm (ckt, fast, p->id, val, NULL);
        if (error) {
            rtn = INPerror(error);
            goto quit;
        }

        /* delete the union val */
        switch (p->dataType & IF_VARTYPES) {
        case IF_REALVEC:
            tfree(val->v.vec.rVec);
            break;
        case IF_INTVEC:
            tfree(val->v.vec.iVec);
            break;
        default:
            break;
        }

        FREE(parm);
    }

 quit:
    FREE(seen_as);
    FREE(parm);
    return rtn;
}
