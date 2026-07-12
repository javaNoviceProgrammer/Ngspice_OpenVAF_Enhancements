/*************
 * Interactive command-line syntax highlighting.
 * Enhancement-169.
 ************/

#ifndef ngspice_SYNTAXHL_H
#define ngspice_SYNTAXHL_H

#include "ngspice/wordlist.h"

/* Return a freshly allocated (TMALLOC) copy of `line` with ANSI color escape
 * sequences wrapping each token: the command word green when it is a recognized
 * command or control keyword, red when it is not, plus distinct colors for
 * numbers, quoted strings and -option flags.  Caller frees with tfree(). */
char *cp_highlight_line(const char *line);

/* Install the readline redisplay hook so the interactive line is colored as it
 * is typed.  No-op unless built with GNU readline. */
void cp_synhl_init(void);

/* The `synhl' command: print the colorized form of its arguments. */
void com_synhl(wordlist *wl);

#endif
