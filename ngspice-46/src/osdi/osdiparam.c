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
#include "ngspice/ngspice.h"
#include "ngspice/typedefs.h"

#include "osdidefs.h"

#include <stdint.h>
#include <string.h>

static int osdi_param_access(OsdiParamOpvar *param_info, bool write_value,
                             IFvalue *value, void *ptr) {
  size_t len;
  void *val_ptr;
  switch (param_info->flags & PARA_TY_MASK) {
  case PARA_TY_REAL:
    len = sizeof(double);
    if (param_info->len) {
      len *= param_info->len;
      val_ptr = value->v.vec.rVec;
    } else {
      val_ptr = &value->rValue;
    }
    break;
  case PARA_TY_INT:
    len = sizeof(int);
    if (param_info->len) {
      len *= param_info->len;
      val_ptr = value->v.vec.iVec;
    } else {
      val_ptr = &value->iValue;
    }
    break;
  case PARA_TY_STR:
    len = sizeof(char *);
    if (param_info->len) {
      len *= param_info->len;
      val_ptr = value->v.vec.cVec;
    } else {
      val_ptr = &value->cValue;
    }
    break;
  default:
    return (E_PARMVAL);
  }
  if (write_value) {
    memcpy(val_ptr, ptr, len);
  } else {
    memcpy(ptr, val_ptr, len);
  }

  return OK;
}

static int osdi_write_param(void *dst, IFvalue *value, int param,
                            const OsdiDescriptor *descr) {
  // value may be NULL as a result of a bad parse from INPgetValue
  // catch it before dereferencing it
  if (dst == NULL || value == NULL) {
    return (E_PANIC);
  }

  OsdiParamOpvar *param_info = &descr->param_opvar[param];

  if (param_info->len) {
    if ((uint32_t)value->v.numValue != param_info->len) {
      return (E_PARMVAL);
    }
  }

  return osdi_param_access(param_info, false, value, dst);
}

extern int OSDIparam(int param, IFvalue *value, GENinstance *instPtr,
                     IFvalue *select) {

  NG_IGNORE(select);
  OsdiRegistryEntry *entry = osdi_reg_entry_inst(instPtr);
  const OsdiDescriptor *descr = entry->descriptor;

  if (param >= (int)descr->num_instance_params) {
    // special handling for temperature parameters
    OsdiExtraInstData *inst = osdi_extra_instance_data(entry, instPtr);
    if (param == (int)entry->dt) {
      inst->dt = value->rValue;
      inst->dt_given = true;
      return (OK);
    }
    if (param == (int)entry->temp) {
      /* Enhancement-394: `temp=` is an ABSOLUTE device temperature and, by the
       * SPICE convention every built-in follows, the user writes it in degrees
       * CELSIUS -- `dioparam.c` does `DIOtemp = value->rValue + CONSTCtoK`, and
       * ngspice's own OSDI code acknowledges the same convention where it hands
       * `tnom` to the model as `CKTnomTemp - CONSTCtoK`.
       *
       * The raw value was stored here and then used directly as the Kelvin
       * device temperature, so `temp=75` reached the model as $temperature=75
       * (and $vt = 6.5 mV instead of 30 mV). On a Verilog-A diode that is
       * -2.5e+16 A where the correct answer is -4.85e-07 A. `temp=0` made $vt
       * exactly zero, so `limexp(V/$vt)` divided by zero and the operating
       * point failed outright; `temp=-40` produced a negative absolute
       * temperature and a negative thermal voltage. `.temp`, `.option temp` and
       * `dtemp` were all correct -- only this path was raw. */
      inst->temp = value->rValue + CONSTCtoK;
      inst->temp_given = true;
      return (OK);
    }

    return (E_BADPARM);
  }

  /* Enhancement-93: a fixed (localparam) parameter -- e.g. a structural width
   * parameter frozen by openvaf -- cannot be set from the netlist. Warn and
   * ignore rather than silently swallowing the value. */
  if (descr->param_opvar[param].flags & PARA_FLAG_FIXED) {
    fprintf(stderr,
            "Warning: parameter '%s' is a fixed (localparam) value and cannot "
            "be set from the netlist; ignored.\n",
            descr->param_opvar[param].name[0]);
    return (OK);
  }

  void *inst = osdi_instance_data(entry, instPtr);
  void *dst = descr->access(inst, NULL, (uint32_t)param,
                            ACCESS_FLAG_SET | ACCESS_FLAG_INSTANCE);

  return osdi_write_param(dst, value, param, descr);
}

extern int OSDImParam(int param, IFvalue *value, GENmodel *modelPtr) {
  OsdiRegistryEntry *entry = osdi_reg_entry_model(modelPtr);
  const OsdiDescriptor *descr = entry->descriptor;

  if (param > (int)descr->num_params ||
      param < (int)descr->num_instance_params) {
    return (E_BADPARM);
  }

  /* Enhancement-93: fixed (localparam) model parameter -- warn and ignore. */
  if (descr->param_opvar[param].flags & PARA_FLAG_FIXED) {
    fprintf(stderr,
            "Warning: parameter '%s' is a fixed (localparam) value and cannot "
            "be set from the netlist; ignored.\n",
            descr->param_opvar[param].name[0]);
    return (OK);
  }

  void *model = osdi_model_data(modelPtr);
  void *dst = descr->access(NULL, model, (uint32_t)param, ACCESS_FLAG_SET);

  return osdi_write_param(dst, value, param, descr);
}

static int osdi_read_param(void *src, IFvalue *value, int id,
                           const OsdiDescriptor *descr) {
  if (src == NULL || value == NULL) {
    return (E_PANIC);
  }

  OsdiParamOpvar *param_info = &descr->param_opvar[id];

  if (param_info->len) {
    value->v.numValue = (int)param_info->len;
  }

  return osdi_param_access(param_info, true, value, src);
}

extern int OSDIask(CKTcircuit *ckt, GENinstance *instPtr, int id,
                   IFvalue *value, IFvalue *select) {
  NG_IGNORE(select);

  OsdiRegistryEntry *entry = osdi_reg_entry_inst(instPtr);
  void *inst = osdi_instance_data(entry, instPtr);
  void *model = osdi_model_data_from_inst(instPtr);

  const OsdiDescriptor *descr = entry->descriptor;

  /* Enhancement-394: ids past the descriptor's parameter/opvar space are the
   * synthesized terminal currents declared in osdiinit.c.
   *
   * The current into terminal t is what the device stamped into that node's
   * KCL row: the resistive residual, plus -- in a transient -- the integrated
   * derivative of the reactive residual (the charge), which OSDIload places in
   * CKTstate0[state+1] while walking the reactive nodes in descriptor order.
   * The same walk is repeated here so the two agree exactly; outside a
   * transient there is no reactive contribution, matching the DC stamp. */
  uint32_t cur_base = descr->num_params + descr->num_opvars;
  if (id >= (int)cur_base) {
    uint32_t t = (uint32_t)id - cur_base;
    if (t >= descr->num_terminals) {
      return (E_BADPARM);
    }
    double cur = 0.0;
    if (descr->nodes[t].resist_residual_off != UINT32_MAX) {
      cur = *((double *)(((char *)inst) + descr->nodes[t].resist_residual_off));
    }
    if (ckt && (ckt->CKTmode & MODETRAN) && ckt->CKTstates[0]) {
      int state = instPtr->GENstate + (int)descr->num_states;
      for (uint32_t i = 0; i < descr->num_nodes; i++) {
        if (descr->nodes[i].react_residual_off == UINT32_MAX)
          continue;
        if (i == t) {
          cur += ckt->CKTstate0[state + 1];
          break;
        }
        state += 2;
      }
    }
    value->rValue = cur;
    return (OK);
  }
  uint32_t flags = ACCESS_FLAG_READ;
  if (id < (int)descr->num_instance_params) {
    flags |= ACCESS_FLAG_INSTANCE;
  }

  void *src = descr->access(inst, model, (uint32_t)id, flags);
  return osdi_read_param(src, value, id, descr);
}

extern int OSDImAsk(CKTcircuit *ckt, GENmodel *modelPtr, int id,
                   IFvalue *value) {

  NG_IGNORE(ckt);

  OsdiRegistryEntry *entry = osdi_reg_entry_model(modelPtr);
  const OsdiDescriptor *descr = entry->descriptor;

  void *model = osdi_model_data(modelPtr);

  if (id >= (int)(descr->num_params)) {
    return (E_BADPARM);
  }

  void *src = descr->access(NULL, model, (uint32_t)id, ACCESS_FLAG_READ);
  return osdi_read_param(src, value, id, descr);
}
