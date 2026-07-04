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

#include "osdi.h"
#include "osdidefs.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int OSDIacLoad(GENmodel *inModel, CKTcircuit *ckt) {

  GENmodel *gen_model;
  GENinstance *gen_inst;

  OsdiRegistryEntry *entry = osdi_reg_entry_model(inModel);
  const OsdiDescriptor *descr = entry->descriptor;
  for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
    void *model = osdi_model_data(gen_model);

    for (gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);
      /* Nothing to calculate: just load the matrix entries calculated during
       * operating-point iterations.                                         */
      descr->load_jacobian_resist(inst, model);
      descr->load_jacobian_react(inst, model, ckt->CKTomega);

      /* Enhancement-51: inject ac_stim small-signal stimulus sources into the
       * complex AC RHS. load_ac_stim fills [re, im] pairs (factor*mag*e^{j*phase},
       * phase in radians per the LRM); each active source (analysis name "ac" --
       * the name of THIS analysis) adds +s at node_1 and -s at node_2. Sources
       * bound to other analysis names stay inactive, per LRM 4.6.3. */
      if (descr->num_ac_stim_src > 0) {
        uint32_t n = descr->num_ac_stim_src;
        double *stim = TMALLOC(double, 2 * n);
        uint32_t *node_mapping =
            (uint32_t *)(((char *)inst) + descr->node_mapping_offset);
        descr->load_ac_stim(inst, model, stim);
        for (uint32_t k = 0; k < n; k++) {
          const OsdiAcStimSource *src = &descr->ac_stim_sources[k];
          if (strcmp(src->analysis, "ac") != 0)
            continue;
          uint32_t n1 = node_mapping[src->nodes.node_1];
          double re = stim[2 * k];
          double im = stim[2 * k + 1];
          /* the stimulus enters the extracted residual with a positive sign,
           * and the AC system solves (G + jwC)x = -residual_stim */
          ckt->CKTrhs[n1] -= re;
          ckt->CKTirhs[n1] -= im;
          if (src->nodes.node_2 != UINT32_MAX) {
            uint32_t n2 = node_mapping[src->nodes.node_2];
            ckt->CKTrhs[n2] += re;
            ckt->CKTirhs[n2] += im;
          }
        }
        txfree(stim);
      }

      /* AC stamping for absdelay slots.
       *
       * For each slot k, the z-equation row has two contributions:
       *   (z_row, y_synth_col): e^{-j*omega*td}   (delayed input)
       *   (z_row, z_col):      -1                  (output)
       *
       * ngspice uses SPICE complex matrix format:
       *   SMPcADD(matrix, row, col, real_part, imag_part)
       * The matrix entries were pre-allocated in OSDIsetup as real pointers;
       * for AC we use the complex variants instead.
       */
      if (entry->num_absdelays > 0) {
        const OsdiAbsDelayInfo *infos =
            (const OsdiAbsDelayInfo *)entry->absdelay_infos;
        OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);
        double omega = ckt->CKTomega;

        for (uint32_t k = 0; k < entry->num_absdelays; k++) {
          double td = *((double *)(((char *)inst) + infos[k].td_offset));
          if (td < 0.0) td = 0.0;

          /* e^{-j*omega*td} = cos(omega*td) - j*sin(omega*td)
           *
           * Complex matrix layout: each entry is two consecutive doubles
           * [real, imag], so ptr+0 = real, ptr+1 = imag.  delay_jac_y/z point
           * to the real slot of that entry: the SMPmakeElt element under the
           * SPARSE solver, or the live CSC_Complex slot under KLU (switched to
           * the complex array by OSDIbindCSCComplex before AC load).         */
          double c =  cos(omega * td);
          double s = -sin(omega * td);

          /* (z_row, y_synth_col): e^{-j*omega*td} */
          *(extra->delay_jac_y[k])     += c;
          *(extra->delay_jac_y[k] + 1) += s;

          /* (z_row, z_col): -1 */
          *(extra->delay_jac_z[k]) += -1.0;
          /* imaginary part stays zero */
        }
      }

      /* AC stamping for last_crossing slots: no well-defined small-signal
       * sensitivity (the crossing time is a function of the whole past
       * trajectory, not the AC-linearized instantaneous value), so this just
       * pins the row diagonal: (z_row, z_col) = -1, no y-coupling term. */
      if (entry->num_last_crossings > 0) {
        OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);
        for (uint32_t k = 0; k < entry->num_last_crossings; k++) {
          *(extra->crossing_jac_z[k]) += -1.0;
        }
      }
    }
  }
  return (OK);
}
