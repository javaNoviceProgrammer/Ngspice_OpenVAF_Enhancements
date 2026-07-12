/*************
 * Interactive command-line syntax highlighting for ngspice.  Enhancement-169.
 *
 * Colors the interactive command line as it is typed: the command word is shown
 * green when it is a recognized command (looked up in the active command table
 * cp_coms, exactly as the interpreter does) or a control keyword, red when it is
 * not -- so a mistyped command is visible before Enter is pressed.  Numbers,
 * quoted strings and -option flags get their own colors.
 *
 * Live coloring is done by overriding GNU readline's redisplay function; the
 * `synhl' command prints the colorized form of a line non-interactively, which
 * also makes the coloring engine testable in batch mode.
 ************/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cpextern.h"
#include "ngspice/wordlist.h"
#include "ngspice/syntaxhl.h"

#include <ctype.h>
#ifdef HAVE_UNISTD_H
#include <unistd.h>
#endif

#ifdef HAVE_GNUREADLINE
#include <readline/readline.h>
#endif

/* ANSI SGR color codes. */
#define SYN_CMD_OK  "\033[32m"   /* green   : recognized command      */
#define SYN_CMD_BAD "\033[31m"   /* red     : unknown command         */
#define SYN_NUM     "\033[33m"   /* yellow  : number                  */
#define SYN_STRING  "\033[35m"   /* magenta : quoted string           */
#define SYN_OPT     "\033[36m"   /* cyan    : -option flag            */
#define SYN_RESET   "\033[0m"

/* Control-flow keywords the interpreter handles directly (not in cp_coms). */
static const char * const keywords[] = {
    "if", "else", "end", "while", "dowhile", "repeat", "foreach",
    "begin", "break", "continue", "label", "goto", NULL
};


static int is_command(const char *word)
{
    int i;
    if (cp_coms)
        for (i = 0; cp_coms[i].co_comname; i++)
            if (strcasecmp(cp_coms[i].co_comname, word) == 0)
                return 1;
    return 0;
}


static int is_keyword(const char *word)
{
    int i;
    for (i = 0; keywords[i]; i++)
        if (strcasecmp(keywords[i], word) == 0)
            return 1;
    return 0;
}


/* Is `word` a leading prefix of some command or keyword?  Used so a partly
 * typed command (e.g. "plo") reads as neutral -- still on its way to valid --
 * rather than flashing red until it is complete. */
static int is_command_prefix(const char *word)
{
    size_t n = strlen(word);
    int i;
    if (n == 0)
        return 1;
    if (cp_coms)
        for (i = 0; cp_coms[i].co_comname; i++)
            if (strncasecmp(cp_coms[i].co_comname, word, n) == 0)
                return 1;
    for (i = 0; keywords[i]; i++)
        if (strncasecmp(keywords[i], word, n) == 0)
            return 1;
    return 0;
}


static int looks_like_number(const char *tok)
{
    if (*tok == '+' || *tok == '-')
        tok++;
    if (isdigit((unsigned char) *tok))
        return 1;
    if (*tok == '.' && isdigit((unsigned char) tok[1]))
        return 1;
    return 0;
}


/* Color for one token, or NULL to leave it the default terminal color. */
static const char *token_color(const char *tok, int first, int quoted)
{
    if (quoted)
        return SYN_STRING;
    if (first) {
        if (is_command(tok) || is_keyword(tok))
            return SYN_CMD_OK;                  /* complete, recognized command */
        if (is_command_prefix(tok))
            return NULL;                        /* still a valid prefix -- neutral */
        return SYN_CMD_BAD;                     /* cannot become a command -- red */
    }
    if (tok[0] == '-' && !(isdigit((unsigned char) tok[1]) || tok[1] == '.'))
        return SYN_OPT;
    if (looks_like_number(tok))
        return SYN_NUM;
    return NULL;
}


char *cp_highlight_line(const char *line)
{
    const char *p;
    char *out, *o;
    int first = 1;

    if (!line)
        line = "";
    /* Generous upper bound: each source char, even as its own token, adds well
     * under 16 bytes of escape sequences. */
    out = o = TMALLOC(char, 16 * strlen(line) + 32);

    for (p = line; *p; ) {
        const char *start;
        size_t len;
        const char *color;
        char quote = 0;

        if (isspace((unsigned char) *p)) {          /* copy whitespace as-is */
            *o++ = *p++;
            continue;
        }

        start = p;
        if (*p == '"' || *p == '\'') {              /* quoted-string token */
            quote = *p++;
            while (*p && *p != quote)
                p++;
            if (*p == quote)
                p++;
        }
        else {                                      /* plain whitespace-delimited token */
            while (*p && !isspace((unsigned char) *p))
                p++;
        }
        len = (size_t) (p - start);

        {
            char *tok = TMALLOC(char, len + 1);
            memcpy(tok, start, len);
            tok[len] = '\0';
            color = token_color(tok, first, quote != 0);
            tfree(tok);
        }

        if (color) {
            memcpy(o, color, strlen(color));
            o += strlen(color);
        }
        memcpy(o, start, len);
        o += len;
        if (color) {
            memcpy(o, SYN_RESET, strlen(SYN_RESET));
            o += strlen(SYN_RESET);
        }
        first = 0;
    }
    *o = '\0';
    return out;
}


/* `synhl [command line]' -- print the colorized form of its arguments, so the
 * highlighting can be previewed (and regression-tested) without a terminal. */
void com_synhl(wordlist *wl)
{
    char *s = wl_flatten(wl);
    char *c = cp_highlight_line(s ? s : "");
    fprintf(cp_out, "%s\n", c);
    tfree(c);
    tfree(s);
}


#ifdef HAVE_GNUREADLINE

/* Whether live coloring should run now: enabled, writing to a real terminal,
 * and not muzzled by the NO_COLOR convention. */
static int synhl_active(void)
{
    if (cp_getvar("no_syntax_highlight", CP_BOOL, NULL, 0))
        return 0;
    if (getenv("NO_COLOR"))
        return 0;
    if (!rl_outstream || !isatty(fileno(rl_outstream)))
        return 0;
    return 1;
}


/* readline redisplay replacement: redraw the current line colorized.  Only used
 * when the whole line fits on one terminal row; otherwise we defer to readline's
 * own redisplay so a wrapped line is never corrupted. */
static void cp_synhl_redisplay(void)
{
    int rows = 0, cols = 0;
    const char *pr;
    int plen, curcol;
    char *col;

    if (!synhl_active()) {
        rl_redisplay();
        return;
    }

    rl_get_screen_size(&rows, &cols);
    pr = rl_display_prompt ? rl_display_prompt : (rl_prompt ? rl_prompt : "");
    plen = (int) strlen(pr);
    if (cols <= 0 || plen + rl_end + 2 >= cols) {
        rl_redisplay();
        return;
    }

    col = cp_highlight_line(rl_line_buffer);
    /* return to column 0, redraw prompt + colorized line, clear to end of row */
    fprintf(rl_outstream, "\r%s%s\033[K", pr, col);
    /* place the cursor: column 0, then step right to prompt + rl_point */
    curcol = plen + rl_point;
    fputc('\r', rl_outstream);
    if (curcol > 0)
        fprintf(rl_outstream, "\033[%dC", curcol);
    fflush(rl_outstream);
    tfree(col);
}

#endif /* HAVE_GNUREADLINE */


#ifdef HAVE_GNUREADLINE

/* accept-line replacement.  Our custom redisplay leaves the cursor positioned
 * with raw escape sequences, which bypasses readline's internal cursor tracking,
 * so readline's own accept handling does not emit the closing newline before the
 * command runs (the command output would otherwise start on the input line).
 * Emit that newline here when coloring is active, then run the normal
 * accept-line. */
static int cp_synhl_accept(int count, int key)
{
    if (synhl_active()) {
        rl_crlf();
        fflush(rl_outstream);
        rl_on_new_line();
    }
    return rl_newline(count, key);
}

#endif /* HAVE_GNUREADLINE */


void cp_synhl_init(void)
{
#ifdef HAVE_GNUREADLINE
    rl_redisplay_function = cp_synhl_redisplay;
    rl_bind_key('\r', cp_synhl_accept);
    rl_bind_key('\n', cp_synhl_accept);
#endif
}
