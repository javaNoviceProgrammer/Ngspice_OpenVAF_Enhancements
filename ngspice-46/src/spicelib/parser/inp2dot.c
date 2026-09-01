/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1988 Thomas L. Quarles
Modified: 2000 AlansFixes
**********/

#include "ngspice/ngspice.h"
#include <stdio.h>
#include "ngspice/ifsim.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/inpdefs.h"
#include "ngspice/inpmacs.h"
#include "ngspice/fteext.h"
#include "inpxx.h"
#include "ngspice/cpdefs.h"
#include "ngspice/tskdefs.h"
#include "ngspice/cktdefs.h"   /* Enhancement-349: for CKTisSetup */

/* Enhancement-349: resolve a node NAMED BY AN ANALYSIS CARD.
 *
 * INPtermInsert() is create-or-find. That is right for a device card, where
 * the device DEFINES its nodes, but wrong for ".tf v(out) v1" and friends,
 * where the node has to exist already: a mistyped name quietly became a brand
 * new node, and the analysis then reported it as a perfectly good 0 V.
 *
 * From the .control section it was worse than wrong. By then CKTsetup() has
 * run and snapshotted the node list, and the matrix has been sized; the extra
 * node makes the tail check at the end of CKTunsetup() fail, and that calls
 * controlled_exit(EXIT_FAILURE). A single typo killed the process and took
 * every loaded circuit and plot with it.
 *
 * Deck order still has to work -- a .tf card may sit ahead of the devices that
 * define its nodes -- so creating is left alone while the circuit is not yet
 * set up. Once it is, deck parsing is over and an unknown name is a typo.
 *
 * Enhancement-426: CKTisSetup was the wrong proxy for "deck parsing is over".
 * It is false for the FIRST analysis of a .control session -- nothing has run,
 * so CKTsetup() has not run either -- and the typo was still invented as a
 * node there. `tf v(nosuch) v1` as the first command returned a confident
 * transfer_function of 0, `tf v(a,nosuch) v1` returned exactly 1.0, `sens
 * v(nosuch)` printed every sensitivity as -0.0 and `noise v(nosuch) ...`
 * reported onoise_total = 0. The same typo after any `op` was diagnosed
 * correctly, which is what hid this.
 *
 * A card synthesised by if_run() is by construction NOT deck parsing, whatever
 * CKTsetup() has or has not done, so that path now says so explicitly. */
int INPanalysisCardFromCommand = 0;

static int
inp_analysis_node(void *ckt, char **token, INPtables *tab, CKTnode **node)
{
    CKTcircuit *c = (CKTcircuit *) ckt;

    if (INPtermSearch(c, token, tab, node) == E_EXISTS)
        return OK;                        /* the ordinary case: a real node */
    if (INPanalysisCardFromCommand)
        return E_NOTFOUND;                /* typed at a command -- a typo */
    if (c && c->CKTisSetup)
        return E_NOTFOUND;                /* deck parsing is over -- a typo */
    INPtermInsert(c, token, tab, node);   /* card ahead of its own devices */
    /* Enhancement-429: this node was INVENTED by an analysis card. That is
     * legitimate while the deck is still being read -- a `.tf` card may sit
     * ahead of the devices that define its nodes -- but nothing has actually
     * referenced it yet. Clear the mark that INPtermInsert just set; a later
     * device card naming the same node sets it again. Whatever is still
     * unmarked once the deck is parsed was named by an analysis card and by
     * nothing else, and the analysis would report it as a perfectly good 0 V.
     * See CKTnodePhantom(). */
    if (node && *node)
        (*node)->devRef = 0;
    return OK;
}

/* Enhancement-429: did an analysis card invent this node and nothing else ever
 * refer to it? Ground (node 0) is never phantom. */
int
CKTnodePhantom(CKTnode *node)
{
    return node && node->number != 0 && !node->devRef;
}


/* Enhancement-492: a node named only in a device's CONTROL position.
 *
 * `E`, `G` and `S` take a controlling node PAIR. Those two names were bound the
 * same way the output pair is -- INPtermInsert, which CREATES the node -- so a
 * typo simply invented a node and the run continued against it. For `E` and `G`
 * the invented node has no path to ground, the matrix goes singular, and the
 * user is told "singular matrix: check node <typo>": a node they never wrote,
 * reported as a fault in their circuit. `S` is worse, because a switch only
 * READS its control voltage to decide open/closed and stamps nothing for it --
 * the matrix stays non-singular, the solve succeeds, and the answer is silently
 * wrong. Measured: `S1 a b nosuch 0 sw` with the switch's control at 1 V left it
 * OPEN, giving v(b) = 9.99999e-07 where the correct answer is 0.999001.
 *
 * Every other route already answers this question. `.ic` and `.nodeset` report
 * "IC on non-existent node - %s, ignored"; `F`, `H`, `W` and a B-source's `i()`
 * all report "unknown controlling source"; and every output construct names a
 * vector that does not exist. Only the controlling-node pair skipped it.
 *
 * The mechanism is Enhancement-429's, unchanged: a control reference does not
 * make a node real, so it does not set `devRef`, and whatever is still unmarked
 * once the deck is parsed was named in a control position and nowhere else.
 * Marking is left to INPtermInsert for every other position, so a control node
 * that IS connected somewhere -- including one that is the source's own output,
 * `E1 out 0 out 0 2` -- stays marked and is never reported.
 *
 * The check runs in pass 3 for the same reason `.ic`'s does: only once every
 * device card has been read is "did anything connect to this?" answerable. */

struct ctrlref {
    struct ctrlref *next;
    char *inst;                 /* owned */
    char *nodename;             /* owned */
    CKTnode *node;              /* not owned */
};

static struct ctrlref *ctrlrefs;

void INPnoteCtrlNode(const char *inst, const char *nodename, CKTnode *node)
{
    struct ctrlref *r;

    if (!node || node->number == 0)     /* ground is never a typo */
        return;
    r = TMALLOC(struct ctrlref, 1);
    if (!r)
        return;
    r->inst = copy(inst ? inst : "?");
    r->nodename = copy(nodename ? nodename : "?");
    r->node = node;
    r->next = ctrlrefs;
    ctrlrefs = r;
}


int INPreportCtrlNodes(void)
{
    struct ctrlref *r, *nx;
    int bad = 0;

    for (r = ctrlrefs; r; r = nx) {
        nx = r->next;
        if (CKTnodePhantom(r->node)) {
            fprintf(stderr,
                    "\nError: instance %s: the controlling node '%s' does not "
                    "exist -- no device\n       connects to it, so nothing ever "
                    "drives it. This is a typo, not a\n       circuit: reading it "
                    "yields 0 V, which for a switch means permanently\n       open "
                    "and for a controlled source means a singular matrix reported "
                    "against\n       a node you never wrote.\n\n",
                    r->inst, r->nodename);
            bad++;
        }
        tfree(r->inst);
        tfree(r->nodename);
        tfree(r);
    }
    ctrlrefs = NULL;
    return bad;
}

/* Enhancement-426: does a numeric value actually appear next on the card?
 *
 * The tests this replaces were written as
 *     (*line != '.' && !isdigit(*line)) || (*line == '.' && !isdigit(line[1]))
 * which has no notion of a sign, so a value that WAS written down but was
 * negative -- `.ac dec 10 -1k 100k` -- was classified as MISSING and quietly
 * replaced by a default. That is the one reading under which the substitution
 * looks reasonable, and it is why a negative start frequency was never
 * reported. A leading '+' or '-' is part of the number. */
static int
inp_value_present(const char *s)
{
    while (*s == ' ' || *s == '\t')
        s++;
    if (*s == '+' || *s == '-')
        s++;
    if (isdigit_c(*s))
        return 1;
    return (*s == '.' && isdigit_c(s[1]));
}

/* Report an analysis card that names a node which does not exist, and abandon
 * the card. `nm` is still owned here -- nothing took it into the symbol
 * table -- so it is released along the way. */
#define ANALYSIS_NODE(nm, nd)                                           \
    do {                                                                \
        if (inp_analysis_node(ckt, &(nm), tab, &(nd)) != OK) {          \
            char *emsg_ = tprintf("no such node: %s\n", (nm));          \
            LITERR(emsg_);                                              \
            tfree(emsg_);                                               \
            tfree(nm);                                                  \
            return (0);                                                 \
        }                                                               \
    } while(0)

/* Enhancement-485: one frequency-sweep validator for the cards that were not
 * getting one.
 *
 * `.ac` (dot_ac) checks its number of points and its frequency range and names
 * whichever is wrong -- Enhancement-426's work. `.sp` and `.noise` do the same
 * from their own analysis code. `.disto` and `.sens ... ac` take the SAME
 * `<type> <points> <fstart> <fstop>` arguments and neither checked anything:
 *
 *   sens v(out) ac dec 0 1 1k     accepted in silence, four rows of output
 *   sens v(out) ac dec 10 1meg 1  accepted in silence, and then swept a
 *                                 FABRICATED decade 1e6 -> 1e7 ASCENDING,
 *                                 nothing like the range the deck asked for
 *   disto dec 0 1 1k              refused, but reporting "no such parameter on
 *   disto dec 10 1k 1             this device or parameter is missing" -- a
 *                                 DEVICE fault it does not have, and the same
 *                                 text for both faults
 *
 * `which` names the card so the message says which one is wrong. Returns 0 when
 * the arguments are usable and -1 when the caller should abandon the card; the
 * message is already emitted in that case. */
static int
inp_sweep_args_ok(struct card *current, const char *card,
                  int numsteps, double fstart, double fstop)
{
    char msg[128];

    if (numsteps < 1) {
        snprintf(msg, sizeof msg,
                 "%s number of points is invalid, must be greater than zero.\n", card);
        LITERR(msg);
        return -1;
    }
    if (fstart < 0.0) {
        snprintf(msg, sizeof msg,
                 "%s start frequency is invalid, must not be negative.\n", card);
        LITERR(msg);
        return -1;
    }
    if (fstop < fstart) {
        snprintf(msg, sizeof msg,
                 "%s stop frequency is invalid, must not be less than the start "
                 "frequency.\n", card);
        LITERR(msg);
        return -1;
    }
    return 0;
}


static int
dot_noise(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
          TSKtask *task, CKTnode *gnode, JOB *foo)
{
    int which;			/* which analysis we are performing */
    int error;			/* error code temporary */
    char *name;			/* the resistor's name */
    char *nname1;		/* the first node's name */
    char *nname2;		/* the second node's name */
    CKTnode *node1;		/* the first node's node pointer */
    CKTnode *node2;		/* the second node's node pointer */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    char *steptype;		/* ac analysis, type of stepping function */

    int found;
    char *point;

    /* .noise V(OUTPUT,REF) SRC {DEC OCT LIN} NP FSTART FSTOP <PTSPRSUM> */
    which = ft_find_analysis("NOISE");
    if (which == -1) {
        LITERR("Noise analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Noise Analysis", &foo, task));
    INPgetTok(&line, &name, 1);

    /* Make sure the ".noise" command is followed by V(xxxx).  If it
       is, extract 'xxxx'.  If not, report an error. */

    if (name != NULL) {

        if ((*name == 'V' || *name == 'v') && !name[1]) {

            INPgetNetTok(&line, &nname1, 0);
            ANALYSIS_NODE(nname1, node1);
            ptemp.nValue = node1;
            GCA(INPapName, (ckt, which, foo, "output", &ptemp));

            if (*line != ')') {
                INPgetNetTok(&line, &nname2, 1);
                ANALYSIS_NODE(nname2, node2);
                ptemp.nValue = node2;
            } else {
                ptemp.nValue = gnode;
            }
            GCA(INPapName, (ckt, which, foo, "outputref", &ptemp));

            tfree(name);
            INPgetTok(&line, &name, 1);
            INPinsert(&name, tab);
            ptemp.uValue = name;
            GCA(INPapName, (ckt, which, foo, "input", &ptemp));

            INPgetTok(&line, &steptype, 1);
            ptemp.iValue = 1;
            error = INPapName(ckt, which, foo, steptype, &ptemp);
            tfree(steptype);
            if (error)
                current->error = INPerrCat(current->error, INPerror(error));
            parm = INPgetValue(ckt, &line, IF_INTEGER, tab);
            error = INPapName(ckt, which, foo, "numsteps", parm);
            if (error)
                current->error = INPerrCat(current->error, INPerror(error));
            parm = INPgetValue(ckt, &line, IF_REAL, tab);
            error = INPapName(ckt, which, foo, "start", parm);
            if (error)
                current->error = INPerrCat(current->error, INPerror(error));
            parm = INPgetValue(ckt, &line, IF_REAL, tab);
            error = INPapName(ckt, which, foo, "stop", parm);
            if (error)
                current->error = INPerrCat(current->error, INPerror(error));

            /* now see if "ptspersum" has been specified by the user */

            for (found = 0, point = line; (!found) && (*point != '\0'); found = ((*point != ' ') && (*(point++) != '\t')))
                ;
            if (found) {
                parm = INPgetValue(ckt, &line, IF_INTEGER, tab);
                error = INPapName(ckt, which, foo, "ptspersum", parm);
                if (error)
                    current->error = INPerrCat(current->error, INPerror(error));
            } else {
                ptemp.iValue = 0;
                error = INPapName(ckt, which, foo, "ptspersum", &ptemp);
                if (error)
                    current->error = INPerrCat(current->error, INPerror(error));
            }
        } else
            LITERR("bad syntax "
                   "[.noise v(OUT) SRC {DEC OCT LIN} "
                   "NP FSTART FSTOP <PTSPRSUM>]\n");
    } else {
        LITERR("bad syntax "
               "[.noise v(OUT) SRC {DEC OCT LIN} "
               "NP FSTART FSTOP <PTSPRSUM>]\n");
    }
    return 0;
}


static int
dot_op(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
       TSKtask *task, CKTnode *gnode, JOB *foo)
{
    int which;			/* which analysis we are performing */
    int error;			/* error code temporary */

    NG_IGNORE(line);
    NG_IGNORE(tab);
    NG_IGNORE(gnode);

    /* .op */
    which = ft_find_analysis("OP");
    if (which == -1) {
        LITERR("DC operating point analysis unsupported\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Operating Point", &foo, task));
    return (0);
}


static int
dot_disto(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
          TSKtask *task, CKTnode *gnode, JOB *foo)
{
    int which;			/* which analysis we are performing */
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    char *steptype;		/* ac analysis, type of stepping function */

    NG_IGNORE(gnode);

    /* .disto {DEC OCT LIN} NP FSTART FSTOP <F2OVERF1> */
    which = ft_find_analysis("DISTO");
    if (which == -1) {
        LITERR("Small signal distortion analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Distortion Analysis", &foo, task));
    INPgetTok(&line, &steptype, 1);	/* get DEC, OCT, or LIN */
    ptemp.iValue = 1;
    GCA(INPapName, (ckt, which, foo, steptype, &ptemp));
    /* Enhancement-485: read all three, then validate together, so the message
       names the offending argument instead of the analysis reporting a device
       fault it does not have. */
    {
        int e485_np;
        double e485_start, e485_stop;

        parm = INPgetValue(ckt, &line, IF_INTEGER, tab);	/* number of points */
        e485_np = parm->iValue;
        GCA(INPapName, (ckt, which, foo, "numsteps", parm));
        parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* fstart */
        e485_start = parm->rValue;
        GCA(INPapName, (ckt, which, foo, "start", parm));
        parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* fstop */
        e485_stop = parm->rValue;
        GCA(INPapName, (ckt, which, foo, "stop", parm));
        if (inp_sweep_args_ok(current, "DISTO", e485_np, e485_start, e485_stop) != 0)
            return (0);
    }
    if (*line) {
        parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* f1phase */
        GCA(INPapName, (ckt, which, foo, "f2overf1", parm));
    }
    return (0);
}


static int
dot_ac(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
       TSKtask *task, CKTnode *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    int which;			/* which analysis we are performing */
    char *steptype;		/* ac analysis, type of stepping function */
    bool pdef = FALSE;  /* issue a warning if default parameters are used */
    bool missing = FALSE; /* Enhancement-426: this value was not written down */
    char* mline = line; /* for debug printout */
    double startval, stopval;

    NG_IGNORE(gnode);

    /* .ac {DEC OCT LIN} NP FSTART FSTOP */
    which = ft_find_analysis("AC");
    if (which == -1) {
        LITERR("AC small signal analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "AC Analysis", &foo, task));
    INPgetTok(&line, &steptype, 1);	/* get DEC, OCT, or LIN */
    if (!*steptype || (!ciprefix("dec", steptype) && !ciprefix("oct", steptype) && !ciprefix("lin", steptype))) {
        LITERR("Missing DEC, OCT, or LIN.\n");
        return (0);
    }
    ptemp.iValue = 1;
    GCA(INPapName, (ckt, which, foo, steptype, &ptemp));
    tfree(steptype);

    /* Enhancement-426: a value that is present but out of range used to be
     * REPLACED by a default, so ngspice ran a different sweep than the one
     * asked for and said only "assumes default parameter(s)". `ac dec 10 100k
     * 1k` silently became 1e5..1e8 (31 points), `ac dec 10 -1k 100k` became
     * 1..1e5 (51 points). .tran diagnoses each of its bad values by name, and
     * this card already does so for one case ("AC startfreq <= 0"), so the
     * remaining three are errors now too.
     *
     * A value that is MISSING is a different matter and still defaults: that
     * is the documented convenience for a truncated card, and pdef below
     * still reports it -- now naming what was supplied. */
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab); /* number of points */
    if (parm->iValue < 1) {
        LITERR("AC number of points is invalid, must be greater than zero.\n");
        return (0);
    }
    GCA(INPapName, (ckt, which, foo, "numsteps", parm));

    /* `missing` is per value: a truncated card still defaults, a value that is
     * WRITTEN DOWN and out of range is an error. */
    missing = !inp_value_present(line);
    parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* fstart */
    startval = parm->rValue;
    if (startval < 0) {
        if (!missing) {
            LITERR("AC start frequency is invalid, must not be negative.\n");
            return (0);
        }
        startval = parm->rValue = 1.;
    }
    GCA(INPapName, (ckt, which, foo, "start", parm));
    pdef = missing;

    missing = !inp_value_present(line);
    parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* fstop */
    stopval = parm->rValue;
    if (stopval < startval) {
        if (!missing) {
            LITERR("AC stop frequency is invalid, must not be less than the start frequency.\n");
            return (0);
        }
        parm->rValue = 1000. * startval;
    }
    GCA(INPapName, (ckt, which, foo, "stop", parm));
    pdef = pdef || missing;

    if (pdef) {
        fprintf(stderr, "Warning, ngspice assumes default parameter(s) for ac simulation\n");
        fprintf(stderr, "    Check your input line '.ac %s'\n\n", mline);
    }
    /* Enhancement-446: a surplus argument used to be dropped in silence -- any
       number of them, numeric or not, gave byte-identical output. `.tran` and
       `.dc` both refuse what they cannot use, so this card does now too. */
    while (*line == ' ' || *line == '\t')
        line++;
    if (*line) {
        LITERR("AC takes {dec|oct|lin} <points> <fstart> <fstop>; "
               "surplus arguments given.\n");
        return (0);
    }
    return (0);
}

static int
dot_pz(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
       TSKtask *task, CKTnode *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    int which;			/* which analysis we are performing */
    char *steptype;		/* ac analysis, type of stepping function */
    char *nname;		/* a node name as written on the card */
    CKTnode *nnode;		/* the node it resolves to */
    int i;

    /* the four node parameters, in the order .pz names them */
    static char * const pz_nodes[] = {"nodei", "nodeg", "nodej", "nodek"};

    NG_IGNORE(gnode);

    /* .pz nodeI nodeG nodeJ nodeK {V I} {POL ZER PZ} */
    which = ft_find_analysis("PZ");
    if (which == -1) {
        LITERR("Pole-zero analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Pole-Zero Analysis", &foo, task));
    /* Enhancement-349: these were read through INPgetValue(IF_NODE), which
     * resolves the name with INPtermInsert() and so invented a node for any
     * name that did not exist. Resolve them the same way every other analysis
     * card now does, so a typo is reported instead of created. */
    for (i = 0; i < 4; i++) {
        INPgetNetTok(&line, &nname, 1);
        ANALYSIS_NODE(nname, nnode);
        ptemp.nValue = nnode;
        GCA(INPapName, (ckt, which, foo, pz_nodes[i], &ptemp));
    }
    INPgetTok(&line, &steptype, 1);	/* get V or I */
    ptemp.iValue = 1;
    GCA(INPapName, (ckt, which, foo, steptype, &ptemp));
    INPgetTok(&line, &steptype, 1);	/* get POL, ZER, or PZ */
    ptemp.iValue = 1;
    GCA(INPapName, (ckt, which, foo, steptype, &ptemp));
    return (0);
}


/* Enhancement-534: read one .dc sweep specification -- either the classic
 * `start stop step` triple or the keyword form `lin|dec|oct N start stop`
 * the `sweep` command established. Returns 0 on success, 1 on bad syntax.
 * `lvl` is 0 or 1, selecting the start1/start2 parameter family. */
/* Enhancement-534: read a sweep-variable NAME. The wildcard spellings the
 * sweep/altermod family established (`@*[p]`, `@#*[p]`, `@*[[p]]`,
 * `@*:leaf[p]`) cannot pass through INPgetTok -- its token grammar breaks at
 * '*' (and '+', '-', '/', '^'), which is right for expressions and wrong for
 * these names. An '@'-led name is therefore read to the next whitespace,
 * verbatim; everything else keeps the classic tokenizer, so no legacy
 * spelling changes by a byte. */
static void
dot_dc_name(char **line, char **name)
{
    char *p = *line, *q;

    while (*p == ' ' || *p == '\t' || *p == '\r')
        p++;
    if (*p != '@') {
        INPgetTok(line, name, 1);
        return;
    }
    q = p;
    while (*q && *q != ' ' && *q != '\t' && *q != '\r')
        q++;
    *name = copy_substring(p, q);
    while (*q == ' ' || *q == '\t' || *q == '\r')
        q++;
    *line = q;
}

static int
dot_dc_spec(char *(*linep), CKTcircuit *ckt, INPtables *tab, JOB *foo,
            int which, int lvl, struct card *current)
{
    IFvalue ptemp;
    IFvalue *parm;
    int error;                  /* consumed by GCA */
    char *line = *linep;
    char *peek = line;
    char *kw = NULL;
    int mode = -1;
    static char nm_start[2][8] = { "start1", "start2" };
    static char nm_stop[2][8]  = { "stop1",  "stop2"  };
    static char nm_step[2][8]  = { "step1",  "step2"  };
    static char nm_scale[2][8] = { "scale1", "scale2" };
    static char nm_npts[2][8]  = { "npts1",  "npts2"  };

    if (*line == '\0')
        return 1;
    INPgetTok(&peek, &kw, 1);
    if (kw && cieq(kw, "lin"))
        mode = 1;
    else if (kw && cieq(kw, "dec"))
        mode = 2;
    else if (kw && cieq(kw, "oct"))
        mode = 3;

    if (mode > 0) {
        double dn;
        line = peek;            /* consume the keyword */
        if (*line == '\0')
            return 1;
        parm = INPgetValue(ckt, &line, IF_REAL, tab);   /* N */
        dn = parm->rValue;
        /* mirror the sweep command's checks exactly (Enhancement-478): a
         * whole, positive count, read as a number so `2e2` is 200 not 2 */
        if (dn != floor(dn) || dn < 1.0 || dn > 100000.0) {
            fprintf(stderr,
                    "Error: .dc %s needs a whole number of points between 1 "
                    "and 100000 (got %g)\n",
                    mode == 1 ? "lin" : mode == 2 ? "dec" : "oct", dn);
            return 1;
        }
        ptemp.iValue = mode;
        GCA(INPapName, (ckt, which, foo, nm_scale[lvl], &ptemp));
        ptemp.iValue = (int) dn;
        GCA(INPapName, (ckt, which, foo, nm_npts[lvl], &ptemp));
        if (*line == '\0')
            return 1;
        parm = INPgetValue(ckt, &line, IF_REAL, tab);   /* start */
        GCA(INPapName, (ckt, which, foo, nm_start[lvl], parm));
        if (*line == '\0')
            return 1;
        parm = INPgetValue(ckt, &line, IF_REAL, tab);   /* stop */
        GCA(INPapName, (ckt, which, foo, nm_stop[lvl], parm));
        /* a nonzero step placates the zero-step refusals; the counted walk
         * never reads it as an increment */
        ptemp.rValue = 1.0;
        GCA(INPapName, (ckt, which, foo, nm_step[lvl], &ptemp));
        *linep = line;
        return 0;
    }

    /* classic triple */
    parm = INPgetValue(ckt, &line, IF_REAL, tab);       /* vstart */
    GCA(INPapName, (ckt, which, foo, nm_start[lvl], parm));
    if (*line == '\0')
        return 1;
    parm = INPgetValue(ckt, &line, IF_REAL, tab);       /* vstop */
    GCA(INPapName, (ckt, which, foo, nm_stop[lvl], parm));
    if (*line == '\0')
        return 1;
    parm = INPgetValue(ckt, &line, IF_REAL, tab);       /* vinc */
    if (parm->rValue == 0)
        return 1;
    GCA(INPapName, (ckt, which, foo, nm_step[lvl], parm));
    *linep = line;
    return 0;
}

static int
dot_dc(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
       TSKtask *task, CKTnode *gnode, JOB *foo)
{
    char *name;			/* the resistor's name */
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    int which;			/* which analysis we are performing */

    NG_IGNORE(gnode);

    /* .dc SRC1NAME <spec1> [SRC2NAME <spec2>], where a spec is either the
       classic `Vstart Vstop Vinc` or `lin|dec|oct N start stop` (E-534).
       Return 1 upon error because of bad syntax (missing tokens).*/
    which = ft_find_analysis("DC");
    if (which == -1) {
        LITERR("DC transfer curve analysis unsupported\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "DC transfer characteristic", &foo, task));
    dot_dc_name(&line, &name);
    if (*name == '\0')
        return 1;
    INPinsert(&name, tab);
    ptemp.uValue = name;
    GCA(INPapName, (ckt, which, foo, "name1", &ptemp));
    if (dot_dc_spec(&line, ckt, tab, foo, which, 0, current))
        return 1;
    if (*line) {
        dot_dc_name(&line, &name);
        if (*line == '\0')
            return 1;
        INPinsert(&name, tab);
        ptemp.uValue = name;
        GCA(INPapName, (ckt, which, foo, "name2", &ptemp));
        if (dot_dc_spec(&line, ckt, tab, foo, which, 1, current))
            return 1;
    }
    /* Enhancement-446: `.dc` nests at most two sources. A third specification
       used to be neither run nor refused -- the analysis produced the 2-D grid
       and left the third variable pinned at its DC value, with nothing printed.
       A user writing a 3-D corner sweep got a 2-D result that looked complete. */
    while (*line == ' ' || *line == '\t')
        line++;
    if (*line) {
        fprintf(stderr,
                "\nError: .dc sweeps at most two sources, but more were given:\n"
                "       \"%s\" is left over.\n"
                "       Nest the extra sweep outside .dc (for example with the "
                "`sweep` command).\n\n", line);
        return 1;
    }
    return 0;
}


static int
dot_tf(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
       TSKtask *task, CKTnode *gnode, JOB *foo)
{
    char *name;			/* the resistor's name */
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    int which;			/* which analysis we are performing */
    char *nname1;		/* the first node's name */
    char *nname2;		/* the second node's name */
    CKTnode *node1;		/* the first node's node pointer */
    CKTnode *node2;		/* the second node's node pointer */

    /* .tf v( node1, node2 ) src */
    /* .tf vsrc2             src */
    which = ft_find_analysis("TF");
    if (which == -1) {
        LITERR("Transfer Function analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Transfer Function", &foo, task));
    INPgetTok(&line, &name, 0);
    /* name is now either V or I or a serious error */
    if (*name == 'v' && strlen(name) == 1) {
        if (*line != '(' ) {
            /* error, bad input format */
        }
        INPgetNetTok(&line, &nname1, 0);
        ANALYSIS_NODE(nname1, node1);
        ptemp.nValue = node1;
        GCA(INPapName, (ckt, which, foo, "outpos", &ptemp));
        if (*line != ')') {
            INPgetNetTok(&line, &nname2, 1);
            ANALYSIS_NODE(nname2, node2);
            ptemp.nValue = node2;
            GCA(INPapName, (ckt, which, foo, "outneg", &ptemp));
            ptemp.sValue = tprintf("V(%s,%s)", nname1, nname2);
            GCA(INPapName, (ckt, which, foo, "outname", &ptemp));
        } else {
            ptemp.nValue = gnode;
            GCA(INPapName, (ckt, which, foo, "outneg", &ptemp));
            ptemp.sValue = tprintf("V(%s)", nname1);
            GCA(INPapName, (ckt, which, foo, "outname", &ptemp));
        }
    } else if (*name == 'i' && strlen(name) == 1) {
        INPgetTok(&line, &name, 1);
        INPinsert(&name, tab);
        ptemp.uValue = name;
        GCA(INPapName, (ckt, which, foo, "outsrc", &ptemp));
    } else {
        LITERR("Syntax error: voltage or current expected.\n");
        return 0;
    }
    INPgetTok(&line, &name, 1);
    INPinsert(&name, tab);
    ptemp.uValue = name;
    GCA(INPapName, (ckt, which, foo, "insrc", &ptemp));
    return (0);
}


static int
dot_tran(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
         TSKtask *task, CKTnode *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    int which;			/* which analysis we are performing */
    double dtemp;		/* random double precision temporary */
    char *word;			/* something to stick a word of input into */

    NG_IGNORE(gnode);

    /* .tran Tstep Tstop <Tstart <Tmax> > <UIC> */
    which = ft_find_analysis("TRAN");
    if (which == -1) {
        LITERR("Transient analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Transient Analysis", &foo, task));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* Tstep */
    GCA(INPapName, (ckt, which, foo, "tstep", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* Tstop */
    GCA(INPapName, (ckt, which, foo, "tstop", parm));
    if (*line) {
        dtemp = INPevaluate(&line, &error, 1);	/* tstart? */
        if (error == 0) {
            ptemp.rValue = dtemp;
            GCA(INPapName, (ckt, which, foo, "tstart", &ptemp));
            dtemp = INPevaluate(&line, &error, 1);	/* tmax? */
            if (error == 0) {
                ptemp.rValue = dtemp;
                GCA(INPapName, (ckt, which, foo, "tmax", &ptemp));
            }
        }
    }
    if (*line) {
        INPgetTok(&line, &word, 1);	/* uic? */
        if (strcmp(word, "uic") == 0) {
            ptemp.iValue = 1;
            GCA(INPapName, (ckt, which, foo, "uic", &ptemp));
        } else {
            LITERR(" Error: unknown parameter on .tran - ignored\n");
        }
        tfree(word);
    }
    return (0);
}


static int
dot_sens(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
         TSKtask *task, CKTnode *gnode, JOB *foo)
{
    char *name;			/* the resistor's name */
    int error;			/* error code temporary */
    int filters, fidx;          /* Filter allocation and index. */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    int which;			/* which analysis we are performing */
    char *nname1;		/* the first node's name */
    char *nname2;		/* the second node's name */
    CKTnode *node1;		/* the first node's node pointer */
    CKTnode *node2;		/* the second node's node pointer */
    char *steptype;		/* ac analysis, type of stepping function */
    char *cp;                   /* Scan for filters. */

    extern char **Sens_filter;  /* cktsens.c */

    which = ft_find_analysis("SENS");
    if (which == -1) {
        LITERR("Sensitivity unsupported.\n");
        return (0);
    }

    IFC(newAnalysis, (ckt, which, "Sensitivity Analysis", &foo, task));

    /* Format is:
     *      .sens <output> [<filter strings>]
     *      + [ac [dec|lin|oct] <pts> <low freq> <high freq> | dc ]
     */

    /* Get the output voltage or current */
    INPgetTok(&line, &name, 0);
    /* name is now either V or I or a serious error */
    if (*name == 'v' && strlen(name) == 1) {
        if (*line != '(') {
            LITERR("Syntax error: '(' expected after 'v'\n");
            return 0;
        }
        INPgetNetTok(&line, &nname1, 0);
        ANALYSIS_NODE(nname1, node1);
        ptemp.nValue = node1;
        GCA(INPapName, (ckt, which, foo, "outpos", &ptemp));

        if (*line != ')') {
            INPgetNetTok(&line, &nname2, 1);
            ANALYSIS_NODE(nname2, node2);
            ptemp.nValue = node2;
            GCA(INPapName, (ckt, which, foo, "outneg", &ptemp));
            ptemp.sValue = tprintf("V(%s,%s)", nname1, nname2);
            GCA(INPapName, (ckt, which, foo, "outname", &ptemp));
        } else {
            ptemp.nValue = gnode;
            GCA(INPapName, (ckt, which, foo, "outneg", &ptemp));
            ptemp.sValue = tprintf("V(%s)", nname1);
            GCA(INPapName, (ckt, which, foo, "outname", &ptemp));
        }
    } else if (*name == 'i' && strlen(name) == 1) {
        INPgetTok(&line, &name, 1);
        INPinsert(&name, tab);
        ptemp.uValue = name;
        GCA(INPapName, (ckt, which, foo, "outsrc", &ptemp));
    } else {
        LITERR("Syntax error: voltage or current expected.\n");
        return 0;
    }

    /* Scan for filters for the parameter names to be varied.
     * INPgetTok() breaks on '*' so scan by hand.
     */

    if (Sens_filter)
        FREE(Sens_filter);
    fidx = 0;
    filters = -1; // Ensure room for NULL.
    name = NULL;
    while (*line && *line > ' ')
            ++line;
    for (;;) {
        int l;

        while (*line && *line <= ' ')
            ++line;
        if (!*line)
            break;
        cp = line;
        while (*cp && *cp > ' ')
            ++cp;
        l = (int)(cp - line);
        name = TMALLOC(char, l + 1);
        strncpy(name, line, l);
        name[l] = 0;
        line = cp;
        if (!strcmp(name, "ac") || !strcmp(name, "dc"))
            break;
        if (fidx >= filters)
            Sens_filter = TREALLOC(char *, Sens_filter, filters + 8);
        filters += 8;
        Sens_filter[fidx++] = name;
        name = NULL;
    }
    if (Sens_filter) {
        Sens_filter[fidx] = NULL;
    }

    if (name && !strcmp(name, "ac")) {
        /* Enhancement-485: these three went straight to INPapName unchecked,
           while `.ac` -- in this same file -- rejects both a non-positive point
           count and a reversed range by name. `sens v(out) ac dec 0 1 1k` was
           accepted silently, and `sens v(out) ac dec 10 1meg 1` silently swept
           1e6 -> 1e7 ASCENDING, a decade the deck never asked for. */
        int e485_np;
        double e485_start, e485_stop;

        INPgetTok(&line, &steptype, 1);	/* get DEC, OCT, or LIN */
        ptemp.iValue = 1;
        GCA(INPapName, (ckt, which, foo, steptype, &ptemp));
        parm = INPgetValue(ckt, &line, IF_INTEGER, tab); /* number of points */
        e485_np = parm->iValue;
        GCA(INPapName, (ckt, which, foo, "numsteps", parm));
        parm = INPgetValue(ckt, &line, IF_REAL, tab); /* fstart */
        e485_start = parm->rValue;
        GCA(INPapName, (ckt, which, foo, "start", parm));
        parm = INPgetValue(ckt, &line, IF_REAL, tab); /* fstop */
        e485_stop = parm->rValue;
        GCA(INPapName, (ckt, which, foo, "stop", parm));
        if (inp_sweep_args_ok(current, "SENS AC", e485_np, e485_start, e485_stop) != 0)
            return (0);
        return (0);
    } else if (name && *name && strcmp(name, "dc")) {
        /* Bad flag */
        LITERR("Syntax error: 'ac' or 'dc' expected.\n");
    }
    if (name)
        FREE(name);
    return 0;
}


#ifdef WANT_SENSE2
static int
dot_sens2(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
          TSKtask *task, CKTnode *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    int which;			/* which analysis we are performing */
    char *token;		/* a token from the line */

    NG_IGNORE(gnode);

    /* .sens {AC} {DC} {TRAN} [dev=nnn parm=nnn]* */
    which = ft_find_analysis("SENS2");
    if (which == -1) {
        LITERR("Sensitivity-2 analysis unsupported\n");
        return (0);
    }

    IFC(newAnalysis, (ckt, which, "Sensitivity-2 Analysis", &foo, task));

    while (*line) {

        IFparm *if_parm;

        /* read the entire line */
        INPgetTok(&line, &token, 1);

        if_parm = ft_find_analysis_parm(which, token);

        if (!if_parm) {
            /* didn't find it! */
            LITERR(" Error: unknown parameter on .sens-ignored \n");
            continue;
        }

        /* found it, analysis which, parameter i */
        if (if_parm->dataType & IF_FLAG) {

            /* one of the keywords! */
            ptemp.iValue = 1;
            error = ft_sim->setAnalysisParm (ckt, foo,
                                             if_parm->id,
                                             &ptemp,
                                             NULL);
            if (error)
                current->error = INPerrCat(current->error, INPerror(error));

        } else {

            parm = INPgetValue(ckt, &line, if_parm->dataType, tab);
            error = ft_sim->setAnalysisParm (ckt, foo,
                                             if_parm->id,
                                             parm,
                                             NULL);
            if (error)
                current->error = INPerrCat(current->error, INPerror(error));
        }
    }

    return (0);
}
#endif

#ifdef WITH_PSS

/* Enhancement-348: every .pss argument is REQUIRED, but INPgetValue() has no
 * way to report "there was nothing left to read" -- it hands back 0. A card
 * that stopped early therefore reached the analysis with points/harmonics 0,
 * sizing the DFT output arrays to nothing. Check the line here so the user
 * gets the card reported instead of a crash further down. */
#define PSS_NEED_ARG(what)                                              \
    do {                                                                \
        if (*line == '\0') {                                            \
            LITERR("Not enough arguments on .pss: missing " what "\n"); \
            return (0);                                                 \
        }                                                               \
    } while(0)

/*SP: Steady State Analyis */
static int
dot_pss(char *line, void *ckt, INPtables *tab, struct card *current,
        void *task, void *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    char *nname;		/* the oscNode name */
    CKTnode *nnode;		/* the oscNode node */
    int which;			/* which analysis we are performing */
    char *word;			/* something to stick a word of input into */

    NG_IGNORE(gnode);

    /* .pss Fguess StabTime OscNode <UIC>*/
    which = ft_find_analysis("PSS");
    if (which == -1) {
        LITERR("Periodic steady state analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Periodic Steady State Analysis", &foo, task));

    PSS_NEED_ARG("fguess");
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Fguess */
    GCA(INPapName, (ckt, which, foo, "fguess", parm));

    PSS_NEED_ARG("stabtime");
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* StabTime */
    GCA(INPapName, (ckt, which, foo, "stabtime", parm));

    PSS_NEED_ARG("oscnode");
    INPgetNetTok(&line, &nname, 0);
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "oscnode", &ptemp));	/* OscNode given as string */

    PSS_NEED_ARG("points");
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS points */
    GCA(INPapName, (ckt, which, foo, "points", parm));

    PSS_NEED_ARG("harmonics");
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS harmonics */
    GCA(INPapName, (ckt, which, foo, "harmonics", parm));

    PSS_NEED_ARG("sc_iter");
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* SC iterations */
    GCA(INPapName, (ckt, which, foo, "sc_iter", parm));

    PSS_NEED_ARG("steady_coeff");
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Steady coefficient */
    GCA(INPapName, (ckt, which, foo, "steady_coeff", parm));

    if (*line) {
        INPgetTok(&line, &word, 1);	/* uic? */
        if (strcmp(word, "uic") == 0) {
            ptemp.iValue = 1;
            GCA(INPapName, (ckt, which, foo, "uic", &ptemp));
        } else {
            fprintf(stderr,"Error: unknown parameter %s on .pss - ignored\n", word);
        }
    }
    return (0);
}
/* SP */

/* Enhancement-122: Periodic AC (PAC). Runs PSS then sweeps a small-signal input
 * frequency, solving the harmonic conversion matrix at each point. Reuses the PSS
 * analysis (the PAC sweep runs off the retained periodic operating point) with the
 * extra pac_* parameters set. */
static int
dot_pac(char *line, void *ckt, INPtables *tab, struct card *current,
        void *task, void *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    char *nname;		/* the oscNode name */
    CKTnode *nnode;		/* the oscNode node */
    int which;			/* which analysis we are performing */
    char *steptype;		/* pac sweep type: dec/oct/lin */

    NG_IGNORE(gnode);
    NG_IGNORE(current);

    /* .pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff
     *      <DEC|OCT|LIN> NumPts Fstart Fstop */
    which = ft_find_analysis("PSS");
    if (which == -1) {
        LITERR("Periodic AC (PAC) analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Periodic AC Analysis", &foo, task));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Fguess */
    GCA(INPapName, (ckt, which, foo, "fguess", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* StabTime */
    GCA(INPapName, (ckt, which, foo, "stabtime", parm));

    INPgetNetTok(&line, &nname, 0);
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "oscnode", &ptemp));	/* OscNode given as string */

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS points */
    GCA(INPapName, (ckt, which, foo, "points", parm));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS harmonics */
    GCA(INPapName, (ckt, which, foo, "harmonics", parm));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* SC iterations */
    GCA(INPapName, (ckt, which, foo, "sc_iter", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Steady coefficient */
    GCA(INPapName, (ckt, which, foo, "steady_coeff", parm));

    /* PAC sweep tail: <DEC|OCT|LIN> NumPts Fstart Fstop */
    INPgetTok(&line, &steptype, 1);
    ptemp.iValue = (strcmp(steptype, "dec") == 0) ? 1 :
                   (strcmp(steptype, "oct") == 0) ? 2 : 0;	/* default LIN */
    tfree(steptype);
    GCA(INPapName, (ckt, which, foo, "pac_step", &ptemp));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* number of points */
    GCA(INPapName, (ckt, which, foo, "pac_points", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstart */
    GCA(INPapName, (ckt, which, foo, "pac_fstart", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstop */
    GCA(INPapName, (ckt, which, foo, "pac_fstop", parm));

    {   /* optional trailing maxsideband: output conversion sidebands each side */
        char *p = line;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p) {
            parm = INPgetValue(ckt, &line, IF_INTEGER, tab);
            GCA(INPapName, (ckt, which, foo, "pac_maxsb", parm));
        }
    }

    ptemp.iValue = 1;						/* enable the PAC sweep */
    GCA(INPapName, (ckt, which, foo, "pac", &ptemp));

    return (0);
}

/* Enhancement-132: Periodic S-parameters (PSP). Runs PSS then, for each RF port,
 * injects through the harmonic conversion matrix and forms the periodic scattering
 * matrix vs input frequency. Same PSS params + sweep tail as .pac; the excitation is
 * the netlist's RF ports (portnum/z0), so there is no output node. */
static int
dot_psp(char *line, void *ckt, INPtables *tab, struct card *current,
        void *task, void *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    char *nname;		/* the oscNode name */
    CKTnode *nnode;		/* the oscNode node */
    int which;			/* which analysis we are performing */
    char *steptype;		/* psp sweep type: dec/oct/lin */

    NG_IGNORE(gnode);
    NG_IGNORE(current);

    /* .psp Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff
     *      <DEC|OCT|LIN> NumPts Fstart Fstop [maxsideband] */
    which = ft_find_analysis("PSS");
    if (which == -1) {
        LITERR("Periodic S-parameter (PSP) analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Periodic S-parameter Analysis", &foo, task));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Fguess */
    GCA(INPapName, (ckt, which, foo, "fguess", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* StabTime */
    GCA(INPapName, (ckt, which, foo, "stabtime", parm));

    INPgetNetTok(&line, &nname, 0);
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "oscnode", &ptemp));	/* OscNode given as string */

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS points */
    GCA(INPapName, (ckt, which, foo, "points", parm));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS harmonics */
    GCA(INPapName, (ckt, which, foo, "harmonics", parm));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* SC iterations */
    GCA(INPapName, (ckt, which, foo, "sc_iter", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Steady coefficient */
    GCA(INPapName, (ckt, which, foo, "steady_coeff", parm));

    /* PSP sweep tail: <DEC|OCT|LIN> NumPts Fstart Fstop */
    INPgetTok(&line, &steptype, 1);
    ptemp.iValue = (strcmp(steptype, "dec") == 0) ? 1 :
                   (strcmp(steptype, "oct") == 0) ? 2 : 0;	/* default LIN */
    tfree(steptype);
    GCA(INPapName, (ckt, which, foo, "pac_step", &ptemp));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* number of points */
    GCA(INPapName, (ckt, which, foo, "pac_points", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstart */
    GCA(INPapName, (ckt, which, foo, "pac_fstart", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstop */
    GCA(INPapName, (ckt, which, foo, "pac_fstop", parm));

    {   /* optional trailing maxsideband: output conversion sidebands each side */
        char *p = line;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p) {
            parm = INPgetValue(ckt, &line, IF_INTEGER, tab);
            GCA(INPapName, (ckt, which, foo, "pac_maxsb", parm));
        }
    }

    ptemp.iValue = 1;						/* enable the PSP sweep */
    GCA(INPapName, (ckt, which, foo, "psp", &ptemp));

    return (0);
}

/* Enhancement-124: Periodic noise (PNOISE). Runs PSS then folds each device's
 * noise through the conversion-matrix adjoint over all sidebands. Reuses the PSS
 * analysis (like .pac) with the pnoise output node, input source, and sweep set. */
static int
dot_pnoise(char *line, void *ckt, INPtables *tab, struct card *current,
           void *task, void *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    char *nname;		/* a node name */
    char *sname;		/* the input source name */
    CKTnode *nnode;		/* a node pointer */
    int which;			/* which analysis we are performing */
    char *steptype;		/* pnoise sweep type: dec/oct/lin */

    NG_IGNORE(gnode);
    NG_IGNORE(current);

    /* .pnoise Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff
     *         OutNode InSrc <DEC|OCT|LIN> NumPts Fstart Fstop */
    which = ft_find_analysis("PSS");
    if (which == -1) {
        LITERR("Periodic noise (PNOISE) analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Periodic Noise Analysis", &foo, task));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Fguess */
    GCA(INPapName, (ckt, which, foo, "fguess", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* StabTime */
    GCA(INPapName, (ckt, which, foo, "stabtime", parm));
    INPgetNetTok(&line, &nname, 0);				/* OscNode */
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "oscnode", &ptemp));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS points */
    GCA(INPapName, (ckt, which, foo, "points", parm));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS harmonics */
    GCA(INPapName, (ckt, which, foo, "harmonics", parm));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* SC iterations */
    GCA(INPapName, (ckt, which, foo, "sc_iter", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Steady coefficient */
    GCA(INPapName, (ckt, which, foo, "steady_coeff", parm));

    INPgetNetTok(&line, &nname, 0);				/* OutNode */
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "pnoise_out", &ptemp));

    INPgetTok(&line, &sname, 1);				/* InSrc */
    INPinsert(&sname, tab);
    ptemp.uValue = sname;
    GCA(INPapName, (ckt, which, foo, "pnoise_insrc", &ptemp));

    /* sweep tail: <DEC|OCT|LIN> NumPts Fstart Fstop */
    INPgetTok(&line, &steptype, 1);
    ptemp.iValue = (strcmp(steptype, "dec") == 0) ? 1 :
                   (strcmp(steptype, "oct") == 0) ? 2 : 0;
    tfree(steptype);
    GCA(INPapName, (ckt, which, foo, "pac_step", &ptemp));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* number of points */
    GCA(INPapName, (ckt, which, foo, "pac_points", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstart */
    GCA(INPapName, (ckt, which, foo, "pac_fstart", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstop */
    GCA(INPapName, (ckt, which, foo, "pac_fstop", parm));

    {   /* Enhancement-126: optional trailing "cyclo" keyword */
        char *p = line;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p) {
            char *word;
            INPgetTok(&line, &word, 1);
            if (strcmp(word, "cyclo") == 0) {
                ptemp.iValue = 1;
                GCA(INPapName, (ckt, which, foo, "pnoise_cyclo", &ptemp));
            } else {
                fprintf(stderr, "Error: unknown parameter %s on .pnoise - ignored\n", word);
            }
            tfree(word);
        }
    }

    ptemp.iValue = 1;						/* enable the pnoise sweep */
    GCA(INPapName, (ckt, which, foo, "pnoise", &ptemp));

    return (0);
}

/* Enhancement-125: Periodic transfer function (PXF). The adjoint of PAC: runs PSS
 * then solves Hᵀ Ψ = e_{out,0} and dots Ψ with the netlist AC-source pattern to get
 * the transfer from the input to a fixed output at each sideband. Reuses the PSS
 * analysis (like .pac). */
static int
dot_pxf(char *line, void *ckt, INPtables *tab, struct card *current,
        void *task, void *gnode, JOB *foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue *parm;		/* a pointer to a value struct for function returns */
    char *nname;		/* a node name */
    CKTnode *nnode;		/* a node pointer */
    int which;			/* which analysis we are performing */
    char *steptype;		/* pxf sweep type: dec/oct/lin */

    NG_IGNORE(gnode);
    NG_IGNORE(current);

    /* .pxf Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff
     *      OutNode <DEC|OCT|LIN> NumPts Fstart Fstop [maxsideband] */
    which = ft_find_analysis("PSS");
    if (which == -1) {
        LITERR("Periodic transfer-function (PXF) analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Periodic Transfer Function Analysis", &foo, task));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Fguess */
    GCA(INPapName, (ckt, which, foo, "fguess", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* StabTime */
    GCA(INPapName, (ckt, which, foo, "stabtime", parm));
    INPgetNetTok(&line, &nname, 0);				/* OscNode */
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "oscnode", &ptemp));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS points */
    GCA(INPapName, (ckt, which, foo, "points", parm));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS harmonics */
    GCA(INPapName, (ckt, which, foo, "harmonics", parm));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* SC iterations */
    GCA(INPapName, (ckt, which, foo, "sc_iter", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Steady coefficient */
    GCA(INPapName, (ckt, which, foo, "steady_coeff", parm));

    INPgetNetTok(&line, &nname, 0);				/* OutNode */
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "pxf_out", &ptemp));

    /* sweep tail: <DEC|OCT|LIN> NumPts Fstart Fstop [maxsideband] */
    INPgetTok(&line, &steptype, 1);
    ptemp.iValue = (strcmp(steptype, "dec") == 0) ? 1 :
                   (strcmp(steptype, "oct") == 0) ? 2 : 0;
    tfree(steptype);
    GCA(INPapName, (ckt, which, foo, "pac_step", &ptemp));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* number of points */
    GCA(INPapName, (ckt, which, foo, "pac_points", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstart */
    GCA(INPapName, (ckt, which, foo, "pac_fstart", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* fstop */
    GCA(INPapName, (ckt, which, foo, "pac_fstop", parm));

    {   /* optional trailing maxsideband */
        char *p = line;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p) {
            parm = INPgetValue(ckt, &line, IF_INTEGER, tab);
            GCA(INPapName, (ckt, which, foo, "pac_maxsb", parm));
        }
    }

    ptemp.iValue = 1;						/* enable the pxf sweep */
    GCA(INPapName, (ckt, which, foo, "pxf", &ptemp));

    return (0);
}
#endif


#ifdef RFSPICE
/* S-Parameter Analyis */
static int
dot_sp(char* line, void* ckt, INPtables* tab, struct card* current,
    void* task, void* gnode, JOB* foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue* parm;		/* a pointer to a value struct for function returns */
    int which;			/* which analysis we are performing */
    char* steptype;		/* ac analysis, type of stepping function */

    NG_IGNORE(gnode);

    /* .ac {DEC OCT LIN} NP FSTART FSTOP */
    which = ft_find_analysis("SP");
    if (which == -1) {
        LITERR("S-Params analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "SP Analysis", &foo, task));
    INPgetTok(&line, &steptype, 1);	/* get DEC, OCT, or LIN */
    ptemp.iValue = 1;
    GCA(INPapName, (ckt, which, foo, steptype, &ptemp));
    tfree(steptype);
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab); /* number of points */
    GCA(INPapName, (ckt, which, foo, "numsteps", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* fstart */
    GCA(INPapName, (ckt, which, foo, "start", parm));
    parm = INPgetValue(ckt, &line, IF_REAL, tab);	/* fstop */
    GCA(INPapName, (ckt, which, foo, "stop", parm));
    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);	/* fstop */
    GCA(INPapName, (ckt, which, foo, "donoise", parm));
    return (0);
}

#ifdef WITH_HB
/*SP: Steady State Analyis */
static int
dot_hb(char* line, void* ckt, INPtables* tab, struct card* current,
    void* task, void* gnode, JOB* foo)
{
    int error;			/* error code temporary */
    IFvalue ptemp;		/* a value structure to package resistance into */
    IFvalue* parm;		/* a pointer to a value struct for function returns */
    char* nname;		/* the oscNode name */
    CKTnode* nnode;		/* the oscNode node */
    int which;			/* which analysis we are performing */
    char* word;			/* something to stick a word of input into */

    NG_IGNORE(gnode);

    /* .pss Fguess StabTime OscNode <UIC>*/
    which = ft_find_analysis("PSS");
    if (which == -1) {
        LITERR("Periodic steady state analysis unsupported.\n");
        return (0);
    }
    IFC(newAnalysis, (ckt, which, "Harmonic Balance State Analysis", &foo, task));

    parm = INPgetValue(ckt, &line, IF_REALVEC, tab);		/* Fguess */
    GCA(INPapName, (ckt, which, foo, "freq", parm));

    parm = INPgetValue(ckt, &line, IF_INTVEC, tab);		/* StabTime */
    GCA(INPapName, (ckt, which, foo, "harmonics", parm));

    INPgetNetTok(&line, &nname, 0);
    ANALYSIS_NODE(nname, nnode);
    ptemp.nValue = nnode;
    GCA(INPapName, (ckt, which, foo, "oscnode", &ptemp));	/* OscNode given as string */

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS points */
    GCA(INPapName, (ckt, which, foo, "points", parm));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* PSS harmonics */
    GCA(INPapName, (ckt, which, foo, "harmonics", parm));

    parm = INPgetValue(ckt, &line, IF_INTEGER, tab);		/* SC iterations */
    GCA(INPapName, (ckt, which, foo, "sc_iter", parm));

    parm = INPgetValue(ckt, &line, IF_REAL, tab);		/* Steady coefficient */
    GCA(INPapName, (ckt, which, foo, "steady_coeff", parm));

    if (*line) {
        INPgetTok(&line, &word, 1);	/* uic? */
        if (strcmp(word, "uic") == 0) {
            ptemp.iValue = 1;
            GCA(INPapName, (ckt, which, foo, "uic", &ptemp));
        }
        else {
            fprintf(stderr, "Error: unknown parameter %s on .pss - ignored\n", word);
        }
    }
    return (0);
}
#endif

#endif


static int
dot_options(char *line, CKTcircuit *ckt, INPtables *tab, struct card *current,
            TSKtask *task, CKTnode *gnode, JOB *foo)
{
    NG_IGNORE(line);
    NG_IGNORE(gnode);
    NG_IGNORE(foo);

    /* .option - specify program options - rather complicated */
    /* use a subroutine to handle all of them to keep this    */
    /* subroutine managable.                                  */

    INPdoOpts(ckt, &(task->taskOptions), current, tab);
    return (0);
}


int
INP2dot(CKTcircuit *ckt, INPtables *tab, struct card *current, TSKtask *task, CKTnode *gnode)
{

    /* .<something> Many possibilities */
    char *token;		/* a token from the line, tmalloc'ed */
    JOB *foo = NULL;		/* pointer to analysis */
    /* the part of the current line left to parse */
    char *line = current->line;
    int rtn = 0;

    INPgetTok(&line, &token, 1);
    if (strcmp(token, ".model") == 0) {
        /* don't have to do anything, since models were all done in
         * pass 1 */
        goto quit;
    } else if (strcmp(token, ".param") == 0) {
        /* don't have to do anything, since params were all done
         * elsewhere */
        goto quit;
    } else if ((strcmp(token, ".width") == 0) ||
               strcmp(token, ".print") == 0 || strcmp(token, ".plot") == 0) {
        /* obsolete - ignore */
        char* token2 = tprintf(" obsolete dot command '%s' - ignored \n", token);
        LITERR(token2);
        tfree(token2);
        goto quit;
    } else if ((strcmp(token, ".temp") == 0)) {
        /* .temp temp1 temp2 temp3 temp4 ..... */
        /* not yet implemented - warn & ignore */
        /*
        LITERR(" Warning: .TEMP card obsolete - use .options TEMP and TNOM\n");
        */
        goto quit;
    } else if ((strcmp(token, ".op") == 0)) {
        rtn = dot_op(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    } else if ((strcmp(token, ".nodeset") == 0)) {
        goto quit;
    } else if ((strcmp(token, ".disto") == 0)) {
        rtn = dot_disto(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    } else if ((strcmp(token, ".noise") == 0)) {
        rtn = dot_noise(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    } else if ((strcmp(token, ".four") == 0)
               || (strcmp(token, ".fourier") == 0)) {
        /* .four */
        /* not implemented - warn & ignore */
        LITERR("Use fourier command to obtain fourier analysis\n");
        goto quit;
    } else if ((strcmp(token, ".ic") == 0)) {
        goto quit;
    } else if ((strcmp(token, ".ac") == 0)) {
        rtn = dot_ac(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    } else if ((strcmp(token, ".pz") == 0)) {
        rtn = dot_pz(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    } else if ((strcmp(token, ".dc") == 0)) {
        rtn = dot_dc(line, ckt, tab, current, task, gnode, foo);
        if (rtn == 1) {
            current->error = copy("Bad syntax! ");
        }
        goto quit;
    } else if ((strcmp(token, ".tf") == 0)) {
        rtn = dot_tf(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    } else if ((strcmp(token, ".tran") == 0)) {
        rtn = dot_tran(line, ckt, tab, current, task, gnode, foo);
        goto quit;
#ifdef WITH_PSS
        /* SP: Steady State Analysis */
    } else if ((strcmp(token, ".pss") == 0)) {
        rtn = dot_pss(line, ckt, tab, current, task, gnode, foo);
        goto quit;
        /* SP */
        /* Enhancement-122: Periodic AC */
    } else if ((strcmp(token, ".pac") == 0)) {
        rtn = dot_pac(line, ckt, tab, current, task, gnode, foo);
        goto quit;
        /* Enhancement-124: Periodic noise */
    } else if ((strcmp(token, ".pnoise") == 0)) {
        rtn = dot_pnoise(line, ckt, tab, current, task, gnode, foo);
        goto quit;
        /* Enhancement-125: Periodic transfer function */
    } else if ((strcmp(token, ".pxf") == 0)) {
        rtn = dot_pxf(line, ckt, tab, current, task, gnode, foo);
        goto quit;
        /* Enhancement-132: Periodic S-parameters */
    } else if ((strcmp(token, ".psp") == 0)) {
        rtn = dot_psp(line, ckt, tab, current, task, gnode, foo);
        goto quit;
#endif
#ifdef RFSPICE
    }
    else if ((strcmp(token, ".sp") == 0)) {
        rtn = dot_sp(line, ckt, tab, current, task, gnode, foo);
        goto quit;
        /* SP */
#ifdef WITH_HB
    }
    else if ((strcmp(token, ".hb") == 0)) {
        rtn = dot_hb(line, ckt, tab, current, task, gnode, foo);
        goto quit;
        /* SP */
#endif
#endif
    } else if ((strcmp(token, ".subckt") == 0) ||
               (strcmp(token, ".ends") == 0)) {
        /* not yet implemented - warn & ignore */
        LITERR(" Warning: Subcircuits not yet implemented - ignored \n");
        goto quit;
    } else if ((strcmp(token, ".end") == 0)) {
        /* .end - end of input */
        /* not allowed to pay attention to additional input - return */
        rtn = 1;
        goto quit;
    } else if (strcmp(token, ".sens") == 0) {
        rtn = dot_sens(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    }
#ifdef WANT_SENSE2
    else if ((strcmp(token, ".sens2") == 0)) {
        rtn = dot_sens2(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    }
#endif
    else if ((strcmp(token, ".probe") == 0)) {
        /* Maybe generate a "probe" format file in the future. */
        goto quit;
    } else if ((strcmp(token, ".options") == 0)||
               (strcmp(token,".option")==0) ||
               (strcmp(token,".opt")==0)) {
        rtn = dot_options(line, ckt, tab, current, task, gnode, foo);
        goto quit;
    }
    /* Added by H.Tanaka to find .global option */
    else if (strcmp(token, ".global") == 0) {
        rtn = 0;
        LITERR(" Warning: .global not yet implemented - ignored \n");
        goto quit;
    }
    /* ignore .meas statements -- these will be handled after analysis */
    /* also ignore .param statements */
    /* ignore .prot, .unprot */
    else if (strcmp(token, ".meas") == 0 || ciprefix(".para", token) || strcmp(token, ".measure") == 0 ||
             strcmp(token, ".prot") == 0 || strcmp(token, ".unprot") == 0) {
        rtn = 0;
        goto quit;
    }
    char *token2 = tprintf(" unimplemented dot command '%s'\n", token);
    LITERR(token2);
    tfree(token2);
quit:
    tfree(token);
    return rtn;
}
