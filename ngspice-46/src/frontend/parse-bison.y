%{
    /*
     * (compile (concat "bison -ydo parse-bison.c " (file-relative-name buffer-file-name)))
     */

  #include "ngspice/ngspice.h"
  #include "ngspice/fteparse.h"

  #include <stdio.h>
  #include <stdlib.h>

  # define YYLTYPE struct PPltype

  #include "parse.h"
  #include "parse-bison.h"
  #include "parse-bison-y.h"


  # define YYLLOC_DEFAULT(Current, Rhs, N)                               \
     do                                                                  \
       if (N) {                                                          \
           (Current).start = YYRHSLOC(Rhs, 1).start;                     \
           (Current).stop  = YYRHSLOC(Rhs, N).stop;                      \
       } else {                                                          \
           (Current).start = (Current).stop = YYRHSLOC(Rhs, 0).stop;     \
       }                                                                 \
     while (0)

  static void PPerror (YYLTYPE *locp, char **line, struct pnode **retval, char const *);

  static char *keepline;
%}

%name-prefix "PP"

%defines
%locations
%debug

%pure-parser

%parse-param {char **line}
%lex-param   {char **line}

%parse-param {struct pnode **retval}

%union {
  double num;
  const char  *str;
  struct pnode *pnode;
}

/*
 * This gramar has three expected shift/reduce conflicts
 *   exp1 '-' exp2  can
 *     o  yield an exp, interpreting '-' as a binary operator
 *     o  yield a list of two expressions
 *          exp1  and
 *          unary '-' exp2
 *     the first interpretation is favoured. (bison defaults to 'shift')
 *   exp1 '+' exp2  the same, since Enhancement-857's unary '+'
 *   TOK_STR '(' exp1 ')'  can
 *     o  yield an exp, per function application
 *     o  yield a list of two expressions
 *          TOK_STR  and
 *          '(' exp1 ')'  which will be reduced to exp1
 *     the first interpretation is favoured. (bison defaults to 'shift')
 *
 * to verify:
 *   execute bison --report=state
 *
 * the %expect 3
 *   manifests my expectation, and will issue a `warning' when not met
 */

%expect 3

%token <num>  TOK_NUM
%token <str>  TOK_STR
%token        TOK_LE TOK_GE TOK_NE

%type  <pnode>   exp exp_list one_exp

/* Operator Precedence */

%right  '?' ':'
%left   '|'
%left   '&'
%left   '=' TOK_NE TOK_LE '<' TOK_GE '>'
%left   '~'
%right  ','
%left   '-' '+'
%left   '*' '/' '%'
%left   NEG      /* negation--unary minus */
/* Enhancement-865: '^' associates left to right, as the manual says of equal-
 * precedence binary operators (2.11.5), as the .param and the B-source take
 * it, and as Verilog-A's LRM takes `**`: 2^3^2 is 64. It was %right, and
 * `let` alone gave 512. */
%left   '^'      /* exponentiation */
%left   '[' ']'

%initial-action      /* initialize yylval */
{
    $$.num = 0.0;
    yylloc.start = yylloc.stop = NULL;
    keepline = *line;
};

%%

/*
 */


expression:
             { *retval = NULL; }
  | exp_list { *retval = $1; }
;

exp_list:
    one_exp
  | one_exp exp_list                  { $1->pn_next = $2; $2->pn_use ++; $$ = $1; }
;

one_exp:
    exp  {
        $1->pn_name = copy_substring(@1.start, @1.stop);
        $$ = $1;
    }
;

exp:
    TOK_NUM                           { $$ = PP_mknnode($1); }
  | TOK_STR                           { $$ = PP_mksnode($1); txfree($1); }

  | exp ',' exp                       { $$ = PP_mkbnode(PT_OP_COMMA,  $1, $3); }
  | exp '+' exp                       { $$ = PP_mkbnode(PT_OP_PLUS,   $1, $3); }
  | exp '-' exp                       { $$ = PP_mkbnode(PT_OP_MINUS,  $1, $3); }
  | exp '*' exp                       { $$ = PP_mkbnode(PT_OP_TIMES,  $1, $3); }
  | exp '%' exp                       { $$ = PP_mkbnode(PT_OP_MOD,    $1, $3); }
  | exp '/' exp                       { $$ = PP_mkbnode(PT_OP_DIVIDE, $1, $3); }
  | exp '^' exp                       { $$ = PP_mkbnode(PT_OP_POWER,  $1, $3); }

  | '(' exp ')'                       { $$ = $2; }

  | '-' exp  %prec NEG                { $$ = PP_mkunode(PT_OP_UMINUS, $2); }
  /* Enhancement-857: a unary plus, as the B-source's grammar and numparam
   * take it; `let x = 2*+3` was a syntax error. */
  | '+' exp  %prec NEG                { $$ = $2; }
  | '~' exp                           { $$ = PP_mkunode(PT_OP_NOT, $2); }

  | TOK_STR '(' exp ')'               { $$ = PP_mkfnode($1, $3);
                                        txfree($1);
                                        if(!$$)
                                            YYABORT;
                                      }

  | exp '=' exp                       { $$ = PP_mkbnode(PT_OP_EQ, $1, $3); }
  | exp TOK_NE exp                    { $$ = PP_mkbnode(PT_OP_NE, $1, $3); }
  | exp '>' exp                       { $$ = PP_mkbnode(PT_OP_GT, $1, $3); }
  | exp '<' exp                       { $$ = PP_mkbnode(PT_OP_LT, $1, $3); }
  | exp TOK_GE exp                    { $$ = PP_mkbnode(PT_OP_GE, $1, $3); }
  | exp TOK_LE exp                    { $$ = PP_mkbnode(PT_OP_LE, $1, $3); }

  | exp '&' exp                       { $$ = PP_mkbnode(PT_OP_AND, $1, $3); }
  | exp '|' exp                       { $$ = PP_mkbnode(PT_OP_OR,  $1, $3); }

  | exp '[' exp ']'                   { $$ = PP_mkbnode(PT_OP_INDX,  $1, $3); }
  | exp '[' '['  exp ']' ']'          { $$ = PP_mkbnode(PT_OP_RANGE, $1, $4); }
  | exp '?' exp ':' exp               { $$ = PP_mkbnode(PT_OP_TERNARY,$1,
                                                     PP_mkbnode(PT_OP_COMMA,$3,$5)); }
;

%%


/* Called by yyparse on error.  */
static void
PPerror (YYLTYPE *locp, char **line, struct pnode **retval, char const *s)
{
  NG_IGNORE(locp);
  NG_IGNORE(line);
  NG_IGNORE(retval);
  char *tmpstr = strstr(keepline, *line);
  int len = (int)strlen(keepline);
  fprintf (stderr, "%s: %s in line segment\n   %s\nnear\n   %*s\n",
      __func__, s, keepline, len, tmpstr);
}
