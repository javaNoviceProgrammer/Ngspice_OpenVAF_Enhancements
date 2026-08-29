/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 2000 AlansFixes
**********/

#ifndef ngspice_INPDEFS_H
#define ngspice_INPDEFS_H

/* structure declarations used by either/both input package */

#include "ngspice/gendefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/inpptree.h"

typedef struct INPtables INPtables;
typedef struct INPmodel INPmodel;

struct INPtab {
    char *t_ent;
    struct INPtab *t_next;
};

struct INPnTab {
    char *t_ent;
    CKTnode *t_node;
    struct INPnTab *t_next;
};

struct INPtables {
    struct INPtab **INPsymtab;
    struct INPnTab **INPtermsymtab;
    int INPsize;
    int INPtermsize;
    GENmodel *defAmod;
    GENmodel *defBmod;
    GENmodel *defCmod;
    GENmodel *defDmod;
    GENmodel *defEmod;
    GENmodel *defFmod;
    GENmodel *defGmod;
    GENmodel *defHmod;
    GENmodel *defImod;
    GENmodel *defJmod;
    GENmodel *defKmod;
    GENmodel *defLmod;
    GENmodel *defMmod;
    GENmodel *defNmod;
    GENmodel *defOmod;
    GENmodel *defPmod;
    GENmodel *defQmod;
    GENmodel *defRmod;
    GENmodel *defSmod;
    GENmodel *defTmod;
    GENmodel *defUmod;
    GENmodel *defVmod;
    GENmodel *defWmod;
    GENmodel *defYmod;
    GENmodel *defZmod;
};

/* Linked list of scoping information for each netlist line entry */
struct nscope {
    struct nscope *next;
    struct card_assoc *subckts;
    struct modellist *models;
};

/* A linked list of netlist line entries, associated for a specific reason */
struct card_assoc {
    const char *name;
    struct card *line;
    struct card_assoc *next;
};

/* The linked list of netlist line entries */
struct card {
    int linenum;
    int linenum_orig;
    char* linesource;
    char *line;
    char *error;
    struct card *nextcard;
    struct card *actualLine;
    struct nscope *level;
    float w;
    float l;
    float nf;
    int compmod;
};

/* structure used to save models in after they are read during pass 1 */
struct INPmodel {
    IFuid INPmodName; /* uid of model */
    int INPmodType; /* type index of device type */
    INPmodel *INPnextModel; /* link to next model */
    struct card *INPmodLine; /* pointer to line describing model */
    GENmodel *INPmodfast; /* high speed pointer to model for access */
};

// Ugly way to pass line onfo (number and source file) to lower-level error handlers.
extern int Current_parse_line;
extern char* Sourcefile;

/* listing types - used for debug listings */
#define LOGICAL 1
#define PHYSICAL 2

int IFnewUid(CKTcircuit *, IFuid *, IFuid, char *, int, CKTnode **);
int IFdelUid(CKTcircuit *, IFuid, int);
int INPaName(char *, IFvalue *, CKTcircuit *, int *, char *, GENinstance **,
        IFsimulator *, int *, IFvalue *);
int INPapName(CKTcircuit *, int, JOB *, char *, IFvalue *);
void INPcaseFix(char *);
char *INPdevParse(char **, CKTcircuit *, int, GENinstance *, double *, int *,
        INPtables *);
char *INPdomodel(CKTcircuit *, struct card *, INPtables *);
void INPdoOpts(CKTcircuit *, JOB *, struct card *, INPtables *);
char *INPerrCat(char *, char *);
char *INPstrCat(char *, char, char *);
char *INPerror(int);
double INPevaluate(char **, int *, int);
double INPevaluate2(char **, int *, int);
double INPevaluateRKM_R(char **, int *, int);
double INPevaluateRKM_C(char **, int *, int);
double INPevaluateRKM_L(char **, int *, int);
char *INPfindLev(char *, int *);
char *INPgetMod(CKTcircuit *, char *, INPmodel **, INPtables *);
char *INPgetModBin(CKTcircuit *, char *, INPmodel **, INPtables *, char *);
int INPgetTok(char **, char **, int);
int INPgetNetTok(char **, char **, int);
void INPgetTree(char **, INPparseTree **, CKTcircuit *, INPtables *);
void INPfreeTree(IFparseTree *);
IFvalue *INPgetValue(CKTcircuit *, char **, int, INPtables *);
/* Enhancement-507: did the last INPgetValue() scalar conversion fail? */
int INPlastValueError(void);
int INPgndInsert(CKTcircuit *, char **, INPtables *, CKTnode **);
int INPinsertNofree(char **token, INPtables *tab);
int INPinsert(char **, INPtables *);
int INPretrieve(char **, INPtables *);
int INPremove(char *, INPtables *);
INPmodel *INPlookMod(const char *);
int INPmakeMod(char *, int, struct card *);
char *INPmkTemp(char *);
void INPpas1(CKTcircuit *, struct card *, INPtables *);
void INPpas2(CKTcircuit *, struct card *, INPtables *, TSKtask *);
/* PROTOTYPE: autoadapt -- runs between pas1 and pas2, see inp2n.c */
void INPadapt(CKTcircuit *, struct card *, INPtables *);

/* Enhancement-464: bus-port grouping, shared so the subcircuit expander and
   INP2N cannot disagree about what a port is or how a bit is spelled.
   Defined in spicelib/parser/inp2n.c. */
struct IFdevice;
int INPbusPorts(struct IFdevice *dev, int *start, int *cnt, int maxp);
int INPbusKicadStyle(void);       /* 0/1 -- `bool` is not in scope here */
void INPbusBitSuffix(const char *lb, int kicad, char *out, size_t n);
/* Enhancement-490: does this token already carry a bit index? */
int INPbusTokenIndexed(const char *name, size_t len, int kicad);
/* Enhancement-426: set while INPpas2() is handed a card that if_run()
 * synthesised from a .control command. Such a card is never deck parsing, so
 * an analysis card naming an unknown node is a typo even before CKTsetup(). */
extern int INPanalysisCardFromCommand;
/* Enhancement-429: a node an analysis card invented and nothing else uses. */
int CKTnodePhantom(CKTnode *node);
/* Enhancement-492: a node named only in a device's CONTROL position is a typo.
   Noted during pass 2, reported in pass 3 -- only then is "did anything
   connect to this?" answerable. */
void INPnoteCtrlNode(const char *inst, const char *nodename, CKTnode *node);
int  INPreportCtrlNodes(void);
void INPpas3(
        CKTcircuit *, struct card *, INPtables *, TSKtask *, IFparm *, int);
void INPpas4(CKTcircuit *, INPtables *);
int INPpName(char *, IFvalue *, CKTcircuit *, int, GENinstance *);
int INPtermInsert(CKTcircuit *, char **, INPtables *, CKTnode **);
int INPtermSearch(CKTcircuit*, char**, INPtables*, CKTnode**);
int INPmkTerm(CKTcircuit *, char **, INPtables *, CKTnode **);
int INPtypelook(char *);
int INP2dot(CKTcircuit *, INPtables *, struct card *, TSKtask *, CKTnode *);
INPtables *INPtabInit(int);
void INPkillMods(void);
void INPtabEnd(INPtables *);
char *INPfindVer(char *line, char *version);
int INPgetStr(char **line, char **token, int gobble);
int INPgetTitle(CKTcircuit **ckt, struct card **data);
int INPgetUTok(char **line, char **token, int gobble);
int INPremTerm(char *token, INPtables *tab);



#endif
