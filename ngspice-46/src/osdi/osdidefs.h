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

#include "ngspice/cktdefs.h"
#include "ngspice/complex.h"
#include "ngspice/fteext.h"
#include "ngspice/gendefs.h"
#include "ngspice/ifsim.h"
#include "ngspice/ngspice.h"
#include "ngspice/noisedef.h"
#include "ngspice/typedefs.h"

#include "osdi.h"
#include "osdiext.h"

#include <stddef.h>
#include <stdint.h>
#ifndef _MSC_VER
#include <stdalign.h>
#endif

#ifdef _MSC_VER
typedef struct {
    long long __max_align_ll ;
    long double __max_align_ld;
    /* _Float128 is defined as a basic type, so max_align_t must be
       sufficiently aligned for it.  This code must work in C++, so we
       use __float128 here; that is only available on some
       architectures, but only on i386 is extra alignment needed for
       __float128.  */
#ifdef __i386__
    __float128 __max_align_f128 __attribute__((__aligned__(__alignof(__float128))));
#endif
} max_align_t;
#endif

#ifdef _MSC_VER
#define MAX_ALIGN 8
#define alignof sizeof
#else
#define MAX_ALIGN alignof(max_align_t)
#endif


/* named OSDI_ALIGN: plain ALIGN collides with the macOS SDK <sys/param.h> */
#ifndef _MSC_VER
#define OSDI_ALIGN(pow) __attribute__((aligned(pow)))
#else
#define OSDI_ALIGN(pow) __declspec(align(pow))
#endif

/* Per-absdelay slot descriptor read from the .osdi binary at load time. */
typedef struct OsdiAbsDelayInfo {
    uint32_t y_node;      /* OSDI node index for the synthetic input y_synth  */
    uint32_t z_node;      /* OSDI node index for the output node z             */
    uint32_t td_offset;   /* byte offset into OSDI instance data for td value  */
} OsdiAbsDelayInfo;

/* Per-last_crossing slot descriptor read from the .osdi binary at load time.
 * See openvaf/osdi/header/osdi_0_4_enhancement2.h for the full ABI writeup. */
typedef struct OsdiLastCrossingInfo {
    uint32_t y_node;      /* OSDI node index for the synthetic input y_synth  */
    uint32_t z_node;      /* OSDI node index for the crossing-time output z   */
    uint32_t dir_offset;  /* byte offset into OSDI instance data for dir value */
} OsdiLastCrossingInfo;

struct trnoise_state;

typedef struct OsdiExtraInstData {
  double dt;
  double temp;
  bool temp_given;
  bool dt_given;
  /* Enhancement-476: has this instance ever been evaluated without raising
   * $fatal? Operating-point variables are OUTPUTS -- they exist only once the
   * model has run. The instance block is calloc'd, so this reads false for a
   * device whose analysis never started or whose setup failed, which is
   * exactly when the opvar storage still holds its initial zeros. Set in the
   * single eval() funnel in osdiload.c; read by OSDIask. */
  bool opvars_valid;
  uint32_t eval_flags;

  /* Waveform history for absdelay — one row per slot, indexed by timepoint. */
  double **delay_hist;        /* [num_absdelays][capacity]  */
  uint32_t delay_hist_cap;    /* allocated timepoints in each row  */

  /* Pre-allocated KLU/sparse matrix pointers for the delay equation rows.
   * delay_jac_y[k] points to the (z_row, y_synth_col) entry,
   * delay_jac_z[k] points to the (z_row, z_col) entry.
   * These are the ACTIVE pointers used by the stamping code; under KLU they
   * are re-pointed between the real (CSC) and complex (CSC_Complex) arrays as
   * the analysis switches between DC/tran and AC.                */
  double **delay_jac_y;
  double **delay_jac_z;

  /* KLU only: saved real and complex CSC pointers for the delay rows, so the
   * active pointers above can be switched on each DC<->AC transition (mirrors
   * the regular Jacobian's inst_matrix_ptrs handling).  NULL under SPARSE,
   * where delay_jac_y/z already address an interleaved [real,imag] entry. */
  double **delay_jac_y_csc;
  double **delay_jac_z_csc;
  double **delay_jac_y_cx;
  double **delay_jac_z_cx;

  /* Waveform history for last_crossing — one row per slot, indexed by
   * timepoint, reusing the same CKTtimePoints/CKTtimeIndex timeline as
   * absdelay's delay_hist. */
  double **crossing_hist;       /* [num_last_crossings][capacity] */
  uint32_t crossing_hist_cap;   /* allocated timepoints in each row */

  /* Cached last-known crossing time per slot; persists across accept()
   * calls, only updated when a new qualifying crossing is found. Initialized
   * to 0.0 (== "no crossing observed yet"). */
  /* Value reported by last_crossing() before any qualifying crossing has been
  * observed. LRM 4.5.10 requires a NEGATIVE value here so that "not yet" is
  * distinguishable from "crossed at t = 0"; this used to be 0.0, which made a
  * model's `last_crossing(...) < 0` test read a crossing that never happened. */
#define OSDI_LAST_CROSSING_NONE (-1.0)
  double *crossing_time;        /* [num_last_crossings] */

  /* Pre-allocated KLU/sparse matrix pointer for each slot's z-row diagonal
   * entry J[z_node, z_node] (no y-coupling entry is needed — the crossing
   * time has zero Jacobian sensitivity to V(y_synth) almost everywhere). */
  double **crossing_jac_z;

  /* KLU only: saved real/complex CSC pointers, mirrored from delay_jac_z_csc/
   * cx's pattern. NULL under SPARSE. */
  double **crossing_jac_z_csc;
  double **crossing_jac_z_cx;

  /* Enhancement-364: one time-domain noise generator per Verilog-A noise
   * source (perfectly correlated same-named sources share one, so `noise_owned`
   * marks which pointers this instance actually owns). Allocated lazily on the
   * first noisy transient timepoint; NULL when the circuit has no transient
   * noise, which is the overwhelmingly common case. */
  struct trnoise_state **noise_state;
  char *noise_owned;
  uint32_t noise_nsrc;

  /* Enhancement-7: true once this instance's eval() has been called at
   * least once. Used by OSDIload to set EVAL_FLAG_IS_INITIAL_STEP on
   * exactly the first call, gating Verilog-A `@(initial_step)` blocks.
   * A per-instance, one-shot approximation of the LRM's "fires once per
   * analysis" semantics -- see openvaf/osdi/src/eval.rs. */
  bool has_evaluated;

  /* Enhancement-55: eval-return flags accumulated over ALL Newton iterations
   * of the CURRENT timepoint attempt (reset when a new attempt starts, i.e.
   * on MODEINITJCT/MODEINITPRED/MODEINITTRAN). `eval_flags` above only holds
   * the LAST eval's flags -- an event (cross) that fired on an intermediate
   * iteration would be missed. Used for the deferred $finish/$stop requests
   * (checked at the accepted-point boundary) and the $discontinuity
   * step-rejection in OSDItrunc. */
  uint32_t point_eval_flags;

  /* Enhancement-55: `point_eval_flags` of the last ACCEPTED timepoint, and a
   * one-shot latch marking that the current point already had its
   * discontinuity rejection. Together they make the $discontinuity step
   * rejection EDGE-triggered (once per onset): a model announcing a
   * discontinuity over a whole REGION (every eval while a condition holds,
   * e.g. the E-24 example) must not have every step rejected down to the
   * delta floor. Updated in OSDIaccept. */
  uint32_t prev_point_eval_flags;
  bool discont_retry;
  /* Enhancement-504: latched once an impossible $bound_step has been
     reported for this instance, so the warning names the model once rather
     than on every timepoint. */
  bool boundstep_floored;

  /* Enhancement-351: the global node numbers this instance's INTERNAL nodes
   * were given, so a SECOND DEVsetup() on an already-set-up circuit reuses them
   * instead of allocating a fresh set.
   *
   * `sens` re-invokes every model's DEVsetup() to stamp the perturbation
   * matrix, and requires that doing so allocate no nodes -- it snapshots
   * CKTlastNode around the call and calls controlled_exit() if it moved. Every
   * built-in device satisfies that by guarding its allocation on "not already
   * allocated" (the inductor's `if (here->INDbrEq == 0)`); OSDI had no such
   * guard, so any model with an internal node killed the process.
   *
   * Cleared by OSDIunsetup(), which deletes the nodes -- so a genuine re-setup
   * after teardown allocates afresh, exactly as INDunsetup() zeroes INDbrEq. */
  uint32_t *int_node_ids;   /* [int_node_count], NULL before the first setup */
  uint32_t int_node_count;

  /* Enhancement-417: the node collapse is decided ONCE, in OSDIsetup, and the
   * node mapping, the matrix pointers and Enhancement-416's collapse-owner map
   * are all built from that decision. OSDItemp re-runs setup_instance -- which
   * re-decides the collapse -- but cannot rebuild any of them, so a model whose
   * collapse condition depends on temperature (or on a parameter `alter` moved)
   * silently ends up with a topology the matrix does not implement.
   *
   * Set when the re-decided collapse differs from the one the matrix was built
   * from. Consumers: OSDItemp warns, and cktsens.c refuses to report a
   * sensitivity derived from the mismatched stamp. */
  bool collapse_changed;
  bool collapse_warned;     /* warn once per instance, not once per temperature */

  /* Enhancement-418: `pz` linearizes an absdelay slot as a zero-delay wire,
   * because e^{-s*td} is transcendental -- it has infinitely many roots, while
   * CKTpzFindZeros searches for a finite set, and across pz's own search range
   * (|s| up to 1e35) the exponential overflows. Warn once per instance, not
   * once per pz trial: OSDIpzLoad runs hundreds of times per analysis. */
  bool pz_delay_warned;

} OSDI_ALIGN(MAX_ALIGN) OsdiExtraInstData;

/* Enhancement-7: extra bit in the eval() `flags` input (see
 * OsdiSimInfo.flags / eval_flags convention in osdi_0_4.h), set by
 * OSDIload only on an instance's very first evaluation. Chosen well above
 * the highest flag defined in osdi_0_4.h (ANALYSIS_NODESET = 1<<16) to
 * avoid collision with the core ABI's flag space. */
#define EVAL_FLAG_IS_INITIAL_STEP (1u << 20)

/* Enhancement-53: sibling of EVAL_FLAG_IS_INITIAL_STEP, set by OSDIfinalStep
 * (osdiload.c) on the one dedicated post-analysis evaluation issued after an
 * analysis completes successfully; its results are not loaded into the
 * matrix/RHS. Gates Verilog-A `@(final_step)` blocks. */
#define EVAL_FLAG_IS_FINAL_STEP (1u << 21)

typedef struct OsdiModelData {
  GENmodel gen;
  max_align_t data;
} OsdiModelData;

extern size_t osdi_instance_data_off(const OsdiRegistryEntry *entry);
extern void *osdi_instance_data(const OsdiRegistryEntry *entry,
                                GENinstance *inst);
extern double *osdi_noise_data(const OsdiRegistryEntry *entry,
                                GENinstance *inst);
#ifdef KLU
extern size_t osdi_instance_matrix_ptr_off(const OsdiRegistryEntry *entry);
extern double **osdi_instance_matrix_ptr(const OsdiRegistryEntry *entry,
                                         GENinstance *inst);
#endif
extern OsdiExtraInstData *
osdi_extra_instance_data(const OsdiRegistryEntry *entry, GENinstance *inst);
extern bool *osdi_collapse_snapshot(const OsdiRegistryEntry *entry,
                                    GENinstance *inst);
extern uint32_t *osdi_collapse_owner(const OsdiRegistryEntry *entry,
                                     GENinstance *inst);
extern size_t osdi_model_data_off(void);
extern void *osdi_model_data(GENmodel *model);
extern void *osdi_model_data_from_inst(GENinstance *inst);
extern OsdiRegistryEntry *osdi_reg_entry_model(const GENmodel *model);
extern OsdiRegistryEntry *osdi_reg_entry_inst(const GENinstance *inst);

typedef struct OsdiNgspiceHandle {
  uint32_t kind;
  char *name;
} OsdiNgspiceHandle;

/* values returned by $simparam*/
OsdiSimParas get_simparams(const CKTcircuit *ckt);

typedef void (*osdi_log_ptr)(void *handle, char *msg, uint32_t lvl);
void osdi_log(void *handle_, char *msg, uint32_t lvl);

typedef void (*osdi_log_ptr)(void *handle, char *msg, uint32_t lvl);

double osdi_pnjlim(bool init, bool *icheck, double vnew, double vold, double vt,
                   double vcrit);

double osdi_limvds(bool init, bool *icheck, double vnew, double vold);
double osdi_limitlog(bool init, bool *icheck, double vnew, double vold,
                     double LIM_TOL);
double osdi_fetlim(bool init, bool *icheck, double vnew, double vold,
                   double vto);
/* LRM 9.17.3: pass-through bound to any unknown/unsupported $limit name. */
double osdi_limit_unknown(bool init, bool *icheck, double vnew, double vold);

/* Enhancement-364: transient noise for OSDI devices (osditrnoise.c). */
double osdi_trnoise_ts(CKTcircuit *ckt);
void osdi_trnoise_reset(void);
void osdi_trnoise_free(OsdiExtraInstData *extra);
void osdi_trnoise_stamp(CKTcircuit *ckt, void *inst, void *model,
                        OsdiExtraInstData *extra, const OsdiDescriptor *descr,
                        bool is_tran);

/* LRM 9.4.6 / 9.5.9 deferred output (audit 2026-08-31, sysio fixes).
 *
 * Display tasks (and un-gated file writes inside the compiled model) must not
 * produce output unless the Newton iteration is accepted. The display side is
 * buffered here in ngspice (all of it funnels through osdi_log); the file side
 * is buffered inside each loaded .osdi's runtime, driven through the optional
 * osdi_io_iter_begin/osdi_io_flush hooks that osdiregistry.c resolves at load
 * time. OSDIload announces the start of each Newton iteration (dropping the
 * superseded iteration's output), OSDIaccept and OSDIfinalStep flush, and the
 * sweep analyses flush per converged point. Messages carrying
 * LOG_FLAG_IMMEDIATE (event-gated statements, $debug/$fdebug, severity tasks)
 * bypass the buffer. */
void osdi_display_iter_begin(void);
void osdi_display_flush(void);
void osdi_register_io_hooks(void *lib_handle, void *(*get_sym)(void *, const char *));
void osdi_io_hooks_iter_begin(void);
void osdi_io_hooks_flush(void);
