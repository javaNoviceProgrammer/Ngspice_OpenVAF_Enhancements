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


#include "ngspice/stringutil.h"

#include "ngspice/config.h"
#include "ngspice/devdefs.h"
#include "ngspice/iferrmsg.h"
#include "ngspice/memory.h"
#include "ngspice/ngspice.h"
#include "ngspice/typedefs.h"

#include "osdi.h"
#include "osdidefs.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

/*
 * This function converts the information in (a list of) OsdiParamOpvar in
 * descr->param_opvar to the internal ngspice representation (IFparm).
 */
static int write_param_info(IFparm **dst, const OsdiDescriptor *descr,
                            uint32_t start, uint32_t end, bool has_m) {
  for (uint32_t i = start; i < end; i++) {
    OsdiParamOpvar *para = &descr->param_opvar[i];
    uint32_t num_names = para->num_alias + 1;

    int dataType = IF_ASK;
    if ((para->flags & (uint32_t)PARA_KIND_OPVAR) == 0) {
      dataType |= IF_SET;
    }

    switch (para->flags & PARA_TY_MASK) {
    case PARA_TY_REAL:
      dataType |= IF_REAL;
      break;
    case PARA_TY_INT:
      dataType |= IF_INTEGER;
      break;
    case PARA_TY_STR:
      dataType |= IF_STRING;
      break;
    default:
      errRtn = "get_osdi_info";
      errMsg = tprintf("Unknown OSDI type %d for parameter %s!",
                       para->flags & PARA_TY_MASK, para->name[0]);
      return -1;
    }

    if (para->len != 0) {
      dataType |= IF_VECTOR;
    }

    for (uint32_t j = 0; j < num_names; j++) {
      if (j != 0) {
        dataType |= IF_UNINTERESTING;
      }
      char *para_name = copy(para->name[j]);
      if (para_name[0] == '$') {
        para_name[0] = '_';
      }
      strtolower(para_name);
      (*dst)[j] = (IFparm){.keyword = para_name,
                           .id = (int)i,
                           .description = para->description,
                           .dataType = dataType};
    }
    if (!has_m && !strcmp(para->name[0], "$mfactor")) {
      (*dst)[num_names] = (IFparm){.keyword = "m",
                                   .id = (int)i,
                                   .description = para->description,
                                   .dataType = dataType};
      *dst += 1;
    }

    *dst += num_names;
  }

  return 0;
}
/**
 * This function creates a SPICEdev instance for a specific OsdiDescriptor by
 * populating the SPICEdev struct with descriptor specific metadata and pointers
 * to the descriptor independent functions.
 * */

/* Enhancement-335: Verilog-A is case-SENSITIVE, SPICE is not. Two OSDI
 * parameters differing only in case (`GAIN` and `gain`) both fold to the same
 * lowercased keyword, and one of them silently loses -- a value written in the
 * deck lands on whichever registered last while the other keeps its default,
 * with nothing to indicate a value was dropped.
 *
 * This cannot be RESOLVED in the loader: a SPICE netlist is lowercased when it
 * is parsed, so by the time a value arrives the two names are indistinguishable.
 * What we can do is refuse to be silent about it, so the model author learns
 * their parameters are unreachable instead of debugging a wrong answer. */
static void osdi_warn_case_collisions(const IFparm *params, int n,
                                      const char *module, const char *kind) {
  for (int i = 1; i < n; i++) {
    if (!params[i].keyword)
      continue;
    for (int j = 0; j < i; j++) {
      if (params[j].keyword && !strcmp(params[j].keyword, params[i].keyword)) {
        fprintf(stderr,
                "Warning: %s: %s parameter '%s' is declared more than once "
                "differing only in case; SPICE cannot tell the names apart, so "
                "only one of them can be set from a netlist.\n",
                module ? module : "(osdi)", kind, params[i].keyword);
        break;
      }
    }
  }
}

extern SPICEdev *osdi_create_spicedev(const OsdiRegistryEntry *entry) {
  const OsdiDescriptor *descr = entry->descriptor;

  // allocate and fill terminal names array
  char **termNames = TMALLOC(char *, descr->num_terminals);
  for (uint32_t i = 0; i < descr->num_terminals; i++) {
    termNames[i] = descr->nodes[i].name;
  }

  // allocate and fill instance params (and opvars)
  int *num_instance_para_names = TMALLOC(int, 1);
  for (uint32_t i = 0; i < descr->num_instance_params; i++) {
    *num_instance_para_names += (int)(1 + descr->param_opvar[i].num_alias);
  }
  for (uint32_t i = descr->num_params;
       i < descr->num_opvars + descr->num_params; i++) {
    *num_instance_para_names += (int)(1 + descr->param_opvar[i].num_alias);
  }
  if (entry->dt != UINT32_MAX) {
    /* "dt" plus the conventional "dtemp" spelling every built-in uses */
    *num_instance_para_names += 2;
  }

  if (entry->temp != UINT32_MAX) {
    *num_instance_para_names += 1;
  }

  if (!entry->has_m) {
    *num_instance_para_names += 1;
  }

  IFparm *instance_para_names = TMALLOC(IFparm, *num_instance_para_names);
  IFparm *dst = instance_para_names;

  if (entry->dt != UINT32_MAX) {
    dst[0] = (IFparm){"dt", (int)entry->dt, IF_REAL | IF_SET,
                      "Instance delta temperature"};
    dst[1] = (IFparm){"dtemp", (int)entry->dt, IF_REAL | IF_SET,
                      "Instance delta temperature"};
    dst += 2;
  }

  if (entry->temp != UINT32_MAX) {
    dst[0] = (IFparm){"temp", (int)entry->temp, IF_REAL | IF_SET,
                      "Instance temperature"};
    dst += 1;
  }
  write_param_info(&dst, descr, 0, descr->num_instance_params, entry->has_m);
  write_param_info(&dst, descr, descr->num_params,
                   descr->num_params + descr->num_opvars, true);
  osdi_warn_case_collisions(instance_para_names, *num_instance_para_names,
                            descr->name, "instance");

  // allocate and fill model params
  int *num_model_para_names = TMALLOC(int, 1);
  for (uint32_t i = descr->num_instance_params; i < descr->num_params; i++) {
    *num_model_para_names += (int)(1 + descr->param_opvar[i].num_alias);
  }
  IFparm *model_para_names = TMALLOC(IFparm, *num_model_para_names);
  dst = model_para_names;
  write_param_info(&dst, descr, descr->num_instance_params, descr->num_params,
                   true);
  osdi_warn_case_collisions(model_para_names, *num_model_para_names,
                            descr->name, "model");

  // Allocate SPICE device
  SPICEdev *OSDIinfo = TMALLOC(SPICEdev, 1);

  // fill information
  OSDIinfo->DEVpublic = (IFdevice){
      .name = descr->name,
      .description = "A simulator independent device loaded with OSDI",
      // TODO why extra indirection? Optional ports?
      .terms = (int *)&descr->num_terminals,
      .numNames = (int *)&descr->num_terminals,
      .termNames = termNames,
      .numInstanceParms = num_instance_para_names,
      .instanceParms = instance_para_names,
      .numModelParms = num_model_para_names,
      .modelParms = model_para_names,
      .flags = DEV_DEFAULT,
      .registry_entry = (void *)entry,
  };

  size_t inst_off = entry->inst_offset;

  int *inst_size = TMALLOC(int, 1);
  *inst_size =
      (int)(inst_off + descr->instance_size + sizeof(OsdiExtraInstData));
  OSDIinfo->DEVinstSize = inst_size;

  size_t model_off = osdi_model_data_off();
  int *model_size = TMALLOC(int, 1);
  *model_size = (int)(model_off + descr->model_size);
  OSDIinfo->DEVmodSize = model_size;

  // fill generic functions
  OSDIinfo->DEVparam = OSDIparam;
  OSDIinfo->DEVmodParam = OSDImParam;
  OSDIinfo->DEVask = OSDIask;
  OSDIinfo->DEVmodAsk = OSDImAsk;
  OSDIinfo->DEVsetup = OSDIsetup;
  OSDIinfo->DEVpzSetup = OSDIsetup;
  OSDIinfo->DEVtemperature = OSDItemp;
  OSDIinfo->DEVunsetup = OSDIunsetup;
  OSDIinfo->DEVload = OSDIload;
  OSDIinfo->DEVacLoad = OSDIacLoad;
  OSDIinfo->DEVpzLoad = OSDIpzLoad;
  OSDIinfo->DEVtrunc = OSDItrunc;
  OSDIinfo->DEVaccept = OSDIaccept;
  OSDIinfo->DEVnoise = OSDInoise;
  /* Enhancement-352: OSDI 0.8 models carry 2nd/3rd order Taylor tensors, so
   * .disto can include their nonlinearities like a built-in device's. */
  OSDIinfo->DEVdisto = OSDIdisto;

  #ifdef KLU
  OSDIinfo->DEVbindCSC = OSDIbindCSC;
  OSDIinfo->DEVbindCSCComplex = OSDIbindCSCComplex;
  OSDIinfo->DEVbindCSCComplexToReal = OSDIbindCSCComplexToReal;
  #endif

  return OSDIinfo;
}

/* Enhancement-323: is device type `type` an OSDI (compiled Verilog-A) device?
 * Every OSDI SPICEdev is built by osdi_create_spicedev above and so shares the
 * OSDIparam instance-parameter setter -- a stable marker no built-in device
 * has. The optimizer's `.param` fast-path guard uses this to weight OSDI
 * instances by their much higher per-reset cost (an OSDI reset re-runs each
 * instance's setup/temperature callbacks). */
int osdi_devtype_is_osdi(int type)
{
  return type >= 0 && type < DEVmaxnum && DEVices[type] &&
         DEVices[type]->DEVparam == OSDIparam;
}
