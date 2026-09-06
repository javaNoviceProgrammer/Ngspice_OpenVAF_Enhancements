# Coverage audit — *A Practical Guide to Verilog-A* (Apress, 2022) against ngspice + openvaf-r

**Date:** 2026-09-05 · **Tree under test:** `aa520ebc` · **Binaries:** the locally built
`OpenVAF-master-20260610/target/opt/openvaf-r` and `ngspice-46/build/src/ngspice`.
**Source:** *A Practical Guide to Verilog-A* (Apress, 2022).
**Reproduction:** every construct-level check is a file in
[`2026-09-05_repro-book/`](2026-09-05_repro-book/) (107 probes, `run_all.sh`).

The book is a tutorial on Verilog-A as fixed by LRM 2.4 (Accellera, 2014), organised in
twenty chapters plus an appendix. This audit reads every chapter, lists the constructs it
teaches, and checks each against what the compiler and simulator do: first against the
project's own statements ([LRM compliance matrix](../compliance/OpenVAF_Verilog-A_LRM_Compliance.md),
[handbook ch. 2](../handbook/02-verilog-a-language.md) and [ch. 4](../handbook/04-limitations-and-gotchas.md)),
then — for every construct those documents do not pin, and for every one where the book's
spelling differs from the LRM's — by compiling a probe of the construct written for this
audit (or the LRM's own example, where the book reprints one). The result is the
list of features the book discusses that this tool chain does **not** cover, ranked by how
much a compact-model or behavioural-model author would miss them.

> **Update, 2026-09-06 (tree `757d27db`).** Five enhancements followed this audit:
> [E-561](../../enhancements_doc/Enhancement-561.md) (bit-level concatenation, §3.2), [E-562](../../enhancements_doc/Enhancement-562.md) (lookup tables, §3.5), [E-563](../../enhancements_doc/Enhancement-563.md)
> (paramsets and the crash, §3.1, §3.3), [E-564](../../enhancements_doc/Enhancement-564.md) (names into generate blocks, §3.4) and
> [E-565](../../enhancements_doc/Enhancement-565.md) (paramset overloading, §3.3). Re-running the 107 probes on that tree
> ([`run_all_after.out`](2026-09-05_repro-book/run_all_after.out)) gives **73 compiling
> and 34 refused, no crash** (was 53 / 54 with one crash). Each finding below keeps its
> original text and carries a **fixed** tag where it no longer holds; §6 sums up what
> remains. The chapter table shows the status after the update.

## 1. Summary by chapter

| Ch. | Topic | Coverage | What is missing (details in §3) |
|---|---|---|---|
| 1 | Lexical basis | ✅ full | — |
| 2 | Basic types and expressions | ✅ full | — (bit-level concatenation and replication of integers: fixed, E-561; was the one edge) |
| 3 | Net-discipline types | ✅ full | vector-net initialiser with a *gap* (`'{2.3, ,6.0}`) (3.2) |
| 4 | Modules and ports | ✅ with edges | `macromodule`; a bus *part-select* in a port connection (`{a[4:0], b}`); SPICE primitive instantiation (documented ✖) (3.2, 3.7) |
| 5 | Parameters | ✅ with edges | the module-header parameter list `module m #(parameter …) (…)`; `defparam x.$mfactor` (3.2) |
| 6 | Paramsets | ✅ full | — (all of 3.3 fixed, E-563 and E-565, and the 3.1 crash; a random draw in an override stays the documented E-545 deviation) |
| 7 | Procedural programming | ✅ full | — |
| 8 | Branches | ✅ with edges | vector branches (documented ✖); vector *port* branches; hierarchical references to a child's **ports** and the `inst.branch(a,b)` spelling (3.4) |
| 9 | Derivative and integral operators | ✅ full | — |
| 10 | Built-in math functions | ✅ with edges | a *constant* seed in `$arandom`/`$rdist_*`; random draws in paramset overrides (documented deviation, E-545) (3.6) |
| 11 | User-defined functions | ✅ full | — |
| 12 | Lookup tables | ✅ full | — (all of 3.5 fixed, E-562; the control string or file name is a `localparam string`, an overridable `parameter string` being refused by design) |
| 13 | Small-signal functions | ✅ full | — |
| 14 | Filters | ✅ full | — |
| 15 | Events | ✅ full | `OR` in upper case (the LRM has only `or`); tolerances accepted, not honoured (documented ⚠️) |
| 16 | Runtime support | ✅ full | `$simparam$str` of `module`/`instance`/`path` (documented ⚠️); `$simprobe` fallback (documented ⚠️) |
| 17 | Input and output | ✅ full | literal separators in a `$fscanf` format (documented) |
| 18 | Generative programming | ✅ with one edge | names into generate blocks and `case`-generate: fixed, E-564; generate conditions on module *parameters* remain the documented deviation, E-67 (3.4) |
| 19 | Attributes | ✅ with one edge | an attribute instance inside a port-connection list (3.2) |
| 20 | Compiler directives | ✅ full | — |
| App. | Reserved words, SPICE primitives | ✅ / ✖ | SPICE primitives are not instantiable from Verilog-A (documented ✖, Annex E) |

Of the 107 probes, 53 compile and 54 are refused or crash. Eleven of the refusals are the
correct answer (the book's own mistakes, §4, and constructs this project documents as out
of scope: vector branches, SPICE primitives, an upper-case `OR`, a random draw in a
constant, a generate condition on a module parameter). The other 43 reduce, once the
isolation rounds are folded together, to **24 distinct constructs** the tool chain does not
cover (§3.1–3.6) — one of them a compiler crash. *After the 2026-09-06 update: 73 compile
and 34 are refused, none crashes; 12 of the 24 constructs are covered (§6).*

## 2. What the book teaches and this tool chain covers

The bulk of the book is covered, and where it was not already pinned by a suite, a probe of
the construct compiled (and, for the semantic cases, ran):

* **Ch. 1–2.** Escaped identifiers (`\level-1`, an escaped keyword), sized and based
  literals, scale factors, underscores in literals, octal escapes in strings, every
  operator including `**`, `^~`/`~^`, shifts, the ternary, string relational operators,
  string concatenation `{s, "def"}`, assignment patterns (nested 2-D, `'{2{y}}` replication)
  for array parameters and variables, ranges.
* **Ch. 3.** Base and derived natures, user attributes on natures (`reltol`, `maxval`),
  a nature derived from a discipline's flow (`nature x : enode.flow`), discipline attribute
  overrides (`flow.abstol = 10u`), reading them back (`a.flow.maxval`,
  `vp.flow.abstol` as a `ddt` tolerance), scalar and vector nets, both `ground` spellings,
  net initialisers (`electrical c = 5.0;`, `'{2.3,4.5,6.0}`), the predefined natures and
  disciplines (`rotational`, `kinematic` and their `Theta`/`Tau`/`Pos`/`F` accessors).
* **Ch. 4.** Both port-declaration styles, vector ports, explicit and positional mapping,
  unconnected ports (`.out()`), instance arrays (`res r[0:3] (x, b)`), implicit nets,
  `$root`, element lists in a port connection.
* **Ch. 5.** Ranges with `inf`, `exclude` of a value and of ranges, ranges on array
  parameters, string parameters with `from '{…}` and `exclude '{""}`, `aliasparam`,
  `localparam`, override by name and by order, the empty override `.LP()`, `defparam`,
  and the hierarchical system parameters read (`$mfactor`, `$xposition`, `$yposition`,
  `$angle`, `$hflip`, `$vflip`) and overridden on an instance (`.$mfactor(2)`).
* **Ch. 6.** A plain paramset with its own parameters and `.p = …` overrides, and
  `.$mfactor = 1.0` in a paramset.
* **Ch. 7.** Named blocks with block-scoped `parameter`s and hierarchical access
  (`myscope.localVar`), whole-array assignment with size checking, `case` with item
  lists, `while`, `for` with a real control variable, `repeat`, multiple `analog initial`
  blocks with display output.
* **Ch. 8.** Scalar, single-terminal and port branches (`branch (<p>) bp`, `I(bp)`,
  `flow(bp)`, `I(<p>)`), the generic `potential()`/`flow()` accessors, unnamed
  branches, direct and indirect contributions (`V(out) : V(pin,nin) == 0`), probe
  branches, **value retention** (the LRM's `value_ret` example reads 7.0 V in ngspice,
  the LRM answer, with a warning that the branch is contributed as both kinds), switch
  branches keyed on `$mfactor`, hierarchical reads and contributions of a child's
  *named* branch (`V(d1.br)`, `I(d1.br) <+`), and `V(bp)` on a port branch correctly refused.
* **Ch. 9.** `ddt` with a tolerance or a nature, `idt` in all five forms, `idtmod` in all
  six, `ddx` against a potential and a flow, indirect contributions with `ddt` on the
  equation's left-hand side (a second-order gap sensor, and the LRM's equation-of-motion
  example), a VCO phase through `idtmod`.
* **Ch. 10.** Every function in both spellings (`ln`/`$ln`, `$clog2`, `hypot`,
  `atan2`, the hyperbolics), `$arandom`/`$random` with a variable seed, and all seven
  `$rdist_*` functions.
* **Ch. 11.** Untyped (`real`-defaulting) functions, `output`/`inout` arguments,
  array arguments in the LRM's own spelling (`inout [0:1] a; real a[0:1];`),
  assignment patterns as array arguments, function-local `parameter`s, and an
  expression passed to an `output` argument correctly refused.
* **Ch. 12.** `$table_model` with a file, with assignment patterns as the data source,
  the `D` closest-point lookup, `C`/`L`/`E` extrapolation, and the `;n` dependent
  selector.
* **Ch. 13.** `ac_stim()` in all four forms, `white_noise`/`flicker_noise` with and
  without labels, `noise_table` from an assignment pattern and from a file,
  `noise_table_log`, correlated noise through shared variables.
* **Ch. 14.** `absdelay` (with `maxdelay`), `transition` in all five forms, `slew` in all
  three, all four Laplace forms with patterns, parameters, a tolerance or a nature, the
  *null* zeros argument (`laplace_zd(x, , '{…})`), and all four Z-domain forms with
  `T`, the transition time and `t0`.
* **Ch. 15.** `initial_step`/`final_step` with analysis lists, `cross` with five
  arguments, `above` with four, `timer` with four, `last_crossing` with and without a
  direction, `or` and comma lists.
* **Ch. 16.** `$port_connected`, `$param_given`, `analysis()` with several names
  including `"ic"`, `"nodeset"`, `"static"`, `$vt(T)`, `$abstime`, `$simparam` with and
  without a default for every name in the book's Table 16-2, `$simparam$str` of the
  analysis name/type and `cwd`, `$simprobe` with a default, `$discontinuity` in all
  three forms, `$bound_step`, `$limit` with a **user-defined limiting function** (the
  LRM's `spicepnjlim` diode, which the book reprints), with `"pnjlim"`/`"fetlim"` and
  bare, `limexp`, and
  `$fatal`/`$error`/`$warning`/`$info`/`$finish`/`$stop` with their arguments.
* **Ch. 17.** Multichannel and file descriptors, `$fopen` with a type, `$ftell`,
  `$fseek`, `$rewind`, `$ferror`, `$feof`, `$fflush` with and without an argument,
  `$fgets`, `$fscanf`/`$sscanf` with whitespace-separated formats, the display family
  (`$display`, `$write`, `$strobe`, `$monitor`, `$debug`), the file family
  (`$fdisplay` to OR-ed descriptors, `$fwrite`, `$fstrobe`, `$fmonitor`, `$fdebug`),
  `$swrite`, `$sformat`, and the `%h %d %o %b %c %s %e %f %g %r %m %l %%` formats.
* **Ch. 18.** `generate`/`endgenerate` regions, `if`-generate on a `localparam` or a
  literal, `for`-generate with `genvar` instantiating modules and analog blocks (the
  LRM's `rcline`), a genvar loop inside an analog block with a literal bound.
* **Ch. 19.** Attributes on modules, ports, parameters, nets, variables (the
  `desc`/`units`/`op`/`multiplicity` set, duplicated names), on module instances, on a
  `defparam`, on an event control statement, on an *operator* (`a + (* x *) b`), on a
  conditional operator and on a user-function call; `port_discipline` on an instance.
* **Ch. 20.** `` `include ``, object-like and function-like macros, multi-line macros,
  `` `undef ``, nested `` `ifdef``/`` `elsif``/`` `else``, a macro inside a nature
  (the LRM's `CURRENT_ABSTOL` idiom), `` `default_transition ``, and the predefined
  `` `__VAMS_COMPACT_MODELING__ `` (defined, and usable as a value).

## 3. What the book teaches and this tool chain does not cover

Ranked by how often a model author meets the construct. The probe file that shows each
one is named in brackets; the diagnostic quoted is the compiler's.

### 3.1 A compiler crash

* **A hierarchical reference to another module's `localparam` inside a paramset
  override crashes the compiler** [`u10_ps_hierref`] — **fixed, [E-563](../../enhancements_doc/Enhancement-563.md)** (the reference
  is folded at elaboration; a non-local parameter is refused, as LRM 6.4.1 requires). The book's "constant module"
  idiom — a top-level module of `localparam`s read from an override, as in
  `.RSH = fab.rsh_poly * fab.bias;` — is LRM 6.4.1 ("hierarchical
  out-of-module references to local parameters of a different module" are allowed in
  override statements). The compiler panics in code generation
  (`openvaf/mir_llvm/src/builder.rs:950`, on an `fmul` whose operands it never
  defined) instead of either honouring or refusing the reference. This is a robustness
  bug, not a coverage gap, and the only crash the audit found.

### 3.2 Syntax the book uses and the compiler refuses

* **The module-header parameter port list** [`u05`, `u06`]:
  `module gainblk #(parameter real gain = 10.0) (inout electrical a, b);` →
  *unexpected token '#'; expected ';'*. Parameters must be declared in the body.
* **`macromodule`** [`t10`, `w07`]: not accepted as a synonym for `module` (LRM 6.2).
* **Bit-level concatenation and replication of integers** [`u39`, `u40`] — **fixed, [E-561](../../enhancements_doc/Enhancement-561.md)**:
  `r = {1'b1, 3'b101};` and `r = {4{w}};` are typed as arrays (*expected integer value
  but found integer[0:2] value*), not as the 4-bit integer 4'b1101 the LRM defines.
  String concatenation `{s, "def"}` works.
* **A vector-net initialiser with a gap** [`t09`]: `electrical [0:4] pins = '{2.3, 4.5, ,6.0};`
  (a missing element means "no initial value") is a parse error; the same list without
  the gap compiles.
* **A bus part-select in a port connection** [`u42b`]: `.in({a[3:0], b})` is counted as
  5 nets for an 8-bit port — the slice `a[3:0]` is taken as one element. Listing the
  elements (`{a[3], a[2], a[1], a[0], b}`) works [`u42`].
* **A vector port branch with a range** [`t18b`]: `branch (<vp>) vbp [1:3];` is a parse
  error (vector branches in general are documented as out of scope, handbook §4.1; the
  scalar port branch works).
* **`defparam` of a hierarchical system parameter** [`w08`]: `defparam g3.$mfactor = 3;`
  → *defparam target(s) did not resolve to any parameter*. The instance form
  `#(.$mfactor(2))` works [`w04`].
* **An attribute instance inside a port-connection list** [`u38`]:
  `r r3 ((* port_discipline="electrical" *) n1, n2);` loses the port list (*connects 1
  port(s) but 'r' declares 2*). Every other attribute placement in the book works.
* **`OR` in upper case in an event expression** [`u29b`]. The LRM's grammar has only the
  keyword `or` (and the comma), so this is the book's extension; noted for completeness.

### 3.3 Paramsets (chapter 6)

The plain paramset works; the chapter's central idioms do not — *as of 2026-09-06 they
all do ([E-563](../../enhancements_doc/Enhancement-563.md), [E-565](../../enhancements_doc/Enhancement-565.md)), except the documented random-draw deviation:*

* **A paramset parameter with the same name as a parent-module parameter is refused**
  — **fixed, [E-563](../../enhancements_doc/Enhancement-563.md)** [`u07`]: `paramset rp vres; parameter real L = 3u; .L = L;` →
  *'L' was already declared in this scope* and *definition of 'L' references itself*.
  LRM 6.4 makes paramset parameters independent of the module's, and every paramset in
  the book (and most in practice) reuses the names.
* **A paramset whose parent is another paramset cannot override the parent paramset's
  own parameters** — **fixed, [E-563](../../enhancements_doc/Enhancement-563.md)** [`u08`]: `.KIND = "metal"` in the child gives *definition of 'MAT'
  references parameter 'KIND' defined afterwards* — the two-level chain is elaborated
  in one scope in the wrong order.
* **Same-name (overloaded) paramsets are refused** — **fixed, [E-565](../../enhancements_doc/Enhancement-565.md)**, with the 6.4.2
  selection on both routes [`u12`, `t14`]: *'rp' was already
  declared in this scope*. The LRM 6.4.2 resolution rules (fewest un-overridden
  parameters, most ranged locals, …) that the book explains at length therefore have
  nothing to act on.
* **`aliasparam` inside a paramset is not usable in an instance override** — **fixed,
  [E-563](../../enhancements_doc/Enhancement-563.md)** [`w03`]:
  `aliasparam LL = LEN;` then `rp #(.LL(3u))` → *'.LL' names no parameter of module
  'rp'*.
* **Paramset variables and output-variable overrides** — **fixed, [E-563](../../enhancements_doc/Enhancement-563.md)** [`u11`]:
  `(* desc="dissipated power" *) real pdis; pdis = .reff * 1e-6;` → *expected
  'parameter', 'localparam' or '.'*. LRM 6.4.1 allows variables and procedural statements in a
  paramset to compute output variables; this project has no such mechanism.
* **Random draws in a paramset override** [`u15`, `t04`]: `.W = WID + $rdist_normal(seed, 0, 5n, "instance")`
  → *random draw '$rdist_normal' is not allowed in constants*. This is a documented
  design decision (E-545): statistical variation is declared with `(* std *)`,
  `(* dist *)` and the osdimc machinery instead of by LRM 9.13 draws in constants. The
  book's Monte-Carlo idiom (chapter 10's `semicoCMOS`/`nch` example) therefore has a
  different spelling here rather than being unavailable.

### 3.4 Hierarchy and generate (chapters 4, 8, 18)

* **Hierarchical references to a child instance's ports** [`u20`, `w06`]: `V(d1.x)` and
  `V(o, d1.y) <+ …`, where `x`, `y` are ports of `d1`, fail with *'d1__y' was not found*.
  A child's *internal* nets (`V(u1.mid)`, [`w05`]) and *named branches* (`V(d1.br)`,
  `I(d1.br) <+`, [`u17`, `u18`]) work, so the gap is the port alias only.
* **The `instance.branch(a, b)` spelling of a hierarchical unnamed branch** [`u19`]:
  `V(d1.branch(x,y)) <+ 1.25;` is not recognised.
* **Hierarchical names into generate blocks** — **fixed, [E-564](../../enhancements_doc/Enhancement-564.md)**, the implicit
  `genblk<n>` names included [`w01`, `u34b`, `u36`]: `V(blk.x)` for a
  named `if`-generate block and `V(g1[0].z)` for a `for`-generate instance are not found
  (*'blk' was not found in the current scope*; *unexpected token '.'*). The blocks
  themselves elaborate; only naming into them fails. The book's chapter-18 examples on
  `genblk<n>` naming are therefore not reachable either.
* **`case`-generate** — **fixed, [E-564](../../enhancements_doc/Enhancement-564.md)** (`t32d` now fails only on its `parameter`
  selector, the E-67 deviation below; with a `localparam` it compiles) [`u33`, `t32d`]: a module-level `case (sel) 1: begin : one … end
  default: … endcase` is not elaborated (*'one' was not found*).
* **Generate conditions on a module parameter** [`t32b`, `t32c`]: `if ($param_given(coeff1)
  && coeff1 != 0.0)` and `for (k = 1; k <= width; …)` with a `genvar` are refused —
  *the condition must be an elaboration-time constant (integer literals and genvars);
  module parameters bind at simulation time under OSDI*. This is the documented E-67
  deviation (handbook §4.3); a `localparam` or a literal in the condition works
  [`w02`, `u35`]. The book's `nlres` (select a contribution by a parameter) and
  `nmosfet` (`if (nqsMod) begin : nqs electrical GP; … end`, optional internal nodes)
  examples are exactly this pattern; the runtime `if` inside the analog block is the
  workaround for the first, and there is none for parameter-conditional *nodes*.

### 3.5 Lookup tables (chapter 12)

* **Array variables as the data source** — **fixed, [E-562](../../enhancements_doc/Enhancement-562.md)** [`u22`, `u23`]: `$table_model(0, V(a,b), y, x, f)`
  with 1-D arrays, and `$table_model(0, V(a,b), grid)` with a 2-D array, are refused
  (*'y' requires a bit-select [i]*). A file and an assignment pattern (`'{1.0,2.0,3.0}`)
  work [`u23b`].
* **A string parameter as the control string** — **fixed, [E-562](../../enhancements_doc/Enhancement-562.md)**, as a `localparam
  string` (the table is built when the model is compiled, so an overridable `parameter
  string`, which `u21` declares, is refused with that reason) [`u21`]: `parameter string ctl = "3LL,3LL"; … $table_model(…, "sample.tbl", ctl)`
  → *invalid function arguments*; only a literal is accepted, so the book's "external
  control of the interpolation" is unavailable.
* **The `I` (ignore this column) control** [`u25`] and **quadratic/cubic spline
  interpolation (`2`, `3`)** [`u27`, `t26`] — **fixed, [E-562](../../enhancements_doc/Enhancement-562.md)** (`3` already worked;
  `2` and `I` were the gap): *unsupported $table_model control string*.
  `D` (closest point), `1`, `C`/`L`/`E` extrapolation and the `;n` selector work.

### 3.6 Random numbers (chapter 10)

* **A constant seed** [`u14`]: `$rdist_normal(1, 0, 1n)` → *expected integer variable
  reference or integer parameter ref but found integer literal*. LRM 9.13 allows "a
  parameter or constant" (the function then keeps an internal seed); the book's
  `semicoCMOS` example uses literal seeds 1 and 2. A variable or parameter seed works.
* The `type_string` argument outside a paramset warns (correctly, per the LRM); inside
  a paramset it is unreachable because of 3.3.

### 3.7 Documented deviations the book relies on

These are already stated in the compliance matrix or the handbook and are listed only so
the chapter table is complete:

* **Vector branches** (`branch (a, b) vb;`, slices, `[1:2]` ranges) — out of scope,
  per-bit branches instead (handbook §4.1) [`t18`].
* **SPICE primitive instantiation** (`resistor #(.r(1k)) R1 (a, b);`, `vsine`) —
  Annex E is not supported; instantiate SPICE devices at netlist level [`t35`].
* **Event tolerances** (`cross(…, dir, ttol, xtol)`, `above(…, ttol, xtol)`,
  `timer(…, ttol)`) are accepted and warned as *not honored*: event detection is
  evaluation-granular and does not bound the time step [`u31`].
* **`$simparam$str("module")`, `"instance"`, `"path"`** warn as not provided (L025);
  `analysis_name`, `analysis_type`, `cwd` are served [`t30`].
* **`$simprobe`** returns its default (no runtime probing of sibling instances)
  [`t30`].
* **`$fscanf`/`$sscanf` formats with literal separators** (`"%f,%d"`, `"%f*%d"`) are
  refused with a message that says the scanner splits on whitespace [`t31`].
* **`limexp` is stateless** and **random draws do not advance a seed** across
  iterations (handbook §4.4) — the book describes `$arandom` as returning a new number
  on every call.
* **`$discontinuity` inside a user function** compiles and is honoured through
  `$limit` [`t30`].

## 4. The book's own mistakes, caught by the compiler

Where the book's text disagrees with the LRM, the compiler sides with the LRM. These are
not gaps:

* `real table[0:2][0:11]` — `table` is a reserved word (the book's own appendix lists it) [`t26`].
* `int A[10:1]` — there is no `int` type in Verilog-A [`t36`].
* The `$table_model` control string `"1LL,1LL:2"` — the dependent selector is introduced by
  `;`, not `:` [`t26b`].
* `arrayadd(x, '{y, z})` against `input [0:4] b` — a two-element pattern for a five-element
  argument (the probe uses matching sizes).
* An expression or a probe passed to an `output` argument of a user function is
  refused, as the book says it should be [`t25b`].
* `A = C` with arrays of different sizes is refused, as the book says [`t16b`].
* `V(bp)` on a port branch is refused, as the book says [`t18c`].

## 5. Method notes

* Every probe is an original model written for this audit around one construct the
  book teaches; where the book reprints an example from the LRM, the LRM's example is
  used (the reproduction README lists them). No listing original to the book is
  reproduced here.
* Every probe is reduced to the construct under test, so a refusal names one thing. Where a first-round file failed on several constructs at once
  (`t14`, `t26`, `t29`, `t31`, `t32d`, `t33`), the second and third rounds split it.
* Coverage claims for constructs the project already pins (§2) were taken from the
  compliance matrix and its suites and *re-checked* by compiling a probe; no claim in
  §2 rests on the documents alone.
* Nothing was fixed during the audit. The crash in §3.1 and the paramset gaps in §3.3
  are the two items that would matter first for a model author following this book
  (both were fixed in the following days; §6).

## 6. Status after the follow-up enhancements (2026-09-06)

Tree `757d27db`; the 107 probes re-run with the same script
([`run_all_after.out`](2026-09-05_repro-book/run_all_after.out)): 73 compile, 34 are
refused, none crashes. Twenty probes changed status, all from refused (or crashed) to
compiling: `t02`, `t14`, `t26c`, `u07`, `u08`, `u10`, `u11`, `u12`, `u22`, `u23`, `u25`,
`u27`, `u33`, `u34`, `u34b`, `u36`, `u39`, `u40`, `w01`, `w03`.

| finding | enhancement | pinned by |
|---|---|---|
| 3.1 the crash on `fab.rsh_poly` in an override | [E-563](../../enhancements_doc/Enhancement-563.md) | `paramsetlrm_examples` |
| 3.2 bit-level concatenation and replication of integers | [E-561](../../enhancements_doc/Enhancement-561.md) | `concat_examples` |
| 3.3 same-name parameters, paramset chains, `aliasparam`, variables and statements | [E-563](../../enhancements_doc/Enhancement-563.md) | `paramsetlrm_examples` |
| 3.3 overloaded paramsets and the 6.4.2 selection | [E-565](../../enhancements_doc/Enhancement-565.md) | `paramsetoverload_examples` |
| 3.4 names into generate blocks, `case`-generate, single-item branches | [E-564](../../enhancements_doc/Enhancement-564.md) | `genhier_examples` |
| 3.5 array data sources, a string parameter as control, `I`, the `2` spline | [E-562](../../enhancements_doc/Enhancement-562.md) | `tablesrc_examples` |

Beyond the probes, the same work fixed two things the audit had not seen: a paramset
instantiated *inside a module* rendered the module at its defaults (the book's divider
never computed what it said), and a generate branch without `begin`/`end` swallowed the
items after it. Both are pinned in the suites above.

Still open, with the probe that shows each (eleven constructs):

* the module-header parameter port list `module m #(parameter …) (…)` [`u05`, `u06`, `t12`];
* `macromodule` [`t10`, `w07`];
* a vector-net initialiser with a gap [`t09`];
* a bus part-select in a port connection [`u42b`, `t11`];
* a vector port branch with a range [`t18b`] (vector branches are documented out of scope);
* `defparam` of a hierarchical system parameter [`w08`];
* an attribute instance inside a port-connection list [`u38`, `t33`];
* hierarchical references to a child instance's *ports* [`u20`, `w06`, `t19b`] and the
  `instance.branch(a, b)` spelling [`u19`];
* a constant seed in `$arandom`/`$rdist_*` [`u14`];
* `OR` in upper case in an event expression [`u29b`, `t29`] (the book's extension).

Unchanged by design, as documented: a random draw in a paramset override (E-545;
[`u15`, `t04`]), a generate condition or case selector on a module parameter (E-67;
[`t32b`, `t32c`, `t32d`]), SPICE primitives, vector branches, event tolerances, the
`$fscanf` literal separators, and the book's own mistakes of §4.
