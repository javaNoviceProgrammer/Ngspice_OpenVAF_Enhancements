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

#include "ngspice/iferrmsg.h"
#include "ngspice/memory.h"
#include "ngspice/ngspice.h"
#include "ngspice/typedefs.h"

#include "ngspice/cktdefs.h"   /* Enhancement-492: CKTvaFatalRaised */
#include "ngspice/osdiitf.h"

/* Enhancement-492: defined here because this file owns the only place a
   Verilog-A $fatal is actually detected. See cktdefs.h. */
int CKTvaFatalRaised = 0;

#include "osdi.h"
#include "osdidefs.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>

/* -----------------------------------------------------------------------
 * absdelay transient stamping helpers
 * -----------------------------------------------------------------------
 *
 * History layout: delay_hist[k][i] = V(y_synth) at CKTtimePoints[i].
 * During Newton iterations CKTtimeIndex = ti is fixed; we keep updating
 * hist[k][ti] with the latest CKTrhsOld value so that at convergence
 * hist[k][ti] holds the true accepted value for the next step.
 */

/* Grow delay_hist rows to hold at least new_cap entries. */
static void absdelay_grow_hist(OsdiExtraInstData *extra, uint32_t n_delays,
                               uint32_t new_cap) {
  for (uint32_t k = 0; k < n_delays; k++) {
    extra->delay_hist[k] =
        TREALLOC(double, extra->delay_hist[k], new_cap);
  }
  extra->delay_hist_cap = new_cap;
}

/* Ensure CKTtimePoints is allocated (if no LTRA device is in the circuit
 * optran.c leaves it NULL).  We allocate it ourselves on the first transient
 * call and let optran.c's nextTime: grow it thereafter.                    */
static void absdelay_ensure_timepoints(CKTcircuit *ckt) {
  if (ckt->CKTtimePoints == NULL) {
    uint32_t cap = (ckt->CKTtimeListSize > 0) ? (uint32_t)ckt->CKTtimeListSize : 256;
    ckt->CKTtimePoints = TMALLOC(double, cap);
    ckt->CKTtimeListSize = (int)cap;
    ckt->CKTtimeIndex = 0;
    ckt->CKTtimePoints[0] = 0.0;
  } else if (ckt->CKTtimeIndex < 0) {
    ckt->CKTtimeIndex = 0;
    ckt->CKTtimePoints[0] = 0.0;
  }
}

/*
 * Lookup the delayed value for slot k, and return the Jacobian alpha
 * (sensitivity of delayed_value w.r.t. V_y_current) via *alpha_out.
 *
 * Uses linear interpolation over accepted timepoints.
 * When t_lookup falls between the last accepted time and CKTtime, the
 * interpolation crosses into the current Newton iteration, giving alpha > 0.
 */
static double absdelay_lookup(const OsdiExtraInstData *extra, uint32_t k,
                              double td, const CKTcircuit *ckt,
                              double V_y_old, double *alpha_out) {
  *alpha_out = 0.0;

  int ti = ckt->CKTtimeIndex;
  if (ti < 0 || ckt->CKTtimePoints == NULL) {
    /* No history yet — pass through */
    return V_y_old;
  }

  double t_lookup = ckt->CKTtime - td;

  /* Clamp to the beginning of history */
  if (t_lookup <= ckt->CKTtimePoints[0]) {
    return extra->delay_hist[k][0];
  }

  double t_last_accepted = ckt->CKTtimePoints[ti];

  if (t_lookup >= ckt->CKTtime && ti >= 0) {
    /* delay <= 0: return current value with full Jacobian sensitivity */
    *alpha_out = 1.0;
    return V_y_old;
  }

  if (t_lookup >= t_last_accepted) {
    /* delay is smaller than current timestep: interpolate between last
     * accepted point and CKTtime (current candidate).               */
    double dt_step = ckt->CKTtime - t_last_accepted;
    double alpha = (dt_step > 0.0)
                       ? (t_lookup - t_last_accepted) / dt_step
                       : 1.0;
    *alpha_out = alpha;
    double hist_last = extra->delay_hist[k][ti];
    return hist_last + alpha * (V_y_old - hist_last);
  }

  /* General case: binary search through accepted timepoints [0 .. ti] */
  int lo = 0, hi = ti;
  while (lo + 1 < hi) {
    int mid = (lo + hi) / 2;
    if (ckt->CKTtimePoints[mid] <= t_lookup)
      lo = mid;
    else
      hi = mid;
  }
  double t0 = ckt->CKTtimePoints[lo];
  double t1 = ckt->CKTtimePoints[hi];
  double v0 = extra->delay_hist[k][lo];
  double v1 = extra->delay_hist[k][hi];
  double dt = t1 - t0;
  if (dt <= 0.0)
    return v0;
  double frac = (t_lookup - t0) / dt;
  return v0 + frac * (v1 - v0);
}

/*
 * Enhancement-532: stamp the synthetic ideal 0 V sources OSDIsetup built for
 * collapse merges the node mapping could not honour (a terminal-terminal
 * short reached through a chain of collapses). Constant, linear, analysis-
 * independent: branch row V(n1) - V(n2) = 0 and the +-1 current columns,
 * with a zero right-hand side -- exactly the vsrc stamp at dc 0.
 */
static void syn_short_stamp(OsdiExtraInstData *extra) {
  for (uint32_t k = 0; k < extra->num_syn_shorts; k++) {
    double **p = extra->syn_short_ptrs + 4 * k;
    *(p[0]) += 1.0;  /* (br, n1) */
    *(p[1]) -= 1.0;  /* (br, n2) */
    *(p[2]) += 1.0;  /* (n1, br) */
    *(p[3]) -= 1.0;  /* (n2, br) */
  }
}

/*
 * DC / TRAN-OP pass-through stamp for absdelay slots.
 * In steady-state absdelay reduces to an ideal wire: V(z) = V(y_synth).
 * Without this the z-row has no matrix entries and the solver reports a
 * singular matrix.
 */
static void absdelay_stamp_dc(void *inst, OsdiExtraInstData *extra,
                               const OsdiRegistryEntry *entry,
                               const OsdiDescriptor *descr) {
  uint32_t n = entry->num_absdelays;
  const OsdiAbsDelayInfo *infos = (const OsdiAbsDelayInfo *)entry->absdelay_infos;
  uint32_t *node_mapping =
      (uint32_t *)(((char *)inst) + descr->node_mapping_offset);

  for (uint32_t k = 0; k < n; k++) {
    /* V(z) - V(y_synth) = 0  →  jac[z,y]+=1, jac[z,z]+=-1, rhs[z]+=0 */
    *(extra->delay_jac_y[k]) += 1.0;
    *(extra->delay_jac_z[k]) += -1.0;
    NG_IGNORE(node_mapping);
  }
}

/*
 * Stamp residual and Jacobian for all absdelay slots of one instance.
 * Called after the standard OSDI load() for each transient step.
 */
static void absdelay_stamp_tran(CKTcircuit *ckt, GENinstance *gen_inst,
                                void *inst, OsdiExtraInstData *extra,
                                const OsdiRegistryEntry *entry,
                                const OsdiDescriptor *descr,
                                bool is_init_tran) {
  uint32_t n = entry->num_absdelays;
  if (n == 0)
    return;

  const OsdiAbsDelayInfo *infos = (const OsdiAbsDelayInfo *)entry->absdelay_infos;
  uint32_t *node_mapping =
      (uint32_t *)(((char *)inst) + descr->node_mapping_offset);

  /* On the first transient call: allocate CKTtimePoints if needed and
   * initialize the history arrays.                                        */
  if (is_init_tran) {
    absdelay_ensure_timepoints(ckt);
    uint32_t cap = (uint32_t)(ckt->CKTtimeListSize > 0
                                  ? (uint32_t)ckt->CKTtimeListSize
                                  : 256) + 64;
    if (extra->delay_hist_cap < cap) {
      absdelay_grow_hist(extra, n, cap);
    }
    /* Seed hist[k][0] with V_y at t=0 -- the CONVERGED OPERATING POINT, not 0.
     *
     * LRM 4.5.7 defines the operator as Output(t) = Input(max(t - td, 0)), so
     * for t < td the output is Input(0): the input's value at time zero. This
     * used to store a literal 0.0, so an absdelay around any non-zero bias
     * reported 0 for the whole first `td` of every transient and then STEPPED
     * to the bias -- a full-swing glitch in a model that was merely sitting at
     * its operating point. (LRM 4.5.15's "no state history prior to t == 0" is
     * exactly what the max(.,0) accommodates; it does not make the value 0.)
     *
     * is_init_tran runs after the operating point has converged, so CKTrhsOld
     * holds it. OSDIaccept() updates hist[k][ti] for ti >= 1 thereafter. The
     * pass-through Jacobian below is unchanged: the first timestep still forces
     * the output to track the input so the matrix is non-singular.          */
    /* LRM 4.5.7 (analog-operators audit): "If maxdelay is not specified,
     * the value of td when the absdelay() is first evaluated shall be used
     * and any future changes to td shall be ignored." This is that first
     * evaluation with a CONVERGED solution behind it (the model-visible
     * IsInitialStep flag still sees the zero initial guess, which is why the
     * latch lives here and not in compiled code -- E-514's own analysis).
     * Latched per transient: a later transient re-latches at its own init. */
    if (extra->delay_td_frozen == NULL && n > 0) {
      extra->delay_td_frozen = TMALLOC(double, n);
    }
    for (uint32_t k = 0; k < n; k++) {
      uint32_t y_mapped = node_mapping[infos[k].y_node];
      extra->delay_hist[k][0] = ckt->CKTrhsOld ? ckt->CKTrhsOld[y_mapped] : 0.0;
      if (extra->delay_td_frozen) {
        double td0 = *((double *)(((char *)inst) + infos[k].td_offset));
        extra->delay_td_frozen[k] = (td0 < 0.0) ? 0.0 : td0;
      }
      *(extra->delay_jac_y[k]) += 1.0;
      *(extra->delay_jac_z[k]) += -1.0;
    }
    return;
  }

  /* Ensure history capacity matches CKTtimeListSize growth */
  uint32_t needed = (uint32_t)(ckt->CKTtimeListSize) + 64;
  if (extra->delay_hist_cap < needed) {
    absdelay_grow_hist(extra, n, needed);
  }

  int ti = ckt->CKTtimeIndex;
  if (ti < 0 || ckt->CKTtimePoints == NULL)
    return;

  for (uint32_t k = 0; k < n; k++) {
    uint32_t y_mapped = node_mapping[infos[k].y_node];
    uint32_t z_mapped = node_mapping[infos[k].z_node];

    /* Read td from OSDI instance data -- or, for a frozen slot (no maxdelay,
     * LRM 4.5.7), the value latched at this transient's MODEINITTRAN. */
    double td;
    if ((infos[k].flags & OSDI_ABSDELAY_TD_FROZEN) && extra->delay_td_frozen) {
      td = extra->delay_td_frozen[k];
    } else {
      td = *((double *)(((char *)inst) + infos[k].td_offset));
      if (td < 0.0)
        td = 0.0;
    }

    double V_y_old = ckt->CKTrhsOld[y_mapped];
    double V_z_old = ckt->CKTrhsOld[z_mapped];

    /* Treat sub-femtosecond delays as zero: stamp as DC pass-through to avoid
     * forcing the timestep below the delay value (which would cause timestep-
     * too-small failures).  Real photonic delays are >> 1 fs. */
    if (td < 1e-15) {
      *(extra->delay_jac_y[k]) += 1.0;
      *(extra->delay_jac_z[k]) += -1.0;
      /* RHS: zero — for V(y_synth) - V(z) = 0 the constant term is 0 */
      NG_IGNORE(V_z_old);
      continue;
    }

    double alpha = 0.0;
    double delayed_val = absdelay_lookup(extra, k, td, ckt, V_y_old, &alpha);

    /* Stamp into pre-allocated matrix entries and RHS.
     * z-row equation: delayed_val - V_z = 0
     *   d/dV_y: alpha   (nonzero only when delay < current timestep)
     *   d/dV_z: -1.0
     * RHS contribution: alpha * V_y_old - delayed_val               */
    *(extra->delay_jac_y[k]) += alpha;
    *(extra->delay_jac_z[k]) += -1.0;
    ckt->CKTrhs[z_mapped] += alpha * V_y_old - delayed_val;

    NG_IGNORE(V_z_old);
  }
}

/*
 * Stamp residual and Jacobian for all last_crossing slots of one instance.
 * Valid in both DC/OP and TRAN modes -- unlike absdelay, no distinction is
 * needed since the crossing-time output has no y-coupling: it is just
 * `V(z) = crossing_time[k]`, an ordinary Dirichlet-style row seeded by
 * whatever last_crossing_accept() has cached (the LRM's negative sentinel until
 * the first qualifying crossing is observed).  Called after the standard OSDI load() for each
 * evaluation, mirroring absdelay_stamp_dc/absdelay_stamp_tran.
 */
static void last_crossing_stamp(void *inst, OsdiExtraInstData *extra,
                                 const OsdiRegistryEntry *entry,
                                 const OsdiDescriptor *descr,
                                 CKTcircuit *ckt, bool is_tran,
                                 bool is_init_tran) {
  uint32_t n = entry->num_last_crossings;
  if (n == 0)
    return;

  /* If NO absdelay is also present in this circuit, ckt->CKTtimePoints /
   * CKTtimeIndex (the shared accepted-timepoint timeline consumed by
   * OSDIaccept) would never get initialized, since that only happens inside
   * absdelay_stamp_tran. Ensure it here too; the call is idempotent (see
   * absdelay_ensure_timepoints). */
  if (is_tran) {
    absdelay_ensure_timepoints(ckt);
  }

  const OsdiLastCrossingInfo *infos =
      (const OsdiLastCrossingInfo *)entry->last_crossing_infos;
  uint32_t *node_mapping =
      (uint32_t *)(((char *)inst) + descr->node_mapping_offset);

  /* This used to say last_crossing "needs no per-instance history seeding on
   * the first transient call". It does, for the same reason absdelay does.
   *
   * crossing_hist[k][0] is the value the FIRST crossing test compares against
   * (`v0` in last_crossing_accept). Left at its allocated 0.0 while the
   * operating point had solved the watched expression to something POSITIVE,
   * the very first accepted point looked like a rising edge from 0 -- so
   * last_crossing reported a crossing at t = 0 that never happened, and the
   * LRM 4.5.10 "negative until it has crossed" sentinel was overwritten before
   * a model could ever read it. Seeding from the converged operating point
   * (CKTrhsOld at MODEINITTRAN) is exactly what absdelay_stamp_tran does for
   * its own history. */
  if (is_init_tran && extra->crossing_hist) {
    uint32_t needed = (uint32_t)(ckt->CKTtimeListSize > 0
                                     ? (uint32_t)ckt->CKTtimeListSize
                                     : 256) + 64;
    if (extra->crossing_hist_cap < needed) {
      for (uint32_t k = 0; k < n; k++) {
        extra->crossing_hist[k] =
            TREALLOC(double, extra->crossing_hist[k], needed);
      }
      extra->crossing_hist_cap = needed;
    }
    for (uint32_t k = 0; k < n; k++) {
      uint32_t y_mapped = node_mapping[infos[k].y_node];
      extra->crossing_hist[k][0] =
          ckt->CKTrhsOld ? ckt->CKTrhsOld[y_mapped] : 0.0;
    }
  }

  for (uint32_t k = 0; k < n; k++) {
    uint32_t z_mapped = node_mapping[infos[k].z_node];
    /* V(z) - crossing_time = 0  ->  jac[z,z] += -1, rhs[z] += -crossing_time */
    *(extra->crossing_jac_z[k]) += -1.0;
    ckt->CKTrhs[z_mapped] += -extra->crossing_time[k];
  }
}

/* Enhancement-394: `scale` joins the list. `.option scale` is applied by each
 * BUILT-IN device inside its own parameter setter (b3par.c and friends call
 * cp_getvar("scale")); nothing scales an OSDI instance parameter, because the
 * OSDI ABI carries no units and ngspice cannot know which parameters are
 * lengths. The Verilog-A way to receive it is $simparam("scale"), which real
 * models do ask for -- the EKV model in this project's own VA_TEST corpus has
 * `SIMPARSCAL $simparam("scale",1.0)` -- and ngspice did not answer, so the
 * model silently used 1.0 while a built-in MOSFET in the same netlist scaled.
 * There is no double-application risk precisely because ngspice never touches
 * an OSDI parameter itself.
 *
 * NOT added: `shrink`, `imax`, `rthresh`. ngspice has no such option, so the
 * honest answer is to leave the model's own $simparam default in force rather
 * than invent a value.
 *
 * Enhancement-399: three MORE of the LRM's standard names are added, and only
 * three -- the ones ngspice can answer truthfully from state it already keeps:
 *
 *   iteration            ckt->CKTstat->STATnumIter, the solver's iteration count
 *   abstime              ckt->CKTtime, the current transient time
 *   simulatorSubversion  0 -- this release carries no subversion
 *
 * `shrink`, `imax`, `imelt` and `rthresh` stay OUT for the reason above: they
 * name options ngspice does not have, and answering with a made-up number is
 * worse than not answering.
 *
 * Why it mattered that these were missing: an unknown name is not a soft miss.
 * `$simparam("iteration")` -- no default argument -- aborts the whole run with
 * OSDI(fatal), so a model ported from another simulator did not degrade, it
 * died. The three added here are exactly the ones where ngspice had the answer
 * all along.
 *
 * Enhancement-434: `temp` joins them, by exactly the same test. ngspice kept
 * `tnom` in this list but not `temp`, though it has had `ckt->CKTtemp` all
 * along -- so `$simparam("temp")`, which is how a model ported from Spectre
 * asks for the simulation temperature, either returned the caller's default
 * (silently the wrong temperature) or, with no default, killed the run with
 * OSDI(fatal). It is returned in CELSIUS, matching `tnom` beside it.
 *
 * `temperature` is deliberately NOT added: no simulator supplies that spelling,
 * and the LRM's own way to ask is `$temperature`, which already works. Likewise
 * `timestep`, `maxstep` and `freq` stay out -- ngspice has values that resemble
 * them, but they are not names any simulator answers, so supplying them would
 * be inventing an interface rather than completing one. */
#define NUM_SIM_PARAMS 15
char *sim_params[NUM_SIM_PARAMS + 1] = {
    "iniLim", "gmin", "gdev", "tnom",
    "simulatorVersion", "sourceScaleFactor",
    "epsmin", "reltol", "vntol", "abstol", "scale",
    "iteration", "abstime", "simulatorSubversion",
    "temp",
    NULL};
/* Enhancement-25: string simulator parameters returned by $simparam$str.
 * "analysis_name" mirrors the analysis() naming ("dc"/"ac"/"tran"/"noise");
 * "simulator" is constant. The values array is filled per call in get_simparams.
 *
 * Kernel audit, LRM Table 9-28: two more of the table's mandatory names are
 * served -- the ones ngspice can answer truthfully without new plumbing:
 *
 *   analysis_type   ngspice gives analyses no user-chosen names distinct from
 *                   their type, so the honest answer is the same
 *                   "dc"/"ac"/"tran"/"noise" string analysis_name carries
 *   cwd             the working directory, refreshed per query (a .control
 *                   `cd` can change it between runs)
 *
 * `module`, `instance` and `path` stay OUT: the simparam channel is filled
 * per circuit, with no instance identity in reach, and inventing one would be
 * worse than the honest compile-time warning + run-time fatal the unknown-name
 * path already gives. Documented in the compliance doc. */
#define NUM_SIM_PARAMS_STR 4
char *sim_params_str[NUM_SIM_PARAMS_STR + 1] =
    {"analysis_name", "simulator", "analysis_type", "cwd", NULL};
char *sim_param_vals_str[NUM_SIM_PARAMS_STR] = {"dc", "ngspice", "dc", ""};

/* kernel audit: $simparam$str("cwd"), LRM Table 9-28. */
static const char *osdi_cwd(void) {
  static char buf[1024];
  buf[0] = '\0';
#ifdef HAVE_GETCWD
  if (!getcwd(buf, sizeof(buf)))
    buf[0] = '\0';
#endif
  return buf;
}

double sim_param_vals[NUM_SIM_PARAMS] = {0};

/* Enhancement-215: command-line plusargs (`+name[=value]`) served through the
 * simparam channel. main.c registers each `+`-arg at startup; a compiled model's
 * `$test$plusargs("name")` / `$value$plusargs("name=%fmt", var)` look them up as
 * namespaced simparams -- numeric "$test$plusargs$<name>" = 1.0 (presence) and
 * string "$value$plusargs$<name>" = "<value>". The keys are interned once at
 * registration; get_simparams splices them onto the base arrays on first use, so
 * a run with no plusargs pays nothing. */
static char **pa_test_key = NULL;  /* "$test$plusargs$<name>"   numeric: present 1.0        */
static char **pa_valset_key = NULL;/* "$valset$plusargs$<name>" numeric: given as name=value */
static char **pa_valnum_key = NULL;/* "$valnum$plusargs$<name>" numeric: value as double     */
static char **pa_val_key = NULL;   /* "$value$plusargs$<name>"  string:  value as text       */
static char **pa_value = NULL;     /* "<value>" ("" when the plusarg has none)               */
static double *pa_valset = NULL;   /* 1.0 iff the plusarg was `name=value`, else 0.0         */
static double *pa_valnum = NULL;   /* strtod(value) (0 when non-numeric or absent)           */
static int pa_n = 0, pa_cap = 0;

void ngspice_register_plusarg(const char *arg) {
  /* `arg` is the plusarg without its leading '+': "name" or "name=value".
   * $test$plusargs matches either form; $value$plusargs matches only name=value
   * (hence the separate $valset presence flag). */
  if (arg == NULL || *arg == '\0')
    return;
  if (pa_n >= pa_cap) {
    pa_cap = pa_cap ? 2 * pa_cap : 8;
    pa_test_key = TREALLOC(char *, pa_test_key, pa_cap);
    pa_valset_key = TREALLOC(char *, pa_valset_key, pa_cap);
    pa_valnum_key = TREALLOC(char *, pa_valnum_key, pa_cap);
    pa_val_key = TREALLOC(char *, pa_val_key, pa_cap);
    pa_value = TREALLOC(char *, pa_value, pa_cap);
    pa_valset = TREALLOC(double, pa_valset, pa_cap);
    pa_valnum = TREALLOC(double, pa_valnum, pa_cap);
  }
  const char *eq = strchr(arg, '=');
  char *name = eq ? copy_substring(arg, eq) : copy(arg);
  pa_test_key[pa_n] = tprintf("$test$plusargs$%s", name);
  pa_valset_key[pa_n] = tprintf("$valset$plusargs$%s", name);
  pa_valnum_key[pa_n] = tprintf("$valnum$plusargs$%s", name);
  pa_val_key[pa_n] = tprintf("$value$plusargs$%s", name);
  pa_value[pa_n] = eq ? copy(eq + 1) : copy("");
  pa_valset[pa_n] = eq ? 1.0 : 0.0;
  pa_valnum[pa_n] = eq ? strtod(eq + 1, NULL) : 0.0;
  tfree(name);
  pa_n++;
}

/* Base + plusarg simparam arrays, built once on first get_simparams call when
 * plusargs are present. The numeric values [0..NUM_SIM_PARAMS) are refreshed per
 * call; the plusarg tail (presence 1.0 / value string) is constant. */
static char **ext_names = NULL, **ext_names_str = NULL, **ext_vals_str = NULL;
static double *ext_vals = NULL;
static int ext_built = 0;

static void build_plusarg_arrays(void) {
  int i;
  /* numeric channel: base params, then three entries per plusarg -- presence
   * ($test$plusargs$name = 1), the name=value flag ($valset$plusargs$name) and
   * the value as a number ($valnum$plusargs$name). */
  ext_names = TMALLOC(char *, NUM_SIM_PARAMS + 3 * pa_n + 1);
  ext_vals = TMALLOC(double, NUM_SIM_PARAMS + 3 * pa_n);
  for (i = 0; i < NUM_SIM_PARAMS; i++)
    ext_names[i] = sim_params[i];
  for (i = 0; i < pa_n; i++) {
    ext_names[NUM_SIM_PARAMS + 3 * i] = pa_test_key[i];
    ext_vals[NUM_SIM_PARAMS + 3 * i] = 1.0;
    ext_names[NUM_SIM_PARAMS + 3 * i + 1] = pa_valset_key[i];
    ext_vals[NUM_SIM_PARAMS + 3 * i + 1] = pa_valset[i];
    ext_names[NUM_SIM_PARAMS + 3 * i + 2] = pa_valnum_key[i];
    ext_vals[NUM_SIM_PARAMS + 3 * i + 2] = pa_valnum[i];
  }
  ext_names[NUM_SIM_PARAMS + 3 * pa_n] = NULL;

  ext_names_str = TMALLOC(char *, NUM_SIM_PARAMS_STR + pa_n + 1);
  ext_vals_str = TMALLOC(char *, NUM_SIM_PARAMS_STR + pa_n);
  for (i = 0; i < NUM_SIM_PARAMS_STR; i++) {
    ext_names_str[i] = sim_params_str[i];
    ext_vals_str[i] = sim_param_vals_str[i];
  }
  for (i = 0; i < pa_n; i++) {
    ext_names_str[NUM_SIM_PARAMS_STR + i] = pa_val_key[i];
    ext_vals_str[NUM_SIM_PARAMS_STR + i] = pa_value[i];
  }
  ext_names_str[NUM_SIM_PARAMS_STR + pa_n] = NULL;
  ext_built = 1;
}

/* Enhancement-394: the single source of truth for "which analysis is running",
 * mirroring the ANALYSIS_* flag derivation in OSDIload term for term so that
 * $simparam$str("analysis_name") and analysis() can never disagree.
 *
 * The order matters and matches the flags: a noise job's operating point is
 * noise, an AC job's operating point is ac (Enhancement-53), and only then do
 * the plain CKTmode bits decide. MODEINITSMSIG is deliberately NOT treated as
 * `ac`: it is the small-signal pass that follows a DC solution, and a plain
 * `op` is not an AC analysis -- `finalstep_examples` pins that ac-qualified
 * events stay silent there. */
static const char *osdi_analysis_name(const CKTcircuit *ckt) {
  bool is_ac = ckt->CKTmode & MODEAC;
  bool is_dc = ckt->CKTmode & (MODEDCOP | MODEDCTRANCURVE);
  bool is_tran = ckt->CKTmode & (MODETRAN | MODETRANOP | MODEINITTRAN);
  const char *job = NULL;

  if (ckt->CKTcurJob && ft_sim->analyses[ckt->CKTcurJob->JOBtype])
    job = ft_sim->analyses[ckt->CKTcurJob->JOBtype]->name;

  if (ckt->CKTmode & MODEACNOISE)
    return "noise";
  if (is_dc && job && !strcmp(job, "NOISE"))
    return "noise";
  if (is_dc && job && !strcmp(job, "AC"))
    return "ac";
  if (is_ac)
    return "ac";
  if (is_tran)
    return "tran";
  return "dc";
}

/* values returned by $simparam*/
OsdiSimParas get_simparams(const CKTcircuit *ckt) {
  double simulatorVersion = strtod(PACKAGE_VERSION, NULL);
  double gdev = ckt->CKTgmin;
  double sourceScaleFactor = ckt->CKTsrcFact;
  double gmin = ((ckt->CKTgmin) > (ckt->CKTdiagGmin)) ? (ckt->CKTgmin)
                                                      : (ckt->CKTdiagGmin);
  double initializeLimiting = (ckt->CKTmode & MODEINITJCT) ? 1 : 0;

  double geom_scale;
  if (!cp_getvar("scale", CP_REAL, &geom_scale, 0))
    geom_scale = 1.0;

  double sim_param_vals_[NUM_SIM_PARAMS] = {
      // Verilog-A tnom is in degrees Celsius
      initializeLimiting, gmin, gdev, ckt->CKTnomTemp-CONSTCtoK, simulatorVersion, sourceScaleFactor, 
      ckt->CKTepsmin, ckt->CKTreltol, ckt->CKTvoltTol, ckt->CKTabstol, geom_scale,
      /* Enhancement-399 */
      (ckt->CKTstat != NULL) ? (double)ckt->CKTstat->STATnumIter : 0.0,
      /* Enhancement-434: abstime is a TIME, and `ckt->CKTtime` only holds one
       * during a transient. `.dc` reuses the same field as its sweep abscissa,
       * so this handed the model the swept VOLTAGE as though it were a time
       * (`dc V1 0 5 1` -> abstime 5.0). Outside a transient there is no
       * simulation time, and 0.0 is the honest answer. */
      (ckt->CKTmode & MODETRAN) ? ckt->CKTtime : 0.0,
      0.0,
      /* Enhancement-434: temp, in Celsius like tnom above it */
      ckt->CKTtemp - CONSTCtoK };
  memcpy(&sim_param_vals, &sim_param_vals_, sizeof(double) * NUM_SIM_PARAMS);

  /* Enhancement-25: current analysis name for $simparam$str("analysis_name"),
   * derived from CKTmode with the same convention as analysis().
   *
   * Enhancement-394: it was NOT the same convention any more, and the two
   * channels contradicted each other inside a single model evaluation.
   * Enhancement-53 taught the ANALYSIS_* flags to consult the RUNNING JOB
   * (`CKTcurJob`) so that an AC/noise job's operating-point phase reports
   * `ac`/`noise`, because CKTmode alone cannot tell that phase apart from a
   * standalone op. This string was left on the CKTmode-only derivation, so:
   *
   *   plain `op`      -> name="ac" while analysis("ac")=0, analysis("dc")=1
   *                      (MODEINITSMSIG is set by the small-signal pass that
   *                       follows a DC op, and it is matched below)
   *   AC job's op     -> name="dc" while analysis("ac")=1
   *
   * A model that gates behaviour on the string therefore disagreed with one
   * gating on analysis(). Both now come from `osdi_analysis_name`, which is
   * built from the SAME `is_*` booleans and the same job consultation the
   * flags use, so `name=="ac"` implies `analysis("ac")` and vice versa.
   *
   * A single name cannot express a phase that carries two flags (an AC job's
   * op is both ANALYSIS_DC and ANALYSIS_AC); it reports the owning analysis,
   * which is what E-53 established and what the LRM asks for. */
  const char *analysis_name = osdi_analysis_name(ckt);
  sim_param_vals_str[0] = (char *)analysis_name;
  /* kernel audit, Table 9-28: type == the same derivation here (see the
   * declaration comment), and the cwd is refreshed per query */
  sim_param_vals_str[2] = (char *)analysis_name;
  sim_param_vals_str[3] = (char *)osdi_cwd();

  /* Enhancement-215: with command-line plusargs present, return the extended
   * arrays (base params + the namespaced plusarg entries). The base numeric
   * values were just computed above into sim_param_vals; copy them into the
   * extended array's head and refresh the analysis name. */
  if (pa_n > 0) {
    int i;
    if (!ext_built)
      build_plusarg_arrays();
    for (i = 0; i < NUM_SIM_PARAMS; i++)
      ext_vals[i] = sim_param_vals[i];
    ext_vals_str[0] = (char *)analysis_name;
    ext_vals_str[2] = (char *)analysis_name;
    ext_vals_str[3] = sim_param_vals_str[3];
    OsdiSimParas ext_params_ = {.names = ext_names,
                                .vals = ext_vals,
                                .names_str = ext_names_str,
                                .vals_str = ext_vals_str};
    return ext_params_;
  }

  OsdiSimParas sim_params_ = {.names = sim_params,
                              .vals = (double *)&sim_param_vals,
                              .names_str = sim_params_str,
                              .vals_str = sim_param_vals_str};
  return sim_params_;
}

static void eval(const OsdiDescriptor *descr, const GENinstance *gen_inst,
                 void *inst, OsdiExtraInstData *extra_inst_data,
                 const void *model, const OsdiSimInfo *sim_info) {

  OsdiNgspiceHandle handle =
      (OsdiNgspiceHandle){.kind = 3, .name = gen_inst->GENname};
  /* TODO initial conditions? */
  extra_inst_data->eval_flags = descr->eval(&handle, inst, model, sim_info);

  /* Enhancement-476: this is the ONE funnel every evaluation passes through
   * (the three load sites and OSDIfinalStep all call it), so it is the only
   * place that has to record that the instance's operating-point variables
   * now hold computed values.
   *
   * Gated on $fatal because an evaluation that raised it was abandoned
   * part-way: `$simparam("GMIN")` kills the run, and the opvars assigned
   * before that line would otherwise read back as though the analysis had
   * succeeded. Each OpenMP task writes only its own instance's field. */
  if (!(extra_inst_data->eval_flags & EVAL_RET_FLAG_FATAL)) {
    extra_inst_data->opvars_valid = true;
  }
}

static void load(CKTcircuit *ckt, const GENinstance *gen_inst, void *model,
                 void *inst, OsdiExtraInstData *extra_inst_data, bool is_tran,
                 bool is_init_tran, const OsdiDescriptor *descr) {

  NG_IGNORE(extra_inst_data);

  double dump;
  if (is_tran) {
    /* load dc matrix and capacitances (charge derivative multiplied with
     * CKTag[0]) */
    descr->load_jacobian_tran(inst, model, ckt->CKTag[0]);

    /* load static rhs and dynamic linearized rhs (SUM Vb * dIa/dVb)*/
    descr->load_spice_rhs_tran(inst, model, ckt->CKTrhs, ckt->CKTrhsOld,
                               ckt->CKTag[0]);

    uint32_t *node_mapping =
        (uint32_t *)(((char *)inst) + descr->node_mapping_offset);

    /* use numeric integration to obtain the remainer of the RHS*/
    int state = gen_inst->GENstate + (int)descr->num_states;
    for (uint32_t i = 0; i < descr->num_nodes; i++) {
      if (descr->nodes[i].react_residual_off != UINT32_MAX) {

        double residual_react =
            *((double *)(((char *)inst) + descr->nodes[i].react_residual_off));

        /* store charges in state vector*/
        ckt->CKTstate0[state] = residual_react;
        if (is_init_tran) {
          ckt->CKTstate1[state] = residual_react;
        }

        /* we only care about the numeric integration itself not ceq/geq
        because those are already calculated by load_jacobian_tran and
        load_spice_rhs_tran*/
        NIintegrate(ckt, &dump, &dump, 0, state);

        /* add the numeric derivative to the rhs */
        ckt->CKTrhs[node_mapping[i]] -= ckt->CKTstate0[state + 1];

        if (is_init_tran) {
          ckt->CKTstate1[state + 1] = ckt->CKTstate0[state + 1];
        }

        state += 2;
      }
    }
  } else {
    /* copy internal derivatives into global matrix */
    descr->load_jacobian_resist(inst, model);

    /* calculate spice RHS from internal currents and store into global RHS
     */
    descr->load_spice_rhs_dc(inst, model, ckt->CKTrhs, ckt->CKTrhsOld);
  }
}

/* LRM 9.4.6/9.5.9: a new Newton iteration's output supersedes the previous,
 * unaccepted iteration's. Detected per (circuit, iteration-counter) pair; the
 * counter alone would go stale across a re-run of the same circuit. */
static void osdi_note_iteration(CKTcircuit *ckt) {
  /* STATnumIter is only bulk-updated when NIiter returns, so it cannot tell
   * the iterations of one solve apart. NIiter swaps CKTrhs/CKTrhsOld once per
   * iteration, so the CKTrhsOld pointer alternates -- adjacent iterations
   * always differ in the composite key below (and solves/points differ in
   * time, mode, or the iteration total). */
  static CKTcircuit *last_ckt;
  static int last_iter = -1;
  static double *last_rhs_old;
  static double last_time = -1.0;
  static long last_mode = -1;
  int it = (ckt->CKTstat != NULL) ? ckt->CKTstat->STATnumIter : -1;
  if (ckt != last_ckt || it != last_iter || ckt->CKTrhsOld != last_rhs_old ||
      ckt->CKTtime != last_time || (long)ckt->CKTmode != last_mode) {
    last_ckt = ckt;
    last_iter = it;
    last_rhs_old = ckt->CKTrhsOld;
    last_time = ckt->CKTtime;
    last_mode = (long)ckt->CKTmode;
    osdi_display_iter_begin();
    osdi_io_hooks_iter_begin();
  }
}

/* Flush the just-converged/accepted point's deferred display and file output.
 * Called from OSDIaccept (transient points), OSDIfinalStep (analysis ends),
 * and the sweep analyses (per swept point). */
extern void OSDIpendingFlush(CKTcircuit *ckt) {
  NG_IGNORE(ckt);
  osdi_display_flush();
  osdi_io_hooks_flush();
}

extern int OSDIload(GENmodel *inModel, CKTcircuit *ckt) {
  GENmodel *gen_model;
  GENinstance *gen_inst;

  osdi_note_iteration(ckt);

  bool is_init_smsig = ckt->CKTmode & MODEINITSMSIG;
  bool is_dc = ckt->CKTmode & (MODEDCOP | MODEDCTRANCURVE);
  bool is_ac = ckt->CKTmode & (MODEAC | MODEINITSMSIG);
  bool is_tran = ckt->CKTmode & (MODETRAN);
  bool is_tran_op = ckt->CKTmode & (MODETRANOP);
  bool is_init_tran = ckt->CKTmode & MODEINITTRAN;
  bool is_init_junc = ckt->CKTmode & MODEINITJCT;

  OsdiSimInfo sim_info = {
      .paras = get_simparams(ckt),
      .abstime = is_tran ? ckt->CKTtime : 0.0,
      .prev_solve = ckt->CKTrhsOld,
      .prev_state = ckt->CKTstates[0],
      .next_state = ckt->CKTstates[0],
      .flags = CALC_RESIST_JACOBIAN,
  };

  sim_info.flags |= CALC_OP;

  if (is_dc) {
    sim_info.flags |= ANALYSIS_DC | ANALYSIS_STATIC;
  }

  if (!is_init_smsig) {
    sim_info.flags |= CALC_RESIST_RESIDUAL | ENABLE_LIM | CALC_RESIST_LIM_RHS;
  }

  if (is_tran) {
    sim_info.flags |= CALC_REACT_JACOBIAN | CALC_REACT_RESIDUAL |
                      CALC_REACT_LIM_RHS | ANALYSIS_TRAN;
  }

  if (is_tran_op) {
    /* Analysis-noise audit, LRM Table 4-22 (TRAN OP column): during the
     * operating point that precedes a transient, analysis("ic") and
     * analysis("static") shall be 1 (with "tran" 1 and "dc" 0) -- this is
     * what makes the LRM 4.6.1 idiom
     *   if (analysis("ic")) V(cap) <+ v0; else I(cap) <+ ddt(C*V(cap));
     * apply its initial condition during the tran op. The bits used to ride
     * MODEINITTRAN instead, which ngspice raises at the FIRST ACCEPTED
     * TIMESTEP (t > 0): 0 exactly where the LRM requires 1, and the IC
     * forced mid-transient at the first step. */
    sim_info.flags |= ANALYSIS_TRAN | ANALYSIS_IC | ANALYSIS_STATIC;
  }

  if (is_ac) {
    /* Enhancement-394: the reactive Jacobian IS needed during MODEINITSMSIG --
     * that pass computes the small-signal capacitances after a DC solution --
     * but ANALYSIS_AC is a NAME, and a plain `op` is not an AC analysis. The
     * two were set together, so during a plain `op` a model saw
     * analysis("ac") true while OSDIfinalStep (MODEAC only) saw it false, and
     * $simparam$str("analysis_name") disagreed with whichever it was asked
     * beside. The name bit now follows MODEAC, plus Enhancement-53's job
     * consultation below for an AC/noise job's operating-point phase; the
     * `finalstep_examples` suite pins that ac-qualified events stay silent in
     * a plain `op`, which is the behaviour this preserves. */
    sim_info.flags |= CALC_REACT_JACOBIAN;
  }
  if ((ckt->CKTmode & MODEAC) && !(ckt->CKTmode & MODEACNOISE)) {
    /* LRM audit (events): LRM Table 4-22 says analysis("ac") is FALSE for
     * every point of a NOISE analysis (its own row carries the "noise"
     * name), and Table 5-1 gives ac-qualified step events 0 there -- but a
     * noise data point runs with MODEAC|MODEACNOISE set, so the bare MODEAC
     * test raised ANALYSIS_AC through a whole .noise run. */
    sim_info.flags |= ANALYSIS_AC;
  }

  /* (Analysis-noise audit: MODEINITTRAN used to raise ANALYSIS_IC and
   * ANALYSIS_STATIC here -- a t > 0 transient evaluation, exactly where
   * Table 4-22 has both at 0. The bits belong to the MODETRANOP phase
   * above.) */

  if (is_init_junc) {
    sim_info.flags |= INIT_LIM;
  }

  /* Analysis-noise audit, LRM 4.6.2 / Table 4-22: analysis("nodeset") is
   * true during the phase of an equilibrium calculation in which the deck's
   * .nodeset values are enforced. ngspice holds them exactly while CKTmode
   * carries MODEINITJCT/MODEINITFIX (cktload.c's nsGiven stamping), and
   * only when the deck supplied any (CKThadNodeset). The ANALYSIS_NODESET
   * flag was defined but never set anywhere. */
  if (ckt->CKThadNodeset && (ckt->CKTmode & (MODEINITJCT | MODEINITFIX))) {
    sim_info.flags |= ANALYSIS_NODESET;
  }

  if (ckt->CKTmode & MODEACNOISE) {
    sim_info.flags |= ANALYSIS_NOISE;
  }
  sim_info.flags |= CALC_NOISE;

  /* Enhancement-53: the initial operating point of an AC/noise job belongs
   * to that analysis (LRM 4.6.1: analysis("ac") holds through the whole AC
   * analysis, mirroring the existing MODETRANOP -> ANALYSIS_TRAN mapping
   * above). CKTmode alone cannot distinguish an AC job's op phase from a
   * standalone op, so consult the running job's type. Only the ANALYSIS_*
   * name bit is added -- NOT the reactive CALC_* bits is_ac carries, which
   * would wrongly enable ddt/integration during the op. This makes
   * `@(initial_step("ac"))` (whose one-shot fires at the op's first eval)
   * and `analysis("ac")` behave per the LRM in AC/noise runs. */
  if (is_dc && ckt->CKTcurJob && ft_sim->analyses[ckt->CKTcurJob->JOBtype]) {
    const char *job_name = ft_sim->analyses[ckt->CKTcurJob->JOBtype]->name;
    if (strcmp(job_name, "AC") == 0) {
      sim_info.flags |= ANALYSIS_AC;
    } else if (strcmp(job_name, "NOISE") == 0) {
      sim_info.flags |= ANALYSIS_NOISE;
    }
    /* LRM audit (events): the op phase of an AC/NOISE job BELONGS to that
     * analysis and is not a DC analysis. LRM Table 4-22's "dc" row is 0 in
     * the AC-OP and NOISE-OP columns (only "static" stays 1 there), and
     * Table 5-1 gives initial_step("dc") 0 for every AC and NOISE point --
     * yet the phase carried ANALYSIS_DC from its MODEDCOP bit, so both
     * analysis("dc") and @(initial_step("dc")) answered as though a .op were
     * running. The owning-analysis name replaces the DC bit rather than
     * joining it; ANALYSIS_STATIC (set above) is what "an equilibrium point
     * calculation" keeps. */
    if (sim_info.flags & (ANALYSIS_AC | ANALYSIS_NOISE)) {
      sim_info.flags &= ~(uint32_t)ANALYSIS_DC;
    }
  }

  OsdiRegistryEntry *entry = osdi_reg_entry_model(inModel);
  const OsdiDescriptor *descr = entry->descriptor;
  uint32_t eval_flags = 0;

#ifdef USE_OMP
  int ret = OK;

  /* use openmp 3.0 tasks to parallelize linked list transveral */
#pragma omp parallel
#pragma omp single
  {
    for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
      void *model = osdi_model_data(gen_model);

      for (gen_inst = gen_model->GENinstances; gen_inst;
           gen_inst = gen_inst->GENnextInstance) {

        void *inst = osdi_instance_data(entry, gen_inst);

        OsdiExtraInstData *extra_inst_data =
            osdi_extra_instance_data(entry, gen_inst);

#pragma omp task firstprivate(gen_inst, inst, extra_inst_data, model)
        {
          /* OSDI-layer audit: mirror the serial branch's Enhancement-7
           * gating. This task used to call eval() with the shared sim_info
           * and never set EVAL_FLAG_IS_INITIAL_STEP or has_evaluated, so an
           * ngspice built with --enable-openmp never fired @(initial_step)
           * in any OSDI device. A task-local OsdiSimInfo keeps the flag
           * per instance and race-free (one task per instance). */
          OsdiSimInfo task_info = sim_info;
          if (!extra_inst_data->has_evaluated) {
            task_info.flags |= EVAL_FLAG_IS_INITIAL_STEP;
            extra_inst_data->has_evaluated = true;
          }
          eval(descr, gen_inst, inst, extra_inst_data, model, &task_info);
        }
      }
    }
  }

  /* init small signal analysis does not require loading values into
   * matrix/rhs*/
  if (is_init_smsig) {
    return ret;
  }

  for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
    void *model = osdi_model_data(gen_model);

    for (gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);
      OsdiExtraInstData *extra_inst_data =
          osdi_extra_instance_data(entry, gen_inst);
      load(ckt, gen_inst, model, inst, extra_inst_data, is_tran, is_init_tran,
           descr);
      if (is_tran) {
        absdelay_stamp_tran(ckt, gen_inst, inst, extra_inst_data, entry,
                            descr, is_init_tran);
      } else if (entry->num_absdelays > 0) {
        absdelay_stamp_dc(inst, extra_inst_data, entry, descr);
      }
      last_crossing_stamp(inst, extra_inst_data, entry, descr, ckt, is_tran,
                          is_init_tran);
      /* Enhancement-532: chained terminal-terminal collapse shorts */
      syn_short_stamp(extra_inst_data);
      /* Enhancement-364: inject Verilog-A noise sources into the transient
         right-hand side. No-op unless the circuit has transient noise. */
      osdi_trnoise_stamp(ckt, inst, model, extra_inst_data, descr, is_tran);
      /* Enhancement-55: accumulate this timepoint attempt's flags (an
         event may fire on an intermediate Newton iteration only) */
      if (ckt->CKTmode & (MODEINITJCT | MODEINITPRED | MODEINITTRAN)) {
        extra_inst_data->point_eval_flags = extra_inst_data->eval_flags;
      } else {
        extra_inst_data->point_eval_flags |= extra_inst_data->eval_flags;
      }
      eval_flags |= extra_inst_data->eval_flags;
    }
  }
#else
  for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
    void *model = osdi_model_data(gen_model);

    for (gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);

      OsdiExtraInstData *extra_inst_data =
          osdi_extra_instance_data(entry, gen_inst);

      /* Enhancement-7: set EVAL_FLAG_IS_INITIAL_STEP on exactly this
       * instance's first evaluation, gating `@(initial_step)`. sim_info is
       * shared across all instances in this sequential (non-OMP) loop, so
       * the bit is added just for this call and cleared right after. */
      if (!extra_inst_data->has_evaluated) {
        sim_info.flags |= EVAL_FLAG_IS_INITIAL_STEP;
        eval(descr, gen_inst, inst, extra_inst_data, model, &sim_info);
        sim_info.flags &= ~EVAL_FLAG_IS_INITIAL_STEP;
        extra_inst_data->has_evaluated = true;
      } else {
        eval(descr, gen_inst, inst, extra_inst_data, model, &sim_info);
      }

      /* init small signal analysis does not require loading values into
       * matrix/rhs*/
      if (!is_init_smsig) {
        load(ckt, gen_inst, model, inst, extra_inst_data, is_tran, is_init_tran,
             descr);
        if (is_tran) {
          absdelay_stamp_tran(ckt, gen_inst, inst, extra_inst_data, entry,
                              descr, is_init_tran);
        } else if (entry->num_absdelays > 0) {
          absdelay_stamp_dc(inst, extra_inst_data, entry, descr);
        }
        last_crossing_stamp(inst, extra_inst_data, entry, descr, ckt, is_tran,
                          is_init_tran);
        /* Enhancement-532: chained terminal-terminal collapse shorts */
        syn_short_stamp(extra_inst_data);
        /* Enhancement-364: inject Verilog-A noise sources into the transient
           right-hand side. No-op unless the circuit has transient noise. */
        osdi_trnoise_stamp(ckt, inst, model, extra_inst_data, descr, is_tran);
        /* Enhancement-55: accumulate this timepoint attempt's flags (an
           event may fire on an intermediate Newton iteration only) */
        if (ckt->CKTmode & (MODEINITJCT | MODEINITPRED | MODEINITTRAN)) {
          extra_inst_data->point_eval_flags = extra_inst_data->eval_flags;
        } else {
          extra_inst_data->point_eval_flags |= extra_inst_data->eval_flags;
        }
        eval_flags |= extra_inst_data->eval_flags;
      }
    }
  }
#endif

  /* call to $fatal in Verilog-A abort simulation!*/
  if (eval_flags & EVAL_RET_FLAG_FATAL) {
    /* Enhancement-492: record that it was THIS -- a device actually raising
       $fatal -- and not one of E_PANIC's other producers. CKTop reports the
       abort, and its message names Verilog-A; without this it named Verilog-A
       for any E_PANIC that reached it, including decks with no Verilog-A device
       in them at all. */
    CKTvaFatalRaised = 1;
    return E_PANIC;
  }

  if (eval_flags & EVAL_RET_FLAG_LIM) {
    ckt->CKTnoncon++;
    ckt->CKTtroubleElt = gen_inst;
  }

  /* Enhancement-55: $stop/$finish are DEFERRED to the accepted-point
   * boundary (OSDIpendingRequests below, checked by the analyses). Returning
   * E_PAUSE here, mid-Newton-iteration, broke timestep control (the "error"
   * made the integrator reject and grind the step down). */

  return OK;
}

/* Enhancement-55: report deferred $finish/$stop requests latched during the
 * current timepoint attempt's evaluations. The analyses call this once a
 * point is ACCEPTED and act between points: $finish ends the analysis
 * cleanly (after firing @(final_step)), $stop pauses resumably. */
int OSDIpendingRequests(CKTcircuit *ckt) {
  int req = 0;

  for (int type = 0; type < ft_sim->numDevices; type++) {
    if (!ft_sim->devices[type] || !ft_sim->devices[type]->registry_entry ||
        !ckt->CKThead[type]) {
      continue;
    }

    OsdiRegistryEntry *entry = osdi_reg_entry_model(ckt->CKThead[type]);

    for (GENmodel *gen_model = ckt->CKThead[type]; gen_model;
         gen_model = gen_model->GENnextModel) {
      for (GENinstance *gen_inst = gen_model->GENinstances; gen_inst;
           gen_inst = gen_inst->GENnextInstance) {
        OsdiExtraInstData *extra_inst_data =
            osdi_extra_instance_data(entry, gen_inst);
        if (extra_inst_data->point_eval_flags & EVAL_RET_FLAG_FINISH) {
          req |= OSDI_REQ_FINISH;
        }
        if (extra_inst_data->point_eval_flags & EVAL_RET_FLAG_STOP) {
          req |= OSDI_REQ_STOP;
        }
      }
    }
  }

  return req;
}

/* Enhancement-53: fire Verilog-A `@(final_step)` blocks (LRM 5.10.2: the
 * event is active during the solution of the last point of an analysis).
 *
 * Called by the analyses (dctran.c, dcop.c, dctrcurv.c, acan.c) once they
 * complete successfully. Issues one dedicated eval() per OSDI instance with
 * EVAL_FLAG_IS_FINAL_STEP set, computed at the converged final solution
 * (CKTrhsOld). The results are deliberately NOT loaded into the matrix/RHS --
 * the analysis is over; the call exists so that `@(final_step)` bodies
 * ($strobe/$fdisplay logging, cleanup assignments, ...) run exactly once,
 * the symmetric counterpart of OSDIload's one-shot
 * EVAL_FLAG_IS_INITIAL_STEP. The ANALYSIS_* flags are set from CKTmode with
 * OSDIload's mapping so that phase-qualified events
 * (`@(final_step("tran"))`) match via the stdlib analysis() callback. */
int OSDIfinalStep(CKTcircuit *ckt) {
  /* The analysis just completed: whatever the final converged iteration
   * deferred belongs to an accepted solution -- flush it before the
   * final_step evaluations produce their own (immediate-tagged) output. */
  OSDIpendingFlush(ckt);
  bool is_tran = ckt->CKTmode & MODETRAN;
  /* Enhancement-412: see the snapshot below. AC and NOISE end on a
   * small-signal solution, so this evaluation must not be allowed to leave its
   * results in the instance. */
  bool preserve_op = (ckt->CKTmode & (MODEAC | MODEACNOISE)) != 0;

  OsdiSimInfo sim_info = {
      .paras = get_simparams(ckt),
      .abstime = is_tran ? ckt->CKTtime : 0.0,
      .prev_solve = ckt->CKTrhsOld,
      .prev_state = ckt->CKTstates[0],
      .next_state = ckt->CKTstates[0],
      .flags = CALC_OP | EVAL_FLAG_IS_FINAL_STEP,
  };

  if (ckt->CKTmode & (MODEDCOP | MODEDCTRANCURVE)) {
    sim_info.flags |= ANALYSIS_DC | ANALYSIS_STATIC;
  }
  if (is_tran) {
    sim_info.flags |= ANALYSIS_TRAN;
  }
  /* LRM audit (events): a noise job ends with MODEAC|MODEACNOISE both set,
   * and the bare MODEAC test made @(final_step("ac")) fire at the end of a
   * .noise analysis -- LRM Table 5-1 gives it 0 there (the run's own name is
   * "noise", exactly as Table 4-22's analysis() rows separate the two). */
  if ((ckt->CKTmode & MODEAC) && !(ckt->CKTmode & MODEACNOISE)) {
    sim_info.flags |= ANALYSIS_AC;
  }
  if (ckt->CKTmode & MODEACNOISE) {
    sim_info.flags |= ANALYSIS_NOISE;
  }

  for (int type = 0; type < ft_sim->numDevices; type++) {
    if (!ft_sim->devices[type] || !ft_sim->devices[type]->registry_entry ||
        !ckt->CKThead[type]) {
      continue;
    }

    OsdiRegistryEntry *entry = osdi_reg_entry_model(ckt->CKThead[type]);
    const OsdiDescriptor *descr = entry->descriptor;

    for (GENmodel *gen_model = ckt->CKThead[type]; gen_model;
         gen_model = gen_model->GENnextModel) {
      void *model = osdi_model_data(gen_model);

      for (GENinstance *gen_inst = gen_model->GENinstances; gen_inst;
           gen_inst = gen_inst->GENnextInstance) {
        void *inst = osdi_instance_data(entry, gen_inst);
        OsdiExtraInstData *extra_inst_data =
            osdi_extra_instance_data(entry, gen_inst);

        /* Enhancement-412: in AC and NOISE, `prev_solve` (CKTrhsOld) holds the
         * SMALL-SIGNAL solution at the last swept frequency, not a bias point.
         * Evaluating the model against it recomputes every operating-point
         * variable from a complex response -- so `@nd1[gm]` read after an `.ac`
         * returned a frequency-dependent number instead of the operating point,
         * silently. (Built-in devices are unaffected: they have no such
         * post-analysis evaluation.)
         *
         * The eval still has to happen, because it is the only thing that fires
         * `@(final_step)`, and `@(final_step("ac"))` / the noise variant are
         * supported and tested (finalstep_examples). So the instance data is
         * snapshotted around it and put back afterwards: the event bodies run
         * and their side effects ($strobe, $fdisplay) stand, while everything
         * the evaluation wrote into the instance -- opvars included -- is
         * discarded. Discarding is precisely correct here, since the results of
         * this evaluation are deliberately never loaded into the matrix or RHS.
         *
         * DC, DCTRANCURVE and TRAN are deliberately NOT snapshotted: there the
         * final solution IS a real operating point, so the values that
         * evaluation leaves behind are the ones a reader should see. */
        char *op_snapshot = NULL;
        if (preserve_op && descr->instance_size > 0) {
          op_snapshot = TMALLOC(char, descr->instance_size);
          if (op_snapshot) {
            memcpy(op_snapshot, inst, descr->instance_size);
          }
        }

        eval(descr, gen_inst, inst, extra_inst_data, model, &sim_info);

        if (op_snapshot) {
          memcpy(inst, op_snapshot, descr->instance_size);
          txfree(op_snapshot);
        }
      }
    }
  }

  return OK;
}
