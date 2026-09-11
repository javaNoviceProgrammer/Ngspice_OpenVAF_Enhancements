/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: AlansFixes
**********/

#include "ngspice/ngspice.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/ifsim.h"
#include "ngspice/inpmacs.h"
#include "ngspice/cktdefs.h"

#include "inppas3.h"

/* Enhancement-608: a `.ic` or `.nodeset` on a device's INTERNAL node --
 * `v(n1#mid)`, the node the device builds at setup, after this pass -- was
 * refused, "on non-existent node, ignored". When the part before the '#'
 * names an instance of the deck, the entry is kept by name (CKTpendNodPm)
 * and CKTsetup() places it once the device has built the node. A name that
 * is no instance's stays the refusal it was; a suffix the device does not
 * build is reported at setup. */
static int
inp_internal_node_name(CKTcircuit *ckt, const char *nodename)
{
    const char *sharp = strchr(nodename, '#');
    char *inst;
    int found;

    if (!sharp || sharp == nodename || !sharp[1])
        return 0;
    inst = copy_substring(nodename, sharp);
    found = CKTfndDev(ckt, inst) != NULL;
    tfree(inst);
    return found;
}

extern IFsimulator *ft_sim;


/* pass 3 - Read all nodeset and IC lines. All circuit nodes will have
 * been created by now, (except for internal device nodes), so any
 * nodeset or IC nodes which have to be created are flagged with a
 * warning.  */

void
INPpas3(CKTcircuit *ckt, struct card *data, INPtables *tab, TSKtask *task,
        IFparm *nodeParms, int numNodeParms)
{

    struct card *current;
    int error;			/* used by the macros defined above */
    char *line;			/* the part of the current line left
                                   to parse */
    char *token=NULL;		/* a token from the line */
    IFparm *prm;		/* pointer to parameter to search
                                   through array */
    IFvalue ptemp;		/* a value structure to package
                                   resistance into */
    int which;			/* which analysis we are performing */
    CKTnode *node1;		/* the first node's node pointer */
    char *deferred;         /* Enhancement-608: an internal node's name, placed at setup */
    int found;

    NG_IGNORE(task);

#ifdef TRACE
    /* SDB debug statement */
    printf("In INPpas3 . . . \n");
#endif

    for(current = data; current != NULL; current = current->nextcard) {
        line = current->line;
        FREE(token);
        INPgetTok(&line,&token,1);

        if (strcmp(token,".nodeset")==0) {
            which = -1;

            for(prm = nodeParms; prm < nodeParms + numNodeParms; prm++) {
                if(strcmp(prm->keyword,"nodeset")==0) {
                    which = prm->id;
                    break;
                }
            }

            if(which == -1) {
                LITERR("nodeset unknown to simulator. \n");
                goto quit;
            }

            for(;;) {
                char *name;     /* the node's name */

                /* loop until we run out of data */
                INPgetTok(&line,&name,1);
                if( *name == '\0') {
                    FREE(name);
                    break; /* end of line */
                }

                /* If we have 'all = value' , then set all voltage nodes to 'value',
                   except for ground node at node->number 0 */
                if ( cieq(name, "all")) {
                    ptemp.rValue = INPevaluate(&line,&error,1);
                    /* Enhancement-468: a card naming a node but giving NO
                     * VALUE was dropped in total silence -- `.ic v(out)` and
                     * `.nodeset v(out)` produced no Note, Warning or Error of
                     * any kind, while a bad NODE NAME in the same card has
                     * always been reported and a bare `.probe` says what it
                     * assumed. INPevaluate already returns the error; nothing
                     * had ever read it. */
                    if (error) {
                        fprintf(stderr,
                                "Warning: .nodeset/.ic (all): no value given after the node; "
                                "this entry is ignored.\n   Please check line "
                                "%s\n\n", current->line);
                        FREE(name);
                        break;
                    }
                    for (node1 = ckt->CKTnodes; node1 != NULL; node1 = node1->next) {
                        if ((node1->type == SP_VOLTAGE) && (node1->number > 0))
                            IFC(setNodeParm, (ckt, node1, which, &ptemp, NULL));
                    }
                    FREE(name);
                    break;
                }
                /* check to see if in the form V(xxx) and grab the xxx */
                if( (*name == 'V' || *name == 'v') && !name[1] ) {
                    /* looks like V - must be V(xx) - get xx now*/
                    char *nodename;
                    INPgetNetTok(&line,&nodename,1);
                    /* If node is not found, issue a warning, ignore the defective token */
                    deferred = NULL;
                    found = INPtermSearch(ckt, &nodename, tab, &node1) == E_EXISTS;
                    if (!found && inp_internal_node_name(ckt, nodename)) {
                        deferred = nodename;    /* Enhancement-608: placed at setup */
                        node1 = NULL;
                    } else if (!found) {
                        const char *nf, *nr, *sfx;
                        /* Enhancement-592: a bit of a node autoadapt split */
                        if (INPadaptSplitOf(nodename, &nf, &nr, &sfx))
                            fprintf(stderr,
                                "Warning: autoadapt split node '%.*s' into '%s' and '%s', so its bit '%s' no longer exists;\n"
                                "         the .nodeset on it is ignored -- refer to %s%s or %s%s instead.\n",
                                (int) (sfx - nodename), nodename, nf, nr, nodename, nf, sfx, nr, sfx);
                        else
                            fprintf(stderr,
                                "Warning : Nodeset on non-existent node - %s, ignored\n", nodename);
                        fprintf(stderr,
                            "   Please check line %s\n\n", current->line);
                        FREE(name);
                        /* Gobble the rest of the token */
                        line = nexttok(line);
                        continue;
                    }
                    ptemp.rValue = INPevaluate(&line,&error,1);
                    /* Enhancement-468: a card naming a node but giving NO
                     * VALUE was dropped in total silence -- `.ic v(out)` and
                     * `.nodeset v(out)` produced no Note, Warning or Error of
                     * any kind, while a bad NODE NAME in the same card has
                     * always been reported and a bare `.probe` says what it
                     * assumed. INPevaluate already returns the error; nothing
                     * had ever read it. */
                    if (error) {
                        fprintf(stderr,
                                "Warning: .nodeset: no value given after the node; "
                                "this entry is ignored.\n   Please check line "
                                "%s\n\n", current->line);
                        FREE(name);
                        continue;
                    }
                    if (deferred)
                        CKTpendNodPm(ckt, deferred, which, ptemp.rValue);
                    else
                        IFC(setNodeParm, (ckt, node1, which, &ptemp, NULL));
                    FREE(name);
                    continue;
                }
                LITERR(" Error: .nodeset syntax error.\n");
                FREE(name);
                break;
            }
        } else if ((strcmp(token,".ic") == 0)) {
            /* .ic */
            which = -1;
            for(prm = nodeParms; prm < nodeParms + numNodeParms; prm++) {
                if(strcmp(prm->keyword,"ic")==0) {
                    which = prm->id;
                    break;
                }
            }

            if(which==-1) {
                LITERR("ic unknown to simulator. \n");
                goto quit;
            }

            for(;;) {
                char *name;     /* the node's name */

                /* loop until we run out of data */
                INPgetTok(&line,&name,1);
                /* check to see if in the form V(xxx) and grab the xxx */
                if( *name == '\0') {
                    FREE(name);
                    break; /* end of line */
                }
                if( (*name == 'V' || *name == 'v') && !name[1] ) {
                    /* looks like V - must be V(xx) - get xx now*/
                    char *nodename;
                    INPgetNetTok(&line,&nodename,1);
                    /* If node is not found, issue a warning, ignore the defective token */
                    deferred = NULL;
                    found = INPtermSearch(ckt, &nodename, tab, &node1) == E_EXISTS;
                    if (!found && inp_internal_node_name(ckt, nodename)) {
                        deferred = nodename;    /* Enhancement-608: placed at setup */
                        node1 = NULL;
                    } else if (!found) {
                        const char *nf, *nr, *sfx;
                        /* Enhancement-592: a bit of a node autoadapt split */
                        if (INPadaptSplitOf(nodename, &nf, &nr, &sfx))
                            fprintf(stderr,
                                "Warning: autoadapt split node '%.*s' into '%s' and '%s', so its bit '%s' no longer exists;\n"
                                "         the .ic on it is ignored -- refer to %s%s or %s%s instead.\n",
                                (int) (sfx - nodename), nodename, nf, nr, nodename, nf, sfx, nr, sfx);
                        else
                            fprintf(stderr,
                                "Warning : IC on non-existent node - %s, ignored\n", nodename);
                        fprintf(stderr,
                            "   Please check line %s\n\n", current->line);
                        FREE(name);
                        /* Gobble the rest of the token */
                        line = nexttok(line);
                        if (!line)
                            break;
                        continue;
                    }
                    ptemp.rValue = INPevaluate(&line,&error,1);
                    /* Enhancement-468: a card naming a node but giving NO
                     * VALUE was dropped in total silence -- `.ic v(out)` and
                     * `.nodeset v(out)` produced no Note, Warning or Error of
                     * any kind, while a bad NODE NAME in the same card has
                     * always been reported and a bare `.probe` says what it
                     * assumed. INPevaluate already returns the error; nothing
                     * had ever read it. */
                    if (error) {
                        fprintf(stderr,
                                "Warning: .ic: no value given after the node; "
                                "this entry is ignored.\n   Please check line "
                                "%s\n\n", current->line);
                        FREE(name);
                        continue;
                    }
                    if (deferred)
                        CKTpendNodPm(ckt, deferred, which, ptemp.rValue);
                    else
                        IFC(setNodeParm, (ckt, node1, which, &ptemp, NULL));
                    FREE(name);
                    continue;
                }
                LITERR(" Error: .ic syntax error.\n");
                FREE(name);
                break;
            }
        }
    }
quit:
    /* Enhancement-492: every device card has now been read, so "did anything
       connect to this node?" is finally answerable. Report any node that was
       named only in a controlling position -- see INPnoteCtrlNode().

       REFUSE rather than warn. `E` and `G` already fail on their own, because
       the invented node makes the matrix singular; a switch does not, because it
       only READS its control voltage and stamps nothing for it -- so it would
       otherwise carry on and answer from a node that is not in the circuit. That
       is the detect-announce-then-use-it-anyway shape Enhancement-485 had to undo
       eight times in one round, and a typo'd control node has no reading under
       which the deck is what the user wrote. */
    INPreportBusBases(ckt);     /* Enhancement-572 */
    if (INPreportCtrlNodes() > 0 && data)
        data->error = INPerrCat(data->error,
                                INPmkTemp("a controlling node does not exist; "
                                          "see the message above"));
    FREE(token);
    return;
}

