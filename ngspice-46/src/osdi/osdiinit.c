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
static void osdi_warn_case_collisions(const IFparm *params, int n,
                                      const char *module, const char *kind) {
  for (int i = 1; i < n; i++) {
    if (!params[i].keyword)
      continue;
    for (int j = 0; j < i; j++) {
      if (params[j].keyword && !strcmp(params[j].keyword, params[i].keyword)) {
        if (params[j].id == params[i].id) {
          /* the same parameter under two spellings -- deliberately routed */
          continue;
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
  if (descr->num_terminals == 2) {
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
  write_param_info(&dst, descr, 0, descr->num_instance_params, entry->has_m);
  write_param_info(&dst, descr, descr->num_params,
                   descr->num_params + descr->num_opvars, true);

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
    if (descr->num_terminals == 2) {
      dst[0] = (IFparm){"i", (int)base, IF_REAL | IF_ASK,
                        "current into the first terminal"};
      dst += 1;
    }
  }
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
  while (*p && *p != ':' && *p != ']' && *p != ')' && *p != ' ' && *p != '\t')
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

int osdi_select_paramset_overload(int type, const char *card,
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
      if (numeric[i] && rt && *rt && !osdi_range_accepts(rt, vals[i]))
        reason = tprintf("%s: %s = %g is outside %s", label, names[i], vals[i], rt);
    }
    if (!reason && e->param_defaults && e->param_ranges) {
      for (uint32_t pid = 0; pid < d->num_params; pid++) {
        if (given[pid] || (d->param_opvar[pid].flags & PARA_FLAG_FIXED))
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
        if (!given[pid] && !(d->param_opvar[pid].flags & PARA_FLAG_FIXED))
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
    *why = tprintf("paramset '%s' is ambiguous for .model %s (LRM 6.4.2): %d members apply "
                   "with %d un-overridden parameter(s) each -- give a parameter only one "
                   "of them declares\n",
                   family, modname, n_best, best);
    fprintf(stderr, "Error: %s", *why);
    return -1;
  }
  if (winner != type)
    fprintf(stderr, "Note: .model %s: paramset '%s' resolved to its member '%s' (LRM 6.4.2)\n",
            modname, family, DEVices[winner]->DEVpublic.name);
  return winner;
}
