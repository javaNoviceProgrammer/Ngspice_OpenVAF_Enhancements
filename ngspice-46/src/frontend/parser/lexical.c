/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/

/*
 * Initial lexer.
 */

#include "ngspice/defines.h"
#include "ngspice/ngspice.h"
#include <ctype.h>
#include "ngspice/cpdefs.h"

#include <errno.h>

#ifdef HAVE_UNISTD_H
#include <unistd.h>
#endif

#ifdef HAVE_PWD_H
#include <sys/types.h>
#include <pwd.h>
#endif

#include "ngspice/fteinput.h"
#include "lexical.h"

/** Constants related to characters that form their own words.
 ** These expressions will be resolved at compile time */
#define ID_SOLO_CHAR 1 /* Identifier for special chars */

/* Largest of the special chars */
#define MAX_SOLO_CHAR1 ('<' > '>' ? '<' : '>')
#define MAX_SOLO_CHAR2 (MAX_SOLO_CHAR1 > ';' ? MAX_SOLO_CHAR1 : ';')
#define MAX_SOLO_CHAR (MAX_SOLO_CHAR2 > '&' ? MAX_SOLO_CHAR2 : '&')

/* Smallest of the special chars */
#define MIN_SOLO_CHAR1 ('<' < '>' ? '<' : '>')
#define MIN_SOLO_CHAR2 (MIN_SOLO_CHAR1 < ';' ? MIN_SOLO_CHAR1 : ';')
#define MIN_SOLO_CHAR (MIN_SOLO_CHAR2 < '&' ? MIN_SOLO_CHAR2 : '&')

/* Largest index of solo char array */
#define MAX_INDEX_SOLO_CHAR (MAX_SOLO_CHAR - MIN_SOLO_CHAR)

static void prompt(void);

extern bool cp_echo;  /* For CDHW patches: defined in variable.c */

FILE *cp_inp_cur = NULL;
int cp_event = 1;
bool cp_interactive = TRUE;
bool cp_bqflag = FALSE;
char *cp_promptstring = NULL;
char *cp_altprompt = NULL;

#define ESCAPE  '\033'

/* Return a list of words, with backslash quoting and '' quoting done.
 * Strings enclosed in "" or `` are made single words and returned,
 * but with the "" or `` still present. For the \ and '' cases, the
 * 8th bit is turned on (as in csh) to prevent them from being recognized,
 * and stripped off once all processing is done. We also have to deal with
 * command, filename, and keyword completion here.
 * If string is non-NULL, then use it instead of the fp. Escape and EOF
 * have no business being in the string.
 */

struct cp_lexer_buf
{
    int i, sz;
    char *s;
};


static inline void
push(struct cp_lexer_buf *buf, int c)
{
    if (buf->sz <= buf->i) {
        buf->sz += MAX(64, buf->sz);
        buf->s = TREALLOC(char, buf->s, buf->sz);
    }
    buf->s[buf->i++] = (char) c;
}


#define append(word)                            \
    wl_append_word(&wlist, &wlist_tail, word)


#define newword                                         \
    do {                                                \
        append(copy_substring(buf.s, buf.s + buf.i));   \
        buf.i = 0;                                      \
    } while(0)


/* CDHW Debug function */
/* CDHW used to perform function of set echo */

static void
pwlist_echo(wordlist *wlist, char *name)
{
    wordlist *wl;

    if (!cp_echo || cp_debug)
        return;

    fprintf(cp_err, "%s ", name);
    for (wl = wlist; wl; wl = wl->wl_next)
        fprintf(cp_err, "%s ", wl->wl_word);
    fprintf(cp_err, "\n");
}


static int
cp_readchar(char **string, FILE *fptr)
{
    if (*string == NULL)
        return input(fptr);

    if (**string)
        return *(*string)++;
    else
        return '\n';
}


/* CDHW */

/* Enhancement-553: the length (1 or 2) of a string prefix -- r, f, rf or fr,
 * in either case -- that `word` (of `len` characters, not terminated) consists
 * of exactly, else 0. Shared by the lexer, cp_unquote() and the f-string pass
 * so that the three agree on what a prefix is. */
int cp_string_prefix_len(const char *word, size_t len)
{
    if (len < 1 || len > 2)
        return 0;
    if (!strchr("rRfF", word[0]) || (len == 2 && !strchr("rRfF", word[1])))
        return 0;
    if (len == 2 && tolower((unsigned char) word[0]) == tolower((unsigned char) word[1]))
        return 0;
    return (int) len;
}

/* Enhancement-556 (hunt F3): the prefixed string a WORD carries, if it does
 * -- r"..." / f"..." / rf"..." at the word's start or after `=`, `(` or `,`
 * (exactly where the lexer accepts a prefix), closing at the next `"`.
 * Returns the prefix length (1 or 2), its position in `*pos` and the closing
 * quote's in `*end`, else 0. The glob skip and the f-string pass share it,
 * so that `let z=f"{7}"` -- which the deck reader makes of `let z = f"{7}"`
 * -- is treated like `echo f"{7}"`, and `f"{1+1}"=2` -- what it makes of an
 * `if f"{1+1}" = 2` -- keeps its tail: before this, the two recognised a
 * prefix at the word start only, the lexer after `=` as well, and an
 * f-string after `name=` had its braces globbed away and was never
 * evaluated. The search starts at `word + from`, so a caller can walk a
 * word carrying more than one. */
int cp_string_prefix_at(const char *word, size_t from, size_t *pos, size_t *end)
{
    const char *q, *e;
    size_t n, k;
    if (!word)
        return 0;
    n = strlen(word);
    if (from >= n)
        return 0;
    for (q = strchr(word + from, '"'); q; q = strchr(q + 1, '"')) {
        if (q == word)
            continue;
        e = strchr(q + 1, '"');
        if (!e)
            return 0;
        for (k = 1; k <= 2 && (size_t) (q - word) >= k; k++) {
            const char *start = q - k;
            if (cp_string_prefix_len(start, k) > 0
                && (start == word || start[-1] == '=' || start[-1] == '('
                    || start[-1] == ',')) {
                if (pos)
                    *pos = (size_t) (start - word);
                if (end)
                    *end = (size_t) (e - word);
                return (int) k;
            }
        }
        q = e;                      /* an unprefixed pair: skip past it */
    }
    return 0;
}

/* The prefix at the END of the word read so far, if the word ends in one:
 * the whole word (`r`, `rf`), or a prefix after `=`, `(` or `,` -- so that
 * `set t=r'...'` and `title=r"..."` carry one. 0 otherwise. */
static int cp_string_prefix_tail(const char *word, size_t len)
{
    size_t k;
    for (k = 1; k <= 2 && k <= len; k++) {
        const char *start = word + len - k;
        if (cp_string_prefix_len(start, k) > 0
            && (start == word || start[-1] == '=' || start[-1] == '(' || start[-1] == ','))
            return (int) k;
    }
    return 0;
}

wordlist *
cp_lexer(char *string)
{
    int c, d;
    wordlist *wlist, *wlist_tail;
    struct cp_lexer_buf buf, linebuf;
    int paren;

    if (!cp_inp_cur)
        cp_inp_cur = cp_in;

    /* prompt for string if none is passed */
    if (!string && cp_interactive) {
        prompt();
    }

    wlist = wlist_tail = NULL;

    buf.sz = 0;
    buf.s = NULL;
    linebuf.sz = 0;
    linebuf.s = NULL;

nloop:
    if (wlist)
        wl_free(wlist);
    wlist = wlist_tail = NULL;
    buf.i = 0;
    linebuf.i = 0;
    paren = 0;

    for (;;) {

        /* if string, read from string, else read from stdin */
        c = cp_readchar(&string, cp_inp_cur);

    gotchar:

        if (string && (c == ESCAPE))
            continue;

        if (c != EOF)
            push(&linebuf, c);

        /* if '\' or '^', add following character to linebuf */
        if ((c == '\\' && DIR_TERM != '\\') || (c == '\026') /* ^V */ ) {
            c = cp_readchar(&string, cp_inp_cur);
            push(&linebuf, c);
        }

        /* if reading from fcn backeval() for backquote subst. */
        if ((c == '\n') && cp_bqflag)
            c = ' ';

        if ((c == EOF) && cp_bqflag)
            c = '\n';

        /* '#' or '*' as the first character in a line,
           starts a comment line, drop it */
        if ((c == '#' || c == '*') && (linebuf.i == 1)) {
            if (string) {
                wl_free(wlist);
                tfree(buf.s);
                tfree(linebuf.s);
                return NULL;
            }
            while (((c = cp_readchar(&string, cp_inp_cur)) != '\n') &&
                    (c != EOF)) {
                ;
            }
            prompt();
            goto nloop;
        }

        /* check if we are inside of parens during reading:
           if we are and ',' or ';' occur: no new line */
        if ((c == '(') || (c == '['))
            paren++;
        else if ((c == ')') || (c == ']'))
            paren--;

        /* What else has to be decided, depending on c ? */
        switch (c) {

        /* new word to wordlist, when space or tab follow */
        case ' ':
        case '\t':
            if (buf.i > 0)
                newword;
            break;

        /* new word to wordlist, when \n follows */
        case '\n':
            if (buf.i)
                newword;
            if (!wlist_tail)
                append(NULL);
            goto done;

        /* if ' read until next ' is hit, will form a new word,
           but without the ' */
        case '\'':
            /* Enhancement-553: r'...', f'...', rf'...' -- the word so far is
               exactly a string prefix. The literal is turned into the
               double-quoted form, quotes kept, so that cp_unquote() and the
               f-string pass see one spelling; a backslash is kept verbatim. */
            if (cp_string_prefix_tail(buf.s, (size_t) buf.i) > 0) {
                push(&buf, '"');
                while ((c = cp_readchar(&string, cp_inp_cur)) != '\'')
                {
                    if ((c == '\n') || (c == EOF) || (c == ESCAPE))
                        goto gotchar;
                    push(&buf, c);
                    push(&linebuf, c);
                }
                push(&buf, '"');
                push(&linebuf, '\'');
                break;
            }
            while ((c = cp_readchar(&string, cp_inp_cur)) != '\'')
            {
                if ((c == '\n') || (c == EOF) || (c == ESCAPE))
                    goto gotchar;
                push(&buf, c);
                push(&linebuf, c);
            }
            push(&linebuf, '\'');
            break;

        /* if " or `, read until next " or ` is hit, will form a new word,
           including the quotes.
           In case of \, the next character gets the eights bit set. */
        case '"':
        case '`':
            d = c;
            {
                /* Enhancement-553: inside a prefixed string (r"..", f"..) a
                   backslash is kept as written, so that \{ and \} can reach the
                   f-string pass and a raw string is raw */
                const int raw = (d == '"' && cp_string_prefix_tail(buf.s, (size_t) buf.i) > 0);
                push(&buf, d);
                while ((c = cp_readchar(&string, cp_inp_cur)) != d)
                {
                    if ((c == '\n') || (c == EOF) || (c == ESCAPE))
                        goto gotchar;
                    if (c == '\\' && !raw) {
                        push(&linebuf, c);
                        c = cp_readchar(&string, cp_inp_cur);
                        push(&buf, c);
                        push(&linebuf, c);
                    } else {
                        push(&buf, c);
                        push(&linebuf, c);
                    }
                }
            }
            push(&buf, d);
            push(&linebuf, d);
            break;

        case ',':
            if ((paren < 1) && (buf.i > 0)) {
                newword;
                break;
            }
            goto ldefault;

        case ';':  /* CDHW semicolon inside parentheses is part of expression */
            if (paren > 0) {
                push(&buf, c);
                break;
            }
            goto ldefault;

        case '&':  /* va: $&name is one word */
            if ((buf.i >= 1) && (buf.s[buf.i - 1] == '$')) {
                push(&buf, c);
                break;
            }
            goto ldefault;

        case '<':
        case '>':  /* va: <=, >= are unbreakable words */
            if (string)
                if ((buf.i == 0) && (*string == '=')) {
                    push(&buf, c);
                    break;
                }
            goto ldefault;

        default:
            /* $< is a special case where the '<' is not treated
             * as a character forming its own word */
        ldefault: {
            /* Lookup table for "solo" chars forming their own word */
            static const char id_solo_chars[MAX_INDEX_SOLO_CHAR + 1] = {
                ['<' - MIN_SOLO_CHAR] = ID_SOLO_CHAR,
                ['>' - MIN_SOLO_CHAR] = ID_SOLO_CHAR,
                [';' - MIN_SOLO_CHAR] = ID_SOLO_CHAR,
                ['&' - MIN_SOLO_CHAR] = ID_SOLO_CHAR
            };

            /* Find index into solo chars table */
            const unsigned int index_char =
                    (unsigned int) c - (unsigned int) MIN_SOLO_CHAR;

            /* Flag that the current character c is a solo character */
            const bool f_solo_char = index_char <= MAX_INDEX_SOLO_CHAR &&
                    id_solo_chars[index_char];
            bool f_is_dollar_lt = FALSE;

            if (f_solo_char && buf.i > 0) {
                /* The current char is a character forming its own word,
                 * unless it is "$<" */
                if (c == '<' && buf.s[buf.i - 1] == '$') { /* is "$<" */
                    f_is_dollar_lt = TRUE; /* set flag that "$<" found */
                }
                else {
                    /* not "$<", so terminate current word and start
                     * another one */
                     newword;
                }
            }

            push(&buf, c); /* Add the current char to the current word */

            if (f_solo_char && !f_is_dollar_lt) {
                /* Split into a new word if this char forms its own word */
                newword;
            }
        } /* end of ldefault block */
        } /* end of switch over character value */
    } /* end of loop over characters */

done:
    if (wlist->wl_word)
        pwlist_echo(wlist, "Command>");
    tfree(buf.s);
    tfree(linebuf.s);
    return wlist;
}


static void
prompt(void)
{
    char *s;

    if (cp_interactive == FALSE)
        return;

    if (cp_altprompt)
        s = cp_altprompt;
    else if (cp_promptstring)
        s = cp_promptstring;
    else
        s = "-> ";

    while (*s) {
        /* NOTE: The FALLTHROUGH comment is used to suppress a GCC warning
         * when flag -Wimplicit-fallthrough is present */
        switch (*s) {
        case '!':
            fprintf(cp_out, "%d", cp_event);
            break;
        case '\\':
            if (s[1])
                (void) putc((*++s), cp_out);
            /* FALLTHROUGH */
        default:
            (void) putc((*s), cp_out);
        }
        s++;
    }

    (void) fflush(cp_out);
}
