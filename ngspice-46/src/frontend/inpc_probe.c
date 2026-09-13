/* ngspice file inpc_probe.c
   Copyright Holger Vogt 2021-2024
   License: BSD 3-clause
 */

#include "ngspice/ngspice.h"
#include "ngspice/cpextern.h"
#include "ngspice/dstring.h"
#include "numparam/general.h"
#include "ngspice/hash.h"
#include "ngspice/inpdefs.h"
#include "ngspice/wordlist.h"
#include "ngspice/stringskip.h"
#include "ngspice/ifsim.h"          /* Enhancement-628: IFdevice terminal names */
#include "inp.h"                    /* Enhancement-628: inp_autobus_of_deck */
#include "subckt.h"                 /* Enhancement-628: inp_osdi_port_widths */

void inp_probe(struct card* card);
void inp_probe_osdi(struct card* deck);   /* Enhancement-628 */
void modprobenames(INPtables* tab);

extern struct card* insert_new_line(
    struct card* card, char* line, int linenum, int linenum_orig, char *lineinfo);
extern int get_number_terminals(char* c);
extern char* search_plain_identifier(char* str, const char* identifier);

static char* get_terminal_name(char* element, char* numberstr, NGHASHPTR instances);
static char* get_terminal_number(char* element, char* numberstr);
static int setallvsources(struct card* tmpcard, NGHASHPTR instances, char* instname, int numnodes, bool haveall, bool power);

/* Enhancement-430: say what `.probe` actually accepts, and where an
 * `@device[param]` belongs.
 *
 * The old text was "Warning: Strange parameter in line %s, ingnored" -- it named
 * neither the accepted forms nor the right tool, and it printed TWICE for one
 * bad token (the type test below warns and advances, then the `!nextnode` test
 * warns again on the wreckage).
 *
 * `.probe` and `.save` are deliberately different mechanisms, not two spellings
 * of one thing, and the message now says so rather than looking like an
 * oversight. Per the manual (11.7.1) `.probe` MEASURES a current by placing a
 * voltage source in series with the device's node, which is why its results
 * appear as `<inst>#branch`; `@device[param]` is read out of the device
 * instead, needs no extra node, and is a `.save` item (11.7.3, where
 * `.options savecurrents` is described precisely as generating `.save @r1[i]`
 * lines). So a token starting with '@' gets pointed at the tool that handles
 * it, not merely refused. */
static void
probe_reject_token(const char *line, const char *tok)
{
    /* The wordlist holds the card in its consumed form, `*probe ...`; echo it
     * back the way the user wrote it. */
    const char *shown = line;
    if (shown && *shown == '*')
        shown++;
    fprintf(stderr,
            "Warning: .probe accepts v(...), i(...), p(...) or alli -- ignoring "
            "\".%s\"\n", shown);
    if (tok && *tok == '@')
        fprintf(stderr,
                "    `@device[param]` is read from the device rather than measured "
                "with an added\n"
                "    source, so it belongs to .save: use `.save %s`, or "
                "`.options savecurrents`\n"
                "    for every device terminal current.\n", tok);
}


static int check_for_nodes(char* instance, int numnodes);

/* Enhancement-628 (hunt F11): `.probe alli` on an OSDI device whose line is in
 * autobus shorthand -- `N2 /mid /out vares` for two 4-bit bus ports.
 *
 * The pass counted the line's node tokens (2), took the device for a
 * two-terminal one and spliced its measuring source into the SECOND TOKEN:
 * `n2 /mid probe_int_/out_n2 vares` plus `vcurr_... probe_int_/out_n2 /out 0`.
 * Autobus then expanded the base `probe_int_/out_n2` into four bits nothing
 * else touched, the source sat on the plain node, and the bits floated: 0 V
 * on every output, gmin on every bit, and a warning about the node the pass
 * itself had invented (E-572's "also uses ... as a plain node"). KiCad adds
 * `.probe alli` to every run by default, so under KiCad every bus device
 * read 0 V.
 *
 * The pre-pass now knows a bus port when it sees one: `pre_osdi` has already
 * registered the module and the deck's own `.model` cards name it, so the
 * port widths are the same ones INP2N will use (E-464's lookup). A line with
 * one token per PORT is written out here -- each token becomes its bits, in
 * the deck's own spelling (`/out_0_ .. /out_3_` under `.option autobus=kicad`,
 * `/out[0] ..` otherwise, E-572's one-bit rule included) -- and every bit
 * gets its own measuring source, so autobus finds nothing left to expand
 * and each terminal current is a vector: `n2:p_0_#branch .. n2:n_3_#branch`.
 * An OSDI line already written out gets the model's terminal names on its
 * currents too (they were all `nn`); a two-terminal scalar device keeps
 * `<inst>#branch`. */
#define PROBE_MAXPORT 256
static bool probe_osdi_pending;     /* `alli` met an OSDI line during the deck read */

/* the model's terminal name as a vector name can carry it: `p[0]` -> `p_0_` */
static char *probe_term_name(const char *tn)
{
    char buf[128];
    INPbusBitSuffix(tn ? tn : "nn", TRUE, buf, sizeof buf);
    return copy(buf);
}

/* the ports of an OSDI instance line's model; -1 when it cannot be resolved */
static int probe_osdi_ports(struct card *deck, const char *line, int *start, int *cnt,
                            IFdevice **dev)
{
    char *model = inp_model_of_line(line);
    int np = inp_osdi_port_widths(deck, model, start, cnt, PROBE_MAXPORT, dev);
    tfree(model);
    return np;
}

/* the line's node tokens in shorthand (one per port) written out as bits, in
 * the deck's spelling; the rest of the line (the model name, parameters)
 * follows. NULL when the tokens do not go one per port. */
static char *probe_expand_bus_line(const char *nodes, int np, const int *start,
                                   const int *cnt, IFdevice *dev, bool kicad)
{
    DS_CREATE(out, 256);
    char *scan = (char *) nodes, *tok;
    int p, k;
    char *res;

    for (p = 0; p < np; p++) {
        tok = gettok_instance(&scan);
        if (!tok || !*tok) {
            tfree(tok);
            ds_free(&out);
            return NULL;
        }
        if (cnt[p] > 1 && (strchr(tok, '[') || strcmp(tok, "0") == 0 ||
                           INPbusTokenIndexed(tok, strlen(tok), kicad))) {
            tfree(tok);                 /* E-445 / E-490: not a shorthand token */
            ds_free(&out);
            return NULL;
        }
        for (k = 0; k < cnt[p]; k++) {
            const char *tn = dev->termNames[start[p] + k];
            const char *lb = tn ? strchr(tn, '[') : NULL;
            if (p || k)
                ds_cat_char(&out, ' ');
            ds_cat_str(&out, tok);
            if (lb && strcmp(tok, "0") != 0 && strcasecmp(tok, "gnd") != 0) {
                char sfx[64];
                INPbusBitSuffix(lb, kicad, sfx, sizeof sfx);
                ds_cat_str(&out, sfx);
            }
        }
        tfree(tok);
    }
    ds_cat_char(&out, ' ');
    ds_cat_str(&out, scan);             /* the model name and any parameters */
    res = copy(ds_get_buf(&out));
    ds_free(&out);
    return res;
}

/* Find any line starting with .probe: assemble all parameters like
   <empty>     add V(0) current measure sources to all device nodes in addition to .save all
   alli        add V(0) current measure sources to all device nodes in addition to .save all
   I(R1)       add V(0) measure source to node 1 of a two-terminal device R1
   I(Q1)       add V(0) measure sources to all nodes of a multi-terminal device Q1
   I(M4,3)     add V(0) measure source to node 3 of a multi-terminal device M4
   Vd(R1)     add E source inputs to measure voltage difference to both terminals of a two-terminal device R1
   Vd(X1:2:3) add E source inputs to terminals 2 and 3 of a multi-terminal device X1
   Vd(X1:2,X2:3) add E source inputs to terminal 2 of a multi-terminal device X1 and to terminal 3 of X2

   Seach the netlist for the devices found in the .probe parameters.
   Check the number of terminals for each device. Add 0V voltage sources
   in series to each of the named terminals. Add E sources to the differential
   voltage probes.

   */
/* Enhancement-605: the card after which a line meant for the head of the
 * deck goes -- past a .control block that opens the deck (every OSDI deck
 * opens with one, for `pre_osdi`), where a `.save` line would run as a
 * command: ".save: no such command available in ngspice". */
static struct card *
probe_head(struct card *deck)
{
    struct card *at = deck;

    if (at && ciprefix(".control", at->line))
        while (at->nextcard && !ciprefix(".endc", at->line))
            at = at->nextcard;
    return at;
}

/* Enhancement-628: the splice itself -- one measuring source per node of the
 * device line, the line rewritten onto the sources' inner nodes, the device's
 * currents put on a .save card after it. `thisline` is the line's node tokens
 * (and what follows them), `curr_line` the same for the messages; `osdi_terms`
 * names the terminals of an OSDI device whose model resolved (NULL otherwise:
 * the generic per-device names). Returns the last card inserted. */
static struct card *
probe_splice(struct card *card, char *instname, char *thisline, char *curr_line,
             int numnodes, char **osdi_terms, NGHASHPTR instances)
{
    struct card *prevcard = card;
    wordlist *allsaves = NULL;
    int nn = 0, i;

    /* all elements with 2 nodes: add a voltage source to the second node in the elements line */
    if (numnodes == 2) {
        char *strnode1, *strnode2, *nodename2;
        strnode1 = gettok(&thisline);
        strnode2 = gettok(&thisline);

        if (!strnode2 || *strnode2 == '\0') {
            fprintf(stderr, "Warning: Cannot read 2 nodes in line %s\n", curr_line);
            fprintf(stderr, "    Instance not ready for .probe command\n");
            tfree(strnode1);
            tfree(strnode2);
            return card;
        }

        /* Enhancement-628: an OSDI terminal (or a subcircuit formal) by name */
        nodename2 = osdi_terms ? probe_term_name(osdi_terms[1])
                               : get_terminal_name(instname, "2", instances);

        char* newnode = tprintf("probe_int_%s_%s", strnode2, instname);
        char* vline = tprintf("vcurr_%s:%s_%s %s %s 0", instname, nodename2, strnode2, newnode, strnode2);
        char *newline = tprintf("%s %s %s %s", instname, strnode1, newnode, thisline);

        char* nodesaves = tprintf("%s#branch", instname);
        allsaves = wl_cons(nodesaves, allsaves);

        tfree(card->line);
        card->line = newline;

        card = insert_new_line(card, vline, 0, card->linenum_orig, card->linesource);

        tfree(strnode1);
        tfree(strnode2);
        tfree(newnode);
        tfree(nodename2);

    }
    else {
        char* nodename;
        DS_CREATE(dnewline, 200);
        sadd(&dnewline, instname);
        cadd(&dnewline, ' ');
        for (i = 1; i <= numnodes; i++) {
            char* thisnode;
            char nodebuf[20];
            thisnode = gettok(&thisline);
            if (!thisnode || *thisnode == '\0') {
                fprintf(stderr, "Warning: Cannot read node %d in line %s\n", i, curr_line);
                fprintf(stderr, "    Instance not ready for .probe command\n");
                tfree(thisnode);
                continue;
            }
            char* newnode = tprintf("probe_int_%s_%s_%d", thisnode, instname, i);
            sadd(&dnewline, newnode);
            cadd(&dnewline, ' ');
            /* to make the nodes unique */
            snprintf(nodebuf, 12, "%d", i);
            /* Enhancement-628: an OSDI terminal by the model's name */
            nodename = osdi_terms ? probe_term_name(osdi_terms[i - 1])
                                  : get_terminal_name(instname, nodebuf, instances);
            if (!nodename || *nodename == '\0') {
                fprintf(stderr, "Warning: Cannot find node name %d in line %s\n", i, curr_line);
                fprintf(stderr, "    Instance not ready for .probe command\n");
                tfree(thisnode);
                continue;
            }
            char* vline = tprintf("vcurr_%s:%s:%s_%s %s %s 0", instname, nodename, thisnode, nodebuf, thisnode, newnode);
            card = insert_new_line(card, vline, 0, card->linenum_orig, card->linesource);
            /* special for KiCad: add shunt resistor if thisnode contains 'unconnected' */
            if (*instname == 'x' && strstr(thisnode, "unconnected")) {
                /* nn makes the resistor name unique for a device with multiple unconnected nodes */
                char *rline = tprintf("r%s%d %s 0 1e15", thisnode, nn++, thisnode);
                card = insert_new_line(card, rline, 0, card->linenum_orig, card->linesource);
            }
            char* nodesaves = tprintf("%s:%s#branch", instname, nodename);
            allsaves = wl_cons(nodesaves, allsaves);

            tfree(newnode);
            tfree(nodename);
        }
        sadd(&dnewline, thisline);
        tfree(prevcard->line);
        prevcard->line = copy(ds_get_buf(&dnewline));
        ds_free(&dnewline);
    }
    if (allsaves) {
        allsaves = wl_cons(copy(".save"), allsaves);
        char* newline = wl_flatten(allsaves);
        wl_free(allsaves);
        allsaves = NULL;
        card = insert_new_line(card, newline, 0, card->linenum_orig, card->linesource);
    }
    return card;
}

/* Enhancement-628 (hunt F11): a subcircuit call's formal may be a bus base
 * INSIDE the subcircuit -- `.subckt va_res_block in out` with `N2 /mid out
 * vares` in it, `out` standing for four bits. The probe used to put its one
 * source on the X line's token, `probe_int_/out_x1`, which the subcircuit
 * then expanded into four bits the source never touched. The width a formal
 * is used with is found by looking inside: an OSDI shorthand line that names
 * it on a bus port, or a nested call that passes it on. */
#define PROBE_MAXDEPTH 8

/* the `.subckt <name>` card, or NULL */
static struct card *probe_subckt_card(struct card *deck, const char *name)
{
    struct card *c;
    for (c = deck; c; c = c->nextcard) {
        char *line = c->line, *tok, *nm;
        if (!line || !ciprefix(".subckt", line))
            continue;
        tok = gettok(&line);            /* .subckt */
        tfree(tok);
        nm = gettok(&line);
        if (nm && cieq(nm, name)) {
            tfree(nm);
            return c;
        }
        tfree(nm);
    }
    return NULL;
}

/* the formals of a .subckt card: the tokens up to `params:` or a `k=v` */
static char **probe_subckt_formals(struct card *sc, int *n)
{
    char *line = sc->line, *tok, **f = NULL;
    int cap = 0;
    *n = 0;
    tok = gettok(&line); tfree(tok);   /* .subckt */
    tok = gettok(&line); tfree(tok);   /* the name */
    while ((tok = gettok(&line)) != NULL && *tok) {
        if (search_plain_identifier(tok, "params:") || strchr(tok, '=')) {
            tfree(tok);
            break;
        }
        if (*n == cap) {
            cap = cap ? 2 * cap : 8;
            f = TREALLOC(char *, f, cap);
        }
        f[(*n)++] = tok;
    }
    return f;
}

static void probe_free_formals(char **f, int n)
{
    int i;
    for (i = 0; i < n; i++)
        tfree(f[i]);
    tfree(f);
}

/* the bits formal `fidx` of subcircuit `sname` is used with inside it: the
 * terminal names of the OSDI bus port a shorthand line puts it on (found
 * through nested calls too); 0 when it is a plain node there. *terms points
 * into the device's own table. */
static int probe_formal_bits(struct card *deck, const char *sname, int fidx,
                             char ***terms, int depth)
{
    struct card *sc = probe_subckt_card(deck, sname), *c;
    char **formals;
    int nf, found = 0, nest = 0;

    if (!sc || depth > PROBE_MAXDEPTH)
        return 0;
    formals = probe_subckt_formals(sc, &nf);
    if (fidx >= nf) {
        probe_free_formals(formals, nf);
        return 0;
    }
    for (c = sc->nextcard; c && !found; c = c->nextcard) {
        char *line = c->line, *inst, *tok;
        int numnodes, i;
        if (!line)
            continue;
        if (ciprefix(".subckt", line)) { nest++; continue; }
        if (ciprefix(".ends", line)) { if (nest-- == 0) break; continue; }
        if (nest > 0 || *line == '*' || *line == '.' || *line == '\0')
            continue;
        if (*line != 'n' && *line != 'x')
            continue;
        inst = gettok_instance(&line);
        if (!inst)
            continue;
        numnodes = get_number_terminals(c->line);
        if (*inst == 'n') {
            int pstart[PROBE_MAXPORT], pcnt[PROBE_MAXPORT];
            IFdevice *dev = NULL;
            int np = probe_osdi_ports(deck, c->line, pstart, pcnt, &dev);
            if (np > 0 && dev && dev->terms && numnodes == np && np < *dev->terms) {
                for (i = 0; i < np && !found; i++) {
                    tok = gettok_instance(&line);
                    if (!tok)
                        break;
                    if (pcnt[i] > 1 && cieq(tok, formals[fidx])) {
                        *terms = dev->termNames + pstart[i];
                        found = pcnt[i];
                    }
                    tfree(tok);
                }
            }
        } else {
            char **actuals = TMALLOC(char *, numnodes > 0 ? numnodes : 1);
            char *sub = NULL;
            int na = 0;
            for (i = 0; i < numnodes; i++) {
                tok = gettok_instance(&line);
                if (!tok)
                    break;
                actuals[na++] = tok;
            }
            sub = gettok_instance(&line);
            for (i = 0; i < na && !found && sub; i++)
                if (cieq(actuals[i], formals[fidx]))
                    found = probe_formal_bits(deck, sub, i, terms, depth + 1);
            for (i = 0; i < na; i++)
                tfree(actuals[i]);
            tfree(actuals);
            tfree(sub);
        }
        tfree(inst);
    }
    probe_free_formals(formals, nf);
    return found;
}

/* the splice of a subcircuit call: a formal that is a bus base inside keeps
 * its base token on the X line (the subcircuit expands it into the bits) and
 * gets one measuring source per bit, bridging `<actual><bit>` to
 * `probe_int_<actual>_<inst>_<i><bit>`; a plain formal is spliced as any
 * node. Two plain nodes keep the `<inst>#branch` form. */
static struct card *probe_splice_x(struct card *deck, struct card *card, char *instname,
                                   char *thisline, int numnodes, bool kicad)
{
    struct card *prevcard = card;
    wordlist *allsaves = NULL;
    char *scan = thisline, *sname, *rest;
    char **actuals = TMALLOC(char *, numnodes > 0 ? numnodes : 1);
    char **formals = NULL;
    struct card *sc;
    int nf = 0, i, na = 0, nn = 0;
    bool anybus = FALSE;
    DS_CREATE(dnewline, 200);

    for (i = 0; i < numnodes; i++) {
        char *tok = gettok_instance(&scan);
        if (!tok || !*tok) {
            tfree(tok);
            break;
        }
        actuals[na++] = tok;
    }
    rest = scan;
    {
        char *r = rest;
        sname = gettok_instance(&r);
    }
    sc = sname ? probe_subckt_card(deck, sname) : NULL;
    if (sc)
        formals = probe_subckt_formals(sc, &nf);
    if (na != numnodes || !sc || nf < na) {
        /* not a call this pass can read: the generic splice, formals unknown */
        struct card *r = probe_splice(card, instname, thisline, thisline, numnodes, NULL, NULL);
        for (i = 0; i < na; i++) tfree(actuals[i]);
        tfree(actuals); tfree(sname);
        probe_free_formals(formals, nf);
        ds_free(&dnewline);
        return r;
    }
    for (i = 0; i < na && !anybus; i++) {
        char **terms = NULL;
        if (probe_formal_bits(deck, sname, i, &terms, 0) > 1)
            anybus = TRUE;
    }
    if (!anybus) {
        /* every formal a plain node: as before, the formal names on the currents */
        struct card *r;
        char **fn = TMALLOC(char *, na);
        for (i = 0; i < na; i++)
            fn[i] = formals[i];
        r = probe_splice(card, instname, thisline, thisline, numnodes, fn, NULL);
        tfree(fn);
        for (i = 0; i < na; i++) tfree(actuals[i]);
        tfree(actuals); tfree(sname);
        probe_free_formals(formals, nf);
        ds_free(&dnewline);
        return r;
    }

    sadd(&dnewline, instname);
    cadd(&dnewline, ' ');
    for (i = 0; i < na; i++) {
        char **terms = NULL;
        int bits = probe_formal_bits(deck, sname, i, &terms, 0);
        char *inner = tprintf("probe_int_%s_%s_%d", actuals[i], instname, i + 1);
        sadd(&dnewline, inner);
        cadd(&dnewline, ' ');
        if (bits > 1) {
            int k;
            for (k = 0; k < bits; k++) {
                const char *lb = terms[k] ? strchr(terms[k], '[') : NULL;
                char sfx[64], usfx[64];
                INPbusBitSuffix(lb ? lb : "", kicad, sfx, sizeof sfx);
                INPbusBitSuffix(lb ? lb : "", TRUE, usfx, sizeof usfx);
                char *vline = tprintf("vcurr_%s:%s%s:%s%s_%d %s%s %s%s 0", instname, formals[i], usfx,
                                      actuals[i], sfx, i + 1, actuals[i], sfx, inner, sfx);
                card = insert_new_line(card, vline, 0, card->linenum_orig, card->linesource);
                allsaves = wl_cons(tprintf("%s:%s%s#branch", instname, formals[i], usfx), allsaves);
            }
        } else {
            char *vline = tprintf("vcurr_%s:%s:%s_%d %s %s 0", instname, formals[i], actuals[i], i + 1,
                                  actuals[i], inner);
            card = insert_new_line(card, vline, 0, card->linenum_orig, card->linesource);
            if (strstr(actuals[i], "unconnected")) {   /* KiCad's open pin */
                char *rline = tprintf("r%s%d %s 0 1e15", actuals[i], nn++, actuals[i]);
                card = insert_new_line(card, rline, 0, card->linenum_orig, card->linesource);
            }
            allsaves = wl_cons(tprintf("%s:%s#branch", instname, formals[i]), allsaves);
        }
        tfree(inner);
    }
    sadd(&dnewline, rest);
    tfree(prevcard->line);
    prevcard->line = copy(ds_get_buf(&dnewline));
    ds_free(&dnewline);
    if (allsaves) {
        char *newline;
        allsaves = wl_cons(copy(".save"), allsaves);
        newline = wl_flatten(allsaves);
        wl_free(allsaves);
        card = insert_new_line(card, newline, 0, card->linenum_orig, card->linesource);
    }
    for (i = 0; i < na; i++) tfree(actuals[i]);
    tfree(actuals); tfree(sname);
    probe_free_formals(formals, nf);
    return card;
}

/* Enhancement-628 (hunt F11): the `.probe alli` pass over the deck's OSDI
 * lines, run from inp_spsource once the pre_ commands have loaded the .osdi
 * objects and the autobus option has been resolved -- so a shorthand line
 * can be written out against its model's ports and every terminal current
 * measured under the model's own terminal name. A line whose model does not
 * resolve is spliced as the generic pass would have. */
void inp_probe_osdi(struct card *deck)
{
    struct card *card;
    int skip_control = 0, skip_subckt = 0;
    bool kicad = FALSE, autobus;

    if (!probe_osdi_pending)
        return;
    probe_osdi_pending = FALSE;
    autobus = inp_get_autobus(&kicad);

    for (card = deck; card; card = card->nextcard) {
        char *curr_line = card->line, *instname, *thisline, *expanded = NULL;
        char **osdi_terms = NULL;
        int numnodes;

        if (ciprefix(".control", curr_line)) { skip_control++; continue; }
        if (ciprefix(".endc", curr_line)) { skip_control--; continue; }
        if (skip_control > 0) continue;
        if (ciprefix(".subckt", curr_line)) { skip_subckt++; continue; }
        if (ciprefix(".ends", curr_line)) { skip_subckt--; continue; }
        if (skip_subckt > 0) continue;
        if (*curr_line == '*' || *curr_line == '.' || *curr_line == '\0')
            continue;
        if (*curr_line != 'n' && *curr_line != 'x')
            continue;
        if (*curr_line == 'x' && cp_getvar("probe_alli_nox", CP_BOOL, NULL, 0))
            continue;                   /* as the generic pass has it */
        instname = gettok_instance(&curr_line);
        if (!instname)
            continue;
        numnodes = get_number_terminals(card->line);
        if (check_for_nodes(card->line, numnodes)) {
            fprintf(stderr, "Error: Not enough tokens in line %d\n%s\n", card->linenum_orig, card->line);
            fprintf(stderr, "    Please correct your input file\n");
            controlled_exit(EXIT_BAD);
        }
        thisline = curr_line;
        if (*instname == 'x') {
            card = probe_splice_x(deck, card, instname, thisline, numnodes, kicad);
            tfree(instname);
            continue;
        }
        {
            int pstart[PROBE_MAXPORT], pcnt[PROBE_MAXPORT];
            IFdevice *dev = NULL;
            int np = probe_osdi_ports(deck, card->line, pstart, pcnt, &dev);
            if (np > 0 && dev && dev->terms) {
                int terms = *dev->terms;
                if (numnodes == np && np < terms && autobus) {
                    expanded = probe_expand_bus_line(thisline, np, pstart, pcnt, dev, kicad);
                    if (expanded) {
                        thisline = expanded;
                        numnodes = terms;
                    }
                }
                if (numnodes == terms)
                    osdi_terms = dev->termNames;
            }
        }
        card = probe_splice(card, instname, thisline, curr_line, numnodes, osdi_terms, NULL);
        tfree(expanded);
        tfree(instname);
    }
}

void inp_probe(struct card* deck)
{
    struct card *card;
    int skip_control = 0;
    int skip_subckt = 0;
    wordlist* probes = NULL, *probeparams = NULL, *wltmp, *allsaves = NULL;
    bool haveall = FALSE, havedifferential = FALSE, t = TRUE, havesave = FALSE;
    NGHASHPTR instances;   /* instance hash table */
    int ee = 0; /* serial number for sources */

    for (card = deck; card; card = card->nextcard) {
        /* get the .probe netlist lines, comment them out */
        if (ciprefix(".probe", card->line)) {
            probes = wl_cons(card->line, probes);
            *(card->line) = '*';
        }
    }
    /* no .probe command */
    if (probes == NULL)
        return;

    /* check for '.save' and (in a .control section) 'save'.
       If not found, add '.save all' */
    for (card = deck; card; card = card->nextcard) {
        /* find .save */
        if (ciprefix(".save", card->line)) {
            havesave = TRUE;
            break;
        }
        /* exclude any command inside .control ... .endc */
        else if (ciprefix(".control", card->line)) {
            skip_control++;
            continue;
        }
        else if (ciprefix(".endc", card->line)) {
            skip_control--;
            continue;
        }
        else if (skip_control > 0) {
            if (ciprefix("save ", card->line)) {
                havesave = TRUE;
                break;
            }
        }
    }
    skip_control = 0;

    if (!havesave) {
        char* vline = copy(".save all");
        /* Enhancement-605: `deck` is the first card after the title, and the
         * line went in right after it -- INSIDE a .control block that opens
         * the deck (every OSDI deck opens with one, for `pre_osdi`), where it
         * ran as a command: ".save: no such command available in ngspice".
         * It goes after that block's .endc. And `deck` itself is no longer
         * moved onto the inserted card: the walks below start at the first
         * card again, so a probed device on the deck's first line is seen. */
        struct card *at = probe_head(deck);
        insert_new_line(at, vline, 0, at->linenum_orig, at->linesource);
    }

    /* set a variable if .probe command is given */
    cp_vset("probe_is_given", CP_BOOL, &t);

    /* Assemble all .probe parameters in a wordlist 'probeparams' */
    for (wltmp = probes; wltmp; wltmp = wltmp->wl_next) {
        char* nextnode;
        char* tmpstr = wltmp->wl_word;
        /* skip *probe */
        tmpstr = nexttok(tmpstr);

        if (*tmpstr == '\0') {
            fprintf(stderr, "Note: Empty .probe command, treated as .probe alli\n");
            haveall = TRUE;
            continue;
        }

        /* set haveall and remove 'alli' token */
        char *allistr = search_plain_identifier(tmpstr, "alli");
        if (allistr) {
            haveall = TRUE;
            memcpy(allistr, "    ", 4);
        }

        tmpstr = skip_ws(tmpstr);
        {
            /* Enhancement-430: one message per bad token, not two. */
            bool rejected = FALSE;

            if (!strchr("vipVIP", *tmpstr)) {
                probe_reject_token(wltmp->wl_word, tmpstr);
                rejected = TRUE;
                tmpstr = nexttok(tmpstr);
            }
            nextnode = gettok_char(&tmpstr, ')', TRUE, FALSE);

            if (haveall == FALSE && !nextnode) {
                if (!rejected)
                    probe_reject_token(wltmp->wl_word, tmpstr);
                continue;
            }
        }

        while (nextnode && (*nextnode != '\0')) {
            probeparams = wl_cons(nextnode, probeparams);

            if (ciprefix("vd(", nextnode)) {
                havedifferential = TRUE;
            }

            nextnode = gettok_char(&tmpstr, ')', TRUE, FALSE);
        }
    }
    /* don't free the wl_word, they belong to the cards */
    tfree(probes);

    /* Set up the hash table for all instances (instance name is key, data
       is the storage location of the card) */
    instances = nghash_init(100);
    nghash_unique(instances, TRUE);

    for (card = deck; card; card = card->nextcard) {
        char* curr_line = card->line;

        /* exclude any command inside .control ... .endc */
        if (ciprefix(".control", curr_line)) {
            skip_control++;
            continue;
        }
        else if (ciprefix(".endc", curr_line)) {
            skip_control--;
            continue;
        }
        else if (skip_control > 0) {
            continue;
        }
        /* exclude any device or command inside .subckt ... .ends */
        if (ciprefix(".subckt", curr_line)) {
            skip_subckt++;
            continue;
        }
        else if (ciprefix(".ends", curr_line)) {
            skip_subckt--;
            continue;
        }
        else if (skip_subckt > 0) {
            continue;
        }
        if (*curr_line == '*')
            continue;
        if (*curr_line == '.')
            continue;
        if (*curr_line == '\0')
            continue;

        /* here we should go on with only true device instances at top level.
           Put all instance names as key into a hash table, with the address as parameter. */
           /* Get the instance name as key */
        char* instname = gettok_instance(&curr_line);
        if (!instname)
            continue;
        nghash_insert(instances, instname, card);
    }

    if (haveall || probeparams == NULL) {
        /* Either we have 'alli' among the .probe parameters, or we have a single .probe command without parameters:
           Add current measure voltage sources for all devices, add differential E sources only for selected devices. */
        int numnodes;

        for (card = deck; card; card = card->nextcard) {

            char* curr_line = card->line;

            /* exclude any command inside .control ... .endc */
            if (ciprefix(".control", curr_line)) {
                skip_control++;
                continue;
            }
            else if (ciprefix(".endc", curr_line)) {
                skip_control--;
                continue;
            }
            else if (skip_control > 0) {
                continue;
            }
            /* exclude any device or command inside .subckt ... .ends */
            if (ciprefix(".subckt", curr_line)) {
                skip_subckt++;
                continue;
            }
            else if (ciprefix(".ends", curr_line)) {
                skip_subckt--;
                continue;
            }
            else if (skip_subckt > 0) {
                continue;
            }
            if (*curr_line == '*')
                continue;
            if (*curr_line == '.')
                continue;
            if (*curr_line == '\0')
                continue;

            char* instname = gettok_instance(&curr_line);
            if (!instname)
                continue;

            /* select elements not in need of a measure Vsource */
            if (strchr("ehvk", *instname))
                continue;

            /* exclude B voltage source */
            if (strchr("b", *instname) && strstr(curr_line, "v="))
                continue;

            /* exclude a devices (code models may have special characters in their instance line.
            digital nodes should not get V sources in series anyway.) */
            if ('a' == *instname)
                continue;

            /* exclude x devices (Subcircuits may contain digital a devices,
            and digital nodes should not get V sources in series anyway.),
            when probe_alli_nox is set in .spiceinit. */
            if ('x' == *instname && cp_getvar("probe_alli_nox", CP_BOOL, NULL, 0))
                continue;

            /* special treatment for controlled current sources and switches:
               We have three or four tokens until model name, but only the first 2 are relevant nodes. */
            if (strchr("fgsw", *instname))
                numnodes = 2;
            else
                numnodes = get_number_terminals(card->line);

            if (check_for_nodes(card->line, numnodes)) {
                fprintf(stderr, "Error: Not enough tokens in line %d\n%s\n", card->linenum_orig, card->line);
                fprintf(stderr, "    Please correct your input file\n");
                controlled_exit(EXIT_BAD);
            }

            char* thisline = curr_line;

#ifdef OSDI
            /* Enhancement-628 (hunt F11): an OSDI line, and a subcircuit call
             * (whose formals may stand for OSDI bus ports inside), are left to
             * inp_probe_osdi(), which runs once `pre_osdi` has registered the
             * modules and the deck's .model cards can name their ports --
             * here, during the deck read, nothing is registered yet */
            if (*instname == 'n' || *instname == 'x') {
                probe_osdi_pending = TRUE;
                tfree(instname);
                continue;
            }
#endif
            card = probe_splice(card, instname, thisline, curr_line, numnodes, NULL, instances);
            tfree(instname);
        }
    }

    if (probeparams) {
        /* There are .probe with parameters:
           Add current measure voltage sources only for the selected devices.
           Add differential probes only if 'all' had been found. */
        for (wltmp = probeparams; wltmp; wltmp = wltmp->wl_next) {
            char *tmpstr = wltmp->wl_word;
            ee++;
            /* check for differential voltage probes:
               v(nR1) voltage at node named nR1
               vd(R1) voltage across a two-terminal device named R1
               vd(m4:1:0) voltage at instance node 1 of device m4
               vd(m4:1:3) voltage between instance nodes 1 and 3 of device m4
               vd(m4:1, m5:3) voltage between instance node 1 of device m4 and node 3 of device m5 */
               /* no nodes after first token: must be a node itself */

            /* v(nodename), voltage at node named nodename */
            if (ciprefix("v(", tmpstr)) {
                char* instname1 = gettok_char(&tmpstr, ')', TRUE, FALSE);
                allsaves = wl_cons(copy(instname1), allsaves);
                continue;
            }
            /* vd(R1), vd(R1:1,R2:1), vd(MN4:d:s), vd(QN4:1:3), vd(nodename,MN5:d), vd(nodename1,nodename2) */
            else  if (ciprefix("vd(", tmpstr)) {
                char* instname1, *instname2;
                int numnodes1, numnodes2;
                struct card* tmpcard1;

                /* skip vd_ */
                tmpstr += 3;

                /* vd(R1)
                   vd(nodename1,nodename2) */
                if (!strchr(tmpstr, ':')) {
                    char* newline = NULL, *strnode1, *strnode2, *tmpstr2;
                    tmpstr2 = tmpstr;
                    strnode1 = gettok_char(&tmpstr2, ',', FALSE, FALSE);
                    if (strnode1) {
                        tmpstr2++; /* beyond ',' */
                        strnode2 = gettok_char(&tmpstr2, ')', FALSE, FALSE);
                        if (!strnode2) {
                        }
                        else {
                            newline = tprintf("ediff%d_nodes vd_%s:%s 0 %s %s 1", ee, strnode1, strnode2, strnode1, strnode2);

                            char* nodesaves = tprintf("vd_%s:%s", strnode1, strnode2);
                            allsaves = wl_cons(nodesaves, allsaves);
                            tfree(strnode1);
                            tfree(strnode2);
                            tmpcard1 = probe_head(deck);    /* Enhancement-605 */
                            tmpcard1 = insert_new_line(tmpcard1, newline, 0, tmpcard1->linenum_orig, tmpcard1->linesource);
                        }
                        continue;
                    }

                    instname1 = gettok_char(&tmpstr, ')', FALSE, FALSE);
                    tmpcard1 = nghash_find(instances, instname1);
                    if (!tmpcard1) {
                        fprintf(stderr, "Warning: Could not find the instance line for %s,\n   .probe %s will be ignored\n", instname1, wltmp->wl_word);
                        tfree(instname1);
                        continue;
                    }
                    char* thisline = tmpcard1->line;
                    numnodes1 = get_number_terminals(thisline);
                    if (numnodes1 != 2) {
                        fprintf(stderr, "Warning: Instance %s has more than 2 nodes,\n   .probe %s will be ignored\n", instname1, wltmp->wl_word);
                        tfree(instname1);
                        continue;
                    }
                    thisline = nexttok(thisline); /* skip instance name */
                    strnode1 = gettok(&thisline);
                    strnode2 = gettok(&thisline);
                    if (!strnode2 || *strnode2 == '\0') {
                        fprintf(stderr, "Warning: Cannot read 2 nodes in line %s\n", tmpcard1->line);
                        fprintf(stderr, "    Instance not ready for .probe command\n");
                        tfree(strnode1);
                        tfree(strnode2);
                        continue;
                    }
                    newline = tprintf("ediff%d_%s vd_%s 0 %s %s 1", ee, instname1, instname1, strnode1, strnode2);

                    char* nodesaves = tprintf("vd_%s", instname1);
                    allsaves = wl_cons(nodesaves, allsaves);
                    tfree(strnode1);
                    tfree(strnode2);
                    tmpcard1 = insert_new_line(tmpcard1, newline, 0, tmpcard1->linenum_orig, tmpcard1->linesource);
                    continue;
                }
                /* node containing ':' 
                vd(R1:1,R2:2)
                vd(M4:1:3)
                vd(m5:d:s)*/
                else {
                    char* tmpstr2, *nodename1, *nodename2;
                    struct card* tmpcard2;
                    tmpstr2 = tmpstr;
                    instname1 = gettok_char(&tmpstr, ':', FALSE, FALSE);
                    if (!instname1) {
                        fprintf(stderr, "Warning: Cannot read instance name in %s, ignored\n", tmpstr);
                        continue;
                    }
                    tmpcard1 = nghash_find(instances, instname1);
                    if (!tmpcard1) {
                        fprintf(stderr, "Warning: Could not find the instance line for %s,\n   .probe %s will be ignored\n", instname1, wltmp->wl_word);
                        tfree(instname1);
                        continue;
                    }
                    char* thisline = tmpcard1->line;
                    numnodes1 = get_number_terminals(thisline);
                    tmpstr++;
                    tmpstr2 = tmpstr;
                    nodename1 =  gettok_char(&tmpstr2, ',', FALSE, FALSE);
                    if (nodename1) {
                        /* vd(R1:1,R2:2) */
                        int nodenum1, nodenum2, i;
                        char* ptr, *node1, *node2, *strnode1, *strnode2;
                        bool err = FALSE;

                        tmpstr2++; /* beyond ',' */
                        instname2 = gettok_char(&tmpstr2, ':', FALSE, FALSE);
                        if (!instname2) {
                            fprintf(stderr, "Warning: Cannot read instance name in %s, ignored\n", tmpstr);
                            tfree(nodename1);
                            continue;
                        }
                        tmpstr2++; /* beyond ':' */
                        tmpcard2 = nghash_find(instances, instname2);
                        if (!tmpcard2) {
                            fprintf(stderr, "Warning: Could not find the instance line for %s,\n   .probe %s will be ignored\n", instname2, wltmp->wl_word);
                            tfree(instname2);
                            tfree(nodename1);
                            continue;
                        }
                        char* thisline2 = tmpcard2->line;
                        numnodes2 = get_number_terminals(thisline2);
                        nodename2 = gettok_char(&tmpstr2, ')', FALSE, FALSE);
                        if (!nodename2) {
                            fprintf(stderr, "Warning: Could not find the second node name for %s,\n   .probe %s will be ignored\n", instname2, wltmp->wl_word);
                            tfree(instname2);
                            tfree(nodename1);
                            continue;
                        }
                        /* nodenames may be numbers or characters, we always need the numbers */
                        node1 = get_terminal_number(instname1, nodename1);
                        if (eq(node1, "0")) {
                            fprintf(stderr, "Warning: Node %s is not available for device %s,\n   .probe %s will be ignored\n", node1, instname1, wltmp->wl_word);
                            continue;
                        }
                        node2 = get_terminal_number(instname2, nodename2);
                        if (eq(node2, "0")) {
                            fprintf(stderr, "Warning: Node %s is not available for device %s,\n   .probe %s will be ignored\n", node1, instname2, wltmp->wl_word);
                            continue;
                        }

                        /* nodes are numbered 1, 2, 3, ... */
                        nodenum1 = (int)strtol(node1, &ptr, 10);
                        nodenum2 = (int)strtol(node2, &ptr, 10);

                        if (nodenum1 > numnodes1) {
                            fprintf(stderr, "Warning: There are only %d nodes available for %s,\n   .probe %s will be ignored!\n", numnodes1, instname1, wltmp->wl_word);
                            continue;
                        }
                        if (nodenum2 > numnodes2) {
                            fprintf(stderr, "Warning: There are only %d nodes available for %s,\n   .probe %s will be ignored!\n", numnodes2, instname2, wltmp->wl_word);
                            continue;
                        }
                        if (nodenum1 == nodenum2 && eq(instname1, instname2)) {
                            fprintf(stderr, "Warning: Duplicate node numbers and instances,\n   .probe %s will be ignored!\n", wltmp->wl_word);
                            continue;
                        }
                        /* if node1 is the 0 node*/
                        if (nodenum1 == 0) {
                            strnode1 = copy("0");
                        }
                        else {
                            /* skip instance and leading nodes not wanted */
                            for (i = 0; i < nodenum1; i++) {
                                thisline = nexttok(thisline);
                                if (*thisline == '\0') {
                                    fprintf(stderr, "Warning: node number %d not available for instance %s, ignored!\n", nodenum1, instname1);
                                    err = TRUE;
                                    break;
                                }
                            }
                            if (err)
                                continue;

                            strnode1 = gettok(&thisline);
                        }

                        /* if node2 is the 0 node*/
                        if (nodenum2 == 0) {
                            strnode2 = copy("0");
                        }
                        else {
                            /* skip instance and leading nodes not wanted */
                            for (i = 0; i < nodenum2; i++) {
                                thisline2 = nexttok(thisline2);
                                if (*thisline2 == '\0') {
                                    fprintf(stderr, "Warning: node number %d not available for instance %s, ignored!\n", nodenum2, instname2);
                                    err = TRUE;
                                    break;
                                }
                            }
                            if (err)
                                continue;

                            strnode2 = gettok(&thisline2);
                        }

                        /* preserve the 0 node */
                        if (*node1 == '0') {
                            nodename1 = copy("0");
                        }
                        else {
                            if (*node1 != '\0' && atoi(node1) == 0) {
                                char* nn = get_terminal_number(instname1, node1);
                                tfree(node1);
                                node1 = copy(nn);
                            }
                            nodename1 = get_terminal_name(instname1, node1, instances);
                        }

                        /* preserve the 0 node */
                        if (*node2 == '0') {
                            nodename2 = copy("0");
                        }
                        else {
                            if (*node2 != '\0' && atoi(node2) == 0) {
                                char* nn = get_terminal_number(instname2, node2);
                                tfree(node2);
                                node2 = copy(nn);
                            }
                            nodename2 = get_terminal_name(instname2, node2, instances);
                        }
                        char *newline = tprintf("ediff%d_%s_%s vd_%s:%s_%s:%s 0 %s %s 1", ee, instname1, instname2, instname1, nodename1, instname2, nodename2, strnode1, strnode2);
                        char* nodesaves = tprintf("vd_%s:%s_%s:%s", instname1, nodename1, instname2, nodename2);
                        allsaves = wl_cons(nodesaves, allsaves);
                        tmpcard1 = insert_new_line(tmpcard1, newline, 0, tmpcard1->linenum_orig, tmpcard1->linesource);
                        tfree(strnode1);
                        tfree(strnode2);
                        tfree(nodename1);
                        tfree(nodename2);

                    }
                    else {
                        /* vd(M4:1:3) */
                        int nodenum1, nodenum2, i;
                        char* ptr, * node1, * node2, * strnode1, * strnode2;
                        bool err = FALSE;
                        char* thisline2 = thisline;

                        tmpstr2 = tmpstr;
                        nodename1 =  gettok_char(&tmpstr2, ':', FALSE, FALSE);
                        if (!nodename1) {
                            fprintf(stderr, "Warning: Could not find the first node name for %s,\n   .probe %s will be ignored\n", instname1, wltmp->wl_word);
                            tfree(instname1);
                            continue;
                        }
                        tmpstr2++;
                        nodename2 =  gettok_char(&tmpstr2, ')', FALSE, FALSE);
                        if (!nodename1 || !nodename2) {
                            fprintf(stderr, "Warning: Could not find the second node name for %s,\n   .probe %s will be ignored\n", instname1, wltmp->wl_word);
                            tfree(instname1);
                            tfree(nodename1);
                            continue;
                        }
                        /* nodenames may be numbers or characters, we always need the numbers */
                        node1 = get_terminal_number(instname1, nodename1);
                        node2 = get_terminal_number(instname1, nodename2);
                        if (eq(node1, "0") && eq(node2, "0")) {
                            fprintf(stderr, "Warning: Either first or second node have to be non-zero,\n   .probe %s will be ignored\n", wltmp->wl_word);
                            continue;
                        }

                        /* nodes are numbered 1, 2, 3, ... */
                        nodenum1 = (int)strtol(node1, &ptr, 10);
                        nodenum2 = (int)strtol(node2, &ptr, 10);

                        if (nodenum1 > numnodes1) {
                            fprintf(stderr, "Warning: There are only %d nodes available for %s,\n   .probe %s will be ignored!\n", numnodes1, instname1, wltmp->wl_word);
                            continue;
                        }
                        if (nodenum2 > numnodes1) {
                            fprintf(stderr, "Warning: There are only %d nodes available for %s,\n   .probe %s will be ignored!\n", numnodes1, instname1, wltmp->wl_word);
                            continue;
                        }
                        if (nodenum1 == nodenum2) {
                            fprintf(stderr, "Warning: Duplicate node numbers,\n   .probe %s will be ignored!\n", wltmp->wl_word);
                            continue;
                        }
                        /* if node1 is the 0 node*/
                        if (nodenum1 == 0) {
                            strnode1 = copy("0");
                        }
                        else {
                            /* skip instance and leading nodes not wanted */
                            for (i = 0; i < nodenum1; i++) {
                                thisline2 = nexttok(thisline2);
                                if (*thisline2 == '\0') {
                                    fprintf(stderr, "Warning: node number %d not available for instance %s, ignored!\n", nodenum1, instname1);
                                    err = TRUE;
                                    break;
                                }
                            }
                            if (err)
                                continue;

                            strnode1 = gettok(&thisline2);
                        }

                        thisline2 = thisline;
                        /* if node2 is the 0 node*/
                        if (nodenum2 == 0) {
                            strnode2 = copy("0");
                        }
                        else {
                            /* skip instance and leading nodes not wanted */
                            for (i = 0; i < nodenum2; i++) {
                                thisline2 = nexttok(thisline2);
                                if (*thisline2 == '\0') {
                                    fprintf(stderr, "Warning: node number %d not available for instance %s, ignored!\n", nodenum2, instname1);
                                    err = TRUE;
                                    break;
                                }
                            }
                            if (err)
                                continue;

                            strnode2 = gettok(&thisline2);
                        }

                        /* preserve the 0 node */
                        if (*node1 == '0') {
                            nodename1 = copy("0");
                        }
                        else {
                            if (*node1 != '\0' && atoi(node1) == 0) {
                                char* nn = get_terminal_number(instname1, node1);
                                tfree(node1);
                                node1 = copy(nn);
                            }
                            nodename1 = get_terminal_name(instname1, node1, instances);
                        }

                        /* preserve the 0 node */
                        if (*node2 == '0') {
                            nodename2 = copy("0");
                        }
                        else {
                            if (*node2 != '\0' && atoi(node2) == 0) {
                                char* nn = get_terminal_number(instname1, node2);
                                tfree(node2);
                                node2 = copy(nn);
                            }
                            nodename2 = get_terminal_name(instname1, node2, instances);
                        }
                        char* newline = tprintf("ediff%d_%s vd_%s:%s:%s 0 %s %s 1", ee, instname1, instname1, nodename1, nodename2, strnode1, strnode2);
                        char* nodesaves = tprintf("vd_%s:%s:%s", instname1, nodename1, nodename2);
                        allsaves = wl_cons(nodesaves, allsaves);
                        tmpcard1 = insert_new_line(tmpcard1, newline, 0, tmpcard1->linenum_orig, tmpcard1->linesource);
                        tfree(strnode1);
                        tfree(strnode2);
                        tfree(nodename1);
                        tfree(nodename2);
                    }
                }
            }

            /* No .probe parameter 'alli' (has been treated already), but dedicated current probes requested */
            else if (!haveall && ciprefix("i(", tmpstr)) {
                char* instname, * node1 = NULL, *nodename1;
                struct card* tmpcard;
                int numnodes;

                tmpstr += 2;

                /* Replace a : by , to enable i(mn1:s) equivalent to i(mn1,s) */
                char* co = strchr(tmpstr, ':');
                if (co) {
                    *co = ',';
                }

                instname = gettok_noparens(&tmpstr);
                tmpcard = nghash_find(instances, instname);
                if (!tmpcard) {
                    fprintf(stderr, "Warning: Could not find the instance line for %s,\n   .probe %s will be ignored\n", instname, wltmp->wl_word);
                    continue;
                }
                char* thisline = tmpcard->line;

                /* special treatment for controlled current sources and switches:
                   We have three or four tokens until model name, but only the first 2 are relevant nodes. */
                if (strchr("fgsw", *instname))
                    numnodes = 2;
                else
                    numnodes = get_number_terminals(thisline);

                if (check_for_nodes(tmpcard->line, numnodes)) {
                    fprintf(stderr, "Error: Not enough tokens in line %d\n%s\n", tmpcard->linenum_orig, tmpcard->line);
                    fprintf(stderr, "    Please correct your input file\n");
                    controlled_exit(EXIT_BAD);
                }

                /* skip ',' */
                if (*tmpstr == ',')
                    tmpstr++;

                /* read the input for node1: either a number or a (device dependent) name */
                node1 = gettok_noparens(&tmpstr);
                if (*node1 != '\0' && atoi(node1) == 0) {
                    char *nn = get_terminal_number(instname, node1);
                    if (eq(nn, "0")) {
                        fprintf(stderr, "Warning: Node %s is not available for device %s,\n   .probe %s will be ignored\n", node1, instname, wltmp->wl_word);
                        tfree(node1);
                        continue;
                    }

                    tfree(node1);
                    node1 = copy(nn);
                }

                if (node1 && *node1 == '\0') {
                    node1 = NULL;
                    nodename1 = copy("nn");
                }
                else
                    nodename1 = get_terminal_name(instname, node1, instances);

                /* i(R3): add voltage source always to second node */
                if (!node1 && numnodes == 2) {
                    char* newline, *strnode2, *nodename2;
                    /* skip instance */
                    thisline = nexttok(thisline);
                    /* skip first node */
                    thisline = nexttok(thisline);
                    char* begstr = copy_substring(tmpcard->line, thisline);
                    strnode2 = gettok(&thisline);

                    nodename2 = get_terminal_name(instname, "2", instances);

                    char* newnode = tprintf("probe_int_%s_%s_2", strnode2, instname);
                    char* vline = tprintf("vcurr_%s:%s_%s %s %s 0", instname, nodename2, strnode2, newnode, strnode2);
                    newline = tprintf("%s %s %s", begstr, newnode, thisline);

                    char* nodesaves = tprintf("%s#branch", instname);
                    allsaves = wl_cons(nodesaves, allsaves);

                    tfree(tmpcard->line);
                    tmpcard->line = newline;
                    tmpcard = insert_new_line(tmpcard, vline, 0, tmpcard->linenum_orig, tmpcard->linesource);

                    tfree(strnode2);
                    tfree(newnode);
                    tfree(begstr);
                    tfree(nodename1);
                    tfree(nodename2);
                }
                else if (!node1 && numnodes > 2) {
                    int err = 0;
                    tfree(nodename1);
                    err = setallvsources(tmpcard, instances, instname, numnodes, haveall, FALSE);
                    if (err) {
                        fprintf(stderr, "Warning: Cannot set zero voltage sources,\n   .probe %s will be ignored\n", wltmp->wl_word);
                    }
                    continue;
                }
                /* i(X1, 2): add voltage source to user defined node */
                else if (node1 && *node1 != '\0') {
                    char* newline, * ptr;
                    int nodenum;
                    int i;
                    bool err = FALSE;
                    /* nodes are numbered 1, 2, 3, ... */
                    nodenum = (int)strtol(node1, &ptr, 10);
                    if (nodenum > numnodes) {
                        fprintf(stderr, "Warning: There are only %d nodes available for %s,\n   .probe %s will be ignored\n", numnodes, instname, wltmp->wl_word);
                        continue;
                    }

                    /* skip instance and leading nodes not wanted */
                    for (i = 0; i < nodenum; i++) {
                        thisline = nexttok(thisline);
                        if (*thisline == '\0') {
                            fprintf(stderr, "Warning: node number %d not available for instance %s!\n", nodenum, instname);
                            err = TRUE;
                            break;
                        }
                    }
                    if (err)
                        continue;

                    char* begstr = copy_substring(tmpcard->line, thisline);

                    char* strnode1 = gettok(&thisline);

                    char* newnode = tprintf("probe_int_%s_%s_%d", strnode1, instname, nodenum);

                    newline = tprintf("%s %s %s", begstr, newnode, thisline);

                    char* vline = tprintf("vcurr_%s:%s:%s_%s %s %s 0", instname, nodename1, node1,  strnode1, strnode1, newnode);

                    tfree(tmpcard->line);
                    tmpcard->line = newline;
                    tmpcard = insert_new_line(tmpcard, vline, 0, tmpcard->linenum_orig, tmpcard->linesource);

                    char* nodesaves = tprintf("%s:%s#branch", instname, nodename1);
                    allsaves = wl_cons(nodesaves, allsaves);

                    tfree(begstr);
                    tfree(strnode1);
                    tfree(newnode);
                    tfree(nodename1);
                }
            }
            /* measure the power of a device */
            else if (ciprefix("p(", tmpstr))
            {
                char* instname;
                struct card* tmpcard;
                int numnodes;

                tmpstr += 2;
                instname = gettok_noparens(&tmpstr);
                tmpcard = nghash_find(instances, instname);
                if (!tmpcard) {
                    fprintf(stderr, "Warning: Could not find the instance line for %s,\n   .probe %s will be ignored\n", instname, wltmp->wl_word);
                    continue;
                }
                char* thisline = tmpcard->line;

                /* special treatment for controlled current sources and switches:
                   We have three or four tokens until model name, but only the first 2 are relevant nodes. */
                if (strchr("fgsw", *instname))
                    numnodes = 2;
                else
                    numnodes = get_number_terminals(thisline);

                if (numnodes < 2) {
                    fprintf(stderr, "Warning: Power mesasurement not available,\n   .probe %s will be ignored\n", wltmp->wl_word);
                    tfree(instname);
                    continue;
                }

                if (check_for_nodes(tmpcard->line, numnodes)) {
                    fprintf(stderr, "Error: Not enough tokens in line %d\n%s\n", tmpcard->linenum_orig, tmpcard->line);
                    fprintf(stderr, "    Please correct your input file\n");
                    controlled_exit(EXIT_BAD);
                }

                int err = 0;
                /* call fcn with power requested */
                err = setallvsources(tmpcard, instances, instname, numnodes, haveall, TRUE);
                if (err == 1) {
                    fprintf(stderr, "Warning: Cannot set zero voltage sources,\n   .probe %s will be ignored\n", wltmp->wl_word);
                }
                else if (err == 2) {
                    fprintf(stderr, "Warning: Zero voltage sources already set,\n   .probe %s will be ignored\n", wltmp->wl_word);
                }
                else if (err == 3) {
                    fprintf(stderr, "Warning: Number of nodes mismatch,\n   .probe %s will be ignored\n", wltmp->wl_word);
                }
                continue;
            }
            else if (!haveall) {
                fprintf(stderr, "Warning: unknown .probe parameter %s,\n   .probe %s will be ignored!\n", tmpstr, wltmp->wl_word);
                continue;
            }
        }
        if (allsaves) {
            allsaves = wl_cons(copy(".save"), allsaves);
            char* newline = wl_flatten(allsaves);
            wl_free(allsaves);
            allsaves = NULL;
            card = probe_head(deck);    /* Enhancement-605 */
            card = insert_new_line(card, newline, 0, card->linenum_orig, card->linesource);
        }

    }
    nghash_free(instances, NULL, NULL);
}

/* enter the element (instance) line and the node number (as string),
   get the node name, if defined (e.g. a for anode, c for cathode of a diode).
   If not (yet) defined, return "nx" (x is the node number) or "nn" */
static char *get_terminal_name(char* element, char *numberstr, NGHASHPTR instances)
{
    switch (*element) {
    case 'r':
    case 'c':
    case 'l':
    case 'k':
    case 'f':
    case 'h':
    case 'b':
    case 'v':
    case 'i':
        return tprintf("n%s", numberstr);
        break;
    case 'd':
        switch (*numberstr) {
        case 'a':
        case '1':
            return copy("a");
            break;
        case 'c':
        case 'k':
        case '2':
            return copy("c");
            break;
        default:
            return copy("nn");
            break;
        }
        break;
    case 'j':
    case 'z':
        switch (*numberstr) {
        case 'd':
        case '1':
            return copy("d");
            break;
        case 'g':
        case '2':
            return copy("g");
            break;
        case 's':
        case '3':
            return copy("s");
            break;
        default:
            return copy("nn");
            break;
        }
    case 'm':
        switch (*numberstr) {
        case 'd':
        case '1':
            return copy("d");
            break;
        case 'g':
        case '2':
            return copy("g");
            break;
        case 's':
        case '3':
            return copy("s");
            break;
        case 'b':
        case '4':
            return copy("b_tj");
            break;
        case '5':
            return copy("tc");
            break;
        case '6':
            return copy("n6");
            break;
        case '7':
            return copy("n7");
            break;
        default:
            return copy("nn");
            break;
        }

    case 'q':
        switch (*numberstr) {
        case 'c':
        case '1':
            return copy("c");
            break;
        case 'b':
        case '2':
            return copy("b");
            break;
        case 'e':
        case '3':
            return copy("e");
            break;
        case 's':
        case '4':
            return copy("s");
            break;
        case '5':
            return copy("t");
            break;
        default:
            return copy("nn");
            break;
        }

    case 'x':
        /* This should be the names of the corresponding subcircuit:
           Get the subckt name from the x line
           Search for the corresponding .subckt line
           Find the numberstr node name of the .subckt
           */
    {
        int i;
        char* subcktname, * ptr, * xcardsubsline = NULL, * subsnodestr;
        struct card* xcard = nghash_find(instances, element);
        char* thisline = xcard->line;
        int numnodes = get_number_terminals(thisline);
        int nodenumber = (int)strtol(numberstr, &ptr, 10);
        /*Get the subckt name from the x line*/
        for (i = 0; i <= numnodes; i++)
            thisline = nexttok(thisline);
        subcktname = gettok(&thisline);

        /*Search for the corresponding .subckt line*/
        struct card_assoc* allsubs = xcard->level->subckts;

        if (!allsubs) {
            char* instline = xcard->line;
            char* inst = gettok(&instline);
            fprintf(stderr, "Instance '%s' does not have an corresponding subcircuit '%s'!\n", inst, subcktname);
            fprintf(stderr, "    Is the model missing? .probe cannot determine subcircuit pin names.\n");
            tfree(subcktname);
            tfree(inst);
            return tprintf("n%s", numberstr);
        }

        while (allsubs) {
            xcardsubsline = allsubs->line->line;
            /* safeguard against NULL pointers) */
            if (!subcktname || !allsubs->name) {
                tfree(subcktname);
                return tprintf("n%s", numberstr);
            }
            if (cieq(subcktname, allsubs->name))
                break;
            allsubs = allsubs->next;
        }
        /*Find the numberstr node name of the .subckt*/
        for (i = 1; i < nodenumber + 2; i++) {
            xcardsubsline = nexttok(xcardsubsline);
        }
        subsnodestr = gettok(&xcardsubsline);
        tfree(subcktname);
        return subsnodestr;
        break;
    }
/* the following are not (yet) supported */
    case 'u':
    case 'w':
    case 't':
    case 'o':
    case 'g':
    case 'e':
    case 's':
    case 'y':
    case 'p':
        return tprintf("n%s", numberstr);
        break;

    default:
        return copy("nn");
        break;
    }
}

/* enter the element (instance) line and the node name,
   if defined (e.g. a for anode, c for cathode of a diode)
   return the node number. If there is no regular node
   name, return "0". */
static char* get_terminal_number(char* element, char* namestr)
{
    switch (*element) {
    case 'r':
    case 'c':
    case 'l':
    case 'k':
    case 'f':
    case 'h':
    case 'b':
    case 'v':
    case 'i':
        return "0";
        break;
    case 'd':
        switch (*namestr) {
        case 'a':
        case '1':
            return "1";
            break;
        case 'c':
        case 'k':
        case '2':
            return "2";
            break;
        default:
            return "0";
            break;
        }
        break;
    case 'j':
    case 'z':
        switch (*namestr) {
        case 'd':
        case '1':
            return "1";
            break;
        case 'g':
        case '2':
            return "2";
            break;
        case 's':
        case '3':
            return "3";
            break;
        default:
            return "0";
            break;
        }
    case 'm':
        switch (*namestr) {
        case 'd':
        case '1':
            return "1";
            break;
        case 'g':
        case '2':
            return "2";
            break;
        case 's':
        case '3':
            return "3";
            break;
        case 'b':
        case '4':
            return "4";
            break;
        case 't':
            switch (namestr[1]) {
            case 'j':
                return  "4";
                break;
            case 'c':
                return  "5";
                break;
            default:
                return "0";
            }
        case '5':
            return "5";
            break;
        case '6':
            return "6";
            break;
        case '7':
            return "7";
            break;
        default:
            return "0";
            break;
        }

    case 'q':
        switch (*namestr) {
        case 'c':
        case '1':
            return "1";
            break;
        case 'b':
        case '2':
            return "2";
            break;
        case 'e':
        case '3':
            return "3";
            break;
        case 's':
        case '4':
            return "4";
            break;
        case 't':
            return "5";
            break;
        default:
            return "nn";
            break;
        }

        /* the following are not (yet) supported */
    case 'x':
        if (isdigit_c(*namestr))
            return namestr;
        else
            return "0";
        break;

    case 'u':
    case 'w':
        //        return 3;
        //        break;
    case 't':
    case 'o':
    case 'g':
    case 'e':
    case 's':
    case 'y':
        //        return 4;
        if (isdigit_c(*namestr))
            return namestr;
        else
            return "0";
        break;

    case 'p':
        if (isdigit_c(*namestr))
            return namestr;
        else
            return "0";
        break;

    default:
        return "0";
        break;
    }
}

/* get new .save names from V instances from instance table.
   Called from inp.c*/
void modprobenames(INPtables* tab) {
    GENinstance* GENinst;
    if (tab && tab->defVmod && tab->defVmod->GENinstances) {
        for (GENinst = tab->defVmod->GENinstances; GENinst; GENinst = GENinst->GENnextInstance) {
            char* name = GENinst->GENname;
            if (prefix("vcurr_", name)) {
                /* copy from char no. 6 to (and excluding) second colon */
                char* endname2;
                char* endname = strchr(name, ':');
                if (endname)
                    endname2 = strchr(endname + 1, ':');
                else /* not a single colon, something different? */
                    continue;
                /* two-terminal device, one colon, copy all from char no. 6 to (and excluding) colon */
                if (!endname2) {
                    char* newname = copy_substring(name + 6, endname);
                    memcpy(name, newname, strlen(newname) + 1);
                    tfree(newname);
                }
                /* copy from char no. 6 to (and excluding) second colon */
                else {
                    char* newname = copy_substring(name + 6, endname2);
                    memcpy(name, newname, strlen(newname) + 1);
                    tfree(newname);
                }
            }
        }
    }
}

/* If a command like .probe i(Q1) is found, set 0 VSRC (voltage source) in series to all nodes of the device Q1.
   Polarity of VSRC is that its node 2 is directed towards the device, its node 1 towards the outer net connection. 
   If .probe p(Q1) is found, flag power is true, then do additional power calculations:
   Define a reference voltage of an n-terminal device as Vref = (V(1) + V(2) +...+ V(n)) / n  with terminal (node) voltages V(n).
   Calculate power PQ1 = (v(1) - Vref) * i1 + (V(2) - Vref) * i2 + ... + (V(n) - Vref) * in) with terminal currents in.
   See "Quantities of a Multiterminal Circuit Determined on the Basis of Kirchhoff�s Laws", M. Depenbrock, 
   ETEP Vol. 8, No. 4, July/August 1998.
   probe_int_ is used to trigger supressing the vectors when saving the results. Internal vectors thus are
   not saved. */
static int setallvsources(struct card *tmpcard, NGHASHPTR instances, char *instname, int numnodes, bool haveall, bool power)
{
    
    struct card* card;
    char* newline;
    int nodenum;
    int err = 0;
    wordlist * allsaves = NULL;

    if (haveall && !power)
        return 2;

    DS_CREATE(BVrefline, 200);
    DS_CREATE(Bpowerline, 200);
    DS_CREATE(Bpowersave, 200);

    if (power) {
        /* For example: bq1vref q1vref 0 v = 1/3*( */
        char numbuf[3];
        sadd(&BVrefline, "bprobe_int_");
        sadd(&BVrefline, instname);
        sadd(&BVrefline, "vref ");
        sadd(&BVrefline, instname);
        sadd(&BVrefline, "probe_int_vref 0 v = 1/");
        sadd(&BVrefline, itoa10(numnodes, numbuf));
        sadd(&BVrefline, "*(");
        /* For example: bq1power q1:power 0 v = */
        sadd(&Bpowerline, "bprobe_int_");
        sadd(&Bpowerline, instname);
        sadd(&Bpowerline, "power ");
        sadd(&Bpowerline, instname);
        cadd(&Bpowerline, ':');
        sadd(&Bpowerline, "power 0 v = 0+"); /*FIXME 0+ required to suppress adding {} and numparam failure*/
        /* For example: q1:power */
        sadd(&Bpowersave, instname);
        cadd(&Bpowersave, ':');
        sadd(&Bpowersave, "power");

        /* special for VDMOS: exclude thermal nodes */
        if (*instname == 'm' && strstr(tmpcard->line, "thermal"))
            numnodes = 3;
        /* special for MOS, exclude temp nodes (not always possible) */
        if (*instname == 'm' && numnodes > 5)
            numnodes = 5;
        /* special for diodes, they have 2 terminals, so exclude thermal nodes */
        if (*instname == 'd')
            numnodes = 2;
    }

    /* Scan through all nodes of the device */
    for (nodenum = 1; nodenum <= numnodes; nodenum++) {
        int i;
        char* instline = tmpcard->line;
        for (i = nodenum; i > 0; i--) {
            instline = nexttok(instline);
        }
        char* begstr = copy_substring(tmpcard->line, instline);
        char* strnode1 = gettok(&instline);

        /* node name becomes part of a new v-source name, don't allow / in node name (aka /VT).
           Replace by _ (_VT).
           Otherwise the B source function parser fails with i() not found. */
        char* strnode1name = copy(strnode1);
        if (strnode1name[0] == '/')
            strnode1name[0] = '_';
        char* newnode = tprintf("probe_int_%s_%s_%d", strnode1name, instname, nodenum);
        char nodenumstr[3];
        char *nodename1 = get_terminal_name(instname, itoa10(nodenum, nodenumstr), instances);

        if (!nodename1) {
            tfree(begstr);
            tfree(strnode1);
            tfree(strnode1name);
            ds_free(&BVrefline);
            ds_free(&Bpowerline);
            ds_free(&Bpowersave);
            return 3;
        }

        newline = tprintf("%s %s %s", begstr, newnode, instline);

        char* vline;
        if (power)
            vline= tprintf("vcurr_%s:probe_int_%s:%s_%s %s %s 0", instname, nodename1, nodenumstr, strnode1name, strnode1, newnode);
        else
            vline= tprintf("vcurr_%s:%s:%s_%s %s %s 0", instname, nodename1, nodenumstr, strnode1name, strnode1, newnode);
        tfree(tmpcard->line);
        tmpcard->line = newline;

        card = tmpcard;

        card = insert_new_line(card, vline, 0, card->linenum_orig, card->linesource);

        if (power) {
            /* For example V(1)+V(2)+V(3)*/
            if (nodenum == 1)
               sadd(&BVrefline, "v(");
            else
               sadd(&BVrefline, "+v(");
            sadd(&BVrefline, newnode);
            cadd(&BVrefline, ')');
            /*For example: (V(node1)-V(q1probe_int_Vref))*node1#branch+(V(node2)-V(q1Vref))*node2#branch */
            if (nodenum == 1)
               sadd(&Bpowerline, "(v(");
            else
               sadd(&Bpowerline, "+(v(");
            sadd(&Bpowerline, newnode);
            sadd(&Bpowerline, ")-v(");
            sadd(&Bpowerline, instname);
            sadd(&Bpowerline, "probe_int_vref))*i(vcurr_");
            sadd(&Bpowerline, instname);
            sadd(&Bpowerline, ":probe_int_");
            sadd(&Bpowerline, nodename1);
            cadd(&Bpowerline, ':');
            sadd(&Bpowerline, nodenumstr);
            cadd(&Bpowerline, '_');
            sadd(&Bpowerline, strnode1name);
            cadd(&Bpowerline, ')');

            allsaves = wl_cons(copy(ds_get_buf(&Bpowersave)), allsaves);
        }

        tfree(begstr);
        tfree(strnode1);
        tfree(strnode1name);
        tfree(newnode);
        tfree(nodename1);
    }

    if (allsaves) {
        allsaves = wl_cons(copy(".save"), allsaves);
        char* newsaveline = wl_flatten(allsaves);
        wl_free(allsaves);
        allsaves = NULL;
        card = tmpcard->nextcard;
        card = insert_new_line(card, newsaveline, 0, card->linenum_orig, card->linesource);
    }

    if (power) {
        cadd(&BVrefline, ')');
        card = tmpcard->nextcard;
        card = insert_new_line(card, copy(ds_get_buf(&BVrefline)), 0, card->linenum_orig, card->linesource);
        card = insert_new_line(card, copy(ds_get_buf(&Bpowerline)), 0, card->linenum_orig, card->linesource);
    }

    ds_free(&BVrefline);
    ds_free(&Bpowerline);
    ds_free(&Bpowersave);
    return err;
}

/* check if there are enough tokens in an instance line */
static int check_for_nodes(char* instance, int numnodes) {
    int i;
    char* tmpinst = instance;
    tmpinst = nexttok(tmpinst); /* instance name */
    for (i = 0; i < numnodes; i++) {
        tmpinst = nexttok(tmpinst);
        if (!tmpinst || *tmpinst == '\0') {
            return 1;;
        }
    }
    return 0;
}
