/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/

/* The front-end command loop.  */

#include "ngspice/ngspice.h"
#include <ctype.h>
#include "ngspice/cpdefs.h"

#include "control.h"
#include "com_cdump.h"
#include "variable.h"
#include "ngspice/fteext.h"
#include "com_aging.h"      /* Enhancement-544: the user alter journal */


/* Return values from doblock().  I am assuming that nobody will use
 * these characters in a string.  */
#define NORMAL      '\001'
#define BROKEN      '\002'
#define CONTINUED   '\003'
#define NORMAL_STR  "\001"
#define BROKEN_STR  "\002"
#define CONTINUED_STR   "\003"

static void cp_free_control(void); /* needed by resetcontrol */

/* Are we waiting for a command? This lets signal handling be
 * more clever. */

bool cp_cwait = FALSE;
char *cp_csep = ";"; /* character that separates commands */

bool cp_dounixcom = FALSE;

/* We have to keep the control structures in a stack, so that when we
 * do a 'source', we can push a fresh set onto the top...  Actually
 * there has to be two stacks -- one for the pointer to the list of
 * control structs, and one for the 'current command' pointer...  */
struct control *control[CONTROLSTACKSIZE];
struct control *cend[CONTROLSTACKSIZE];
int stackp = 0;


/* If there is an argument, give this to cshpar to use instead of
 * stdin. In a few places, we call cp_evloop again if it returns 1 and
 * exit (or close a file) if it returns 0... Because of the way
 * sources are done, we can't allow the control structures to get
 * blown away every time we return -- probably every time we type
 * source at the keyboard and every time a source returns to keyboard
 * input is ok though -- use ft_controlreset.  */

/* Notes by CDHW:
 * This routine leaked like a sieve because each getcommand() created a
 * wordlist that was never freed because it might have been added into
 * the control structure. I've tackled this by making sure that everything
 * put into the cend[stackp] is a copy. This means that wlist can be
 * destroyed safely
 */

/* no redirection after the following commands (we may need more to add here!) */
static char *noredirect[] = { "stop", "define", "circbyline", NULL};


/* This function returns the (first) structure wit the label s */
static struct control *findlabel(const char *s, struct control *ct)
{
    while (ct) {
        if ((ct->co_type == CO_LABEL) && eq(s, ct->co_text->wl_word)) {
            break;
        }
        ct = ct->co_next;
    }
    return (ct);
}


/* This is also in cshpar.c ... */
static void
pwlist(wordlist *wlist, char *name)
{
    wordlist *wl;

    if (!cp_debug)
        return;
    fprintf(cp_err, "%s : [ ", name);
    for (wl = wlist; wl; wl = wl->wl_next)
        fprintf(cp_err, "%s ", wl->wl_word);
    fprintf(cp_err, "]\n");
}


/* CDHW defined functions */

static void
pwlist_echo(wordlist *wlist, char *name)   /*CDHW used to perform function of set echo */
{
    wordlist *wl;

    if ((!cp_echo)||cp_debug) /* cpdebug prints the same info */
        return;
    fprintf(cp_err, "%s ", name);
    for (wl = wlist; wl; wl = wl->wl_next)
        fprintf(cp_err, "%s ", wl->wl_word);
    fprintf(cp_err, "\n");
}


/*CDHW Remove control structure and free the memory its hogging CDHW*/

static void
ctl_free(struct control *ctrl)
{
    if (!ctrl) {
        return;
    }

    wl_free(ctrl->co_cond);
    ctrl->co_cond = NULL;
    txfree(ctrl->co_foreachvar);
    ctrl->co_foreachvar = NULL;
    wl_free(ctrl->co_text);
    ctrl->co_text = NULL;
    ctl_free(ctrl->co_children);
    ctrl->co_children = NULL;
    ctl_free(ctrl->co_elseblock);
    ctrl->co_elseblock = NULL;
    ctl_free(ctrl->co_next);
    ctrl->co_next = NULL;
    txfree(ctrl);
}


/* ------------------------------------------------------------------------
 * Enhancement-553: f-strings in the control language.
 *
 *     echo f"yield {100*montecarlo_yield:.2f} %, corner {mean(fc):.4g} Hz"
 *     pyplot fig v(out) title rf"RC low-pass, Vmax = {vecmax(v(out)):.3f} V"
 *
 * A word spelled f"..." (or rf"..." / fr"..." -- the r half keeps the case
 * through the deck's folding, see inpcom.c) has every {expression} inside it
 * evaluated with the ordinary expression evaluator and replaced by its text:
 * a scalar with %g, or with the printf-style format after a ':' (`.3f`,
 * `.4g`, `e`, `d` for an integer); a vector by its elements separated by
 * spaces; a complex value as `re,im`, the way `print` shows one. \{ and \}
 * are literal braces ({{ }} belongs to the `.for` construct of the netlist,
 * E-474, and is not reused here). The result is one quoted word, so every
 * command that unquotes its argument takes it. An expression that resolves
 * to nothing, or a format that is not one, is an error naming the string and
 * the brace, and the command does not run -- an empty substitution would be
 * the silent-zero fault of E-431 all over again. $variables are substituted
 * before this pass, as in every other word.
 * ------------------------------------------------------------------------ */

/* is `spec` a printf-style number format: [-+ #0]* [width] [.prec] one of
   eEfFgGdiuxX ? */
static int fstr_valid_spec(const char *spec, char *conv)
{
    const char *p = spec;
    while (*p == '-' || *p == '+' || *p == ' ' || *p == '#' || *p == '0')
        p++;
    while (isdigit((unsigned char) *p))
        p++;
    if (*p == '.') {
        p++;
        if (!isdigit((unsigned char) *p))
            return 0;
        while (isdigit((unsigned char) *p))
            p++;
    }
    if (*p && strchr("eEfFgGdiuxX", *p) && p[1] == '\0') {
        *conv = *p;
        return 1;
    }
    return 0;
}

/* hunt F12: a spec's flags and width, without its precision and conversion
   -- what a :d that cannot go through a long keeps when it falls back to
   %.0f. */
static void fstr_spec_head(const char *spec, char *head, size_t n)
{
    size_t i = 0;
    while (spec[i] && strchr("-+ #0", spec[i]))
        i++;
    while (isdigit((unsigned char) spec[i]))
        i++;
    if (i >= n)
        i = n - 1;
    memcpy(head, spec, i);
    head[i] = '\0';
}

/* format one real with `spec` (NULL: %g) into `out` (of `cap` bytes); 0 when
   the conversion cannot show the value (reported by the caller) */
static int fstr_format_real(char *out, size_t cap, double v, const char *spec, char conv)
{
    char fmt[48], head[48];
    if (!spec) {
        (void) snprintf(out, cap, "%g", v);
        return 1;
    }
    if (strchr("diuxX", conv)) {
        /* hunt F12: (long) of a value outside long's range is undefined --
           arm64 saturates, so {1e20:d} printed 9223372036854775807 in
           silence (x86 would have printed LONG_MIN). A whole number too big
           for a long is what :d asked for, so print it exactly through %.0f
           (and inf/nan as themselves); hex and unsigned conversions have no
           such rendering, and a negative value in one is a mistake, not a
           number to wrap. */
        int fits = isfinite(v) && v < 9223372036854775808.0
                   && v >= -9223372036854775808.0;
        if (conv == 'd' || conv == 'i') {
            if (!fits) {
                fstr_spec_head(spec, head, sizeof head);
                (void) snprintf(fmt, sizeof fmt, "%%%s.0f", head);
                (void) snprintf(out, cap, fmt, v);
                return 1;
            }
        } else if (!fits || v < 0.0) {
            return 0;
        }
        (void) snprintf(fmt, sizeof fmt, "%%%.*sl%c", (int) (strlen(spec) - 1), spec, conv);
        (void) snprintf(out, cap, fmt, (long) v);
    } else {
        (void) snprintf(fmt, sizeof fmt, "%%%s", spec);
        (void) snprintf(out, cap, fmt, v);
    }
    return 1;
}

/* append `add` to the growable string */
static void fstr_cat(char **buf, size_t *len, size_t *cap, const char *add)
{
    size_t n = strlen(add);
    if (*len + n + 1 > *cap) {
        *cap = (*len + n + 1) * 2;
        *buf = TREALLOC(char, *buf, *cap);
    }
    memcpy(*buf + *len, add, n + 1);
    *len += n;
}

/* Evaluate `expr` (with `spec`, NULL for none) and append its text.
   1: appended; 0: the expression resolves to nothing; -1: it does, but the
   format cannot show the value (hunt F12; reported here, with the value). */
static int fstr_eval_one(char **buf, size_t *len, size_t *cap,
                         const char *expr, const char *spec, char conv,
                         const char *word)
{
    struct pnode *pn = ft_getpnames_from_string(expr, TRUE);
    struct dvec *v;
    int i, ok = 0;
    char num[64];
    if (!pn)
        return 0;
    v = ft_evaluate(pn);
    if (v && v->v_length >= 1) {
        ok = 1;
        for (i = 0; i < v->v_length && ok > 0; i++) {
            double parts[2];
            int np = 1, k;
            if (isreal(v)) {
                parts[0] = v->v_realdata[i];
            } else {
                parts[0] = v->v_compdata[i].cx_real;
                parts[1] = v->v_compdata[i].cx_imag;
                np = 2;
            }
            if (i > 0)
                fstr_cat(buf, len, cap, " ");
            for (k = 0; k < np; k++) {
                if (k > 0)
                    fstr_cat(buf, len, cap, ",");
                if (!fstr_format_real(num, sizeof num, parts[k], spec, conv)) {
                    fprintf(cp_err, "Error: f-string %s: {%s:%s}: %g cannot be "
                                    "shown as %s (use :d for a whole number or "
                                    ":g for any); the command is not run\n",
                            word, expr, spec, parts[k],
                            conv == 'u' ? "unsigned" : "hex");
                    ok = -1;
                    break;
                }
                fstr_cat(buf, len, cap, num);
            }
        }
    }
    if (!pn->pn_value && v)
        vec_free(v);
    free_pnode(pn);
    return ok;
}

/* hunt F12: `{1+1:.3}` is not a format (a format ends with a conversion
   letter), so the colon is handed to the expression, which then fails. When
   the tail after the colon has a format's shape -- flags, width, precision
   and at most one letter, which is then not a conversion -- say so. 1 when a
   hint was written. */
static int fstr_spec_hint(const char *spec, char *hint, size_t n)
{
    const char *p = spec;
    if (*p == ' ')      /* `a ? 1 : 2` -- a ternary's tail, not a format */
        return 0;
    while (*p == '-' || *p == '+' || *p == ' ' || *p == '#' || *p == '0')
        p++;
    while (isdigit((unsigned char) *p))
        p++;
    if (*p == '.') {
        p++;
        while (isdigit((unsigned char) *p))
            p++;
    }
    if (p == spec)
        return 0;
    if (!*p) {
        (void) snprintf(hint, n, "; if ':%s' was meant as a format, it needs a "
                                 "conversion letter (e, f, g, d, i, u, x, X): "
                                 ":%sf", spec, spec);
        return 1;
    }
    if (isalpha((unsigned char) *p) && !p[1]) {
        (void) snprintf(hint, n, "; if ':%s' was meant as a format, '%c' is not a "
                                 "conversion letter (e, f, g, d, i, u, x, X)",
                        spec, *p);
        return 1;
    }
    return 0;
}

/* The body of one f-string (between the quotes) to its text; NULL on error,
   which has been reported. */
static char *fstr_expand(const char *body, const char *word)
{
    char *out = NULL;
    size_t len = 0, cap = 0;
    const char *p = body;
    char one[2] = { 0, 0 };

    fstr_cat(&out, &len, &cap, "");
    while (*p) {
        if (*p == '\\' && (p[1] == '{' || p[1] == '}' || p[1] == '\\')) {
            one[0] = p[1];
            fstr_cat(&out, &len, &cap, one);
            p += 2;
        } else if (*p == '{') {
            const char *q = p + 1, *colon = NULL;
            int depth = 1, par = 0, rc;
            char *expr, *spec = NULL, *tail = NULL, conv = 0;
            while (*q && depth > 0) {
                if (*q == '{') depth++;
                else if (*q == '}') { depth--; if (depth == 0) break; }
                else if (*q == '(' || *q == '[') par++;
                else if (*q == ')' || *q == ']') par--;
                else if (*q == ':' && par == 0 && depth == 1) colon = q;
                q++;
            }
            if (*q != '}') {
                fprintf(cp_err, "Error: f-string %s: '{' without a closing '}'\n", word);
                tfree(out);
                return NULL;
            }
            if (colon) {
                spec = copy(colon + 1);
                spec[q - colon - 1] = '\0';
                if (!fstr_valid_spec(spec, &conv)) {
                    /* not a format: the colon belongs to the expression;
                       hunt F12: kept for the hint below */
                    tail = spec;
                    spec = NULL;
                    colon = NULL;
                }
            }
            expr = copy(p + 1);
            expr[(colon ? colon : q) - (p + 1)] = '\0';
            {
                const char *e = expr;
                while (*e == ' ' || *e == '\t')
                    e++;
                if (!*e) {      /* hunt F12: `{ }` is as empty as `{}` */
                    fprintf(cp_err, "Error: f-string %s: an empty {}\n", word);
                    rc = -1;
                } else if (*e == '{') {  /* hunt F12: `{{1+1}}` named vector `{1` */
                    fprintf(cp_err, "Error: f-string %s: {%s}: braces do not nest "
                                    "-- an expression cannot start with '{' "
                                    "(write \\{ for a literal brace); the "
                                    "command is not run\n", word, expr);
                    rc = -1;
                } else {
                    rc = fstr_eval_one(&out, &len, &cap, expr, spec, conv, word);
                }
            }
            if (rc == 0) {
                char hint[160] = "";
                if (tail)
                    (void) fstr_spec_hint(tail, hint, sizeof hint);
                fprintf(cp_err, "Error: f-string %s: {%s} does not evaluate to a value "
                                "(no such vector or variable in the current plot?)%s; "
                                "the command is not run\n", word, expr, hint);
            }
            if (rc <= 0) {
                tfree(expr); if (spec) tfree(spec); if (tail) tfree(tail);
                tfree(out);
                return NULL;
            }
            tfree(expr);
            if (spec) tfree(spec);
            if (tail) tfree(tail);
            tail = NULL;
            p = q + 1;
        } else if (*p == '}') {
            fprintf(cp_err, "Error: f-string %s: a '}' without a '{' (write \\} for a "
                            "literal brace)\n", word);
            tfree(out);
            return NULL;
        } else {
            one[0] = *p++;
            fstr_cat(&out, &len, &cap, one);
        }
    }
    return out;
}

/* Every f"..." / rf"..." of the list is replaced by its text; a bare r"..."
   becomes "..." (its case has already been kept). NULL, with the list freed,
   on an error.

   Enhancement-556 (hunt F3, F4): the prefixed string may sit after `name=`
   inside the word (`let z=f"{7}"`, `set t=f"{1+1}"`, `alter r1=f"{2k}"` --
   the deck reader collapses the spaces around `=`), and what an f-string
   produces is PLAIN TEXT, not a quoted word: `"7"` was refused by `let`,
   `alter`, `setplot` and every numeric option, which do not see through
   quotes, so the value an f-string formats could reach an echo and nothing
   else. Text with whitespace in it is quoted, so a command that re-reads its
   arguments still sees one word and unquotes it itself; a raw string keeps
   its quotes, like the plain quoted word it stands in for. */
wordlist *cp_fstringsubst(wordlist *wlist)
{
    wordlist *wl;
    for (wl = wlist; wl; wl = wl->wl_next) {
        size_t from = 0;
        int guard;
        /* a word may carry more than one, and a tail after the closing quote
           (`f"{1+1}"=2`, the deck reader's form of `f"{1+1}" = 2`) is kept */
        for (guard = 0; guard < 16 && wl->wl_word; guard++) {
            const char *w = wl->wl_word;
            size_t pos = 0, end = 0;
            int k, has_f = 0, i;
            k = cp_string_prefix_at(w, from, &pos, &end);
            if (k <= 0)
                break;
            for (i = 0; i < k; i++)
                if (w[pos + i] == 'f' || w[pos + i] == 'F')
                    has_f = 1;
            {
                size_t blen = end - (pos + (size_t) k + 1);
                char *body = TMALLOC(char, blen + 1);
                char *head = TMALLOC(char, pos + 1);
                const char *tail = w + end + 1;
                char *text, *neww;
                memcpy(body, w + pos + k + 1, blen);
                body[blen] = '\0';
                memcpy(head, w, pos);
                head[pos] = '\0';
                if (has_f) {
                    text = fstr_expand(body, w);
                    tfree(body);
                    if (!text) {
                        tfree(head);
                        wl_free(wlist);
                        return NULL;
                    }
                    if (strpbrk(text, " \t")) {
                        /* whitespace: stay one word through a command that
                           re-reads its arguments (`set u=f"{x} V"`) */
                        neww = tprintf("%s\"%s\"%s", head, text, tail);
                        from = pos + strlen(text) + 2;
                    } else {
                        neww = tprintf("%s%s%s", head, text, tail);
                        from = pos + strlen(text);
                    }
                } else {
                    text = body;
                    neww = tprintf("%s\"%s\"%s", head, text, tail);
                    from = pos + strlen(text) + 2;
                }
                tfree(text);
                tfree(head);
                tfree(wl->wl_word);
                wl->wl_word = neww;
            }
        }
    }
    return wlist;
}

/* Note that we only do io redirection when we get to here - we also
 * postpone some other things until now.  */
static void
docommand(wordlist *wlist)
{
    wordlist *rwlist;

    if (cp_debug) {
        printf("docommand ");
        wl_print(wlist, stdout);
        putc('\n', stdout);
    }

    /* Do all the things that used to be done by cshpar when the line
     * was read...  */
    wlist = cp_variablesubst(wlist);

    if (!wlist || !wlist->wl_word)
        return;

    pwlist(wlist, "After variable substitution");

    wlist = cp_bquote(wlist);
    pwlist(wlist, "After backquote substitution");

    /* Do not expand braces after command circbyline, keep them intact */
    if (!eq(wlist->wl_word, "circbyline"))
        wlist = cp_doglob(wlist);
    pwlist(wlist, "After globbing");

    /* Enhancement-553: f-strings, evaluated AFTER globbing -- cp_doglob()
     * leaves a prefixed word alone, so the {expr} of an f"..." reach this
     * pass intact and the braces it produces (\{ \}) are never globbed */
    wlist = cp_fstringsubst(wlist);
    if (!wlist)
        return;
    pwlist(wlist, "After f-string substitution");

    pwlist_echo(wlist, "Becomes >");

    if (!wlist || !wlist->wl_word) /*CDHW need to free wlist in second case? CDHW*/
        return;

    /* Now loop through all of the commands given. */
    rwlist = wlist;
    while (wlist) {

        char *s;
        int i;
        struct comm *command;
        wordlist *nextc, *ee;

        nextc = wl_find(cp_csep, wlist);

        if (nextc == wlist) {   /* skip leading `;' */
            wlist = wlist->wl_next;
            continue;
        }

        /* Temporarily hide the rest of the command... */
        ee = wlist->wl_prev;
        wl_chop(nextc);
        wl_chop(wlist);

        /* And do the redirection. */
        cp_ioreset();
        for (i = 0; noredirect[i]; i++)
            if (eq(wlist->wl_word, noredirect[i]))
                break;
        if (!noredirect[i])
            if ((wlist = cp_redirect(wlist)) == NULL) {
                cp_ioreset();
                return;
            }

        s = wlist->wl_word;

        /* Look for the command in the command list. */
        for (i = 0; cp_coms[i].co_comname; i++)
            if (strcasecmp(cp_coms[i].co_comname, s) == 0)
                break;

        command = &cp_coms[i];

        /* Now give the user-supplied command routine a try... */
        if (!command->co_func && cp_oddcomm(s, wlist->wl_next))
            goto out;

        /* If it's not there, try it as a unix command. */
        if (!command->co_comname) {
            if (cp_dounixcom && cp_unixcom(wlist))
                goto out;
            fprintf(cp_err, "%s: no such command available in %s\n",
                    s, cp_program);
            goto out;

            /* If it hasn't been implemented */
        } else if (!command->co_func) {
            fprintf(cp_err, "%s: command is not implemented\n", s);
            goto out;
            /* If it's there but spiceonly, and this is nutmeg, error. */
        } else if (ft_nutmeg && command->co_spiceonly) {
            fprintf(cp_err, "%s: command available only in spice\n", s);
            goto out;
        }

        /* The command was a valid spice/nutmeg command. */
        {
            int nargs = wl_length(wlist->wl_next);
            if (nargs < command->co_minargs) {
                if (command->co_argfn &&
                    cp_getvar("interactive", CP_BOOL, NULL, 0)) {
                    command->co_argfn (wlist->wl_next, command);
                } else {
                    fprintf(cp_err, "%s: too few args.\n", s);
                }
            } else if (nargs > command->co_maxargs) {
                fprintf(cp_err, "%s: too many args.\n", s);
            } else {
                /* Enhancement-544: an alter/altermod reaching this dispatcher
                 * is the USER's (the loop commands call the command from C);
                 * only those are journaled across internal resets. */
                alter_journal_dispatch(command->co_comname, 1);
                command->co_func (wlist->wl_next);
                alter_journal_dispatch(command->co_comname, 0);
            }
        }

    out:
        wl_append(ee, wlist);
        wl_append(wlist, nextc);

        if (!ee)
            rwlist = wlist;

        wlist = nextc;
    }

    wl_free(rwlist);

    /* Do periodic sorts of things... */
    cp_periodic();

    cp_ioreset();
}


/* Execute a block.  There can be a number of return values from this routine.
 *  NORMAL indicates a normal termination
 *  BROKEN indicates a break -- if the caller is a breakable loop,
 *      terminate it, otherwise pass the break upwards
 *  CONTINUED indicates a continue -- if the caller is a continuable loop,
 *      continue, else pass the continue upwards
 *  Any other return code is considered a pointer to a string which is
 *      a label somewhere -- if this label is present in the block,
 *      goto it, otherwise pass it up. Note that this prevents jumping
 *      into a loop, which is good.
 *
 * Note that here is where we expand variables, ``, and globs for
 * controls.
 *
 * The 'num' argument is used by break n and continue n.  */
static char *
doblock(struct control *bl, int *num)
{
    struct control *ch, *cn = NULL;
    wordlist *wl, *wltmp;
    char *i, *wlword;
    int nn;

    nn = *num + 1; /*CDHW this is a guess... CDHW*/

    switch (bl->co_type) {
    case CO_WHILE:
        if (!bl->co_children) {
            fprintf(cp_err, "Warning: Executing empty 'while' block.\n"
                    "         (Use a label statement as a no-op "
                    "to suppress this warning.)\n");
        }
        while (bl->co_cond && cp_istrue(bl->co_cond)) {
            if (!bl->co_children) cp_periodic();  /*CDHW*/
            for (ch = bl->co_children; ch; ch = cn) {
                cn = ch->co_next;
                i = doblock(ch, &nn);
                switch (*i) {

                case NORMAL:
                    break;

                case BROKEN:    /* Break. */
                    if (nn < 2) {
                        return (NORMAL_STR);
                    } else {
                        *num = nn - 1;
                        return (BROKEN_STR);
                    }

                case CONTINUED: /* Continue. */
                    if (nn < 2) {
                        cn = NULL;
                        break;
                    } else {
                        *num = nn - 1;
                        return (CONTINUED_STR);
                    }

                default:
                    cn = findlabel(i, bl->co_children);
                    if (!cn)
                        return (i);
                }
            }
        }
        break;

    case CO_DOWHILE:
        do {
            for (ch = bl->co_children; ch; ch = cn) {
                cn = ch->co_next;
                i = doblock(ch, &nn);
                switch (*i) {

                case NORMAL:
                    break;

                case BROKEN:    /* Break. */
                    if (nn < 2) {
                        return (NORMAL_STR);
                    } else {
                        *num = nn - 1;
                        return (BROKEN_STR);
                    }

                case CONTINUED: /* Continue. */
                    if (nn < 2) {
                        cn = NULL;
                        break;
                    } else {
                        *num = nn - 1;
                        return (CONTINUED_STR);
                    }

                default:
                    cn = findlabel(i, bl->co_children);
                    if (!cn)
                        return (i);
                }
            }
        } while (bl->co_cond && cp_istrue(bl->co_cond));
        break;

    case CO_REPEAT:
        if (!bl->co_children) {
            fprintf(cp_err, "Warning: Executing empty 'repeat' block.\n");
            fprintf(cp_err, "         (Use a label statement as a no-op to suppress this warning.)\n");
        }
        if (!bl->co_timestodo) bl->co_timestodo = bl->co_numtimes;
        /*bl->co_numtimes: total repeat count
          bl->co_numtimes = -1: repeat forever
          bl->co_timestodo: remaining repeats*/
        while ((bl->co_timestodo > 0) ||
               (bl->co_timestodo == -1)) {
            if (!bl->co_children) cp_periodic();  /*CDHW*/
            if (bl->co_timestodo != -1) bl->co_timestodo--;
            /* loop through all stements inside rpeat ... end */
            for (ch = bl->co_children; ch; ch = cn) {
                cn = ch->co_next;
                i = doblock(ch, &nn);
                switch (*i) {

                case NORMAL:
                    break;

                case BROKEN:    /* Break. */
                    /* before leaving repeat loop set remaining timestodo to 0 */
                    bl->co_timestodo = 0;
                    if (nn < 2) {
                        return (NORMAL_STR);
                    } else {
                        *num = nn - 1;
                        return (BROKEN_STR);
                    }

                case CONTINUED: /* Continue. */
                    if (nn < 2) {
                        cn = NULL;
                        break;
                    } else {
                        /* before leaving repeat loop set remaining timestodo to 0 */
                        bl->co_timestodo = 0;
                        *num = nn - 1;
                        return (CONTINUED_STR);
                    }

                default:
                    cn = findlabel(i, bl->co_children);

                    if (!cn) {
                        /* no label found inside repeat loop:
                           before leaving loop set remaining timestodo to 0 */
                        bl->co_timestodo = 0;
                        return (i);
                    }
                }
            }
        }
        break;

    case CO_IF:
        if (bl->co_cond && cp_istrue(bl->co_cond)) {
            for (ch = bl->co_children; ch; ch = cn) {
                cn = ch->co_next;
                i = doblock(ch, &nn);
                if (*i > 2) {
                    cn = findlabel(i,
                                   bl->co_children);
                    if (!cn)
                        return (i);
                    else
                        tfree(i);
                } else if (*i != NORMAL) {
                    *num = nn;
                    return (i);
                }
            }
        } else {
            for (ch = bl->co_elseblock; ch; ch = cn) {
                cn = ch->co_next;
                i = doblock(ch, &nn);
                if (*i > 2) {
                    cn = findlabel(i, bl->co_elseblock);
                    if (!cn)
                        return (i);
                } else if (*i != NORMAL) {
                    *num = nn;
                    return (i);
                }
            }
        }
        break;

    case CO_FOREACH:
        wltmp = cp_fstringsubst(cp_variablesubst(cp_bquote(cp_doglob(wl_copy(bl->co_text)))));
        for (wl = wltmp; wl; wl = wl->wl_next) {
            cp_vset(bl->co_foreachvar, CP_STRING, wl->wl_word);
            for (ch = bl->co_children; ch; ch = cn) {
                cn = ch->co_next;
                i = doblock(ch, &nn);
                switch (*i) {

                case NORMAL:
                    break;

                case BROKEN:    /* Break. */
                    if (nn < 2) {
                        wl_free(wltmp);
                        return (NORMAL_STR);
                    } else {
                        *num = nn - 1;
                        wl_free(wltmp);
                        return (BROKEN_STR);
                    }

                case CONTINUED: /* Continue. */
                    if (nn < 2) {
                        cn = NULL;
                        break;
                    } else {
                        *num = nn - 1;
                        wl_free(wltmp);
                        return (CONTINUED_STR);
                    }

                default:
                    cn = findlabel(i, bl->co_children);
                    if (!cn) {
                        wl_free(wltmp);
                        return (i);
                    }
                }
            }
        }
        wl_free(wltmp);
        break;

    case CO_BREAK:
        if (bl->co_numtimes > 0) {
            *num = bl->co_numtimes;
            return (BROKEN_STR);
        } else {
            fprintf(cp_err, "Warning: break %d a no-op\n",
                    bl->co_numtimes);
            return (NORMAL_STR);
        }

    case CO_CONTINUE:
        if (bl->co_numtimes > 0) {
            *num = bl->co_numtimes;
            return (CONTINUED_STR);
        } else {
            fprintf(cp_err, "Warning: continue %d a no-op\n",
                    bl->co_numtimes);
            return (NORMAL_STR);
        }

    case CO_GOTO:
        wl = cp_variablesubst(cp_bquote(cp_doglob(wl_copy(bl->co_text))));
        wlword = wl->wl_word;
        wl->wl_word = NULL;
        wl_free(wl);
        return (wlword);

    case CO_LABEL:
        /* Do nothing. */
        cp_periodic();  /*CDHW needed to avoid lock-ups when loop contains only a label CDHW*/
        break;

    case CO_STATEMENT:
        docommand(wl_copy(bl->co_text));
        break;

    case CO_UNFILLED:
        /* There was probably an error here... */
        fprintf(cp_err, "Warning: ignoring previous error\n");
        break;

    default:
        fprintf(cp_err,
                "doblock: Internal Error: bad block type %d\n",
                bl->co_type);
        return (NORMAL_STR);
    }
    return (NORMAL_STR);
}


/* Maxiumum number of cheverons used for the alternative prompt */
#define MAX_CHEVRONS    16

/* Get the alternate prompt.
   Number of chevrons indicates stack depth.
   Returns NULL when there is no alternate prompt.
   SJB 28th April 2005 */
char *
get_alt_prompt(void)
{
    int i = 0;
    static char buf[MAX_CHEVRONS + 2];  /* includes terminating space & null */
    struct control *c;

    /* If nothing on the command stack return NULL */
    if (cend[stackp] == NULL)
        return NULL;

    /* measure stack depth */
    for (c = cend[stackp]->co_parent; c; c = c->co_parent)
        i++;

    if (i == 0) {
        return NULL;
    }

    /* Avoid overflow of buffer and
       indicate when we've limited the chevrons by starting with a '+' */
    if (i > MAX_CHEVRONS) {
        i = MAX_CHEVRONS;
        buf[0] = '+';
    } else {
        buf[0] = '>';
    }

    /* return one chevron per command stack depth */
    {
        int j;
        for (j = 1; j < i; j++)
            buf[j] = '>';

        /* Add space and terminate */
        buf[j] = ' ';
        buf[j + 1] = '\0';
    }

    return buf;
} /* end of function get_alt_prompt */



/* Get a command. This does all the bookkeeping things like turning
 * command completion on and off...  */
static wordlist *
getcommand(char *string)
{
    wordlist *wlist;

    if (cp_debug) {
        fprintf(cp_err, "calling getcommand %s\n", string ? string : "");
    }

#if !defined(HAVE_GNUREADLINE) && !defined(HAVE_BSDEDITLINE)
    /* set cp_altprompt for use by the lexer - see parser/lexical.c */
    cp_altprompt = get_alt_prompt();
#else
    cp_cwait = TRUE;
#endif /* !defined(HAVE_GNUREADLINE) && !defined(HAVE_BSDEDITLINE) */

    wlist = cp_parse(string);
    cp_cwait = FALSE;
    if (cp_debug) {
        printf("getcommand ");
        wl_print(wlist, stdout);
        putc('\n', stdout);
    }
    return wlist;
}


/* va: TODO: free control structure(s) before overwriting (memory leakage) */
int
cp_evloop(char *string)
{
    wordlist *wlist, *ww, *freewl;
    struct control *x;
    char *i;

#define newblock                                                \
    do {                                                        \
        cend[stackp]->co_children = TMALLOC(struct control, 1); \
        ZERO(cend[stackp]->co_children, struct control);        \
        cend[stackp]->co_children->co_parent = cend[stackp];    \
        cend[stackp] = cend[stackp]->co_children;               \
        cend[stackp]->co_type = CO_UNFILLED;                    \
    } while(0)

    for (;;) {
        freewl = wlist = getcommand(string);
        if (wlist == NULL) { /* End of file or end of user input. */
            if (cend[stackp] && cend[stackp]->co_parent && !string) {
                cp_resetcontrol(TRUE);
                continue;
            }
            else {
                return (0);
            }
        }
        if ((wlist->wl_word == NULL) || (*wlist->wl_word == '\0')) {
            /* User just typed return. */
            wl_free(wlist); /* va, avoid memory leak */
            if (string) {
                return 1;
            }
            else {
                cp_event--;
                continue;
            }
        }

        /* Just a check... */
        for (ww = wlist; ww; ww = ww->wl_next) {
            if (!ww->wl_word) {
                fprintf(cp_err,
                        "cp_evloop: Internal Error: NULL word pointer\n");
                wl_free(wlist);
                continue;
            }
        }


        /* Add this to the control structure list. If cend->co_type is
         * CO_UNFILLED, the last line was the beginning of a block,
         * and this is the unfilled first statement.
         */
        /* va: TODO: free old structure and its content, before overwriting */
        if (cend[stackp] && (cend[stackp]->co_type != CO_UNFILLED)) {
            cend[stackp]->co_next = TMALLOC(struct control, 1);
            ZERO(cend[stackp]->co_next, struct control);
            cend[stackp]->co_next->co_prev = cend[stackp];
            cend[stackp]->co_next->co_parent = cend[stackp]->co_parent;
            cend[stackp] = cend[stackp]->co_next;
        } else if (!cend[stackp]) {
            control[stackp] = cend[stackp] = TMALLOC(struct control, 1);
            ZERO(cend[stackp], struct control);
        }

        if (eq(wlist->wl_word, "while")) {
            cend[stackp]->co_type = CO_WHILE;
            cend[stackp]->co_cond = wl_copy(wlist->wl_next); /* va, wl_copy */
            if (!cend[stackp]->co_cond) {
                fprintf(stderr,
                        "Error: missing while condition, 'false' will be assumed.\n");
            }
            newblock;
        } else if (eq(wlist->wl_word, "dowhile")) {
            cend[stackp]->co_type = CO_DOWHILE;
            cend[stackp]->co_cond = wl_copy(wlist->wl_next); /* va, wl_copy */
            if (!cend[stackp]->co_cond) {
                /* va: prevent misinterpretation as trigraph sequence with \-sign */
                fprintf(stderr,
                        "Error: missing dowhile condition, '?\?\?' will be assumed.\n");
            }
            newblock;
        } else if (eq(wlist->wl_word, "repeat")) {
            cend[stackp]->co_type = CO_REPEAT;
            if (!wlist->wl_next) {
                cend[stackp]->co_numtimes = -1;
            } else {
                char *s = "1";
                double val;

                struct wordlist *t;  /*CDHW*/
                /*CDHW wlist = cp_variablesubst(cp_bquote(cp_doglob(wl_copy(wlist)))); Wrong order? Leak? CDHW*/
                t = cp_doglob(cp_bquote(cp_variablesubst(wl_copy(wlist)))); /*CDHW leak from cp_doglob? */

                if (!t->wl_next) {
                    fprintf(cp_err, "Error: Undefined number after command 'repeat', assume 1\n");
                }
                else
                    s = t->wl_next->wl_word;

                if (ft_numparse(&s, FALSE, &val) > 0) {
                    /* Can be converted to int */
                    if (val < 0) {
                        fprintf(cp_err,
                                "Error: can't repeat a negative number of times\n");
                        val = 0.0;
                    }
                    cend[stackp]->co_numtimes = (int) val;
                }
                else {
                    fprintf(cp_err,
                            "Error: bad repeat argument %s\n",
                            t->wl_next->wl_word); /* CDHW */
                }
                wl_free(t);
                t = NULL;  /* CDHW */
            }
            newblock;

        } else if (eq(wlist->wl_word, "if")) {
            cend[stackp]->co_type = CO_IF;
            cend[stackp]->co_cond = wl_copy(wlist->wl_next); /* va, wl_copy */
            if (!cend[stackp]->co_cond) {
                fprintf(stderr,
                        "Error: missing if condition.\n");
            }
            newblock;

        } else if (eq(wlist->wl_word, "foreach")) {
            cend[stackp]->co_type = CO_FOREACH;
            if (wlist->wl_next) {
                wlist = wlist->wl_next;
                cend[stackp]->co_foreachvar =
                    copy(wlist->wl_word);
                wlist = wlist->wl_next;
            }
            else {
                fprintf(stderr,
                        "Error: missing foreach variable.\n");
                wl_free(wlist);
                continue;
            }
            wlist = cp_doglob(wlist);
            cend[stackp]->co_text = wl_copy(wlist);
            newblock;
        } else if (eq(wlist->wl_word, "label")) {
            cend[stackp]->co_type = CO_LABEL;
            if (wlist->wl_next) {
                cend[stackp]->co_text = wl_copy(wlist->wl_next);
                /* I think of everything, don't I? */
                cp_addkword(CT_LABEL, wlist->wl_next->wl_word);
                if (wlist->wl_next->wl_next)
                    fprintf(cp_err,
                            "Warning: ignored extra junk after label.\n");
            } else {
                fprintf(stderr, "Error: missing label.\n");
            }

        } else if (eq(wlist->wl_word, "goto")) {
            /* Incidentally, this won't work if the values 1 and 2 ever get
             * to be valid character pointers -- I think it's reasonably
             * safe to assume they aren't...  */
            cend[stackp]->co_type = CO_GOTO;
            if (wlist->wl_next) {
                cend[stackp]->co_text = wl_copy(wlist->wl_next);
                if (wlist->wl_next->wl_next)
                    fprintf(cp_err,
                            "Warning: ignored extra junk after goto.\n");
            } else {
                fprintf(stderr, "Error: missing label.\n");
            }
        } else if (eq(wlist->wl_word, "continue")) {
            cend[stackp]->co_type = CO_CONTINUE;
            if (wlist->wl_next) {
                cend[stackp]->co_numtimes = scannum(wlist->wl_next->wl_word);
                if (wlist->wl_next->wl_next)
                    fprintf(cp_err,
                            "Warning: ignored extra junk after continue %d.\n",
                            cend[stackp]->co_numtimes);
            } else {
                cend[stackp]->co_numtimes = 1;
            }
        } else if (eq(wlist->wl_word, "break")) {
            cend[stackp]->co_type = CO_BREAK;
            if (wlist->wl_next) {
                cend[stackp]->co_numtimes = scannum(wlist->wl_next->wl_word);
                if (wlist->wl_next->wl_next)
                    fprintf(cp_err,
                            "Warning: ignored extra junk after break %d.\n",
                            cend[stackp]->co_numtimes);
            } else {
                cend[stackp]->co_numtimes = 1;
            }
        } else if (eq(wlist->wl_word, "end")) {
            /* Throw away this thing if not in a block. */
            if (!cend[stackp]->co_parent) {
                fprintf(stderr, "Error: no block to end.\n");
                cend[stackp]->co_type = CO_UNFILLED;
            } else if (cend[stackp]->co_prev) {
                cend[stackp]->co_prev->co_next = NULL;
                x = cend[stackp];
                cend[stackp] = cend[stackp]->co_parent;
                tfree(x);
                x = NULL;
            } else {
                x = cend[stackp];
                cend[stackp] = cend[stackp]->co_parent;
                cend[stackp]->co_children = NULL;
                tfree(x);
                x = NULL;
            }
        } else if (eq(wlist->wl_word, "else")) {
            if (!cend[stackp]->co_parent ||
                    (cend[stackp]->co_parent->co_type != CO_IF)) {
                fprintf(stderr, "Error: misplaced else.\n");
                cend[stackp]->co_type = CO_UNFILLED;
            } else {
                if (cend[stackp]->co_prev)
                    cend[stackp]->co_prev->co_next = NULL;
                else
                    cend[stackp]->co_parent->co_children = NULL;
                cend[stackp]->co_parent->co_elseblock = cend[stackp];
                cend[stackp]->co_prev = NULL;
            }
        } else {
            cend[stackp]->co_type = CO_STATEMENT;
            cend[stackp]->co_text = wl_copy(wlist);
        }

        if (!cend[stackp]->co_parent) {
            x = cend[stackp];
            /* We have to toss this do-while loop in here so
             * that gotos at the top level will work.
             */
            do {
                int nn = 0; /* CDHW */
                i = doblock(x, &nn);
                switch (*i) {
                case NORMAL:
                    break;
                case BROKEN:
                    fprintf(cp_err,
                            "Error: break not in loop or too many break levels given\n");
                    break;
                case CONTINUED:
                    fprintf(cp_err,
                            "Error: continue not in loop or too many continue levels given\n");
                    break;
                default:
                    x = findlabel(i, control[stackp]);
                    if (!x)
                        fprintf(cp_err, "Error: label %s not found\n", i);
                    tfree(i);
                }
                if (x)
                    x = x->co_next;
            } while (x);
        }
        wl_free(freewl);
        if (string)
            return (1); /* The return value is irrelevant. */
    } /* end of unconditional loop */
} /* end of function cp_evloop */


/* This blows away the control structures... */
void cp_resetcontrol(bool warn)
{
    if (warn) {
        fprintf(cp_err, "Warning: clearing control structures\n");
        if (cend[stackp] && cend[stackp]->co_parent)
            fprintf(cp_err, "Warning: EOF before block terminated\n");
    }
    /* free the control structures */
    cp_free_control();
    control[0] = cend[0] = NULL;
    stackp = 0;
    cp_kwswitch(CT_LABEL, NULL);
}


/* Push or pop a new control structure set... */
void
cp_popcontrol(void)
{
    if (cp_debug)
        fprintf(cp_err, "pop: stackp: %d -> %d\n", stackp, stackp - 1);
    if (stackp < 1) {
        fprintf(cp_err, "cp_popcontrol: Internal Error: stack empty\n");
    } else {
        /* va: free unused control structure */
        ctl_free(control[stackp]);
        stackp--;
    }
}


void
cp_pushcontrol(void)
{
    if (cp_debug)
        fprintf(cp_err, "push: stackp: %d -> %d\n", stackp, stackp + 1);
    if (stackp > CONTROLSTACKSIZE - 2) {
        fprintf(cp_err, "Error: stack overflow -- max depth = %d\n",
                CONTROLSTACKSIZE);
        stackp = 0;
    } else {
        stackp++;
        control[stackp] = cend[stackp] = NULL;
    }
}


/* And this returns to the top level (for use in the interrupt handlers). */
void
cp_toplevel(void)
{
    stackp = 0;
    if (cend[stackp])
        while (cend[stackp]->co_parent)
            cend[stackp] = cend[stackp]->co_parent;
}


/* va: This totally frees the control structures */
static void
cp_free_control(void)
{
    int i;

    /* Free the control structures */
    for (i = stackp; i >= 0; i--) {
        ctl_free(control[i]);
    }

    control[0] = cend[0] = NULL;
    stackp = 0;
}

/* Enhancement-480: is a control block (`if`, `while`, `repeat`, `foreach`,
 * `dowhile`) still open?
 *
 * `cp_evloop` is called once per line of a `.control` section, so its own
 * end-of-input check never sees the end of the SECTION -- an unterminated
 * block therefore swallowed every command after it, in silence, and ngspice
 * exited 0. The caller asks here once the section has been fed. */
bool cp_block_open(void)
{
    return cend[stackp] && cend[stackp]->co_parent;
}
