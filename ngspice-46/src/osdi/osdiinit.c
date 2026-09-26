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
#include "ngspice/inpdefs.h"   /* E-565: INPgetTok, INPevaluate */
#include "ngspice/osdiitf.h"
#include <math.h>

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
/* Enhancement-396: two entries may legitimately share a keyword. When a model
 * declares one of the names this loader also provides, `osdi_create_registry_
 * entry` ROUTES the built-in to the model's own parameter -- `dtemp` sets
 * `dt = param_id`, `m` sets `has_m`, `temp` suppresses the loader's entry -- so
 * both IFparm entries address the SAME parameter id and nothing is unreachable.
 * That is the intended arrangement for essentially every CMC model in the
 * industry corpus (PSP, MEXTRAM, VBIC, HiSIM, BSIM all declare `dtemp`), and
 * warning about it was pure noise.
 *
 * The genuine defect Enhancement-335 found is a keyword shared by parameters
 * with DIFFERENT ids: `GAIN` and `gain` fold to one lowercased keyword, a deck
 * value lands on whichever registered last, and the other keeps its default with
 * nothing to say a value was dropped. Comparing ids is what separates the two. */
/* Enhancement-644 (IHP hunt C2): a parameter a paramset BOUND (PARA_FLAG_FIXED,
 * Enhancement-93) cannot be set from a netlist at all, so sharing its keyword
 * with a settable one loses nothing -- PSP's `SWSOA` bound to the paramset's
 * own `swsoa`, `sp_resistor`'s `r` alias bound to the paramset's `R`. The
 * warning below is about a value that lands on the wrong parameter; there
 * is no such value here. */
static int osdi_param_is_fixed(const OsdiDescriptor *descr, int id) {
  return id >= 0 && (uint32_t)id < descr->num_params &&
         (descr->param_opvar[id].flags & PARA_FLAG_FIXED) != 0;
}

/* Enhancement-731 (D1 of the 2026-09-25 evening hunt): the instance table
 * starts with rows THIS LOADER writes -- `dt`/`dtemp`, `temp`, and after the
 * module's own rows the terminal currents `i_<term>` and the bare `i` of
 * Enhancement-394 -- and none of them is a declaration of the model's. The
 * check ran over the whole table, so an operating-point VARIABLE named `temp`
 * (Enhancement-505 warns about it, once, naming the winner) also drew "instance
 * parameter 'temp' is declared more than once differing only in case": no such
 * parameter is declared, and the two spellings are identical. The caller now
 * hands this function the module's own rows alone. A model that names one of
 * the loader's rows keeps the arrangement it always had -- `m`, `dtemp` and
 * `temp` are routed or suppressed (E-396), an opvar `m`/`temp`/`dt` is named
 * by E-505, and an opvar `i` or `i_<term>` comes first in the table and wins,
 * as E-644 chose for `i`. */
/* Enhancement-731: the one loader row that sits AMONG the module's own --
 * write_param_info spells the compiler's `$mfactor` as `m` as well (E-394),
 * so an opvar `m` met it there and drew the same wrong line. */
static int osdi_is_mfactor_alias(const OsdiDescriptor *descr, const IFparm *p) {
  return p->keyword && !strcmp(p->keyword, "m") && p->id >= 0 &&
         (uint32_t)p->id < descr->num_instance_params &&
         !strcmp(descr->param_opvar[p->id].name[0], "$mfactor");
}

static void osdi_warn_case_collisions(const IFparm *params, int n,
                                      const OsdiDescriptor *descr,
                                      const char *kind) {
  const char *module = descr->name;
  for (int i = 1; i < n; i++) {
    if (!params[i].keyword)
      continue;
    for (int j = 0; j < i; j++) {
      if (params[j].keyword && !strcmp(params[j].keyword, params[i].keyword)) {
        if (params[j].id == params[i].id) {
          /* the same parameter under two spellings -- deliberately routed */
          continue;
        }
        if (osdi_is_mfactor_alias(descr, &params[j]) ||
            osdi_is_mfactor_alias(descr, &params[i])) {
          continue; /* Enhancement-731: the loader's `m`, not a declaration */
        }
        if (osdi_param_is_fixed(descr, params[j].id) ||
            osdi_param_is_fixed(descr, params[i].id)) {
          continue; /* Enhancement-644: one of them cannot be set anyway */
        }
        fprintf(stderr,
                "Warning: %s: %s parameter '%s' is declared more than once "
                "differing only in case; SPICE cannot tell the names apart, "
                "so only one of them can be set from a netlist.\n",
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
    /* OSDI-layer audit: the synthesized `m` alias row is only WRITTEN when
     * the descriptor carries an instance parameter literally named
     * "$mfactor" (write_param_info above). Counting the slot
     * unconditionally left the table's last IFparm row zeroed for a foreign
     * object without one -- keyword NULL, id 0 -- and devhelp (or any
     * instanceParms walker) showed a phantom "(null)" row, one strcmp away
     * from a crash. Unreachable for openvaf-r output, which always emits
     * $mfactor; reachable for any hand-written object. Count under the same
     * condition the writer uses. */
    bool descr_has_mfactor = false;
    for (uint32_t i = 0; i < descr->num_instance_params; i++) {
      if (!strcmp(descr->param_opvar[i].name[0], "$mfactor")) {
        descr_has_mfactor = true;
        break;
      }
    }
    if (descr_has_mfactor)
      *num_instance_para_names += 1;
  }

  /* Enhancement-394: one read-only terminal current per terminal, `i(<term>)`.
   * An OSDI device previously exposed no current at all: `.options
   * savecurrents` produced `@r1[i]` for a built-in resistor and nothing for
   * the OSDI device beside it, and `@n1[i]` did not exist, so the only way to
   * see a compact model's terminal current was to edit the model. */
  *num_instance_para_names += (int)descr->num_terminals;
  /* Enhancement-644 (IHP hunt C2): a two-terminal model that declares an `i`
   * of its own -- `sp_resistor`'s `(* desc="Current" *) real i` -- keeps
   * it: `@n1[i]` reads the model's value (the table lookup finds the model's
   * entry first), and the loader's alias would only draw the case-collision
   * warning against a name the author chose deliberately. */
  bool model_has_i = false;
  for (uint32_t i = 0; i < descr->num_params + descr->num_opvars; i++) {
    if ((i < descr->num_instance_params || i >= descr->num_params) &&
        !strcasecmp(descr->param_opvar[i].name[0], "i")) {
      model_has_i = true;
      break;
    }
  }
  if (descr->num_terminals == 2 && !model_has_i) {
    *num_instance_para_names += 1; /* the bare `i` alias */
  }

  IFparm *instance_para_names = TMALLOC(IFparm, *num_instance_para_names);
  IFparm *dst = instance_para_names;

  /* Enhancement-397: these were IF_SET only, so a value could be written and
   * never read back -- `@n1[temp]` answered "no such parameter" where every
   * built-in reports one, `show` listed neither, and a `sweep` over them ended
   * with a spurious error AFTER completing correctly. OSDIask serves them now
   * (see osdiparam.c), matching the built-in convention exactly: `temp` reads
   * back in DEGREES CELSIUS and defaults to the ambient, `dtemp`/`dt` read back
   * the offset and default to zero. */
  if (entry->dt != UINT32_MAX) {
    dst[0] = (IFparm){"dt", (int)entry->dt, IF_REAL | IF_SET | IF_ASK,
                      "Instance delta temperature"};
    dst[1] = (IFparm){"dtemp", (int)entry->dt, IF_REAL | IF_SET | IF_ASK,
                      "Instance delta temperature"};
    dst += 2;
  }

  if (entry->temp != UINT32_MAX) {
    dst[0] = (IFparm){"temp", (int)entry->temp, IF_REAL | IF_SET | IF_ASK,
                      "Instance temperature"};
    dst += 1;
  }
  IFparm *own_start = dst; /* Enhancement-731: the module's own rows */
  write_param_info(&dst, descr, 0, descr->num_instance_params, entry->has_m);
  write_param_info(&dst, descr, descr->num_params,
                   descr->num_params + descr->num_opvars, true);
  int own_count = (int)(dst - own_start);

  /* Enhancement-505: say so when one of the model's own names is unreachable.
   *
   * The simulator-supplied instance parameters above -- `m`, `temp`, `dtemp`,
   * `dt` -- are written into this table FIRST, so a lookup finds them before
   * anything the model declared. A model with an operating-point variable named
   * `temp` therefore assigned it and read back the ambient temperature, and one
   * named `m` read back the multiplier: the value was computed on every
   * evaluation and could never be seen. Nothing said a word, in the compiler or
   * here, and the name is legal Verilog-A.
   *
   * The collision is not worth refusing the model over -- the rest of it works,
   * and refusing would break a model that runs today for the sake of a name it
   * never reads -- so this names the parameter, the model and the winner, once
   * per descriptor at load time. */
  {
    static const char *const injected[] = {"m", "temp", "dtemp", "dt", NULL};
    for (uint32_t i = 0; i < descr->num_instance_params + descr->num_opvars; i++) {
      uint32_t idx = (i < descr->num_instance_params)
                         ? i
                         : descr->num_params + (i - descr->num_instance_params);
      const char *nm = descr->param_opvar[idx].name[0];
      /* OPERATING-POINT VARIABLES ONLY. A model may legitimately declare `m` or
       * `dtemp` as its own instance PARAMETER -- that is what Enhancement-394's
       * `has_m` exists for, a CMC-style model scales by its own `m`, and the
       * loader routes the deck's value into it, so nothing is shadowed and
       * limguard_examples asserts there is no warning. An opvar is read-only:
       * nothing routes into it, the simulator's parameter wins the lookup, and
       * the model's value can never be read back. */
      if ((descr->param_opvar[idx].flags & (uint32_t)PARA_KIND_OPVAR) == 0) {
        continue;
      }
      for (int k = 0; injected[k]; k++) {
        int supplied =
            (!strcmp(injected[k], "m") && !entry->has_m) ||
            (!strcmp(injected[k], "temp") && entry->temp != UINT32_MAX) ||
            ((!strcmp(injected[k], "dtemp") || !strcmp(injected[k], "dt")) &&
             entry->dt != UINT32_MAX);
        if (supplied && !strcasecmp(nm, injected[k])) {
          fprintf(stderr,
                  "Warning: %s: the operating-point variable '%s' has the "
                  "same name as the simulator's own instance parameter '%s', "
                  "which wins the lookup -- `@<inst>[%s]` reads the simulator's "
                  "value, not the model's. Rename it in the Verilog-A source.\n",
                  descr->name, nm, injected[k], nm);
        }
      }
    }
  }

  /* Enhancement-394: terminal currents occupy ids just past the descriptor's
   * own parameter/opvar space; OSDIask recognises that range. Two-terminal
   * devices additionally answer to the bare `i`, matching what R, C and L use,
   * so `.options savecurrents` can emit `.save @dev[i]` for them without
   * knowing the model's terminal names. */
  {
    uint32_t base = descr->num_params + descr->num_opvars;
    for (uint32_t t = 0; t < descr->num_terminals; t++) {
      /* `i_<term>`, not `i(<term>)`: the @dev[param] reader hands the text
         between the brackets to the vector parser, which reads `i(p)` as a
         function call and finds nothing. */
      char *nm = tprintf("i_%s", descr->nodes[t].name);
      dst[0] = (IFparm){nm, (int)(base + t), IF_REAL | IF_ASK,
                        "terminal current"};
      dst += 1;
    }
    if (descr->num_terminals == 2 && !model_has_i) {
      dst[0] = (IFparm){"i", (int)base, IF_REAL | IF_ASK,
                        "current into the first terminal"};
      dst += 1;
    }
  }
  /* Enhancement-731: the module's own declarations, not the loader's rows */
  osdi_warn_case_collisions(own_start, own_count, descr, "instance");

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
                            descr, "model");

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
  /* Enhancement-416: one uint32_t per descriptor node trails the extra data --
   * the collapse-owner map, see osdi_collapse_owner(). num_nodes is a
   * per-descriptor constant, so the instance block stays a fixed size for the
   * device type, exactly as DEVinstSize requires.
   *
   * Enhancement-417 appends a second trailing array: one bool per collapsible
   * pair, the collapse set the mapping above was actually built from. Both are
   * per-descriptor constants, so the block stays a fixed size. */
  *inst_size = (int)(inst_off + descr->instance_size +
                     sizeof(OsdiExtraInstData) +
                     (size_t)descr->num_nodes * sizeof(uint32_t) +
                     (size_t)descr->num_collapsible * sizeof(bool));
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


/* ---- Enhancement-565: paramset overloading on the .model route (LRM 6.4.2) ----
 *
 * The compiler exports an overloaded paramset family as the twins `nch`,
 * `nch__2`, `nch__3`, ... (declaration order), each naming the family, with the
 * literal default of every parameter beside E-558's range texts. A `.model`
 * card that names the family is resolved here by the clause's rules: every
 * parameter the card gives is a parameter of the member; the member's
 * parameters, given or defaulted, lie within their declared ranges; among the
 * survivors the fewest un-overridden parameters win. More than one left, or
 * none, is an error, as the clause says. A bound that is not a literal
 * (`[lmin:inf)`) is unbounded here, as it is for the compiler's own selection
 * of an instance inside a module. */

/* one bound of a range text: a number with its SI suffix, or inf; `fallback`
 * when it is anything else (an expression the card cannot judge) */
static double osdi_range_bound(const char **pp, double fallback)
{
  const char *p = *pp;
  while (*p == ' ' || *p == '\t')
    p++;
  const char *start = p;
  /* `,` and `}` end a member of a value set (Enhancement-643) */
  while (*p && *p != ':' && *p != ']' && *p != ')' && *p != ' ' && *p != '\t' &&
         *p != ',' && *p != '}')
    p++;
  size_t n = (size_t)(p - start);
  *pp = p;
  if (n == 0)
    return fallback;
  char buf[64];
  if (n >= sizeof buf)
    return fallback;
  memcpy(buf, start, n);
  buf[n] = '\0';
  if (!strcmp(buf, "inf") || !strcmp(buf, "+inf"))
    return HUGE_VAL;
  if (!strcmp(buf, "-inf"))
    return -HUGE_VAL;
  char *bp = buf;
  int err = 0;
  double v = INPevaluate(&bp, &err, 1);
  return err ? fallback : v;
}

/* does the E-558 range text -- `from [a:b) exclude c ...` -- accept v? */
static int osdi_range_accepts(const char *text, double v)
{
  int any_from = 0, in_from = 0;
  const char *p = text;
  while (*p) {
    int is_from;
    if (!strncmp(p, "from", 4)) {
      is_from = 1;
      p += 4;
    } else if (!strncmp(p, "exclude", 7)) {
      is_from = 0;
      p += 7;
    } else {
      p++;
      continue;
    }
    while (*p == ' ' || *p == '\t')
      p++;
    int satisfied;
    if (*p == '[' || *p == '(') {
      int lo_inc = (*p == '[');
      p++;
      double lo = osdi_range_bound(&p, -HUGE_VAL);
      while (*p == ' ' || *p == '\t')
        p++;
      if (*p == ':')
        p++;
      double hi = osdi_range_bound(&p, HUGE_VAL);
      while (*p == ' ' || *p == '\t')
        p++;
      int hi_inc = 1;
      if (*p == ']' || *p == ')') {
        hi_inc = (*p == ']');
        p++;
      }
      satisfied = (lo_inc ? v >= lo : v > lo) && (hi_inc ? v <= hi : v < hi);
    } else if (*p == '{') {
      /* Enhancement-643: a value set -- `exclude {0}`, `from {1, 2, 4}` (the
       * compiler writes every single-value constraint this way, E-589). It
       * used to be read as ONE bound, `{0}`, which no number parser accepts,
       * and an unparseable bound counts as satisfied -- so every `exclude`
       * excluded every value, and r3_cmc's `type from [-1:1] exclude 0`
       * disqualified each of the IHP resistor paramsets at its own default.
       * A member the card cannot judge (an expression) gets the benefit of
       * the doubt: a from-set accepts, an exclude-set does not exclude. */
      int unknown = 0;
      p++;
      satisfied = 0;
      for (;;) {
        while (*p == ' ' || *p == '\t' || *p == ',')
          p++;
        if (*p == '}' || !*p)
          break;
        const char *before = p;
        double x = osdi_range_bound(&p, NAN);
        if (isnan(x))
          unknown = 1;
        else if (v == x)
          satisfied = 1;
        if (p == before) /* nothing consumed: a stray character */
          p++;
      }
      if (*p == '}')
        p++;
      if (unknown && !satisfied)
        satisfied = is_from;
    } else {
      double x = osdi_range_bound(&p, NAN);
      satisfied = isnan(x) ? 1 : (v == x);
    }
    if (is_from) {
      any_from = 1;
      if (satisfied)
        in_from = 1;
    } else if (satisfied) {
      return 0;
    }
  }
  return !any_from || in_from;
}

/* Enhancement-643 (LRM 6.4.2): is parameter `pid` of the member one of the
 * paramset's OWN -- declared in the paramset, not a target-module parameter
 * passed through unbound? "The simulator shall consider only the ranges of
 * the paramset's own parameters when choosing a paramset", and the
 * "un-overridden parameters" it counts are the paramset's. Both used to run
 * over every non-fixed parameter: r3_cmc's `type from [-1:1] exclude 0`
 * disqualified every IHP resistor paramset (with the `{0}` mis-parse above),
 * and the mismatch member of `rsil`, which binds six more module parameters,
 * had six fewer "un-overridden" ones and won a card that named neither --
 * where the clause's answer is the tie error. An object without the
 * OSDI_PARAMSET_OWN table (an older compiler) keeps the old reading. */
static int osdi_param_is_own(const OsdiRegistryEntry *e, uint32_t pid)
{
  return !e->param_own || e->param_own[pid];
}

/* the parameter id of `name` (an alias counts) in device type t, or -1. A
 * parameter the paramset FIXED (a bound module parameter, PARA_FLAG_FIXED
 * since Enhancement-93) is not one of the paramset's own and does not count. */
static int osdi_member_param(int t, const char *name)
{
  const OsdiRegistryEntry *e =
      (const OsdiRegistryEntry *)DEVices[t]->DEVpublic.registry_entry;
  const OsdiDescriptor *d = e->descriptor;
  for (uint32_t pid = 0; pid < d->num_params; pid++) {
    const OsdiParamOpvar *po = &d->param_opvar[pid];
    if (po->flags & PARA_FLAG_FIXED)
      continue;
    for (uint32_t k = 0; k <= po->num_alias; k++)
      if (po->name[k] && !strcasecmp(po->name[k], name))
        return (int)pid;
  }
  return -1;
}

/* Enhancement-668 (hunt F10): does member `type`'s parameter `pname` accept
 * `v`? 1 when it does or has no range text to judge by, 0 when its declared
 * range refuses it, -1 when the member has no such parameter. For the
 * out-of-bounds note that names the member a corner's value lands in. */
int osdi_member_accepts(int type, const char *pname, double v)
{
  if (type < 0 || !osdi_devtype_is_osdi(type))
    return -1;
  const OsdiRegistryEntry *e =
      (const OsdiRegistryEntry *)DEVices[type]->DEVpublic.registry_entry;
  if (!e || !e->descriptor)
    return -1;
  const OsdiDescriptor *d = e->descriptor;
  for (uint32_t k = 0; k < d->num_params; k++) {
    const OsdiParamOpvar *po = &d->param_opvar[k];
    for (uint32_t a = 0; a <= po->num_alias; a++) {
      if (!po->name[a] || strcmp(po->name[a], pname) != 0)
        continue;
      if (!e->param_ranges || !e->param_ranges[k] || !*e->param_ranges[k])
        return 1;
      return osdi_range_accepts(e->param_ranges[k], v) ? 1 : 0;
    }
  }
  return -1;
}

/* Enhancement-644: is `type` the head of an overloaded paramset family --
 * the member whose name IS the family name, the one a `.model` card of that
 * name is bound to before anything selects? */
int osdi_paramset_family_head(int type)
{
  if (type < 0 || !osdi_devtype_is_osdi(type))
    return 0;
  const OsdiRegistryEntry *e =
      (const OsdiRegistryEntry *)DEVices[type]->DEVpublic.registry_entry;
  return e && e->paramset_family &&
         strcmp(DEVices[type]->DEVpublic.name, e->paramset_family) == 0;
}

/* Enhancement-644: the head of the family `type` is a member of (the member
 * named as the family), or -1 when `type` is no paramset member. */
int osdi_paramset_family_of(int type)
{
  if (type < 0 || !osdi_devtype_is_osdi(type))
    return -1;
  const OsdiRegistryEntry *e =
      (const OsdiRegistryEntry *)DEVices[type]->DEVpublic.registry_entry;
  if (!e || !e->paramset_family)
    return -1;
  for (int t = 0; t < DEVmaxnum; t++) {
    if (!osdi_devtype_is_osdi(t))
      continue;
    if (!strcmp(DEVices[t]->DEVpublic.name, e->paramset_family))
      return t;
  }
  return -1;
}

int osdi_select_paramset_overload(int type, const char *card,
                                  const char *modname, char **why)
{
  return osdi_select_paramset_member(type, card, NULL, modname, why);
}

/* Enhancement-644: `name=value` pairs of an instance line's parameter part
 * (`n1 a b rsil l=0.5u w=0.5u mm_ok=0`, everything after the nodes), for the
 * selection below -- the values an instance of the paramset sets, which LRM
 * 6.4.2 selects by. Names and values are copies; `n` is the fill so far. */
static void osdi_instance_params(const char *inst, char **names, double *vals,
                                 int *numeric, int *n, int max)
{
  const char *p = inst;
  while (p && *p && *n < max) {
    const char *eq = strchr(p, '=');
    if (!eq)
      break;
    /* the name: the identifier run before `=` */
    const char *ne = eq;
    while (ne > p && (ne[-1] == ' ' || ne[-1] == '\t'))
      ne--;
    const char *ns = ne;
    while (ns > p && ns[-1] != ' ' && ns[-1] != '\t' && ns[-1] != '(' && ns[-1] != ',')
      ns--;
    /* the value: the run after `=` */
    const char *vs = eq + 1;
    while (*vs == ' ' || *vs == '\t')
      vs++;
    const char *ve = vs;
    while (*ve && *ve != ' ' && *ve != '\t' && *ve != ')' && *ve != ',')
      ve++;
    if (ne > ns) {
      char *name = copy_substring(ns, ne);
      char *vt = copy_substring(vs, ve);
      char *vp = vt;
      int err = 0;
      double v = INPevaluate(&vp, &err, 0);
      names[*n] = name;
      vals[*n] = v;
      numeric[*n] = !err;
      (*n)++;
      tfree(vt);
    }
    p = ve;
  }
}

/* Enhancement-644: the selection with the values an INSTANCE line gives as
 * well as the card's -- an instance's own parameters are what 6.4.2 selects
 * by (`rsil #(.mm_ok(1))`), and since Enhancement-644 a paramset's own
 * parameters are instance parameters. An instance value replaces the card's
 * for the same name; an instance name no member declares (`m`, `temp`, a
 * misspelling INPdevParse will refuse later) is left out of the selection.
 * `inst` NULL is the card alone, the `.model` route of Enhancement-565. */
int osdi_select_paramset_member(int type, const char *card, const char *inst,
                                const char *modname, char **why)
{
  *why = NULL;
  if (!osdi_devtype_is_osdi(type))
    return type;
  const OsdiRegistryEntry *head =
      (const OsdiRegistryEntry *)DEVices[type]->DEVpublic.registry_entry;
  if (!head || !head->paramset_family)
    return type;
  const char *family = head->paramset_family;
  /* a card naming a member itself (`nch__2`) is taken at its word */
  if (strcmp(DEVices[type]->DEVpublic.name, family) != 0)
    return type;

  enum { MAXM = 64, MAXP = 256 };
  int members[MAXM];
  int n_members = 0;
  for (int t = 0; t < DEVmaxnum && n_members < MAXM; t++) {
    if (!osdi_devtype_is_osdi(t))
      continue;
    const OsdiRegistryEntry *e =
        (const OsdiRegistryEntry *)DEVices[t]->DEVpublic.registry_entry;
    if (e && e->paramset_family && !strcmp(e->paramset_family, family))
      members[n_members++] = t;
  }
  if (n_members < 2)
    return type;

  /* the card's parameters: name and value */
  char *text = copy(card);
  char *line = text;
  char *tok = NULL;
  INPgetTok(&line, &tok, 1);    /* .model */
  tfree(tok);
  INPgetNetTok(&line, &tok, 1); /* the model name */
  tfree(tok);
  INPgetTok(&line, &tok, 1);    /* the type */
  tfree(tok);
  char *names[MAXP];
  double vals[MAXP];
  int numeric[MAXP];
  int n = 0;
  /* `=`, `(` and `)` are token separators, so the card is name, value, name,
   * value, ...; a name no member declares is kept, for rule 1 to refuse */
  while (*line && n < MAXP) {
    INPgetNetTok(&line, &tok, 1);
    if (!tok)
      break;
    if (!*tok) {
      tfree(tok);
      continue;
    }
    names[n] = tok;
    char *vt = NULL;
    INPgetNetTok(&line, &vt, 1);
    numeric[n] = 0;
    vals[n] = 0.0;
    if (vt && *vt) {
      char *vp = vt;
      int err = 0;
      double v = INPevaluate(&vp, &err, 1);
      numeric[n] = !err;
      vals[n] = v;
    }
    if (vt)
      tfree(vt);
    n++;
  }
  /* Enhancement-644: the instance's values, replacing the card's for the
   * same name, and only for names some member declares */
  if (inst) {
    char *inames[MAXP];
    double ivals[MAXP];
    int inumeric[MAXP];
    int ni = 0;
    osdi_instance_params(inst, inames, ivals, inumeric, &ni, MAXP);
    for (int i = 0; i < ni; i++) {
      int known = 0;
      for (int k = 0; k < n_members && !known; k++)
        known = osdi_member_param(members[k], inames[i]) >= 0;
      if (!known) {
        tfree(inames[i]);
        continue;
      }
      int j;
      for (j = 0; j < n; j++)
        if (!strcasecmp(names[j], inames[i]))
          break;
      if (j < n) {
        tfree(names[j]);
        names[j] = inames[i];
        vals[j] = ivals[i];
        numeric[j] = inumeric[i];
      } else if (n < MAXP) {
        names[n] = inames[i];
        vals[n] = ivals[i];
        numeric[n] = inumeric[i];
        n++;
      } else {
        tfree(inames[i]);
      }
    }
  }

  int survivors[MAXM], unoverridden[MAXM];
  int n_surv = 0;
  char *reasons = NULL;
  for (int k = 0; k < n_members; k++) {
    int t = members[k];
    const OsdiRegistryEntry *e =
        (const OsdiRegistryEntry *)DEVices[t]->DEVpublic.registry_entry;
    const OsdiDescriptor *d = e->descriptor;
    const char *label = DEVices[t]->DEVpublic.name;
    char *reason = NULL;
    bool *given = TMALLOC(bool, d->num_params + 1);
    memset(given, 0, (d->num_params + 1) * sizeof(bool));
    for (int i = 0; i < n && !reason; i++) {
      int pid = osdi_member_param(t, names[i]);
      if (pid < 0) {
        reason = tprintf("%s: '%s' is not one of its parameters", label, names[i]);
        break;
      }
      given[pid] = TRUE;
      const char *rt = e->param_ranges ? e->param_ranges[pid] : NULL;
      if (numeric[i] && rt && *rt && osdi_param_is_own(e, (uint32_t)pid) &&
          !osdi_range_accepts(rt, vals[i]))
        reason = tprintf("%s: %s = %g is outside %s", label, names[i], vals[i], rt);
    }
    if (!reason && e->param_defaults && e->param_ranges) {
      for (uint32_t pid = 0; pid < d->num_params; pid++) {
        if (given[pid] || (d->param_opvar[pid].flags & PARA_FLAG_FIXED) ||
            !osdi_param_is_own(e, pid))
          continue;
        double dv = e->param_defaults[pid];
        const char *rt = e->param_ranges[pid];
        if (isnan(dv) || !rt || !*rt)
          continue;
        if (!osdi_range_accepts(rt, dv)) {
          reason = tprintf("%s: the default %s = %g is outside %s", label,
                           d->param_opvar[pid].name[0], dv, rt);
          break;
        }
      }
    }
    if (reason) {
      char *joined = reasons ? tprintf("%s; %s", reasons, reason) : copy(reason);
      tfree(reasons);
      tfree(reason);
      reasons = joined;
    } else {
      int un = 0;
      for (uint32_t pid = 0; pid < d->num_params; pid++)
        if (!given[pid] && !(d->param_opvar[pid].flags & PARA_FLAG_FIXED) &&
            osdi_param_is_own(e, pid))
          un++;
      survivors[n_surv] = t;
      unoverridden[n_surv] = un;
      n_surv++;
    }
    tfree(given);
  }
  for (int i = 0; i < n; i++)
    tfree(names[i]);
  tfree(text);

  if (n_surv == 0) {
    *why = tprintf("no paramset '%s' applies to .model %s (LRM 6.4.2): %s\n",
                   family, modname, reasons ? reasons : "none declared");
    fprintf(stderr, "Error: %s", *why);
    tfree(reasons);
    return -1;
  }
  tfree(reasons);
  int best = unoverridden[0], n_best = 1, winner = survivors[0];
  for (int i = 1; i < n_surv; i++) {
    if (unoverridden[i] < best) {
      best = unoverridden[i];
      winner = survivors[i];
      n_best = 1;
    } else if (unoverridden[i] == best) {
      n_best++;
    }
  }
  if (n_best > 1) {
    /* Enhancement-643: name what would tell the tied members apart -- each
     * one's own ranged parameters (`rsil takes mm_ok from [0:0]; rsil__2
     * takes mm_ok from [1:1]`), which is how an overloaded family is meant
     * to be selected (the clause's own `nch` example) */
    char *hint = NULL;
    for (int i = 0; i < n_surv; i++) {
      if (unoverridden[i] != best)
        continue;
      int t = survivors[i];
      const OsdiRegistryEntry *e =
          (const OsdiRegistryEntry *)DEVices[t]->DEVpublic.registry_entry;
      const OsdiDescriptor *d = e->descriptor;
      char *ranged = NULL;
      for (uint32_t pid = 0; e->param_ranges && pid < d->num_params; pid++) {
        const char *rt = e->param_ranges[pid];
        if ((d->param_opvar[pid].flags & PARA_FLAG_FIXED) || !osdi_param_is_own(e, pid) ||
            !rt || !*rt)
          continue;
        /* a range every tied member declares alike selects nothing */
        int common = 1;
        for (int j = 0; j < n_surv && common; j++) {
          if (j == i || unoverridden[j] != best)
            continue;
          const OsdiRegistryEntry *ej =
              (const OsdiRegistryEntry *)DEVices[survivors[j]]->DEVpublic.registry_entry;
          int pj = osdi_member_param(survivors[j], d->param_opvar[pid].name[0]);
          const char *rj = pj >= 0 && ej->param_ranges ? ej->param_ranges[pj] : NULL;
          if (!rj || strcmp(rj, rt) != 0)
            common = 0;
        }
        if (common)
          continue;
        char *next = ranged ? tprintf("%s, %s %s", ranged, d->param_opvar[pid].name[0], rt)
                            : tprintf("%s %s", d->param_opvar[pid].name[0], rt);
        tfree(ranged);
        ranged = next;
      }
      char *next = hint ? tprintf("%s; %s takes %s", hint, DEVices[t]->DEVpublic.name,
                                  ranged ? ranged : "no range of its own")
                        : tprintf("%s takes %s", DEVices[t]->DEVpublic.name,
                                  ranged ? ranged : "no range of its own");
      tfree(hint);
      tfree(ranged);
      hint = next;
    }
    *why = tprintf("paramset '%s' is ambiguous for .model %s (LRM 6.4.2): %d members apply "
                   "with %d un-overridden parameter(s) each -- give a parameter whose value "
                   "only one of them accepts: %s\n",
                   family, modname, n_best, best, hint ? hint : "");
    tfree(hint);
    fprintf(stderr, "Error: %s", *why);
    return -1;
  }
  if (winner != type && !inst)
    fprintf(stderr, "Note: .model %s: paramset '%s' resolved to its member '%s' (LRM 6.4.2)\n",
            modname, family, DEVices[winner]->DEVpublic.name);
  return winner;
}
