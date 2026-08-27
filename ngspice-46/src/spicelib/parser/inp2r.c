/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1988 Thomas L. Quarles
Modified: Paolo Nenzi 2000
Remarks:  This code is based on a version written by Serban Popescu which
          accepted an optional parameter ac. I have adapted his code
          to conform to INP standard. (PN)
**********/

#include "ngspice/ngspice.h"
#include "ngspice/ifsim.h"
#include "ngspice/inpdefs.h"
#include "ngspice/inpmacs.h"
#include "ngspice/fteext.h"
#include "inpxx.h"
#include "ngspice/stringskip.h"
#include "ngspice/compatmode.h"

/* undefine to add tracing to this file */
/* #define TRACE */

void INP2R(CKTcircuit *ckt, INPtables * tab, struct card *current)
{
/* parse a resistor card */
/* Rname <node> <node> [<val>][<mname>][w=<val>][l=<val>][ac=<val>] */

    static int mytype = -1;	/* the type we determine resistors are */
    int type = 0;		/* the type the model says it is */
    char *line;			/* the part of the current line left to parse */
    char *saveline;		/* ... just in case we need to go back... */
    char *name;			/* the resistor's name */
    char *model;		/* the name of the resistor's model */
    char *nname1;		/* the first node's name */
    char *nname2;		/* the second node's name */
    CKTnode *node1;		/* the first node's node pointer */
    CKTnode *node2;		/* the second node's node pointer */
    double val;			/* temp to held resistance */
    int error;			/* error code temporary */
    int error1;			/* secondary error code temporary */
    INPmodel *thismodel;	/* pointer to model structure describing our model */
    GENmodel *mdfast = NULL;	/* pointer to the actual model */
    GENinstance *fast = NULL;		/* pointer to the actual instance */
    IFvalue ptemp;		/* a value structure to package resistance into */
    int waslead;		/* flag to indicate that funny unlabeled number was found */
    double leadval;		/* actual value of unlabeled number */
    IFuid uid;			/* uid for default model */

    char *s;   /* Temporary buffer and pointer for translation */

#ifdef TRACE
    printf("In INP2R, Current line: %s\n", current->line);
#endif

    if (mytype < 0) {
        if ((mytype = INPtypelook("Resistor")) < 0) {
            LITERR("Device type Resistor not supported by this binary\n");
            return;
        }
    }
    line = current->line;
    INPgetNetTok(&line, &name, 1);			/* Rname */
    if (*line == '\0') {
        fprintf(stderr, "\nWarning: '%s' is not a valid resistor instance line, ignored!\n\n", current->line);
        return;
    }
    INPgetNetTok(&line, &nname1, 1);		/* <node> */
    if (*line == '\0') {
        fprintf(stderr, "\nWarning: '%s' is not a valid resistor instance line, ignored!\n\n", current->line);
        return;
    }
    INPgetNetTok(&line, &nname2, 1);		/* <node> */
    if (*line == '\0') {
        fprintf(stderr, "\nWarning: '%s' is not a valid resistor instance line, ignored!\n\n", current->line);
        return;
    }

    INPinsert(&name, tab);
    INPtermInsert(ckt, &nname1, tab, &node1);
    INPtermInsert(ckt, &nname2, tab, &node2);

    /* enable reading values like 4k7 */
    if (newcompat.lt)
        val = INPevaluateRKM_R(&line, &error1, 1);	/* [<val>] */
    else
        val = INPevaluate(&line, &error1, 1);	/* [<val>] */

    /* either not a number -> model, or
     * follows a number, so must be a model name
     * -> MUST be a model name (or null)
     */

#ifdef TRACE
    printf("Begining tc=xxx yyyy search and translation in '%s'\n", line);
#endif /* TRACE */    
    /* This routine translates "tc=xxx yyy" to "tc=xxx tc2=yyy".
       This is a re-write of the routine originally proposed by Hitoshi Tanaka.
       In my version we simply look for the first occurence of 'tc' followed
       by '=' followed by two numbers. If we find it then we splice in "tc2=".
       sjb - 2005-05-09 */

    for(s = line; NULL != (s = strstr(s, "tc")); ) {

        char *p;
        size_t left_length;

        s = skip_ws(s + 2);

        /* reject if not '=' */
        if(*s != '=')
            continue;

        s = skip_ws(s + 1);

        /* if we now have +, - or a decimal digit then assume we have a number,
           otherwise reject */
        if((*s != '+') && (*s != '-') && !isdigit_c(*s))
            continue;

        /* look for next white space or null */
        s = skip_non_ws(s);

        left_length = (size_t) (s - current->line);

        /* skip any additional white space */
        s = skip_ws(s);

        /* if we now have +, - or a decimal digit then assume we have the
            second number, otherwise reject */
        if((*s != '+') && (*s != '-') && !isdigit_c(*s))
            continue;

        /* if we get this far we have met all are criterea,
           so now we splice in a "tc2=" at the location remembered above. */

        p = TMALLOC(char, left_length + 5 + strlen(s) + 1);

        /* failed to allocate memory so we recover rather crudely
             by rejecting the translation */
        if(!p)
            break;

        strncpy(p, current->line, left_length);
        strcpy(p + left_length, " tc2=");
        strcpy(p + left_length + 5, s);

        line = p + (line - current->line);
        s    = p + (s    - current->line);

        /* replace old line with new */
        tfree(current->line);
        current->line = p;
    }

#ifdef TRACE
    printf("(Translated) Resistor line: %s\n", current->line);
#endif

    saveline = line;		/* save then old pointer */

    INPgetNetTok(&line, &model, 1);

    /* Enhancement-493: `r` was excluded from being a model name outright.
     *
     * The exclusion is there for `R1 a b r=1k`, where `r` is the keyword that
     * writes the resistance and must not be read as a model. But it also locked
     * out a model actually CALLED `r`: `.model r r rsh=1k` with `R1 a 0 r l=1u
     * w=1u` bound no model and no value, so the device fell through to the
     * default and came out as 1 mOhm with "resistance too low or not given" --
     * a message about the symptom, when the cause is that the model named on the
     * line was never looked up. Every other name works, including every other
     * resistor keyword (`rsh`, `l`, `w`, `tc1`, `temp`, `m`, `scale`); only this
     * one letter was unreachable.
     *
     * The two spellings are distinguishable by what FOLLOWS the token: the
     * keyword form is `r=`, a model name is not. Ask that instead, so `r=1k`
     * keeps its meaning and a model called `r` becomes reachable. A deck with no
     * such model is unaffected -- INPlookMod fails and the existing else branch
     * restores the line and builds the default model, exactly as for any other
     * unrecognised token. */
    if (*model && (strcmp(model, "r") != 0 || *skip_ws(line) != '=')) {
      /* token isn't null */
      if (INPlookMod(model)) {
          /* If this is a valid model connect it */
#ifdef TRACE
          printf("In INP2R, Valid R Model: %s\n", model);
#endif
          INPinsert(&model, tab);
          current->error = INPgetMod(ckt, model, &thismodel, tab);
          if (thismodel != NULL) {
            if (INPtypelook("Resistor") != thismodel->INPmodType)
            {
                LITERR("incorrect model type for resistor");
                return;
            }
            mdfast = thismodel->INPmodfast;
            type = thismodel->INPmodType;
          }
      } else {
          tfree(model);
          /* It is not a model */
          line = saveline;	/* go back */
          type = mytype;
          if (!tab->defRmod) {	/* create default R model */
            IFnewUid(ckt, &uid, NULL, "R", UID_MODEL, NULL);
            IFC(newModel, (ckt, type, &(tab->defRmod), uid));
          }
          mdfast = tab->defRmod;
      }
      IFC(newInstance, (ckt, mdfast, &fast, name));
    } else {
      tfree(model);
      /* The token is null or we have r=val - a default model will be created */
      type = mytype;
      if (!tab->defRmod) {
          /* create default R model */
          IFnewUid(ckt, &uid, NULL, "R", UID_MODEL, NULL);
          IFC(newModel, (ckt, type, &(tab->defRmod), uid));
      }
      IFC(newInstance, (ckt, tab->defRmod, &fast, name));
      if (error1 == 1) {		/* was a r=val construction */
        val = INPevaluate(&line, &error1, 1);	/* [<val>] */
#ifdef TRACE
        printf ("In INP2R, R=val construction: val=%g\n", val);
#endif
      }
    }

    if (!fast || !fast->GENmodPtr) {
        fprintf(stderr, "\nWarning: Instance for resistor '%s' could not be set up properly, ignored!\n\n", current->line);
        return;
    }

    if (error1 == 0) {		/* got a resistance above */
      ptemp.rValue = val;
      GCA(INPpName, ("resistance", &ptemp, ckt, type, fast));
    }

    IFC(bindNode, (ckt, fast, 1, node1));
    IFC(bindNode, (ckt, fast, 2, node2));
    PARSECALL((&line, ckt, type, fast, &leadval, &waslead, tab));
    /* Enhancement-445: an unlabeled trailing number is how `R1 a b rmod 1k`
     * gives its value, and that is legitimate -- there, the value position held
     * a MODEL name, so error1 != 0 and nothing was read above.
     *
     * When a value WAS read above, a second unlabeled number is a contradiction
     * rather than an override, and silently overriding is what made a comma so
     * dangerous: `,` is a token separator, so `R1 a b 1,5k` parses as the value
     * `1` followed by a stray unlabeled `5k`, and the resistor came out 5 kOhm
     * -- not 1.5 k as a European decimal comma intends, and not 1 k either.
     * Every other separator (`1;5`, `1:5`, `1_000`) is ignored as trailing text
     * per ngspice's documented rule; only the comma reached this overwrite.
     *
     * Keep the value written in the value position and say the rest was not
     * understood, rather than choose silently between two readings. */
    if (waslead && error1 == 0) {
      fprintf(stderr,
              "\nWarning: resistor '%s': value given twice; \"%g\" is used and "
              "the trailing\n         number \"%g\" is ignored. Note ',' "
              "separates fields, so \"1,5k\" is\n         two values, not "
              "1.5k.\n\n", name, val, leadval);
    } else if (waslead) {
      ptemp.rValue = leadval;
      GCA(INPpName, ("resistance", &ptemp, ckt, type, fast));
    }

    return;
}
