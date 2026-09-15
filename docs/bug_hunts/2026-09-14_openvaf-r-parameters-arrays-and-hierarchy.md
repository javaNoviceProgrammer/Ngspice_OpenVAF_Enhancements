# openvaf-r parameters, arrays, hierarchy and the CLI — a one-hour hunt

**Date:** 2026-09-14, 19:00–20:00. **Target:** the compiler (`openvaf-r`) at
head `c23868ab` (after E-634), through `ngspice-46/build/src/ngspice`.
**Rule of the hour:** find and record, do not fix.

Earlier compiler hunts covered events, noise, analog functions, language
semantics, arithmetic, differentiation, the preprocessor, `$table_model`,
hierarchy diagnostics and file I/O ([09-04](2026-09-04_openvaf-r-compiler.md),
[09-07 a](2026-09-07_openvaf-r-events-noise-and-commands.md),
[09-07 b](2026-09-07_openvaf-r-language-semantics.md),
[09-08](2026-09-08_openvaf-r-hierarchy-elaboration-and-io.md)). This hour went
for what those left aside: parameter ranges on integers, array indexing at
run time, `localparam` and `aliasparam` as ngspice sees them, bus-port
connections, genvar misuse, port directions, `analog initial`, the lint
switches, batch-mode caching, the dump flags and the CLI's edge cases.

## Summary

Five findings and a list of diagnostic slips. Nothing crashes; the five are
all of the "accepted silently, means something else" kind. (Three more
candidates — a `localparam`, a parameter used as a bus bit-select, and a
`paramset`'s fixed assignment, each overridable from a `.model` card — turned
out to be answered by ngspice's `Warning: parameter 'a' is a fixed
(localparam) value and cannot be set from the netlist; ignored`, which the
first pass's output filter had hidden; they are in the smaller notes.)

| # | finding | severity |
|---|---|---|
| F1 | an integer parameter's real range bounds are rounded before the run-time check, so `from (1.5:2.5)` refuses every value (2 included) and `from (0.5:2.5]` refuses 1 and accepts 3 — while the compile-time default check uses the true bounds | correctness — **fixed in [E-635](../../enhancements_doc/Enhancement-635.md)** |
| F2 | an array index outside the declared range at run time reads element 0 and drops the write, with no message; only a literal index is refused, and then as a "bus bit-select" | silent misuse |
| F3 | a reversed part-select `p[3:0]` of a `[0:3]` bus connected to a child port means `p[0:3]`; the concatenation `{p[3],p[2],p[1],p[0]}` does reverse | silent misuse |
| F4 | assigning to a genvar inside its own loop is substituted textually (`0 = 0 + 1`) and reported as a parse error in the generated copy | diagnostic |
| F5 | a contribution to, or a port-flow probe of, an `input` port compiles without a word | lint gap |
| F6 | diagnostic slips: runs of spaces in two messages, `--dump-json` advertised but unimplemented, a `$fatal` without arguments told to "see the message above" that was never printed, and more | wording |

## What was read and run

A harness in the session scratchpad (`hunt13/h.py`) compiles a module from a
string with `openvaf-r` and runs a deck through the repo's `ngspice -b` with
`pre_osdi` in the control block. 45 batches, about 300 probe modules and 280
decks; every number below was read from a run, not inferred — and, after the
first pass's output filter hid an ngspice warning and three "silent" findings
had to be withdrawn, every finding that claims silence was re-run and read
unfiltered. The probe files stay in the session scratchpad (`hunt13/*.va`,
`*.cir`, harness `h.py`).

## F1 — an integer parameter's real range bounds are rounded before the run-time check

*Fixed in [E-635](../../enhancements_doc/Enhancement-635.md): the bound keeps its real type and the parameter's value is compared as a real against it; a range no integer satisfies is refused at compile time.*

```verilog
parameter integer k = 2 from (1.5:2.5);   // the only legal value is 2
```

Every value is refused at run time:

```
Parameter k of 'mm' is out of bounds (value 2; range from (1.5:2.5))!
```

The run-time check rounds the bounds to integers first (half away from zero:
`(1.5:2.5)` becomes `(2:3)`, an empty range) and then compares. The message
prints the real bounds it did not use. The full table, `.model mm m k=<v>`:

| range | legal values | accepted at run time |
|---|---|---|
| `(0.5:2.5]` | 1, 2 | 2, 3 — **1 is refused, 3 accepted** |
| `[1.5:2.5]` | 2 | 2, 3 |
| `(1.5:2.5)` | 2 | **none** |
| `[0:10] exclude 2.5` | 0 … 10 | 0 … 10 except **3** |
| `[0:inf)` | 0 … 2147483647 | **2147483647 refused** (`inf` became the exclusive bound) |
| `(-inf:inf)` | every integer | **−2147483648 refused** |

The compile-time check disagrees with the run-time one: `parameter integer
k = 3 from (0.5:2.5]` gets `warning[L027]: the default value of parameter 'k'
violates its own range` (correct, 3 > 2.5), and `k = 1` gets no warning
(correct, 0.5 < 1) — yet at run time 3 passes and 1 fails. The E-558 range
text (`param_ranges`) also carries the real bounds. Whichever side is meant to
win, the two should agree; the LRM semantics are the real comparison (an
integer is a real for the purpose of `from`).

Repro: `hunt13/ir4.va`, `ir5.va`, `ir3.va`, `p10.va`, `ki1.va` with the decks
beside them.

## F2 — an array index outside the declared range reads element 0 and drops the write

```verilog
parameter integer k = 3;
real a[0:2], b[0:2];
analog begin
  a[0]=10; a[1]=20; a[2]=30; b[0]=40; b[1]=50; b[2]=60;
  I(p,n) <+ V(p,n)*(a[k]+b[k])*1e-3;
end
```

With `k` = 3, 4, −1 or 100 the current is 50 mA: `a[k]+b[k]` is `a[0]+b[0]`.
A write `a[k] = 999` with the same `k` values changes nothing (the sum of all
six elements stays 210). No message at compile time (the index is a
parameter, so it cannot be judged there) and none at run time. The LRM gives
no value to an out-of-range read; a silent element 0 is the worst reading of
that, because the model keeps running on a wrong number. A `$fatal`-style
message naming the array and the index (the `E` mode of `$table_model` is the
precedent) would do.

A literal index is refused, but as a bus: `a[-1]` on `real a[0:2]` gets
`error: bus bit-select index out of range … this bus was declared with width
[0:2]` — `a` is a variable array, not a bus (see F6).

Repro: `hunt13/d1b.va` (reads), `d1c.va` (writes), `d3.va` (literal).

## F3 — a reversed part-select on a bus-port connection is silently un-reversed

```verilog
module ch(a,b); inout [0:3] a; inout b; electrical [0:3] a; electrical b;
  genvar i; analog for (i=0;i<4;i=i+1) I(a[i],b) <+ V(a[i],b)/1k*(i+1);
endmodule
module m(p,n); inout [0:3] p; inout n; electrical [0:3] p; electrical n;
  ch c(.a(p[3:0]), .b(n));      // reversed part-select
endmodule
```

With one volt on each of the four bits, the currents are 1, 2, 3, 4 mA on
`p[0]` … `p[3]` — the same as `.a(p)`: `a[0]` is `p[0]`. The explicit
concatenation `.a({p[3],p[2],p[1],p[0]})` gives 4, 3, 2, 1 mA, so the
reversal is honoured there. A part-select whose index order differs from the
declaration is illegal in Verilog (the usual tool message is "reversed
part-select index ordering"); accepting it as the un-reversed range is the
one reading a user who wrote `[3:0]` did not intend. Refuse it, or honour it.

Repro: `hunt13/bo1.va`, `bo2.va`, `bo3.va`.

## F4 — assigning to a genvar inside its own loop is reported as a parse error in the generated copy

```verilog
genvar i; real s;
analog begin s=0; for (i=0;i<3;i=i+1) begin i = i + 1; s = s + 1; end … end
```

```
error: unexpected token integer; expected ';', '@', 'begin', 'case', 'casex',
'casez', 'disable', 'for', 'if', 'integer', 'parameter', 'localparam', 'real', 'string', 'while',
'repeat', 'do', 'break', 'continue', 'return', identifier or system function identifier
    --> /g5.va__generated.va:135:82
    |
135 | … begin begin 0 = 0 + 1; s = s + 1; end begin 1 = 1 + 1; … 
```

The unroller substitutes the genvar's value everywhere, the assignment
becomes `0 = 0 + 1`, and the parser reports that — three times, once per
copy. The user's mistake is "a genvar cannot be assigned inside its loop"
(a genvar is assigned only by its loop); the check belongs before the
substitution. (The expected-token
list also offers `casex` and `casez`, which are digital Verilog and not
accepted anywhere in an analog block.)

Repro: `hunt13/g5.va`.

## F5 — a contribution to an `input` port compiles without a word

```verilog
module m(p,n); input p; inout n; electrical p,n;
analog I(p,n) <+ V(p,n)/1k;
endmodule
```

compiles clean and runs (1 mA). So do `V(p,n) <+ 1`, `V(p) <+ 1` and the
port-flow probe `I(<p>)` on the same `input p`. `input` says the module reads
the port and does not drive it; a contribution to it is the model
contradicting its own interface, and `I(<p>)` reads a flow the direction says
the module does not carry. `port_without_direction` is a lint (an error by
default) for the missing direction; a contribution against a declared
`input` is the same family and has no lint at all.

Repro: `hunt13/p1.va`, `in1.va`, `in2.va`, `in3.va`.

## F6 — diagnostic slips

* **Runs of spaces** inside two messages, from a backslash continuation in
  the format string: `LRM 3.4.7: an aliasparam is an override spelling only
  --                              'the equations in the module shall …'`
  (`hunt13/c1.va`) and `instance parameter override '.zz' names no parameter
  of module                              'ch' (it declares r)` (`h5.va`).
* **`--dump-json`** is in `--help` ("Abort after lowering and serialize MIR
  as json") and answers `error: currently unimplemented`.
* **`$fatal` with no arguments** (`sv4.va`): ngspice says `see the
  OSDI(fatal) message above for the cause`, but nothing was printed above —
  the no-argument form emits no line. `$info` with no arguments prints
  nothing either (the severity tasks print their severity and location even
  without a message).
* **`'std' and 'std_rel' attributes are mutually exclusive; the absolute
  'std' is used`** is an error (`sd6.va`) that says which one is used.
* **`'std' attribute is ignored: only a scalar real parameter can carry
  statistics`** (on a string or integer parameter) — but `(* std=1 *)
  parameter real a[0:1]` does carry statistics: under `.option osdimc` each
  element is drawn (`osdimc: trial 2: mm:a[0] = -0.818715 (nominal 1)`).
  Either the wording or the array support is off; the array draw looks
  intended, so the wording.
* **`bus bit-select index out of range`** for a literal index into a `real`
  array (F2).
* **`-C foo=bar`** (an unknown LLVM codegen option) is accepted without a
  word; `--target_cpu zzz` at least says it is ignoring the processor
  (twice).
* **`1e400`** is refused as `real literal is too large to represent … this is
  infinity as a double`; `1e308*10` folds to the same infinity and is
  accepted.
* **A contribution outside the analog block** (`m5.va`) gives three errors
  for one mistake (`unexpected token '('; expected identifier` and twice
  `expected discipline but found nature access function 'I'`).

## Smaller notes (not pursued)

* **Fixed parameters.** A `localparam`, a `parameter` used as a bus
  bit-select (`I(a[j],b)` with `parameter integer j`), a parameter that sizes
  an array (`real a[0:N]`) or a bus (`inout [0:W] a`), and a parameter a
  `paramset` fixes (`.r = 2k`) all appear in `showmod` as ordinary model
  parameters; a `.model` write to any of them is answered by ngspice with
  `Warning: parameter 'j' is a fixed (localparam) value and cannot be set
  from the netlist; ignored`. Honest, but the wording calls a declared
  `parameter` a localparam, and the compiler never says at compile time that
  it froze `j` or `N` (the bit-select help text even says the index "must be
  a constant integer literal", which a parameter is not). A compile-time
  note — "parameter `j` selects a bus bit and is fixed at its default" —
  would tell the model author before the netlist does.
* `showmod` of a `.model mm rx` (a paramset with its own `k` and `.r = 1k*k`)
  lists `r 1000`, the base module's default, not the paramset's expression.
* A bus port declared `[3:0]` still puts `a[0]` first on the ngspice instance
  line (the bits are exported ascending whatever the declared direction) —
  E-3 says so; noted because a Verilog reader expects the declared order.

* `$clog2(-1)` is 0; with the unsigned reading of the LRM it would be 32.
* `$rdist_normal(seed, …)` with `seed` a **parameter** compiles; the seed is
  an inout integer variable by the LRM (9.13) and a parameter cannot be
  written. The draws do advance (two calls give different numbers), so the
  state lives elsewhere; a refusal, or a lint, would be honest.
* String relational operators (`s > "a"`) compile and evaluate; the LRM
  defines `==`/`!=` only.
* An analog function that never assigns its return value returns 0 silently;
  an `output` argument never assigned inside the function resets the caller's
  variable to 0 (7 became 0). Both are LRM-undefined; a warning would help.
* `(* type="both" *)` — an unknown value of a known attribute — is ignored
  silently (the parameter is model-only). `(* std=30 *)` on an `aliasparam`
  is accepted without a message as well (`sd9.va`); the draws follow the
  original's `std=25` as far as one trial can tell.
* `white_noise(pw)` with a parameter `pw` = −1e-20 gives zero noise at run
  time with no message; the literal `white_noise(-1e-20)` is refused at
  compile time.
* `$discontinuity(-1)` is accepted.
* There is no way to spell "no zeros" in `laplace_zp`/`laplace_zd`: `{}` is
  refused twice (`unexpected token '}'` and `empty concatenation {} is not
  allowed`); the way round is `laplace_nd`/`laplace_np`.
* A default outside its own range is warned at compile time (L027, for reals,
  integers and array elements) and then runs unrefused: `parameter real r=1k
  from (0:100)` and `parameter integer k=7 from {1,2,3}` both give their
  default's current, while the same value on a `.model` card is refused. A
  string default outside its set is neither warned nor refused — the 09-04
  hunt's F4, still open.
* `$fatal` with no arguments prints no `OSDI(fatal)` line, so ngspice's
  "see the OSDI(fatal) message above" points at nothing (also in F6).
* `$analog_node_alias(x, "nosuch")` in `analog initial` returns its documented
  fallback (0) and the model's `x` stays floating — documented in the
  handbook §4.2, noted here only because the probe read like a bug until the
  docs were checked.

## Coverage, honestly

Verified correct this hour (each with a deck, values matched by hand):

- **Parameters and ranges:** `exclude` single values and intervals, `inf`
  bounds, `exclude [100:inf)`, inclusivity at both ends (`[0:1)` refuses 1,
  accepts 0), ranges referencing an earlier parameter (`from [0:hi]`, checked
  after `hi` is overridden, the message says `hi = 3`), forward and self
  references refused, an empty range `[10:1]` refused at compile time, a
  system function in a default refused, `aliasparam` from the model card,
  the instance line, `alter`, `altermod` and both names at once (refused with
  the LRM clause), `$param_given` for an instance-type parameter given on the
  instance, the model, both, neither, string parameters with `from {"lin",
  "log"}` and an out-of-set value refused, array parameters shown and set per
  element (`a[1]=7`), child-module parameters exported as `c1__r` and
  settable, a `#(.r(2*r))` override following the parent's `r`, statistics
  attributes on string/integer/localparam warned, negative `std`, unknown
  `dist`, `std` with `std_rel`, negative `trunc` refused.
- **Two analog blocks** concatenate (two 1 kΩ contributions give 2 mA);
  declarations after use and assignments in a later block work through
  variable persistence; a variable read before it is written in the same
  evaluation carries the previous iteration's value (LRM); block-local
  variables and shadowing in named blocks; `real x = 2.0` initialisers.
- **Hierarchy:** unconnected child port (`.b()`), `ground` with a discipline,
  `$port_connected` in the child and the top under ngspice, unknown port and
  parameter names and too many positional connections refused with the
  module's list, bus-port width mismatches refused with LRM 6.5.7.1,
  matching part-selects and concatenations connected.
- **Branches:** two named branches on one node pair, a potential source on
  one and a flow on the other, a switch branch (flow, then potential when a
  condition holds), a branch to ground, opposite orientations cancelling,
  the L022 warning for both kinds on one unnamed branch (potential wins).
- **Analog operators:** `laplace_nd` with a model-card-overridden `tau`
  (−3.01 dB and −20.04 dB at the corner), `ddt(idt(x))` = x in ac, `absdelay`
  with `td` above `maxdelay` (clamped to `maxdelay`) and with a
  node-controlled, time-varying delay (`out(t) = in(t − td(t))`),
  `transition` and `slew` with overridden times and rates, `ddt` under `m=4`
  (charge scales), an explicit `/$mfactor` undoing `m`, `white_noise` under
  `m=4` (power scales), same-labelled noise calls uncorrelated (the E-42
  design), `flicker_noise` with an overridden exponent (1/f and 1/f²),
  exponent 0, ddt inside genvar loops (two copies, two states) and refused in
  `repeat`/`for`/`while` bodies.
- **Differentiation:** ac conductance against a finite-difference dc slope
  for `pow` under a node-dependent `if`, a `for` accumulating powers, a
  `case (1)` pattern, `max`/`min`, `limexp`, `$limit(…,"pnjlim",…)`, an
  internal node with a potential contribution, a self-referential
  `I(p,n) <+ … + I(p,n)*0.5`, `atan2`/`hypot`/`tanh`/`floor`; `ddx` signs
  w.r.t. `V(p)` and `V(n)`, nested `ddx`, `ddx` inside a function refused.
- **Types:** the result type of 22 mixed-type expressions (`max(1,2.5)` real,
  `2**-1` integer, `1&&2.5` integer, …) all as the LRM has them; shifts by
  32 and −1 warned and zero; `>>>` warned as an extension; integer overflow
  wraps; over-wide literals saturate with L030; `$rtoi(±1e300)` saturates;
  `%x %o %b %c %+d % d %-8d %08.3f` formats; escapes `\t \" \101 \\ %%`.
- **CLI and lints:** `-E warnings`/`-E <lint>` turn a warning into a failing
  build, `-A all`/`-A warnings` silence it, `-W errors` leaves an error
  alone, an unknown lint name lists the known ones; batch mode caches on the
  expanded source plus options (an `include` edit recompiles, a root edit
  under an untaken `ifdef` reuses the object, `-D` and `-O` change the key);
  nested `include` resolves relative to the including file and wins over
  `-I`; a directory or a missing file as `include`, `-o` a directory or a
  missing directory, no or two input files, an input without extension,
  `--target_cpu generic`, `--print-expansion`, `--dump-mir`,
  `--dump-unopt-mir`, `--dump-ir`, `--dry-run` all behave; `-O0`…`-O3` give
  identical op/ac/tran currents on EKV and DIODE_CMC.
- **Robustness:** a portless module, 300 and 600 ports (4 s and 9 s), a
  10 000-element array parameter (4 s), a 1 000-iteration genvar loop, a
  500-item `case`, a 10 000-character identifier, a `$strobe` with 100
  arguments, 3 000 nested parentheses and 20 000 unary minuses refused as
  nesting too deeply, a NUL byte, an unterminated comment, no newline at EOF.
- **Severity tasks:** `$warning`/`$error` print and continue, `$fatal` aborts
  the analysis with the "not a convergence failure" note, `$error` under a
  node condition fires once per accepted point with distinct text and is
  de-duplicated for identical text; `analysis("dc"/"static"/"tran"/"ac"/
  "noise")` under op, dc, tran, ac and noise.
- **`analog initial`:** contributions and probes refused with the LRM
  reason, `$temperature` available, a parameter-derived value reaching the
  analog block after a model-card override.

Not exercised: the Windows and Linux prebuilt compilers, `--target` cross
compilation beyond confirming the refusal, `paramset` beyond the two above, `$table_model`
(covered on 09-08), file I/O, mixed-signal constructs, and the OSDI
descriptor other than through ngspice's `show`/`showmod`.
