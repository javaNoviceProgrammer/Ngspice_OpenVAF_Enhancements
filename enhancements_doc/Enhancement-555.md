# Enhancement-555: a machine write leaves givenness as it found it, and a default is judged against a range that moved

**Scope:** F1 and F2 of the
[bug hunt of 2026-09-05](../docs/bug_hunts/2026-09-05_strings-mcexpr-and-osdimc-distributions.md).
The compiler's parameter analysis (`openvaf/sim_back/src/module_info.rs`),
the HIR (`openvaf/hir/src/body.rs`), the parameter lowering
(`openvaf/hir_lower/src/parameters.rs`), the OSDI export
(`openvaf/osdi/src/{given.rs,lib.rs,metadata.rs,bitfield.rs,inst_data.rs,model_data.rs}`);
the simulator's registry, draw code and sweep restores
(`src/osdi/{osdi.h,osdiregistry.c,osdisetup.c}`, `src/spicelib/analysis/dctrcurv.c`,
`src/frontend/com_sweep.c`). **Compiler and ngspice together.**

**Suites:** [`paramgiven_examples`](../examples/paramgiven_examples/) (new, 16
checks, both solvers, the bundled BSIM4 compiled with statistics added and an
object from a pre-E-555 compiler among them); `elabguard` adjusted (its
`freeze(aa=5)` check set exactly the shape F2 refuses now, and a new check
pins the refusal); the statistics, sweep, range and CMC runtime suites pass;
full sweep 459 of 459; compiler tests and the model corpus unchanged. Handbook
[§2.4](../docs/handbook/02-verilog-a-language.md), [§2.13](../docs/handbook/02-verilog-a-language.md),
[§3.6](../docs/handbook/03-ngspice-workflows.md), README_OSDI, the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md),
the [compiler internals](../docs/internals/openvaf_internals/OpenVAF_compiler_internals.md).

## What was wrong

**F1.** The descriptor's `access()` marks a parameter *given* on every write.
An `.option osdimc` draw, and the restore after a `.dc` or `sweep` of the
parameter, went through it, so a parameter the deck never gave came out
given — and a model that picks a default with `$param_given` ran its "given"
branch at the declared default from the second trial on, and after any
sweep. BSIM4 derives `toxp = toxe − dtox` unless `toxp` is given: with
`(* std=1e-13 *)` on `toxp` and only `toxe` on the card, a sigma of 0.003 %
cost 32 % of the drain current (−112.39 µA → −76.30 µA), every member of the
recorded ensemble sat 32 % from the design point, and a `dc @mos_va[toxp]`
sweep with the option off left the next `op` there for good. The built-in
BSIM4 under the same sweep was unchanged: it puts its given flags back, OSDI
had no way to. The readback `@mos_va[toxp]` reported the declared default,
3e-9, while the device ran at 2e-9.

**F2.** The compiled setup judged a parameter's range only when the parameter
was given: `l = 1.2 from [lmin:inf)` with `lmin` altered, swept or drawn to 1.5
ran with `l` below its bound, silently, while `l=1.2` on the card was refused.
E-546's per-instance judgement had the same gate.

## What changed

* **The compiler says which statistical parameters the model tests.**
  `BodyRef::param_given_tests` reads the inference result for `$param_given`
  calls; `module_given_tests` follows the analog blocks and the user functions
  they call. Such a parameter carries `OSDI_DIST_GATED` in the
  `OSDI_STAT_PARAM_INFOS` record.
* **A given-flag entry point per descriptor.** `OSDI_PARAM_GIVEN_FNS` exports
  `param_given_<sym>(inst, model, id, op)` — `op` 0 reads the flag, 1 sets, 2
  clears; `inst == NULL` means the card-level flag of an instance parameter —
  built beside `access` from the same bitfield helpers (`bitfield::clear_bit`
  and the `clear_nth_*` data helpers added). The descriptor ABI is unchanged;
  an older object has no such symbol and behaves as before.
* **The simulator draws a gated parameter only when the deck gave it**, and
  says so once: *`mos_va:toxp` is not given by the deck and the model tests
  `$param_given(toxp)`: a draw would switch the model to its "given" branch
  instead of varying it — not drawn. Give it on the card, or altermod it, to
  vary it.* A gated, ungiven parameter is no dimension of the `wcd` walk and
  no factor of the `highsigma` weight. `OSDIparamGiven` /
  `OSDIparamGivenByName` let the `.dc` restores (instance and model targets),
  the `sweep` command's restore and `unset osdimc` clear the flag of a
  parameter the deck never gave.
* **A default is judged against a range that reads another parameter.**
  `module_info` records `dynamic_bounds` (the bounds half of E-546's read
  analysis); `sim_back` passes those as `check_default` and
  `insert_param_init` judges the default when the parameter is not given —
  in the instance setup, the model setup and E-546's per-instance check. A
  constant default outside a constant range keeps E-56's exemption (the CMC
  "feature off" idiom, lint L027 at compile time).

## Verification

| check | result |
|---|---|
| gated `r` never given, 4 trials | `$param_given` 0, the derived default 2000 kept, the note once |
| the same `r` given on the card | drawn, as before |
| per instance, one line without `r`, one with `r=500` | the first not drawn, the second drawn |
| `dc @mm[r]`, `sweep @mm[r]`, `dc @n1[r]` of a defaulted parameter | not-given afterwards; `sens` never flipped it |
| BSIM4, `toxe=2e-9` only, 3 trials | −112.39 µA on every trial, the note names `toxp` |
| BSIM4 with `toxp=2e-9` on the card | drawn |
| BSIM4, `dc @mos_va[toxp] 2.5e-9 3.5e-9 0.5e-9`, no osdimc | −112.39 µA before and after |
| `montecarlo -expr id=i(vdd)` on the gated deck | every sample at the nominal |
| `altermod mm lmin=1.5`, `l` defaulted / given | both refused: *Parameter l of 'mm' is out of bounds (value 1.2)* |
| `dc @mm[lmin] 0.5 2.0 0.5` | stops at the first point past `l` |
| osdimc draws of `lmin` | the trials past `l` refused |
| `l = 2.0 from (0:w]` defaulted, instance `w=1` / `w=3` | refused / runs |
| `x = 0.0 from (0:inf)` defaulted | runs (E-56), L027 at compile time |
| an object from a pre-E-555 compiler | loads, draws, no symbol |
| `paramgiven_examples`; full sweep | 16 / 16, both solvers; 459 of 459 |
