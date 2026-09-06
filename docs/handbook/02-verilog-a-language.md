# 2 · Verilog-A language support

This is the feature matrix: what the compiler accepts, what the compiled
model actually *does* at simulation time, and where each claim is proven.
The scope of the project is **Verilog-A** — the analog subset defined in
Annex C of the Verilog-AMS LRM — not full mixed-signal AMS (see
[chapter 4](04-limitations-and-gotchas.md#41-scope-verilog-a-not-full-ams)
for exactly where that line runs).

Every table row links the enhancement that built or audited the feature
(`E-n` → the detailed write-up in `enhancements_doc/`) and, in the notes,
the `examples/` folder whose verify script pins it. A recurring lesson of
this project is that *compiling proves nothing* — several features compiled
for years while silently doing the wrong thing at runtime — so a row only
says "works" if a committed script checks the simulated numbers.

## 2.1 Modules, hierarchy, and elaboration

Hierarchy is resolved by a compile-time **elaboration pass**: instantiated
modules are recursively inlined (alpha-renamed per instance, ports bound to
the caller's nets, parameters bound to overrides) into a single flat module
before the rest of the compiler runs. Everything in this section is
therefore resolved at **compile time**.

| Feature | Notes | Since |
|---|---|---|
| Module instantiation | Named `.p(net)` and positional port connections, open ports, named `#(.r(1e3))` and positional `#(1e3)` parameter overrides, instance arrays `res rarr[0:3](…)`, arbitrary nesting, across `` `include `` boundaries; cyclic instantiation is a clean error. Mixing positional and named forms in one `#(...)` list is an error (LRM Syntax 6-2; the positional half used to be silently dropped), and a connection that does not match a multi-bit port's width — e.g. a scalar net on a 2-bit port — is an error citing LRM 6.5.7.1 instead of a silent per-bit broadcast. `examples/instantiation_examples/` | [E-5](../../enhancements_doc/Enhancement-5.md) |
| `generate for` / `genvar` | Structural loops generating nets, instances, variables, parameters; nested loops (inner bounds may use outer genvars); genvars usable in any expression, e.g. `#(.r(1e3*(i+1)))`. Since E-564 what a block declares is reachable by its **hierarchical name** (LRM 6.7): `V(g1[0].z)` for an iteration, `V(g1[0].genblk1.w)` for a block nested in it, `g1[1].r1.mid` for an instance inside it. `examples/generate_examples/`, `examples/genhier_examples/` | [E-8](../../enhancements_doc/Enhancement-8.md), [E-67](../../enhancements_doc/Enhancement-67.md), [E-564](../../enhancements_doc/Enhancement-564.md) |
| `generate if` / `generate case` | else/else-if chains, multi-value case arms, default; conditions fold over genvars and literals; a branch or arm may be a **single item** without `begin`/`end` (LRM 6.6.2). Since E-564 a named block is reachable as `V(blk.x)`, a case arm as `V(two.q)`, and an unlabelled block by its **implicit `genblk<n>` name** (LRM 6.6.3: constructs numbered in textual order, leading zeroes added while the name is declared). A condition on a module *parameter* is an intentional error — parameters bind at simulation time and cannot shape structure (see [§4.3](04-limitations-and-gotchas.md#43-compile-time-vs-simulation-time)). | [E-67](../../enhancements_doc/Enhancement-67.md), [E-564](../../enhancements_doc/Enhancement-564.md) |
| Hierarchical names | Instance-path references `u1.u2.node`, `$root.top.net`, from expressions and probes. A **contribution** targeting a hierarchical net (`V(p, c1.mid) <+ 0.5;`) creates its own branch in the contributing module per LRM 5.6.8.1 — distinct from any branch the child has between the same nodes — so the child's contributions and probes are unaffected; references to a child's *named* branch merge per 5.6.8.2. `examples/hiername_examples/` | [E-49](../../enhancements_doc/Enhancement-49.md) |
| `defparam` | Compile-time hierarchical parameter override at any depth (`defparam u1.u2.r = 2e3;`), multi-assignment form, expression values; takes LRM-mandated precedence over instance `#()` overrides. Works inside generate blocks (targeting the per-iteration instance, genvars usable in the value) and at module scope beside generate constructs — both used to be silently dropped by the generate rewrite. `examples/defparam_examples/` | [E-58](../../enhancements_doc/Enhancement-58.md) |
| `paramset` | Verilog-AMS paramset blocks per LRM 6.4, including `.$mfactor`/position hidden-system-parameter assignments inside the paramset. Since E-563: a paramset's parameters, aliases and variables **reuse the module's names** (`parameter real L = 3u; .L = L;`); a paramset may target **another paramset** and assign the parent's own parameters (a chain); an **`aliasparam`** of the paramset names its parameter on the card and in an instance override; **variables and statements** (6.4.1) compute **output variables** (6.4.3) from the module's through `.name` — a same-named one replaces the module's; **hierarchical references to another module's `localparam`s** (the "constant module" idiom, `.RSH = fab.rsh_poly * fab.bias;`); and a paramset **instantiated inside a module** carries all of this (its bindings used to be lost there). Since E-565 paramsets may be **overloaded** (6.4.2): the family compiles to `nch`, `nch__2`, …, an instance inside a module is resolved at elaboration and a `.model nch …` card by ngspice as it is materialised, both by the clause's rules and tie-breaks, an ambiguity or a card no member accepts being an error. Still refused: a random draw in an override (E-545). `examples/paramset_examples/`, `examples/paramsethsp_examples/`, `examples/paramsetlrm_examples/`, `examples/paramsetoverload_examples/` | [E-21](../../enhancements_doc/Enhancement-21.md), [E-44](../../enhancements_doc/Enhancement-44.md), [E-563](../../enhancements_doc/Enhancement-563.md), [E-565](../../enhancements_doc/Enhancement-565.md) |
| Implicit nets | An undeclared identifier in an instance connection becomes an implicit scalar net, discipline derived from the connected port. `examples/implicitnet_examples/` | [E-41](../../enhancements_doc/Enhancement-41.md) |
| Net concatenation in ports | `u1({a, c})` onto a vectored port, expanded bit-by-bit (leftmost = msb), positionally or named, nested through instance levels; width mismatch is a hard error. | [E-59](../../enhancements_doc/Enhancement-59.md) |
| Multiple `analog` blocks | Several `analog` / `analog initial` blocks per module execute as-if-concatenated in source order (LRM 6.2), including across instance flattening. `examples/multianalog_examples/` | [E-60](../../enhancements_doc/Enhancement-60.md) |

## 2.2 Nets, disciplines, natures

| Feature | Notes | Since |
|---|---|---|
| Vectored (bus) nets and ports | `electrical [3:0] bus;` with bit-select access in branches and probes; buses slice element-wise onto instance arrays and bus ports. A signal-access index may be any constant expression over literals, genvars, and **parameters** (`V(in[width-2])`, LRM 5.5.2) — the index selects a node, so parameters it reads freeze structural like parameter-shaped widths. `examples/bus_examples/` | [E-3](../../enhancements_doc/Enhancement-3.md) |
| `ground` declarations | Both orderings (`electrical ground gnd;` and `ground electrical gnd;`). `examples/ground_examples/` | [E-9](../../enhancements_doc/Enhancement-9.md) |
| Derived natures | `nature X : Parent`, deriving from a discipline's nature (`: electrical.flow`), with full attribute inheritance. `examples/derivednature_examples/` | [E-39](../../enhancements_doc/Enhancement-39.md) |
| Net initializers (nodesets) | `electrical a = 5.0;` becomes an OSDI nodeset — an initial-guess hint for the solver, essential for bistable circuits. `examples/netinit_examples/` | [E-45](../../enhancements_doc/Enhancement-45.md) |
| Nature-attribute access | `net.potential.abstol`, `branch.potential.abstol` readable in expressions. | [E-45](../../enhancements_doc/Enhancement-45.md), [E-59](../../enhancements_doc/Enhancement-59.md) |
| Domain binding | `domain continuous` accepted; `domain discrete` on a discipline with natures is a proper two-label error (LRM 3.6.2.2). `examples/domainbind_examples/` | [E-50](../../enhancements_doc/Enhancement-50.md) |
| Signal-flow / flow-only disciplines | Disciplines with only a flow (or only a potential) nature work, including probe-only usage (§2.7). `examples/signalflow_examples/` | [E-36](../../enhancements_doc/Enhancement-36.md) |
| Discipline compatibility (LRM 3.11.1) | The full rule set: a branch between a conservative net and a signal-flow net of the same potential nature is legal (`electrical`/`voltage`), natureless disciplines match their whole domain, domainless ones match everything; genuinely incompatible pairs (`electrical`/`rotational`) still refused. | — |
| NIST2018 physical constants | `constants.vams` is the VAMS-2023 Annex D.2 file: `` `define PHYSICAL_CONSTANTS_NIST2018 `` before the include selects the exact 2019-SI values; the default stays NIST1998 per the LRM. | — |

## 2.3 Data types, variables, and arrays

| Feature | Notes | Since |
|---|---|---|
| `real`, `integer`, `string` variables | Full support, including uninitialized strings defaulting to `""`. `examples/vartype_examples/` | [E-9](../../enhancements_doc/Enhancement-9.md) |
| Variable persistence | Module-level variables genuinely keep their value across evaluations (`accum = accum + 1.0;` accumulates) — for `real` *and* `integer` state. `examples/variable_persistence_examples/`, `examples/intstate_examples/` | [E-7](../../enhancements_doc/Enhancement-7.md), [E-32](../../enhancements_doc/Enhancement-32.md) |
| Declaration initializers | `real x = 2.0*p;`, including on (multi-dimensional) arrays; parameter-only initializers evaluate once at setup. `examples/varinit_examples/` | [E-43](../../enhancements_doc/Enhancement-43.md) |
| Arrays, 1-D to N-D | Both declaration orders (`real [0:3] x;` and LRM-style `real x[0:3];`), any number of dimensions, constant *and dynamic* indexing (`m[i][j]` with runtime `i`, `j`). `examples/array_examples/`, `examples/mdarray_examples/` | [E-14](../../enhancements_doc/Enhancement-14.md), [E-15](../../enhancements_doc/Enhancement-15.md), [E-18](../../enhancements_doc/Enhancement-18.md) |
| Array aggregates | Whole-array assignment `c = '{v0, v1, v2};`, nested for N-D, array-to-array copy `c = d;`. | [E-14](../../enhancements_doc/Enhancement-14.md), [E-15](../../enhancements_doc/Enhancement-15.md) |
| Concatenation / replication | `{a, b, c}` and `{n{x}}` as real operators over arrays and strings (`'{…}` stays the typed aggregate); and, where a **scalar** is expected of it, a `{…}` of scalar integers is the LRM 4.1.13 **bit-level** concatenation — `{4'hA, 4'h5}` is 165, `{2{4'b1010}}` is 170, sized literals contribute their size and any other integer 32 bits, an unsized literal is refused and a result wider than 32 bits is warned about (F12 of the 2026-09-05 book audit). `examples/concat_examples/` | [E-34](../../enhancements_doc/Enhancement-34.md) |
| Arrays in `case` | Element-wise array `case` statements and array-literal case labels. `examples/arraycase_examples/` | [E-33](../../enhancements_doc/Enhancement-33.md) |

## 2.4 Parameters

| Feature | Notes | Since |
|---|---|---|
| Ranges and excludes | `from (0:inf)`, `exclude 0`, etc., enforced on user-given values. Per the CMC convention, a parameter's **default is exempt** from its own range — industry models use an out-of-range default as the "feature disabled" state. Since E-532 a **constant** default that violates its own constant range is no longer silent: the `param_default_out_of_range` lint (L027, warn by default) names it at compile time, and the deliberate must-give/feature-disabled idiom silences it per declaration with `(* openvaf_allow="param_default_out_of_range" *)`. All 26 bundled industry models compile with zero L027 hits. Since E-555 a default whose **bounds read another parameter** (`l = 1.2 from [lmin:inf)`) *is* judged at setup, given or not — the range can have moved since the default was declared, by `altermod`, a `.dc` sweep or an `osdimc` draw of `lmin`, and it was running silently below its bound; the constant-range exemption is untouched. `examples/paramgiven_examples/` | [E-56](../../enhancements_doc/Enhancement-56.md), [E-532](../../enhancements_doc/Enhancement-532.md), [E-555](../../enhancements_doc/Enhancement-555.md) |
| `localparam` | Non-overridable per the LRM; derived localparams (`localparam G = 1/R`) track their inputs. `examples/localparam_examples/` | [E-9](../../enhancements_doc/Enhancement-9.md) |
| `aliasparam` | Works, including `$param_given` queried through the alias. LRM 3.4.7's error rules are enforced: setting a parameter by its original name **and** an alias on one card/line is a netlist error, and referencing the alias in module equations is a compile error. | [E-59](../../enhancements_doc/Enhancement-59.md) |
| Array-valued parameters | `parameter real [0:3] w = '{…};` (any dimensionality) expands to one scalar OSDI parameter per element, each individually overridable from SPICE: `.model m dev(w[1][1]=0.9)`. The whole array can also be overridden at instantiation with an assignment pattern — `leaf #(.w('{…})) l1(a,b);` — checked against the declared element count (LRM 3.4.4/3.4.8). | [E-14](../../enhancements_doc/Enhancement-14.md), [E-15](../../enhancements_doc/Enhancement-15.md) |
| String parameters | Including `case` dispatch on a string parameter. | [E-59](../../enhancements_doc/Enhancement-59.md) |
| Hidden system parameters | `$mfactor` (device multiplicity — automatically scales flows, noise, and Jacobians) and the position parameters, readable in the model and settable per instance (`n1 a b mod m=4`) — and per **child instance** inside the hierarchy: `leaf #(.$mfactor(4)) u1 (p, n);` applies the full LRM 6.3.6 multiplicity transform to the inlined child (reads compose with the netlist value, flow contributions ×m, flow probes read per-copy, noise power scales as the parallel combination), with `.$xposition(...)`-family overrides composing additively. | [E-44](../../enhancements_doc/Enhancement-44.md) |
| Instance-line parameters | `(* type="instance" *)` on a parameter exposes it on the instance line and to `alter @n1[p]` / `.dc @n1[p]` (see [§3.3](03-ngspice-workflows.md#33-parameter-access-alter-and-sweeps)). Since E-546 a parameter whose **default** reads an instance parameter (`parameter real l = 2*w;` with an instance `w`, transitively, `$param_given(w)` included) is itself resolved per instance — promoted to the instance line, named by the `instance_dependent_parameter` lint (L028, warn; silent for an untyped `localparam`), and still settable on the `.model` card as the card's default. A parameter whose **range** reads an instance parameter (`from (0:w]`, the shape BSIM6's `XGL` and HiSIM2's `LP` use) keeps its level and is judged per instance, with that instance's values; before E-546 both were resolved once per card, against the instance parameter's default — which is what BSIMCMG's `LSP = 0.2*(L+XL)`, a model parameter by declaration, was silently getting. `examples/instdep_examples/` | [E-62](../../enhancements_doc/Enhancement-62.md), [E-546](../../enhancements_doc/Enhancement-546.md) |
| `$param_given`, `$port_connected` | Both work; industry models use them for configuration guards. A parameter overridden from inside the hierarchy (instance `#(...)` value or `defparam`) reports *given* per LRM 6.3.5, even though flattening bakes the value in as the new default. | — |

## 2.5 Operators and literals

The operator surface was audited systematically — every operator against the
LRM, every precedence level against LRM Table 4-2 — with self-checking
modules whose failure modes are numerically visible.

| Feature | Notes | Since |
|---|---|---|
| Arithmetic, comparison, logical, bitwise operators | Audited; fixes included `~` (was arithmetic negate) and const-folded unsigned `>>`. `examples/operator_examples/` | [E-37](../../enhancements_doc/Enhancement-37.md) |
| Precedence and associativity | Audited against LRM Table 4-2; `%` now binds like `*`/`/`, `2**3**2 = 64` (left-assoc), unary binds above `**`. `examples/precedence_examples/` | [E-38](../../enhancements_doc/Enhancement-38.md) |
| Arithmetic shifts `<<<` / `>>>` | A flagged extension: LRM 4.2.11 bars them from analog blocks, so each use draws a warning, but `>>>` is the only spelling of a sign-extending shift. A shift distance outside 0..=31 (any spelling) warns and yields the LRM-defined value (`1<<32` is 0 — the distance is unsigned). `examples/shift_examples/` | [E-6](../../enhancements_doc/Enhancement-6.md) |
| Case (in)equality `===` / `!==` | Lex and evaluate as `==`/`!=` — exact in a 2-state analog world (no x/z bits to distinguish). | — |
| Ternary `?:` | Including over string operands. | [E-37](../../enhancements_doc/Enhancement-37.md) |
| Based integer literals | `'h1F`, `'b101`, `'o17`, `'d42`, with underscores and explicit widths. `examples/escid_examples/` | [E-46](../../enhancements_doc/Enhancement-46.md) |
| Escaped identifiers | `\my-net!` per the LRM, everywhere identifiers appear. | [E-46](../../enhancements_doc/Enhancement-46.md) |
| String literal escapes | The full set (`\n`, `\t`, `\\`, `\"`, octal `\ddd`) via a single-pass unescaper. `examples/stresc_examples/` | [E-48](../../enhancements_doc/Enhancement-48.md) |
| Integer `min`/`max`/`abs`, away-from-zero rounding | Verified integer-typed, per the LRM. | [E-59](../../enhancements_doc/Enhancement-59.md) |
| Math functions & scale factors | `ln/log/exp/sqrt/pow/trig/hyperbolic/floor/ceil`, SI suffixes (`1k`, `1u`, …). | — |

## 2.6 Analog operators (filters, integrators, delays)

All analog operators produce correct **Jacobian contributions** via automatic
differentiation, so convergence behaves like a hand-written stamp.

| Operator | Notes | Since |
|---|---|---|
| `ddt(x)` | Time derivative; fully working (the reactive residual/Jacobian path). | — |
| `idt(x[, ic])` | Time integral; the initial condition survives into transient (it used to be zeroed at the IC phase). `examples/idtic_examples/` | [E-28](../../enhancements_doc/Enhancement-28.md) |
| `idt(x, ic, assert[, tol])` | Reset form: while `assert` is nonzero the state holds at `ic`; smooth reset dynamics keep self-referential resets bounded. Relaxation oscillators work. `examples/idtassert_examples/` | [E-52](../../enhancements_doc/Enhancement-52.md) |
| `idtmod(x[, ic, modulus, offset])` | Modulo integrator (VCO phase idiom): integrates unbounded internally, wraps the returned value. A no-ic `idtmod` defaults its ic to 0 and pins the DC solution (LRM 4.5.5) instead of demanding feedback. `examples/idtmod_examples/` | [E-27](../../enhancements_doc/Enhancement-27.md) |
| `ddx(x, probe)` | Symbolic derivative w.r.t. a potential *or flow* probe — including the unnamed-branch flow `ddx(f, I(a,b))` (reversed orientation negates; a flow that is not a system unknown differentiates to 0). `examples/ddx_examples/` | [E-13](../../enhancements_doc/Enhancement-13.md), [E-59](../../enhancements_doc/Enhancement-59.md) |
| `absdelay(x, td[, maxdelay])` | Transport delay via the synthetic-node DAE approach. Without `maxdelay`, `td` is frozen at the first transient evaluation per LRM 4.5.7 (latched simulator-side at the converged operating point); with `maxdelay` it tracks and clamps. `examples/absdelay_examples/` | [E-1](../../enhancements_doc/Enhancement-1.md) |
| `transition(x[, td, rise, fall])` | 3/4/5-argument forms; `` `default_transition `` supplies defaults — for omitted **and explicit-zero** rise/fall times (LRM 4.5.8's "specified or are equal to zero"); without the directive, a bare `transition(x)` takes the LRM's negligible non-zero ramp. DC is well-posed. Approximation to know: the ramp runs at the fixed rate `1/rise`, so an amplitude-A step completes in `A·rise` (exact for 0/1 comparator inputs), and the small-signal transfer is a lowpass with corner `1000/rise` rad/s. `examples/transition_examples/`, `examples/defaulttransition_examples/` | [E-6](../../enhancements_doc/Enhancement-6.md), [E-47](../../enhancements_doc/Enhancement-47.md) |
| `slew(x[, max_pos, max_neg])` | Rate limiter; honors the LRM's *negative* `max_neg_slew_rate` convention (and tolerates the legacy positive-magnitude spelling). `examples/slew_examples/`, `examples/opargs_examples/` | [E-6](../../enhancements_doc/Enhancement-6.md), [E-61](../../enhancements_doc/Enhancement-61.md) |
| `laplace_nd/np/zd/zp` | Continuous-time filters via exact state-space realization; complex pole/zero pairs per the LRM's (re, im) vector convention; parameter-dependent coefficients. A **solution-dependent** coefficient tracks (the LRM would freeze it at analysis start) and draws a warning. `examples/laplace_examples/`, `examples/complexpole_examples/` | [E-4](../../enhancements_doc/Enhancement-4.md), [E-31](../../enhancements_doc/Enhancement-31.md) |
| `zi_nd/np/zd/zp` | Z-domain filters via bilinear transform onto the laplace machinery — a **continuous** approximation: no discrete-time sample-and-hold (a unity z-filter is a wire), and the 6-argument form's `tau`/`t0` are accepted but ignored. `examples/zi_examples/` | [E-6](../../enhancements_doc/Enhancement-6.md), [E-31](../../enhancements_doc/Enhancement-31.md) |
| `last_crossing(x, dir)` | Interpolated crossing times, backed by simulator-side waveform history (an additive OSDI extension). `examples/last_crossing_examples/` | [E-6](../../enhancements_doc/Enhancement-6.md) |
| `limexp(x)` | **Stateless** limited exponential (tangent-continued above the overflow cutoff) — a documented decision; see [§4.4](04-limitations-and-gotchas.md#44-documented-design-decisions). | [E-13](../../enhancements_doc/Enhancement-13.md) |
| `$limit(x, "pnjlim", …)` / `$limit(x, fn, …)` | Genuinely engages SPICE-style iteration limiting (stiff diodes converge without gmin stepping), for the built-in and user-function forms. `examples/opargs_examples/` | [E-61](../../enhancements_doc/Enhancement-61.md) |
| `$bound_step(t)` | Genuinely bounds the transient step; several calls in one evaluation honor the **smallest** active bound (LRM 9.17.2 — the last call used to win). | [E-61](../../enhancements_doc/Enhancement-61.md) |
| `$discontinuity(n)` | Clamps the *next* step and makes the integrator bisect onto the event instead of extrapolating across it. `examples/discontinuity_examples/` | [E-24](../../enhancements_doc/Enhancement-24.md), [E-55](../../enhancements_doc/Enhancement-55.md) |
| Trailing tolerance arguments | The optional `abstol`/nature args of `ddt`/`idt`/`idtmod`/`laplace_*`/`zi_*` are accepted and validated (positive, a real nature) but do **not** influence convergence tolerances — the OSDI ABI has no per-**equation** tolerance channel, so ngspice's global `abstol`/`reltol` govern. (A **nature's** declared `abstol` is a different matter and *does* reach the convergence test, per LRM 3.6.1 — see E-539.) Event tolerances likewise (a nonzero `cross`/`above` tolerance warns). | [E-61](../../enhancements_doc/Enhancement-61.md) |

Analog operators are statically forbidden inside conditionals whose condition
depends on the solution, and inside loops (LRM 4.5.1) — the diagnostics name
the actual construct and suggest hoisting or `generate` unrolling
([E-70](../../enhancements_doc/Enhancement-70.md)).

## 2.7 Contributions, branches, and probes

| Feature | Notes | Since |
|---|---|---|
| `V(a,b) <+` / `I(a,b) <+` contributions | Including switch branches and accumulation across statements, loops, and multiple analog blocks. A switch branch contributes the two kinds on **mutually exclusive conditional paths**; contributing both with no condition between them keeps only the last one and is reported by the `discarded_contribution` lint. | [E-400](../../enhancements_doc/Enhancement-400.md) |
| Indirect branch assignment | `V(out): V(x) == 0;` — the LRM's ideal-opamp construct, one implicit equation per statement. The LRM placement rules are enforced: illegal under a non-constant `if`/`case`/loop and inside event controls (a guarded-off constraint is a singular matrix), and mixing an indirect assignment with a direct `<+` on the same branch is an error naming both statements (LRM 5.6.7/5.6.7.2). A general real expression on the equality's left side is accepted as a generalized-implicit-equation extension. `examples/indirect_assignment_examples/` | [E-2](../../enhancements_doc/Enhancement-2.md) |
| Port-flow probes `I(<p>)` | Reading the total flow through a port (previously returned 0). `examples/portflow_examples/` | [E-29](../../enhancements_doc/Enhancement-29.md) |
| Probe-only branches | Probing a branch that is never contributed to reads its actual flow (an ideal ammeter) instead of 0 + open circuit; makes flow-only signal-flow disciplines work. `examples/portflow_examples/`, `examples/signalflow_examples/` | [E-36](../../enhancements_doc/Enhancement-36.md) |
| Grounded branch declarations | `branch (a) br;` | [E-59](../../enhancements_doc/Enhancement-59.md) |

## 2.8 Events

| Feature | Notes | Since |
|---|---|---|
| `@(initial_step)` / `@(final_step)` | Genuinely gated (once at the start; once at the end of a *successful* analysis, seeing the converged solution — the classic "report a tracked peak" pattern works). An op fires both. `examples/initial_step_examples/`, `examples/finalstep_examples/` | [E-7](../../enhancements_doc/Enhancement-7.md), [E-53](../../enhancements_doc/Enhancement-53.md) |
| Analysis-phase lists | `@(initial_step("ac","tran"))` filters by analysis type — LRM Table 5-1 exact per analysis: the OP of an `.ac`/`.noise` job belongs to that analysis, not to `"dc"`. | [E-53](../../enhancements_doc/Enhancement-53.md) |
| `cross(expr[, dir, time_tol, expr_tol])` | Edge detection with persistent state across evaluations. Fires only in transient analyses and only after t > 0 (LRM 5.10.3.2); its state still tracks through DC so the first step compares against the operating point. Tolerances are accepted but **not honored** (detection is evaluation-granular; a nonzero tolerance draws a warning). Not allowed under runtime `if`/`case`/loops (enforced; genvar forms stay legal). `examples/cross_examples/` | [E-8](../../enhancements_doc/Enhancement-8.md), [E-61](../../enhancements_doc/Enhancement-61.md) |
| `above(expr[, …])` | Like `cross` but also fires in DC — including the LRM-mandated initialization event when the expression is positive at the initial solve. | [E-8](../../enhancements_doc/Enhancement-8.md), [E-59](../../enhancements_doc/Enhancement-59.md) |
| `timer(start[, period, tol])` | Periodic firing verified at exact counts; placement exact via the bound-step channel. `examples/timer_examples/` | [E-8](../../enhancements_doc/Enhancement-8.md), [E-61](../../enhancements_doc/Enhancement-61.md) |
| Event OR lists | `@(cross(…) or timer(…) or initial_step)` — fires exactly when any member fires (LRM 5.10.3); a comma is interchangeable with `or` (5.10.1). `examples/lrmcorner_examples/` | [E-59](../../enhancements_doc/Enhancement-59.md) |
| Invalid events rejected | `@(absdelta(…))`, named events, and typos are targeted **errors** — they used to silently drop the event and run the body on every evaluation. Nested `@(…)` is an error too. | — |

## 2.9 Analog functions

| Feature | Notes | Since |
|---|---|---|
| `analog function` basics | Inlined at the call site; derivatives flow through automatically. | — |
| Array arguments | Whole-array `input` args ([E-18](../../enhancements_doc/Enhancement-18.md)), `output`/`inout` writeback ([E-20](../../enhancements_doc/Enhancement-20.md)), **array return values** (`real [0:2] f;` — [E-23](../../enhancements_doc/Enhancement-23.md)), array-literal arguments ([E-33](../../enhancements_doc/Enhancement-33.md)), array locals. `examples/funcarray_examples/`, `examples/arrayout_examples/`, `examples/arrayret_examples/` | E-18/20/23/33 |
| Loops inside functions | Iterative algorithms (Newton, factorial) verified exact. | [E-70](../../enhancements_doc/Enhancement-70.md) |
| Integer/untyped arguments | Untyped args default to `real`; integer output args work. | [E-43](../../enhancements_doc/Enhancement-43.md), [E-59](../../enhancements_doc/Enhancement-59.md) |
| String functions | `analog function string` return types and string `output` arguments (VAMS-2023, LRM 4.7.1). | [E-520](../../enhancements_doc/Enhancement-520.md) |
| Function-local `parameter`s | A `parameter` inside a function body is a compile-time local (LRM 4.7.1): it shadows a same-named module parameter, other module parameters read through — a netlist override of those propagates into the function — and it is never netlist-settable itself. | — |
| Output-array semantics | A pure `output` array is zero-initialized at entry, and an unassigned one resets the caller's array to zeros (LRM 4.7.2.3); `inout` arrays copy in and out. | — |
| Recursion | Not legal in Verilog-A; both direct and mutual recursion are clean, cycle-naming errors (mutual recursion used to crash the compiler). | [E-59](../../enhancements_doc/Enhancement-59.md) |

## 2.10 Procedural statements and loops

| Feature | Notes | Since |
|---|---|---|
| `if`/`else`, `case`, `casex`/`casez` | `case` works on strings and arrays; `casex`/`casez` treat `x`/`z`/`?` digits of item literals as comparison masks (the priority-encoder idiom), with don't-care literals rejected everywhere else. `examples/casexz_examples/` | [E-33](../../enhancements_doc/Enhancement-33.md), [E-59](../../enhancements_doc/Enhancement-59.md), [E-78](../../enhancements_doc/Enhancement-78.md) |
| `for`, `while`, `repeat(n)`, `do…while` | All four, audited: nesting, loops over arrays, solution-dependent conditions, contributions accumulating inside loops. Parameter-dependent trip counts honor **model-card overrides at simulation time**. Note two deliberate relaxations beyond the LRM: contributions inside runtime loops (LRM 5.9 allows them only in the genvar `analog_for`) and `do…while` itself (absent from Annex A.6.8) — models relying on either are not portable LRM Verilog-A. `examples/analogloop_examples/`, `examples/dowhile_examples/`, `examples/repeat_examples/` | [E-9](../../enhancements_doc/Enhancement-9.md), [E-19](../../enhancements_doc/Enhancement-19.md), [E-70](../../enhancements_doc/Enhancement-70.md) |
| `disable <block>;` | Named-block early exit. `examples/disable_examples/` | [E-9](../../enhancements_doc/Enhancement-9.md) |
| `break` / `continue` / `return` | The VAMS-2023 jump statements (LRM 5.11): `break`/`continue` in any runtime loop (`continue` re-enters a `for` at its increment), `return [expr]` exits an analog function early. Contextual keywords — legacy identifiers named `break` etc. still compile, with the L012 lint. Not allowed in genvar for-loops (LRM 5.9.3), and enforced. | — |

## 2.11 System tasks and functions

### Display and I/O

| Feature | Notes | Since |
|---|---|---|
| `$strobe`, `$display`, `$write`, `$monitor`, `$debug` | All five kinds; **full format-specifier surface** — `[flags][width][.precision]` on every conversion (`%5d`, `%-8s`, `%08.3f`, dynamic `%*d`), `%e/f/g/r` (engineering notation), `%d/h/o/b/c`, `%s`, `%m` (the **instance**'s hierarchical path, per LRM 9.4.4 — it named the *module* until E-539, so every instance printed one string), `%%`. `examples/display_examples/` | [E-71](../../enhancements_doc/Enhancement-71.md), [E-539](../../enhancements_doc/Enhancement-539.md) |
| File I/O | `$fopen`/`$fclose`/`$fdisplay`/`$fwrite`/`$fstrobe`/`$fmonitor`/`$fdebug`/`$fflush`/`$ftell`/`$fseek`/`$rewind`/`$feof`/`$ferror`. `examples/fileio_examples/` | [E-11](../../enhancements_doc/Enhancement-11.md) |
| Descriptors: the two kinds | `$fopen(name, mode)` returns a **file descriptor**; `$fopen(name)` returns a **multichannel descriptor** — a one-hot bit, with bit 0 reserved for stdout — and OR-ing several writes to all of them at once (`$fdisplay(mA\|mB, ...)`). The two are separate namespaces (LRM 9.5.1); they shared one until E-539, so an OR-ed write landed in an unrelated third file. `examples/lrmio_examples/` | [E-539](../../enhancements_doc/Enhancement-539.md) |
| Reading: what each call consumes | `$fgets` consumes the whole line; `$fscanf` consumes only what its format matches, so a following `$fgets` sees the **remainder** of that line. `$fclose` then `$fopen` for reading restarts at byte 0. `examples/lrmio_examples/` | [E-539](../../enhancements_doc/Enhancement-539.md) |
| String formatting/parsing | `$swrite`, `$sformat`, `$sscanf`, `$fgets`, `$fscanf`. `examples/stringio_examples/` | [E-11](../../enhancements_doc/Enhancement-11.md) |

### Modeling functions

| Feature | Notes | Since |
|---|---|---|
| `$table_model` | The LRM 9.21 surface: piecewise-linear (`1`), **natural cubic-spline** (`3`) and **closest-point** (`D`, with the 9.21.4 tie rule) interpolation; **default linear extrapolation** per Tables 9-31/9-32 with per-dimension comma-separated control sub-strings, per-end `C`/`L`/`E` (error-on-extrapolation) characters, and the `;N` dependent-column selector; data from the normative **N+M-column isoline files** (ragged isolines included), the self-describing N-D grid file (extension), interleaved `'{x0,y0,…}` or paired `'{xs}, '{ys}` arrays, and runtime array variables. Lowered to differentiable MIR, so *all* partial derivatives feed the Jacobian (a table-based MOSFET gets exact gm and gds). Since E-562: the **quadratic spline** (`2`); **`I` ignores a data column** of a file or of the array form; the **9.21.1 array data source** for a table of any dimension — column arrays (filled in `analog initial`, the textbook idiom, or initialised at declaration) or one 2-D array whose rows are the columns — read at compile time like a file, so the arrays must be compile-time constants (a run-time write, or an overridable `parameter` array, is refused with the reason); a **`localparam string`** as the file name or the control string (`file_name ::= string_literal \| string_parameter`; an overridable `parameter string` is refused — the table is built before the model card is read). Still refused: `I` on the runtime 1-D array form and on inline `'{...}` data. `examples/table_model_examples/`, `examples/mdtable_examples/`, `examples/ndtable_examples/`, `examples/cubic_table_examples/`, `examples/tablesrc_examples/` | [E-16](../../enhancements_doc/Enhancement-16.md), [E-17](../../enhancements_doc/Enhancement-17.md), [E-22](../../enhancements_doc/Enhancement-22.md), [E-40](../../enhancements_doc/Enhancement-40.md), [E-562](../../enhancements_doc/Enhancement-562.md) |
| Noise sources | `white_noise`, `flicker_noise`, `noise_table`, `noise_table_log` (inline data or file; parameter-fed tables are honestly refused — the table bakes at compile time). **Correlation follows the call** (LRM 4.6.4.6): one call's output used in several contributions sums coherently (anti-phase uses cancel exactly), separate calls stay uncorrelated even under a shared label, and the label combines the contribution summary per 4.6.4.1; operating-point-dependent factors and `ddt()`-shaped noise (induced-gate idiom) are exact and add **no matrix unknowns**. `examples/noise_examples/`, `examples/noisecorr_examples/`, `examples/noisejw_examples/` | [E-9](../../enhancements_doc/Enhancement-9.md), [E-42](../../enhancements_doc/Enhancement-42.md), [E-54](../../enhancements_doc/Enhancement-54.md) |
| `analysis("name", …)` | Variadic; matches ngspice's analysis phases per LRM Table 4-22, including the AC/noise operating point counting as `"ac"`/`"noise"`, `"ic"`/`"static"` true at the transient's own operating point (the initial-condition idiom fires there, not at the first timestep), and `"nodeset"` true while `.nodeset` values are enforced. `examples/analysis_examples/` | [E-30](../../enhancements_doc/Enhancement-30.md), [E-53](../../enhancements_doc/Enhancement-53.md) |
| `ac_stim([name, mag, phase])` | Full AC right-hand-side injection — a Verilog-A module can *be* the AC stimulus, with exact magnitude and phase (in **radians**). Activation matches the *running* small-signal analysis per 4.6.3: an `"ac"` stimulus stays out of `.noise` gain solves, and `ac_stim("noise")` participates there. `examples/acstim_examples/` | [E-26](../../enhancements_doc/Enhancement-26.md), [E-51](../../enhancements_doc/Enhancement-51.md) |
| Random / distributions | `$random`, `$arandom`, `$dist_*` and `$rdist_*` (uniform, normal, exponential, poisson, chi-square, t, erlang) — deterministic per `(seed, call site)`, stable across Newton iterations (reproducible Monte Carlo, no convergence breakage). Per the LRM, `$dist_*` returns `integer` and `$rdist_*` returns `real`. The 9.13.2 domain rules (mean/dof/k > 0) abort with the mandated runtime error on deck-supplied violations too, and `type_string` warns outside a paramset. `examples/rng_examples/`, `examples/distint_examples/` | [E-10](../../enhancements_doc/Enhancement-10.md), [E-376](../../enhancements_doc/Enhancement-376.md) |

### Environment and control

| Feature | Notes | Since |
|---|---|---|
| `$temperature`, `$vt[(T)]` | Simulator temperature (tracks `.dc temp` sweeps per point) and thermal voltage. | [E-62](../../enhancements_doc/Enhancement-62.md) |
| `$abstime`, `$realtime` | Identical in the continuous-time analog context. | [E-59](../../enhancements_doc/Enhancement-59.md) |
| `$simparam("name"[, default])`, `$simparam$str("name")` | Numeric and string simulator parameters; ngspice exposes `analysis_name` and `simulator` among others. `examples/simparamstr_examples/` | [E-25](../../enhancements_doc/Enhancement-25.md) |
| `$finish`, `$stop`, `$fatal` | Honored at the accepted-point boundary: `$finish` ends the analysis cleanly (firing `@(final_step)`), `$stop` pauses resumably, `$fatal` aborts with its message — including under solution-dependent conditions, and during setup ("device rejected its configuration"). `examples/simctrl_examples/` | [E-55](../../enhancements_doc/Enhancement-55.md), [E-56](../../enhancements_doc/Enhancement-56.md) |
| Fallback group | `$simprobe` (with a default; the no-default form is the LRM 9.16 error — warned at compile, fatal at run), `$analog_node_alias`, `$analog_port_alias` (analog-initial-only, enforced) compile and return their LRM "mechanism unavailable" fallbacks (see [§4.2](04-limitations-and-gotchas.md#42-features-with-fallback-semantics)). `examples/alias_examples/` | [E-12](../../enhancements_doc/Enhancement-12.md) |

## 2.12 Preprocessor and compiler directives

| Feature | Notes | Since |
|---|---|---|
| `` `define `` with arguments | Macros-using-macros, macro calls as macro arguments, backslash continuations, multi-line calls; **recursive expansion is a clean, located error** (both direct and mutual), while legitimate same-macro nesting inside arguments still works. `examples/preproc_examples/` | [E-65](../../enhancements_doc/Enhancement-65.md) |
| `` `ifdef ``/`` `ifndef ``/`` `elsif ``/`` `else ``/`` `endif `` | Chained and nested, including inside module bodies; unbalanced conditionals are located errors. | [E-65](../../enhancements_doc/Enhancement-65.md) |
| `` `include `` | Nested chains; `-I` search paths. | — |
| `` `default_transition `` | Supplies default rise/fall for bare `transition()` calls. `examples/defaulttransition_examples/` | [E-47](../../enhancements_doc/Enhancement-47.md) |
| Housekeeping directives | `` `celldefine ``/`` `endcelldefine ``, `` `unconnected_drive ``/`` `nounconnected_drive ``, `` `timescale ``, `` `line ``, `` `pragma ``, `` `undefineall ``, `` `resetall ``, `` `default_nettype `` — accepted (previously fatal errors). `examples/directive_examples/` | [E-6](../../enhancements_doc/Enhancement-6.md) |

## 2.12b Later language work

The sections above were written around the first wave of language support. The
following arrived afterwards and are all exercised by their own example suites.

**Declarations and ports.** Name-then-range declarations (`electrical in[0:2];`,
`input in[0:2];` — LRM 3.6/3.7) are normalised to the range-then-name form
([E-89](../../enhancements_doc/Enhancement-89.md)), multi-name declarations split per name
([E-91](../../enhancements_doc/Enhancement-91.md)), and a bus port's INPUT ordering bug was fixed
([E-90](../../enhancements_doc/Enhancement-90.md)). Parameters that shape a declaration width become
`localparam` so the width cannot change at simulation time
([E-92](../../enhancements_doc/Enhancement-92.md)), and a parameter that is never set is reported
([E-93](../../enhancements_doc/Enhancement-93.md)). Block-scoped parameters inside a named `begin`
are supported ([E-87](../../enhancements_doc/Enhancement-87.md)).

**Statements.** `casex`/`casez` with proper don't-care semantics — `z`/`?` for
`casez`, plus `x` for `casex` ([E-78](../../enhancements_doc/Enhancement-78.md)). Part-select on the
left and right of an assignment, and `` `__FILE__``/`` `__LINE__``
([E-85](../../enhancements_doc/Enhancement-85.md)). The legacy `generate` form with an `analog` block
inside ([E-88](../../enhancements_doc/Enhancement-88.md)) and the bare `generate` block
([E-96](../../enhancements_doc/Enhancement-96.md)).

**Builtins.** `$clog2` arity and its `ceil` crash ([E-101](../../enhancements_doc/Enhancement-101.md)–
[E-103](../../enhancements_doc/Enhancement-103.md)), `$rtoi`/`$itor` and the string functions
([E-104](../../enhancements_doc/Enhancement-104.md)–[E-108](../../enhancements_doc/Enhancement-108.md)), `$limit` for
genuine iteration limiting ([E-353](../../enhancements_doc/Enhancement-353.md)), and hierarchical
branch probes ([E-86](../../enhancements_doc/Enhancement-86.md)).

**The LRM's own examples as a suite.** [E-84](../../enhancements_doc/Enhancement-84.md) extracts every
code example from the LRM 2023 PDF and compiles it: 42 compile, 17 are documented
limitations pinned to their diagnostics, and 21 are correctly rejected as
mixed-signal (outside Annex C). The 146 non-module fragments double as a
no-crash corpus.

**Loops must be able to finish.** A provably non-terminating loop — `while (1)`,
or forgetting the increment — is a compile-time error
([E-375](../../enhancements_doc/Enhancement-375.md)):

```
error: loop condition is always true
       help: write what the condition reads inside the loop body, or in the `for` increment
```

A second message, `loop condition can never change`, covers a condition that is not
a literal but that nothing in the loop writes. The check is deliberately
conservative — `repeat (n)` is counted, `$finish`/`$stop`/`$fatal` leave the loop,
and a value passed to a function counts as written, since it may be an output
argument. What it cannot see is a loop whose variables change but never toward the
exit (nested loops sharing an index, where the bounds decide it).

## 2.13 Attributes

Attributes `(* … *)` are how a model talks to the simulator's UI:

| Attribute | Effect |
|---|---|
| `(* desc="…" *)` on a **variable** | Exposes it as an operating-point variable: `print @n1[var]`, `.save @n1[var]`, `.meas` over it — for real *and* integer variables ([E-69](../../enhancements_doc/Enhancement-69.md), `examples/opvar_examples/`) |
| `(* type="instance" *)` on a **parameter** | Exposes it on the instance line and to `alter`/`.dc @n1[param]` ([E-62](../../enhancements_doc/Enhancement-62.md)) |
| `(* desc="…", units="…" *)` on a **parameter** | Description/units metadata in the OSDI descriptor |
| `(* std=σ *)` / `(* std_rel=f *)` / `(* dist="gauss"\|"uniform"\|"lognormal"\|"tgauss" *)` / `(* trunc=n *)` on a **parameter** | Declares the parameter's statistics for `.option osdimc` automatic Monte-Carlo (see [§3.6](03-ngspice-workflows.md#36-monte-carlo)); scalar real, non-local parameters only, and combining `std` with `std_rel` is an error. `dist="lognormal"` (alias `lnorm`) draws `nominal·exp(s·z)`, never crossing zero, with `std_rel` the sigma of the logarithm and an absolute `std` converted at the nominal; `trunc=n` confines the Gaussian coordinate to ±n sigmas (`dist="tgauss"` is gauss with `trunc=3`), and has no effect on a uniform ([E-554](../../enhancements_doc/Enhancement-554.md), `examples/osdidist_examples/`). A parameter the module tests with `$param_given` is drawn only when the deck gives it: a draw is a write, a write marks the parameter given, and a model that derives its default (`toxp = toxe − dtox` unless `toxp` is given) would switch branch instead of varying — the simulator says so once and leaves it alone ([E-555](../../enhancements_doc/Enhancement-555.md)). The sigma is a numeric literal, or a quoted number (`std="25.0"`) — anything else in the quotes (`"25 ohm"`, `"inf"`) is a located error (`examples/osdimc_examples/`) |

A symmetry worth remembering: instance access to *parameters* needs
`type="instance"`; instance access to *variables* needs `desc`. And the
statistics attributes compose with it: a `(* type="instance", std=… *)`
parameter draws per instance (mismatch), a model-card one per card
(process).
