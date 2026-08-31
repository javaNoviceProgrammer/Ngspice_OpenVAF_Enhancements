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
#include "ngspice/cktdefs.h"   /* Enhancement-467: CKTtemp for the dtemp guard */
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



/* Enhancement-426: the instance multiplier was never checked. A NEGATIVE m does
 * not merely scale a device, it INVERTS it -- `R1 a 0 2k m=-1` stamps -2000 ohm
 * and a passive device becomes active, silently -- and on an OSDI device it
 * additionally poisons noise with a NaN, because the compiled model takes
 * sqrt($mfactor) (onoise_spectrum 3.324262e-09 -> nan). A non-finite m gives
 * @r1[m] = inf and a five-message convergence cascade that never names `m`.
 *
 * Identified by parameter ID, not by keyword. For an OSDI device `m` and
 * `_mfactor` are two spellings of one slot, so a keyword test on "m" would miss
 * `_mfactor=-1`; and a Verilog-A model that declares its OWN `m` gets a
 * different id, whose range OpenVAF's `from` clause already enforces.
 *
 * WARNING, and the value is left exactly as written. ngspice deliberately
 * supports negative resistors (resparam.c has an explicit branch for one), so
 * "this makes a passive device active" is not by itself grounds for refusing a
 * value here; and E-361/362 recorded that clamping a bad number can be worse
 * than the number. m == 0 is NOT diagnosed: it is the ordinary "disable this
 * instance" idiom and behaves cleanly. */
static int
e426_multiplier_id(IFdevice *device)
{
    int i;

    if (!device || !device->instanceParms)
        return -1;
    for (i = 0; i < *(device->numInstanceParms); i++) {
        const char *kw = device->instanceParms[i].keyword;
        if (!kw)
            continue;
        if (device->registry_entry ? cieq(kw, "_mfactor") : cieq(kw, "m"))
            return device->instanceParms[i].id;
    }
    return -1;
}

static void
e426_check_multiplier(IFdevice *device, GENinstance *fast, IFparm *p,
                      IFvalue *val, int mult_id)
{
    double v;

    if (!p || !val || mult_id < 0 || p->id != mult_id)
        return;
    v = ((p->dataType & IF_VARTYPES) == IF_INTEGER) ? (double) val->iValue
                                                    : val->rValue;
    if (!isfinite(v))
        fprintf(stderr,
                "Warning: %s: multiplier %s=%g is not a finite number; the "
                "operating point cannot converge.\n",
                fast && fast->GENname ? fast->GENname : device->name,
                p->keyword, v);
    else if (v < 0.0)
        fprintf(stderr,
                "Warning: %s: multiplier %s=%g is negative; the device's "
                "contribution is sign-inverted (a passive device becomes "
                "active) and any noise contribution becomes NaN.\n",
                fast && fast->GENname ? fast->GENname : device->name,
                p->keyword, v);
    /* Enhancement-447 considered warning on m=0 as well, since zero deletes the
       instance outright while a NEGATIVE multiplier was already reported. It is
       deliberately left silent: Enhancement-426 established m=0 as the
       "disable this instance" idiom and its suite asserts the silence, so a
       warning here would fire on decks that mean exactly what they wrote. */
}

/* Enhancement-467: instance-level value guards, the siblings of the option-level
 * ones in spicelib/analysis/cktsopt.c.
 *
 * `.option temp=-300` has warned since Enhancement-426 that it is at or below
 * absolute zero, and osdi/osdisetup.c makes the same check for an OSDI
 * instance. The per-instance knob on a BUILT-IN device had no guard at all:
 * `R1 in out 1k tc1=0.01 temp=-300` was accepted silently and answered
 * v(out) = -0.998 from a +1 V source -- a negative absolute temperature drives
 * the temperature factor negative, so the resistance goes negative and a
 * network of three positive-valued parts delivers a negative voltage.
 * `temp=-1e6` did the same, and `dtemp=-400` reached it by the other road.
 *
 * WARN and ignore the value, keeping what the device already had -- the same
 * contract E426_BAD_OPT uses at option level, so the two levels answer alike.
 *
 * Deliberately NOT extended to a negative `w`/`l`: Enhancement-438's
 * `.option warn_physics` already reports those and keeps the value, which is
 * its established contract, and ignoring the value here silenced it. */
static int
e467_bad_instance_value(CKTcircuit *ckt, IFdevice *device, GENinstance *fast,
                        IFparm *p, IFvalue *val)
{
    const char *who;
    double v;

    if (!p || !p->keyword || !val)
        return 0;
    if ((p->dataType & IF_VARTYPES) != IF_REAL)
        return 0;

    v = val->rValue;
    who = (fast && fast->GENname) ? fast->GENname
                                  : (device ? device->name : "device");

    if (cieq(p->keyword, "temp")) {
        if (v + CONSTCtoK <= 0.0) {
            fprintf(stderr,
                    "\nWarning: %s: temp = %g C is at or below absolute zero "
                    "(-273.15 C); ignored, the circuit temperature is used "
                    "instead.\n\n", who, v);
            return 1;
        }
        return 0;
    }

    if (cieq(p->keyword, "dtemp")) {
        /* dtemp is a DELTA, so it is unphysical only together with an ambient.
         * `ckt->CKTtemp` is the ambient in force as this card is parsed; a
         * `.option temp` card ahead of the devices (the ordinary layout) has
         * already been applied. */
        double amb = ckt ? ckt->CKTtemp - CONSTCtoK : 27.0;
        if (amb + v + CONSTCtoK <= 0.0) {
            fprintf(stderr,
                    "\nWarning: %s: dtemp = %g C puts the device at %g C, at "
                    "or below absolute zero (-273.15 C); ignored.\n\n",
                    who, v, amb + v);
            return 1;
        }
        return 0;
    }

    return 0;
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
    /* Enhancement-468: every device, not only OSDI -- a built-in instance line
     * that set one parameter twice took the last value in silence
     * (`D1 in 0 dm area=1 area=4` quadrupled the current with no diagnostic),
     * while the same repeat on an OSDI line has been reported since E-395. */
    const int track_repeats = 1;
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
        if (INPlastRoundWarn()) {
            /* same warning inpgmod.c gives on a .model card */
            fprintf(stderr,
                    "Warning: %s: parameter (%s) is an integer; the given "
                    "non-integral value was rounded to the nearest integer.\n",
                    fast && fast->GENname ? fast->GENname : device->name,
                    p->keyword);
        }

        e426_check_multiplier(device, fast, p, val, e426_multiplier_id(device));
        error = e467_bad_instance_value(ckt, device, fast, p, val)
                    ? 0
                    : ft_sim->setInstanceParm (ckt, fast, p->id, val, NULL);
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
                else {
                    /* Enhancement-517 / LRM 3.4.7: an override through the
                     * original name AND an alias (or two aliases) "shall be
                     * an error", however the override is written. */
                    errbuf = tprintf("  '%s' and '%s' are the same parameter "
                                     "(aliasparam) and both are set on this "
                                     "line; LRM 3.4.7 makes that an error -- "
                                     "remove one.\n",
                                     seen_as[p->id], p->keyword);
                    rtn = errbuf;
                    goto quit;
                }
            } else {
                seen_as[p->id] = p->keyword;
            }
        }

        val = INPgetValue(ckt, line, p->dataType, tab);
        if (!val) {
            rtn = INPerror(E_PARMVAL);
            goto quit;
        }
        if (INPlastRoundWarn()) {
            /* same warning inpgmod.c gives on a .model card */
            fprintf(stderr,
                    "Warning: %s: parameter (%s) is an integer; the given "
                    "non-integral value was rounded to the nearest integer.\n",
                    fast && fast->GENname ? fast->GENname : device->name,
                    p->keyword);
        }
        e426_check_multiplier(device, fast, p, val, e426_multiplier_id(device));
        error = e467_bad_instance_value(ckt, device, fast, p, val)
                    ? 0
                    : ft_sim->setInstanceParm (ckt, fast, p->id, val, NULL);
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
