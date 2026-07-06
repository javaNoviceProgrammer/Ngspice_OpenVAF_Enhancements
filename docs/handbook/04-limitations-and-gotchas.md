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

When in doubt whether a construct is Verilog-A or AMS-only, Annex C of the
LRM (in [`docs/`](..)) is the authority the compiler follows.

## 4.2 Features with fallback semantics

These compile and behave predictably, but the OSDI/ngspice target has no
underlying mechanism for them, so they return their LRM-specified
"mechanism unavailable" values ([E-12](../../enhancements_doc/Enhancement-12.md)):

| Function | Behavior |
|---|---|
| `$test$plusargs` / `$value$plusargs` | `false` / default (ngspice has no plusargs) |
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
- **`.disto` warns instead of pretending** ([E-62](../../enhancements_doc/Enhancement-62.md)):
  the small-signal distortion kernel needs higher-order Taylor coefficients
  the OSDI ABI cannot carry; OSDI devices are skipped with a loud warning
  (they used to contribute silent zeros).
- **`@(final_step)` fires only on success**: a failed or interrupted
  analysis never fires it — "final" means the converged end of the run
  ([E-53](../../enhancements_doc/Enhancement-53.md)).

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
- **Module names that collide with ngspice built-in device types**
  (`cccs`, `vccs`, `vcvs`, …) break model creation — name your modules
  something else ([E-29](../../enhancements_doc/Enhancement-29.md)).

## 4.6 Assorted edges

- **`casex`/`casez` are not implemented** — plain `case` (including over
  strings and arrays) is; the don't-care variants are rejected at parse
  time.
- **`break`/`continue` don't exist in Verilog-A** — the compiler rejects
  them with the `disable <block>;` idiom as the alternative
  ([E-9](../../enhancements_doc/Enhancement-9.md), [E-70](../../enhancements_doc/Enhancement-70.md)).
- **Analog operators can't sit in loops or solution-dependent
  conditionals** (LRM 4.5.1) — hoist them or unroll with `generate`; the
  diagnostics say which ([E-70](../../enhancements_doc/Enhancement-70.md)).
- **Recursion in analog functions is illegal** — direct and mutual forms
  are clean errors naming the cycle ([E-59](../../enhancements_doc/Enhancement-59.md)).
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
