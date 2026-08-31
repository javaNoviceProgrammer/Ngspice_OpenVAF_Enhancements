# 4 · Limitations and gotchas

An honest map of the edges: what is out of scope by design, what carries
fallback semantics, the deliberate design decisions, and the traps that
cost real debugging time in this project. Everything here is *documented
behavior* — most entries are pinned by a verify script so they can't
regress silently into something different.

## 4.1 Scope: Verilog-A, not full AMS

The project targets **Verilog-A** — the analog-only subset defined in Annex
C of the Verilog-AMS LRM. Features that exist only in full Verilog-AMS are
out of scope, most notably:

- **digital/mixed-signal constructs** — `reg`/`wire` logic, `always`/
  `initial` (digital) blocks, delays/event control on digital signals,
  connect modules and auto-insertion;
- **`` `default_discipline ``** — the directive is AMS-only. (Implicit nets
  *are* Verilog-A, and work: an undeclared net takes its discipline from
  the connected port — [E-41](../../enhancements_doc/Enhancement-41.md).)
- **discrete-domain disciplines** — `domain discrete` combined with natures
  is rejected with a proper error per LRM 3.6.2.2.
- **vector branches** (LRM 3.12: `branch (a,b) br;` over whole vector
  nets) — rejected with a located diagnostic; declare per-bit branches
  (`branch (a[i],b[i]) bri;`) instead. Likewise **out-of-module
  discipline declarations** (`electrical top.other.net;`, LRM 3.10),
  which have no meaning in a single-module OSDI compile.

When in doubt whether a construct is Verilog-A or AMS-only, Annex C of the
LRM (in [`docs/`](..)) is the authority the compiler follows.

## 4.2 Features with fallback semantics

These compile and behave predictably, but the OSDI/ngspice target has no
underlying mechanism for them, so they return their LRM-specified
"mechanism unavailable" values ([E-12](../../enhancements_doc/Enhancement-12.md)):

| Function | Behavior |
|---|---|
| `$simprobe` | the supplied default |
| `$analog_node_alias` / `$analog_port_alias` | `0` (no runtime hierarchical aliasing) |

## 4.3 Compile time vs. simulation time

The single most useful mental model for this toolchain:

- **Structure binds at compile time.** Hierarchy, `generate` blocks,
  genvars, `defparam`, paramsets, bus widths — all resolved by the
  elaboration pass. Consequently a `generate` condition or bound on a
  module **parameter** is an intentional, explained error: parameters
  arrive from model cards at simulation time, after structure is frozen
  ([E-67](../../enhancements_doc/Enhancement-67.md)).
- **Behavior binds at simulation time.** Loop trip counts, `if` arms, and
  expressions may depend on parameters (and the solution) freely — a
  model-card override genuinely changes how many times a `for` loop runs
  ([E-70](../../enhancements_doc/Enhancement-70.md)).
- **Untyped parameters take their default's type at compile time.**
  `parameter untyped = 1;` compiles as an *integer* parameter, so a
  netlist override of `2.5` is rounded to that frozen type. LRM 3.4.1
  says the type follows the *final overridden value*, but a compiled
  OSDI descriptor declares exactly one type per parameter, so
  override-dependent typing cannot exist here. Write `parameter real`
  when real overrides are expected; ngspice warns when an override is
  rounded this way.

## 4.4 Documented design decisions

- **`limexp()` is stateless** ([E-13](../../enhancements_doc/Enhancement-13.md)):
  `exp(x)` below the overflow cutoff, tangent-continued above — exact in
  every analysis. A stateful, previous-iterate limiting version was built
  and reverted: correct converged values under limiting require SPICE's
  limiting-RHS correction, which applies to circuit unknowns, not to
  `limexp`'s derived argument. Use `$limit` for genuine iteration limiting.
- **Random draws don't advance a seed** ([E-10](../../enhancements_doc/Enhancement-10.md)):
  each `$random`/`$dist_*` call site is a deterministic function of (seed,
  call site). An advancing seed would return different values on every
  Newton iteration and destroy convergence. Sequences within one evaluation
  are therefore not available; per-instance/per-call-site independence is.
- **`.disto` works for OSDI devices, via numerical differencing**
  ([E-359](../../enhancements_doc/Enhancement-359.md)): the Volterra kernel needs 2nd- and
  3rd-order derivative tensors. Rather than have the compiler emit them — an
  approach that was built, measured and *abandoned* because it cost 20–49x
  compile time, 30 MB objects and a 3.3–3.9x runtime penalty on every OTHER
  analysis — ngspice differences the analytic Jacobian numerically at the
  operating point. Compile time, object size, runtime and the OSDI ABI are all
  back at baseline. The tensors used *by `.disto` only* are therefore accurate
  to ~5e-9 rather than exact; **every other analysis still uses the compiler's
  exact derivatives**, unchanged. Supersedes the older behaviour where OSDI
  devices were skipped with a warning ([E-62](../../enhancements_doc/Enhancement-62.md)).
- **`@(final_step)` fires only on success**: a failed or interrupted
  analysis never fires it — "final" means the converged end of the run
  ([E-53](../../enhancements_doc/Enhancement-53.md)).

- **Transient noise activates automatically** ([E-364](../../enhancements_doc/Enhancement-364.md)):
  Verilog-A `white_noise`/`flicker_noise` are injected into `.tran` when — and
  only when — the circuit already contains a `trnoise` source, whose noise
  timestep is adopted so every generator shares one grid. A deck without one is
  unaffected. `noise_table` sources are **not** injected (a tabulated spectrum
  needs frequency shaping, not a scalar amplitude); they warn once and remain
  fully accounted for in `.noise`.

## 4.5 ngspice control-language traps

Pinned during this project's own verification work — they will bite anyone
scripting ngspice:

- **The first line of a deck is the title**, not a statement. A netlist
  line placed first is silently swallowed.
- **`wrdata` mispairs control-created vectors** (it attaches the current
  plot's scale, which for a control-made vector is length 1). Export such
  vectors by parsing `print` output, or `wrdata` only plot-native vectors
  ([E-66](../../enhancements_doc/Enhancement-66.md)).
- **`print` of an imported/foreign plot omits the scale column** — print
  `frequency[0]`-style expressions separately
  ([E-72](../../enhancements_doc/Enhancement-72.md)).
- **`sunif(0)` is uniform on [−1, 1]**, not [0, 1]; and every textual
  occurrence of a random-valued `{param}` draws independently — matched
  devices need the `alter` idiom ([E-66](../../enhancements_doc/Enhancement-66.md)).
- **Control scripts continue past aborted analyses** — detect completion
  from data, not from `echo` markers after the analysis command
  ([E-56](../../enhancements_doc/Enhancement-56.md)).
- **`sp lin 2 f1 f2` yields one point** (a stock ngspice quirk; `lin 3`
  and up behave; [E-63](../../enhancements_doc/Enhancement-63.md)).
- **A recompiled `.osdi` does not reload in-session** — `pre_osdi` on an
  already-loaded path notes it and keeps the existing registration;
  restart ngspice to pick up a recompiled file
  ([E-81](../../enhancements_doc/Enhancement-81.md)).
- **Module names that collide with ngspice built-in device types**
  (`cccs`, `vccs`, `vcvs`, …) are skipped with a warning — the built-in
  keeps the name, so pick another module name to actually use the model
  (this used to be a hard crash;
  [E-76](../../enhancements_doc/Enhancement-76.md)).

## 4.6 Assorted edges

- **A non-terminating analog loop is a compile-time error**
  ([E-375](../../enhancements_doc/Enhancement-375.md)): `while (1)`, or the far more ordinary
  case of forgetting the loop increment, is rejected with `loop condition is
  always true` or `loop condition can never change`. There is no correct object
  code for such a model — it can never finish one evaluation — so a diagnostic
  was the only right answer. It is worth knowing what it replaced: this used to
  crash `openvaf-r`, and after the E-363 CFG repair it stopped crashing and
  started *emitting* — the `.osdi` loaded cleanly and then hung the simulator on
  the first device evaluation with no diagnostic at all, which is worse than the
  crash. [E-389](../../enhancements_doc/Enhancement-389.md) closed the gap that
  mattered most in practice: a control variable that is *written but never
  changes* (`for (k = 0; k < 10; k = k + 0)`, or a plain `k = k`) used to
  satisfy the check and hang the simulator, and is now rejected too. The check
  remains conservative — it can still miss a loop whose variables genuinely
  change but never toward the exit, notably nested loops sharing an index — so
  it is still worth confirming that your loop variables actually advance. A loop
  that terminates only by integer wrap (`k = k - 1`) is *not* rejected: it does
  finish, after about 2³¹ iterations.

- **`break`/`continue` don't exist in Verilog-A** — the compiler rejects
  them with the `disable <block>;` idiom as the alternative
  ([E-9](../../enhancements_doc/Enhancement-9.md), [E-70](../../enhancements_doc/Enhancement-70.md)).
  One restriction: `disable` works as an early exit from a loop that can *also*
  finish normally, but it is not accepted as the **only** way out of a loop whose
  condition never changes — `while (1) … disable blk;` is rejected by the check
  above. That form never compiled anyway; it aborted codegen with
  `attempted to read undefined value`, so the error replaces a compiler crash
  ([E-375](../../enhancements_doc/Enhancement-375.md)).
- **Analog operators can't sit in loops or solution-dependent
  conditionals** (LRM 4.5.1) — hoist them or unroll with `generate`; the
  diagnostics say which ([E-70](../../enhancements_doc/Enhancement-70.md)).
- **Recursion in analog functions is illegal** — direct and mutual forms
  are clean errors naming the cycle ([E-59](../../enhancements_doc/Enhancement-59.md)).
- **Analog function arguments accept all three declaration forms**
  ([E-389](../../enhancements_doc/Enhancement-389.md)): the classic separated
  style `input x; real x;`, the combined declaration `input real x;`, and the
  ANSI header `analog function real f(input real x);` — in which a later
  argument may restate neither direction nor type (`f(input real x, y)` gives
  `y` both of `x`'s). Only **array** arguments still require the separated form
  (`output w; real w[0:3];`, not `output real w[0:3];`), because the
  declaration-level range machinery has no counterpart in the combined and ANSI
  positions.
- **String opvars** display via `show` but can't become vectors (ngspice
  vectors are numeric) — `print @n1[strvar]` fails with a clear message
  ([E-69](../../enhancements_doc/Enhancement-69.md)).
- **`sin` is a reserved word** in Verilog-A — don't name a net `sin`
  ([E-36](../../enhancements_doc/Enhancement-36.md)).
- **OSDI ABI pairing**: this ngspice requires OSDI ≥ 0.7; `.osdi` files
  from older compilers must be recompiled, and this compiler's output
  won't load into stock ngspice ([E-54](../../enhancements_doc/Enhancement-54.md)).
- **Parameter default ranges**: a parameter's default is exempt from its
  own `from` range (the CMC "disabled feature" idiom) — but every
  user-given value is fully validated. Don't rely on an out-of-range
  *given* value sneaking through ([E-56](../../enhancements_doc/Enhancement-56.md)).
- **Corpus models that "fail" by design**: some industry models reject
  default configurations on purpose (HiSIM's `$port_connected` guards,
  VBIC floating internal nodes at `RCX=0` — use `.option rshunt`, FBH-HBT
  needing `fb>0`). The triage lives in
  [E-56](../../enhancements_doc/Enhancement-56.md).
