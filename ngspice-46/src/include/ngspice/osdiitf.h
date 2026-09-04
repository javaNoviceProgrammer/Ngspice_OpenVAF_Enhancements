/*
 * This file is part of the OSDI component of NGSPICE.
 * Copyright© 2022 SemiMod GmbH.
 * 
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. 
 *
 * Author: Pascal Kuthe <pascal.kuthe@semimod.de>
 */

#pragma once

#include "ngspice/config.h"
#include "ngspice/devdefs.h"
#include <stdint.h>

typedef struct OsdiRegistryEntry {
  const void *descriptor;
  uint32_t inst_offset;
  uint32_t noise_offset;
  uint32_t dt;
  uint32_t temp;

  bool has_m;

#ifdef KLU
  uint32_t matrix_ptr_offset;
#endif

  /* absdelay support: filled at .osdi load time from OSDI_ABSDELAY_* symbols */
  uint32_t num_absdelays;
  const void *absdelay_infos;  /* points into the loaded .osdi's OSDI_ABSDELAY_INFOS */

  /* last_crossing support: filled at .osdi load time from
   * OSDI_LAST_CROSSING_* symbols */
  uint32_t num_last_crossings;
  const void *last_crossing_infos;  /* points into the loaded .osdi's OSDI_LAST_CROSSING_INFOS */

  /* Enhancement-401: terminal-short support, filled at .osdi load time from
   * OSDI_TERM_SHORT_* symbols. A model that shorts two of its own TERMINALS with
   * `V(a,b) <+ 0` cannot be served by node collapsing (terminals are allocated by
   * ngspice, see collapse_nodes), so the compiler emits a real 0 V source instead
   * and lists the branch here. If the netlist turns out to tie those terminals to
   * ONE circuit node the equation is redundant and the system singular, so setup
   * drops the branch current in that case. */
  uint32_t num_term_shorts;
  const void *term_short_infos;  /* points into the loaded .osdi's OSDI_TERM_SHORT_INFOS */

  /* `.option osdimc` parameter statistics, filled at .osdi load time from
   * OSDI_STAT_PARAM_* symbols (same side-table mechanism as absdelay above).
   * Each entry names a parameter the Verilog-A declared with `(* std= *)` /
   * `(* std_rel= *)` and the simulator varies per Monte-Carlo run. */
  uint32_t num_stat_params;
  const void *stat_param_infos;  /* points into the loaded .osdi's OSDI_STAT_PARAM_INFOS */

  /* Nature / discipline / attribute tables (OSDI_NATURES, OSDI_DISCIPLINES,
   * OSDI_ATTRIBUTES), filled at .osdi load time. The compiler has always
   * written a nature's declared `abstol` (LRM 3.6.1) into these, but nothing
   * on this side ever read them, so a model's tolerance never reached the
   * convergence test -- every node was judged by the global `abstol`/`vntol`
   * whatever its nature said. osdi_node_abstol() below resolves them. */
  uint32_t num_natures;
  const void *natures;
  uint32_t num_disciplines;
  const void *disciplines;
  uint32_t num_attributes;
  const void *attributes;

} OsdiRegistryEntry;

/* Declared abstol of node `node_idx`'s potential nature, or 0.0 when the model
 * names none (in which case the circuit-wide tolerance applies as before). */
double osdi_node_abstol(const OsdiRegistryEntry *entry, uint32_t node_idx);

/* Enhancement-401: one entry of OSDI_TERM_SHORT_INFOS. `node_1`/`node_2` are the
 * OSDI node indices of the two shorted terminals (`node_2` is UINT32_MAX when the
 * short is to ground); `flow_node` is the branch-current unknown to drop when the
 * two do not resolve to two distinct connected circuit nodes. */
typedef struct OsdiTermShortInfo {
  uint32_t node_1;
  uint32_t node_2;
  uint32_t flow_node;
} OsdiTermShortInfo;

typedef struct OsdiObjectFile {
  OsdiRegistryEntry *entrys;
  int num_entries;
} OsdiObjectFile;

extern OsdiObjectFile load_object_file(const char *path);
extern SPICEdev *osdi_create_spicedev(const OsdiRegistryEntry *entry);
extern int osdi_devtype_is_osdi(int type);   /* Enhancement-323 */

/* Enhancement-215: register a command-line plusarg (`+name[=value]`, passed
 * without the leading '+') so a compiled Verilog-A model's $test$plusargs /
 * $value$plusargs can read it through the simparam channel. */
extern void ngspice_register_plusarg(const char *arg);

extern char *inputdir;

/* Enhancement-500: `pre_osdi -va file.va ...` compiles Verilog-A in place.
 *
 * osdi_find_openvaf() is com_presnp.c's compiler lookup, exported so both
 * generators use one policy: the `openvaf` ngspice variable, then $OPENVAF,
 * then $SPICE_LIB_DIR/openvaf-r (the prebuilt binary this tree ships), then
 * PATH. A bare PATH search would miss the shipped compiler, which is exactly
 * where it lives for anyone using the bundle.
 *
 * osdi_va_cache is `.option osdicache`, read from the DECK CARDS rather than
 * through cp_getvar: pre_ commands run before the circuit is set up, so no
 * option has been published yet -- the trap Enhancement-464 recorded for
 * `autobus`. Default OFF: recompiling every time is the only safe default
 * while openvaf-r itself is under development, because the `.va` timestamp
 * says nothing about the COMPILER having changed (Enhancement-453's cache key
 * omitted its codegen settings and was wrong the same way). */
extern int osdi_va_cache;
extern char *osdi_find_openvaf(void);

/* Enhancement-55: deferred $finish/$stop requests. OSDIload latches the
 * eval-return flags per timepoint attempt; the analyses check at the
 * ACCEPTED-point boundary (acting mid-Newton-iteration breaks timestep
 * control) and end the analysis cleanly ($finish, after firing
 * @(final_step)) or pause resumably ($stop). */
#define OSDI_REQ_FINISH 1
#define OSDI_REQ_STOP 2
extern int OSDIpendingRequests(CKTcircuit *ckt);

/* Enhancement-53: fire Verilog-A `@(final_step)` blocks. Called by the
 * analyses (tran/op/dc/ac) once they complete successfully; issues one
 * dedicated eval() per OSDI instance with EVAL_FLAG_IS_FINAL_STEP set at the
 * converged final solution. Results are not loaded into the matrix/RHS.
 * Defined in src/osdi/osdiload.c. */
extern int OSDIfinalStep(CKTcircuit *ckt);

/* Deferred display/file output (LRM 9.4.6/9.5.9): flush the just-converged
 * point's buffered output. Called per accepted/converged solution point by the
 * analyses that solve a SEQUENCE of points without CKTaccept (.dc sweeps);
 * transient points flush from OSDIaccept and analysis ends from OSDIfinalStep. */
extern void OSDIpendingFlush(CKTcircuit *ckt);

/* Enhancement-413: terminal names of an OSDI instance (0 if it is not one), so
 * `.options savecurrents` can be expanded per terminal once the descriptor is
 * known. Defined in src/osdi/osdiparam.c. */
extern int OSDIterminalNames(CKTcircuit *ckt, const char *name, char ***names,
                             int *count);

/* Enhancement-417: 1 if the last setup_instance re-decided this instance's node
 * collapse away from the one the matrix was built for, else 0 (including for
 * every non-OSDI instance). Reading it clears it. Defined in
 * src/osdi/osdiparam.c. */
extern int OSDIcollapseChanged(GENinstance *instPtr);
extern int OSDIanyCollapseChanged(CKTcircuit *ckt);   /* Enhancement-471 */

/* `.option osdimc` (alias `automc`) automatic Monte-Carlo: called by if_run
 * at the start of every run-class command (not `resume`). Advances the trial
 * counter and, from the second run on, writes nominal+draw into every OSDI
 * parameter that declared `(* std= *)` statistics -- through the ordinary
 * parameter setter, so no netlist reset is involved. The FIRST run after
 * sourcing is the nominal baseline: default values of unset parameters are
 * only knowable after one setup pass has resolved them. With the option off
 * it restores any drawn parameter to its nominal and is otherwise free.
 * Defined in src/osdi/osdisetup.c. */
extern void OSDImcNewRun(CKTcircuit *ckt);

/* bug-hunt F1: a USER (`alter`/`altermod`, wildcards included) stored a scalar
 * real parameter -- recenter its Monte-Carlo nominal if it has one. Called
 * from frontend/spiceif.c's doset_user only; machine writes (.dc parameter
 * sweeps, `sweep` per-point/restore, sensitivity) must NOT recenter. */
extern void OSDImcNoteUserWrite(int typecode, GENinstance *dev, GENmodel *mdl,
                                int param_id, double value);

/* bug-hunt F2: the deck was (re)loaded -- every stored nominal's owner
 * pointer is stale; drop the table. Called by inp_dodeck. */
extern void OSDImcCircuitChanged(void);
/* Enhancement-535: loop-command trial policy -- a deterministic loop
 * (sweep per-point, optimize, wcd, loadpull) brackets its inner analyses
 * with HoldTrial so the whole loop is ONE sample; an INTERNAL reset calls
 * PreserveTrial so montecarlo/highsigma samples keep drawing; SigmaScale
 * is highsigma's -scale inflation for attribute-declared sigmas. */
extern void OSDImcHoldTrial(bool on);
extern void OSDImcPreserveTrial(void);
extern void OSDImcSigmaScale(double s);
/* E-536: the hunt round's known-open repairs.
 * InterruptReset -- a keyboard interrupt longjmps past every bracket clear;
 * ft_sigintr_cleanup() calls this so a leaked hold/inflation/preserve cannot
 * corrupt later commands (hunt bugs 5/6/12).
 * TrialCheckpoint/TrialRewind -- `optimize -center` replays the same osdimc
 * trial window for every candidate, so its yield objective is deterministic
 * across candidates while still sampling osdimc variation (hunt bug 8).
 * SampleLogLR -- the log importance weight of the current trial's inflated
 * gauss draws, for `highsigma -scale`'s estimator (hunt bug 7). */
/* E-537 (hunt G): bracket writes that go through the `alter` command but are
 * machine-computed (aging's dose), so they do not recenter a statistical
 * nominal -- the E-531 rule that only user writes recenter. */
extern void OSDImcMachineWrite(bool on);
/* E-537 (hunt P): a loop command's own `-seed`, mixed into the draw key so
 * independent replications really are independent. 0 = not given (the draws a
 * deck gets today). */
extern void OSDImcSeedOffset(unsigned s);
/* E-537 (hunt O): true while `.option osdimc` is drawing, so a command can say
 * that Latin-hypercube stratification does not cover these draws. */
extern bool OSDImcActive(void);
/* E-537 (hunt J): step past the nominal baseline so `montecarlo N` really
 * draws N samples rather than N-1 draws plus the deterministic nominal. */
extern void OSDImcSkipBaseline(void);
/* E-538: scope `highsigma -scale` to named statistical parameters, so the
 * importance weight stays low-dimensional enough to estimate with. A spec is
 * a bare parameter name or `@owner[param]` (`*` allowed as the owner); with
 * no specs every gauss statistical parameter inflates, as before. Hits counts
 * the draws the specs actually matched, so the command can say when a spec
 * named nothing. */
extern void OSDImcScaleScopeClear(void);
extern bool OSDImcScaleScopeAdd(const char *spec);
extern int  OSDImcScaleScopeHits(void);
extern void OSDImcInterruptReset(void);
extern unsigned long OSDImcTrialCheckpoint(void);
extern void OSDImcTrialRewind(unsigned long t);
extern double OSDImcSampleLogLR(CKTcircuit *ckt);
/* 2026-09-04 MC hunt, F3: WALK mode for `wcd`. While a walk is set, every
 * Gaussian statistical parameter takes nominal + sigma * z[k] (k = its place
 * in the applier's fixed enumeration order; 0 beyond n), uniform ones are held
 * at their nominal, and the trial counter's baseline gate does not apply --
 * the deck is a plain function of z. NULL/0 ends the walk. The counts are of
 * the CURRENT circuit's applicable parameters, valid after it has run once. */
extern void OSDImcWalk(const double *z, int n);
extern int  OSDImcWalkNdim(void);
extern int  OSDImcWalkNuniform(void);
/* 2026-09-04 hunt, F1: Verilog-A modules whose name is one of ngspice's own
 * (a built-in device's name, or a `.model` type keyword). They are registered
 * but SHADOWED: a `.model` card of that type resolves to the built-in, and
 * only an `n`-line instance -- which can mean nothing but an OSDI device --
 * re-binds the card to the module (INP2N). `osdi_shadowed_module` looks one
 * up by the card's type name and returns its device-table index (-1 if none),
 * naming the library and the built-in; `osdi_shadowed_module_for` looks one
 * up by the built-in's device name and returns the module's name (NULL if
 * none), naming the library. */
extern int osdi_shadowed_module(const char *type_name, const char **lib,
                                const char **builtin);
extern const char *osdi_shadowed_module_for(const char *devname,
                                            const char **lib);
