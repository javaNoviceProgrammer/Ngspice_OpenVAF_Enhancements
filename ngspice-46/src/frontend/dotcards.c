/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
Modified: 2000 AlansFixes
**********/

/*
 * Spice-2 compatibility stuff for .plot, .print, .four, and .width.
 */

#include "ngspice/ngspice.h"
#include <assert.h>
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dstring.h"
#include "ngspice/dvec.h"
#include "ngspice/fteinp.h"
#include "ngspice/sim.h"
#include "circuits.h"
#include "dotcards.h"
#include "variable.h"
#include "fourier.h"
#include "breakp2.h"
#include "com_measure2.h"
#include "com_commands.h"
#include "com_asciiplot.h"
#include "resource.h"
#include "postcoms.h"

/* Extract all the .save lines */

static void fixdotplot(wordlist *wl);
static void fixdotprint(wordlist *wl);
static char *fixem(char *string);
void ft_savemeasure(void);


static struct plot *
setcplot(char *name)
{
    struct plot *pl;

    for (pl = plot_list; pl; pl = pl->pl_next)
        if (ciprefix(name, pl->pl_typename))
            return pl;

    return NULL;
}


/* All lines with .width, .plot, .print, .save, .op, .meas, .tf
   have been assembled into a wordlist (wl_first) in inp.c:inp_spsource(),
   and then stored to ci_commands in inp.c:inp_dodeck().
   The .save lines are selected, com_save will put the commands into dbs.
*/

void
ft_dotsaves(void)
{
    wordlist *iline, *wl = NULL;
    char *s;

    if (!ft_curckt) /* Shouldn't happen. */
        return;

    for (iline = ft_curckt->ci_commands; iline; iline = iline->wl_next)
        if (ciprefix(".save", iline->wl_word)) {
            s = iline->wl_word;
            /* skip .save */
            s = nexttok(s);
            wl = wl_append(wl, gettoks(s));
        }

    com_save(wl);
    wl_free(wl);
}


/* ---------------------------------------------------------------------------
 * Enhancement-469: `.option saveused` -- save only what the control block reads.
 *
 * A sweep or a long transient stores every node at every point. On a circuit
 * with a few thousand unknowns that dominates the run: the dielectric-stack
 * deck this was written for costs 512 ms per sweep point with everything
 * stored and 29.7 ms with a hand-written `save` of the four vectors it
 * actually plots -- a factor of 17, from one line the author has to remember
 * to write and to keep in step with the `wrdata` beside it.
 *
 * With the option on, the control block is read before it runs and every
 * vector it mentions is saved; nothing else is.
 *
 * WHAT IS COLLECTED, and why it is deliberately more than the letter of the
 * request. Scanning only the arguments of `wrdata`/`plot`/`pyplot` would miss
 *
 *     let r = v(pin[2]) / v(pin[3])
 *     plot r
 *
 * -- `r` is not a node, and the two vectors that build it would go unsaved,
 * so the deck would fail where before it worked. Under-saving turns a
 * performance option into a correctness bug, so the scan takes every
 * `v(...)`, `i(...)` and `@dev[param]` reference ANYWHERE in the block,
 * whatever command it belongs to, plus the plain node names given to the
 * output commands. Over-saving costs a little memory; under-saving costs the
 * answer.
 *
 * WHEN IT STANDS ASIDE:
 *   - any explicit `save`/`.save` in the deck -- the author has already said
 *     what they want, and silently adding to it would make their line mean
 *     something different from what it says;
 *   - `all` as an argument to an output command, which asks for everything;
 *   - a control block with no output command at all, where there is nothing
 *     to infer from.
 * In each case the run is left exactly as it would have been.
 */

static const char *e469_out_cmds[] = {
    "wrdata", "write", "plot", "pyplot", "gnuplot", "hardcopy", "print",
    "wrs2p", "fourier", "four", "fft", "psd", "spec", "meas", "measure",
    NULL
};

/* commands whose FIRST argument is a file name, not a vector */
static const char *e469_file_first[] = { "wrdata", "write", "hardcopy",
                                         "wrs2p", NULL };

/* Enhancement-496: words that are the PLOT COMMAND'S OWN GRAMMAR, not vectors.
 *
 * The bare-word scan below took every argument that was not a number, a
 * redirection or an expression as a vector name, so `plot v(a) xlabel 'x'`
 * registered a save for `xlabel`. That was harmless to the answer -- an
 * unmatched save produces nothing -- but from Enhancement-493 onward it printed
 * "save 'xlabel': nothing of that name is in this analysis", telling the author
 * a signal was missing and naming a keyword as the signal.
 *
 * The list mirrors CT_PLOTKEYWORDS in cpitf.c, which cannot be reused because
 * it is a tab-completion table built only for an interactive session. A
 * keyword missing from this copy costs nothing but the old noise for that one
 * word -- the save itself was always a no-op -- which is why the marking in
 * ft_saveused() below, and not this list, is what actually fixes the report. */
static const char *e469_plot_kw[] = {
    "xlimit", "ylimit", "vs", "xindices", "xcompress", "xdelta", "ydelta",
    "lingrid", "loglog", "linear", "xlog", "ylog", "polar", "smith",
    "smithgrid", "nointerp", "nogrid", "title", "xlabel", "ylabel",
    "linplot", "combplot", "pointplot", "samep", "retraceplot",
    NULL
};

/* commands whose bare words are grammar rather than vectors. `meas` names its
 * analysis, its result and its function as bare words -- `meas tran m1 FIND
 * v(b) AT 50u` offered `tran`, `m1`, `find` and `at` -- while the vectors it
 * reads arrive as v(...)/i(...) and are already taken by the reference scan,
 * which runs over EVERY line whatever command it belongs to. */
static const char *e469_no_bare[] = { "meas", "measure", NULL };

/* commands that accept the plot grammar */
static const char *e469_plot_cmds[] = { "plot", "pyplot", "gnuplot",
                                        "hardcopy", NULL };

static int e469_in_list(const char *w, const char **list)
{
    int i;
    for (i = 0; list[i]; i++)
        if (cieq(w, list[i]))
            return 1;
    return 0;
}

static int e469_enabled = 0;        /* set from the option cards, see inp.c */

void inp_set_saveused(bool onoff)
{
    e469_enabled = onoff ? 1 : 0;
}

/* append `tok` to *wl unless it is already there */
static void e469_add(wordlist **wl, const char *tok)
{
    wordlist *w;
    if (!tok || !*tok)
        return;
    for (w = *wl; w; w = w->wl_next)
        if (cieq(w->wl_word, tok))
            return;
    *wl = wl_append(*wl, wl_cons(copy(tok), NULL));
}

/* Collect every v(...)/i(...)/@dev[param] reference in `line`. The scan is
   textual and bracket-counted, so `mag(v(a))`, `v(a)-v(b)` and `v(pin[2])`
   all yield the inner reference itself. */
static void e469_scan_refs(const char *line, wordlist **wl)
{
    const char *p = line;

    while (*p) {
        if (*p == '@') {
            const char *q = p + 1;
            while (*q && *q != '[' && !isspace_c(*q))
                q++;
            if (*q == '[') {
                while (*q && *q != ']')
                    q++;
                if (*q == ']') {
                    char buf[256];
                    size_t n = (size_t) (q + 1 - p);
                    if (n < sizeof buf) {
                        memcpy(buf, p, n);
                        buf[n] = '\0';
                        /* Enhancement-469 fix: a WILDCARD accessor is a sweep or
                         * alter KNOB, not an output vector -- `sweep
                         * @*[wavelength_nm] ...` is the commonest form there is.
                         * `save` cannot expand one, and handing it over produced
                         * "a wildcard device name is not expanded here, so this
                         * vector will stay empty" once per sweep point. The
                         * results were right and the noise was the whole defect,
                         * but it is noise this feature invented. A NAMED
                         * accessor is still collected: `@r1[resistance]` is a
                         * perfectly good thing to save, whatever command it
                         * appeared on. */
                        if (!strchr(buf, '*') && !strchr(buf, '?'))
                            e469_add(wl, buf);
                    }
                    p = q + 1;
                    continue;
                }
            }
            p++;
            continue;
        }
        /* v( or i( preceded by a non-identifier character */
        if ((*p == 'v' || *p == 'V' || *p == 'i' || *p == 'I') &&
            p[1] == '(' &&
            (p == line || (!isalnum_c(p[-1]) && p[-1] != '_'))) {
            const char *q = p + 2;
            int depth = 1;
            while (*q && depth) {
                if (*q == '(')
                    depth++;
                else if (*q == ')')
                    depth--;
                if (depth)
                    q++;
            }
            if (*q == ')') {
                char buf[256];
                size_t n = (size_t) (q + 1 - p);
                if (n < sizeof buf) {
                    memcpy(buf, p, n);
                    buf[n] = '\0';
                    e469_add(wl, buf);
                }
                p = q + 1;
                continue;
            }
        }
        p++;
    }
}

/* Plain node names written as bare words to an output command. Numbers,
   switches and the leading file name of `wrdata`-style commands are skipped;
   so is anything containing an operator, which belongs to an expression the
   reference scan above has already covered. */
static int e469_scan_bare(const char *line, wordlist **wl)
{
    char *c = (char *) line, *tok;
    char cmd[64];
    int argno = 0, filefirst, saw_all = 0, plotcmd;

    tok = gettok(&c);
    if (!tok)
        return 0;
    (void) strncpy(cmd, tok, sizeof cmd - 1);
    cmd[sizeof cmd - 1] = '\0';
    tfree(tok);
    if (!e469_in_list(cmd, e469_out_cmds))
        return 0;
    if (e469_in_list(cmd, e469_no_bare))     /* Enhancement-496 */
        return 0;
    filefirst = e469_in_list(cmd, e469_file_first);
    plotcmd = e469_in_list(cmd, e469_plot_cmds);

    while ((tok = gettok(&c)) != NULL) {
        argno++;
        if (cieq(tok, "all")) {
            saw_all = 1;
            tfree(tok);
            break;
        }
        if (filefirst && argno == 1) {          /* the output file */
            tfree(tok);
            continue;
        }
        if (tok[0] == '-' || tok[0] == '>' || tok[0] == '<') {
            tfree(tok);
            continue;
        }
        if (isdigit_c(tok[0]) || tok[0] == '.' || tok[0] == '+') {
            tfree(tok);                          /* a number, not a vector */
            continue;
        }
        if (strpbrk(tok, "()[]@=*/+-,'\"")) {    /* handled by the ref scan */
            tfree(tok);
            continue;
        }
        if (plotcmd && e469_in_list(tok, e469_plot_kw)) {
            tfree(tok);                          /* Enhancement-496: grammar */
            continue;
        }
        e469_add(wl, tok);
        tfree(tok);
    }
    return saw_all;
}

/* TRUE when the deck already says what to save, in which case autosave keeps
   out of the way. */
static int e469_user_saved(wordlist *controls)
{
    wordlist *w;

    if (ft_curckt)
        for (w = ft_curckt->ci_commands; w; w = w->wl_next)
            if (w->wl_word && ciprefix(".save", w->wl_word))
                return 1;
    for (w = controls; w; w = w->wl_next) {
        char *l = w->wl_word;
        if (!l)
            continue;
        while (*l && isspace_c(*l))
            l++;
        if (ciprefix("save", l) && (!l[4] || isspace_c(l[4])))
            return 1;
    }
    return 0;
}

void ft_saveused(wordlist *controls)
{
    wordlist *w, *saves = NULL;
    int any_out = 0, saw_all = 0;

    if (!e469_enabled || !controls || !ft_curckt)
        return;
    if (e469_user_saved(controls))
        return;

    for (w = controls; w; w = w->wl_next) {
        char *l = w->wl_word, *first;
        if (!l)
            continue;
        while (*l && isspace_c(*l))
            l++;
        {
            char *c = l;
            first = gettok(&c);
        }
        if (first) {
            if (e469_in_list(first, e469_out_cmds)) {
                any_out = 1;
                if (e469_scan_bare(l, &saves))
                    saw_all = 1;
            }
            tfree(first);
        }
        /* references are collected from EVERY line, not only output ones --
           see the note above about `let` */
        e469_scan_refs(l, &saves);
    }

    if (saw_all || !any_out || !saves) {
        wl_free(saves);
        return;
    }

    /* Enhancement-496: everything registered here was INFERRED from the
     * control block, not written by the user. Marking it keeps E-493's
     * unmatched-name warning for the names a deck actually asked for. */
    ft_save_mark_auto(1);
    com_save(saves);
    ft_save_mark_auto(0);
    if (ft_ngdebug)
        fprintf(stdout, "saveused: %d vector(s) kept\n", wl_length(saves));
    wl_free(saves);
}


/* Go through the dot lines given and make up a big "save" command with
 * all the node names mentioned. Note that if a node is requested for
 * one analysis, it is saved for all of them.
 */

static char *plot_opts[ ] = {
    "linear",
    "xlog",
    "ylog",
    "loglog"
};


int
ft_savedotargs(void)
{
    wordlist *w, *wl = NULL, *iline, **prev_wl, *w_next;
    char *name;
    char *s;
    int some = 0;
    static wordlist all = { "all", NULL, NULL };
    int isaplot;
    int i;
    int status;

    if (!ft_curckt) /* Shouldn't happen. */
        return 0;

    for (iline = ft_curckt->ci_commands; iline; iline = iline->wl_next) {
        s = iline->wl_word;
        if (ciprefix(".plot", s))
            isaplot = 1;
        else
            isaplot = 0;

        if (isaplot || ciprefix(".print", s)) {
            s = nexttok(s);
            name = gettok(&s);

            if ((w = gettoks(s)) == NULL) {
                fprintf(cp_err, "Warning: no nodes given: %s\n", iline->wl_word);
            } else {
                if (isaplot) {
                    prev_wl = &w;
                    for (wl = w; wl; wl = w_next) {
                        w_next = wl->wl_next;
                        for (i = 0; (size_t) i < NUMELEMS(plot_opts); i++) {
                            if (!strcmp(wl->wl_word, plot_opts[i])) {
                                /* skip it */
                                *prev_wl = w_next;
                                tfree(wl);
                                break;
                            }
                        }
                        if (i == NUMELEMS(plot_opts))
                            prev_wl = &wl->wl_next;
                    }
                }
                some = 1;
                com_save2(w, name);
            }
        } else if (ciprefix(".four", s)) {
            s = nexttok(s);
            s = nexttok(s);
            if ((w = gettoks(s)) == NULL) {
                fprintf(cp_err, "Warning: no nodes given: %s\n", iline->wl_word);
            } else {
                some = 1;
                com_save2(w, "TRAN");       /* A hack */
            }
        } else if (ciprefix(".meas", s)) {
            status = measure_extract_variables(s);
            if (!(status)) {
                some = 1;
            }
        } else if (ciprefix(".op", s)) {
            some = 1;
            com_save2(&all, "OP");
        } else if (ciprefix(".tf", s)) {
            some = 1;
            com_save2(&all, "TF");
        }
    }
    return some;
}


void
ft_savemeasure(void)
{
    char *s;
    wordlist *iline;

    if (!ft_curckt) /* Shouldn't happen. */
        return;

    for (iline = ft_curckt->ci_commands; iline; iline = iline->wl_next) {
        s = iline->wl_word;
        if (ciprefix(".measure", s)) {
            (void) measure_extract_variables(s);
        }
    }
}


/* Execute the .whatever lines found in the deck, after we are done running.
 * We'll be cheap and use cp_lexer to get the words... This should make us
 * spice-2 compatible.  If terse is TRUE then there was a rawfile, so don't
 * print lots of junk.
 */

int
ft_cktcoms(bool terse)
{
    wordlist *coms, *command, all;
    char *plottype, *s;
    struct dvec *v;
    static wordlist twl = { "col", NULL, NULL };
    struct plot *pl;
    int i, found;
    char numbuf[BSIZE_SP]; /* For printnum*/

    all.wl_next = NULL;
    all.wl_word = "all";

    if (!ft_curckt) {
        return 1;
    }

    plot_cur = setcplot("op");
    if (!ft_curckt->ci_commands && !plot_cur)
        goto nocmds;
    coms = ft_curckt->ci_commands;
    cp_interactive = FALSE;

    /* Listing */
    if (ft_listprint) {
        if (terse)
            fprintf(cp_err, ".options: no listing, rawfile was generated.\n");
        else
            inp_list(cp_out, ft_curckt->ci_deck, ft_curckt->ci_options, LS_DECK);
    }

    /* If there was a .op line, then we have to do the .op output. */
    plot_cur = setcplot("op");
    /* Enhancement-212: an empty circuit (no non-ground nodes -- e.g. an
     * all-commented-out deck) produces an "op" plot with no data vectors, so
     * pl_dvecs is NULL. The former assert() aborted (SIGABRT) here, and with
     * -DNDEBUG the next line dereferenced NULL. Guard instead and skip the
     * (empty) op printout gracefully. */
    if (plot_cur != NULL && plot_cur->pl_dvecs != NULL) {
        if (plot_cur->pl_dvecs->v_realdata != NULL) {
            if (terse) {
                fprintf(cp_out, "OP information in rawfile.\n");
            } else {
                fprintf(cp_out, "\t%-30s%15s\n", "Node", "Voltage");
                fprintf(cp_out, "\t%-30s%15s\n", "----", "-------");
                fprintf(cp_out, "\t----\t-------\n");
                for (v = plot_cur->pl_dvecs; v; v = v->v_next) {
                    if (!isreal(v)) {
                        fprintf(cp_err,
                                "Internal error: op vector %s not real\n",
                                v->v_name);
                        continue;
                    }
                    if ((v->v_type == SV_VOLTAGE) && (*(v->v_name) != '@')) {
                        printnum(numbuf, sizeof numbuf, v->v_realdata[0]);
                        fprintf(cp_out, "\t%-30s%15s\n", v->v_name, numbuf);
                    }
                }
                fprintf(cp_out, "\n\tSource\tCurrent\n");
                fprintf(cp_out, "\t------\t-------\n\n");
                for (v = plot_cur->pl_dvecs; v; v = v->v_next)
                    if (v->v_type == SV_CURRENT) {
                        printnum(numbuf, sizeof numbuf, v->v_realdata[0]);
                        fprintf(cp_out, "\t%-30s%15s\n", v->v_name, numbuf);
                    }
                fprintf(cp_out, "\n");

                if (!ft_nomod) {
                    com_showmod(&all);
                }
                com_show(&all);
            }
        }
    }

    for (pl = plot_list; pl; pl = pl->pl_next)
        if (ciprefix("tf", pl->pl_typename)) {
            if (terse) {
                fprintf(cp_out, "TF information in rawfile.\n");
                break;
            }
            plot_cur = pl;
            fprintf(cp_out, "Transfer function information:\n");
            com_print(&all);
            fprintf(cp_out, "\n");
        }

    /* Now all the '.' lines */
    while (coms) {
        wordlist* freecom;
        freecom = command = cp_lexer(coms->wl_word);
        if (!command) {
            /* Line not converted to a wordlist */
            goto bad;
        }
        if (command->wl_word == (char*)NULL) {
            /* Line not converted to a wordlist */
            wl_free(freecom);
            goto bad;
        }
        if (eq(command->wl_word, ".width")) {
            do
                command = command->wl_next;
            while (command && !ciprefix("out", command->wl_word));
            if (command) {
                s = strchr(command->wl_word, '=');
                if (!s || !s[1]) {
                    fprintf(cp_err, "Error: bad line %s\n", coms->wl_word);
                    coms = coms->wl_next;
                    wl_free(freecom);
                    continue;
                }
                i = atoi(++s);
                cp_vset("width", CP_NUM, &i);
            }
        } else if (eq(command->wl_word, ".print")) {
            if (terse) {
                fprintf(cp_out,
                        ".print line ignored since rawfile was produced.\n");
            } else {
                command = command->wl_next;
                if (!command) {
                    fprintf(cp_err, "Error: bad line %s\n", coms->wl_word);
                    coms = coms->wl_next;
                    wl_free(freecom);
                    continue;
                }
                plottype = command->wl_word;
                command = command->wl_next;
                fixdotprint(command);
                twl.wl_next = command;
                found = 0;
                for (pl = plot_list; pl; pl = pl->pl_next)
                    if (ciprefix(plottype, pl->pl_typename)) {
                        plot_cur = pl;
                        com_print(&twl);
                        fprintf(cp_out, "\n");
                        found = 1;
                    }
                if (!found)
                    fprintf(cp_err, "Error: .print: no %s analysis found.\n",
                            plottype);
            }
        } else if (eq(command->wl_word, ".plot")) {
            if (terse) {
                fprintf(cp_out,
                        ".plot line ignored since rawfile was produced.\n");
            } else {
                command = command->wl_next;
                if (!command) {
                    fprintf(cp_err, "Error: bad line %s\n",
                            coms->wl_word);
                    coms = coms->wl_next;
                    wl_free(freecom);
                    continue;
                }
                plottype = command->wl_word;
                command = command->wl_next;
                fixdotplot(command);
                found = 0;
                for (pl = plot_list; pl; pl = pl->pl_next)
                    if (ciprefix(plottype, pl->pl_typename)) {
                        plot_cur = pl;
                        com_asciiplot(command);
                        fprintf(cp_out, "\n");
                        found = 1;
                    }
                if (!found)
                    fprintf(cp_err, "Error: .plot: no %s analysis found.\n",
                            plottype);
            }
        } else if (ciprefix(".four", command->wl_word)) {
            if (terse) {
                fprintf(cp_out,
                        ".fourier line ignored since rawfile was produced.\n");
            } else {
                int err;

                plot_cur = setcplot("tran");
                err = fourier(command->wl_next, plot_cur);
                if (!err)
                    fprintf(cp_out, "\n\n");
                else
                    fprintf(cp_err, "No transient data available for "
                            "fourier analysis");
            }
        } else if (!eq(command->wl_word, ".save") &&
                   !eq(command->wl_word, ".op") &&
                   !ciprefix(".meas", command->wl_word) &&
                   !eq(command->wl_word, ".tf")) {
            wl_free(freecom);
            goto bad;
        }
        coms = coms->wl_next; /* go to next line */
        wl_free(freecom);
    } /* end of loop over '.' lines */

nocmds:
    /* Now the node table
       if (ft_nodesprint)
       ;
    */

    /* The options */
    if (ft_optsprint) {
        fprintf(cp_out, "Options:\n\n");
        cp_vprint();
        (void) putc('\n', cp_out);
    }

    /* And finally the accounting info. */
    if (ft_acctprint) {
        static wordlist ww = { "everything", NULL, NULL };
        com_rusage(&ww);
    } else if ((!ft_noacctprint) && (!ft_acctprint)) {
        com_rusage(NULL);
    }
    /* absolutely no accounting if noacct is given */

    putc('\n', cp_out);
    return 0;

bad:
    fprintf(cp_err, "Internal Error: ft_cktcoms: bad commands\n");
    return 1;
}


/* These routines make sure that the arguments to .plot and .print in
 * spice2 decks are acceptable to spice3. The things we look for are
 *  trailing (a,b) in .plot -> xlimit a b
 *  vm(x) -> mag(v(x))
 *  vp(x) -> ph(v(x))
 *  v(x,0) -> v(x)
 *  v(0,x) -> -v(x)
 */

static void
fixdotplot(wordlist *wl)
{
    /* Create a buffer for printing numbers */
    DS_CREATE(numbuf, 100);

    while (wl) {
        wl->wl_word = fixem(wl->wl_word);

        /* Is this a trailing "(a,b)"? Note that we require it to be
         * one word. */
        if (!wl->wl_next && (*wl->wl_word == '(')) {
            double d1, d2;
            char *s = wl->wl_word + 1;
            if (ft_numparse(&s, FALSE, &d1) < 0 ||
                    *s != ',') {
                fprintf(cp_err, "Error: bad limits \"%s\"\n",
                        wl->wl_word);
                goto EXITPOINT;
            }
            s++; /* step past comma */
            if (ft_numparse(&s, FALSE, &d2) < 0 ||
                    *s != ')' || s[1] != '\0') { /* must end with ")" */
                fprintf(cp_err, "Error: bad limits \"%s\"\n",
                        wl->wl_word);
                goto EXITPOINT;
            }

            tfree(wl->wl_word);
            wl->wl_word = copy("xlimit");
            ds_clear(&numbuf);
            if (printnum_ds(&numbuf, d1) != 0) {
                fprintf(cp_err, "Unable to print limit 1: %g\n", d1);
                goto EXITPOINT;
            }
            wl_append_word(NULL, &wl, copy(ds_get_buf(&numbuf)));
            ds_clear(&numbuf);
            if (printnum_ds(&numbuf, d2) != 0) {
                fprintf(cp_err, "Unable to print limit 2: %g\n", d2);
                goto EXITPOINT;
            }
            wl_append_word(NULL, &wl, copy(ds_get_buf(&numbuf)));
        } /* end of case of start of potential (a,b) */
        wl = wl->wl_next;
    } /* end of loop over words */

EXITPOINT:
    ds_free(&numbuf); /* Free DSTRING resources */
} /* end of function fixdotplot */



static void fixdotprint(wordlist *wl)
{
    /* Process each word in the wordlist */
    while (wl) {
        wl->wl_word = fixem(wl->wl_word);
        wl = wl->wl_next;
    }
} /* end of function fixdotprint */



static char *fixem(char *string)
{
    char *buf, *s, *t;
    char *ss = string; /* save addr of string in case it is freed */
    /* E-237: size the scratch buffer to the input rather than a fixed
     * BSIZE_SP[512] -- the rewrites below wrap the (possibly long) user node
     * names of a differential form like v(a,b), and a long enough a/b pair
     * overran the old fixed buffer.  The output is the input plus a small,
     * bounded wrapper ("real(v()-v())" etc. < 20 chars), so strlen + 32 is
     * always ample; every write below is a bounded snprintf regardless. */
    size_t bufsz = strlen(string) + 32;
    buf = TMALLOC(char, bufsz);

    if (ciprefix("v(", string) &&strchr(string, ',')) {
        for (s = string; *s && (*s != ','); s++)
            ;
        *s++ = '\0';
        for (t = s; *t && (*t != ')'); t++)
            ;
        *t   = '\0';
        if (eq(s, "0"))
            (void) snprintf(buf, bufsz, "v(%s)", string + 2);
        else if (eq(string + 2, "0"))
            (void) snprintf(buf, bufsz, "-v(%s)", s);
        else
            (void) snprintf(buf, bufsz, "v(%s)-v(%s)", string + 2, s);
    } else if (ciprefix("vm(", string) &&strchr(string, ',')) {
        for (s = string; *s && (*s != ','); s++)
            ;
        *s++ = '\0';
        for (t = s;      *t && (*t != ')'); t++)
            ;
        *t   = '\0';
        if (eq(s, "0"))
            (void) snprintf(buf, bufsz, "mag(v(%s))", string + 3);
        else if (eq(string + 3, "0"))
            (void) snprintf(buf, bufsz, "mag(-v(%s))", s);
        else
            (void) snprintf(buf, bufsz, "mag(v(%s)-v(%s))", string + 3, s);
    } else if (ciprefix("vp(", string) &&strchr(string, ',')) {
        for (s = string; *s && (*s != ','); s++)
            ;
        *s++ = '\0';
        for (t = s;      *t && (*t != ')'); t++)
            ;
        *t   = '\0';
        if (eq(s, "0"))
            (void) snprintf(buf, bufsz, "ph(v(%s))", string + 3);
        else if (eq(string + 3, "0"))
            (void) snprintf(buf, bufsz, "ph(-v(%s))", s);
        else
            (void) snprintf(buf, bufsz, "ph(v(%s)-v(%s))", string + 3, s);
    } else if (ciprefix("vi(", string) &&strchr(string, ',')) {
        for (s = string; *s && (*s != ','); s++)
            ;
        *s++ = '\0';
        for (t = s;      *t && (*t != ')'); t++)
            ;
        *t   = '\0';
        if (eq(s, "0"))
            (void) snprintf(buf, bufsz, "imag(v(%s))", string + 3);
        else if (eq(string + 3, "0"))
            (void) snprintf(buf, bufsz, "imag(-v(%s))", s);
        else
            (void) snprintf(buf, bufsz, "imag(v(%s)-v(%s))", string + 3, s);
    } else if (ciprefix("vr(", string) &&strchr(string, ',')) {
        for (s = string; *s && (*s != ','); s++)
            ;
        *s++ = '\0';
        for (t = s;      *t && (*t != ')'); t++)
            ;
        *t   = '\0';
        if (eq(s, "0"))
            (void) snprintf(buf, bufsz, "real(v(%s))", string + 3);
        else if (eq(string + 3, "0"))
            (void) snprintf(buf, bufsz, "real(-v(%s))", s);
        else
            (void) snprintf(buf, bufsz, "real(v(%s)-v(%s))", string + 3, s);
    } else if (ciprefix("vdb(", string) &&strchr(string, ',')) {
        for (s = string; *s && (*s != ','); s++)
            ;
        *s++ = '\0';
        for (t = s;      *t && (*t != ')'); t++)
            ;
        *t   = '\0';
        if (eq(s, "0"))
            (void) snprintf(buf, bufsz, "db(v(%s))", string + 4);
        else if (eq(string + 4, "0"))
            (void) snprintf(buf, bufsz, "db(-v(%s))", s);
        else
            (void) snprintf(buf, bufsz, "db(v(%s)-v(%s))", string + 4, s);
    } else if (ciprefix("i(", string)) {
        for (s = string; *s && (*s != ')'); s++)
            ;
        *s = '\0';
        string += 2;
        (void) snprintf(buf, bufsz, "%s#branch", string);
    } else {
        tfree(buf);        /* no rewrite applies: hand back the original */
        return string;
    }

    txfree(ss);
    /* buf is already heap-allocated and right-sized -- return it directly */
    return buf;
} /* end of function fixem */



wordlist *
gettoks(char *s)
{
    char        *t, *s0;
    char        *l, *r, *c;     /* left, right, center/comma */
    wordlist    *wl, *list, **prevp;


    list = NULL;
    prevp = &list;

    if (!s) {
        return list;
    }

    /* stripWhite.... uses copy() to return a malloc'ed s, so we have to free it,
       using s0 as its starting address */
    if (strchr(s, '('))
        s0 = s = stripWhiteSpacesInsideParens(s);
    else
        s0 = s = copy(s);

    while ((t = gettok(&s)) != NULL) {
        if (*t == '(') {
            /* gettok uses copy() to return a malloc'ed t, so we have to free it */
            tfree(t);
            continue;
        }
        l = strrchr(t, '(');
        if (!l) {
            wl = wl_cons(copy(t), NULL);
            *prevp = wl;
            prevp = &wl->wl_next;
            tfree(t);
            continue;
        }

        r = strchr(t, ')');

        c = strchr(t, ',');
        if (!c)
            c = r;

        if (c)
            *c = '\0';

        wl = wl_cons(NULL, NULL);
        *prevp = wl;
        prevp = &wl->wl_next;

        /* Transfer i(xx) to xxx#branch only when i is the first
           character of the token or preceeded by a space. */
        if ((*(l - 1) == 'i' ||
             ((*(l - 1) == 'I') && (l - 1 == t))) ||
            ((l > t + 1) && isspace(*(l-2)))) {
            /* E-237: a long branch name overran the fixed buf[513]; build
             * the "<name>#branch" string in a right-sized allocation. */
            wl->wl_word = tprintf("%s#branch", l + 1);
            c = r = NULL;
        }
        else {
            wl->wl_word = copy(l + 1);
        }

        /* E-238: a differential token like "v(a,b)" has both a comma (c) and a
         * close paren (r), and we split off the second operand at r.  A
         * MALFORMED token such as "v(1," has a comma but NO ')', so r is NULL
         * while c is not -- the old `c != r` was then true and `*r = '\0'`
         * dereferenced NULL.  Require r to be non-NULL before splitting. */
        if (r && c != r) {
            *r = '\0';
            wl = wl_cons(copy(c + 1), NULL);
            *prevp = wl;
            prevp = &wl->wl_next;
        }
        tfree(t);
    } /* end of loop parsing string */

    txfree(s0);
    return list;
} /* end of function gettoks */



