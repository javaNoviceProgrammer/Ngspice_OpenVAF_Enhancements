/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
**********/

#include "ngspice/ngspice.h"
#include <stdio.h>
#include "ngspice/inpdefs.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/hash.h"
#include "inpxx.h"

/*  global input model table.  */
INPmodel *modtab = NULL;
/* Global input model hash table.
   The modelname is the key, the return value is the pointer to the model. */
NGHASHPTR modtabhash = NULL;

/*--------------------------------------------------------------
 * This fcn takes the model name and looks to see if it is already
 * in the model table.  If it is, then just return.  Otherwise,
 * stick the model into the model table.
 * Note that the model table INPmodel *modtab is a linked list,
 * in parallel a hash table modtabhash is filled in for faster
 * access to modtab elements by giving the model name.
 *--------------------------------------------------------------*/

int INPmakeMod(char *token, int type, struct card *line)
{
   register INPmodel *newm;
   /* Initialze the hash table. The default key type is string.
      The default comparison function is strcmp.*/
   if (!modtabhash) {
       modtabhash = nghash_init(NGHASH_MIN_SIZE);
       nghash_unique(modtabhash, TRUE);
   }
   /* If the model is already there, just return -- but say so.
    *
    * Enhancement-426: two `.model` cards with the same name were silently
    * reduced to one and the FIRST card won: `.model dm d(is=1e-14)` followed by
    * `.model dm d(is=1e-9)` gave the 1e-14 answer with no diagnostic, and
    * reversing the two cards changed the result. The "model type mismatch"
    * warning elsewhere is NOT a duplicate detector -- it checks the INSTANCE
    * line's device letter. WARNING, not error: three of ngspice's own shipped
    * example decks carry byte-identical duplicate `.model` cards (harmless
    * copy-paste), while two others carry duplicates with DIFFERENT values where
    * the second is plainly the intended one and is silently discarded. House
    * precedent is the osdi loader's "device is already registered; keeping the
    * existing device". */
   else if (nghash_find(modtabhash, token)) {
       INPmodel *dup = (INPmodel *) nghash_find(modtabhash, token);
       fprintf(stderr,
               "Warning: model \"%s\" is already defined%s; keeping the first "
               "definition and ignoring the later one.\n",
               token,
               (dup && dup->INPmodType != type)
                   ? " with a DIFFERENT device type" : "");
       return (OK);
   }

   /* Model name was not already in model table. Therefore stick
      it in the front of the model table, also into the model hash table.
      Then return.  */

#ifdef TRACE
   /* debug statement */
   printf("In INPmakeMod, about to insert new model name = %s . . .\n", token);
#endif

   newm = TMALLOC(INPmodel, 1);
   if (newm == NULL)
      return (E_NOMEM);

   newm->INPmodName = token;                 /* model name */
   newm->INPmodType = type;                  /* model type */
   newm->INPnextModel = modtab;              /* pointer to second model */
   newm->INPmodLine = line;                  /* model line */
   newm->INPmodfast = NULL;
   newm->INPmodTypeName = NULL;   /* set by INPdomodel once the type is known */

   nghash_insert(modtabhash, token, newm);

   modtab = newm;

   return (OK);
}

