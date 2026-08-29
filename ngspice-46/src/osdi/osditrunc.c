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

#include "ngspice/cktdefs.h"
#include "osdidefs.h"

/* Enhancement-504: the most steps a MODEL may force across one analysis
   window through $bound_step. Not a limit on ngspice's own stepping. */
#define E504_MAX_MODEL_STEPS 1.0e6

int OSDItrunc(GENmodel *in_model, CKTcircuit *ckt, double *timestep) {
  OsdiRegistryEntry *entry = osdi_reg_entry_model(in_model);
  const OsdiDescriptor *descr = entry->descriptor;
  uint32_t offset = descr->bound_step_offset;
  bool has_boundstep = offset != UINT32_MAX;
  offset += entry->inst_offset;

  for (GENmodel *model = in_model; model; model = model->GENnextModel) {
    for (GENinstance *inst = model->GENinstances; inst;
         inst = inst->GENnextInstance) {

      /* Enhancement-55: $discontinuity(n >= 0) fired during this (converged,
       * not yet accepted) timepoint: request a much smaller step so the
       * integrator REJECTS the point and retries with delta/8, resolving the
       * event onset instead of extrapolating across it (the E-24 sentinel
       * below only bounds the NEXT step). EDGE-triggered and once per onset:
       * only when the flag is NEW versus the last accepted point and the
       * retry latch is clear -- a model announcing over a whole REGION
       * (every eval while a condition holds) must not grind every step down
       * to the floor. The CKTdelmin guard keeps degenerate cases terminating. */
      OsdiExtraInstData *extra_inst_data =
          osdi_extra_instance_data(entry, inst);
      if ((extra_inst_data->point_eval_flags & EVAL_RET_FLAG_DISCONT) &&
          !(extra_inst_data->prev_point_eval_flags & EVAL_RET_FLAG_DISCONT) &&
          !extra_inst_data->discont_retry &&
          ckt->CKTdelta > 20.0 * ckt->CKTdelmin) {
        double cut = ckt->CKTdelta / 8.0;
        if (cut < *timestep) {
          *timestep = cut;
        }
        extra_inst_data->discont_retry = true;
      }

      if (has_boundstep) {
        double *del = (double *)(((char *)inst) + offset);
        if (*del < 0.0) {
          /* Enhancement-24: a negative bound_step is the sentinel written by
           * $discontinuity(n) (n >= 0). Rather than a literal step bound, it means
           * "a discontinuity occurred here": don't let the next timestep grow past
           * the last accepted step, so the event is resolved rather than
           * extrapolated across. CKTdeltaOld[0] is the most recent accepted delta. */
          double last = ckt->CKTdeltaOld[0];
          /* Enhancement-504: floor this branch too. A model that announces a
             discontinuity on EVERY evaluation -- `$discontinuity(0)` outside
             any conditional -- pins the step to the last accepted delta and it
             can never grow again, so once the retry above has cut it the
             transient crawls for the rest of the analysis and never returns.
             E-55 already made the RETRY edge-triggered for exactly this reason;
             the cap needs the same protection. */
          double dfloor = (ckt->CKTfinalTime - ckt->CKTinitTime) / E504_MAX_MODEL_STEPS;
          if (dfloor > 0.0 && last > 0.0 && last < dfloor) {
            if (!extra_inst_data->boundstep_floored) {
              extra_inst_data->boundstep_floored = true;
              fprintf(stderr,
                      "Warning: %s: announcing a discontinuity on every "
                      "evaluation has pinned the timestep to %g; holding it at "
                      "%g. Guard the $discontinuity with the condition it "
                      "belongs to.\n",
                      inst->GENname, last, dfloor);
            }
            last = dfloor;
          }
          if (last > 0.0 && last < *timestep) {
            *timestep = last;
          }
        } else if (*del < *timestep) {
          /* Enhancement-504: honour the model's bound, but not to the point
             of an unbounded run.

             `$bound_step(1e-18)` is a perfectly LEGAL positive request and the
             transient took it literally: >150 s of wall clock with no output,
             no error and no "timestep too small". That check compares against
             CKTdelmin, which for a 12 ns analysis is ~5e-20 -- far BELOW the
             1e-18 being asked for -- so nothing ever fired. The step was not
             too small for the solver; it was too small to finish.

             No clamp value makes 1.2e10 steps work, so the rule is stated in
             the only terms that bound the run: a model may not force more than
             E504_MAX_MODEL_STEPS steps across the analysis window. Beyond that
             the bound is clamped and the model is named once. A model asking
             for genuinely fine resolution is unaffected -- one million steps is
             already far more than any transient here needs -- and ngspice's own
             adaptive stepping is untouched, since this bounds only what a
             DEVICE may demand. */
          double req = *del;
          double span = ckt->CKTfinalTime - ckt->CKTinitTime;
          double floor_step = (span > 0.0) ? span / E504_MAX_MODEL_STEPS : 0.0;
          if (floor_step > 0.0 && req < floor_step) {
            if (!extra_inst_data->boundstep_floored) {
              extra_inst_data->boundstep_floored = true;
              fprintf(stderr,
                      "Warning: %s: $bound_step(%g) would need %.3g steps to "
                      "cross this analysis; using %g (%g steps) instead. A "
                      "device cannot demand an unbounded step count.\n",
                      inst->GENname, req, span / req, floor_step,
                      E504_MAX_MODEL_STEPS);
            }
            req = floor_step;
          }
          if (req < *timestep) {
            *timestep = req;
          }
        }
      }

      int state = inst->GENstate + (int)descr->num_states;
      for (uint32_t i = 0; i < descr->num_nodes; i++) {
        if (descr->nodes[i].react_residual_off != UINT32_MAX) {
          CKTterr(state, ckt, timestep);
          state += 2;
        }
      }
    }
  }
  return 0;
}
