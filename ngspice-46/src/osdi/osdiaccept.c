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
 * per the LRM), and starts at 0.0 (set at slot allocation in OSDIsetup)
 * before any crossing has been observed.
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

int OSDIaccept(CKTcircuit *ckt, GENmodel *inModel) {
  OsdiRegistryEntry *entry = osdi_reg_entry_model(inModel);

  bool is_tran = (bool)(ckt->CKTmode & MODETRAN);
  if (!is_tran)
    return OK;

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
