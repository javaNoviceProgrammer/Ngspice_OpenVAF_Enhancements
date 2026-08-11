/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
Modified: 2000 AlansFixes
**********/

/*
 * Interface routines. These are specific to spice. The only changes to FTE
 * that should be needed to make FTE work with a different simulator is
 * to rewrite this file. What each routine is expected to do can be
 * found in the programmer's manual. This file should be the only one
 * that includes ngspice.header files.
 */

/*CDHW Notes:

I have never really understood the way Berkeley intended the six pointers
to default values (ci_defOpt/Task  ci_specOpt/Task ci_curOpt/Task) to work,
as there only see to be two data blocks to point at, or I've missed something
clever elsewhere.

Anyway, in the original 3f4 the interactive command 'set temp = 10'
set temp for its current task and clobbered the default values as a side
effect. When an interactive is run it created specTask using the spice
application default values, not the circuit defaults affected
by 'set temp = 10'.

The fix involves two changes

  1. Make 'set temp = 10' change the values in the 'default' block, not whatever
     the 'current' pointer happens to be pointing at (which is usually the
     default block except when one interactive is run immediately
after another).

  2. Hack CKTnewTask() so that it looks to see whether it is creating
a 'special'
     task, in which case it copies the values from
ft_curckt->ci_defTask providing
     everything looks sane, otherwise it uses the hard-coded
'application defaults'.

These are fairly minor changes, and as they don't change the data structures
they should be fairly 'safe'. However, ...


CDHW*/

#include "ngspice/ngspice.h"
#include "ngspice/cktdefs.h"
#include "ngspice/cpdefs.h"
#include "ngspice/tskdefs.h" /* Is really needed ? */
#include "ngspice/ftedefs.h"
#include "ngspice/fteinp.h"
#include "ngspice/inpdefs.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/ifsim.h"
#include "ngspice/hash.h"
#include "ngspice/devdefs.h"

#include "circuits.h"
#include "spiceif.h"
#include "variable.h"


#ifdef XSPICE
#include "ngspice/evt.h"
#include "ngspice/enh.h"
/* gtri - add - wbk - 11/9/90 - include MIF function prototypes */
#include "ngspice/mifproto.h"
/* gtri - end - wbk - 11/9/90 */

/* gtri - evt - wbk - 5/20/91 - Add stuff for user-defined nodes */
#include "ngspice/evtproto.h"
#include "ngspice/evtudn.h"
/* gtri - end - wbk - 5/20/91 - Add stuff for user-defined nodes */
#include "ngspice/mif.h"
#endif

extern INPmodel *modtab;
extern NGHASHPTR modtabhash;
extern bool ft_batchmode;

static struct variable *parmtovar(IFvalue *pv, IFparm *opt,
                                  int use_description);
static IFparm *parmlookup(IFdevice *dev, GENinstance **inptr, char *param,
                           int do_model, int inout);
static IFvalue *doask(CKTcircuit *ckt, int typecode, GENinstance *dev, GENmodel *mod,
                       IFparm *opt, int ind);
static int doset(CKTcircuit *ckt, int typecode, GENinstance *dev, GENmodel *mod,
                 IFparm *opt, struct dvec *val);
static int finddev(CKTcircuit *ckt, char *name, GENinstance **devptr, GENmodel **modptr);

/* espice fix integration */
static int finddev_special(CKTcircuit *ckt, char *name, GENinstance **devptr, GENmodel **modptr, int *device_or_model);

/* Input a single deck, and return a pointer to the circuit. 
   Parse all models in function INPpas1, instances (devices) in INPpas2,
   consider initial conditions (INPpas3), and shunt capacitors (INPpas4). */
CKTcircuit *
if_inpdeck(struct card *deck, INPtables **tab)
{
    CKTcircuit *ckt;
    int err, i;
    struct card *ll;
    IFuid taskUid;
    IFuid optUid;
    int which = -1;

    for (i = 0, ll = deck; ll; ll = ll->nextcard)
        i++;
    *tab = INPtabInit(i);
    ft_curckt->ci_symtab = *tab;

    err = ft_sim->newCircuit (&ckt);
    if (err != OK) {
        ft_sperror(err, "CKTinit");
        return (NULL);
    }

    /*CDHW Create a task DDD with a new UID. ci_defTask will point to it CDHW*/

    err = IFnewUid(ckt, &taskUid, NULL, "default", UID_TASK, NULL);
    if (err) {
        ft_sperror(err, "newUid");
        return (NULL);
    }

#if (0)
    err = ft_sim->newTask (ckt, &(ft_curckt->ci_defTask), taskUid);
#else /*CDHW*/
    err = ft_sim->newTask (ckt, &(ft_curckt->ci_defTask), taskUid, NULL);
#endif
    if (err) {
        ft_sperror(err, "newTask");
        return (NULL);
    }

    /*CDHW which options available for this simulator? CDHW*/

    which = ft_find_analysis("options");

    if (which != -1) {
        err = IFnewUid(ckt, &optUid, NULL, "options", UID_ANALYSIS, NULL);
        if (err) {
            ft_sperror(err, "newUid");
            return (NULL);
        }

        err = ft_sim->newAnalysis (ft_curckt->ci_ckt, which, optUid,
                                   &(ft_curckt->ci_defOpt),
                                   ft_curckt->ci_defTask);

        /*CDHW ci_defTask and ci_defOpt point to parameters DDD CDHW*/

        if (err) {
            ft_sperror(err, "createOptions");
            return (NULL);
        }

        ft_curckt->ci_curOpt  = ft_curckt->ci_defOpt;
        /*CDHW ci_curOpt and ci_defOpt point to DDD CDHW*/
    }

    ft_curckt->ci_curTask = ft_curckt->ci_defTask;

    modtab = NULL;
    modtabhash = NULL;
    /* Parsing the circuit 7.
       This is the next major step:
       Parse the .model lines.
       Enter the model into the global model table modtab
       and into the corresponding hash table modtabhash.
       The role of 'tab' is unclear (not used any more?). */
    INPpas1(ckt, deck->nextcard, *tab);
    /* store the new model tables in the current circuit */
    ft_curckt->ci_modtab = modtab;
    ft_curckt->ci_modtabhash = modtabhash;

    /* Parsing the circuit 8.
       This is the next major step:
       Scan through the instance lines and parse the circuit.
       Set up the circuit matrix. */
    INPpas2(ckt, deck->nextcard, *tab, ft_curckt->ci_defTask);
#ifdef XSPICE
    if (!Evtcheck_nodes(ckt, *tab)) {
        ft_sperror(E_PRIVATE, "Evtcheck_nodes");
        return NULL;
    }
#endif

    /* If option cshunt is given, add capacitors to each voltage node */
    INPpas4(ckt, *tab);

    /* Fill in .NODESET and .IC data.
     * nodeset/ic of non-existent nodes is rejected.  */
    INPpas3(ckt, deck->nextcard,
            *tab, ft_curckt->ci_defTask, ft_sim->nodeParms,
            ft_sim->numNodeParms);

#ifdef XSPICE
    /* gtri - begin - wbk - 6/6/91 - Finish initialization of event driven structures */
    err = EVTinit(ckt);
    if (err) {
        ft_sperror(err, "EVTinit");
        return (NULL);
    }
    /* gtri - end - wbk - 6/6/91 - Finish initialization of event driven structures */
#endif

    return (ckt);
}


/* Do a run of the circuit, of the given type. Type "resume" is
 * special -- it means to resume whatever simulation that was in
 * progress. The return value of this routine is 0 if the exit was ok,
 * and 1 if there was a reason to interrupt the circuit (interrupt
 * typed at the keyboard, error in the simulation, etc). args should
 * be the entire command line, e.g. "tran 1 10 20 uic" */
int
if_run(CKTcircuit *ckt, char *what, wordlist *args, INPtables *tab)
{
    int err;
    struct card deck;
    char buf[BSIZE_SP];
    int which = -1;
    IFuid specUid, optUid;
    char *s;


    /* First parse the line... */
    /*CDHW Look for an interactive task CDHW*/
    if (eq(what, "tran") ||
        eq(what, "ac") ||
        eq(what, "dc") ||
        eq(what, "op") ||
        eq(what, "pz") ||
        eq(what, "disto") ||
        eq(what, "adjsen") ||
        eq(what, "sens") ||
        eq(what, "tf") ||
        eq(what, "noise")
#ifdef WITH_PSS
        /* Steady State Analysis */
        || eq(what, "pss")
#endif
#ifdef RFSPICE
        || eq(what, "sp")
#ifdef WITH_HB
        || eq(what, "hb")
#endif
#endif
        )
    {
        s = wl_flatten(args); /* va: tfree char's tmalloc'ed in wl_flatten */
        (void) sprintf(buf, ".%s", s);
        tfree(s);
        deck.nextcard = deck.actualLine = NULL;
        deck.error = NULL;
        deck.linenum = 0;
        deck.compmod = 0;
        deck.line = buf;

        /*CDHW Delete any previous special task CDHW*/

        if (ft_curckt->ci_specTask) {
            if (ft_curckt->ci_specTask == ft_curckt->ci_defTask)   /*CDHW*/
                printf("Oh dear...something bad has happened to the options.\n");

            err = ft_sim->deleteTask (ft_curckt->ci_ckt, ft_curckt->ci_specTask);
            if (err) {
                ft_sperror(err, "deleteTask");
                return (2);
            }

            ft_curckt->ci_specTask = NULL;
            ft_curckt->ci_specOpt  = NULL; /*CDHW*/
        }
        /*CDHW Create an interactive task AAA with a new UID.
          ci_specTask will point to it CDHW*/

        err = IFnewUid(ft_curckt->ci_ckt, &specUid, NULL, "special", UID_TASK, NULL);
        if (err) {
            ft_sperror(err, "newUid");
            return (2);
        }
#if (0)
        err = ft_sim->newTask (ft_curckt->ci_ckt,
                               &(ft_curckt->ci_specTask), specUid);
#else /*CDHW*/

        err = ft_sim->newTask (ft_curckt->ci_ckt,
                               &(ft_curckt->ci_specTask),
                               specUid, &(ft_curckt->ci_defTask));
#endif
        if (err) {
            ft_sperror(err, "newTask");
            return (2);
        }

        /*CDHW which options available for this simulator? CDHW*/

        which = ft_find_analysis("options");

        if (which != -1) { /*CDHW options are available CDHW*/
            err = IFnewUid(ft_curckt->ci_ckt, &optUid, NULL, "options", UID_ANALYSIS, NULL);
            if (err) {
                ft_sperror(err, "newUid");
                return (2);
            }

            err = ft_sim->newAnalysis (ft_curckt->ci_ckt, which, optUid,
                                       &(ft_curckt->ci_specOpt),
                                       ft_curckt->ci_specTask);

            /*CDHW 'options' ci_specOpt points to AAA in this case CDHW*/

            if (err) {
                ft_sperror(err, "createOptions");
                return (2);
            }

            ft_curckt->ci_curOpt  = ft_curckt->ci_specOpt;

            /*CDHW ci_specTask ci_specOpt and ci_curOpt all point to AAA CDHW*/

        }

        ft_curckt->ci_curTask = ft_curckt->ci_specTask;

        /*CDHW ci_curTask and ci_specTask point to the interactive task AAA CDHW*/

        /* Enhancement-426: this card was synthesised above from a .control
         * command, so it is not deck parsing and a node it names must already
         * exist -- see inp_analysis_node() in inp2dot.c. CKTisSetup cannot
         * stand in for that: it is still 0 when this is the session's first
         * analysis, which is exactly when the check was being skipped. */
        INPanalysisCardFromCommand = 1;
        INPpas2(ckt, &deck, tab, ft_curckt->ci_specTask);
        INPanalysisCardFromCommand = 0;

        if (deck.error) {
            fprintf(cp_err, "Error: %sin   %s\n\n", deck.error, deck.line);
            return 2;
        }
    }

    /*CDHW
    ** if the task is to 'run' the deck, change ci_curTask and
    ** ci_curOpt to point to DDD
    ** created by if_inpdeck(), otherwise they point to AAA.
    CDHW*/

    if (eq(what, "run")) {
        ft_curckt->ci_curTask = ft_curckt->ci_defTask;
        ft_curckt->ci_curOpt = ft_curckt->ci_defOpt;
        if (ft_curckt->ci_curTask->jobs == NULL) {
            /* nothing to 'run' */
            if (!ft_batchmode) { /* FIXME: This is a hack to re-enable 'make check' */
                fprintf(stderr, "Warning: No job (tran, ac, op etc.) defined:\n");
                return (3);
            }
        }
    }

    /* -- Find out what we are supposed to do.              */

    if ((eq(what, "tran")) ||
        (eq(what, "ac")) ||
        (eq(what, "dc")) ||
        (eq(what, "op")) ||
        (eq(what, "pz")) ||
        (eq(what, "disto")) ||
        (eq(what, "noise")) ||
        (eq(what, "adjsen")) ||
        (eq(what, "sens")) ||
        (eq(what, "tf")) ||
#ifdef WITH_PSS
        /* SP: Steady State Analysis */
        (eq(what, "pss")) ||
        /* SP */
#endif
#ifdef RFSPICE
        (eq(what, "sp")) ||
#ifdef WITH_HB
        (eq(what, "hb")) ||
#endif
#endif
        (eq(what, "run")))
    {
        /*CDHW Run the analysis pointed to by ci_curTask CDHW*/

        ft_curckt->ci_curOpt = ft_curckt->ci_defOpt;
        if ((err = ft_sim->doAnalyses (ckt, 1, ft_curckt->ci_curTask)) != OK) {
            ft_sperror(err, "doAnalyses");
            /* wrd_end(); */
            if (err == E_PAUSE)
                return (1);
            else
                return (2);
        }
    } else if (eq(what, "resume")) {
        if ((err = ft_sim->doAnalyses (ckt, 0, ft_curckt->ci_curTask)) != OK) {
            ft_sperror(err, "doAnalyses");
            /* wrd_end(); */
            if (err == E_PAUSE)
                return (1);
            else
                return (2);
        }
    } else {
        fprintf(cp_err, "if_run: Internal Error: bad run type %s\n", what);
        return (2);
    }

    return (0);
}


/* Set an option in the circuit. Arguments are option name, type, and
 * value (the last a char *), suitable for casting to whatever needed...
 */

static char *unsupported[] = {
    "itl3",
    "itl5",
    "lvltim",
    "maxord",
    "method",
    NULL
};

static char *obsolete[] = {
    "limpts",
    "limtim",
    "lvlcod",
    NULL
};



/* Enhancement-438: does this name denote a simulator option at all?
 *
 * NOT a diagnostic in itself -- if_option() above is called by cp_usrset() for
 * EVERY shell variable that gets set, precisely to discover whether the name is
 * a simulator option, so an unrecognised name there is entirely normal and must
 * stay silent. (Warning inside if_option() makes ngspice complain about its own
 * `rndseed` on every run.)
 *
 * On a `.options` CARD the name is unambiguously meant to be an option, so the
 * deck path in inp.c can use this to say so. Without it a misspelling was
 * silently inert: `.options reltoll=1e-12` left reltol at its default while the
 * user believed the tolerance had been tightened. */
int
if_is_option(const char *name)
{
    static const char *const specials[] = {
        "acct", "noacct", "noinit", "norefvalue", "list", "node", "opts",
        "nopage", "nomod",
        "warn_physics",              /* Enhancement-438 */
        NULL
    };
    const char *const *sp;
    int which;
    IFparm *if_parm;

    if (!name || !*name)
        return 0;
    for (sp = specials; *sp; sp++)
        if (eq((char *) name, (char *) *sp))
            return 1;
    which = ft_find_analysis("options");
    if (which == -1)
        return 1;                /* cannot tell -- do not accuse the user */
    if_parm = ft_find_analysis_parm(which, (char *) name);
    return (if_parm && (if_parm->dataType & IF_SET)) ? 1 : 0;
}

int
if_option(CKTcircuit *ckt, char *name, enum cp_types type, void *value)
{
    IFvalue pval;
    int err;
    char **vv, *sfree = NULL;
    int which = -1;
    IFparm *if_parm;

    if (eq(name, "acct")) {
        ft_acctprint = TRUE;
        return 0;
    } else if (eq(name, "noacct")) {
        ft_noacctprint = TRUE;
        return 0;
    } else if (eq(name, "noinit")) {
        ft_noinitprint = TRUE;
        return 0;
    } else if (eq(name, "norefvalue")) {
        ft_norefprint = TRUE;
        return 0;
    } else if (eq(name, "list")) {
        ft_listprint = TRUE;
        return 0;
    } else if (eq(name, "node")) {
        ft_nodesprint = TRUE;
        return 0;
    } else if (eq(name, "opts")) {
        ft_optsprint = TRUE;
        return 0;
    } else if (eq(name, "nopage")) {
        ft_nopage = TRUE;
        return 0;
    } else if (eq(name, "nomod")) {
        ft_nomod = TRUE;
        return 0;
    } else if (eq(name, "warn_physics")) {
        /* Enhancement-438: consumed by if_check_physics() via cp_getvar; the
           .options machinery has already published it as a variable. */
        return 0;
    }

    which = ft_find_analysis("options");

    if (which == -1) {
        fprintf(cp_err, "Warning:  .options line unsupported\n");
        return 0;
    }

    if_parm = ft_find_analysis_parm(which, name);

    if (!if_parm || !(if_parm->dataType & IF_SET)) {
        /* See if this is unsupported or obsolete. */
        for (vv = unsupported; *vv; vv++)
            if (eq(name, *vv)) {
                fprintf(cp_err, "Warning: option %s is currently unsupported.\n", name);
                return 1;
            }
        for (vv = obsolete; *vv; vv++)
            if (eq(name, *vv)) {
                fprintf(cp_err, "Warning: option %s is obsolete.\n", name);
                return 1;
            }
        return 0;
    }

    switch (if_parm->dataType & IF_VARTYPES) {
    case IF_REAL:
        if (type == CP_REAL)
            pval.rValue = *((double *) value);
        else if (type == CP_NUM)
            pval.rValue = *((int *) value);
        else
            goto badtype;
        break;
    case IF_INTEGER:
        if (type == CP_NUM)
            pval.iValue = *((int *) value);
        else if (type == CP_REAL)
            pval.iValue = (int)floor((*(double *)value) + 0.5);
        else
            goto badtype;
        break;
    case IF_STRING:
        if (type == CP_STRING)
            sfree = pval.sValue = copy((char*) value);
        else
            goto badtype;
        break;
    case IF_FLAG:
        if (type == CP_BOOL)
            pval.iValue = *((bool *) value) ? 1 : 0;
        else if (type == CP_NUM) /* FIXME, shall we allow this ? */
            pval.iValue = *((int *) value);
        else
            goto badtype;
        break;
    default:
        fprintf(cp_err,
                "if_option: Internal Error: bad option type %d.\n",
                if_parm->dataType);
    }

    if (!ckt) {
        /* XXX No circuit loaded */
        fprintf(cp_err, "Simulation parameter \"%s\" can't be set until\n",
                name);
        fprintf(cp_err, "a circuit has been loaded.\n");
        return 1;
    }

#if (0)
    if ((err = ft_sim->setAnalysisParm (ckt, ft_curckt->ci_curOpt,
                                        if_parm->id, &pval,
                                        NULL)) != OK)
        ft_sperror(err, "setAnalysisParm(options) ci_curOpt");
#else /*CDHW*/
    if ((err = ft_sim->setAnalysisParm (ckt, ft_curckt->ci_defOpt,
                                        if_parm->id, &pval,
                                        NULL)) != OK)
        ft_sperror(err, "setAnalysisParm(options) ci_curOpt");
    tfree(sfree);
    return 1;
#endif

badtype:
    fprintf(cp_err, "Error: bad type given for option %s --\n", name);
    fprintf(cp_err, "\ttype given was ");
    switch (type) {
    case CP_BOOL:
        fputs("boolean", cp_err);
        break;
    case CP_NUM:
        fputs("integer", cp_err);
        break;
    case CP_REAL:
        fputs("real", cp_err);
        break;
    case CP_STRING:
        fputs("string", cp_err);
        break;
    case CP_LIST:
        fputs("list", cp_err);
        break;
    default:
        fputs("something strange", cp_err);
        break;
    }
    fprintf(cp_err, ", type expected was ");
    switch (if_parm->dataType & IF_VARTYPES) {
    case IF_REAL:
        fputs("real.\n", cp_err);
        break;
    case IF_INTEGER:
        fputs("integer.\n", cp_err);
        break;
    case IF_STRING:
        fputs("string.\n", cp_err);
        break;
    case IF_FLAG:
        fputs("flag.\n", cp_err);
        break;
    default:
        fputs("something strange.\n", cp_err);
        break;
    }

    if (type == CP_BOOL)
        fputs("\t(Note that you must use an = to separate option name and value.)\n",
              cp_err);
    return 0;
}


void
if_dump(CKTcircuit *ckt, FILE *file)
{
    NG_IGNORE(ckt);

    fprintf(file, "diagnostic output dump unavailable.");
}


void
if_cktfree(CKTcircuit *ckt, INPtables *tab)
{
    ft_sim->deleteCircuit (ckt);
    INPtabEnd(tab);
}


/* Return a string describing an error code. */

/* BLOW THIS AWAY.... */

char *
if_errstring(int code)
{
    return (INPerror(code));
}


/* Enhancement-410: find an instance whose name was written WITHOUT the
 * device-type letter that subcircuit flattening prepends.
 *
 * ngspice flattens a subcircuit by rewriting its cards back into the deck and
 * re-parsing them as ordinary element lines, and the parser takes the device
 * type from the FIRST CHARACTER of the card (inppas2.c). So the flattened refdes
 * has to keep a type letter in front: `r1` inside `x1` becomes `r.x1.r1`, or the
 * card `x1.r1 a m 1k` would be re-read as another subcircuit call. That is also
 * why translate_inst_name() exempts `x` devices -- their name already starts
 * with the right letter -- and why NODES, which have no type, keep plain
 * hierarchical paths (`x1.m`).
 *
 * The consequence is that `@x1.r1[resistance]` names nothing, while the node
 * beside it is spelled `x1.m`. This restores the symmetry, and the mapping needs
 * no search: the letter flattening prepends is literally the local name's own
 * first character (`bxx_putc(buffer, *name)`), and ngspice already requires a
 * device's name to begin with its type letter -- so `x1.r1` can only ever mean
 * `r.x1.r1`. Two device types cannot share a local name.
 *
 * STRICTLY A FALLBACK: the caller looks the exact name up first, so every name
 * that resolves today resolves to exactly what it does today. This is only
 * consulted after that fails.
 */
GENinstance *
if_find_instance_hier(CKTcircuit *ckt, const char *name)
{
    GENinstance *inst;
    const char *local;
    char *buf;
    size_t n;

    if (!ckt || !name || !*name)
        return NULL;
    local = strrchr(name, '.');
    if (!local || !local[1])
        return NULL;            /* not hierarchical -- nothing to reconstruct */
    local++;                    /* the leaf instance name */
    if (tolower_c(*local) == 'x')
        return NULL;            /* an X instance carries no prefix to restore */

    n = strlen(name);
    buf = TMALLOC(char, n + 3);
    if (!buf)
        return NULL;
    buf[0] = *local;
    buf[1] = '.';
    memcpy(buf + 2, name, n + 1);
    inst = ft_sim->findInstance(ckt, buf);
    tfree(buf);
    return inst;
}


/* A `.model` declared inside a subcircuit is renamed by subckt expansion to
 * `<instance-path>:<model>` -- modtranslate() in subckt.c builds it as
 * tprintf("%s:%s", scname, model_name), and scname is the instance path, so a
 * model in x1 becomes `x1:rmod` and one in x1/x2 becomes `x1.x2:rmod`. Levels
 * are separated by '.', the model itself by ':'.
 *
 * Nothing else in the hierarchy is spelled that way. Devices are `@x1.rx[p]`
 * (Enhancement-410) and nodes are `v(x1.mid)`, so a user who writes the model
 * the same way -- `@x1.rmod[res]` -- got "no such device or model name" and had
 * to discover the colon. This maps the dotted spelling onto the real one by
 * turning the LAST '.' into ':', which is exactly the instance-path/model
 * boundary at any nesting depth.
 *
 * STRICTLY A FALLBACK, and tried after Enhancement-410's: the caller has already
 * failed the exact instance and model lookups, so every name that resolves today
 * still resolves to exactly what it does today. A name that already contains ':'
 * was spelled the real way and was handled by the exact lookup.
 */
GENmodel *
if_find_model_hier(CKTcircuit *ckt, const char *name)
{
    GENmodel *mod;
    char *buf, *dot;

    if (!ckt || !name || !*name)
        return NULL;
    if (strchr(name, ':'))
        return NULL;            /* already the real spelling -- exact lookup ran */
    buf = copy(name);
    if (!buf)
        return NULL;
    dot = strrchr(buf, '.');
    if (!dot || !dot[1]) {      /* not hierarchical -- nothing to reconstruct */
        tfree(buf);
        return NULL;
    }
    *dot = ':';
    mod = ft_sim->findModel(ckt, buf);
    tfree(buf);
    return mod;
}


/* Get pointers to a device, its model, and its type number given the name. If
 * there is no such device, try to find a model with that name
 * device_or_model says if we are referencing a device or a model.
 *  finddev_special(ck, name, devptr, modptr, device_or_model):
 *  Introduced to look for correct reference in expression like  print @BC107 [is]
 * and find out  whether a model or a device parameter is referenced and properly
 * call the spif_getparam_special (ckt, name, param, ind, do_model) function in
 * vector.c - A. Roldan (espice).
 */
static int
finddev_special(
    CKTcircuit *ckt,
    char *name,
    GENinstance **devptr,
    GENmodel **modptr,
    int *device_or_model)
{
    *devptr = ft_sim->findInstance (ckt, name);
    if (*devptr) {
        *device_or_model = 0;
        return (*devptr)->GENmodPtr->GENmodType;
    }

    *modptr = ft_sim->findModel (ckt, name);
    if (*modptr) {
        *device_or_model = 1;
        return (*modptr)->GENmodType;
    }

    /* Enhancement-410: only now, after both exact lookups have failed, try the
       hierarchical name written without its device-type letter */
    *devptr = if_find_instance_hier(ckt, name);
    if (*devptr) {
        *device_or_model = 0;
        return (*devptr)->GENmodPtr->GENmodType;
    }

    /* ...and a subcircuit-local model written with a dot instead of its colon */
    *modptr = if_find_model_hier(ckt, name);
    if (*modptr) {
        *device_or_model = 1;
        return (*modptr)->GENmodType;
    }

    *device_or_model = 2;
    return (-1);
}


/* Get a parameter value from the circuit. If name is left unspecified,
 * we want a circuit parameter. Now works both for devices and models.
 * A.Roldan (espice)
 */
struct variable *
spif_getparam_special(CKTcircuit *ckt, char **name, char *param, int ind, int do_model)
{
    struct variable *vv = NULL, *tv;
    IFvalue *pv;
    IFparm *opt;
    int typecode, i, modelo_dispositivo;
    GENinstance *dev = NULL;
    GENmodel *mod = NULL;
    IFdevice *device;

    NG_IGNORE(do_model);

    /* fprintf(cp_err, "Calling if_getparam(%s, %s)\n", *name, param); */

    if (!param || (param && eq(param, "all"))) {
        INPretrieve(name, ft_curckt->ci_symtab);
        typecode = finddev_special(ckt, *name, &dev, &mod, &modelo_dispositivo);
        if (typecode == -1) {
            fprintf(cp_err, "Error: no such device or model name %s\n", *name);
            return (NULL);
        }
        device = ft_sim->devices[typecode];
        if (!modelo_dispositivo) {
            /* It is a device */
            for (i = 0; i < *(device->numInstanceParms); i++) {
                opt = &device->instanceParms[i];
                if (opt->dataType & IF_REDUNDANT || !opt->description)
                    continue;
                if (!(opt->dataType & IF_ASK))
                    continue;
                pv = doask(ckt, typecode, dev, mod, opt, ind);
                if (pv) {
                    tv = parmtovar(pv, opt, 0);
                    if (tv) {
                        if (vv)
                            tv->va_next = vv;
                        vv = tv;
                    }
                } else {
                    fprintf(cp_err,
                            "Internal Error: no parameter '%s' on device '%s'\n",
                            device->instanceParms[i].keyword, device->name);
                }
            }
            return (vv);
        } else { /* Is it a model or a device ? */
            /* It is a model */
            for (i = 0; i < *(device->numModelParms); i++) {
                opt = &device->modelParms[i];
                if (opt->dataType & IF_REDUNDANT || !opt->description)
                    continue;

                /* We check that the parameter is interesting and therefore is
                 * implemented in the corresponding function ModelAsk. Originally
                 * the argument of "if" was: || (opt->dataType & IF_STRING)) continue;
                 * so, a model parameter defined like  OP("type",   MOS_SGT_MOD_TYPE,
                 * IF_STRING, N-channel or P-channel MOS") would not be printed.
                 */

                /* if (!(opt->dataType & IF_ASK) || (opt->dataType & IF_UNINTERESTING) || (opt->dataType & IF_STRING)) continue; */
                if (!(opt->dataType & IF_ASK) || (opt->dataType & IF_UNINTERESTING))
                    continue;
                pv = doask(ckt, typecode, dev, mod, opt, ind);
                if (pv) {
                    tv = parmtovar(pv, opt, 0);
                    if (tv) {
                        if (vv)
                            tv->va_next = vv;
                        vv = tv;
                    }
                } else {
                    fprintf(cp_err,
                            "Internal Error: no parameter '%s' on device '%s'\n",
                            device->modelParms[i].keyword, device->name);
                }
            }
            return (vv);
        }
    } else if (param) {
        INPretrieve(name, ft_curckt->ci_symtab);
        typecode = finddev_special(ckt, *name, &dev, &mod, &modelo_dispositivo);
        if (typecode == -1) {
            fprintf(cp_err, "Error: no such device or model name %s\n", *name);
            return (NULL);
        }
        device = ft_sim->devices[typecode];
        opt = parmlookup(device, &dev, param, modelo_dispositivo, 0);
        if (!opt) {
            fprintf(cp_err, "Error: no such parameter %s.\n", param);
            return (NULL);
        }
        pv = doask(ckt, typecode, dev, mod, opt, ind);
        if (pv)
            vv = parmtovar(pv, opt, 0);
        return (vv);
    } else {
        return (if_getstat(ckt, *name));
    }
}


/* Get a parameter value from the circuit. If name is left unspecified,
 * we want a circuit parameter.
 */

struct variable *
spif_getparam(CKTcircuit *ckt, char **name, char *param, int ind, int do_model)
{
    struct variable *vv = NULL, *tv;
    IFvalue *pv;
    IFparm *opt;
    int typecode, i;
    GENinstance *dev = NULL;
    GENmodel *mod = NULL;
    IFdevice *device;

    /* fprintf(cp_err, "Calling if_getparam(%s, %s)\n", *name, param); */

    if (param && eq(param, "all")) {

        /* MW. My "special routine here" */
        INPretrieve(name, ft_curckt->ci_symtab);

        typecode = finddev(ckt, *name, &dev, &mod);
        if (typecode == -1) {
            fprintf(cp_err,
                    "Error: no such device or model name %s\n",
                    *name);
            return (NULL);
        }
        device = ft_sim->devices[typecode];
        for (i = 0; i < *(device->numInstanceParms); i++) {
            opt = &device->instanceParms[i];
            if (opt->dataType & IF_REDUNDANT || !opt->description)
                continue;
            if (!(opt->dataType & IF_ASK))
                continue;
            pv = doask(ckt, typecode, dev, mod, opt, ind);
            if (pv) {
                tv = parmtovar(pv, opt, 0);
                if (tv) {
                    if (vv)
                        tv->va_next = vv;
                    vv = tv;
                }
            } else {
                fprintf(cp_err,
                        "Internal Error: no parameter '%s' on device '%s'\n",
                        device->instanceParms[i].keyword,
                        device->name);
            }
        }
        return (vv);
    } else if (param) {

        /* MW.  */
        INPretrieve(name, ft_curckt->ci_symtab);
        typecode = finddev(ckt, *name, &dev, &mod);
        if (typecode == -1) {
            fprintf(cp_err, "Error: no such device or model name %s\n", *name);
            return (NULL);
        }
        device = ft_sim->devices[typecode];
        opt = parmlookup(device, &dev, param, do_model, 0);
        if (!opt) {
            fprintf(cp_err, "Error: no such parameter %s.\n", param);
            return (NULL);
        }
        pv = doask(ckt, typecode, dev, mod, opt, ind);
        if (pv)
            vv = parmtovar(pv, opt, 0);
        return (vv);
    } else {
        return (if_getstat(ckt, *name));
    }
}


/* 9/26/03 PJB : function to allow setting model of device */
void
if_setparam_model(CKTcircuit *ckt, char **name, char *val)
{
    GENinstance *dev     = NULL;
    GENinstance *prevDev = NULL;
    GENmodel    *curMod  = NULL;
    GENmodel    *newMod  = NULL;
    INPmodel    *inpmod  = NULL;
    GENinstance *iter;
    GENmodel    *mods, *prevMod;
    int         typecode;
    char        *modname;

    /* retrieve device name from symbol table */
    INPretrieve(name, ft_curckt->ci_symtab);
    /* find the specified device */
    typecode = finddev(ckt, *name, &dev, &curMod);
    if (typecode == -1) {
        fprintf(cp_err, "Error: no such device name %s\n", *name);
        return;
    }
    curMod = dev->GENmodPtr;
    modname = copy(dev->GENmodPtr->GENmodName);
    modname = strtok(modname, "."); /* want only have the parent model name */
    /*
      retrieve the model from the global model table; also add the model to 'ckt'
      and indicate model is being used
    */
    INPgetMod(ckt, modname, &inpmod, ft_curckt->ci_symtab);
    /* check if using model binning -- pass in line since need 'l' and 'w' */
    if (inpmod == NULL)
        INPgetModBin(ckt, modname, &inpmod, ft_curckt->ci_symtab, val);
    tfree(modname);
    if (inpmod == NULL) {
        fprintf(cp_err, "Error: no model available for %s.\n", val);
        return;
    }
    newMod = inpmod->INPmodfast;

    /* see if new model name same as current model name */
    if (newMod->GENmodName != curMod->GENmodName)
        printf("Notice: model has changed from %s to %s.\n", curMod->GENmodName, newMod->GENmodName);
    if (newMod->GENmodType != curMod->GENmodType) {
        fprintf(cp_err, "Error: new model %s must be same type as current model.\n", val);
        return;
    }

    /* fix current model linked list */
    prevDev = NULL;
    for (iter = curMod->GENinstances; iter; iter = iter->GENnextInstance) {
        if (iter->GENname == dev->GENname) {

            /* see if at beginning of linked list */
            if (prevDev == NULL)
                curMod->GENinstances     = iter->GENnextInstance;
            else
                prevDev->GENnextInstance = iter->GENnextInstance;

            /* update model for device */
            dev->GENmodPtr       = newMod;
            dev->GENnextInstance = newMod->GENinstances;
            newMod->GENinstances = dev;
            break;
        }
        prevDev = iter;
    }
    /* see if any devices remaining that reference current model */
    if (curMod->GENinstances == NULL) {
        prevMod = NULL;
        for (mods = ckt->CKThead[typecode]; mods; mods = mods->GENnextModel) {
            if (mods->GENmodName == curMod->GENmodName) {

                /* see if at beginning of linked list */
                if (prevMod == NULL)
                    ckt->CKThead[typecode] = mods->GENnextModel;
                else
                    prevMod->GENnextModel  = mods->GENnextModel;

                INPgetMod(ckt, mods->GENmodName, &inpmod, ft_curckt->ci_symtab);
                if (curMod != nghash_delete(ckt->MODnameHash, curMod->GENmodName))
                    fprintf(stderr, "ERROR, ouch nasal daemons ...\n");
                GENmodelFree(mods);

                inpmod->INPmodfast = NULL;
                break;
            }
            prevMod = mods;
        }
    }
}


void
if_setparam(CKTcircuit *ckt, char **name, char *param, struct dvec *val, int do_model)
{
    IFparm *opt;
    IFdevice *device;
    GENmodel *mod = NULL;
    GENinstance *dev = NULL;
    int typecode;

    /* PN  */
    INPretrieve(name, ft_curckt->ci_symtab);
    typecode = finddev(ckt, *name, &dev, &mod);
    if (typecode == -1) {
        fprintf(cp_err, "Error: no such device or model name %s\n", *name);
        return;
    }
    device = ft_sim->devices[typecode];
    opt = parmlookup(device, &dev, param, do_model, 1);
    if (!opt) {
        if (param)
            fprintf(cp_err, "Error: no such parameter %s.\n", param);
        else
            fprintf(cp_err, "Error: no default parameter.\n");
        return;
    }
    if (do_model && !mod) {
        mod = dev->GENmodPtr;
        dev = NULL;
    }
    doset(ckt, typecode, dev, mod, opt, val);

    /* Call to CKTtemp(ckt) will be invoked here only by 'altermod' commands,
       to set internal model parameters pParam of each instance for immediate use,
       otherwise e.g. model->BSIM3vth0 will be set, but not pParam of any BSIM3 instance.
       Call only if CKTtime > 0 to avoid conflict with previous 'reset' command.
       May contain side effects because called from many places.  h_vogt 110101
    */
    if (do_model && (ckt->CKTtime > 0)) {
        int error = 0;
        error = CKTtemp(ckt);
        if (error)
            fprintf(stderr, "Error during changing a device model parameter!\n");
        if (error)
            controlled_exit(1);
    }
}


/* Enhancement-268: set the model parameter `param` to `val` on EVERY model in the
 * circuit that HAS such a parameter -- the backend of the wildcard `@*[param]`
 * altermod / sweep knob. This lets one `sweep @*[wavelength] ...` co-vary a shared
 * parameter across several `.model` cards in place (no `.param` + deck re-source).
 * Model parameters are a property of the device TYPE, so a single `parmlookup`
 * per type decides whether that type's models carry `param`; matching models are
 * then set with `doset` (the same path a plain `altermod @model[param]=` uses).
 * Returns the number of models set. */
/* Enhancement-436: the model wildcard, narrowed to ONE model name.
 *
 * `@*[param]` sets every model that has `param`, which is usually far more than
 * intended: with an `rmod` in a subcircuit and an unrelated `omod` elsewhere,
 * both move. The other extreme, `@rmod[param]`, reaches only the top-level card,
 * because subcircuit expansion renamed every in-subcircuit copy to
 * `<instance-path>:rmod` -- so a deck with `rmod` in both places silently
 * adjusts one of them and leaves the instance copies at their old value.
 *
 * `@*:rmod[param]` is the missing middle: the model called `rmod`, wherever it
 * lives. The `*` stands for the instance path and matches ANY path INCLUDING
 * NONE, so the top-level card is included -- which is the whole point, since a
 * model usually exists at top level and in subcircuits at once.
 *
 * Matching is on the LEAF name: everything after the last ':' if there is one,
 * the whole name otherwise. That makes it depth-independent -- `rmod`,
 * `x1:rmod` and `x1.x2:rmod` all match -- without introducing pattern syntax.
 * Deliberately not a glob: E-269's wildcards are a small fixed token set, and a
 * mistyped pattern would match nothing silently. */
static const char *model_leaf(const char *name)
{
    const char *c = name ? strrchr(name, ':') : NULL;
    return c ? c + 1 : name;
}


int
if_setparam_wildcard_model_named(CKTcircuit *ckt, const char *leaf, char *param,
                                 struct dvec *val)
{
    int typecode, count = 0;

    if (!leaf || !*leaf || !param || !*param || !ckt)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *dummy  = NULL;
        GENmodel    *mod;
        IFparm      *opt;

        if (!device || !ckt->CKThead[typecode])
            continue;
        opt = parmlookup(device, &dummy, param, 1 /*do_model*/, 1 /*inout=set*/);
        if (!opt)
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            const char *nm = mod->GENmodName;
            if (!nm || !eq(model_leaf(nm), leaf))
                continue;
            doset(ckt, typecode, NULL, mod, opt, val);
            count++;
        }
    }

    /* same mid-run propagation as if_setparam_wildcard below */
    if (count > 0 && ckt->CKTtime > 0) {
        int error = CKTtemp(ckt);
        if (error) {
            fprintf(stderr, "Error during wildcard model-parameter change!\n");
            controlled_exit(1);
        }
    }
    return count;
}


/* Enhancement-436: does any loaded model carry this leaf name at all? Used to
 * tell "no model called that" apart from "that model has no such parameter". */
int
if_hasmodel_named(CKTcircuit *ckt, const char *leaf)
{
    int typecode, count = 0;
    if (!leaf || !*leaf || !ckt)
        return 0;
    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        GENmodel *mod;
        if (!ft_sim->devices[typecode] || !ckt->CKThead[typecode])
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel)
            if (mod->GENmodName && eq(model_leaf(mod->GENmodName), leaf))
                count++;
    }
    return count;
}


int
if_setparam_wildcard(CKTcircuit *ckt, char *param, struct dvec *val)
{
    int typecode, count = 0;

    if (!param || !*param || !ckt)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *dummy  = NULL;
        GENmodel    *mod;
        IFparm      *opt;

        if (!device || !ckt->CKThead[typecode])
            continue;
        /* does this device type have a settable model parameter named `param`? */
        opt = parmlookup(device, &dummy, param, 1 /*do_model*/, 1 /*inout=set*/);
        if (!opt)
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            doset(ckt, typecode, NULL, mod, opt, val);
            count++;
        }
    }

    /* mirror if_setparam's altermod behaviour: propagate to instances mid-run */
    if (count > 0 && ckt->CKTtime > 0) {
        int error = CKTtemp(ckt);
        if (error) {
            fprintf(stderr, "Error during wildcard model-parameter change!\n");
            controlled_exit(1);
        }
    }

    return count;
}


/* Enhancement-269: set the INSTANCE parameter `param` to `val` on EVERY device
 * instance in the circuit that has it -- the backend of the instance wildcards
 * `@#*[param]` / `@*[[param]]`. Where `@*[param]` (Enhancement-268) targets model
 * cards, this targets the per-instance value. Instance parameters are a property
 * of the device TYPE, so a single `parmlookup(..., do_model=0, ...)` per type
 * decides whether that type's instances carry `param`; each instance (walking
 * every model's `GENinstances -> GENnextInstance`) is then set with `doset`
 * (`dev != NULL` -> `setInstanceParm`, the same path a plain `alter @dev[param]=`
 * uses). Returns the number of instances set. */
int
if_setparam_wildcard_instance(CKTcircuit *ckt, char *param, struct dvec *val)
{
    int typecode, count = 0;

    if (!param || !*param || !ckt)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *dummy  = NULL;
        GENmodel    *mod;
        IFparm      *opt;

        if (!device || !ckt->CKThead[typecode])
            continue;
        /* does this device type have a settable INSTANCE parameter named `param`? */
        opt = parmlookup(device, &dummy, param, 0 /*instance*/, 1 /*inout=set*/);
        if (!opt)
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            GENinstance *inst;
            for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
                doset(ckt, typecode, inst, NULL, opt, val);
                count++;
            }
        }
    }

    if (count > 0 && ckt->CKTtime > 0) {
        int error = CKTtemp(ckt);
        if (error) {
            fprintf(stderr, "Error during wildcard instance-parameter change!\n");
            controlled_exit(1);
        }
    }

    return count;
}

/* Enhancement-284: does ANY loaded model (do_model != 0) or instance (do_model == 0)
 * carry a settable parameter named `param`? This only PROBES -- nothing is changed.
 * It lets a wildcard that matched nothing report the form that would have worked,
 * instead of a bare "not found" that reads like a spelling/case problem. */
int
if_hasparam_wildcard(CKTcircuit *ckt, char *param, int do_model)
{
    int typecode, count = 0;

    if (!param || !*param || !ckt)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *dummy  = NULL;
        GENmodel    *mod;

        if (!device || !ckt->CKThead[typecode])
            continue;
        if (!parmlookup(device, &dummy, param, do_model, 1 /*inout=set*/))
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            if (do_model) {
                count++;
            } else {
                GENinstance *inst;
                for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance)
                    count++;
            }
        }
    }

    return count;
}


/* Enhancement-409: read one target's scalar value into vals[*n]. Returns 0 --
 * refusing the whole capture -- for anything that is not a plain number, since a
 * vector-valued parameter cannot be put back from a single reading. */
static int
wild_ask_scalar(CKTcircuit *ckt, int typecode, GENinstance *dev, GENmodel *mod,
                IFparm *opt, double *vals, int *n, int cap)
{
    IFvalue *pv;

    if (*n >= cap)
        return 0;
    pv = doask(ckt, typecode, dev, mod, opt, 0);
    if (!pv)
        return 0;
    switch (opt->dataType & IF_VARTYPES) {
    case IF_REAL:
        vals[(*n)++] = pv->rValue;
        return 1;
    case IF_FLAG:
    case IF_INTEGER:
        vals[(*n)++] = (double) pv->iValue;
        return 1;
    default:
        return 0;
    }
}


/* Enhancement-409: write one target's scalar value back through the same `doset`
 * path a plain `alter`/`altermod` uses. */
static int
wild_set_scalar(CKTcircuit *ckt, int typecode, GENinstance *dev, GENmodel *mod,
                IFparm *opt, double value)
{
    struct dvec v;
    double d = value;

    /* The capture refuses anything vector-valued, so the set side should never
       see one; refuse rather than hand doset a one-element vector if the set and
       ask entries for a keyword ever disagree about the shape. */
    if (opt->dataType & IF_VECTOR)
        return E_UNSUPP;

    memset(&v, 0, sizeof v);
    v.v_realdata = &d;
    v.v_length = 1;
    v.v_flags = VF_REAL;
    return doset(ckt, typecode, dev, mod, opt, &v);
}


/* Enhancement-409: capture, and later put back, the PER-TARGET nominal values a
 * wildcard knob overwrites.
 *
 * `@*[p]` and `@#*[p]` set EVERY matching model (or instance) to ONE value, but
 * the values they overwrite can all differ -- two `.model` cards of the same type
 * routinely carry different numbers -- so undoing the change needs one reading
 * per target, not a single number. That is why `sweep` could not restore a
 * wildcard knob through Enhancement-385's scalar path.
 *
 * These walk exactly the same targets in exactly the same order as
 * if_setparam_wildcard{,_instance} above -- same device-type loop, same model and
 * instance chains, selected by the same `parmlookup(..., inout=set)` predicate --
 * so index i of the saved array names the same target on the way out as on the
 * way in.
 *
 * Saving is ALL-OR-NOTHING: a parameter that is settable but not askable, or one
 * that is not a plain number, cannot be undone, and a partially restored circuit
 * is harder to reason about than an untouched one (the rule Enhancement-385
 * already applies to concrete knobs). Returns the number of targets saved, or 0.
 */
int
if_saveparam_wildcard(CKTcircuit *ckt, char *param, int do_model,
                      double **valsOut, int *nOut)
{
    int typecode, n = 0, cap;
    double *vals;

    if (valsOut)
        *valsOut = NULL;
    if (nOut)
        *nOut = 0;
    if (!param || !*param || !ckt || !valsOut || !nOut)
        return 0;

    cap = if_hasparam_wildcard(ckt, param, do_model);
    if (cap <= 0)
        return 0;
    vals = TMALLOC(double, cap);
    if (!vals)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *sdummy = NULL, *admy = NULL;
        GENmodel    *mod;
        IFparm      *aopt;

        if (!device || !ckt->CKThead[typecode])
            continue;
        if (!parmlookup(device, &sdummy, param, do_model, 1 /*inout=set*/))
            continue;               /* not a target of this wildcard */
        /* the READABLE twin of the same parameter -- a set-only parameter
           cannot be undone at all, so refuse the whole capture */
        admy = NULL;
        aopt = parmlookup(device, &admy, param, do_model, 0 /*inout=ask*/);
        if (!aopt)
            goto fail;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            if (do_model) {
                if (!wild_ask_scalar(ckt, typecode, NULL, mod, aopt, vals, &n, cap))
                    goto fail;
            } else {
                GENinstance *inst;
                for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance)
                    if (!wild_ask_scalar(ckt, typecode, inst, NULL, aopt,
                                         vals, &n, cap))
                        goto fail;
            }
        }
    }

    if (n != cap)               /* the two walks disagreed -- do not risk it */
        goto fail;

    *valsOut = vals;
    *nOut = n;
    return n;

fail:
    tfree(vals);
    return 0;
}


/* Enhancement-409: put back what if_saveparam_wildcard() captured. Returns the
 * number of targets restored. */
int
if_restoreparam_wildcard(CKTcircuit *ckt, char *param, int do_model,
                         const double *vals, int n)
{
    int typecode, i = 0, count = 0;

    if (!param || !*param || !ckt || !vals || n <= 0)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *dummy  = NULL;
        GENmodel    *mod;
        IFparm      *opt;

        if (!device || !ckt->CKThead[typecode])
            continue;
        opt = parmlookup(device, &dummy, param, do_model, 1 /*inout=set*/);
        if (!opt)
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            if (do_model) {
                if (i >= n)
                    goto done;
                if (wild_set_scalar(ckt, typecode, NULL, mod, opt, vals[i++]) == OK)
                    count++;
            } else {
                GENinstance *inst;
                for (inst = mod->GENinstances; inst; inst = inst->GENnextInstance) {
                    if (i >= n)
                        goto done;
                    if (wild_set_scalar(ckt, typecode, inst, NULL, opt,
                                        vals[i++]) == OK)
                        count++;
                }
            }
        }
    }

done:
    /* mirror if_setparam_wildcard: propagate to instances mid-run */
    if (count > 0 && ckt->CKTtime > 0) {
        int error = CKTtemp(ckt);
        if (error) {
            fprintf(stderr, "Error while restoring wildcard parameter!\n");
            controlled_exit(1);
        }
    }

    return count;
}



/* ------------------------------------------------------------------------
 * Enhancement-438: `.option warn_physics` -- an OPT-IN check that device
 * parameters lie inside their physically meaningful domain.
 *
 * WHY OPT-IN. Every value flagged here is one a simulator has good reason to
 * accept by default: a negative resistance is a standard small-signal
 * equivalent, a negative capacitance appears in de-embedding, and behavioural
 * modelling deliberately uses non-physical elements. Refusing them outright
 * would break working decks. But when a value is a MISTAKE it is currently
 * silent, and the results stay plausible rather than obviously wrong:
 *
 *   K1 L1 L2 1.5     a coupling coefficient above 1 makes the inductance matrix
 *                    indefinite -- the pair GENERATES energy. Measured on a 1:1
 *                    transformer: |v(secondary)| = 1.178 while
 *                    |v(primary)| = 0.9986, which |k| <= 1 makes impossible.
 *   .model sw sw ron=-1     a switch that is a -1 ohm resistor when closed;
 *                    a passive divider then reports a NEGATIVE node voltage.
 *   M1 ... l=-1u     a MOSFET with negative channel length sources current and
 *                    pushes a node ABOVE the supply rail (1.0306 V from 1 V).
 *
 * So the values stay legal and the check is something you ask for. It runs over
 * the same device-type / model / instance walk the wildcard accessors use, so it
 * needs no per-device code and picks up any device exposing these parameter
 * names.
 *
 * Deliberately NOT flagged: `is`. The name collides -- it is the diode/BJT
 * SATURATION CURRENT on a model card but the SOURCE CURRENT on a MOSFET
 * instance, where a negative value is the normal operating point. (ngspice
 * already clamps a negative diode `is` to 1e-28, so nothing is lost.) This is
 * the hazard of matching on parameter NAME across every device, and the reason
 * every rule here is checked against a clean multi-device deck before shipping.
 *
 * Deliberately NOT flagged: `res`/`capacitance`/`inductance` sign. Negative
 * passives are the very idiom this project's own examples use for equivalent
 * circuits, and flagging them would make the option too noisy to leave on.
 */
int ng_warn_physics = 0;         /* Enhancement-438 */

enum phys_rule { PHYS_NONNEG, PHYS_ABS_LE1 };

static const struct {
    const char *param;
    enum phys_rule rule;
    const char *why;
} phys_rules[] = {
    { "k",    PHYS_ABS_LE1, "a coupling coefficient outside [-1,1] makes the "
                            "inductance matrix indefinite (the coupled pair can "
                            "generate energy)" },
    { "ron",  PHYS_NONNEG,  "a switch's closed resistance cannot be negative" },
    { "roff", PHYS_NONNEG,  "a switch's open resistance cannot be negative" },
    { "l",    PHYS_NONNEG,  "a channel length cannot be negative" },
    { "w",    PHYS_NONNEG,  "a channel width cannot be negative" },
    { "area", PHYS_NONNEG,  "an area factor cannot be negative" },
    { "bf",   PHYS_NONNEG,  "a forward current gain cannot be negative" },
    { "br",   PHYS_NONNEG,  "a reverse current gain cannot be negative" },
    { NULL, PHYS_NONNEG, NULL }
};

/* Enhancement-438: only a STRICTLY NEGATIVE value is flagged, never zero.
 * These parameter names are shared across devices where zero is the ordinary
 * "not specified" default -- a resistor model carries `l`, a diode carries `l`,
 * and both sit at 0 in every normal deck. Flagging zero made the option warn
 * six times on a circuit with nothing wrong with it, which is the fastest way
 * to get a diagnostic switched off and ignored. Every finding this was written
 * for (ron=-1, l=-1u, is<0, bf<0, |k|>1) is caught by the negative test. */
static int phys_bad(double v, enum phys_rule r)
{
    switch (r) {
    case PHYS_NONNEG:   return v < 0.0;
    case PHYS_ABS_LE1:  return !(v >= -1.0 && v <= 1.0);
    }
    return 0;
}

/* Ask one target's scalar value; returns 0 if it is not a plain number. */
static int phys_ask(CKTcircuit *ckt, int typecode, GENinstance *dev,
                    GENmodel *mod, IFparm *opt, double *out)
{
    IFvalue *pv = doask(ckt, typecode, dev, mod, opt, 0);
    if (!pv)
        return 0;
    switch (opt->dataType & IF_VARTYPES) {
    case IF_REAL:                *out = pv->rValue;          return 1;
    case IF_INTEGER: case IF_FLAG: *out = (double) pv->iValue; return 1;
    default:                     return 0;
    }
}

int
if_check_physics(CKTcircuit *ckt)
{
    int typecode, r, nbad = 0;

    if (!ckt)
        return 0;

    for (r = 0; phys_rules[r].param; r++) {
        char pname[64];
        (void) snprintf(pname, sizeof pname, "%s", phys_rules[r].param);
        for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
            IFdevice *device = ft_sim->devices[typecode];
            GENinstance *dummy = NULL;
            GENmodel *mod;
            IFparm *mopt, *iopt;
            double v;

            if (!device || !ckt->CKThead[typecode])
                continue;
            dummy = NULL;
            mopt = parmlookup(device, &dummy, pname, 1 /*model*/, 0 /*ask*/);
            dummy = NULL;
            iopt = parmlookup(device, &dummy, pname, 0 /*instance*/, 0 /*ask*/);
            if (!mopt && !iopt)
                continue;

            for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
                if (mopt && phys_ask(ckt, typecode, NULL, mod, mopt, &v) &&
                    phys_bad(v, phys_rules[r].rule)) {
                    fprintf(cp_err, "Warning: model '%s' has %s = %g -- %s.\n",
                            mod->GENmodName ? mod->GENmodName : "?",
                            pname, v, phys_rules[r].why);
                    nbad++;
                }
                if (iopt) {
                    GENinstance *inst;
                    for (inst = mod->GENinstances; inst;
                         inst = inst->GENnextInstance) {
                        if (phys_ask(ckt, typecode, inst, NULL, iopt, &v) &&
                            phys_bad(v, phys_rules[r].rule)) {
                            fprintf(cp_err,
                                    "Warning: instance '%s' has %s = %g -- %s.\n",
                                    inst->GENname ? inst->GENname : "?",
                                    pname, v, phys_rules[r].why);
                            nbad++;
                        }
                    }
                }
            }
        }
    }
    return nbad;
}

/* Enhancement-437: the save/restore twins of if_setparam_wildcard_model_named.
 *
 * Enhancement-436 gave `@*:rmod[param]` its own dispatch for SETTING, but not
 * for the capture/replay that `sweep` needs to put a knob back. Without them a
 * sweep over `@*:rmod[res]` left every matched model at the LAST swept value --
 * the same defect Enhancement-409 fixed for `@*[param]`, reappearing for the
 * newer spelling because it did not route into E-409's path.
 *
 * As with E-409, these must walk EXACTLY the targets, in EXACTLY the order, that
 * if_setparam_wildcard_model_named walks -- same device-type loop, same model
 * chain, same `eq(model_leaf(nm), leaf)` predicate -- so index i names the same
 * model on the way out as on the way in. The leaf filter is the only difference
 * from if_{save,restore}param_wildcard. */
static int
if_hasparam_wildcard_model_named(CKTcircuit *ckt, const char *leaf, char *param)
{
    int typecode, count = 0;

    if (!leaf || !*leaf || !param || !*param || !ckt)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *dummy  = NULL;
        GENmodel    *mod;

        if (!device || !ckt->CKThead[typecode])
            continue;
        if (!parmlookup(device, &dummy, param, 1 /*do_model*/, 1 /*inout=set*/))
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel)
            if (mod->GENmodName && eq(model_leaf(mod->GENmodName), leaf))
                count++;
    }
    return count;
}


int
if_saveparam_wildcard_model_named(CKTcircuit *ckt, const char *leaf, char *param,
                                  double **valsOut, int *nOut)
{
    int typecode, n = 0, cap;
    double *vals;

    if (valsOut)
        *valsOut = NULL;
    if (nOut)
        *nOut = 0;
    if (!leaf || !*leaf || !param || !*param || !ckt || !valsOut || !nOut)
        return 0;

    cap = if_hasparam_wildcard_model_named(ckt, leaf, param);
    if (cap <= 0)
        return 0;
    vals = TMALLOC(double, cap);
    if (!vals)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *sdummy = NULL, *admy = NULL;
        GENmodel    *mod;
        IFparm      *aopt;

        if (!device || !ckt->CKThead[typecode])
            continue;
        if (!parmlookup(device, &sdummy, param, 1 /*do_model*/, 1 /*inout=set*/))
            continue;
        /* the READABLE twin -- a set-only parameter cannot be undone at all, so
           refuse the whole capture (E-409's all-or-nothing rule) */
        admy = NULL;
        aopt = parmlookup(device, &admy, param, 1 /*do_model*/, 0 /*inout=ask*/);
        if (!aopt)
            goto fail;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            if (!mod->GENmodName || !eq(model_leaf(mod->GENmodName), leaf))
                continue;
            if (!wild_ask_scalar(ckt, typecode, NULL, mod, aopt, vals, &n, cap))
                goto fail;
        }
    }

    if (n != cap)               /* the two walks disagreed -- do not risk it */
        goto fail;

    *valsOut = vals;
    *nOut = n;
    return n;

fail:
    tfree(vals);
    return 0;
}


int
if_restoreparam_wildcard_model_named(CKTcircuit *ckt, const char *leaf,
                                     char *param, const double *vals, int n)
{
    int typecode, i = 0, count = 0;

    if (!leaf || !*leaf || !param || !*param || !ckt || !vals || n <= 0)
        return 0;

    for (typecode = 0; typecode < ft_sim->numDevices; typecode++) {
        IFdevice    *device = ft_sim->devices[typecode];
        GENinstance *dummy  = NULL;
        GENmodel    *mod;
        IFparm      *opt;

        if (!device || !ckt->CKThead[typecode])
            continue;
        opt = parmlookup(device, &dummy, param, 1 /*do_model*/, 1 /*inout=set*/);
        if (!opt)
            continue;
        for (mod = ckt->CKThead[typecode]; mod; mod = mod->GENnextModel) {
            if (!mod->GENmodName || !eq(model_leaf(mod->GENmodName), leaf))
                continue;
            if (i >= n)
                goto done;
            if (wild_set_scalar(ckt, typecode, NULL, mod, opt, vals[i++]) == OK)
                count++;
        }
    }

done:
    /* mirror if_setparam_wildcard_model_named: propagate to instances mid-run */
    if (count > 0 && ckt->CKTtime > 0) {
        int error = CKTtemp(ckt);
        if (error) {
            fprintf(stderr, "Error while restoring wildcard parameter!\n");
            controlled_exit(1);
        }
    }

    return count;
}


/* Make a linked list where the first node is a CP_LIST variable
 * pointing to the different values of the vector variables.
 *
 *
 * In the case of Vin_sin 1 0 sin (0 2 2000)
 * and of print @vin_sin[sin]
 *
 * vv->va_V.vV_list->va_V.vV_real = 2000
 * vv->va_V.vV_list->va_next->va_V.vV_real = 2
 * vv->va_V.vV_list->va_next->va_next->va_V.vV_real = 0
 * So the list is starting from behind, but no problem
 * This works fine
 */

static struct variable *
parmtolist(IFvalue *pv, IFparm *opt, char *name)
{
    struct variable *list = NULL;
    int              i;

    for (i = pv->v.numValue; --i >= 0;) {
        switch (opt->dataType & (IF_VARTYPES & ~IF_VECTOR)) {
        case IF_INTEGER:
            list = var_alloc_num(NULL, pv->v.vec.iVec[i], list);
            break;
        case IF_REAL:
        case IF_COMPLEX:
            list = var_alloc_real(NULL, pv->v.vec.rVec[i], list);
            break;
        case IF_STRING:
            list = var_alloc_string(NULL, copy(pv->v.vec.sVec[i]), list);
            break;
        case IF_FLAG:
            list = var_alloc_bool(NULL, pv->v.vec.iVec[i] ? TRUE : FALSE,
                                  list);
            break;
        default:
            fprintf(cp_err,
                    "parmtolist: Internal Error: bad PARM type "
                    "%#x for %s (%s).\n",
                    opt->dataType, opt->keyword, opt->description);
            if (name)
                free(name);
            break;
        }
    }

    if (i || pv->v.numValue == 0)
        list = var_alloc_vlist(name, list, NULL);
    if (pv->v.vec.iVec) {       // All the union members are pointers
        free(pv->v.vec.iVec);
        pv->v.vec.iVec = NULL;
    }
    return list;
}

static struct variable *
parmtovar(IFvalue *pv, IFparm *opt, int use_description)
{
    char *name;

    name = use_description ? opt->description : opt->keyword;
    if (name)
        name = copy(name);
    if (opt->dataType & IF_VECTOR)
        return parmtolist(pv, opt, name);

    switch (opt->dataType & IF_VARTYPES) {
    case IF_INTEGER:
        return var_alloc_num(name, pv->iValue, NULL);
    case IF_REAL:
    case IF_COMPLEX:
        return var_alloc_real(name, pv->rValue, NULL);
    case IF_STRING:
        return var_alloc_string(name, copy(pv->sValue), NULL);
    case IF_FLAG:
        return var_alloc_bool(name, pv->iValue ? TRUE : FALSE,
                              NULL);
    default:
        fprintf(cp_err,
                "parmtovar: Internal Error: bad PARM type %#x for %s (%s).\n",
                opt->dataType, opt->keyword, opt->description);
        if (name)
            free(name);
        return (NULL);
    }
}


/* Extract the parameter (IFparm structure) from the device or device's model.
 * If do_mode is TRUE then look in the device's parameters
 * If do_mode is FALSE then look in the device model's parameters
 * If inout equals 1 then look only for parameters with the IF_SET type flag
 * if inout equals 0 then look only for parameters with the IF_ASK type flag
 */

static IFparm *
parmlookup(IFdevice *dev, GENinstance **inptr, char *param, int do_model, int inout)
{
    int i;

    NG_IGNORE(inptr);

    /* First try the device questions... */
    if (!do_model && dev->numInstanceParms) {
        for (i = 0; i < *(dev->numInstanceParms); i++) {
            if (!param && (dev->instanceParms[i].dataType & IF_PRINCIPAL))
                return (&dev->instanceParms[i]);
            else if (!param)
                continue;
            else if ((((dev->instanceParms[i].dataType & IF_SET) && inout == 1) ||
                      ((dev->instanceParms[i].dataType & IF_ASK) && inout == 0)) &&
                     cieq(dev->instanceParms[i].keyword, param))
            {
                while ((dev->instanceParms[i].dataType & IF_REDUNDANT) && (i > 0))
                    i--;
                return (&dev->instanceParms[i]);
            }
        }
        return NULL;
    }

    /* `param` may be NULL here (e.g. `altermod nm c` -- com_altermod treats the
     * stray token as a second model to alter, with no param=value), so guard it
     * before eq()/strcmp(); the instance loop above already handles !param. */
    if (dev->numModelParms && param)
        for (i = 0; i < *(dev->numModelParms); i++)
            if (dev->modelParms[i].keyword &&
                (((dev->modelParms[i].dataType & IF_SET) && inout == 1) ||
                 ((dev->modelParms[i].dataType & IF_ASK) && inout == 0)) &&
                eq(dev->modelParms[i].keyword, param))
            {
                while ((dev->modelParms[i].dataType & IF_REDUNDANT) && (i > 0))
                    i--;
                return (&dev->modelParms[i]);
            }

    return (NULL);
}


/* Perform the CKTask call. We have both 'fast' and 'modfast', so the other
 * parameters aren't necessary.
 */

static IFvalue *
doask(CKTcircuit *ckt, int typecode, GENinstance *dev, GENmodel *mod, IFparm *opt, int ind)
{
    static IFvalue pv;
    int err;

    NG_IGNORE(typecode);

    /* Enhancement-386: `pv` is STATIC, so without this it carries the previous
     * query's bytes into the next one. Any ask handler that returns OK without
     * writing *value therefore handed the caller a stale reading rather than an
     * obviously-wrong one -- that is how `sens_cplx` produced denormal garbage
     * (2.12736e-314) that varied between calls. The handlers now all write, and
     * this makes the channel itself deterministic for any that ever do not.
     * Zero FIRST: pv.iValue below is an INPUT (the select index). */
    memset(&pv, 0, sizeof pv);

    pv.iValue = ind;    /* Sometimes this will be junk and ignored... */

    /* fprintf(cp_err, "Calling doask(%d, %x, %x, %x)\n",
       typecode, dev, mod, opt); */
    if (dev)
        err = ft_sim->askInstanceQuest (ckt, dev, opt->id, &pv, NULL);
    else
        err = ft_sim->askModelQuest (ckt, mod, opt->id, &pv, NULL);

    if (err != OK) {
        ft_sperror(err, "if_getparam");
        return (NULL);
    }

    return (&pv);
}


/* Perform the CKTset call. We have both 'fast' and 'modfast', so the other
 * parameters aren't necessary.
 */

static int
doset(CKTcircuit *ckt, int typecode, GENinstance *dev, GENmodel *mod, IFparm *opt, struct dvec *val)
{
    IFvalue nval;
    int err;
    int n;
    int *iptr;
    double *dptr;
    int i;

    NG_IGNORE(typecode);

    /* Count items */
    if (opt->dataType & IF_VECTOR) {
        n = nval.v.numValue = val->v_length;

        dptr = val->v_realdata;
        /* XXXX compdata!!! */

        switch (opt->dataType & (IF_VARTYPES & ~IF_VECTOR)) {
        case IF_FLAG:
        case IF_INTEGER:
            iptr = nval.v.vec.iVec = TMALLOC(int, n);

            for (i = 0; i < n; i++)
                *iptr++ = (int)floor(*dptr++ + 0.5);
            break;

        case IF_REAL:
            nval.v.vec.rVec = val->v_realdata;
            break;

        default:
            fprintf(cp_err,
                    "Can't assign value to \"%s\" (unsupported vector type)\n",
                    opt->keyword);
            return E_UNSUPP;
        }
    } else {
        switch (opt->dataType & IF_VARTYPES) {
        case IF_FLAG:
        case IF_INTEGER:
            nval.iValue = (int)floor(*val->v_realdata + 0.5);
            break;

        case IF_REAL:
            /*kensmith don't blow up with NULL dereference*/
            if (!val->v_realdata) {
                fprintf(cp_err, "Unable to determine the value\n");
                return E_UNSUPP;
            }

            nval.rValue = *val->v_realdata;
            break;

        default:
            fprintf(cp_err,
                    "Can't assign value to \"%s\" (unsupported type)\n",
                    opt->keyword);
            return E_UNSUPP;
        }
    }

    /* fprintf(cp_err, "Calling doask(%d, %x, %x, %x)\n",
       typecode, dev, mod, opt); */

    if (dev)
        err = ft_sim->setInstanceParm (ckt, dev, opt->id, &nval, NULL);
    else
        err = ft_sim->setModelParm (ckt, mod, opt->id, &nval, NULL);

    return err;
}


/* Get pointers to a device, its model, and its type number given the name. If
 * there is no such device, try to find a model with that name.
 */

static int
finddev(CKTcircuit *ckt, char *name, GENinstance **devptr, GENmodel **modptr)
{
    *devptr = ft_sim->findInstance (ckt, name);
    if (*devptr)
        return (*devptr)->GENmodPtr->GENmodType;

    *modptr = ft_sim->findModel (ckt, name);
    if (*modptr)
        return (*modptr)->GENmodType;

    /* Enhancement-410: only now, after both exact lookups have failed, try the
       hierarchical name written without its device-type letter */
    *devptr = if_find_instance_hier(ckt, name);
    if (*devptr)
        return (*devptr)->GENmodPtr->GENmodType;

    /* ...and a subcircuit-local model written with a dot instead of its colon */
    *modptr = if_find_model_hier(ckt, name);
    if (*modptr)
        return (*modptr)->GENmodType;

    return (-1);
}


/* get an analysis parameter by name instead of id */

int
if_analQbyName(CKTcircuit *ckt, int which, JOB *anal, char *name, IFvalue *parm)
{
    IFparm *if_parm = ft_find_analysis_parm(which, name);

    if (!if_parm)
        return (E_BADPARM);

    return (ft_sim->askAnalysisQuest (ckt, anal, if_parm->id, parm, NULL));
}


/* Get the parameters tstart, tstop, and tstep from the CKT struct. */

/* BLOW THIS AWAY TOO */

bool
if_tranparams(struct circ *ci, double *start, double *stop, double *step)
{
    IFvalue tmp;
    int err;
    int which = -1;
    JOB *anal;
    IFuid tranUid;

    if (!ci->ci_curTask)
        return (FALSE);

    which = ft_find_analysis("TRAN");

    if (which == -1)
        return (FALSE);

    err = IFnewUid(ci->ci_ckt, &tranUid, NULL, "Transient Analysis", UID_ANALYSIS, NULL);
    if (err != OK)
        return (FALSE);

    err = ft_sim->findAnalysis (ci->ci_ckt, &which, &anal, tranUid,
                                ci->ci_curTask, NULL);
    if (err != OK)
        return (FALSE);

    err = if_analQbyName(ci->ci_ckt, which, anal, "tstart", &tmp);
    if (err != OK)
        return (FALSE);

    *start = tmp.rValue;

    err = if_analQbyName(ci->ci_ckt, which, anal, "tstop", &tmp);
    if (err != OK)
        return (FALSE);

    *stop = tmp.rValue;

    err = if_analQbyName(ci->ci_ckt, which, anal, "tstep", &tmp);
    if (err != OK)
        return (FALSE);

    *step = tmp.rValue;
    return (TRUE);
}


/* Get the statistic called 'name'.  If this is NULL get all statistics
 * available.
 */

struct variable *
if_getstat(CKTcircuit *ckt, char *name)
{
    int         options_idx, i;
    IFanalysis *options;
    IFvalue     parm;
    IFparm     *if_parm;

    options_idx = ft_find_analysis("options");

    if (options_idx == -1) {
        fprintf(cp_err, "Warning:  statistics unsupported\n");
        return (NULL);
    }

    options = ft_sim->analyses[options_idx];

    if (name) {

        if_parm = ft_find_analysis_parm(options_idx, name);

        if (!if_parm)
            return (NULL);

        if (ft_sim->askAnalysisQuest (ckt,
                                      &(ft_curckt->ci_curTask->taskOptions),
                                      if_parm->id, &parm,
                                      NULL) == -1)
        {
            fprintf(cp_err, "if_getstat: Internal Error: can't get %s\n", name);
            return (NULL);
        }

        return (parmtovar(&parm, if_parm, 1));

    } else {

        struct variable *vars = NULL, **v = &vars;

        for (i = 0; i < options->numParms; i++) {

            if_parm = &(options->analysisParms[i]);

            if (!(if_parm->dataType & IF_ASK))
                continue;

            if (ft_sim->askAnalysisQuest (ckt,
                                          &(ft_curckt->ci_curTask->taskOptions),
                                          if_parm->id, &parm,
                                          NULL) == -1)
            {
                fprintf(cp_err,
                        "if_getstat: Internal Error: can't get a name for "
                        "analysis parameter %d\n",
                        if_parm->id);
                continue;
            }

            *v = parmtovar(&parm, if_parm, 1);
            v = &((*v)->va_next);
        }

        return (vars);
    }
}


/* Some small updates to make it work, h_vogt, Feb. 2012
   Still very experimental !
   It is now possible to save a state during transient simulation,
   reload it later into a new ngspice run and resume simulation.
   XSPICE code models probably will not do.
   LTRA transmission line will not do.
   Many others are not tested.
*/

#include "ngspice/cktdefs.h"
#include "ngspice/trandefs.h"

/* arg0: circuit file, arg1: data file */
void com_snload(wordlist *wl)
{
    int error = 0;
    FILE *file;
    int tmpI, i, size;
    CKTcircuit *my_ckt, *ckt;

    /*
      Pseudo code:

      source(file_name);
      This should setup all the device structs, voltage nodes, etc.

      call cktsetup;
      This is needed to setup vector mamory allocation for vectors and branch nodes

      load_binary_data(info);
      Overwrite the allocated numbers, rhs etc, with saved data
    */


    if (ft_curckt && !strstr(ft_curckt->ci_name, "script")) {
        /* Circuit, not a script */
        fprintf(cp_err, "Error: there is already a circuit loaded.\n");
        return;
    }

    /* source the circuit */
    inp_source(wl->wl_word);
    if (!ft_curckt)
        return;

    /* allocate all the vectors, with luck!  */
    if (!error)
        error = CKTsetup(ft_curckt->ci_ckt);
    if (!error)
        error = CKTtemp(ft_curckt->ci_ckt);

    if (error) {
        fprintf(cp_err, "Some error in the CKT setup fncts!\n");
        return;
    }

    /* so it resumes ... */
    ft_curckt->ci_inprogress = TRUE;

    /* now load the binary file */
    ckt = ft_curckt->ci_ckt;

    file = fopen(wl->wl_next->wl_word, "rb");

    if (!file) {
        fprintf(cp_err, "Error: Couldn't open \"%s\" for reading\n", wl->wl_next->wl_word);
        return;
    }

    if (fread(&tmpI, sizeof(int), 1, file) != 1) {
        (void) fprintf(cp_err, "Unable to read spice version from snapshot.\n");
        fclose(file);
        return;
    }
    if (tmpI != sizeof(CKTcircuit)) {
        fprintf(cp_err, "loaded num: %d, expected num: %ld\n", tmpI, (long)sizeof(CKTcircuit));
        fprintf(cp_err, "Error: snapshot saved with different version of spice\n");
        fclose(file);
        return;
    }

    my_ckt = TMALLOC(CKTcircuit, 1);

    if (fread(my_ckt, sizeof(CKTcircuit), 1, file) != 1) {
        (void) fprintf(cp_err, "Unable to read spice circuit from snapshot.\n");
        fclose(file);
        return;
    }

#define _t(name) ckt->name = my_ckt->name
#define _ta(name, size)                                                 \
    do { int __i; for (__i = 0; __i < size; __i++) _t(name[__i]); } while(0)

    _t(CKTtime);
    _t(CKTdelta);
    _ta(CKTdeltaOld, 7);
    _t(CKTtemp);
    _t(CKTnomTemp);
    _t(CKTvt);
    _ta(CKTag, 7);

    _t(CKTorder);
    _t(CKTmaxOrder);
    _t(CKTintegrateMethod);
    _t(CKTxmu);
    _t(CKTindverbosity);
    _t(CKTepsmin);

    _t(CKTniState);

    _t(CKTmaxEqNum);
    _t(CKTcurrentAnalysis);

    _t(CKTnumStates);
    _t(CKTmode);

    _t(CKTbypass);
    _t(CKTdcMaxIter);
    _t(CKTdcTrcvMaxIter);
    _t(CKTtranMaxIter);
    _t(CKTbreakSize);
    _t(CKTbreak);
    _t(CKTsaveDelta);
    _t(CKTminBreak);
    _t(CKTabstol);
    _t(CKTpivotAbsTol);
    _t(CKTpivotRelTol);
    _t(CKTreltol);
    _t(CKTchgtol);
    _t(CKTvoltTol);

    _t(CKTgmin);
    _t(CKTgshunt);
    _t(CKTcshunt);
    _t(CKTdelmin);
    _t(CKTtrtol);
    _t(CKTfinalTime);
    _t(CKTstep);
    _t(CKTmaxStep);
    _t(CKTinitTime);
    _t(CKTomega);
    _t(CKTsrcFact);
    _t(CKTdiagGmin);
    _t(CKTnumSrcSteps);
    _t(CKTnumGminSteps);
    _t(CKTgminFactor);
    _t(CKTnoncon);
    _t(CKTdefaultMosM);
    _t(CKTdefaultMosL);
    _t(CKTdefaultMosW);
    _t(CKTdefaultMosAD);
    _t(CKTdefaultMosAS);
    _t(CKThadNodeset);
    _t(CKTfixLimit);
    _t(CKTnoOpIter);
    _t(CKTisSetup);
#ifdef XSPICE
    _t(CKTadevFlag);
#endif
    _t(CKTtimeListSize);
    _t(CKTtimeIndex);
    _t(CKTsizeIncr);

    _t(CKTtryToCompact);
    _t(CKTbadMos3);
    _t(CKTkeepOpInfo);
    _t(CKTcopyNodesets);
    _t(CKTnodeDamping);
    _t(CKTabsDv);
    _t(CKTrelDv);
    _t(CKTtroubleNode);

#undef _foo
#define _foo(name, type, _size)                                         \
    do {                                                                \
        int __i;                                                        \
        if (fread(&__i, sizeof(int), 1, file) == 1 && __i > 0) {        \
            if (name) {                                                 \
                txfree(name);                                           \
            }                                                           \
            name = (type *) tmalloc((size_t) __i);                      \
            if (fread(name, 1, (size_t) __i, file) != (size_t) __i) {   \
                (void) fprintf(cp_err,                                  \
                        "Unable to read vector " #name "\n");           \
                break;                                                  \
            }                                                           \
        }                                                               \
        else {                                                          \
            fprintf(cp_err, "size for vector " #name " is 0\n");        \
        }                                                               \
        if ((_size) != -1 && __i !=                                     \
                (int) (_size) * (int) sizeof(type)) {                   \
            fprintf(cp_err, "expected %ld, but got %d for "#name"\n",   \
                    (_size)*(long)sizeof(type), __i);                   \
        }                                                               \
    } while(0)


    for (i = 0; i <= ckt->CKTmaxOrder+1; i++)
        _foo(ckt->CKTstates[i], double, ckt->CKTnumStates);

    size = SMPmatSize(ckt->CKTmatrix) + 1;
    _foo(ckt->CKTrhs, double, size);
    _foo(ckt->CKTrhsOld, double, size);
    _foo(ckt->CKTrhsSpare, double, size);
    _foo(ckt->CKTirhs, double, size);
    _foo(ckt->CKTirhsOld, double, size);
    _foo(ckt->CKTirhsSpare, double, size);
//    _foo(ckt->CKTrhsOp, double, size);
//    _foo(ckt->CKTsenRhs, double, size);
//    _foo(ckt->CKTseniRhs, double, size);

//    _foo(ckt->CKTtimePoints, double, -1);
//    _foo(ckt->CKTdeltaList, double, -1);

    _foo(ckt->CKTbreaks, double, ckt->CKTbreakSize);

    {   /* avoid invalid lvalue assignment errors in the macro _foo() */
        TSKtask *lname = NULL;
        _foo(lname, TSKtask, 1);
        ft_curckt->ci_curTask = lname;
    }

    /* To stop the Free */
    ft_curckt->ci_curTask->TSKname = NULL;
    ft_curckt->ci_curTask->jobs = NULL;

    _foo(ft_curckt->ci_curTask->TSKname, char, -1);

    {
        TRANan *lname = NULL;
        _foo(lname, TRANan, -1);
        ft_curckt->ci_curTask->jobs = (JOB *)lname;
    }
    ft_curckt->ci_curTask->jobs->JOBname = NULL;
    _foo(ft_curckt->ci_curTask->jobs->JOBname, char, -1);
    ft_curckt->ci_curTask->jobs->JOBnextJob = NULL;
    ckt->CKTcurJob = ft_curckt->ci_curTask->jobs;
    ((TRANan *)ft_curckt->ci_curTask->jobs)->TRANplot = NULL;

    _foo(ckt->CKTstat, STATistics, 1);
    ckt->CKTstat->STATdevNum = NULL;
    _foo(ckt->CKTstat->STATdevNum, STATdevList, -1);
    ckt->CKTstat->devCounts = NULL;
    _foo(ckt->CKTstat->devCounts, size_t, DEVmaxnum + 1);
    ckt->CKTstat->devTimes = NULL;
    _foo(ckt->CKTstat->devTimes, double, DEVmaxnum + 1);

#ifdef XSPICE
    _foo(ckt->evt, Evt_Ckt_Data_t, 1);
    _foo(ckt->enh, Enh_Ckt_Data_t, 1);
    g_mif_info.breakpoint.current = ckt->enh->breakpoint.current;
    g_mif_info.breakpoint.last = ckt->enh->breakpoint.last;
#endif

    tfree(my_ckt);
    fclose(file);

    /* Finally to resume the plot in some fashion */

    /* a worked out version of this should be enough */
    {
        IFuid *nameList;
        int numNames;
        IFuid timeUid;

        error = CKTnames(ckt, &numNames, &nameList);
        if (error) {
            fprintf(cp_err, "error in CKTnames\n");
            return;
        }
        SPfrontEnd->IFnewUid (ckt, &timeUid, NULL, "time", UID_OTHER, NULL);
        error = SPfrontEnd->OUTpBeginPlot (ckt, ckt->CKTcurJob,
                                           ckt->CKTcurJob->JOBname,
                                           timeUid, IF_REAL,
                                           numNames, nameList, IF_REAL,
                                           &(((TRANan*)ckt->CKTcurJob)->TRANplot));
        if (error) {
            fprintf(cp_err, "error in CKTnames\n");
            return;
        }
    }
}


void com_snsave(wordlist *wl)
{
    FILE *file;
    int i, size;
    CKTcircuit *ckt;
    TSKtask *task;

    if (!ft_curckt) {
        fprintf(cp_err, "Warning: there is no circuit loaded.\n");
        fprintf(cp_err, "    Command 'snsave' is ignored.\n");
        return;
    } else if (!ft_curckt->ci_ckt) { /* Set noparse? */
        fprintf(cp_err, "Warning: circuit not parsed.\n");
        fprintf(cp_err, "    Command 'snsave' is ignored.\n");
        return;
    }

    /* save the data */

    ckt = ft_curckt->ci_ckt;

#ifdef XSPICE
    if (ckt->CKTadevFlag == 1) {
        fprintf(cp_err, "Warning: snsave not implemented for XSPICE A devices.\n");
        fprintf(cp_err, "    Command 'snsave' will be ignored!\n");
        return;
    }
#endif

    task = ft_curckt->ci_curTask;

    if (task->jobs->JOBtype != 4) {
        fprintf(cp_err, "Warning: Only saving of tran analysis is implemented\n");
        return;
    }

    file = fopen(wl->wl_word, "wb");

    if (!file) {
        fprintf(cp_err,
                "Error: Couldn't open \"%s\" for writing\n", wl->wl_word);
        return;
    }

#undef _foo
#define _foo(name, type, num)                                           \
    do {                                                                \
        int __i;                                                        \
        if (name) {                                                     \
            __i = (num) * (int)sizeof(type); fwrite(&__i, sizeof(int), 1, file); \
            if ((num))                                                  \
                fwrite(name, sizeof(type), (size_t)(num), file);        \
        } else {                                                        \
            __i = 0;                                                    \
            fprintf(cp_err, #name " is NULL, zero written\n");          \
            fwrite(&__i, sizeof(int), 1, file);                         \
        }                                                               \
    } while(0)


    _foo(ckt, CKTcircuit, 1);

    /* To save list

       double *(CKTstates[8]);
       double *CKTrhs;
       double *CKTrhsOld;
       double *CKTrhsSpare;
       double *CKTirhs;
       double *CKTirhsOld;
       double *CKTirhsSpare;
       double *CKTrhsOp;
       double *CKTsenRhs;
       double *CKTseniRhs;
       double *CKTtimePoints;       list of all accepted timepoints in
       the current transient simulation
       double *CKTdeltaList;        list of all timesteps in the
       current transient simulation

    */


    for (i = 0; i <= ckt->CKTmaxOrder+1; i++)
        _foo(ckt->CKTstates[i], double, ckt->CKTnumStates);


    size = SMPmatSize(ckt->CKTmatrix) + 1;

    _foo(ckt->CKTrhs, double, size);
    _foo(ckt->CKTrhsOld, double, size);
    _foo(ckt->CKTrhsSpare, double, size);
    _foo(ckt->CKTirhs, double, size);
    _foo(ckt->CKTirhsOld, double, size);
    _foo(ckt->CKTirhsSpare, double, size);
//    _foo(ckt->CKTrhsOp, double, size);
//    _foo(ckt->CKTsenRhs, double, size);
//    _foo(ckt->CKTseniRhs, double, size);

//    _foo(ckt->CKTtimePoints, double, ckt->CKTtimeListSize);
//    _foo(ckt->CKTdeltaList, double, ckt->CKTtimeListSize);

    /* need to save the breakpoints, or something */
    _foo(ckt->CKTbreaks, double, ckt->CKTbreakSize);

    /* now save the TSK struct, ft_curckt->ci_curTask*/
    _foo(task, TSKtask, 1);
    _foo(task->TSKname, char, ((int)strlen(task->TSKname)+1));

    /* now save the JOB struct task->jobs */
    /* lol, only allow one job, tough! */
    /* Note that JOB is a base class, need to save actual type!! */
    _foo(task->jobs, TRANan, 1);
    _foo(task->jobs->JOBname, char, ((int)strlen(task->jobs->JOBname)+1));

    /* Finally the stats */
    _foo(ckt->CKTstat, STATistics, 1);
    _foo(ckt->CKTstat->STATdevNum, STATdevList, 1);
    _foo(ckt->CKTstat->devCounts, size_t, DEVmaxnum + 1);
    _foo(ckt->CKTstat->devTimes, double, DEVmaxnum + 1);

#ifdef XSPICE
    /* FIXME struct ckt->evt->data and others are not stored
       thus snsave, snload not compatible with XSPICE code models*/
    _foo(ckt->evt, Evt_Ckt_Data_t, 1);
    _foo(ckt->enh, Enh_Ckt_Data_t, 1);
#endif

    fclose(file);
    fprintf(stdout, "Snapshot saved to %s.\n", wl->wl_word);
}


int
ft_find_analysis(char *name)
{
    int j;
    for (j = 0; j < ft_sim->numAnalyses; j++)
        if (strcmp(ft_sim->analyses[j]->name, name) == 0)
            return j;
    return -1;
}


IFparm *
ft_find_analysis_parm(int which, char *name)
{
    int i;
    for (i = 0; i < ft_sim->analyses[which]->numParms; i++)
        if (!strcmp(ft_sim->analyses[which]->analysisParms[i].keyword, name))
            return &(ft_sim->analyses[which]->analysisParms[i]);
    return NULL;
}
