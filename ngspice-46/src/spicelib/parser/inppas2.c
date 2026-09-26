/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/inpmacs.h"
#ifdef OSDI
#include "ngspice/osdiitf.h"   /* Enhancement-740: osdi_devtype_is_osdi */
#endif

#include "inppas2.h"
#include "inpxx.h"

#ifdef XSPICE
/* gtri - add - wbk - 11/9/90 - include function prototypes */
#include "ngspice/mifproto.h"
/* gtri - end - wbk - 11/9/90 */
#endif

// Ugly way to pass line info (number and source file) to lower-level error handlers.
int Current_parse_line;
char* Sourcefile;

/* uncomment to trace in this file */
/*#define TRACE*/

/* pass 2 - Scan through the lines.  ".model" cards have processed in
 *  pass1 and are ignored here.  */

#ifdef OSDI
/* Enhancement-740 (options-and-convergence hunt N1): a line whose device letter
 * is not `n` but which names a compiled (OSDI) model failed with the letter's
 * own message and nothing more -- `y1 a 0 dva` gave "model name is not found",
 * a Y line having taken `dva` for a node -- so the one fact that explains the
 * failure, that the model exists under another letter, was never said. The
 * tokens after the first are looked up BEFORE the letter's parser runs (some
 * parsers consume the card's line as they read it); if the line then fails,
 * the token that names a compiled model is said, with the prefix that reaches
 * it. Returns the token, malloc'd, or NULL. */
/* The other half: the card's model may already be GONE. inp_rem_unused_models
 * comments out a `.model` card that no line refers to in its model position,
 * and a wrongly prefixed line (`y1 a 0 dva`, `t1 a 0 b 0 dva`) refers to it as
 * a node or a parameter, so by pass 2 the card reads `*model dva vadiode(...)`
 * and no lookup finds it. When the failing line's token is the name of such a
 * card, say so, and whether its type is a compiled module. Returns a malloc'd
 * hint or NULL. */
static char *
INPculledModelHint(struct card *data, const char *cardline, char letter)
{
    char *line = (char *) cardline, *tok, *hint = NULL;
    int first = 1;

    while (*line && !hint) {
        if (INPgetTok(&line, &tok, 1) || !tok)
            break;
        if (*tok && !first) {
            struct card *k;
            size_t n = strlen(tok);
            for (k = data; k; k = k->nextcard) {
                const char *l = k->line;
                if (strncmp(l, "*model ", 7) != 0)
                    continue;
                l += 7;
                while (*l == ' ' || *l == '\t')
                    l++;
                if (strncmp(l, tok, n) == 0 && (l[n] == ' ' || l[n] == '\t')) {
                    char *rest = (char *) l + n, *type;
                    int ty;
                    if (INPgetTok(&rest, &type, 1) || !type)
                        break;
                    ty = INPtypelook(type);
                    if (ty >= 0 && osdi_devtype_is_osdi(ty))
                        hint = tprintf("  '%s' names a .model card (type %s) that was "
                                       "dropped as unused: no line refers to it in the "
                                       "model position; %s is a compiled (OSDI) module, "
                                       "and its instances are written with the prefix "
                                       "'n', not '%c'\n", tok, type, type, letter);
                    else
                        hint = tprintf("  '%s' names a .model card (type %s) that was "
                                       "dropped as unused: no line refers to it in the "
                                       "model position\n", tok, type);
                    tfree(type);
                    break;
                }
            }
        }
        first = 0;
        tfree(tok);
    }
    return hint;
}

static char *
INPosdiModelToken(const char *cardline)
{
    char *line = (char *) cardline, *tok;
    int first = 1;

    while (*line) {
        if (INPgetTok(&line, &tok, 1) || !tok)
            break;
        if (*tok && !first) {
            INPmodel *m = INPlookMod(tok);
            if (m && m->INPmodType >= 0 && osdi_devtype_is_osdi(m->INPmodType))
                return tok;
        }
        first = 0;
        tfree(tok);
    }
    return NULL;
}
#endif

void INPpas2(CKTcircuit *ckt, struct card *data, INPtables * tab, TSKtask *task)
{

    struct card *current;
    char c;
    char *groundname = "0";
    char *gname;
    CKTnode *gnode;
    int error;          /* used by the macros defined above */
#ifdef HAS_PROGREP
    int linecount = 0, actcount = 0;
#endif

#ifdef TRACE
    /* SDB debug statement */
    printf("Entered INPpas2 . . . .\n");
#endif

    error = INPgetTok(&groundname, &gname, 1);
    if (error) {
        data->error =
            INPerrCat(data->error,
                INPmkTemp
                ("can't read internal ground node name!\n"));
    }
    error = INPgndInsert(ckt, &gname, tab, &gnode);
    if (error && error != E_EXISTS) {
        data->error =
            INPerrCat(data->error,
                INPmkTemp
                ("can't insert internal ground node in symbol table!\n"));
    }

#ifdef TRACE
    printf("Examining this deck:\n");
    for (current = data; current != NULL; current = current->nextcard) {
        printf("%s\n", current->line);
    }
    printf("\n");
#endif

#ifdef HAS_PROGREP
    for (current = data; current != NULL; current = current->nextcard)
        linecount++;
#endif

    for (current = data; current != NULL; current = current->nextcard) {

#ifdef TRACE
        /* SDB debug statement */
        printf("In INPpas2, examining card %s . . .\n", current->line);
#endif

#ifdef HAS_PROGREP
        if (linecount > 0) {
            SetAnalyse( "Parse", (int) (1000.*actcount/linecount));
            actcount++;
        }
#endif

        Current_parse_line = current->linenum_orig;
        Sourcefile = current->linesource;

        c = *(current->line);
        if(islower_c(c))
            c = toupper_c(c);
#ifdef OSDI
        {
            char *osdi_tok = (c != 'N' && isalpha_c(c)) ?
                INPosdiModelToken(current->line) : NULL;      /* Enhancement-740 */
            char *err_before = current->error;
#endif

        switch (c) {

        case ' ':
            /* blank line (space leading) */
        case '\t':
            /* blank line (tab leading) */
            break;

#ifdef XSPICE
        /* gtri - add - wbk - 10/23/90 - add case for 'A' devices */

        case 'A':   /* Aname <cm connections> <mname> */
            MIF_INP2A(ckt, tab, current);
            ckt->CKTadevFlag = 1; /* an 'A' device is requested */
            break;

      /* gtri - end - wbk - 10/23/90 */
#endif

        case 'R':
            /* Rname <node> <node> [<val>][<mname>][w=<val>][l=<val>] */
            INP2R(ckt, tab, current);
            break;

        case 'C':
            /* Cname <node> <node> <val> [IC=<val>] */
            INP2C(ckt, tab, current);
            break;

        case 'L':
            /* Lname <node> <node> <val> [IC=<val>] */
            INP2L(ckt, tab, current);
            break;

        case 'G':
            /* Gname <node> <node> <node> <node> <val> */
            INP2G(ckt, tab, current);
            break;

        case 'E':
            /* Ename <node> <node> <node> <node> <val> */
            INP2E(ckt, tab, current);
            break;

        case 'F':
            /* Fname <node> <node> <vname> <val> */
            INP2F(ckt, tab, current);
            break;

        case 'H':
            /* Hname <node> <node> <vname> <val> */
            INP2H(ckt, tab, current);
            break;

        case 'D':
            /* Dname <node> <node> <model> [<val>] [OFF] [IC=<val>] */
            INP2D(ckt, tab, current);
            break;

        case 'J':
            /* Jname <node> <node> <node> <model> [<val>] [OFF]
                   [IC=<val>,<val>] */
            INP2J(ckt, tab, current);
            break;

        case 'Z':
            /* Zname <node> <node> <node> <model> [<val>] [OFF]
               [IC=<val>,<val>] */
            INP2Z(ckt, tab, current);
            break;

        case 'M':
            /* Mname <node> <node> <node> <node> <model> [L=<val>]
               [W=<val>] [AD=<val>] [AS=<val>] [PD=<val>]
               [PS=<val>] [NRD=<val>] [NRS=<val>] [OFF]
               [IC=<val>,<val>,<val>] */
            INP2M(ckt, tab, current);
            break;
#ifdef  OSDI
        case 'N':
            /* Nname [<node>...]  [<mname>] */
            INP2N(ckt, tab, current);
            break;
#endif
        case 'O':
            /* Oname <node> <node> <node> <node> <model>
               [IC=<val>,<val>,<val>,<val>] */
            INP2O(ckt, tab, current);
            break;

        case 'V':
            /* Vname <node> <node> [ [DC] <val>] [AC [<val> [<val> ] ] ]
               [<tran function>] */
            INP2V(ckt, tab, current);
            break;

        case 'I':
            /* Iname <node> <node> [ [DC] <val>] [AC [<val> [<val> ] ] ]
               [<tran function>] */
            INP2I(ckt, tab, current);
            break;

        case 'Q':
            /* Qname <node> <node> <node> [<node>] <model> [<val>] [OFF]
               [IC=<val>,<val>] */
            INP2Q(ckt, tab, current, gnode);
            break;

        case 'T':
            /* Tname <node> <node> <node> <node> [TD=<val>]
               [F=<val> [NL=<val>]][IC=<val>,<val>,<val>,<val>] */
            INP2T(ckt, tab, current);
            break;

        case 'S':
            /* Sname <node> <node> <node> <node> [<modname>] [IC] */
            INP2S(ckt, tab, current);
            break;

        case 'W':
            /* Wname <node> <node> <vctrl> [<modname>] [IC] */
            /* CURRENT CONTROLLED SWITCH */
            INP2W(ckt, tab, current);
            break;

        case 'U':
            /* Uname <node> <node> <model> [l=<val>] [n=<val>] */
            INP2U(ckt, tab, current);
            break;

        /* Kspice addition - saj */
        case 'P':
            /* Pname <node> <node> ... <gnd> <node> <node> ... <gnd> [<modname>] */
            /* R=<vector> L=<matrix> G=<vector> C=<matrix> len=<val> */
            INP2P(ckt, tab, current);
            break;
        case 'Y':
            /* Yname <node> <node> R=<val> L=<val> G=<val> C=<val> len=<val> */
            INP2Y(ckt, tab, current);
            break;
        /* end Kspice */

        case 'K':
            /* Kname Lname Lname <val> */
            INP2K(ckt, tab, current);
            break;

        case '*': case '$':
            /* *<anything> - a comment - ignore */
            break;

        case 'B':
            /* Bname <node> <node> [V=expr] [I=expr] */
            /* Arbitrary source. */
            INP2B(ckt, tab, current);
            break;

        case '.':   /* .<something> Many possibilities */
            if (INP2dot(ckt,tab,current,task,gnode))
            return;
            break;

        case '\0':
            break;

        default:
            /* the un-implemented device */
            LITERR(" unknown device type - error \n");
            break;
        }
#ifdef OSDI
            if (current->error && current->error != err_before) {
                if (osdi_tok)
                    current->error = INPerrCat(current->error,
                        tprintf("  '%s' names a compiled (OSDI) model of module "
                                "'%s'; its instances are written with the prefix "
                                "'n', not '%c'\n",
                                osdi_tok, INPlookMod(osdi_tok)->INPmodTypeName
                                    ? INPlookMod(osdi_tok)->INPmodTypeName : "?",
                                *current->line));
                else if (c != 'N' && isalpha_c(c)) {
                    char *hint = INPculledModelHint(data, current->line, *current->line);
                    if (hint)
                        current->error = INPerrCat(current->error, hint);
                }
            }
            if (osdi_tok)
                tfree(osdi_tok);
        }
#endif
    }

    return;
}
