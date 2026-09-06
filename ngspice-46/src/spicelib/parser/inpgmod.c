/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Copyright 2000 The ngspice team
3-Clause BSD license
(see COPYING or https://opensource.org/licenses/BSD-3-Clause)
Author: 1985 Thomas L. Quarles, 1991 David A. Gates
Modified: 2001 Paolo Nenzi (Cider Integration)
**********/

#include "ngspice/ngspice.h"
#ifdef OSDI
#include "ngspice/osdiitf.h"
#endif
#include "ngspice/inpdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/cpstd.h"
#include "ngspice/fteext.h"
#include "ngspice/compatmode.h"
#include "ngspice/devdefs.h"
#ifdef OSDI
#include "ngspice/osdiitf.h"   /* Enhancement-495: osdi_devtype_is_osdi */
#endif
#include "inpxx.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>

#ifdef CIDER

#include "ngspice/numcards.h"
#include "ngspice/carddefs.h"
#include "ngspice/numgen.h"
#include "ngspice/suffix.h"

#define E_MISSING    -1
#define E_AMBIGUOUS  -2

extern IFcardInfo *INPcardTab[];
extern int INPnumCards;

static int INPparseNumMod(CKTcircuit *ckt, INPmodel *model, INPtables *tab, char **errMessage);
static int INPfindCard(char *name, IFcardInfo *table[], int numCards);
static int INPfindParm(char *name, IFparm *table, int numParms);

#endif

extern INPmodel *modtab;
extern NGHASHPTR modtabhash;


static IFparm *
find_model_parameter(const char *name, IFdevice *device)
{
    /* devices without .model-card support (VCVS, CCCS, ...) have a NULL
     * parameter table; a .model card naming such a type used to crash here */
    if (!device->modelParms || !device->numModelParms)
        return NULL;

    IFparm *p = device->modelParms;
    IFparm *p_end = p + *(device->numModelParms);

    for (; p < p_end; p++)
        if (strcmp(name, p->keyword) == 0)
            return p;

    return NULL;
}


static IFparm *
find_instance_parameter(const char *name, IFdevice *device)
{
    IFparm *p = device->instanceParms;
    IFparm *p_end = p + *(device->numInstanceParms);

    for (; p < p_end; p++)
        if (strcmp(name, p->keyword) == 0)
            return p;

    return NULL;
}


/*
 * code moved from INPgetMod
 */
/* Enhancement-395: one message for both spellings of a doubly-set parameter.
 *
 * Deliberately does NOT name which value wins. A .model card carries two kinds
 * of parameter and they disagree: a model parameter is written straight through
 * so the LAST one on the card wins, while an instance-parameter default is
 * pushed onto `INPmodfast->defaults` with wl_cons and therefore replayed in
 * reverse, so the FIRST one on the card wins. Stating a rule here would be
 * wrong half the time; the actionable advice is to remove one of them. The
 * instance line has no such split and its message does say which wins.
 *
 * Enhancement-517: the ALIAS spelling is an ERROR, not a warning -- LRM 3.4.7:
 * "it shall be an error to specify an override for a parameter by its original
 * name and one or more aliases, or by more than one alias, regardless of how
 * the override is done". Returns nonzero for that case so the caller can
 * refuse the model card; the SAME name written twice stays a warning (a
 * netlist-level habit outside 3.4.7's rule). */
static int inp_warn_dup_param(const char *dev, const char *first,
                              const char *second)
{
    if (strcmp(first, second) == 0) {
        fprintf(stderr,
                "Warning: %s: parameter '%s' is set more than once on this "
                "model card; only one value takes effect -- remove one.\n",
                dev, first);
        return 0;
    }
    fprintf(stderr,
            "Error: %s: '%s' and '%s' are the same parameter (aliasparam) "
            "and both are set on this model card; LRM 3.4.7 makes that an "
            "error -- remove one.\n", dev, first, second);
    return 1;
}

static int
create_model(CKTcircuit *ckt, INPmodel *modtmp, INPtables *tab)
{
    char    *err = NULL, *line, *parm, *endptr;
    int     error;

#ifdef OSDI
    /* F1 (2026-09-04 hunt): this card is being materialised as a BUILT-IN
     * while a Verilog-A module of the same name is loaded and shadowed. The
     * author compiled and loaded that module; without this line the built-in
     * runs in its place in silence (it may even accept the card's parameters,
     * as the junction diode does for `is`). An `n` line would have re-bound
     * the card first (INP2N), so reaching here means a built-in device letter
     * is using it. */
    if (modtmp->INPmodTypeName && ft_sim->devices[modtmp->INPmodType] &&
        !ft_sim->devices[modtmp->INPmodType]->registry_entry) {
        const char *lib = NULL, *builtin = NULL;
        if (osdi_shadowed_module(modtmp->INPmodTypeName, &lib, &builtin) >= 0) {
            fprintf(stderr,
                    "Warning: .model %s: created as ngspice's built-in %s. The "
                    "Verilog-A module \"%s\" loaded from \"%s\" has the same "
                    "name and is reached only from an `n`-line instance; this "
                    "card is used by another device letter, so the built-in "
                    "simulates. Rename the module if you meant the Verilog-A "
                    "model.\n",
                    modtmp->INPmodName, builtin ? builtin : "device",
                    modtmp->INPmodTypeName, lib ? lib : "?");
        }
    }
#endif

#ifdef OSDI
    /* Enhancement-565 (LRM 6.4.2): a card naming an overloaded paramset
     * family is bound to the member its parameters select. Done here, where
     * the card is materialised: an `n` line reads the model's type after
     * INPgetMod returns (INP2N), so the instance follows. */
    if (modtmp->INPmodType >= 0 && osdi_devtype_is_osdi(modtmp->INPmodType)) {
        char *why = NULL;
        int sel = osdi_select_paramset_overload(modtmp->INPmodType, modtmp->INPmodLine->line,
                                                modtmp->INPmodName, &why);
        if (sel < 0) {
            modtmp->INPmodLine->error = INPerrCat(modtmp->INPmodLine->error, why);
            return E_PARMVAL;
        }
        modtmp->INPmodType = sel;
    }
#endif

    /* not already defined, so create & give parameters */
    error = ft_sim->newModel(ckt, modtmp->INPmodType, &(modtmp->INPmodfast), modtmp->INPmodName);
    if (error)
        return error;

#ifdef CIDER
    /* Handle Numerical Models Differently */
    if (modtmp->INPmodType == INPtypelook("NUMD") ||
        modtmp->INPmodType == INPtypelook("NBJT") ||
        modtmp->INPmodType == INPtypelook("NUMD2") ||
        modtmp->INPmodType == INPtypelook("NBJT2") ||
        modtmp->INPmodType == INPtypelook("NUMOS"))
    {
        error = INPparseNumMod(ckt, modtmp, tab, &err);
        if (error)
            return error;
        modtmp->INPmodLine->error = err;
        return 0;
    }
#endif

    IFdevice *device = ft_sim->devices[modtmp->INPmodType];

    /* parameter isolation, identification, binding */

    line = modtmp->INPmodLine->line;

#ifdef TRACE
    printf("In INPgetMod, inserting new model into table.  line = %s ...\n", line);
#endif

    INPgetTok(&line, &parm, 1);        /* throw away '.model' */
    tfree(parm);
    INPgetNetTok(&line, &parm, 1);        /* throw away 'modname' */
    tfree(parm);

#ifdef OSDI
    /* osdi models don't accept their device type as an argument */
    bool is_osdi = false;
    if (device->registry_entry){ 
        INPgetNetTok(&line, &parm, 1); /* throw away osdi */
        tfree(parm);
        is_osdi = true;
    }
#endif

    /* Enhancement-395: as in INPdevParse -- an OSDI parameter and each of its
     * `aliasparam` names share one .id, so a .model card that sets both writes
     * a single slot twice with no diagnostic. Model parameters and the
     * instance-parameter defaults a card may also carry are separate id
     * spaces, so they are tracked separately. OSDI only. */
    int n_mtrack = 0, n_itrack = 0;
    char **mseen = NULL, **iseen = NULL;
    /* Enhancement-468: track repeats for EVERY device, not only OSDI ones.
     *
     * E-395 built this to catch an OSDI `aliasparam` written twice on one line,
     * and scoped it there because aliasparam is a Verilog-A construct. But the
     * defect it protects against is not Verilog-A's: a built-in `.model` card
     * that sets one parameter twice took the last value in silence, and the
     * consequence is a different circuit --
     *
     *     .model dm d is=1e-14 is=9e-14     ->  i(v1) -5.67e-03 becomes -5.10e-02
     *
     * with nothing said, while a duplicate `.model` CARD is reported ("model
     * 'dm' is already defined") and a duplicate `.subckt` is reported too. The
     * id-based test is right for built-ins as well: their aliases (`r` for
     * `resistance`, `tc` for `tc1`) share an id, so writing both really is
     * writing one slot twice, and E-395's message already distinguishes the
     * same-keyword case from the alias case. */
    /* Built-in parameter ids are ENUM TAGS, not dense indices -- a diode's
     * model ids start at DIO_MOD_LEVEL = 100 -- so the id-indexed array E-395
     * used for OSDI silently tracked nothing here. Keep a short list of the
     * ids already written and search it; a card carries tens of parameters, so
     * the linear scan costs nothing and does not care how the ids are numbered. */
    int *mid = NULL, *iid = NULL, nmid = 0, niid = 0;
    if (device->numModelParms && device->numInstanceParms) {
        n_mtrack = *(device->numModelParms);
        n_itrack = *(device->numInstanceParms);
        mseen = TMALLOC(char *, n_mtrack);
        iseen = TMALLOC(char *, n_itrack);
        mid = TMALLOC(int, n_mtrack);
        iid = TMALLOC(int, n_itrack);
        memset(mseen, 0, (size_t)n_mtrack * sizeof(char *));
        memset(iseen, 0, (size_t)n_itrack * sizeof(char *));
    }

    /* Enhancement-480: 1 while the model TYPE token is still to be seen. An
     * OSDI card had its type consumed above, so its first token really is a
     * parameter and nothing is skipped there. */
#ifdef OSDI
    int first_tok = is_osdi ? 0 : 1;
#else
    int first_tok = 1;
#endif

    while (*line) {
        INPgetTok(&line, &parm, 1);
        if (!*parm) {
            FREE(parm);
            continue;
        }

        IFparm *p = find_model_parameter(parm, device);

        if (p) {
#ifdef OSDI
            if (is_osdi && (p->dataType & IF_VECTOR)){  
                // we need to get rid if the leading [ in order to make sure 
                // that INPgetValue can parse the value properly
                // This is because, unlike other SPICEDev, OSDI models receive
                // array params in the syntax (param_name=[...])
                ++line;
            }
#endif
            /* Enhancement-480: the FIRST token of a built-in `.model` card is
             * the device TYPE, not a parameter, and it is deliberately left in
             * `line` for the parse (only an OSDI card has its type thrown away
             * above). For most devices that is harmless here because the type
             * name is not also a parameter name -- `d` is not a diode
             * parameter, so `.model dm d(is=1e-14)` was clean. But `r`, `c` and
             * `l` ARE parameters of the resistor, capacitor and inductor, so
             * the type token was recorded as a first sighting and the real
             * assignment right after it looked like a repeat:
             *
             *     .model rmod r(r=1k)   ->  "parameter 'r' is set more than
             *                               once on this model card"
             *
             * on the most ordinary model card there is, telling the author to
             * remove one of the two things they wrote once. `r(res=1k)`
             * collected the aliasparam wording for the same reason. Skip the
             * type token for tracking only; the parse is untouched, so a
             * genuine `r(r=1k r=4k)` still reports exactly once. */
            /* Enhancement-480: `nmid < n_mtrack` used to gate the whole block,
             * so once the list was full -- every distinct model parameter seen
             * once -- a repeat was never even LOOKED UP. A device with a single
             * model parameter could therefore never report one:
             *
             *     .model mm dut(r=1k r=4k)   ->  4k silently wins
             *
             * for an OSDI model whose only model parameter is `r`. The
             * instance-default branch below has always had this right: it
             * searches unconditionally and bounds only the INSERT. Do the same
             * here, so the bound protects the array rather than the check. */
            if (mseen && !first_tok) {
                int q, hit = -1;
                for (q = 0; q < nmid; q++)
                    if (mid[q] == p->id) { hit = q; break; }
                if (hit >= 0) {
                    if (inp_warn_dup_param(device->name, mseen[hit], p->keyword))
                        return E_PARMVAL;
                }
                else if (nmid < n_mtrack) {
                    mid[nmid] = p->id;
                    mseen[nmid] = p->keyword;
                    nmid++;
                }
            }
            /* Enhancement-510: the FIRST token on a .model card is the model
               TYPE, and a type name can collide with a real parameter name --
               ngspice's resistor model has a parameter `r`, so `.model mm r`
               and `.model mm res` matched the type token as a parameter, called
               INPgetValue on what followed, and failed to parse a value there.
               The value checks below then reported

                 Error on .model mm : parameter (r) is not a number ...

               on every resistor model card in every deck. The simulation was
               right and the message was not. `first_tok` already exists for
               exactly this collision (it gates the duplicate-parameter warning
               above); the checks added since simply never consulted it. */
            int was_first_tok = first_tok;
            first_tok = 0;
            IFvalue *val = INPgetValue(ckt, &line, p->dataType, tab);
            /* Enhancement-507: a value that did not parse is not a value.
             *
             * INPgetValue's scalar paths returned 0 for a token INPevaluate
             * rejects and said nothing, so the model ran with that parameter set
             * to ZERO. numparam makes this ordinary rather than exotic: it
             * substitutes the TEXT of a `{...}` expression, and `{1/0}` becomes
             * `inf`, which this parser does not accept. `.model nm nmos ...
             * kp={1/0}` therefore built a transistor with kp = 0 and conducted
             * 1e-12 instead of 1.25e-4, with exit code 0. The same value written
             * as `inf` on the same card is refused, as is `{1/0}` on an instance
             * line, so this was the one path that took it. */
            if (val && !was_first_tok && INPlastRangeError()) {
                err = INPerrCat(err,
                    tprintf("Error on .model %s : parameter (%s) does not fit an "
                            "integer parameter, and would otherwise be applied as "
                            "the saturated value 2147483647 -- which can even pass "
                            "a `from [0:2147483647]` range check",
                            modtmp->INPmodName, p->keyword));
                FREE(parm);
                continue;               /* do NOT apply it */
            }
            if (val && !was_first_tok && INPlastValueError()) {
                err = INPerrCat(err,
                    tprintf("Error on .model %s : parameter (%s) is not a number "
                            "this parser accepts - a `{...}` expression that "
                            "evaluates to inf or nan arrives here as that literal "
                            "text, and would otherwise be applied as ZERO",
                            modtmp->INPmodName, p->keyword));
                FREE(parm);
                continue;               /* do NOT apply it */
            }
            if (val && !was_first_tok && INPlastRoundWarn()) {
                /* Applied anyway (the LRM's own round-to-nearest), but no
                 * longer in silence: for a compiled Verilog-A model this is
                 * usually an UNTYPED parameter whose type froze as integer
                 * from its default (LRM 3.4.1 would have re-typed it from the
                 * override; one fixed type per OSDI parameter cannot). */
                fprintf(stderr,
                        "Warning: .model %s: parameter (%s) is an integer; the "
                        "given non-integral value was rounded to the nearest "
                        "integer.\n",
                        modtmp->INPmodName, p->keyword);
            }
            error = ft_sim->setModelParm(ckt, modtmp->INPmodfast, p->id, val, NULL);
            if (error) {
                FREE(mseen);
                FREE(iseen);
                FREE(mid);
                FREE(iid);
                return error;
            }
        } else if ((strcmp(parm, "level") == 0) || (strcmp(parm, "m") == 0) ||
                   /* Enhancement-495: the four bin limits are consumed the way
                    * `level` is. On a BSIM card they are real model parameters
                    * and are matched above, so this is reached only for a type
                    * that has no such parameter -- an OSDI model, which may now
                    * be binned and therefore may carry them. Without this the
                    * selected bin's own card reported four unknown parameters. */
                   (strcmp(parm, "lmin") == 0) || (strcmp(parm, "lmax") == 0) ||
                   (strcmp(parm, "wmin") == 0) || (strcmp(parm, "wmax") == 0)) {
            /* no instance parameter default for level and multiplier */
            /* just grab the number and throw away */
            /* since we already have that info from pass1 */
            IFvalue *thrown = INPgetValue(ckt, &line, IF_REAL, tab);

            /* Enhancement-426: `m` written on a .model card is discarded here,
             * silently, while EVERY other instance parameter on a .model card
             * DOES become an instance default -- and for an OSDI model the
             * other spelling of the same slot, `_mfactor=`, works. Measured:
             * `.model nm nres(r=2k m=3)` gives @n1[m] = 1.0 and no message,
             * `.model nm nres(r=2k _mfactor=3)` gives 3.0 and 3x the current.
             *
             * The discard is NOT changed -- making it work would silently
             * multiply any deck that has carried a stray `m=` for years, which
             * is far wider than the evidence. It is only made audible, in the
             * style nport uses for this same parameter. `level` stays silent:
             * it is genuinely consumed in pass 1. */
            if (strcmp(parm, "m") == 0 &&
                find_instance_parameter("m", device) != NULL)
                fprintf(stderr,
                        "Warning: %s: `m` on a .model card is ignored; the "
                        "multiplier is an instance parameter -- write it on "
                        "the instance line%s.\n",
                        device->name,
                        device->registry_entry
                            ? " (or as `_mfactor` on the model card)" : "");
            NG_IGNORE(thrown);
        
        } else {

            p = find_instance_parameter(parm, device);

            if (p) {
                char *value;

                INPgetTok(&line, &value, 1);
                if (iseen) {
                    if (1) {
                        int q, hit = -1;
                        for (q = 0; q < niid; q++)
                            if (iid[q] == p->id) { hit = q; break; }
                        if (hit >= 0) {
                            if (inp_warn_dup_param(device->name, iseen[hit],
                                                   p->keyword))
                                return E_PARMVAL;
                        }
                        else if (niid < n_itrack) {
                            iid[niid] = p->id;
                            iseen[niid] = p->keyword;
                            niid++;
                        }
                    }
                }
                if (p->dataType & IF_SET) {
                    modtmp->INPmodfast->defaults =
                        wl_cons(copy(parm),
                                wl_cons(value, modtmp->INPmodfast->defaults));
                } else {
                    fprintf(stderr,
                            "Ignoring attempt to set a default "
                            "for read-only instance parameter %s in:\n  %s\n",
                            p->keyword, modtmp->INPmodLine->line);
                }
            } else {

                double dval;

                /* want only the parameter names in output - not the values */
                errno = 0;    /* To distinguish success/failure after call */
                dval = strtod(parm, &endptr);
                /* Check for various possible errors */
                if ((errno == ERANGE && dval == HUGE_VAL) || errno != 0) {
                    perror("strtod");
                    controlled_exit(EXIT_FAILURE);
                }
                if (endptr == parm) /* it was no number - it is really a string */
                    err = INPerrCat(err,
                                    tprintf("unrecognized parameter (%s) - ignored",
                                            parm));
            }
        }
        FREE(parm);
    }

    FREE(mseen);
    FREE(iseen);
    FREE(mid);
    FREE(iid);
    modtmp->INPmodLine->error = err;
    return 0;
}


static bool
parse_line(char *line, char *tokens[], int num_tokens, double values[], bool found[])
{
    int get_index = -1;
    int i;

    for (i = 0; i < num_tokens; i++)
        found[i] = FALSE;

    while (*line) {

        if (get_index != -1) {
            int error;
            values[get_index] = INPevaluate(&line, &error, 1);
            found[get_index] = TRUE;
            get_index = -1;
            continue;
        }

        char *token = NULL;
        INPgetNetTok(&line, &token, 1);

        for (i = 0; i < num_tokens; i++)
            if (strcmp(tokens[i], token) == 0)
                get_index = i;

        txfree(token);
    }

    for (i = 0; i < num_tokens; i++)
        if (!found[i])
            return FALSE;

    return TRUE;
}


/* Enhancement-495: the tolerance was ABSOLUTE, and these are METRES.
 *
 * `fabs(a - b) < 1e-9` on a channel length is a slop of one NANOMETRE, applied
 * whatever the geometry. A device up to 1 nm outside EVERY declared bin was
 * silently placed in one -- `l=31n` with bins reaching 30n bound to the 20n-30n
 * bin, while `l=31.1n` was refused, so the edge really was the fixed 1e-9. As a
 * fraction of the device the slop grows without bound as processes shrink: 0.03%
 * of a 3 um width, but 5% of a 20 nm channel.
 *
 * A bin limit is a number the model card states exactly, so what is wanted is
 * "the same number", not "within a nanometre". Scale the comparison to the
 * values themselves. 1e-12 relative is far tighter than any slop a card
 * intends and still absorbs the decimal-to-binary error in `1u` vs `1e-6`. */
#define BIN_RTOL 1.0e-12

static bool
is_equal(double result, double expectedResult)
{
    double a = fabs(result), b = fabs(expectedResult);
    double scale = (a > b) ? a : b;

    return fabs(result - expectedResult) <= BIN_RTOL * scale;
}


/* Enhancement-495: the comment below stated the rule the code did not follow.
 *
 * `min <= value < max` is what it says; accepting `is_equal(value, max)` as well
 * makes the interval CLOSED, so adjacent bins overlap at every shared boundary
 * and a device sitting on one matches both. Which one it got was then decided by
 * the order the `.model` cards happen to appear in -- reversing two cards moved
 * `l=2u` between bins and changed i(V1) by 2.95x on an otherwise identical deck.
 *
 * The strict rule is what selection now asks first. The closed reading is kept
 * as a SECOND pass, used only when the strict one matched nothing, because it is
 * what admits a device sitting exactly on the top bin's `lmax` -- there is no
 * bin above it, and refusing it would break decks that work today. That is the
 * Enhancement-493 shape: the existing reading still runs, but only where the
 * correct one found nothing, so nothing that already selected a bin can move. */
static bool
in_range(double value, double min, double max)
{
    /* the standard binning rule is: min <= value < max */
    return (is_equal(value, min) || value > min)
        && value < max && !is_equal(value, max);
}


/* the historical reading -- both ends inclusive -- kept for the fallback pass */
static bool
in_range_closed(double value, double min, double max)
{
    return is_equal(value, min) || is_equal(value, max) ||
           (min < value && value < max);
}


/* Enhancement-495: which model types may be binned.
 *
 * The list was eleven hardcoded built-ins, so a Verilog-A model compiled through
 * OSDI -- the way a modern PDK ships a compact model -- could not be binned at
 * all. Written exactly as a BSIM PDK writes it, with `nv.1`/`nv.2` and
 * lmin/lmax/wmin/wmax, it failed with
 *
 *     Unable to find definition of model nv
 *
 * for a model defined twice: the symptom, not the cause, and the same shape as
 * the resistor named `r` in Enhancement-493.
 *
 * OSDI devices are asked by the predicate Enhancement-323 already provides,
 * rather than by name, so every model any .osdi file defines is covered without
 * a list to maintain. The four bin limits are not Verilog-A parameters, so
 * INPgetMod below consumes them the way it consumes `level`. */
static bool
type_is_binnable(int type)
{
    static const char * const binnable[] = {
        "BSIM3", "BSIM3v32", "BSIM3v0", "BSIM3v1",
        "BSIM4", "BSIM4v5", "BSIM4v6", "BSIM4v7",
        "HiSIM2", "HiSIMHV1", "HiSIMHV2",
        NULL
    };
    int k;

    for (k = 0; binnable[k]; k++)
        if (type == INPtypelook((char *) binnable[k]))
            return TRUE;

#ifdef OSDI
    if (type >= 0 && osdi_devtype_is_osdi(type))
        return TRUE;
#endif

    return FALSE;
}


char *
INPgetModBin(CKTcircuit *ckt, char *name, INPmodel **model, INPtables *tab, char *line)
{
    INPmodel    *modtmp;
    double       l, w, lmin, lmax, wmin, wmax;
    double       parse_values[4];
    bool         parse_found[4];
    static char *instance_tokens[] = { "l", "w", "nf", "wnflag" };
    static char *model_tokens[]    = { "lmin", "lmax", "wmin", "wmax" };
    double       scale;
    int          wnflag;
    int          pass;

    if (!cp_getvar("scale", CP_REAL, &scale, 0))
        scale = 1;

    if (!cp_getvar("wnflag", CP_NUM, &wnflag, 0)) {
        if (newcompat.spe || newcompat.hs)
            wnflag = 1;
        else
            wnflag = 0;
    }

    *model = NULL;

    /* read W and L. If not on the instance line, leave */
    if (!parse_line(line, instance_tokens, 2, parse_values, parse_found))
        return NULL;

    /* This is for reading nf. If nf is not available, set to 1 if in HSPICE or Spectre compatibility mode */
    if (!parse_line(line, instance_tokens, 3, parse_values, parse_found)) {
        parse_values[2] = 1.; /* divisor */
    }
    /* This is for reading wnflag from instance. If it is not available, no change.
       If instance wnflag == 0, set divisor to 1, else use instance nf */
    else if (parse_line(line, instance_tokens, 4, parse_values, parse_found)) {
        /* wnflag from instance overrules: no use of nf */
        if (parse_values[3] == 0) {
            parse_values[2] = 1.; /* divisor */
        }
    }
    /* We do have nf, but no wnflag on the instance. Now it depends on the default
       wnflag or on the .options wnflag */
    else {
        if (wnflag == 0)
            parse_values[2] = 1.; /* divisor */
    }


    l = parse_values[0] * scale;
    w = parse_values[1] / parse_values[2] * scale;

    /* Enhancement-495: two passes.
     *
     * Pass 0 asks the documented half-open rule, `min <= value < max`, under
     * which the bins of a well-formed card set do not overlap -- so a device on
     * a shared boundary belongs to exactly one of them and the order the cards
     * were written stops mattering.
     *
     * Pass 1 asks the historical closed reading, and runs ONLY if pass 0
     * matched nothing. That is what still admits a device sitting exactly on
     * the top bin's `lmax`, which no half-open bin can contain and which decks
     * rely on today. Because it never runs when the strict rule already found a
     * bin, no selection that works today can move. */
    for (pass = 0; pass < 2; pass++) {

        for (modtmp = modtab; modtmp; modtmp = modtmp->INPnextModel) {

            if (model_name_match(name, modtmp->INPmodName) < 2)
                continue;

            /* skip if not binnable */
            if (!type_is_binnable(modtmp->INPmodType))
                continue;

            /* if illegal device type */
            if (modtmp->INPmodType < 0) {
                *model = NULL;
                return tprintf("Unknown device type for model %s\n", name);
            }

            if (!parse_line(modtmp->INPmodLine->line, model_tokens, 4,
                            parse_values, parse_found))
                continue;

            lmin = parse_values[0]; lmax = parse_values[1];
            wmin = parse_values[2]; wmax = parse_values[3];

            if (pass == 0
                ? (in_range(l, lmin, lmax) && in_range(w, wmin, wmax))
                : (in_range_closed(l, lmin, lmax) &&
                   in_range_closed(w, wmin, wmax))) {
                /* create unless model is already defined */
                if (!modtmp->INPmodfast) {
                    int error = create_model(ckt, modtmp, tab);
                    if (error)
                        return NULL;
                }

                *model = modtmp;
                return NULL;
            }
        }
    }

    return NULL;
}


char *
INPgetMod(CKTcircuit *ckt, char *name, INPmodel **model, INPtables *tab)
{
    INPmodel *modtmp;

#ifdef TRACE
    printf("In INPgetMod, examining model %s ...\n", name);
#endif

    if (modtabhash) {
        modtmp = nghash_find(modtabhash, name);
        if (modtmp) {
            /* found the model in question - now instantiate if necessary */
            /* and return an appropriate pointer to it */

    /* if illegal device type */
            if (modtmp->INPmodType < 0) {
#ifdef TRACE
                printf("In INPgetMod, illegal device type for model %s ...\n", name);
#endif
                * model = NULL;
                return tprintf("Unknown device type for model %s\n", name);
            }

            /* create unless model is already defined */
            if (!modtmp->INPmodfast) {
                int error = create_model(ckt, modtmp, tab);
                if (error) {
                    *model = NULL;
                    return INPerror(error);
                }
            }

            *model = modtmp;
            return NULL;
        }
    }
#if (0)
    for (modtmp = modtab; modtmp; modtmp = modtmp->INPnextModel) {

#ifdef TRACE
        printf("In INPgetMod, comparing %s against stored model %s ...\n", name, modtmp->INPmodName);
#endif

        if (strcmp(modtmp->INPmodName, name) == 0) {
            /* found the model in question - now instantiate if necessary */
            /* and return an appropriate pointer to it */

            /* if illegal device type */
            if (modtmp->INPmodType < 0) {
#ifdef TRACE
                printf("In INPgetMod, illegal device type for model %s ...\n", name);
#endif
                *model = NULL;
                return tprintf("Unknown device type for model %s\n", name);
            }

            /* create unless model is already defined */
            if (!modtmp->INPmodfast) {
                int error = create_model(ckt, modtmp, tab);
                if (error) {
                    *model = NULL;
                    return INPerror(error);
                }
            }

            *model = modtmp;
            return NULL;
        }
    }
#endif
#ifdef TRACE
    printf("In INPgetMod, didn't find model for %s, using default ...\n", name);
#endif

    *model = NULL;
    return tprintf("Unable to find definition of model %s\n", name);
}


#ifdef CIDER
/*
 * Parse a numerical model by running through the list of original
 * input cards which make up the model
 * Given:
 * 1. First card looks like: .model modname modtype <level=val>
 * 2. Other cards look like: +<whitespace>? where ? tells us what
 * to do with the next card:
 *    '#$*' = comment card
 *    '+'   = continue previous card
 *    other = new card
 */
static int
INPparseNumMod(CKTcircuit *ckt, INPmodel *model, INPtables *tab, char **errMessage)
{
    struct card *txtCard;    /* Text description of a card */
    GENcard *tmpCard = NULL; /* Processed description of a card */
    IFcardInfo *info = NULL; /* Info about the type of card located */
    char *cardName = NULL;   /* name of a card */
    int cardNum = 0;         /* number of this card in the overall line */
    char *err = NULL;        /* Strings for error messages */
    int error;

    /* Chase down to the top of the list of actual cards */
    txtCard = model->INPmodLine->actualLine;

    /* Skip the first card if it exists since there's nothing interesting */
    /* txtCard will be empty if the numerical model is empty */
    if (txtCard)
        txtCard = txtCard->nextcard;

    /* Now parse each remaining card */
    for (; txtCard; txtCard = txtCard->nextcard) {
        char *line = txtCard->line;
        cardNum++;

        /* Skip the initial '+' and any whitespace. */
        line++;
        while (*line == ' ' || *line == '\t')
            line++;

        switch (*line) {
        case '*':
        case '$':
        case '#':
        case '\0':
        case '\n':
            /* comment or empty cards */
            info = NULL;
            continue;
        case '+':
            /* continuation card */
            if (!info) {
                err = INPerrCat(err,
                                tprintf("Error on card %d : illegal continuation \'+\' - ignored",
                                        cardNum));
                continue;
            }
            /* Skip leading '+'s */
            while (*line == '+')
                line++;
            break;
        default:
            info = NULL;
            break;
        }

        if (!info) {
            /* new command card */
            if (cardName)       /* get rid of old card name */
                FREE(cardName);
            INPgetTok(&line, &cardName, 1);        /* get new card name */
            if (*cardName) {                 /* Found a name? */
                int lastType = INPfindCard(cardName, INPcardTab, INPnumCards);
                if (lastType >= 0) {
                    /* Add card structure to model */
                    info = INPcardTab[lastType];
                    error = info->newCard(&tmpCard, model->INPmodfast);
                    if (error) {
                        FREE(cardName);
                        return error;
                    }
                    /* Handle parameter-less cards */
                } else if (cinprefix(cardName, "title", 3)) {
                    /* Do nothing */
                } else if (cinprefix(cardName, "comment", 3)) {
                    /* Do nothing */
                } else if (cinprefix(cardName, "end", 3)) {
                    /* Terminate parsing */
                    *errMessage = err;
                    FREE(cardName);
                    return 0;
                } else {
                    /* Error */
                    err = INPerrCat(err,
                                    tprintf("Error on card %d : unrecognized name (%s) - ignored",
                                            cardNum, cardName));
                }
                FREE(cardName);
            }
        }

        if (!info)
            continue;

        /* parse the rest of this line */
        while (*line) {

            int invert = FALSE;
            /* Strip leading carat from booleans */
            if (*line == '^') {
                invert = TRUE;
                line++;
            }

            char *parm;                /* name of a parameter */
            INPgetTok(&line, &parm, 1);
            if (!*parm) {
                FREE(parm);
                break;
            }

            int idx = INPfindParm(parm, info->cardParms, info->numParms);
            if (idx == E_MISSING) {
                /* parm not found */
                err = INPerrCat(err,
                                tprintf("Error on card %d : unrecognized parameter (%s) - ignored",
                                        cardNum, parm));
            } else if (idx == E_AMBIGUOUS) {
                /* parm ambiguous */
                err = INPerrCat(err,
                                tprintf("Error on card %d : ambiguous parameter (%s) - ignored",
                                        cardNum, parm));
            } else {
                IFvalue *value = INPgetValue(ckt, &line, info->cardParms[idx].dataType, tab);

                /* invert if this is a boolean entry */
                if (invert) {
                    if ((info->cardParms[idx].dataType & IF_VARTYPES) == IF_FLAG)
                        value->iValue = 0;
                    else
                        err = INPerrCat(err,
                                        tprintf("Error on card %d : non-boolean parameter (%s) - \'^\' ignored",
                                                cardNum, parm));
                }

                error = info->setCardParm(info->cardParms[idx].id, value, tmpCard);
                if (info->cardParms[idx].dataType & IF_STRING) {
                    FREE(value->sValue);
                } else if (info->cardParms[idx].dataType & IF_REALVEC) {
                    FREE(value->v.vec.rVec);
                } else if (info->cardParms[idx].dataType & IF_INTVEC) {
                    FREE(value->v.vec.iVec);
                }
                if (error)
                    return error;
            }
            FREE(parm);
        }
    }

    *errMessage = err;
    return 0;
}


/*
 * Locate the best match to a card name in an IFcardInfo table
 */
static int
INPfindCard(char *name, IFcardInfo *table[], int numCards)
{
    int length = (int) strlen(name);
    int best = E_MISSING;
    int bestMatch = 0;

    int test;

    /* compare all the names in the card table to this name */
    for (test = 0; test < numCards; test++) {
        int match = cimatch(name, table[test]->name);
        if ((match > 0) && (match == bestMatch)) {
            best = E_AMBIGUOUS;
        } else if ((match > bestMatch) && (match == length)) {
            best = test;
            bestMatch = match;
        }
    }

    return best;
}


/*
 * Locate the best match to a parameter name in an IFparm table
 */
static int
INPfindParm(char *name, IFparm *table, int numParms)
{
    int length = (int) strlen(name);
    int best = E_MISSING;
    int bestMatch = 0;
    int bestId = -1;

    int test;

    /* compare all the names in the parameter table to this name */
    for (test = 0; test < numParms; test++) {
        int match = cimatch(name, table[test].keyword);
        if ((match == length) && (match == (int) strlen(table[test].keyword))) {
            /* exact match */
            return test;
        }
        int id = table[test].id;
        if ((match > 0) && (match == bestMatch) && (id != bestId)) {
            best = E_AMBIGUOUS;
        } else if ((match > bestMatch) && (match == length)) {
            bestMatch = match;
            bestId = id;
            best = test;
        }
    }

    return best;
}

#endif /* CIDER */
