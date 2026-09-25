/*
 * This file is part of the OSDI component of NGSPICE.
 * Copyright© 2022 SemiMod GmbH.
 *
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */

/*
 * OSDIaccept — called by CKTaccept() after each accepted transient timepoint.
 *
 * For absdelay slots we commit the converged V(y_synth) value into the
 * waveform history at the current CKTtimeIndex.  CKTtimePoints[ti] has
 * already been set to the accepted time by optran.c before CKTaccept() is
 * called, so the pairing (CKTtimePoints[ti], delay_hist[k][ti]) is correct.
 */

#include "ngspice/iferrmsg.h"
#include "ngspice/memory.h"
#include "ngspice/ngspice.h"
#include "ngspice/typedefs.h"

#include "osdi.h"
#include "osdidefs.h"

#include <stdint.h>
#include <string.h>

/*
 * For last_crossing slots: commit the converged V(y_synth) (the watched
 * expression) into crossing_hist at the current timepoint, exactly like
 * absdelay's delay_hist, then check whether the just-completed step
 * [ti-1, ti] contains a zero-crossing matching the requested direction; if
 * so, linearly interpolate the crossing time within that step and cache it
 * in crossing_time[k]. The cache is left unchanged when no new qualifying
 * crossing is found (so V(z) keeps returning the time of the LAST crossing,
 * per the LRM), and starts at OSDI_LAST_CROSSING_NONE -- the NEGATIVE sentinel
 * LRM 4.5.10 requires before any crossing has been observed (set at slot
 * allocation in OSDIsetup and re-armed in OSDItemp). The history's [0] entry is
 * seeded from the converged operating point in last_crossing_stamp: left at 0
 * it made an expression that is already positive at the operating point look
 * like a rising edge at the first accepted point, faking a crossing at t = 0.
 */
static void last_crossing_accept(CKTcircuit *ckt, GENmodel *inModel,
                                  OsdiRegistryEntry *entry, int ti) {
  if (entry->num_last_crossings == 0)
    return;

  const OsdiDescriptor *descr = entry->descriptor;
  const OsdiLastCrossingInfo *infos =
      (const OsdiLastCrossingInfo *)entry->last_crossing_infos;
  uint32_t n = entry->num_last_crossings;

  for (GENmodel *gen_model = inModel; gen_model;
       gen_model = gen_model->GENnextModel) {
    for (GENinstance *gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);
      OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);

      if (!extra->crossing_hist)
        continue;

      uint32_t needed = (uint32_t)(ckt->CKTtimeListSize) + 64;
      if (extra->crossing_hist_cap < needed) {
        for (uint32_t k = 0; k < n; k++) {
          extra->crossing_hist[k] =
              TREALLOC(double, extra->crossing_hist[k], needed);
        }
        extra->crossing_hist_cap = needed;
      }

      if ((uint32_t)ti >= extra->crossing_hist_cap)
        continue;

      uint32_t *node_mapping =
          (uint32_t *)(((char *)inst) + descr->node_mapping_offset);

      for (uint32_t k = 0; k < n; k++) {
        uint32_t y_mapped = node_mapping[infos[k].y_node];
        double v1 = ckt->CKTrhsOld[y_mapped];
        extra->crossing_hist[k][ti] = v1;

        if (ti < 1)
          continue;

        double v0 = extra->crossing_hist[k][ti - 1];
        double dir = *((double *)(((char *)inst) + infos[k].dir_offset));

        bool rising = v0 <= 0.0 && v1 > 0.0;
        bool falling = v0 >= 0.0 && v1 < 0.0;
        bool qualifies = (dir > 0.0 && rising) || (dir < 0.0 && falling) ||
                          (dir == 0.0 && (rising || falling));

        if (qualifies && v1 != v0) {
          double t0 = ckt->CKTtimePoints[ti - 1];
          double t1 = ckt->CKTtimePoints[ti];
          double frac = -v0 / (v1 - v0);
          extra->crossing_time[k] = t0 + frac * (t1 - t0);
        }
      }
    }
  }
}

/* -----------------------------------------------------------------------
 * Enhancement-698 (hunt F1/F2 of 2026-09-21): the transition() schedule
 * -----------------------------------------------------------------------
 *
 * Everything LRM 4.5.8 says about the operator is an event on its input: "A
 * transition is created when the input expression changes, and at this point
 * it uses the value of td, rise_time, fall_time and time_tol to determine
 * the new pending transition operator." This hook sees the ACCEPTED input,
 * so it is where a change is a change (an iterate that flips and flips back
 * never was one). At each accepted time t, per slot:
 *
 *   1. the active ramp is advanced to t (and retired once it has reached its
 *      destination);
 *   2. a pending transition whose due time has come starts -- readjusting
 *      the active ramp, if there is one, by the LRM's slope rule below;
 *   3. if the input differs from its last accepted value, a transition is
 *      created with the operator's CURRENT td / rise / fall: with td = 0 it
 *      starts now ("current transitions and scheduled ones are canceled, and
 *      the new one is created": the active ramp is readjusted, the queue is
 *      dropped); with td > 0 it is queued for t + td, cancelling any queued
 *      transition due at or after that ("If td is before a previously
 *      scheduled transition, then the previously scheduled transition(s) are
 *      canceled"), and a breakpoint marks the leading corner.
 *
 * A ramp from (t0, v0) to a target v over the rise (v > v0) or fall time T
 * has the slope (v - v0)/T and a breakpoint at each corner ("The transition
 * function causes the simulator to place time points at both corners of a
 * transition"): the trailing one at t0 + T through CKTsetBreak; the leading
 * one, when the ramp starts at the accepted point itself (td = 0), is that
 * point, entered at the head of the breakpoint table so that dctran treats
 * the step after it as it treats every step off a breakpoint -- order one,
 * a small first step. That is what keeps `ddt` of the output clean: the
 * trapezoidal rule across a slope corner that is not a breakpoint reads
 * twice the slope at the first point and rings 2, 0, 2, 0 down the ramp,
 * where the backward-Euler restart reads the slope exactly. A ZERO time --
 * no `default_transition, or
 * an edge below resolution -- is the LRM's "negligible, but non-zero,
 * transition time": the ramp lasts OSDI_TRANSITION_NEGLIGIBLE of TSTEP,
 * invisible on the print grid and resolvable by the step control of whatever
 * it drives, and "the simulator does not force a time point at the trailing
 * corner of a transition to avoid causing the simulator to take very small
 * time steps".
 *
 * Readjustment (4.5.8, Figures 4-7 to 4-12): "An interrupted transition is
 * not considered a new transition, but rather a readjustment of the original
 * transition." The new slope is taken from the ORIGIN (t1, v1) of the
 * interrupted ramp when the new destination continues in its direction and
 * from its DESTINATION (t2, v2) when it reverses -- "(v3-v1)/tr3", "(v3-v2)/
 * tf3" -- over the new transition's own time, and applied from the point of
 * interruption (ti, vi), so the readjusted ramp ends at t3 = ti + (v3 - vi)/
 * slope; its new origin (t4, v4), "which will be used if the transition is
 * interrupted again", is that line's point at v1 or v2.
 *
 * An input that is NOT piecewise constant -- a sine through a bare
 * transition(), which the LRM allows and warns "can cause the simulator to
 * run slowly" -- changes at every accepted point. Each change readjusts the
 * ramp as above, but places NO breakpoints: with them, every timepoint bred
 * a breakpoint td later, each breakpoint bred a cut step and so several
 * timepoints, and the transient never finished. The slot notices a change
 * following a change (`changed_prev`) and drops the breakpoints until the
 * input has held still for a point; a comparator's edge is never two
 * changes in a row.
 */
#define OSDI_TRANSITION_NEGLIGIBLE 1e-3 /* of TSTEP */

static double transition_negligible(const CKTcircuit *ckt) {
  double eps = OSDI_TRANSITION_NEGLIGIBLE * ckt->CKTstep;
  return eps > 0.0 ? eps : 1e-12;
}

static void transition_set_break(CKTcircuit *ckt, double t) {
  /* strictly in the future: CKTsetBreak panics on a breakpoint in the past
   * and ignores one at the current time */
  if (t > ckt->CKTtime)
    CKTsetBreak(ckt, t);
}

/* The accepted point itself becomes a breakpoint (the leading corner of a
 * ramp starting now). CKTsetBreak ignores the current time, so the entry
 * goes in by hand, at the head of the sorted table; dctran's "are we at a
 * breakpoint" test then finds it after this accept, and its own sweep of
 * past breakpoints retires it. */
static void transition_break_now(CKTcircuit *ckt) {
  double t = ckt->CKTtime;
  if (ckt->CKTbreaks == NULL || ckt->CKTbreakSize <= 0 ||
      ckt->CKTbreaks[0] <= t)
    return;
  double *tmp = TMALLOC(double, ckt->CKTbreakSize + 1);
  tmp[0] = t;
  memcpy(tmp + 1, ckt->CKTbreaks, (size_t)ckt->CKTbreakSize * sizeof(double));
  FREE(ckt->CKTbreaks);
  ckt->CKTbreaks = tmp;
  ckt->CKTbreakSize++;
}

/* Start a ramp toward `target` at the accepted time t0 -- or readjust the
 * active one -- with the times the operator held when the input changed.
 * `brk`: place the corner breakpoints (not for an input that churns). */
static void transition_start(CKTcircuit *ckt, OsdiTransitionState *s,
                             double t0, double target, double trise,
                             double tfall, bool brk, bool churn) {
  double vi = s->v_out;
  /* Enhancement-720: the ramp this change interrupts. A change that follows
   * a change is one of the points the integrator put inside an input edge
   * (a source's 1 ns rise is a dozen accepted points), or an input that is
   * not piecewise constant: it readjusts against the ramp the edge's FIRST
   * change found, not against what the previous point of the same edge made
   * of it. The reversal rule takes the interrupted ramp's destination, and
   * that had become the input's value at the last point on the near side of
   * the output -- 0.683 of a 1 V edge, wherever the timepoint fell -- so the
   * slope was set by the step and by the delay path, not by the two levels
   * LRM 4.5.8 names. */
  if (!churn) {
    s->ref_active = s->active;
    s->ref_rising = s->slope > 0.0;
    s->ref_v_orig = s->v_orig;
    s->ref_v_dest = s->v_dest;
  }
  if (target == vi) {
    /* the input came back to where the output is: nothing to move */
    s->active = false;
    s->corner_pending = false;
    return;
  }
  bool rising = target > vi;
  double tt = rising ? trise : tfall;
  double eps = transition_negligible(ckt);
  bool negligible = !(tt > eps); /* zero, below resolution, or NaN */
  if (negligible)
    tt = eps;

  if (s->ref_active && !negligible) {
    /* readjustment: the slope from the interrupted ramp's origin (same
     * direction) or destination (reversal) over the NEW time, applied from
     * the point of interruption */
    double v_ref = (rising == s->ref_rising) ? s->ref_v_orig : s->ref_v_dest;
    double slope = (target - v_ref) / tt;
    if (slope != 0.0 && (target - vi) / slope > 0.0) {
      double t3 = t0 + (target - vi) / slope;
      s->active = true;
      s->slope = slope;
      s->t_from = t0;
      s->v_from = vi;
      s->t_dest = t3;
      s->v_dest = target;
      s->v_orig = v_ref;
      s->t_orig = t3 - tt;
      s->corner_pending = !brk;
      if (brk) {
        transition_break_now(ckt);
        transition_set_break(ckt, t3);
      }
      return;
    }
    /* degenerate reference: a fresh ramp from the interruption point */
  }
  s->active = true;
  s->slope = (target - vi) / tt;
  s->t_from = t0;
  s->t_orig = t0;
  s->v_from = vi;
  s->v_orig = vi;
  s->t_dest = t0 + tt;
  s->v_dest = target;
  s->corner_pending = !brk && !negligible;
  if (brk) {
    transition_break_now(ckt);
    if (!negligible)
      transition_set_break(ckt, s->t_dest);
  }
}

static void transition_accept_slot(CKTcircuit *ckt, OsdiTransitionState *s,
                                   double x, double td, double trise,
                                   double tfall) {
  double t = ckt->CKTtime;
  bool changed = x != s->x_last;
  /* a change following a change: a point inside an input edge, or an input
   * that is not piecewise constant -- no breakpoints for it, and it
   * readjusts against the ramp the edge's first change found (E-720) */
  bool churn = changed && s->changed_prev;
  bool brk = !churn;
  bool edge_over = !changed && s->changed_prev; /* the input holds still again */
  s->changed_prev = changed;

  /* 1. advance the active ramp to this point */
  if (s->active) {
    if (t >= s->t_dest) {
      s->v_out = s->v_dest;
      s->active = false;
    } else {
      s->v_out = transition_value_at(s, t);
    }
  }

  /* 2. start what is due: the breakpoint put a timepoint at t_due, within
   *    the breakpoint tolerance; a due time the step overran counts too */
  while (s->n_pending > 0 && s->pending[0].t_due <= t + ckt->CKTminBreak) {
    OsdiTransitionPending p = s->pending[0];
    s->n_pending--;
    if (s->n_pending > 0)
      memmove(&s->pending[0], &s->pending[1], s->n_pending * sizeof p);
    transition_start(ckt, s, t, p.target, p.trise, p.tfall, brk, p.churn);
  }

  /* 3. a change of the accepted input creates a transition */
  if (changed) {
    s->x_last = x;
    if (!(td > 0.0)) { /* 0, negative (projected by the compiler), NaN */
      s->n_pending = 0;
      transition_start(ckt, s, t, x, trise, tfall, brk, churn);
    } else {
      double t_due = t + td;
      while (s->n_pending > 0 && s->pending[s->n_pending - 1].t_due >= t_due)
        s->n_pending--;
      if (s->n_pending == s->cap_pending) {
        s->cap_pending = s->cap_pending ? 2 * s->cap_pending : 4;
        s->pending = TREALLOC(OsdiTransitionPending, s->pending, s->cap_pending);
      }
      s->pending[s->n_pending].t_due = t_due;
      s->pending[s->n_pending].target = x;
      s->pending[s->n_pending].trise = trise;
      s->pending[s->n_pending].tfall = tfall;
      s->pending[s->n_pending].churn = churn;
      s->n_pending++;
      if (brk)
        transition_set_break(ckt, t_due);
    }
  }

  /* 4. the input holds still after a run of changes: the edge is over. Its
   *    ramp gets the trailing corner breakpoint the run's changes did not
   *    place ("time points at both corners"), and when the edge was queued
   *    behind a delay its final value's due time gets one, so that the ramp
   *    the edge ends in starts there and not at whatever accepted point
   *    first passes it -- one breakpoint each per edge, none for an input
   *    that never holds still (E-720) */
  if (edge_over) {
    if (s->active && s->corner_pending) {
      transition_set_break(ckt, s->t_dest);
      s->corner_pending = false;
    }
    if (s->n_pending > 0 && s->pending[s->n_pending - 1].churn)
      transition_set_break(ckt, s->pending[s->n_pending - 1].t_due);
  }
}

static void transition_accept(CKTcircuit *ckt, GENmodel *inModel,
                              OsdiRegistryEntry *entry) {
  if (entry->num_transitions == 0)
    return;
  const OsdiDescriptor *descr = entry->descriptor;
  const OsdiTransitionInfo *infos =
      (const OsdiTransitionInfo *)entry->transition_infos;

  for (GENmodel *gen_model = inModel; gen_model;
       gen_model = gen_model->GENnextModel) {
    for (GENinstance *gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);
      OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);
      if (!extra->transition_state)
        continue;
      uint32_t *node_mapping =
          (uint32_t *)(((char *)inst) + descr->node_mapping_offset);
      for (uint32_t k = 0; k < entry->num_transitions; k++) {
        OsdiTransitionState *s = &extra->transition_state[k];
        if (!s->armed)
          continue;
        double x = ckt->CKTrhsOld[node_mapping[infos[k].y_node]];
        double td = *((double *)(((char *)inst) + infos[k].td_offset));
        double trise = *((double *)(((char *)inst) + infos[k].trise_offset));
        double tfall = *((double *)(((char *)inst) + infos[k].tfall_offset));
        transition_accept_slot(ckt, s, x, td, trise, tfall);
      }
    }
  }
}

/* Enhancement-698: the slew() limiter remembers the output it accepted, and
 * when: the next point's bound is y_last +- rate * (t - t_last). */
static void slew_accept(CKTcircuit *ckt, GENmodel *inModel,
                        OsdiRegistryEntry *entry) {
  if (entry->num_slews == 0)
    return;
  const OsdiDescriptor *descr = entry->descriptor;
  const OsdiSlewInfo *infos = (const OsdiSlewInfo *)entry->slew_infos;

  for (GENmodel *gen_model = inModel; gen_model;
       gen_model = gen_model->GENnextModel) {
    for (GENinstance *gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);
      OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);
      if (!extra->slew_state)
        continue;
      uint32_t *node_mapping =
          (uint32_t *)(((char *)inst) + descr->node_mapping_offset);
      for (uint32_t k = 0; k < entry->num_slews; k++) {
        extra->slew_state[k].y_last =
            ckt->CKTrhsOld[node_mapping[infos[k].z_node]];
        extra->slew_state[k].t_last = ckt->CKTtime;
      }
    }
  }
}

int OSDIaccept(CKTcircuit *ckt, GENmodel *inModel) {
  OsdiRegistryEntry *entry = osdi_reg_entry_model(inModel);

  /* LRM 9.4.6/9.5.9: the timepoint was accepted -- flush the deferred display
   * and file output of its converged iteration. Runs once per accept in
   * practice: the second model's call finds the buffers empty. */
  OSDIpendingFlush(ckt);

  bool is_tran = (bool)(ckt->CKTmode & MODETRAN);
  if (!is_tran)
    return OK;

  /* Enhancement-55: latch the accepted point's eval-return flags and clear
   * the discontinuity-rejection one-shot -- makes the $discontinuity step
   * rejection in OSDItrunc edge-triggered (once per onset). Must run for
   * every instance, before the absdelay-specific early returns below. */
  for (GENmodel *gen_model_ = inModel; gen_model_;
       gen_model_ = gen_model_->GENnextModel) {
    for (GENinstance *gen_inst_ = gen_model_->GENinstances; gen_inst_;
         gen_inst_ = gen_inst_->GENnextInstance) {
      OsdiExtraInstData *extra_ = osdi_extra_instance_data(entry, gen_inst_);
      extra_->prev_point_eval_flags = extra_->point_eval_flags;
      extra_->discont_retry = false;
    }
  }

  /* Enhancement-698: the transition schedule and the slew memory advance on
   * the accepted solution -- not at the accept of the operating point (the
   * first accept of a transient, with MODEINITTRAN still set), which precedes
   * the evaluation that seeds their state. Independent of the absdelay
   * timeline below: a model with neither absdelay nor last_crossing never
   * allocates it. */
  if (!(ckt->CKTmode & MODEINITTRAN)) {
    transition_accept(ckt, inModel, entry);
    slew_accept(ckt, inModel, entry);
  }

  /* CKTtimePoints and CKTtimeIndex are populated by absdelay_stamp_tran
   * during the MODEINITTRAN Newton call.  If still NULL the transient hasn't
   * started yet (e.g., MODETRANOP DC OP call).                             */
  if (ckt->CKTtimePoints == NULL || ckt->CKTtimeIndex < 0)
    return OK;

  int ti = ckt->CKTtimeIndex;

  last_crossing_accept(ckt, inModel, entry, ti);

  if (entry->num_absdelays == 0)
    return OK;

  const OsdiDescriptor *descr = entry->descriptor;
  const OsdiAbsDelayInfo *infos = (const OsdiAbsDelayInfo *)entry->absdelay_infos;
  uint32_t n = entry->num_absdelays;

  for (GENmodel *gen_model = inModel; gen_model;
       gen_model = gen_model->GENnextModel) {
    for (GENinstance *gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);
      OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);

      if (!extra->delay_hist)
        continue;

      /* Grow history arrays if needed (optran.c may have grown CKTtimePoints) */
      uint32_t needed = (uint32_t)(ckt->CKTtimeListSize) + 64;
      if (extra->delay_hist_cap < needed) {
        for (uint32_t k = 0; k < n; k++) {
          extra->delay_hist[k] =
              TREALLOC(double, extra->delay_hist[k], needed);
        }
        extra->delay_hist_cap = needed;
      }

      if ((uint32_t)ti >= extra->delay_hist_cap)
        continue;

      uint32_t *node_mapping =
          (uint32_t *)(((char *)inst) + descr->node_mapping_offset);

      for (uint32_t k = 0; k < n; k++) {
        uint32_t y_mapped = node_mapping[infos[k].y_node];
        /* Store the CONVERGED V(y_synth) at the just-accepted timepoint. */
        extra->delay_hist[k][ti] = ckt->CKTrhsOld[y_mapped];
      }
    }
  }

  return OK;
}
