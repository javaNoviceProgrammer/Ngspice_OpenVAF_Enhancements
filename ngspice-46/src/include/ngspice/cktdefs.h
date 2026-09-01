/*
 * Copyright (c) 1985 Thomas L. Quarles
 * Modified 1999 Paolo Nenzi - Removed non STDC definitions
 * Modified 2000 AlansFixes
 */
#ifndef ngspice_CKTDEFS_H
#define ngspice_CKTDEFS_H

#include "ngspice/typedefs.h"
/* ensure config is always included to avoid missmatching type definitions*/
#include "ngspice/config.h"

/* gtri - evt - wbk - 5/20/91 - add event-driven and enhancements data */
#ifdef XSPICE
#include "ngspice/evttypes.h"
#include "ngspice/enhtypes.h"
#endif
/* gtri - evt - wbk - 5/20/91 - add event-driven and enhancements data */


#define MAXNUMDEVS 64   /* Max number of possible devices PN:XXX may cause toubles*/
#define MAXNUMDEVNODES 4        /* Max No. of nodes per device */
                         /* Need to change for SOI devs ? */

#include "ngspice/smpdefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/acdefs.h"
#include "ngspice/gendefs.h"
#include "ngspice/trcvdefs.h"
#include "ngspice/optdefs.h"
#include "ngspice/sen2defs.h"
#include "ngspice/pzdefs.h"
#include "ngspice/noisedef.h"
#include "ngspice/hash.h"

#ifdef RFSPICE
#include "../maths/dense/dense.h"
#endif


/* Enhancement-492: set by the OSDI load path when a Verilog-A device actually
 * raised $fatal, and by nothing else. CKTop's abort test used to read E_PANIC
 * alone, but E_PANIC has around ten producers -- circuit setup, OSDI parameter
 * and setup errors, PSS, pole-zero, expression evaluation, CIDER and the KLU
 * empty-matrix path -- so a deck containing no Verilog-A device at all was
 * told one had raised $fatal. */
extern int CKTvaFatalRaised;

struct CKTnode {
    IFuid name;
    int type;

#define SP_VOLTAGE 3
#define SP_CURRENT 4
#define NODE_VOLTAGE SP_VOLTAGE
#define NODE_CURRENT SP_CURRENT

    int number;                 /* Number of the node */
    double ic;                  /* Value of the initial condition */
    double nodeset;             /* Value of the .nodeset option */
    double *ptr;                /* ??? */
    CKTnode *next;              /* pointer to the next node */
    unsigned int icGiven:1;     /* FLAG ic given */
    unsigned int nsGiven:1;     /* FLAG nodeset given */
    /* Enhancement-429: was this node ever named by a DEVICE card, or created by
     * the simulator itself?  Every real creation path sets it; only
     * inp_analysis_node() -- which invents a node so that a `.tf`/`.sens`
     * card may legitimately precede the devices defining its nodes -- clears
     * it. A node still unset once the deck is parsed was named by an analysis
     * card and by nothing else, i.e. it is a typo, and the analysis would
     * otherwise report it as a perfectly good 0 V. */
    unsigned int devRef:1;      /* FLAG named by a device / made by the simulator */
};

/* defines for node parameters */
enum {
    PARM_NS = 1,
    PARM_IC,
    PARM_NODETYPE,
};

/* Enhancement-438: `.option warn_physics` -- set by the frontend, read by the
 * device layer where a physical constraint needs both a parameter and its
 * context (the coupling coefficient needs the two inductances). */
extern int ng_warn_physics;

struct CKTcircuit {

/* gtri - begin - wbk - change declaration to allow dynamic sizing */

/* An associated change is made in CKTinit.c to alloc the space */
/* required for the pointers.  No changes are needed to the source */
/* code at the 3C1 level, although the compiler will generate */
/* slightly different code for references to this data. */

/*  GENmodel *CKThead[MAXNUMDEVS]; The max number of loadable devices */
    GENmodel **CKThead;

/* gtri - end   - wbk - change declaration to allow dynamic sizing */

/*    GENmodel *CKThead[MAXNUMDEVS];  maschmann : deleted */


    STATistics *CKTstat;        /* The STATistics structure */
    double *CKTstates[8];       /* Used as memory of past steps ??? */

    /* Some shortcut for CKTstates */
#define CKTstate0 CKTstates[0]
#define CKTstate1 CKTstates[1]
#define CKTstate2 CKTstates[2]
#define CKTstate3 CKTstates[3]
#define CKTstate4 CKTstates[4]
#define CKTstate5 CKTstates[5]
#define CKTstate6 CKTstates[6]
#define CKTstate7 CKTstates[7]
    double CKTtime;             /* Current transient simulation time */
    double CKTdelta;            /* next time step in transient simulation */
    double CKTdeltaOld[7];      /* Memory for the 7 most recent CKTdelta */
    double CKTtemp;             /* Actual temperature of CKT, initialzed to 300.15 K in cktinit.c*/
    double CKTnomTemp;          /* Reference temperature 300.15 K set in cktinit.c */
    double CKTvt;               /* Thernmal voltage at CKTtemp */
    double CKTag[7];            /* the gear variable coefficient matrix */
#ifdef PREDICTOR
    double CKTagp[7];           /* the gear predictor variable
                                   coefficient matrix */
#endif /*PREDICTOR*/
    int CKTorder;               /* the integration method order */
    int CKTmaxOrder;            /* maximum integration method order */
    int CKTintegrateMethod;     /* the integration method to be used */
    double CKTxmu;              /* for trapezoidal method */
    /* Enhancement-419: TR-BDF2 sub-step bookkeeping. `CKTtrStage` is 0 outside
     * a composite step, 1 while the trapezoidal sub-step is being solved and 2
     * while the BDF2 sub-step is. `CKTtrGamma` is the split point (2-sqrt(2));
     * it is a field rather than a constant so the tests can sweep it and show
     * that any other value costs a matrix refactorization between stages. */
    int CKTtrStage;
    double CKTtrGamma;
    int CKTsdirkStage;          /* Enhancement-419: 1..s, 0 outside a step */
    int CKTsdirkStages;
    double CKTsdirkGamma;
    int CKTindverbosity;        /* control check of inductive couplings */


/* known integration methods */
#define TRAPEZOIDAL 1
#define GEAR 2
/* Enhancement-419: TR-BDF2, a one-step COMPOSITE method -- a trapezoidal
 * sub-step over [t, t+gamma*h] followed by a BDF2 step across t, t+gamma*h and
 * t+h. With gamma = 2-sqrt(2) both sub-steps have the SAME leading coefficient
 *      2/(gamma*h)  ==  (2-gamma)/((1-gamma)*h)  ==  3.4142135.../h
 * (the root of gamma^2 - 4*gamma + 2), so the Jacobian scaling is identical
 * across the step and the conductance conditioning does not change between
 * stages. Second order and L-stable: unlike trapezoidal it damps rather than
 * rings at a sharp transition, and unlike Gear it does not pay accuracy for it.
 *
 * Neither sub-step needs a new integration formula. Stage 1 is exactly the
 * existing TRAPEZOIDAL order-2 form evaluated at delta = gamma*h; stage 2 is
 * the GEAR order-2 shape (ag[0]*q0 + ag[1]*q1 + ag[2]*q2) with the unequal-step
 * BDF2 coefficients and the state slots rotated once mid-step, so that q1 holds
 * the stage-1 charge and q2 the charge at t. */
#define TRBDF2 3
/* Enhancement-419: a general singly-diagonally-implicit Runge-Kutta driver.
 * Restricted to STIFFLY ACCURATE tableaux (a[s][j] == b[j], so c[s] == 1 and
 * the final stage IS the solution). That restriction is what lets RK fit
 * ngspice at all: without it the step would end with a weighted COMBINATION of
 * stage values, which nothing could write into the state vector -- every value
 * a device stores has to come out of a solve, not out of an assignment.
 *
 * Each stage is one ordinary implicit solve with ag[0] = 1/(h*gamma); a single
 * gamma on the diagonal means every stage presents the solver with the same
 * conductance scaling, exactly as in TR-BDF2. Shipped tableau: Alexander's
 * 3-stage order-3 L-stable SDIRK, gamma the root of g^3-3g^2+3g/2-1/6. */
#define SDIRK 4
/* Enhancement-419: Adams-Moulton, the implicit multistep family, of order
 * `maxord`. AM2 IS the trapezoidal rule, so `method=adams maxord=2` must
 * reproduce `method=trap` bit for bit -- the example suite asserts exactly
 * that, which is what validates the coefficient generator.
 *
 * NOT STIFFLY STABLE ABOVE ORDER 2. The Adams stability region shrinks with
 * order instead of opening out to the left half-plane the way BDF's does; that
 * is precisely why SPICE standardised on Gear. AM3+ is here to be measured, and
 * for genuinely non-stiff circuits -- it will lose to Gear on anything with a
 * wide spread of time constants, and the campaign is expected to show it. */
#define ADAMS 5

    SMPmatrix *CKTmatrix;       /* pointer to sparse matrix */
    int CKTniState;             /* internal state */
    double *CKTrhs;             /* current rhs value - being loaded */
    double *CKTrhsOld;          /* previous rhs value for convergence
                                   testing */
    double *CKTrhsSpare;        /* spare rhs value for reordering */
    double *CKTirhs;            /* current rhs value - being loaded
                                   (imag) */
    double *CKTirhsOld;         /* previous rhs value (imaginary)*/
    double *CKTirhsSpare;       /* spare rhs value (imaginary)*/
    double *CKTpred;            /* predicted solution vector */
#ifdef PREDICTOR
    double *CKTsols[8];         /* previous 8 solutions */
#endif /* PREDICTOR */

    double *CKTrhsOp;           /* opearating point values */
    double *CKTsenRhs;          /* current sensitivity rhs values */
    double *CKTseniRhs;         /* current sensitivity rhs values
                                   (imag)*/


/*
 *  symbolic constants for CKTniState
 *      Note that they are bitwise disjoint
 *  What is their meaning ????
 */

#define NISHOULDREORDER       0x1
#define NIREORDERED           0x2
#define NIUNINITIALIZED       0x4
#define NIACSHOULDREORDER    0x10
#define NIACREORDERED        0x20
#define NIACUNINITIALIZED    0x40
#define NIDIDPREORDER       0x100
#define NIPZSHOULDREORDER   0x200

    int CKTmaxEqNum;            /* And this ? */
    int CKTcurrentAnalysis;     /* the analysis in progress (if any) */

/* defines for the value of  CKTcurrentAnalysis */
/* are in TSKdefs.h */

    CKTnode *CKTnodes;          /* ??? */
    CKTnode *CKTlastNode;       /* ??? */
    CKTnode *prev_CKTlastNode;  /* just before model setup */

    /* This define should be somewhere else ??? */
#define NODENAME(ckt,nodenum) CKTnodName(ckt,nodenum)
    int CKTnumStates;           /* Number of states summed up over all device instances */
    long CKTmode;               /* Mode of operation of the circuit
                                   ??? */

/* defines for CKTmode */

/* old 'mode' parameters */
#define MODE               0x3
#define MODETRAN           0x1
#define MODEAC             0x2

/* for noise analysis */
#define MODEACNOISE        0x8

/* old 'modedc' parameters */
#define MODEDC            0x70
#define MODEDCOP          0x10
#define MODETRANOP        0x20
#define MODEDCTRANCURVE   0x40

/* old 'initf' parameters */
#define INITF           0x3f00
#define MODEINITFLOAT    0x100
#define MODEINITJCT      0x200
#define MODEINITFIX      0x400
#define MODEINITSMSIG    0x800
#define MODEINITTRAN    0x1000
#define MODEINITPRED    0x2000

#ifdef RFSPICE
#define MODESP          0x4000
#define MODESPNOISE     0x8000
#endif

/* old 'nosolv' paramater */
#define MODEUIC 0x10000l

    int CKTbypass;              /* bypass option, how does it work ?  */
    int CKTdcMaxIter;           /* iteration limit for dc op.  (itl1) */
    int CKTdcTrcvMaxIter;       /* iteration limit for dc tran. curv
                                   (itl2) */
    int CKTtranMaxIter;         /* iteration limit for each timepoint
                                   for tran*/
    /* (itl4) */
    int CKTbreakSize;           /* number of breakpoints in table *CKTbreaks */
    int CKTbreak;               /* if 1, a breakpoint may be set (only used in isrcacct.c) */
    double CKTsaveDelta;        /* previous delta, before breakpoints set a new delta */
    double CKTminBreak;         /* minimum time difference between breakpoints */
    double *CKTbreaks;          /* List of breakpoints as an array of doubles */
    double CKTabstol;           /* --- */
    double CKTpivotAbsTol;      /* --- */
    double CKTpivotRelTol;      /* --- */
    double CKTreltol;           /* --- */
    double CKTchgtol;           /* --- */
    double CKTvoltTol;          /* --- */
    double CKTlteReltol;        /* relative error in voltage based truncation error estimation */
    double CKTlteAbstol;        /* absolute error in voltage based truncation error estimation */
    double CKTlteTrtol;         /* scaling time step in voltage based truncation error estimation */
    int CKTnewtrunc;            /* enable lte (local truncation error) based on voltages */
    double CKTgmin;             /* .options GMIN */
    double CKTgshunt;           /* .options RSHUNT */
    double CKTcshunt;           /* .options CSHUNT */
    double CKTdelmin;           /* minimum time step for tran analysis */
    double CKTtrtol;            /* .options TRTOL */
    double CKTfinalTime;        /* TSTOP */
    double CKTstep;             /* TSTEP */
    double CKTmaxStep;          /* TMAX */
    double CKTinitTime;         /* TSTART */
    double CKTomega;            /* actual angular frequency for ac analysis */
    double CKTsrcFact;          /* source stepping scaling factor */
    double CKTdiagGmin;         /* actual value during gmin stepping */
    int CKTnumSrcSteps;         /* .options SRCSTEPS */
    int CKTnumGminSteps;        /* .options GMINSTEPS */
    double CKTgminFactor;       /* gmin stepping scaling factor */
    int CKTnoncon;              /* used by devices (and few other places)
                                   to announce non-convergence */
    double CKTdefaultMosM;      /* Default MOS multiplier parameter m */
    double CKTdefaultMosL;      /* Default Channel Lenght of MOS devices */
    double CKTdefaultMosW;      /* Default Channel Width of MOS devics */
    double CKTdefaultMosAD;     /* Default Drain Area of MOS */
    double CKTdefaultMosAS;     /* Default Source Area of MOS */
    unsigned int CKThadNodeset:1; /* flag to show that nodes have been set up */
    unsigned int CKTfixLimit:1; /* flag to indicate that the limiting
                                   of MOSFETs should be done as in
                                   SPICE2 */
    unsigned int CKTnoOpIter:1; /* flag to indicate not to try the operating
                                   point brute force, but to use gmin stepping
                                   first */
    unsigned int CKTisSetup:1;  /* flag to indicate if CKTsetup done */
    /* Enhancement-471: reuse the existing setup for the next analysis instead
       of tearing the circuit down and rebuilding it. Only ever a REQUEST --
       CKTdoJob still re-decides node collapse through CKTtemp and rebuilds for
       real if it moved. */
    unsigned int CKTreuseSetup:1;
    /* Enhancement-471: how the last repeated analysis actually went -- points
       whose setup was kept, and points where the node collapse moved and the
       circuit had to be rebuilt after all. Reported under `set ngdebug`, which
       is what makes the decision observable instead of inferred from a clock. */
    int CKTreuseKept;
    int CKTreuseRebuilt;
    /* Enhancement-365: set when an analysis has REPLACED ckt->CKTmatrix while
     * leaving CKTisSetup asserted, so every device's cached matrix-element
     * pointer now dangles. `pz` does exactly this (CKTpzSetup destroys and
     * rebuilds the matrix). A consumer that would otherwise skip CKTsetup must
     * first do a balanced CKTunsetup()/CKTsetup() to rebind. Cleared by
     * CKTsetup(), which is what makes the bindings valid again. */
    unsigned int CKTbindStale:1;
#ifdef XSPICE
    unsigned int CKTadevFlag:1; /* flag indicates 'A' devices in the circuit */
#endif
    JOB *CKTcurJob;             /* Next analysis to be performed ??? */

    SENstruct *CKTsenInfo;      /* the sensitivity information */
    double *CKTtimePoints;      /* list of all accepted timepoints in
                                   the current transient simulation */
    double *CKTdeltaList;       /* list of all timesteps in the
                                   current transient simulation */
    int CKTtimeListSize;        /* size of above lists */
    int CKTtimeIndex;           /* current position in above lists */
    int CKTsizeIncr;            /* amount to increment size of above
                                   arrays when you run out of space */
    unsigned int CKTtryToCompact:1; /* try to compact past history for LTRA
                                       lines */
    unsigned int CKTbadMos3:1;  /* Use old, unfixed MOS3 equations */
    unsigned int CKTkeepOpInfo:1; /* flag for small signal analyses */
    unsigned int CKTcopyNodesets:1; /* NodesetFIX */
    unsigned int CKTnodeDamping:1; /* flag for node damping fix */
    unsigned int CKTlinesearch:1;  /* Enhancement-111: adaptive damped-Newton line search */
    unsigned int CKTdcFirstTry:1;  /* Enhancement-256: set by CKTop only around the FIRST plain
                                      Newton operating-point attempt, so the spurious-op guard in
                                      NIiter never fires inside a convergence-aid sub-solve
                                      (gmin/source stepping, pseudo-transient/optran) */
    double CKTlsMerit;             /* E-111: this iteration's residual merit ||F|| = ||G*x-b|| */
    double *CKTlsXk;               /* E-111: line-search scratch (saved x_k) */
    double *CKTlsD;                /* E-111: line-search scratch (Newton step d) */
    int CKTlsBufSz;                /* E-111: allocated size of the LS scratch buffers */
    unsigned int CKTtrustregion:1; /* Enhancement-153: Levenberg-Marquardt trust-region Newton */
    double CKTtrLambda;            /* E-153: dimensionless trust-region damping parameter */
    unsigned int CKTptcont:1;      /* Enhancement-127: pseudo-transient continuation enabled */
    double CKTpseudoGmin;          /* E-127: pseudo-transient shunt conductance Gps=Cps/dtau (0 = off) */
    double *CKTpseudoPrev;         /* E-127: pseudo-transient previous-step solution x_prev */
    unsigned int CKTdynorder:1;    /* Enhancement-128: LTE-based dynamic integration order */
    unsigned int CKTconvhelp:1;    /* Enhancement-204: auto-escalating DC convergence aids */
    int CKTordFix;                 /* Enhancement-181: fixed integration order, 0 = off */
    int CKTorderCnt;               /* E-128: accepted steps since the last order reset (history depth) */
    int CKTorderMaxUsed;           /* E-128: highest integration order actually selected (diagnostic) */
    int CKTorderHold;              /* E-128: steps to hold the order after a change (settling) */
    int CKTorderRej;               /* E-128: consecutive LTE rejections at the current point */
    unsigned int CKTcheckpoint:1;  /* Enhancement-131: DCtran should continue from a restored
                                      checkpoint (keep loaded state, build a fresh output plot) */
    double CKTabsDv;            /* abs limit for iter-iter voltage change */
    double CKTrelDv;            /* rel limit for iter-iter voltage change */
    int CKTtroubleNode;         /* Non-convergent node number */
    GENinstance *CKTtroubleElt; /* Non-convergent device instance */
    int CKTvarHertz;            /* variable HERTZ in B source */
/* gtri - evt - wbk - 5/20/91 - add event-driven and enhancements data */
#ifdef XSPICE
    Evt_Ckt_Data_t *evt;        /* all data about event driven stuff */
    Enh_Ckt_Data_t *enh;        /* data used by general enhancements */
#endif
/* gtri - evt - wbk - 5/20/91 - add event-driven and enhancements data */
#ifdef RFSPICE
    int  CKTactivePort;/* Identify active port during S-Param analysis*/
    int  CKTportCount; /* Number of RF ports */
    int           CKTVSRCid;    /* Place holder for VSRC Devices id*/
    GENinstance** CKTrfPorts;   /* List of all RF ports (HB & SP) */
    CMat* CKTAmat;
    CMat* CKTBmat;
    CMat* CKTSmat;
    CMat* CKTYmat;
    CMat* CKTZmat;
    // Data for RF Noise Calculations
    double* CKTportY;
    CMat* CKTNoiseCYmat;
    int CKTnoiseSourceCount;
    CMat* CKTadjointRHS;       // Matrix where Znj are stored. Znj = impedance from j-th noise source to n-th port
#endif
#ifdef WITH_PSS
/* SP: Periodic Steady State Analysis - 100609 */
    double CKTstabTime;		/* PSS stab time */
    double CKTguessedFreq;	/* PSS guessed frequency */
    int CKTharms;		/* PSS harmonics */
    long int CKTpsspoints;	/* PSS number of samples */
    char *CKToscNode;       	/* PSS oscnode */
    double CKTsteady_coeff;	/* PSS Steady Coefficient */
    int CKTsc_iter;        	/* PSS Maximum Number of Shooting Iterations */
/* SP: 100609 */
#endif

    unsigned int CKTisLinear:1; /* flag to indicate that the circuit
                                   contains only linear elements */
    unsigned int CKTnoopac:1; /* flag to indicate that OP will not be evaluated
                                 during AC simulation */
    int CKTsoaCheck;    /* flag to indicate that in certain device models
                           a safe operating area (SOA) check is executed */
    int CKTsoaMaxWarns; /* specifies the maximum number of SOA warnings */

    double CKTepsmin; /* minimum argument value for some log functions, e.g. diode saturation current*/

    NGHASHPTR DEVnameHash;
    NGHASHPTR MODnameHash;

    GENinstance *noise_input;   /* identify the input vsrc/isrc during noise analysis */

#ifdef KLU
    unsigned int CKTkluMODE:1;
    unsigned int CKTpzEig:1;    /* Enhancement-173: eigenvalue-based pole-zero */
    double CKTkluMemGrowFactor ;
    int CKTkluOrdering ;        /* Enhancement-152: 0=AMD, 1=COLAMD          */
    int CKTkluScale ;           /* Enhancement-152: 0=none, 1=sum, 2=max     */
    int CKTkluBTF ;             /* Enhancement-152: 1=block-triangular, 0=off */
#endif
};


/* Now function prottypes */

extern int ACan(CKTcircuit *, int);
extern int ACaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern int ACsetParm(CKTcircuit *, JOB *, int , IFvalue *);
extern int CKTacDump(CKTcircuit *, double , runDesc *);
extern int CKTacLoad(CKTcircuit *);
extern int CKTaccept(CKTcircuit *);
extern int CKTacct(CKTcircuit *, JOB *, int , IFvalue *);
extern int CKTask(CKTcircuit *, GENinstance *, int , IFvalue *, IFvalue *);
extern int CKTaskAnalQ(CKTcircuit *, JOB *, int , IFvalue *, IFvalue *);
extern int CKTaskNodQst(CKTcircuit *, CKTnode *, int , IFvalue *, IFvalue *);
extern int CKTbindNode(CKTcircuit *, GENinstance *, int , CKTnode *);
extern void CKTbreakDump(CKTcircuit *);
extern int CKTclrBreak(CKTcircuit *);
extern int CKTconvTest(CKTcircuit *);
extern int CKTcrtElt(CKTcircuit *, GENmodel *, GENinstance **, IFuid);
extern int CKTdelTask(CKTcircuit *, TSKtask *);
extern int CKTdestroy(CKTcircuit *);
extern int CKTdltAnal(void *, void *, void *);
extern int CKTdltInst(CKTcircuit *, void *);
extern int CKTdltMod(CKTcircuit *, GENmodel *);
extern int CKTdltNNum(CKTcircuit *, int);
extern int CKTdltNodeSet(CKTcircuit *, const char *, int);  /* Enhancement-470 */
extern int CKTdltNod(CKTcircuit *, CKTnode *);
/* Enhancement-534: may sweeping `param` on built-in `type_name` move its topology? */
extern int CKTbuiltinTopologyParamRisk(const char *type_name, const char *param);
extern int CKTdoJob(CKTcircuit *, int , TSKtask *);
extern void CKTdeclareSweptParams(const char *decl);   /* Enhancement-503 */
extern void CKTdump(CKTcircuit *, double, runDesc *);
extern int CKTsoaInit(void);
extern int CKTsoaCheck(CKTcircuit *);
#ifdef CIDER
extern void NDEVacct(CKTcircuit *ckt, FILE *file);
#endif /* CIDER */
extern void CKTncDump(CKTcircuit *);
extern int CKTfndAnal(CKTcircuit *, int *, JOB **, IFuid , TSKtask *, IFuid);
extern int CKTfndBranch(CKTcircuit *, IFuid);
extern GENinstance *CKTfndDev(CKTcircuit *, IFuid);
extern GENmodel *CKTfndMod(CKTcircuit *, IFuid);
extern int CKTfndNode(CKTcircuit *, CKTnode **, IFuid);
extern int CKTfndTask(CKTcircuit *, TSKtask **, IFuid );
extern int CKTground(CKTcircuit *, CKTnode **, IFuid);
extern int CKTic(CKTcircuit *);
extern int CKTinit(CKTcircuit **);
extern int CKTinst2Node(CKTcircuit *, void *, int , CKTnode **, IFuid *);
extern int CKTlinkEq(CKTcircuit *, CKTnode *);
extern int CKTload(CKTcircuit *);
extern int CKTmapNode(CKTcircuit *, CKTnode **, IFuid);
extern int CKTmkCur(CKTcircuit  *, CKTnode **, IFuid , char *);
extern int CKTmkNode(CKTcircuit *, CKTnode **);
extern int CKTmkVolt(CKTcircuit  *, CKTnode **, IFuid , char *);
extern int CKTmodAsk(CKTcircuit *, GENmodel *, int , IFvalue *, IFvalue *);
extern int CKTmodCrt(CKTcircuit *, int , GENmodel **, IFuid);
extern int CKTmodParam(CKTcircuit *, GENmodel *, int , IFvalue *, IFvalue *);
extern int CKTnames(CKTcircuit *, int *, IFuid **);
#ifdef RFSPICE
extern int CKTSPnames(CKTcircuit*, int*, IFuid**);
#endif
extern int CKTdnames(CKTcircuit *);
extern int CKTnewAnal(CKTcircuit *, int , IFuid , JOB **, TSKtask *);
extern int CKTnewEq(CKTcircuit *, CKTnode **, IFuid);
extern int CKTnewNode(CKTcircuit *, CKTnode **, IFuid);
extern int CKTnewTask(CKTcircuit *, TSKtask **, IFuid, TSKtask **);
extern int CKTnoise (CKTcircuit *ckt, int mode, int operation, Ndata *data);
extern IFuid CKTnodName(CKTcircuit *, int);
extern void CKTnodOut(CKTcircuit *);
extern CKTnode * CKTnum2nod(CKTcircuit *, int);
extern int CKTop(CKTcircuit *, long, long, int);
extern void CKTsetWarmStart(int);   /* Enhancement-188: warm-start repeated DC ops */
extern int CKTpModName(char *, IFvalue *, CKTcircuit *, int , IFuid , GENmodel **);
extern int CKTpName(char *, IFvalue *, CKTcircuit *, int , char *, GENinstance **);
extern int CKTparam(CKTcircuit *, GENinstance *, int , IFvalue *, IFvalue *);
extern int CKTpzFindZeros(CKTcircuit *, PZtrial **, int *);
extern int CKTpzEig(CKTcircuit *, PZtrial **, int *);
extern int CKTpzLoad(CKTcircuit *, SPcomplex *);
extern int CKTpzSetup(CKTcircuit *, int);
extern int CKTsenAC(CKTcircuit *);
extern int CKTsenComp(CKTcircuit *);
extern int CKTsenDCtran(CKTcircuit *);
extern int CKTsenLoad(CKTcircuit *);
extern void CKTsenPrint(CKTcircuit *);
extern int CKTsenSetup(CKTcircuit *);
extern int CKTsenUpdate(CKTcircuit *);
extern int CKTsetAnalPm(CKTcircuit *, JOB *, int , IFvalue *, IFvalue *);
extern int CKTsetBreak(CKTcircuit *, double);
extern int CKTsetNodPm(CKTcircuit *, CKTnode *, int , IFvalue *, IFvalue *);
extern int CKTsetOpt(CKTcircuit *, JOB *, int , IFvalue *);
extern int CKTsetup(CKTcircuit *);
extern void CKTannounceSolver(int klu);   /* Enhancement-266: announce-on-change */
extern int CKTunsetup(CKTcircuit *);
extern int CKTtemp(CKTcircuit *);
extern char *CKTtrouble(CKTcircuit *, char *);
extern void CKTterr(int , CKTcircuit *, double *);
extern int CKTtrunc(CKTcircuit *, double *);
extern int CKTtypelook(char *);
extern int DCOaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern int DCOsetParm(CKTcircuit  *, JOB *, int , IFvalue *);
extern int DCTaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern int DCTsetParm(CKTcircuit  *, JOB *, int , IFvalue *);
extern int DCop(CKTcircuit *ckt, int notused); /* va: notused avoids "init from incompatible pointer type" */
extern int DCtrCurv(CKTcircuit *, int);
extern int DCtran(CKTcircuit *, int);
extern int DCtran_step_quit(CKTcircuit *ckt);
extern int DISTOan(CKTcircuit *, int);
extern int NOISEan(CKTcircuit *, int);
extern int PZan(CKTcircuit *, int);
extern int PZinit(CKTcircuit *);
extern int PZpost(CKTcircuit *);
extern int PZaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern int PZsetParm(CKTcircuit *, JOB *, int , IFvalue *);

extern int OPtran(CKTcircuit *, int);

#ifdef WANT_SENSE2
extern int SENaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern void SENdestroy(SENstruct *);
extern int SENsetParm(CKTcircuit *, JOB *, int , IFvalue *);
extern int SENstartup(CKTcircuit *, int);
#endif

extern int SPIinit(IFfrontEnd *, IFsimulator **);
extern int TFanal(CKTcircuit *, int);
extern int TFaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern int TFsetParm(CKTcircuit *, JOB *, int , IFvalue *);
extern int TRANaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern int TRANsetParm(CKTcircuit *, JOB *, int , IFvalue *);
extern int TRANinit(CKTcircuit *, JOB *);

#ifdef WITH_PSS
/* Steady State Analysis */
extern int PSSaskQuest(CKTcircuit *, JOB *, int , IFvalue *);
extern int PSSsetParm(CKTcircuit *, JOB *, int , IFvalue *);
extern int PSSinit(CKTcircuit *, JOB *);
extern int DCpss(CKTcircuit *, int);
/* Enhancement-209: HBanalyze hands its converged spectrum back to the frontend
   (com_hb) so it can publish nutmeg vectors. When `out` is non-NULL and the run
   converges, ownership of the Vr/Vi arrays passes to the caller (which frees them
   after publishing); pass NULL to keep the old behaviour (printed table only). */
struct hbspectrum {
    int     N;          /* number of circuit unknowns (solution row stride) */
    int     K;          /* highest harmonic */
    double  f0;         /* fundamental frequency (Hz) */
    double *Vr, *Vi;    /* [(2K+1)*N] two-sided Fourier coefficients, index (k+K)*N+i */
};
extern int HBanalyze(CKTcircuit *, double f0, int K, int P, int maxiter, double tol, int verbose, struct hbspectrum *out); /* E-134; E-209 out */
extern int QPSShb(CKTcircuit *, double f1, double f2, int K1, int K2, int P1, int P2, int maxiter, double tol, int verbose); /* E-136 */
extern int QPACanalyze(CKTcircuit *, double f_in, int verbose); /* E-137 */
extern int QPXFanalyze(CKTcircuit *, int outNode, double f_in, int verbose); /* E-141 */
extern int QPACsweep(CKTcircuit *, int stepType, int np, double fstart, double fstop, double *freqs, double *data); /* E-142 */
extern int QPnoiseSweep(CKTcircuit *, int outNode, int stepType, int np, double fstart, double fstop, double *freqs, double *data); /* E-142 */
extern int QPXFsweep(CKTcircuit *, int outNode, int stepType, int np, double fstart, double fstop, double *freqs, double *data); /* E-142 */
extern int QPnoiseAnalyze(CKTcircuit *, int outNode, double f_in, int cyclo, int verbose); /* E-138 / -139 */
extern int HBOSCanalyze(CKTcircuit *, int oscNode, int K, int P, double f0seed, double ampseed, int maxiter, double tol, int verbose, struct hbspectrum *out); /* E-140; E-487 out */
extern int EFanalysis(CKTcircuit *, int obsNode, double fc, double tstop, int nppp, int M0, int Mmax, double reltol, double *o_time, double *o_amp, double *o_dc, double *o_re, double *o_im, int maxpts); /* E-154 envelope following */
extern int CKTreduceRC(CKTcircuit *, double fmax, double factor, int maxdeg, int *keep, int nkeep, const char *fname, const char *subname); /* E-155/156 sparse TICER RC reduction */
/* Enhancement-487: the phase-noise sweep hands its curve back the same way
   HBanalyze hands back a spectrum, so `com_phasenoise` can publish it as nutmeg
   vectors instead of only printing a table. Ownership of foff/ldbc passes to the
   caller; pass NULL for the old printed-table-only behaviour. */
struct pnspectrum {
    int     n;          /* number of offset points */
    double  f0;         /* carrier frequency (Hz) */
    double *foff;       /* [n] offset frequency (Hz) */
    double *ldbc;       /* [n] L(df) in dBc/Hz */
};
extern int PhaseNoiseAnalyze(CKTcircuit *, double fstart, double fstop, int npts, int verbose, struct pnspectrum *out); /* E-140; E-487 out */
#endif

#ifdef RFSPICE
extern int SPan(CKTcircuit*, int);
extern int SPaskQuest(CKTcircuit*, JOB*, int, IFvalue*);
extern int SPsetParm(CKTcircuit*, JOB*, int, IFvalue*);
extern int CKTspDump(CKTcircuit*, double, runDesc*, int);
extern int CKTspLoad(CKTcircuit*);
extern int CKTmatrixIndex(CKTcircuit*, int, int);
extern int CKTspCalcPowerWave(CKTcircuit* ckt);
extern int CKTspCalcSMatrix(CKTcircuit* ckt);
#endif

#ifdef __cplusplus
extern "C"
{
#endif
extern int NaskQuest(CKTcircuit *, JOB *, int, IFvalue *);
extern int NsetParm(CKTcircuit *, JOB *, int, IFvalue *);
extern int NIacIter(CKTcircuit *);
extern int NIcomCof(CKTcircuit *);
extern int NIconvTest(CKTcircuit *);
extern void NIdestroy(CKTcircuit *);
extern int NIinit(CKTcircuit  *);
extern int NIintegrate(CKTcircuit *, double *, double *, double , int);
/* Enhancement-419: the SDIRK tableau lives in niinteg.c, next to the only
 * formula that needs the full a[i][j]; dctran needs just the stage count, the
 * diagonal and the abscissae. */
extern void NIsdirkInfo(int *stages, double *gamma);
extern double NIsdirkC(int stage);
extern int NIiter(CKTcircuit * , int);
extern void NIresetwarnmsg(void);
extern int NIpzMuller(PZtrial **, PZtrial *);
extern int NIpzComplex(PZtrial **, PZtrial *);
extern int NIpzSym(PZtrial **, PZtrial *);
extern int NIpzSym2(PZtrial **, PZtrial *);
extern int NIreinit(CKTcircuit *);
extern int NIsenReinit(CKTcircuit *);
extern int NIdIter (CKTcircuit *);
extern void NInzIter(CKTcircuit *, int, int);
#ifdef RFSPICE
extern int NIspPreload(CKTcircuit*);
extern int NIspSolve(CKTcircuit*);
#endif
#ifdef __cplusplus
}
#endif

#ifdef PREDICTOR
extern int NIpred(CKTcircuit *ckt);
#endif

extern IFfrontEnd *SPfrontEnd;

struct circ;
extern void inp_evaluate_temper(struct circ *ckt);

#endif
