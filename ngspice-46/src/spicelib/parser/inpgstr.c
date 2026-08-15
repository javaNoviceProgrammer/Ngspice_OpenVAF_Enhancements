/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

/*
 * Get string input token from 'line', and return a pointer to it in 'token'
 */

#include "ngspice/ngspice.h"
#include <stdio.h>
#include "ngspice/iferrmsg.h"
#include "ngspice/inpdefs.h"
#include "inpxx.h"

int INPgetStr(char **line, char **token, int gobble)
				/* eat non-whitespace trash AFTER token? */
{
    char *point;
    char separator = '\0';

    /* Scan along throwing away garbage characters. */
    for (point = *line; *point != '\0'; point++) {
	if ((*point == ' ') ||
	    (*point == '\t') ||
	    (*point == '=') ||
	    (*point == '(') || (*point == ')') || (*point == ','))
	    continue;
	break;
    }
    if (*point == '"') {
	separator = '"';
	point++;
    } else if (*point == '\'') {
	separator = '\'';
	point++;
    }
    /* mark beginning of token */
    *line = point;
    /* now find all good characters */
    for (point = *line; *point != '\0'; point++) {
	/* Enhancement-461: inside quotes ONLY the closing quote ends the token.
	 * The separator was honoured for its own character but the whitespace and
	 * punctuation tests below still fired inside it, so a quoted string
	 * parameter was truncated at its first space: `ty="with space"` reached
	 * the model as `with`. A quoted value is one token by definition -- that
	 * is what the quotes are for. */
	if (separator) {
	    if (*point == separator)
		break;
	    continue;
	}
	if ((*point == ' ') ||
	    (*point == '\t') ||
	    (*point == '=') ||
	    (*point == '(') ||
	    (*point == ')') || (*point == ',') || (*point == separator))
	    break;
    }

    /* Create token */
    *token = TMALLOC(char, 1 + point - *line);
    if (!*token)
	return (E_NOMEM);
    (void) strncpy(*token, *line, (size_t) (point - *line));
    *(*token + (point - *line)) = '\0';
    *line = point;

    /* Gobble garbage to next token. */
    if (separator && **line == separator) {
	(*line)++;		/* Skip one closing separator */
    }
    for (; **line != '\0'; (*line)++) {
	if (**line == ' ')
	    continue;
	if (**line == '\t')
	    continue;
	if ((**line == '=') && gobble)
	    continue;
	if ((**line == ',') && gobble)
	    continue;
	break;
    }
    return (OK);
}
