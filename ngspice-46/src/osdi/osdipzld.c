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

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int OSDIpzLoad(GENmodel *inModel, CKTcircuit *ckt, SPcomplex *s) {
  NG_IGNORE(ckt);

  GENmodel *gen_model;
  GENinstance *gen_inst;

  OsdiRegistryEntry *entry = osdi_reg_entry_model(inModel);
  const OsdiDescriptor *descr = entry->descriptor;
  for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
    void *model = osdi_model_data(gen_model);

    for (gen_inst = gen_model->GENinstances; gen_inst;
         gen_inst = gen_inst->GENnextInstance) {
      void *inst = osdi_instance_data(entry, gen_inst);
      // nothing to calculate just load the matrix entries calculated during
      // operating point iterations
      // the load_jacobian_tran function migh seem weird here but all this does
      // is adding J_resist + J_react * a to every matrix entry (real part).
      // J_resist are the conductances (normal matrix entries) and J_react the
      // capcitances
      descr->load_jacobian_tran(inst, model, s->real);
      descr->load_jacobian_react(inst, model, s->imag);

      /* Enhancement-418: absdelay/last_crossing rows, which the DESCRIPTOR
       * does not carry -- the compiler leaves them empty because the simulator
       * fills them (osdiload.c for dc/tran, osdiacld.c for ac). pz filled them
       * nowhere, so the row was identically zero, the matrix was singular at
       * EVERY trial s, and every trial looked like a root: CKTpzFindZeros then
       * reported "the input signal is shorted on the way to the output", which
       * names neither the cause nor the device.
       *
       * The AC stamp cannot simply be reused. There it is exact, e^{-j*w*td},
       * and bounded -- |e^{-j*w*td}| = 1 for real w. Here s is complex and
       * ranges over pz's own search interval (up to 1e35), where e^{-s*td}
       * overflows to inf and poisons the determinant; worse, a transport delay
       * is transcendental and has infinitely many roots, so there is no finite
       * pole-zero set to find. So the slot is stamped as the zero-delay wire
       * V(z) - V(y) = 0 -- the same linearization absdelay_stamp_dc uses for
       * the operating point -- and the user is told, once per instance. */
      if (entry->num_absdelays > 0) {
        OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);
        for (uint32_t k = 0; k < entry->num_absdelays; k++) {
          *(extra->delay_jac_y[k]) += 1.0;
          *(extra->delay_jac_z[k]) += -1.0;
        }
        if (!extra->pz_delay_warned) {
          extra->pz_delay_warned = true;
          fprintf(stderr,
                  "Warning: %s: pole-zero analysis treats the absdelay() of "
                  "model type '%s' as a ZERO delay.\n"
                  "         A transport delay contributes e^-s*td, which has "
                  "infinitely many poles and zeros; the reported set is that of "
                  "the delay-free circuit. Use ac (which stamps the delay "
                  "exactly) if the delay matters.\n",
                  gen_inst->GENname, descr->name);
        }
      }

      /* last_crossing needs no such caveat and no warning: the crossing time is
       * a function of the whole past trajectory, so its small-signal
       * sensitivity is exactly zero. Pinning the diagonal is the same row
       * osdiacld.c stamps, and it adds no root -- a decoupled -1 on the
       * diagonal only flips the sign of the determinant. */
      if (entry->num_last_crossings > 0) {
        OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);
        for (uint32_t k = 0; k < entry->num_last_crossings; k++) {
          *(extra->crossing_jac_z[k]) += -1.0;
        }
      }

      /* Enhancement-532: the synthetic 0 V collapse shorts are frequency-
       * independent linear constraints -- stamp them at every trial s. */
      {
        OsdiExtraInstData *extra = osdi_extra_instance_data(entry, gen_inst);
        for (uint32_t k = 0; k < extra->num_syn_shorts; k++) {
          double **p = extra->syn_short_ptrs + 4 * k;
          *(p[0]) += 1.0;
          *(p[1]) -= 1.0;
          *(p[2]) += 1.0;
          *(p[3]) -= 1.0;
        }
      }
    }
  }
  return (OK);
}
