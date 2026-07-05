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
          if (last > 0.0 && last < *timestep) {
            *timestep = last;
          }
        } else if (*del < *timestep) {
          *timestep = *del;
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
