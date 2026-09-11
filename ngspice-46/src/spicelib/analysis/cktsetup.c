/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

    /* CKTsetup(ckt)
     * this is a driver program to iterate through all the various
     * setup functions provided for the circuit elements in the
     * given circuit
     */

#include "ngspice/ngspice.h"
#include "ngspice/smpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/sperror.h"
#include "ngspice/fteext.h"

#ifdef XSPICE
#include "ngspice/enh.h"
#include "ngspice/osdiitf.h"          /* Enhancement-575 */
#include "../devices/asrc/asrcdefs.h"
#include <ctype.h>
#ifdef XSPICE
#include "ngspice/mif.h"
#include "ngspice/mifdefs.h"
#endif
#endif

#ifdef USE_OMP
#include <omp.h>
#include "ngspice/cpextern.h"
#endif

#define CKALLOC(var,size,type) \
    if(size && ((var = TMALLOC(type, size)) == NULL)){\
            return(E_NOMEM);\
}

/* Enhancement-266: announce the active direct linear solver once, and again
 * only when it changes.  CKTsetup (and CKTpzSetup) run once per analysis, so a
 * command that re-runs the analysis for many points -- `sweep`, Monte Carlo,
 * `optimize`, the pso/de/sa optimizers -- otherwise reprints
 * "Using ... Direct Linear Solver" on every iteration.  The last-announced
 * solver is tracked process-wide (not per-circuit): a `.param` sweep re-sources
 * the deck, rebuilding the circuit each point, so a per-circuit flag would still
 * repeat.  A genuine solver switch (`.option klu` / `.option sparse`) has a
 * different mode and re-announces.  A fresh ngspice process starts un-announced,
 * so batch runs and the dual-solver test harness still print it once. */
void
CKTannounceSolver(int klu)
{
    static int announced = -1;      /* -1 = none yet, 0 = SPARSE, 1 = KLU */
    int mode = klu ? 1 : 0;

    if (announced == mode)
        return;
    announced = mode;
    fprintf(stdout, klu ? "Using KLU as Direct Linear Solver\n"
                        : "Using SPARSE 1.3 as Direct Linear Solver\n");
}

/* ---- Enhancement-575: `.option dcpath` -- gmin installed where a node has no
 * DC path to ground, Spectre's topology check for ngspice ------------------
 *
 * Enhancements 566 and 569 give a node that NOTHING conducts to a diagonal and
 * a warning, but no hold of its own: the gmin-stepping ladder ramps its scalar
 * away before the final solve, so such a node travels the whole ladder to the
 * transient-based operating point, some 277 iterations, and is held there only
 * by the gmin optran runs with -- and not at all in a transient. A node reached
 * only through capacitors is not even seen: its elements exist and are zero at
 * DC, so it surfaces as a singular pivot (Enhancement-570 names it).
 *
 * Spectre decides this before Newton: "No DC path from node <n> to ground, Gmin
 * installed to provide path", and installs gmin there permanently. This does
 * the same. After the device setups have created their elements, the nodes
 * are joined by every DC-conducting device path -- built-in types from a
 * per-type table of DC-connected terminal groups, OSDI models from the
 * resistive flags of their Jacobian pattern, XSPICE code models from their
 * port kinds -- and the graph is walked from ground. Every voltage node the
 * walk does not reach gets a diagonal element and goes on ckt->CKTdcpathNodes;
 * CKTdcpathStamp() adds CKTdcpathG to those diagonals on every load of every
 * analysis (cktload.c, acan.c). A type in no table is taken as fully
 * connected, the conservative reading: nothing is installed there and the run
 * behaves as it did.
 *
 *   .option dcpath=gmin   install the circuit's gmin, and say so   (default)
 *   .option dcpath=<G>    install the conductance G instead
 *   .option dcpath=warn   say so, install nothing -- Enhancement-569's numbers
 *   .option dcpath=error  refuse to run, naming every such node
 *   .option dcpath=off    neither check nor message -- Enhancement-566's run
 *
 * Enhancement-595 -- HOW LONG the hold stays. Held for the whole run
 * (Spectre's rule, E-575's first form) a node reached only through a
 * capacitor leaks with C/gmin in a transient -- 2 pF against 1 pS is a
 * two-second time constant -- and its AC response bends below gmin/C. In a
 * transient the capacitor companion conductance, 2C/h, carries such a node
 * by many orders over gmin, and in AC it sees jwC: the hold is needed only
 * where the matrix is evaluated AT DC -- op, dc, the transient's initial
 * point, the ac's. So a SECOND walk counts the reactive edges too (a
 * capacitor joins its pair, a MOSFET gate its terminals, an OSDI REACT entry
 * its nodes); a node THAT walk reaches is held at DC only, and released in
 * tran and ac. A node it does not reach -- a current source into a lone
 * node, a probed port, an isolated transformer secondary with a capacitor
 * across it -- is held in every mode, as before. A zero-valued reactive
 * element (a parasitic capacitor set to 0, a ddt() with a zero coefficient)
 * would leave a released node with an all-zero row, so the tran stamp holds
 * a released node whose diagonal is still exactly zero after the device
 * loads, and the AC load has Enhancement-571's all-zero-row hold already.
 *
 *   .option dcpath=dc     hold at DC only, release in tran and ac   (default)
 *   .option dcpath=all    hold in every mode, Spectre's rule (E-575's form)
 *   .option dcpathall     the same, as a word of its own: `dcpath=1n dcpathall`
 */
enum { DCPATH_OFF, DCPATH_WARN, DCPATH_HOLD, DCPATH_ERROR };
enum { DCP_ALL, DCP_NONE, DCP_PAIR, DCP_NOGATE, DCP_ASRC };

/* How the terminals of a built-in type are joined at DC. DCP_PAIR joins the
 * first two terminals only -- the output pair of a controlled VOLTAGE source,
 * never its controlling pair; a controlled CURRENT source is a current source
 * at its output and joins nothing, like Isource; DCP_NOGATE joins every
 * terminal except one whose name
 * contains "gate", the MOSFET gate being capacitive at DC unless a gate
 * current model connects it (a JFET or MESFET gate is a junction and stays in
 * DCP_ALL); DCP_ASRC decides per instance from the B-source's type. */
static const struct { const char *name; int how; } dcpath_types[] = {
    { "Resistor", DCP_PAIR }, { "Inductor", DCP_PAIR }, { "Vsource", DCP_PAIR },
    { "VCVS", DCP_PAIR }, { "CCVS", DCP_PAIR },          /* a voltage output is a branch */
    { "Switch", DCP_PAIR }, { "CSwitch", DCP_PAIR },
    { "Capacitor", DCP_NONE }, { "Isource", DCP_NONE }, { "mutual", DCP_NONE },
    { "VCCS", DCP_NONE }, { "CCCS", DCP_NONE },          /* a current output is a current source */
    { "ASRC", DCP_ASRC },
    { "Mos1", DCP_NOGATE }, { "Mos2", DCP_NOGATE }, { "Mos3", DCP_NOGATE },
    { "Mos6", DCP_NOGATE }, { "Mos9", DCP_NOGATE },
    { "BSIM1", DCP_NOGATE }, { "BSIM2", DCP_NOGATE }, { "BSIM3", DCP_NOGATE },
    { "BSIM3v0", DCP_NOGATE }, { "BSIM3v1", DCP_NOGATE }, { "BSIM3v32", DCP_NOGATE },
    { "BSIM4", DCP_NOGATE }, { "BSIM4v5", DCP_NOGATE }, { "BSIM4v6", DCP_NOGATE },
    { "BSIM4v7", DCP_NOGATE }, { "B3SOIDD", DCP_NOGATE }, { "B3SOIFD", DCP_NOGATE },
    { "B3SOIPD", DCP_NOGATE }, { "B4SOI", DCP_NOGATE }, { "HiSIM2", DCP_NOGATE },
    { "HiSIMHV1", DCP_NOGATE }, { "HiSIMHV2", DCP_NOGATE }, { "SOI3", DCP_NOGATE },
    { "VDMOS", DCP_NOGATE }, { "NUMOS", DCP_NOGATE },
    { NULL, DCP_ALL }
};

struct dcpath_uf { int *parent; int n; };

static int dcpath_find(struct dcpath_uf *uf, int a)
{
    while (uf->parent[a] != a) {
        uf->parent[a] = uf->parent[uf->parent[a]];
        a = uf->parent[a];
    }
    return a;
}

static void dcpath_join(void *arg, int a, int b)
{
    struct dcpath_uf *uf = (struct dcpath_uf *) arg;
    if (a < 0 || b < 0 || a > uf->n || b > uf->n)
        return;
    a = dcpath_find(uf, a);
    b = dcpath_find(uf, b);
    if (a != b)
        uf->parent[a] = b;
}

static int dcpath_how(const char *name)
{
    int k;
    for (k = 0; dcpath_types[k].name; k++)
        if (strcmp(dcpath_types[k].name, name) == 0)
            return dcpath_types[k].how;
    return DCP_ALL;
}

static int dcpath_is_gate(const char *termname)
{
    const char *p;
    if (!termname)
        return 0;
    for (p = termname; *p; p++)
        if (tolower((unsigned char) p[0]) == 'g' && strncasecmp(p, "gate", 4) == 0)
            return 1;
    return 0;
}

/* the edges of every built-in instance of `type`. Enhancement-595: with
 * `reactive` set, a capacitor joins its pair and a MOSFET gate its terminals
 * (its oxide capacitance carries it in tran and ac); a current source and a
 * mutual inductance still join nothing -- coupling is not a path to ground,
 * an isolated secondary floats at every frequency. */
static void dcpath_builtin_edges(CKTcircuit *ckt, int type, struct dcpath_uf *uf,
                                 int reactive)
{
    SPICEdev *dev = DEVices[type];
    int how = dcpath_how(dev->DEVpublic.name);
    int terms = dev->DEVpublic.terms ? *dev->DEVpublic.terms : 0;
    GENmodel *model;

    if (reactive) {
        if (how == DCP_NONE && strcmp(dev->DEVpublic.name, "Capacitor") == 0)
            how = DCP_PAIR;
        else if (how == DCP_NOGATE)
            how = DCP_ALL;
    }
    if (how == DCP_NONE || terms <= 0)
        return;
    for (model = ckt->CKThead[type]; model; model = model->GENnextModel) {
        GENinstance *inst;
        for (inst = model->GENinstances; inst; inst = inst->GENnextInstance) {
            int *nodes = GENnode(inst);
            int k, first = -1, ihow = how;
            if (ihow == DCP_ASRC)
                ihow = (((ASRCinstance *) inst)->ASRCtype == ASRC_VOLTAGE) ? DCP_PAIR : DCP_NONE;
            if (ihow == DCP_NONE)
                continue;
            for (k = 0; k < terms; k++) {
                if (ihow == DCP_PAIR && k >= 2)
                    break;
                if (ihow == DCP_NOGATE && dev->DEVpublic.termNames &&
                    dcpath_is_gate(dev->DEVpublic.termNames[k]))
                    continue;
                if (first < 0)
                    first = nodes[k];
                else
                    dcpath_join(uf, first, nodes[k]);
            }
        }
    }
}

#ifdef XSPICE
/* the edges of every code-model instance of `type`: an analog OUTPUT port of a
 * voltage kind (v, vd, h, hd) stamps a source branch between its two nodes;
 * an input port is a probe and a current output is a current source, and
 * neither is a DC path */
static void dcpath_mif_edges(CKTcircuit *ckt, int type, struct dcpath_uf *uf)
{
    GENmodel *model;
    for (model = ckt->CKThead[type]; model; model = model->GENnextModel) {
        GENinstance *gen;
        for (gen = model->GENinstances; gen; gen = gen->GENnextInstance) {
            MIFinstance *here = (MIFinstance *) gen;
            int i, j;
            for (i = 0; i < here->num_conn; i++) {
                Mif_Conn_Data_t *conn = here->conn[i];
                if (!conn || conn->is_null || !conn->is_output)
                    continue;
                for (j = 0; j < conn->size; j++) {
                    Mif_Port_Data_t *port = conn->port[j];
                    if (!port || port->is_null)
                        continue;
                    switch (port->type) {
                    case MIF_VOLTAGE: case MIF_DIFF_VOLTAGE:
                    case MIF_RESISTANCE: case MIF_DIFF_RESISTANCE:
                        dcpath_join(uf, port->smp_data.pos_node, port->smp_data.neg_node);
                        break;
                    default:
                        break;
                    }
                }
            }
        }
    }
}
#endif

/* `.option dcpath`, read the way E-471 reads reusesetup: a number before a
 * string before a bool, because a bare `set` publishes a bool, `=1n` a number
 * and `=warn` a string. */
/* Enhancement-595: a number with SPICE's scale suffixes, for the value part
 * of `dcpath=1n,all` (the option reader hands a comma-joined value over as a
 * string, so the number inside is parsed here). */
static int dcpath_num(const char *w, double *v)
{
    char *end;
    double x = strtod(w, &end);
    if (end == w)
        return 0;
    switch (tolower((unsigned char) *end)) {
    case 'f': x *= 1e-15; break;
    case 'p': x *= 1e-12; break;
    case 'n': x *= 1e-9;  break;
    case 'u': x *= 1e-6;  break;
    case 'm': x *= (strncasecmp(end, "meg", 3) == 0 ? 1e6 : (strncasecmp(end, "mil", 3) == 0 ? 25.4e-6 : 1e-3)); break;
    case 'k': x *= 1e3;   break;
    case 'g': x *= 1e9;   break;
    case 't': x *= 1e12;  break;
    case '\0': break;
    default: return 0;
    }
    if (*end) {                              /* the unit letters may follow, nothing else */
        end++;
        if (strncasecmp(end - 1, "meg", 3) == 0 || strncasecmp(end - 1, "mil", 3) == 0)
            end += 2;
        while (*end && isalpha((unsigned char) *end))
            end++;
        if (*end)
            return 0;
    }
    *v = x;
    return 1;
}

/* one word of the option's string form; returns 0 for a word it does not know */
static int dcpath_word(const char *w, double *g, int *all, int *mode)
{
    double v;
    if (cieq(w, "gmin") || cieq(w, "on") || cieq(w, "yes") || cieq(w, "true"))
        *mode = DCPATH_HOLD;
    else if (cieq(w, "warn"))
        *mode = DCPATH_WARN;
    else if (cieq(w, "error"))
        *mode = DCPATH_ERROR;
    else if (cieq(w, "off") || cieq(w, "no") || cieq(w, "false"))
        *mode = DCPATH_OFF;
    else if (cieq(w, "dc"))                  /* Enhancement-595 */
        *all = 0;
    else if (cieq(w, "all") || cieq(w, "always"))
        *all = 1;
    else if (dcpath_num(w, &v)) {
        if (v > 0.0) {
            *g = v;
            *mode = DCPATH_HOLD;
        } else {
            fprintf(stderr, "Warning: .option dcpath=%g installs nothing; "
                            "taking it as dcpath=warn\n", v);
            *mode = DCPATH_WARN;
        }
    } else
        return 0;
    return 1;
}

static int dcpath_mode(CKTcircuit *ckt, double *g, int *all)
{
    double v;
    char s[64];

    *g = ckt->CKTgmin;
    *all = 0;                                /* Enhancement-595: DC only */
    /* `.option rshunt` / `gshunt` puts a conductance from EVERY node to
       ground: no node lacks a DC path then, there is nothing to install and
       nothing to report -- the global workaround keeps its numbers (E-571's
       AC hold follows gshunt on such a deck). */
    if (ckt->CKTgshunt > 0.0)
        return DCPATH_OFF;
#ifdef XSPICE
    if (ckt->enh->rshunt_data.enabled)           /* `.option rshunt` proper */
        return DCPATH_OFF;
#endif
    if (cp_getvar("nodcpath", CP_BOOL, NULL, 0))
        return DCPATH_OFF;
    /* Enhancement-595: `.option dcpathall` -- hold in every mode -- as a
       word of its own, so it combines with a value: `dcpath=1n dcpathall`.
       (The option reader splits a value at a comma, so `dcpath=1n,all`
       cannot reach here as one word.) Read before the numeric form, which
       returns on its own. */
    if (cp_getvar("dcpathall", CP_BOOL, NULL, 0))
        *all = 1;
    if (cp_getvar("dcpath", CP_REAL, &v, 0)) {
        if (v > 0.0) {
            *g = v;
            return DCPATH_HOLD;
        }
        fprintf(stderr, "Warning: .option dcpath=%g installs nothing; "
                        "taking it as dcpath=warn\n", v);
        return DCPATH_WARN;
    }
    if (cp_getvar("dcpath", CP_STRING, s, sizeof s)) {
        int mode = DCPATH_HOLD;
        if (!dcpath_word(s, g, all, &mode)) {
            fprintf(stderr, "Warning: .option dcpath=%s is not gmin, warn, error, off, "
                            "dc, all or a conductance; using dcpath=gmin\n", s);
            mode = DCPATH_HOLD;
        }
        return mode;
    }
    return DCPATH_HOLD;
}

/* The walk. Fills `named` (one byte per node, 1 = reported here so the
 * Enhancement-569 pass below stays quiet about it) and ckt->CKTdcpathNodes.
 * Returns an error only for dcpath=error. */
static int dcpath_check(CKTcircuit *ckt, SMPmatrix *matrix, int nunk,
                        unsigned char *named)
{
    struct dcpath_uf uf, ufr;
    CKTnode *nd;
    double g;
    int mode, i, root, rootr = 0, all, nfound = 0, nlisted = 0, nalways = 0;
    int *dconly = NULL, ndconly = 0;

    FREE(ckt->CKTdcpathNodes);
    ckt->CKTdcpathCount = 0;
    ckt->CKTdcpathAlways = 0;
    ckt->CKTdcpathG = 0.0;
    mode = dcpath_mode(ckt, &g, &all);
    if (mode == DCPATH_OFF || nunk <= 0)
        return OK;

    uf.n = nunk;
    uf.parent = TMALLOC(int, (size_t) nunk + 1);
    for (i = 0; i <= nunk; i++)
        uf.parent[i] = i;
    for (i = 0; i < DEVmaxnum; i++) {
        if (!DEVices[i] || !ckt->CKThead[i])
            continue;
        if (DEVices[i]->DEVpublic.registry_entry) {
            OSDIdcpathEdges(ckt, i, dcpath_join, &uf, 0);
            continue;
        }
#ifdef XSPICE
        if (DEVices[i]->DEVinstSize == &MIFiSize) {
            dcpath_mif_edges(ckt, i, &uf);
            continue;
        }
#endif
        dcpath_builtin_edges(ckt, i, &uf, 0);
    }
    root = dcpath_find(&uf, 0);
    /* Enhancement-595: the reactive walk, only when a hold is going to be
     * installed at DC only. It decides, per node the DC walk missed, whether
     * a capacitor carries it in tran and ac (released there) or nothing does
     * (held in every mode). */
    ufr.parent = NULL;
    ufr.n = 0;
    if (mode == DCPATH_HOLD && !all) {
        ufr.n = nunk;
        ufr.parent = TMALLOC(int, (size_t) nunk + 1);
        for (i = 0; i <= nunk; i++)
            ufr.parent[i] = i;
        for (i = 0; i < DEVmaxnum; i++) {
            if (!DEVices[i] || !ckt->CKThead[i])
                continue;
            if (DEVices[i]->DEVpublic.registry_entry) {
                OSDIdcpathEdges(ckt, i, dcpath_join, &ufr, 1);
                continue;
            }
#ifdef XSPICE
            if (DEVices[i]->DEVinstSize == &MIFiSize) {
                dcpath_mif_edges(ckt, i, &ufr);
                continue;
            }
#endif
            dcpath_builtin_edges(ckt, i, &ufr, 1);
        }
        rootr = dcpath_find(&ufr, 0);
        dconly = TMALLOC(int, (size_t) nunk + 1);
    }
    ckt->CKTdcpathNodes = TMALLOC(int, (size_t) nunk + 1);
    for (nd = ckt->CKTnodes; nd; nd = nd->next) {
        const char *name;
        if (nd->type != SP_VOLTAGE || nd->number <= 0 || nd->number > nunk)
            continue;
        if (dcpath_find(&uf, nd->number) == root)
            continue;
        /* the node's own name -- CKTnodName() walks the node list for every
           call, which was quadratic on a large deck with thousands of unreached
           device-internal nodes (seven seconds of setup) */
        name = (const char *) nd->name;
        /* A built-in device's INTERNAL node (`t1#int1`, `q1#collector`) is
           joined to its terminals by the device's own series elements, which
           the terminal table cannot see; it is taken as reached. One that
           touches nothing at all is still caught by the structural pass
           below. OSDI internal nodes carry no '#' and stay in the walk. */
        if (name && strchr(name, '#'))
            continue;
        nfound++;
        named[nd->number] = 1;
        if (mode == DCPATH_HOLD) {
            /* Enhancement-595: carried by a reactive element in tran and ac? */
            int released = ufr.parent && dcpath_find(&ufr, nd->number) == rootr;
            SMPmakeElt(matrix, nd->number, nd->number);
            if (released)
                dconly[ndconly++] = nd->number;
            else
                ckt->CKTdcpathNodes[nalways++] = nd->number;
            nlisted++;
            if (nfound <= 5) {
                const char *dur = released
                    ? "; held at DC only -- tran and ac release it while a reactive path carries the node"
                    : "";
                if (g == ckt->CKTgmin)
                    fprintf(stderr, "Warning: no DC path from node '%s' to ground; "
                                    "gmin (%g S) installed to provide one%s\n", name, g, dur);
                else
                    fprintf(stderr, "Warning: no DC path from node '%s' to ground; "
                                    "%g S installed to provide one (.option dcpath)%s\n", name, g, dur);
            }
        } else if (mode == DCPATH_WARN) {
            if (nfound <= 5)
                fprintf(stderr, "Warning: no DC path from node '%s' to ground "
                                "(.option dcpath=warn: nothing installed)\n", name);
        } else {
            fprintf(stderr, "Error: no DC path from node '%s' to ground "
                            "(.option dcpath=error)\n", name);
        }
    }
    if (nfound > 5 && mode != DCPATH_ERROR)
        fprintf(stderr, "Warning: ... and %d more nodes without a DC path to ground\n",
                nfound - 5);
    FREE(uf.parent);
    FREE(ufr.parent);
    if (mode == DCPATH_HOLD) {
        /* the always-held nodes first, then the ones released outside DC */
        for (i = 0; i < ndconly; i++)
            ckt->CKTdcpathNodes[nalways + i] = dconly[i];
        ckt->CKTdcpathAlways = nalways;
        ckt->CKTdcpathCount = nlisted;
        ckt->CKTdcpathG = nlisted ? g : 0.0;
    }
    FREE(dconly);
    if (nlisted == 0)
        FREE(ckt->CKTdcpathNodes);
    if (mode == DCPATH_ERROR && nfound > 0) {
        errMsg = tprintf("%d node%s with no DC path to ground (.option dcpath=error)",
                         nfound, nfound == 1 ? "" : "s");
        return E_PRIVATE;
    }
    return OK;
}

/* the hold: CKTdcpathG onto every listed diagonal, after the device loads.
 * Looked up per load rather than cached, so the KLU CSC conversion needs no
 * rebinding (the lookup is what Enhancement-571 does in the AC load). */
void CKTdcpathStamp(CKTcircuit *ckt, int ac)
{
    int k, atdc;
    if (!ckt->CKTdcpathNodes || ckt->CKTdcpathCount <= 0 || ckt->CKTdcpathG <= 0.0)
        return;
    /* Enhancement-595: the entries past CKTdcpathAlways are held only where
     * the matrix is evaluated at DC (op, dc, the transient's and the ac's
     * operating point -- MODEDC covers all three, and optran runs as a
     * transient, where the capacitor carries the node). In a transient a
     * released node whose diagonal is still exactly zero after the device
     * loads has a zero-valued reactive element and nothing else, and keeps
     * the hold; in ac the all-zero row is Enhancement-571's to hold. */
    atdc = !ac && (ckt->CKTmode & MODEDC);
    for (k = 0; k < ckt->CKTdcpathCount; k++) {
        double *d = (double *) SMPfindElt(ckt->CKTmatrix, ckt->CKTdcpathNodes[k],
                                          ckt->CKTdcpathNodes[k], 0);
        if (!d)
            continue;
        if (k >= ckt->CKTdcpathAlways && !atdc) {
            if (ac || *d != 0.0)
                continue;
        }
        *d += ckt->CKTdcpathG;
    }
}


int
CKTsetup(CKTcircuit *ckt)
{
    int i;
    int error;
#ifdef USE_OMP
    int nthreads = 2;
#endif
#ifdef XSPICE
 /* gtri - begin - Setup for adding rshunt option resistors */
    CKTnode *node;
    int     num_nodes;
 /* gtri - end - Setup for adding rshunt option resistors */

#ifdef KLU
    BindElement BindNode, *matched, *BindStruct ;
    size_t nz ;
#endif
#endif

    SMPmatrix *matrix;

    if (!ckt->CKThead) {
        fprintf(stderr, "Error: No model list found, device setup not possible!\n");
        if (ft_stricterror)
            controlled_exit(EXIT_BAD);
        return E_PANIC;
    }
    if (!DEVices) {
        fprintf(stderr, "Error: No device list found, device setup not possible!\n");
        if (ft_stricterror)
            controlled_exit(EXIT_BAD);
        return E_PANIC;
    }

    ckt->CKTnumStates=0;

#ifdef WANT_SENSE2
    if(ckt->CKTsenInfo){
        error = CKTsenSetup(ckt);
        if (error)
            return(error);
    }
#endif

    if (ckt->CKTisSetup)
        return E_NOCHANGE;

    error = NIinit(ckt);
    if (error) 
        return(error);

    ckt->CKTisSetup = 1;
    ckt->CKTbindStale = 0;  /* Enhancement-365: bindings are current again */

    matrix = ckt->CKTmatrix;

#ifdef USE_OMP
    if (!cp_getvar("num_threads", CP_NUM, &nthreads, 0))
        nthreads = 2;

    omp_set_num_threads(nthreads);
/*    if (nthreads == 1)
      printf("OpenMP: %d thread is requested in ngspice\n", nthreads);
    else
      printf("OpenMP: %d threads are requested in ngspice\n", nthreads);*/
#endif

#ifdef HAS_PROGREP
    SetAnalyse("Device Setup", 0);
#endif

    /* preserve CKTlastNode before invoking DEVsetup()
     * so we can check for incomplete CKTdltNNum() invocations
     * during DEVunsetup() causing an erronous circuit matrix
     *   when reinvoking CKTsetup()
     */
    ckt->prev_CKTlastNode = ckt->CKTlastNode;

    for (i=0;i<DEVmaxnum;i++) {
        if ( DEVices[i] && DEVices[i]->DEVsetup && ckt->CKThead[i] ) {
            error = DEVices[i]->DEVsetup (matrix, ckt->CKThead[i], ckt,
                    &ckt->CKTnumStates);
            if(error) return(error);
        }
    }

    /* Enhancement-608: the devices' internal nodes exist now; place the
     * `.ic`/`.nodeset` entries INPpas3 kept for them. */
    CKTapplyPendingNodPm(ckt);

#ifdef XSPICE
  /* gtri - begin - Setup for adding rshunt option resistors */

    if(ckt->enh->rshunt_data.enabled) {

        /* Count number of voltage nodes in circuit */
        for(num_nodes = 0, node = ckt->CKTnodes; node; node = node->next)
            if((node->type == SP_VOLTAGE) && (node->number != 0))
                num_nodes++;

        /* Allocate space for the matrix diagonal data */
        if(num_nodes > 0) {
            FREE(ckt->enh->rshunt_data.diag);
            ckt->enh->rshunt_data.diag =
                 TMALLOC(double *, num_nodes);
        }

        /* Set the number of nodes in the rshunt data */
        ckt->enh->rshunt_data.num_nodes = num_nodes;

        /* Get/create matrix diagonal entry following what RESsetup does */
        for(i = 0, node = ckt->CKTnodes; node; node = node->next) {
            if((node->type == SP_VOLTAGE) && (node->number != 0)) {
                ckt->enh->rshunt_data.diag[i] =
                      SMPmakeElt(matrix,node->number,node->number);
                i++;
            }
        }
    }

    /* gtri - end - Setup for adding rshunt option resistors */
#endif

    /* F1/F2/F8 (2026-09-06): make the matrix agree with the node numbering.
     *
     * The matrix is created empty (NIinit) and grows only as devices stamp
     * it, so its size was the largest node index that carried an entry, not
     * the number of unknowns.  A node nothing conducts to -- fed only by a
     * current source, or the output of a controlled current source -- was
     * therefore either an empty column in the middle (which KLU's COO->CSC
     * conversion "collapsed", mis-addressing every other node's RHS) or,
     * numbered last, outside the matrix altogether: NIreinit sized the RHS
     * vectors one short, the device load wrote past them, and both solvers
     * printed the injected current as the node's voltage.
     *
     * Two things fix that at the one place where the count is final:
     *  - every node whose matrix row OR column is empty gets a zero diagonal
     *    element, so it is a real (singular) unknown that gmin stepping can
     *    hold up -- the same thing Sparse already did for such a node once a
     *    .nodeset had created its diagonal -- and the user is told
     *    (Enhancement-569 added the row: a node only READ by a B-source or an
     *    XSPICE input has a column entry and an EMPTY row, which no gmin can
     *    rescue; a current-source output has the reverse);
     *  - a node with a .nodeset/.ic gets its diagonal here too, so CKTic finds
     *    it under KLU instead of aborting the whole run as "out of memory"
     *    (nodes held only by inductor or voltage-source branches have none);
     *  - the solver is told the true size, so a trailing node is inside the
     *    matrix and the RHS vectors cover the numbering. */
    {
        int nunk = ckt->CKTmaxEqNum - 1;
        if (nunk > 0) {
            unsigned char *rowocc = TMALLOC(unsigned char, (size_t) nunk + 2);
            unsigned char *colocc = TMALLOC(unsigned char, (size_t) nunk + 2);
            unsigned char *named = TMALLOC(unsigned char, (size_t) nunk + 2);
            CKTnode *nd;
            int nfloat = 0, anyoccupied = 0, k;
            memset(rowocc, 0, (size_t) nunk + 2);
            memset(colocc, 0, (size_t) nunk + 2);
            memset(named, 0, (size_t) nunk + 2);
            SMPmarkOccupied(matrix, rowocc, colocc, nunk);
            for (k = 1; k <= nunk; k++)
                anyoccupied |= rowocc[k] | colocc[k];
            /* Enhancement-575: the DC-path walk, before the structural pass
               below so that a node it named (and, with the hold on, gave a
               diagonal) is not reported twice. A circuit with NO matrix at all
               keeps Enhancement-492's single note, as the structural pass
               does: the walk runs only in an otherwise connected circuit. */
            if (anyoccupied) {
                error = dcpath_check(ckt, matrix, nunk, named);
                if (error) {
                    FREE(rowocc); FREE(colocc); FREE(named);
                    return error;
                }
            }
            /* A circuit with NO matrix at all (nothing conducts anywhere -- an
             * XSPICE digital-only deck, or a current source into a lone node)
             * keeps Enhancement-492's single "no matrix to solve" note rather
             * than one warning per node; only a floating node in an otherwise
             * connected circuit gets a diagonal here. */
            for (nd = ckt->CKTnodes; nd && anyoccupied; nd = nd->next) {
                if (nd->number <= 0 || nd->number > nunk)
                    continue;
                if (!rowocc[nd->number] || !colocc[nd->number]) {
                    if (!named[nd->number]) {
                        if (nfloat < 5)
                            fprintf(stderr, "Warning: node '%s' is connected to nothing that conducts; "
                                    "it is held only by gmin\n", CKTnodName(ckt, nd->number));
                        nfloat++;
                    }
                    SMPmakeElt(matrix, nd->number, nd->number);
                } else if (nd->nsGiven || nd->icGiven) {
                    SMPmakeElt(matrix, nd->number, nd->number);
                }
            }
            if (nfloat > 5)
                fprintf(stderr, "Warning: ... and %d more nodes like that\n", nfloat - 5);
            FREE(rowocc);
            FREE(colocc);
            FREE(named);
        }
        SMPsizeHint(matrix, nunk);
    }

#ifdef KLU
    if (ckt->CKTmatrix->CKTkluMODE)
    {
        CKTannounceSolver (1) ;

        /* Convert the COO Storage to CSC for KLU and Fill the Binding Table */
        SMPconvertCOOtoCSC (matrix) ;

        /* Assign the KLU Pointers */
        for (i = 0 ; i < DEVmaxnum ; i++)
            if (DEVices [i] && DEVices [i]->DEVbindCSC && ckt->CKThead [i])
                DEVices [i]->DEVbindCSC (ckt->CKThead [i], ckt) ;

#ifdef XSPICE
        if (ckt->enh->rshunt_data.num_nodes > 0) {
            BindStruct = ckt->CKTmatrix->SMPkluMatrix->KLUmatrixBindStructCOO ;
            nz = (size_t)ckt->CKTmatrix->SMPkluMatrix->KLUmatrixLinkedListNZ ;
            for(i = 0, node = ckt->CKTnodes; node; node = node->next) {
                if((node->type == SP_VOLTAGE) && (node->number != 0)) {
                    BindNode.COO = ckt->enh->rshunt_data.diag [i] ;
                    BindNode.CSC = NULL ;
                    BindNode.CSC_Complex = NULL ;
                    matched = (BindElement *) bsearch (&BindNode, BindStruct, nz, sizeof (BindElement), BindCompare) ;
                    if (!matched) {
                        fprintf (stderr, "Error: Ptr %p not found in BindStruct Table\n", ckt->enh->rshunt_data.diag [i]) ;
                        ckt->enh->rshunt_data.diag[i] = NULL;
                    }
                    else
                        ckt->enh->rshunt_data.diag [i] = matched->CSC ;
                    i++;
                }
            }
        }
#endif

    } else {
        CKTannounceSolver (0) ;
    }
#endif

    for(i=0;i<=MAX(2,ckt->CKTmaxOrder)+1;i++) { /* dctran needs 3 states as minimum */
        CKALLOC(ckt->CKTstates[i],ckt->CKTnumStates,double);
    }
#ifdef WANT_SENSE2
    if(ckt->CKTsenInfo){
        /* to allocate memory to sensitivity structures if
         * it is not done before */

        error = NIsenReinit(ckt);
        if(error) return(error);
    }
#endif
    if(ckt->CKTniState & NIUNINITIALIZED) {
        error = NIreinit(ckt);
        if(error) return(error);
    }

    return(OK);
}

int
CKTunsetup(CKTcircuit *ckt)
{
    int i, error, e2;
    CKTnode *node;

    /* Enhancement-575: the DC-path hold list belongs to one setup */
    FREE(ckt->CKTdcpathNodes);
    ckt->CKTdcpathCount = 0;
    ckt->CKTdcpathAlways = 0;
    ckt->CKTdcpathG = 0.0;

    error = OK;
    if (!ckt->CKTisSetup)
        return OK;

    for(i=0;i<=ckt->CKTmaxOrder+1;i++) {
        tfree(ckt->CKTstates[i]);
    }

    /* added by HT 050802*/
    for(node=ckt->CKTnodes;node;node=node->next){
        if(node->icGiven || node->nsGiven) {
            node->ptr=NULL;
        }
    }

    for (i=0;i<DEVmaxnum;i++) {
        if ( DEVices[i] && DEVices[i]->DEVunsetup && ckt->CKThead[i] ) {
            e2 = DEVices[i]->DEVunsetup (ckt->CKThead[i], ckt);
            if (!error && e2)
                error = e2;
        }
    }

    if (ckt->prev_CKTlastNode != ckt->CKTlastNode) {
        fprintf(stderr, "Internal Error: incomplete CKTunsetup(), this will cause serious problems, please report this issue !\n");
        controlled_exit(EXIT_FAILURE);
    }
    ckt->prev_CKTlastNode = NULL;

    ckt->CKTisSetup = 0;
    if(error) return(error);

    NIdestroy(ckt);
    /*
    if (ckt->CKTmatrix)
        SMPdestroy(ckt->CKTmatrix);
    ckt->CKTmatrix = NULL;
    */

    return OK;
}
