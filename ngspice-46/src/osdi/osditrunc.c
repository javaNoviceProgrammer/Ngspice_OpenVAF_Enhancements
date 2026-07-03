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
