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
#include "ngspice/fteext.h"   /* Enhancement-600: ft_save_probe */

#include "osdidefs.h"

#include <math.h>   /* round-3 audit: floor(), for the LRM 9.18 angle wrap */
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

    /* Enhancement-476: refuse an instance-scope write to a MODEL-scope
     * parameter that Enhancement-397 routed onto this knob.
     *
     * When a model declares `dtemp` (or `temperature`) itself,
     * osdi_create_registry_entry sets entry->dt (entry->temp) to THAT
     * parameter's id instead of the id it synthesizes -- deliberate, because
     * the industry corpus (PSP, MEXTRAM, VBIC, HiSIM, BSIM) declares `dtemp`
     * and the model's own parameter must win.
     *
     * The routing also puts the name in the INSTANCE parameter table, so
     * `alter @n1[dtemp]=20` found it, fell into the branch below and stored
     * the value in the loader's `inst->dt` -- which nothing reads once the
     * model owns the name. The write was accepted, changed nothing, and said
     * nothing, while `@n1[dtemp]` went on reporting the old value. Every
     * OTHER model-scope parameter reaching this setter already returns
     * E_BADPARM (the fall-through below), so `alter @n1[r1]` has always been
     * refused honestly; only the two routed names were silent.
     *
     * `param < num_params` is what separates the two cases: a routed id is a
     * real declared parameter, the loader's own ids are allocated above the
     * parameter, opvar and terminal ranges (osdiregistry.c). A model that
     * declares `dtemp` as an INSTANCE parameter never reaches here at all --
     * its id is below num_instance_params -- and keeps working, which is the
     * case the corpus actually uses.
     *
     * doset() discards the setter's return code at the `alter` call site, so
     * the diagnostic has to be issued here to be issued at all; the wording
     * matches Enhancement-467's for the same mistake. */
    if (param < (int)descr->num_params) {
      fprintf(stderr,
              "Error: '%s' is a MODEL parameter of model '%s'; `alter` sets "
              "instance parameters. Use `altermod %s %s=...` instead.\n",
              descr->param_opvar[param].name[0],
              (char *)instPtr->GENmodPtr->GENmodName,
              (char *)instPtr->GENmodPtr->GENmodName,
              descr->param_opvar[param].name[0]);
      return (E_BADPARM);
    }

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

  /* OSDI-layer audit: a NEGATIVE multiplicity is refused here. The parser
   * layer (inpdpar.c, Enhancement-447) already warns on a deck-written
   * negative m -- but `alter @n1[m]=-2` reaches this function directly, so
   * the value was silently APPLIED: the device's contribution sign-inverted
   * (a resistor model SOURCED 4 mA) and the compiled noise factor sqrt(m)
   * turned a .noise run into 'onoise_spectrum = nan' with no diagnostic on
   * either channel. Warn and keep the previous value on every route.
   * ZERO is applied: Enhancement-426 established m=0 as the "disable this
   * instance" idiom, exactly as for the built-ins.
   * Enhancement-755: this is the ONE warning a compiled instance gets. The
   * parser layer used to print its built-in sentence first ("the device's
   * contribution is sign-inverted"), which is what a built-in does and this
   * setter does not, so `nr1 a 0 nmod m=-1` carried two warnings that
   * contradicted each other; inpdpar.c now leaves a DEV_OSDI device's
   * negative m to this line, which names the instance and says what is
   * done. */
  if (!strcmp(descr->param_opvar[param].name[0], "$mfactor") &&
      value->rValue < 0.0) {
    fprintf(stderr,
            "Warning: %s: multiplier m=%g is negative; the value is ignored "
            "and the instance keeps the multiplier it had (a negative "
            "multiplicity would sign-invert the device and make its noise "
            "NaN).\n",
            instPtr->GENname ? instPtr->GENname : "instance", value->rValue);
    return (OK);
  }

  /* Enhancement-751 (options-and-convergence hunt F5): m=0 stays the idiom
   * and is applied, but it is no longer silent. A compiled instance given
   * m=0 -- on its line, as `_mfactor=0`, through a subcircuit called with
   * m=0, from a `.model` card's `_mfactor=0` default, or by `alter` at run
   * time, every route ends here -- vanished from the circuit without a word:
   * v(a) rose to the source, @nr1[i] read 0, and nothing named the device.
   * A multiplier that a parameter expression evaluated to zero looked exactly
   * like one written on purpose. Said once per instance, as a Note (a deck
   * that means it is not wrong), on stderr beside the multiplier warnings,
   * and capped so a generator that disables a thousand devices gets ten
   * lines and one more saying so. The built-ins keep E-426's silence: the
   * parser-layer check in inpdpar.c is unchanged. */
  if (!strcmp(descr->param_opvar[param].name[0], "$mfactor") &&
      value->rValue == 0.0) {
    static int e751_notes = 0;
    const char *who = instPtr->GENname ? instPtr->GENname : "instance";
    if (e751_notes < 10)
      fprintf(stderr,
              "Note: %s: m=0 disables the instance -- it stays in the "
              "netlist and contributes nothing (a positive m re-enables "
              "it).\n",
              who);
    else if (e751_notes == 10)
      fprintf(stderr,
              "Note: further instances disabled by m=0 are not listed.\n");
    e751_notes++;
  }

  /* ROUND-3 AUDIT (2026-09-02) / LRM 9.18 Table 9-29: the rest of the
     *Allowed values* column, which nothing checked on this route either.
     `_hflip=5` and `_vflip=0` were applied verbatim, though the table gives
     both as "+1 or -1" -- they say whether the instance is mirrored, and no
     other value means anything. Warned and ignored, the same shape as the
     multiplier above, so a deck that sets one keeps running with the value it
     had. */
  if ((!strcmp(descr->param_opvar[param].name[0], "$hflip") ||
       !strcmp(descr->param_opvar[param].name[0], "$vflip")) &&
      value->rValue != 1.0 && value->rValue != -1.0) {
    fprintf(stderr,
            "Warning: %s=%g is not +1 or -1; the value is ignored "
            "(LRM 9.18 Table 9-29 -- a flip says whether the instance is "
            "mirrored about its center).\n",
            descr->param_opvar[param].name[0], value->rValue);
    return (OK);
  }

  /* LRM 9.18 Table 9-29 again: $angle resolves "modulo 360 degrees" into
     0 <= $angle < 360. `_angle=400` was stored and read back as 400, so a
     model that COMPARES the angle (a quadrant test, a lookup keyed on
     orientation) took the wrong branch -- one that only feeds it to a
     trigonometric function never noticed. Normalised rather than refused:
     400 degrees is a legal rotation, it is simply spelled 40 here. */
  if (!strcmp(descr->param_opvar[param].name[0], "$angle") &&
      (value->rValue < 0.0 || value->rValue >= 360.0)) {
    double a = value->rValue - 360.0 * floor(value->rValue / 360.0);
    if (a < 0.0 || a >= 360.0) {
      a = 0.0; /* only reachable for a non-finite input */
    }
    value->rValue = a;
  }

  void *inst = osdi_instance_data(entry, instPtr);
  void *dst = descr->access(inst, NULL, (uint32_t)param,
                            ACCESS_FLAG_SET | ACCESS_FLAG_INSTANCE);

  /* NOTE (bug-hunt F1): the osdimc nominal-recenter hook deliberately does
   * NOT live here. This setter serves every machine route as well -- .dc
   * parameter sweeps (DCTsetInstParam), the `sweep` command's per-point and
   * restore writes, and sensitivity perturbations -- and recentering on those
   * turned a sweep's save/restore into a permanent nominal shift (a random
   * walk seeded by one sweep). Only the USER commands recenter, via
   * doset_user() -> OSDImcNoteUserWrite() in frontend/spiceif.c.
   *
   * E-535 fix (hunt bug 14): those same routes must WIN over the current
   * trial's draw for as long as their command runs, or a swept statistical
   * parameter is clobbered back to nominal+delta at every point -- so a
   * successful write PINS the parameter's osdimc entry (a no-op for anything
   * without one). See OSDImcNoteParamWrite in osdisetup.c for the pin
   * lifecycle. */
  {
    int err535 = osdi_write_param(dst, value, param, descr);
    if (err535 == OK)
      OSDImcNoteParamWrite(inst, (uint32_t)param, dst);
    return err535;
  }
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

  /* recentering: see the F1 note in OSDIparam above -- user routes only.
   * E-535 fix (hunt bug 14): machine writes pin, as in OSDIparam above. */
  {
    int err535 = osdi_write_param(dst, value, param, descr);
    if (err535 == OK)
      OSDImcNoteParamWrite(model, (uint32_t)param, dst);
    return err535;
  }
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

/* Enhancement-835 (hunt 2026-10-08 F19): the SMALL-SIGNAL current into
 * terminal t in an ac or sp analysis.
 *
 * In those analyses the solution holds the complex small-signal response, and
 * the reading below -- the residual the bias point left in the instance --
 * answered the DC bias current, real and flat at every frequency: `.save
 * @n1[i_a]` in an ac (and `.options savecurrents`, before E-808 left it out)
 * recorded 1 mA + 0j at 1 kHz and at 1 MHz where the true current was
 * 0.5 mA and 0.954 + 0.145j mA. A built-in device refuses the question
 * (E_ASKCURRENT) and records nothing.
 *
 * An OSDI device can answer it. The ac load stamps the Jacobian the bias
 * point left in the instance, G + jwC, and the small-signal current into the
 * terminal is that Jacobian's rows of the terminal's collapse group times the
 * solution, plus what an active ac_stim() source injects at those nodes --
 * exactly the quantity the ac load puts into the group's KCL row. The values
 * come from write_jacobian_array_*, which read the same stored entries the
 * loads do, m included; their index is a running count of the entries that
 * have a resistive (or reactive) part. The answer is complex: `osdi_ask_complex`
 * tells the output code to record it so. */
bool osdi_ask_complex;

static int osdi_ask_ac_current(CKTcircuit *ckt, OsdiRegistryEntry *entry,
                               GENinstance *instPtr, void *inst, void *model,
                               const uint32_t *owner, uint32_t t,
                               IFvalue *value) {
  const OsdiDescriptor *descr = entry->descriptor;
  uint32_t n = descr->num_jacobian_entries, e, ri = 0, xi = 0;
  uint32_t *node_mapping =
      (uint32_t *)(((char *)inst) + descr->node_mapping_offset);
  double *jr = TMALLOC(double, n ? 2 * n : 2), *jx = jr + (n ? n : 1);
  double w = ckt->CKTomega, re = 0.0, im = 0.0;

  NG_IGNORE(instPtr);
  descr->write_jacobian_array_resist(inst, model, jr);
  descr->write_jacobian_array_react(inst, model, jx);
  for (e = 0; e < n; e++) {
    const OsdiJacobianEntry *je = &descr->jacobian_entries[e];
    double g = (je->flags & JACOBIAN_ENTRY_RESIST) ? jr[ri++] : 0.0;
    double c = (je->flags & JACOBIAN_ENTRY_REACT) ? jx[xi++] : 0.0;
    uint32_t u;
    double vr, vi;
    if (owner[je->nodes.node_1] != t + 1)
      continue;
    u = node_mapping[je->nodes.node_2];
    if (u == UINT32_MAX || u == 0)
      continue;
    vr = ckt->CKTrhsOld[u];
    vi = ckt->CKTirhsOld[u];
    re += g * vr - w * c * vi;
    im += g * vi + w * c * vr;
  }
  tfree(jr);
  /* an active ac_stim() source, with the rule the ac load applies */
  if (descr->num_ac_stim_src > 0) {
    uint32_t k, ns = descr->num_ac_stim_src;
    double *stim = TMALLOC(double, 2 * ns);
    const char *running = (ckt->CKTmode & MODEACNOISE) ? "noise" : "ac";
    descr->load_ac_stim(inst, model, stim);
    for (k = 0; k < ns; k++) {
      const OsdiAcStimSource *src = &descr->ac_stim_sources[k];
      if (strcmp(src->analysis, running) != 0)
        continue;
      if (owner[src->nodes.node_1] == t + 1) {
        re += stim[2 * k];
        im += stim[2 * k + 1];
      }
      if (src->nodes.node_2 != UINT32_MAX && owner[src->nodes.node_2] == t + 1) {
        re -= stim[2 * k];
        im -= stim[2 * k + 1];
      }
    }
    tfree(stim);
  }
  value->cValue.real = re;
  value->cValue.imag = im;
  osdi_ask_complex = true;
  return (OK);
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
   * The current into terminal t is what the device stamped into the KCL row
   * that terminal's collapse GROUP shares (see Enhancement-416 below): the
   * resistive residual, plus -- in a transient -- the integrated derivative of
   * the reactive residual (the charge), which OSDIload places in
   * CKTstate0[state+1] while walking the reactive nodes in descriptor order.
   * The same walk is repeated here so the two agree exactly; outside a
   * transient there is no reactive contribution, matching the DC stamp. */
  uint32_t cur_base = descr->num_params + descr->num_opvars;

  /* Enhancement-397: the loader's own `dt`/`dtemp` and `temp`, read back with
   * the same conventions a built-in uses -- verified against a resistor:
   *
   *   @r1[temp]   the BASE temperature in degrees Celsius, following the
   *               ambient (.temp / .option temp) when the instance does not
   *               set it, and NOT including dtemp;
   *   @r1[dtemp]  the offset, zero when not given.
   *
   * The `>= cur_base` guard keeps this to the ids the LOADER synthesized. When
   * the model declares `dtemp`/`temperature` itself, osdi_create_registry_entry
   * routes entry->dt / entry->temp to that model parameter, whose id is below
   * cur_base -- those fall through to the ordinary readable-parameter path
   * below, which is what should serve them. */
  if (entry->dt != UINT32_MAX && entry->dt >= cur_base && id == (int)entry->dt) {
    OsdiExtraInstData *xtra = osdi_extra_instance_data(entry, instPtr);
    value->rValue = xtra->dt_given ? xtra->dt : 0.0;
    return (OK);
  }
  if (entry->temp != UINT32_MAX && entry->temp >= cur_base &&
      id == (int)entry->temp) {
    OsdiExtraInstData *xtra = osdi_extra_instance_data(entry, instPtr);
    value->rValue = xtra->temp_given
                        ? xtra->temp - CONSTCtoK
                        : (ckt ? ckt->CKTtemp - CONSTCtoK : 27.0);
    return (OK);
  }

  if (id >= (int)cur_base) {
    uint32_t t = (uint32_t)id - cur_base;
    if (t >= descr->num_terminals) {
      return (E_BADPARM);
    }

    /* Enhancement-416: sum the terminal's whole COLLAPSE GROUP, not just its
     * own node.
     *
     * `if (rd == 0) V(d,di) <+ 0; else I(d,di) <+ V(d,di)/rd;` is the standard
     * compact-model idiom for an optional series resistance, and rd = 0 is the
     * shipped default of most real models. On that path terminal d is collapsed
     * onto internal node di, and the model writes its current into di's
     * residual -- d's own slot stays zero. Reading d alone therefore reported
     * exactly 0.0 for a terminal that was carrying the device's full current.
     * With rd and rs both zero, every terminal carrying only the through
     * current read 0.0, and in DC the reported currents then summed to zero --
     * so a KCL check did not flag it either. A terminal with a contribution of
     * its own (a gate charge, a leakage path) still read correctly, which is
     * part of why this went unnoticed.
     *
     * The loader has always stamped the group as one row
     * (`CKTrhs[node_mapping[i]] -= ...` in osdiload.c), which is why the
     * SOLUTION was right throughout -- only this readback was wrong. Summing
     * the group is precisely the quantity the loader puts into that row: the
     * current the device presents at the node the terminal connects to.
     *
     * owner[i] == t + 1 marks node i as belonging to terminal t (see
     * osdi_collapse_owner). An uncollapsed terminal owns only itself, so the
     * sum reduces to what this code read before. */
    const uint32_t *owner = osdi_collapse_owner(entry, instPtr);
    bool tran = ckt && (ckt->CKTmode & MODETRAN) && ckt->CKTstates[0];
    int state = instPtr->GENstate + (int)descr->num_states;
    double cur = 0.0;

    if (ckt && (ckt->CKTcurrentAnalysis & DOING_AC) && ckt->CKTrhsOld &&
        ckt->CKTirhsOld && descr->write_jacobian_array_resist &&
        descr->write_jacobian_array_react)
      return osdi_ask_ac_current(ckt, entry, instPtr, inst, model, owner, t,
                                 value);

    for (uint32_t i = 0; i < descr->num_nodes; i++) {
      bool has_react = descr->nodes[i].react_residual_off != UINT32_MAX;

      if (owner[i] == t + 1) {
        uint32_t off = descr->nodes[i].resist_residual_off;
        if (off != UINT32_MAX) {
          cur += *((double *)(((char *)inst) + off));
        }
        if (tran && has_react) {
          cur += ckt->CKTstate0[state + 1];
        }
      }

      /* Advance for EVERY reactive node, in the group or not: this walks the
       * same state cursor osdiload.c does, and there it steps on each node with
       * a reactive residual regardless of anything else. Skipping a non-member
       * would desynchronize the two and charge the wrong node's dQ/dt. */
      if (has_react) {
        state += 2;
      }
    }

    value->rValue = cur;
    return (OK);
  }
  /* Enhancement-476: an operating-point variable is an OUTPUT, and must not
   * answer with a number when nothing has computed it.
   *
   * The opvar storage lives in the calloc'd instance block, so before any
   * evaluation it reads a clean 0.0 -- and 0.0 is a perfectly plausible
   * current, voltage or conductance. `print @n1[op_id]` after
   * `op simulation(s) aborted`, or with no analysis run at all, therefore
   * handed back a number indistinguishable from a real result, while `i(v1)`
   * in the same `print` honestly reported "vector ... is not available" and
   * the equivalent built-in read yielded nothing.
   *
   * Parameters are deliberately NOT gated: they are INPUTS and are readable
   * the moment the deck is parsed, which is what `@n1[r1]` and every suite
   * that reads a parameter before running rely on. Terminal currents are
   * handled above and already report 0.0 from an unfilled block by design
   * (Enhancement-416).
   *
   * E_NOTFOUND rather than E_BADPARM: the parameter exists, it just has no
   * value yet, and spiceif.c's doask() uses that distinction to skip the
   * entry in a `show` dump instead of calling it an internal error. */
  if (id >= (int)descr->num_params && id < (int)cur_base) {
    OsdiExtraInstData *xtra = osdi_extra_instance_data(entry, instPtr);
    if (!xtra->opvars_valid) {
      /* Enhancement-600: quiet under beginPlot's save probe, which says the
       * same thing in its own words -- a `save @n1[x]` before any analysis
       * printed both. */
      if (!ft_save_probe)
        fprintf(stderr,
                "Warning: @%s[%s] is an operating-point variable and no "
                "operating point has been computed for %s, so it has no "
                "value.\n",
                instPtr->GENname, descr->param_opvar[id].name[0],
                instPtr->GENname);
      return (E_NOTFOUND);
    }
  }

  uint32_t flags = ACCESS_FLAG_READ;
  if (id < (int)descr->num_instance_params) {
    flags |= ACCESS_FLAG_INSTANCE;
  }

  void *src = descr->access(inst, model, (uint32_t)id, flags);
  return osdi_read_param(src, value, id, descr);
}

/* Enhancement-413: the terminal names of an OSDI instance, or 0 if `name` is
 * not one. Needed because `.options savecurrents` runs as a TEXTUAL pre-pass
 * over the deck, long before any `.osdi` is loaded, so it cannot know a compact
 * model's terminal names -- it emits the bare `@dev[i]` that R/C/L use, which
 * Enhancement-394 only defines for TWO-terminal devices. For anything wider the
 * save named a parameter that does not exist and the vector stayed empty. The
 * expansion therefore has to happen once the descriptor is known; ft_getSaves()
 * calls this at analysis start, when the circuit is set up.
 *
 * `*names` is filled with `*count` freshly allocated strings; the caller frees
 * both the strings and the array. */
/* Enhancement-417: did the last setup_instance re-decide this instance's node
 * collapse away from the one the matrix was built for? Consumed (and cleared)
 * by cktsens.c, which perturbs a parameter and then calls DEVtemperature: if
 * the perturbation moved the collapse, the perturbed device stamps a topology
 * the matrix does not have, and the difference it computes is roundoff rather
 * than a derivative.
 *
 * Returns 0 for anything that is not an OSDI instance, so the caller needs no
 * device-type test of its own. */
/* Enhancement-810 (hunt 2026-10-08 D17): the declared `units` of parameter or
 * operating-point variable `param` of an OSDI instance -- "" when it declares
 * none -- or NULL when the instance is not an OSDI one or `param` is not one
 * of its parameters or opvars (a terminal current, `dt`, `temp`: names the
 * loader adds). The output layer types a saved vector by it. */
const char *OSDIparamUnits(GENinstance *instPtr, const char *param) {
  OsdiRegistryEntry *entry;
  const OsdiDescriptor *descr;

  if (!instPtr || !instPtr->GENmodPtr || !param)
    return NULL;
  if (!osdi_devtype_is_osdi(instPtr->GENmodPtr->GENmodType))
    return NULL;
  entry = osdi_reg_entry_inst(instPtr);
  if (!entry || !(descr = entry->descriptor))
    return NULL;
  for (uint32_t k = 0; k < descr->num_params + descr->num_opvars; k++) {
    const OsdiParamOpvar *po = &descr->param_opvar[k];
    for (uint32_t a = 0; a <= po->num_alias; a++)
      if (po->name[a] && cieq(po->name[a], (char *) param))
        return po->units ? po->units : "";
  }
  return NULL;
}

/* Enhancement-815 (hunt 2026-10-08 F24): is parameter `id` of OSDI instance
 * `instPtr` one of the loader's temperature knobs? 2 for the offset -- the id
 * Enhancement-397 answers to as `dt` and `dtemp`, or the model's own `dtemp`
 * it routes there -- 1 for the loader's absolute `temp` (Celsius, E-394), 0
 * for anything else or an instance that is not an OSDI one. By id rather than
 * by keyword: the instance-line guard tested the word `dtemp`, so `dt=-400`
 * on the same knob reached the model at -99.85 K. A model's own parameter
 * named `temperature` keeps its own meaning and is not judged here. */
int OSDItempParamKind(GENinstance *instPtr, int id) {
  OsdiRegistryEntry *entry;
  const OsdiDescriptor *descr;

  if (!instPtr || !instPtr->GENmodPtr || id < 0)
    return 0;
  if (!osdi_devtype_is_osdi(instPtr->GENmodPtr->GENmodType))
    return 0;
  entry = osdi_reg_entry_inst(instPtr);
  if (!entry || !(descr = entry->descriptor))
    return 0;
  if (entry->dt != UINT32_MAX && (uint32_t)id == entry->dt)
    return 2;
  if (entry->temp != UINT32_MAX &&
      entry->temp >= descr->num_params + descr->num_opvars &&
      (uint32_t)id == entry->temp)
    return 1;
  return 0;
}

int OSDIcollapseChanged(GENinstance *instPtr) {
  OsdiRegistryEntry *entry;
  OsdiExtraInstData *xtra;
  int changed;

  if (!instPtr || !instPtr->GENmodPtr)
    return 0;
  if (!osdi_devtype_is_osdi(instPtr->GENmodPtr->GENmodType))
    return 0;

  entry = osdi_reg_entry_inst(instPtr);
  if (!entry)
    return 0;
  xtra = osdi_extra_instance_data(entry, instPtr);
  changed = xtra->collapse_changed ? 1 : 0;
  xtra->collapse_changed = false;
  return changed;
}

/* Enhancement-471: did ANY OSDI instance's node collapse move?
 *
 * OSDItemp already re-decides the collapse of every instance and records a
 * mismatch against the snapshot the matrix was built from (Enhancement-417).
 * Until now that could only be reported -- "the matrix was built for the
 * collapse decided at setup and cannot be rebuilt here". CKTdoJob uses this to
 * do exactly what that message said was impossible: notice the change and
 * rebuild.
 *
 * Every instance is visited and its flag consumed, with no early exit, so one
 * changed device cannot leave another's flag set for a later analysis to
 * misread. */
int OSDIanyCollapseChanged(CKTcircuit *ckt) {
  int type, changed = 0;
  GENmodel *model;
  GENinstance *inst;

  if (!ckt)
    return 0;
  for (type = 0; type < DEVmaxnum; type++) {
    if (!ckt->CKThead[type] || !osdi_devtype_is_osdi(type))
      continue;
    for (model = ckt->CKThead[type]; model; model = model->GENnextModel)
      for (inst = model->GENinstances; inst; inst = inst->GENnextInstance)
        if (OSDIcollapseChanged(inst))
          changed = 1;
  }
  return changed;
}

int OSDIterminalNames(CKTcircuit *ckt, const char *name, char ***names,
                      int *count) {
  GENinstance *inst;
  int type;

  if (names)
    *names = NULL;
  if (count)
    *count = 0;
  if (!ckt || !name || !*name || !names || !count)
    return 0;

  inst = ft_sim->findInstance(ckt, (char *)name);
  if (!inst || !inst->GENmodPtr)
    return 0;
  type = inst->GENmodPtr->GENmodType;
  if (!osdi_devtype_is_osdi(type))
    return 0;

  {
    OsdiRegistryEntry *entry = osdi_reg_entry_inst(inst);
    const OsdiDescriptor *descr = entry ? entry->descriptor : NULL;
    uint32_t t;
    if (!descr || descr->num_terminals == 0)
      return 0;
    *names = TMALLOC(char *, descr->num_terminals);
    if (!*names)
      return 0;
    for (t = 0; t < descr->num_terminals; t++)
      (*names)[t] = copy(descr->nodes[t].name);
    *count = (int)descr->num_terminals;
    return *count;
  }
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
