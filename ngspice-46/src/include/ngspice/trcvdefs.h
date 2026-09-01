/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Thomas L. Quarles
Modified: 1999 Paolo Nenzi
**********/
/*
 */
#ifndef ngspice_TRCVDEFS_H
#define ngspice_TRCVDEFS_H


#include "ngspice/jobdefs.h"
#include "ngspice/tskdefs.h"
#include "ngspice/gendefs.h"
    /*
     * structures used to describe D.C. transfer curve analyses to
     * be performed.
     */

#define TRCVNESTLEVEL 2 /* depth of nesting of curves - 2 for spice2 */

/* PN: The following define is for temp sweep */
/* Courtesy of: Serban M. Popescu */
#ifndef TEMP_CODE
#define TEMP_CODE 1023
#endif

/* Enhancement-62: sweep type code for a generic instance-parameter sweep
   (`.dc @inst[param] start stop step`), resolved through the device's own
   DEVparam/DEVask interface -- works for any device type that exposes a
   settable real instance parameter, including Verilog-A (OSDI) devices. */
#ifndef PARAM_CODE
#define PARAM_CODE 1024
#endif

/* Enhancement-534: sweep type code for the extended parameter sweeps --
   a MODEL parameter (`@mod[p]`, subcircuit copies included through the
   `@x1.rmod[p]` spelling), and the wildcard families `sweep`/`altermod`
   established: `@*[p]` (every model with p), `@#*[p]` / `@*[[p]]` (every
   instance with p), `@*:leaf[p]` / `@*.leaf[p]` (every model named leaf).
   Targets are collected once at resolution and set per point through the
   DEV tables directly -- the MACHINE-write path, so an `osdimc` statistical
   parameter's nominal is never recentered by a sweep (Enhancement-531). */
#ifndef XPARAM_CODE
#define XPARAM_CODE 1025
#endif

/* Enhancement-534: one target of an XPARAM_CODE sweep. `inst` NULL means the
   target is the model card itself. */
typedef struct dct_xtarget {
    GENinstance *inst;
    GENmodel    *mod;
    int          type;      /* device type code */
    int          set_id;    /* IFparm id for DEVparam / DEVmodParam */
    int          ptype;     /* IF_REAL or IF_INTEGER */
    double       save;      /* nominal captured at resolution */
} DCTxtarget;

/* Enhancement-534: point-scale modes. LEGACY is the classic accumulate-by-step
   walk, byte-for-byte untouched; the keyword forms generate a COUNTED point
   set exactly the way the `sweep` command does. */
#define DCT_SCALE_LEGACY 0
#define DCT_SCALE_LIN    1
#define DCT_SCALE_DEC    2
#define DCT_SCALE_OCT    3

typedef struct {
    int JOBtype;
    JOB *JOBnextJob;
    char *JOBname;
    double TRCVvStart[TRCVNESTLEVEL];   /* starting voltage/current */
    double TRCVvStop[TRCVNESTLEVEL];    /* ending voltage/current */
    double TRCVvStep[TRCVNESTLEVEL];    /* voltage/current step */
    double TRCVvSave[TRCVNESTLEVEL];    /* voltage of this source BEFORE
                                         * analysis-to restore when done */
    int TRCVgSave[TRCVNESTLEVEL];    /* dcGiven flag; as with vSave */
    IFuid TRCVvName[TRCVNESTLEVEL];     /* source being varied */
    GENinstance *TRCVvElt[TRCVNESTLEVEL];   /* pointer to source */
    int TRCVvType[TRCVNESTLEVEL];   /* type of element being varied */
    int TRCVvParmId[TRCVNESTLEVEL]; /* Enhancement-62: IFparm id for a
                                     * PARAM_CODE (@inst[param]) sweep */
    int TRCVvParmType[TRCVNESTLEVEL]; /* Enhancement-427: IF_REAL or IF_INTEGER
                                       * -- decides which member of the IFvalue
                                       * union DCTsetInstParam writes */
    double TRCVvNow[TRCVNESTLEVEL]; /* Enhancement-62: current value of a
                                     * PARAM_CODE sweep (devices have no
                                     * generic readback field to consult) */
    int TRCVset[TRCVNESTLEVEL];     /* flag to indicate this nest level used */
    int TRCVnestLevel;      /* number of levels of nesting called for */
    int TRCVnestState;      /* iteration state during pause */
    /* Enhancement-534: keyword scales (`lin|dec|oct N start stop`). For
       DCT_SCALE_LEGACY every new field is dormant and the classic walk runs
       unchanged. For the keyword forms TRCVnPts holds N exactly as PARSED
       (lin: total points; dec/oct: points per decade/octave), TRCVratio the
       derived dec/oct multiplier, and TRCVidx the running point index. */
    int    TRCVscale[TRCVNESTLEVEL];
    int    TRCVnPts[TRCVNESTLEVEL];
    int    TRCVidx[TRCVNESTLEVEL];
    double TRCVratio[TRCVNESTLEVEL];
    /* Enhancement-535 (hunt N6): the derived TOTAL point count, kept apart
       from TRCVnPts, which stays exactly as PARSED (dec/oct: per decade or
       octave). The first version derived the total INTO TRCVnPts, so a
       still-loaded .dc card re-derived its multiplier from the previous
       total on every `run` -- 5, then 11, then 23 points, the grid refining
       itself silently. Resolution now recomputes ratio and total from the
       pristine parse on every run. */
    int    TRCVnTotal[TRCVNESTLEVEL];
    /* Enhancement-534: XPARAM_CODE bookkeeping -- the collected target list
       (freed on the restore path) and how the name was classified. */
    DCTxtarget *TRCVxTarg[TRCVNESTLEVEL];
    int         TRCVxN[TRCVNESTLEVEL];
} TRCV;

enum {
    DCT_START1 = 1,
    DCT_STOP1,
    DCT_STEP1,
    DCT_NAME1,
    DCT_TYPE1,
    DCT_START2,
    DCT_STOP2,
    DCT_STEP2,
    DCT_NAME2,
    DCT_TYPE2,
    DCT_SCALE1,          /* Enhancement-534 */
    DCT_NPTS1,
    DCT_SCALE2,
    DCT_NPTS2,
};

#endif
