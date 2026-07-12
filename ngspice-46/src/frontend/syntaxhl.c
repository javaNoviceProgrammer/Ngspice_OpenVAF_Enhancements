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

/* fopencookie (used to colorize error output on Linux) needs _GNU_SOURCE. */
#if defined(__linux__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE
#endif

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cpextern.h"
#include "ngspice/wordlist.h"
#include "ngspice/dvec.h"
#include "ngspice/plot.h"
#include "ngspice/pnode.h"
#include "ngspice/fteext.h"
#include "ngspice/syntaxhl.h"

#include <ctype.h>
#include <fcntl.h>
#ifdef HAVE_UNISTD_H
#include <unistd.h>
#endif

/* The plot holding the built-in constants (pi, e, ...); a non-static global in
 * vectors.c with no public declaration. */
extern struct plot constantplot;

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


/* Color of the command word (first token), or NULL for neutral. */
static const char *command_color(const char *tok)
{
    if (is_command(tok) || is_keyword(tok))
        return SYN_CMD_OK;                      /* complete, recognized command */
    if (is_command_prefix(tok))
        return NULL;                            /* still a valid prefix -- neutral */
    return SYN_CMD_BAD;                         /* cannot become a command -- red */
}


/* Does the signal/vector `word' (e.g. "v(a)", "i(vsrc)", "@r1[r]") exist?
 * Read-only lookup in the current plot and the constants plot -- no evaluation,
 * no vector creation, so it is safe to call on every keystroke. */
static int signal_exists(const char *word)
{
    struct dvec *d = NULL;
    char *w = copy(word);
    if (plot_cur)
        d = vec_fromplot(w, plot_cur);
    if (!d)
        d = vec_fromplot(w, &constantplot);
    tfree(w);
    return d != NULL;
}


/* Commands whose whole argument is a mathematical expression (or list of them),
 * so a parse failure means the expression itself is malformed.  (let/define are
 * excluded: their "name = ..." form is not a bare expression.) */
static const char * const expr_cmds[] = {
    "plot", "print", "gnuplot", "asciiplot", NULL
};

static int is_expr_command(const char *cmd)
{
    int i;
    for (i = 0; expr_cmds[i]; i++)
        if (strcasecmp(expr_cmds[i], cmd) == 0)
            return 1;
    return 0;
}


/* A write-only /dev/null stream, opened once, used to mute the expression
 * parser's diagnostics while we test a line for validity. */
static FILE *null_stream(void)
{
    static FILE *fp = NULL;
    static int tried = 0;
    if (!tried) {
        tried = 1;
        fp = fopen("/dev/null", "w");
    }
    return fp;
}


/* A write-only fd on /dev/null, opened once, to mute raw-stderr writes. */
static int null_fd(void)
{
    static int fd = -2;
    if (fd == -2)
        fd = open("/dev/null", O_WRONLY);
    return fd;
}


/* Is `expr' still obviously being typed -- unbalanced parentheses, or a trailing
 * binary operator / comma?  Such input is not a real parse error, so it should
 * stay neutral rather than flash red before the user finishes. */
static int expr_incomplete(const char *expr)
{
    const char *p, *t;
    int depth = 0;

    for (p = expr; *p; p++) {
        if (*p == '(')
            depth++;
        else if (*p == ')')
            depth--;
    }
    if (depth != 0)
        return 1;

    t = expr + strlen(expr);
    while (t > expr && isspace((unsigned char) t[-1]))
        t--;
    if (t > expr && strchr("+-*/^%,", t[-1]))
        return 1;

    return 0;
}


/* Does `expr' parse as a valid ngspice expression?  Uses the real parser with
 * its output muted, and frees the resulting tree, so it has no visible effect.
 * An empty / whitespace-only string counts as valid (nothing to complain about
 * while the line is still being typed). */
static int expr_parses(const char *expr)
{
    struct pnode *pn;
    FILE *save, *nf;
    int nfd, saved_fd = -1;

    while (*expr && isspace((unsigned char) *expr))
        expr++;
    if (!*expr)
        return 1;

    save = cp_err;
    nf = null_stream();
    if (nf)
        cp_err = nf;
    /* PPerror (the expression parser's error handler) writes straight to stderr,
     * so mute fd 2 across the parse as well -- otherwise a half-typed expression
     * spews "syntax error in line segment ..." onto the prompt. */
    nfd = null_fd();
    if (nfd >= 0) {
        fflush(stderr);
        saved_fd = dup(STDERR_FILENO);
        dup2(nfd, STDERR_FILENO);
    }
    pn = ft_getpnames_from_string(expr, FALSE);
    if (saved_fd >= 0) {
        fflush(stderr);
        dup2(saved_fd, STDERR_FILENO);
        close(saved_fd);
    }
    cp_err = save;

    if (pn) {
        free_pnode(pn);
        return 1;
    }
    return 0;
}


/* Append `len' bytes of `text' to *o, optionally wrapped in `color' + reset. */
static void emit(char **o, const char *text, size_t len, const char *color)
{
    if (color) {
        memcpy(*o, color, strlen(color));
        *o += strlen(color);
    }
    memcpy(*o, text, len);
    *o += len;
    if (color) {
        memcpy(*o, SYN_RESET, strlen(SYN_RESET));
        *o += strlen(SYN_RESET);
    }
}


/* Lex and emit one v(...)/i(...) signal atom starting at *p (which points at the
 * leading v/i and *(p+1) == '('); advances *p past it.  Red if the signal does
 * not exist, default color if it does. */
static void emit_vi_signal(char **o, const char **p)
{
    const char *s = *p;
    int depth;
    char *tok;

    *p += 2;                                    /* skip "v(" / "i(" */
    depth = 1;
    while (**p && depth) {
        if (**p == '(')
            depth++;
        else if (**p == ')')
            depth--;
        (*p)++;
    }
    {
        size_t len = (size_t) (*p - s);
        const char *color = NULL;
        /* depth == 0 means the parenthesis closed -- a complete v(...)/i(...); a
         * non-zero depth means it is still being typed, so leave it neutral. */
        if (depth == 0) {
            tok = TMALLOC(char, len + 1);
            memcpy(tok, s, len);
            tok[len] = '\0';
            color = signal_exists(tok) ? NULL : SYN_CMD_BAD;
            tfree(tok);
        }
        emit(o, s, len, color);
    }
}


char *cp_highlight_line(const char *line)
{
    const char *p;
    char *out, *o;
    int first = 1;

    if (!line)
        line = "";
    /* Generous upper bound: each source char, even as its own atom, adds well
     * under 24 bytes of escape sequences. */
    out = o = TMALLOC(char, 24 * strlen(line) + 32);

    p = line;
    while (*p) {
        if (isspace((unsigned char) *p)) {          /* copy whitespace as-is */
            *o++ = *p++;
            continue;
        }

        /* First non-space token is the command word. */
        if (first) {
            const char *s = p;
            char quote = (*p == '"' || *p == '\'') ? *p : 0;
            char cmd[64];
            size_t len;
            if (quote) {
                p++;
                while (*p && *p != quote)
                    p++;
                if (*p == quote)
                    p++;
            }
            else {
                while (*p && !isspace((unsigned char) *p))
                    p++;
            }
            len = (size_t) (p - s);
            {
                char *tok = TMALLOC(char, len + 1);
                memcpy(tok, s, len);
                tok[len] = '\0';
                emit(&o, s, len, quote ? SYN_STRING : command_color(tok));
                tfree(tok);
            }
            first = 0;

            /* Expression commands: if the whole argument region fails to parse,
             * the expression itself is malformed -- color it all red (req 3). */
            cmd[0] = '\0';
            if (!quote && len < sizeof cmd) {
                memcpy(cmd, s, len);
                cmd[len] = '\0';
            }
            if (cmd[0] && is_expr_command(cmd)) {
                const char *a = p;
                while (*a && isspace((unsigned char) *a))
                    a++;
                /* Only flag a genuine, settled parse error -- not an expression
                 * that is merely mid-typing (unbalanced parens / trailing op). */
                if (*a && !expr_incomplete(a) && !expr_parses(a)) {
                    emit(&o, p, (size_t) (a - p), NULL);    /* leading spaces */
                    emit(&o, a, strlen(a), SYN_CMD_BAD);    /* malformed region */
                    p += strlen(p);                         /* consumed to end */
                }
            }
            continue;
        }

        /* --- argument region: atom lexing --- */

        /* v(...)/i(...) node/branch signal: red if it does not exist. */
        if ((tolower((unsigned char) *p) == 'v' || tolower((unsigned char) *p) == 'i')
                && p[1] == '(') {
            emit_vi_signal(&o, &p);
            continue;
        }

        /* @device[param] signal. */
        if (*p == '@') {
            const char *s = p;
            char *tok;
            p++;
            while (*p && *p != ']' && !isspace((unsigned char) *p))
                p++;
            if (*p == ']')
                p++;
            {
                size_t len = (size_t) (p - s);
                tok = TMALLOC(char, len + 1);
                memcpy(tok, s, len);
                tok[len] = '\0';
                emit(&o, s, len, signal_exists(tok) ? NULL : SYN_CMD_BAD);
                tfree(tok);
            }
            continue;
        }

        /* quoted string. */
        if (*p == '"' || *p == '\'') {
            char quote = *p;
            const char *s = p++;
            while (*p && *p != quote)
                p++;
            if (*p == quote)
                p++;
            emit(&o, s, (size_t) (p - s), SYN_STRING);
            continue;
        }

        /* number (with optional exponent and SI suffix). */
        if (isdigit((unsigned char) *p) ||
                (*p == '.' && isdigit((unsigned char) p[1])) ||
                ((*p == '+' || *p == '-') && isdigit((unsigned char) p[1]))) {
            const char *s = p;
            if (*p == '+' || *p == '-')
                p++;
            while (isdigit((unsigned char) *p))
                p++;
            if (*p == '.') {
                p++;
                while (isdigit((unsigned char) *p))
                    p++;
            }
            if (*p == 'e' || *p == 'E') {
                const char *e = p++;
                if (*p == '+' || *p == '-')
                    p++;
                if (isdigit((unsigned char) *p))
                    while (isdigit((unsigned char) *p))
                        p++;
                else
                    p = e;                      /* not an exponent after all */
            }
            while (isalpha((unsigned char) *p))     /* SI suffix: k, meg, u, ... */
                p++;
            emit(&o, s, (size_t) (p - s), SYN_NUM);
            continue;
        }

        /* -option flag. */
        if (*p == '-' && isalpha((unsigned char) p[1])) {
            const char *s = p;
            p++;
            while (*p && !isspace((unsigned char) *p) && *p != '(' && *p != ')')
                p++;
            emit(&o, s, (size_t) (p - s), SYN_OPT);
            continue;
        }

        /* bare identifier (vector name, function, or keyword).  Left the default
         * color: distinguishing a valid vector from a function/keyword/option
         * without false positives needs the parser (a later phase); the
         * unambiguous v()/i()/@ signal forms above are what get validity-checked. */
        if (isalpha((unsigned char) *p) || *p == '_') {
            const char *s = p;
            while (*p && (isalnum((unsigned char) *p) || *p == '_' || *p == '.'))
                p++;
            emit(&o, s, (size_t) (p - s), NULL);
            continue;
        }

        /* any other single character (operators, parens, commas). */
        *o++ = *p++;
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


/* ----------------------------------------------------------------------------
 * Error-output coloring (req 4): wrap cp_err in a stream that draws everything
 * ngspice writes to the error channel in red.  Independent of readline, so it
 * works in any build.  Gated at write time on an interactive terminal + the
 * `no_syntax_highlight' variable + the NO_COLOR convention, so batch / piped
 * error output is never colored.
 * ------------------------------------------------------------------------- */

static int synhl_err_active(int fd)
{
    if (cp_getvar("no_syntax_highlight", CP_BOOL, NULL, 0))
        return 0;
    if (getenv("NO_COLOR"))
        return 0;
    if (!isatty(fd))
        return 0;
    return 1;
}

#if defined(__APPLE__) || defined(__FreeBSD__) || defined(__NetBSD__) || defined(__OpenBSD__)
#define SYNHL_WRAP_ERRORS 1
static int synhl_red_writefn(void *cookie, const char *buf, int n)
{
    FILE *real = (FILE *) cookie;
    if (n <= 0)
        return n;
    if (synhl_err_active(fileno(real))) {
        fwrite("\033[31m", 1, 5, real);
        fwrite(buf, 1, (size_t) n, real);
        fwrite("\033[0m", 1, 4, real);
    }
    else {
        fwrite(buf, 1, (size_t) n, real);
    }
    fflush(real);
    return n;
}
#elif defined(__linux__)
#define SYNHL_WRAP_ERRORS 1
static ssize_t synhl_red_writefn(void *cookie, const char *buf, size_t n)
{
    FILE *real = (FILE *) cookie;
    if (synhl_err_active(fileno(real))) {
        fwrite("\033[31m", 1, 5, real);
        fwrite(buf, 1, n, real);
        fwrite("\033[0m", 1, 4, real);
    }
    else {
        fwrite(buf, 1, n, real);
    }
    fflush(real);
    return (ssize_t) n;
}
#endif

void cp_synhl_wrap_errors(void)
{
#ifdef SYNHL_WRAP_ERRORS
    static int done = 0;
    FILE *w = NULL;
    if (done || !cp_err)
        return;
    done = 1;
#if defined(__linux__)
    {
        cookie_io_functions_t io = { NULL, synhl_red_writefn, NULL, NULL };
        w = fopencookie(cp_err, "w", io);
    }
#else
    w = funopen(cp_err, NULL, synhl_red_writefn, NULL, NULL);
#endif
    if (w) {
        setvbuf(w, NULL, _IONBF, 0);
        cp_err = w;
        /* cp_ioreset() restores cp_err from cp_curerr after each command (and
         * closes cp_err if the two differ), so point it at the wrapper too. */
        cp_curerr = w;
    }
#endif /* SYNHL_WRAP_ERRORS */
}


void cp_synhl_init(void)
{
#ifdef HAVE_GNUREADLINE
    rl_redisplay_function = cp_synhl_redisplay;
    rl_bind_key('\r', cp_synhl_accept);
    rl_bind_key('\n', cp_synhl_accept);
#endif
    /* Called at interactive start-up, after cp_init() has set cp_curerr, so the
     * error-stream wrapper below takes and keeps effect. */
    cp_synhl_wrap_errors();
}
