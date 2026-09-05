# Bug hunt — openvaf-r, the compiler itself

**Date:** 2026-09-04 · **Commit under test:** `1561a058` · **Binaries:** the
repository's prebuilt `bin/macos/apple-silicon/openvaf-r` (OpenVAF-Reloaded
23.6.0, md5 `cf217a56…`, the same file as `~/bin/openvaf-r`) and the locally
built `ngspice-46/build/src/ngspice` to execute what it compiles.
**Duration:** 20:43–21:43, foreground only, nothing fixed; the document was
written from 21:17 on and extended as the last batches came in.

Every earlier hunt aimed at the simulator side of the pair. This one aims at
the compiler: language front end, semantic checks, diagnostics, the
preprocessor, batch mode and the command line, and — through ngspice —
whether the code it emits computes the right numbers. Method: some four
hundred small Verilog-A modules written for this pass, each compiled and
where meaningful run against a closed form, the LRM's own rule, or the
finite-difference of the value it prints; plus the whole `VA-Models` corpus
compiled once. A verdict is recorded only where the LRM or arithmetic
decides it; where my own expectation was the thing that was wrong (it was,
nine times), the line went into the "holds" list instead.

**Result: one compiler crash, two silent semantic gaps, eight smaller
findings on diagnostics, definitions and the command line, and a very long list of things
that are right.** The crash is a parameter default or
range that names `$temperature`, `$vt`, `$abstime` or `$port_connected`:
the compiler panics instead of diagnosing it. The gaps are a model
parameter whose range or default depends on an instance parameter — checked
once against that parameter's default, never per instance — and an internal
node that nothing can contribute to, which compiles silently and is a
singular matrix at run time.

| # | finding | severity |
|---|---|---|
| [F1](#f1--a-system-function-in-a-parameter-default-or-range-crashes-the-compiler) | `parameter real t0 = $temperature;` (also `$vt`, `$abstime`, `$port_connected`, in a default, a range bound, an array default, an instance-typed or integer parameter) panics at `mir_llvm/src/builder.rs:143`, *attempted to read undefined value*; `$mfactor` and `$random` in the same place are accepted silently and evaluate to 1 and to one fixed number | **high** — crash on a one-line model. **Fixed** (refused in constants, with the rule named) |
| [F2](#f2--a-model-parameters-range-or-default-that-references-an-instance-parameter-is-evaluated-with-that-parameters-default) | `parameter real l = 1e-6 from (0:w]` with `w` instance-typed: an instance with `w=0.5u` runs with `l/w = 2`; `parameter real l = 2*w` reads 2e-6 whatever the instance's `w` | medium — silent wrong value or unchecked range |
| [F3](#f3--an-internal-node-nothing-can-contribute-to-compiles-silently-and-is-singular-at-run-time) | a node used only as a probe, contributed only under `if (0)`, or only inside a genvar loop of zero iterations: no diagnostic, *singular matrix: check node n1#x* at run time | medium-low — silent compile, failed run |
| [F4](#f4--a-string-parameters-default-outside-its-own-range-is-not-diagnosed-and-runs) | `parameter string mode = "cubic" from {"lin","quad"}` compiles without a word (a real gets L027) and runs with `"cubic"`; only a card value is refused | low-medium — the range is not a range for defaults |
| [F5](#f5--integer-power-saturates-where-every-other-integer-operator-wraps) | `10**10`, `2**31`, `3**20` give 2147483647; `100000*100000` and `2147483647+10` wrap | low — inconsistent overflow |
| [F6](#f6--a-flat-sum-of-a-thousand-terms-is-rejected-as-nesting-too-deeply) | 950 `+` terms compile, 1 000 do not: *expression nests too deeply*; grouping in parentheses avoids it | low |
| [F7](#f7--epfl-hemt-is-refused-for-vsisi) | 47 of 48 corpus files compile; `epfl_hemt.va` is refused for `V(si,si)` (LRM 4.4 says error; the expression is 0 and other tool chains accept it) | low — compatibility |
| [F8](#f8--the-zi_-filters-ignore-t0-and-warn-about-a-discontinuity-they-never-produce) | the `zi_*` family is the documented bilinear continuous approximation of Enhancement-6; `t0` is silently ignored and `tau=0` draws a warning about an abrupt output the implementation never produces | low — documented approximation, misleading edges |
| [F9](#f9--diagnostic-wording) | a `$strobe` arity error names `$display`; an array index out of range is a *bus bit-select*; `laplace_zp(x, {}, …)` is refused without saying `'{}` works; the `L027` codes printed in messages are not accepted by `-E`/`-W`/`-A`; a malformed number `1e V(p,n)` is reported as an instance of a module `e` | cosmetic |
| [F11](#f11--every-advertised---target-fails-on-the-macos-build) | `--target` lists four triples; three end in *cannot generate code for target … No available targets* (no LLVM backend), `aarch64-unknown-linux` reaches the link step and dies on `clang: error: unknown argument: '--no-add-needed'`; the error for an unlisted triple does not name the accepted ones | low-medium — advertised, unusable |
| [F10](#f10--integer-division-by-a-zero-valued-parameter-is-silently-0) | `7 / z` with a parameter `z = 0` given on the card evaluates to 0 with no message; `7 % z` is a run-time fatal citing LRM 4.2.4, and a zero literal is a compile error | low — three behaviours for one rule |

Ten observations that are design choices or simulator-side, and then the
holds, follow the findings.

---

## F1 — a system function in a parameter default or range crashes the compiler

```verilog
`include "disciplines.vams"
module m(p,n); inout p,n; electrical p,n;
parameter real t0 = $temperature;
analog I(p,n) <+ V(p,n);
endmodule
```

```
OpenVAF encountered a problem and has crashed!
A log file has been generated at ".../openvaf-crash-1788570142.log"
```

The log: *Panic occurred in file 'openvaf/mir_llvm/src/builder.rs' at line
143 — internal error: entered unreachable code: attempted to read undefined
value.* The LRM makes a parameter default a constant expression, so the right
answer is a diagnostic — which the compiler does give for `analysis()` in
the same place (*analysis function 'analysis' is not allowed in constants*)
and, with a warning, for `$simparam` (L015). The crash reproduces for every
position a parameter expression can occupy:

| expression | verdict |
|---|---|
| `parameter real a = $temperature;` | **crash** |
| `parameter real a = $vt;` | **crash** |
| `parameter real a = $abstime;` | **crash** |
| `parameter integer a = $port_connected(p);` | **crash** |
| `parameter real a = 2.0 * $temperature;` | **crash** |
| `parameter real a = 1.0 from [0:$temperature];` | **crash** |
| `parameter real a[0:1] = '{$temperature, 1.0};` | **crash** |
| `(* type="instance" *) parameter real a = $temperature;` | **crash** |
| `parameter integer a = $temperature;` | **crash** |
| `parameter real b = $temperature; aliasparam c = b;` | **crash** |
| `parameter integer a = analysis("dc");` | error, correctly |
| `parameter real a = $simparam("gmin", 1e-12);` | accepted, L015 warning |
| `parameter real a = $mfactor;` | accepted **silently**; reads 1 on an instance with `m=3` |
| `parameter real a = $random;` | accepted **silently**; every instance reads the same 8.8e7 |
| `parameter real a = 1.0 from [0:$mfactor];`, `… from [0:$random]` | accepted **silently** |

The last two are the same gap without the crash: a non-constant default is
accepted and evaluated to something that is neither an error nor the value
the author could have meant. Crash log saved beside this document's probe
decks (`hunt4/crash_temperature_default.log`).

**Resolved.** A parameter's default and range bodies are validated in the
constant context, where `analysis()` was already refused but these were not,
so they reached codegen of the setup functions with no value to read. The
validator now refuses the simulation-state functions (`$temperature`, `$vt`,
`$abstime`, `$realtime`, `$port_connected`), the hierarchical parameters
(`$mfactor`, `$hflip`, …, which are not builtins and needed their own arm)
and every random draw in a constant, each with the rule and a way out: *system
function '$temperature' is not allowed in constants — a parameter default or
range must be a constant expression (LRM 3.4); the simulator state this reads
… does not exist when defaults are resolved — keep the parameter constant and
compute the value from it in the analog block, or in `analog initial`*; a
draw additionally points at `(* std *)` with `.option osdimc`. Every row of
the table above now ends in that diagnostic, `$param_given` and `$simparam`
keep their behaviour, the same functions stay legal in the analog block, the
corpus compiles as before (48 of 49, EPFL-HEMT unchanged), and a UI test
(`test_data/ui/const_sysfun.va`) pins all ten forms.

## F2 — a model parameter's range or default that references an instance parameter is evaluated with that parameter's default

```verilog
(* type="instance" *) parameter real w = 1e-6 from (0:inf);
parameter real l = 1e-6 from (0:w];
```

The compiler accepts it and places the range check where a model parameter's
check goes, in the model setup, where no instance's `w` is known yet:

| deck | expected | observed |
|---|---|---|
| `.model mm m(l=1e-6)`, `n2 … w=0.5e-6` | refused: `l > w` | **runs**, `l/w = 2.0`, i = 0.5 mA |
| `.model mm m(l=3e-6)`, same instance | refused | refused: *Parameter l of 'mm' is out of bounds (value 3e-06)* — against the **default** `w = 1e-6` |
| control: `(* type="instance" *) parameter real w … from (0:2e-6]`, `n1 … w=3e-6` | refused | refused, correctly, per instance |

The default has the same shape: `parameter real l = 2*w;` reads 2e-6 with an
instance at `w=3e-6`. An instance parameter's own range is checked per
instance; a model parameter that depends on one is checked once, against a
value no instance need have. Either a per-instance evaluation of such
parameters or a diagnostic (*a model parameter's range/default depends on an
instance parameter*) would close it.

## F3 — an internal node nothing can contribute to compiles silently, and is singular at run time

| module body | compile | run |
|---|---|---|
| `electrical x; … vx = V(x);` (probe only) | silent | *singular matrix: check node n1#x*, no op |
| `electrical x, y; … v = V(x,y);` | silent | singular |
| `electrical x; if (0) I(p,x) <+ V(p,x);` | silent | singular |
| `electrical x; genvar g; for (g = 0; g < 0; …) I(p,x) <+ …` | silent | singular |
| `electrical x; parameter integer on = 0; if (on) I(p,x) <+ …` | silent | singular-matrix warning, op recovers |

The compiler knows every contribution a module can make and creates the
node anyway; the simulator inherits an empty matrix row. The first four rows
are decidable at compile time (no contribution reaches the node on any path);
the last is decidable at setup (the collapse machinery already evaluates
parameter conditions). A branch-level cousin is handled: a flow probe on a
contribution-less branch gets L017 and the LRM short.

## F4 — a string parameter's default outside its own range is not diagnosed, and runs

```verilog
parameter string mode = "cubic" from {"lin", "quad"};
```

Compiles with no diagnostic; the same for a real (`parameter real r = 5.0
from [0:1]`) draws *warning[L027]: the default value of parameter 'r'
violates its own range*. At run time both run with the invalid default —
the range is enforced only on a value given on the card (`mode="cubic"` on
the card is refused: *Parameter mode of 'mm' is out of bounds!*). So a
model author's typo in a string default is invisible everywhere, and a real
default's is visible once, at compile time, and then simulated.

## F5 — integer power saturates where every other integer operator wraps

| expression | result | 32-bit wrap |
|---|---:|---:|
| `10**10` | 2147483647 | 1410065408 |
| `2**31` | 2147483647 | −2147483648 |
| `3**20` | 2147483647 | −808182895 |
| `100000*100000` | 1410065408 | 1410065408 |
| `2147483647 + 10` | −2147483639 | −2147483639 |
| `7**11` (no overflow) | 1977326743 | 1977326743 |

Constant folding and run-time evaluation agree with each other in both
behaviours, so it is a definition, not a folding bug — two definitions in
one language.

## F6 — a flat sum of a thousand terms is rejected as nesting too deeply

`I(p,n) <+ 1e-6*V(p,n) + 2e-6*V(p,n) + … + N e-6*V(p,n)`: N = 950 compiles,
N = 1 000 fails with *expression nests too deeply*. The same 1 500 terms
grouped as fifteen parenthesised blocks of a hundred compile. A left-deep
chain is what a generated table or polynomial produces; the recursion
depth of the parser is the limit, not the expression. The same wall stands
at 1 000 nested parentheses (500 compile); 1 000 nested `if` statements
compile, so it is the expression parser alone.

## F7 — EPFL-HEMT is refused for `V(si,si)`

The corpus sweep (48 files, 55 s in all, the slowest 4.3 s) compiles every
model but one:

```
error: both arguments of the potential access name the same net 'si'
   --> epfl_hemt.va:412:11
412 |     Vs =  V(si,si);
    = help: LRM 4.4 (Table 4-16): the two nets of a branch access must be distinct
```

The LRM reference is right and the expression is identically zero; the model
is distributed and compiled by other tool chains, so this is the compiler
being stricter than the field on a harmless line. A warning that reads the
access as 0 would keep the corpus compiling. Three corpus files draw
warnings that are themselves correct: `bsim6.0` (L015), `diode_cmc` and
`fbh_hbt-2_1` (L027 — real defaults outside their ranges, exactly F4's real
half), `fbh_hbt-2_3` (L022, a branch contributed as both potential and
flow).

## F8 — the `zi_*` filters ignore `t0` and warn about a discontinuity they never produce

`V(o) <+ zi_nd(V(i), {1.0}, {1.0, -0.5}, 1u)` on a unit step at 0.5 µs. The
discrete definition holds y[1] = 1 from 1 µs, y[2] = 1.5 from 2 µs:

| t | 0.9 µs | 1.0 | 1.25 | 1.5 | 1.75 | 2.0 | 2.05 |
|---|---:|---:|---:|---:|---:|---:|---:|
| observed | 0.978 | 1.044 | 1.191 | 1.315 | 1.420 | 1.509 | 1.525 |
| with `tau = 0` | identical | | | | | | |
| with `tau = 0, t0 = 0.5u` | identical | | | | | | |

The output rises before the first sample instant, never holds, and is
independent of the transient step (1 ns to 250 ns give 1.31522 at 1.5 µs).
`examples/zi_examples/README.md` says why: Enhancement-6 maps the z-domain
function to a continuous one by the bilinear transform, "exact at DC and
near-DC", because the simulator has no sample-and-hold support. Fine as a
documented approximation; two edges are not: `t0` is accepted and ignored,
and `tau = 0` draws *the output is abruptly discontinuous; LRM 4.5.12 says
such a filter shall not be contributed directly to a branch* — for an
implementation whose output is a smooth curve whatever `tau` is.

## F9 — diagnostic wording

* `$strobe("%d %d", 1)` → *$display system task is missing an argument*.
* `parameter real c[0:3] …; c[4]` → *bus bit-select index out of range*.
* `laplace_zp(x, {}, {-1e6, 0})` → *empty concatenation `{}` is not
  allowed*; `'{}` is accepted and is the spelling wanted, unmentioned.
* Messages print codes (`warning[L027]`), but `-E L027` is *invalid value*;
  the flags want the names (`param_default_out_of_range`), which only
  `--lints` and the help line reveal.
* `I(p,n) <+ 1e V(p,n)` (a malformed exponent) → *instance 'V' refers to
  module 'e', which is not defined anywhere in this compilation unit*.
* `$strobe("bad \q escape")` — an unknown escape — is accepted in silence.
* A genvar assigned inside its own loop body is refused as *unexpected token
  integer; expected ';', '@', 'begin', …* — a parse error where the rule
  (a genvar is not assignable there) is the thing to say.
* `(* openvaf_allow="no_such_lint" *)` is accepted without a word; a typo in
  the attribute silences nothing and reports nothing.
* Two functions that call each other are each reported as *cannot call
  itself*.
* A module compiled without `` `include "disciplines.vams" `` gets
  *'electrical' was not found in the current scope*, twice, and no hint at
  the include every model needs.

## F10 — integer division by a zero-valued parameter is silently 0

```verilog
parameter integer z = 1;
analog begin q = 7 / z; ... end        // .model mm m(z=0)
```

Runs; `q` reads 0, nothing printed. The sibling `7 % z` on the same card
stops the run with *OSDI(fatal) mm: %: the second operand (the modulus
divisor) is zero, which LRM 4.2.4 makes an error*, and a zero **literal**
(`parameter integer k = 1/0;`) is a compile error (*integer division by
zero*). One rule, three behaviours; the silent one is the one a card typo
reaches. (`7.0 / rz` with `rz = 0.0` gives `inf`, as a real should.)

## F11 — every advertised `--target` fails on the macOS build

`--help` lists `x86_64-unknown-linux`, `x86_64-pc-windows`,
`x86_64-apple-darwin`, `aarch64-unknown-linux`. On the shipped
`bin/macos/apple-silicon/openvaf-r`:

| `--target` | outcome |
|---|---|
| `x86_64-unknown-linux` | *cannot generate code for target 'x86_64-unknown-linux-gnu': No available targets* |
| `x86_64-pc-windows` | same, for `x86_64-pc-windows-msvc` |
| `x86_64-apple-darwin` | same, for `x86_64-apple-macosx10.15.0` |
| `aarch64-unknown-linux` | code is generated, then *clang: error: unknown argument: '--no-add-needed'* (a GNU ld flag handed to Apple's clang) |
| `x86_64-unknown-linux-gnu` (the full triple) | *invalid value* — and the message does not list the four accepted spellings; only `--help` does |

The first three are a build configuration (the bundled LLVM has only the
host backend); the fourth is a linker-driver choice made by target rather
than by host. Either the option should be hidden on builds that cannot
honour it or the messages should say so up front.

---

## Observations — design choices and simulator-side notes

* **`%d` with a real argument is a hard error** (*expected integer value
  but found real parameter ref*). Verilog converts; this refuses. Strict but
  self-consistent, and `%s` with a real and `%d` with a string are refused the
  same way.
* **Constant domain errors are hard errors**: `pow(-8.0, 1.0/3.0)`,
  `ln(0.0)`, `-1**0.5` (Verilog's unary minus binds tighter than `**`, so
  this is `(-1)**0.5`) and `1e400` (*too large to represent*) stop the
  compile with a clear message rather than folding to NaN or inf. Documented
  in the message as "checked only when written out as a constant".
* **Analog operators in loops** are refused except in genvar loops, and in
  conditions except constant ones — the LRM's rule, and the messages say so.
* **A parameter named `m`, `temp` or `dtemp`** compiles without a note
  (module names get L018) and takes the instance-line value ngspice would
  otherwise read as its multiplier or temperature; the built-in meaning is
  silently gone for that model.
* **`V(i) <+ 1.0` onto an `input` port** is accepted and drives the port.
* **A variable read before its first assignment** is not warned; the
  converged answer is the same as with the assignment first, because the
  value persists across evaluations.
* **`$bound_step` in `analog initial`** and **`$discontinuity` in an analog
  function** are accepted; an event inside an `if` is accepted.
* **`wire` nets** are refused with *currently not supported*, stated plainly.
* **Run-time out-of-range array indices** are memory-safe and silent:
  `a[5] = 7.0` on `real a[0:3]` changes nothing (no neighbour is touched,
  `b[0]` beside it stays 10), `a[7]` and `a[-1]` read element 0, `a[1000000]`
  does not crash; nothing is reported. A constant index out of range is a
  compile error.
* **`ddx` with respect to a port current** (`ddx(cur, I(<p>))`) is refused as
  *invalid unknown*, an unknown the LRM's `ddx` admits beside `V(n)`; a
  branch potential `V(p,n)` is accepted with the L011 non-standard warning and
  computed correctly (1.2e-3), a named-branch flow `I(br)` is accepted and
  reads 0.
* **`$random` without a seed is the same number in every instance** of a
  model (1.366e9 in three instances): Enhancement-10 makes every draw a pure
  hash of (seed, call site), so unseeded `$random` is a per-model constant,
  and mismatch needs a per-instance seed parameter (`$rdist_normal(seed, …)`
  with `seed` instance-typed gives equal draws for equal seeds and different
  ones otherwise, as it should). The L019 lint covers the loop case; nothing
  says this at the module level.
* **File I/O never crashes, and `$fclose` does not close**: `$fopen` on a
  directory or a missing path returns 0 and writes to 0 are dropped
  (Verilog's multichannel reading of descriptor 0); `$fwrite` to an unopened
  or wild handle survives; two `$fopen` of one path return the same handle;
  a `$fwrite` after `$fclose` still lands in the file (*late* is in the
  file). Silent where the LRM would have an error, harmless otherwise.
* **`%m` inside a structurally instantiated sub-module** prints the top
  instance (`n1`) for both `s1` and `s2`; the sub-instance path is not part
  of the name, though the inner nodes carry it (`s1__x`).
* **A crash leaves partial objects in the batch cache** (`<hash>.o`,
  `.o1`, `.o3` under `~/Library/Caches/com.semimod.openvaf/`, no `.osdi`);
  the next `-b` run crashes again rather than reusing them, so nothing is
  poisoned, only left behind.
* **An integer function input refuses a real argument** (`f(2.7)` with
  `input i; integer i;` is a type error), where Verilog would round; the
  same strictness as `%d` with a real.
* **`"abc"` as an integer parameter default** is accepted and reads 6382179
  (0x616263), Verilog's packed-ASCII reading of a string literal.
* **ngspice side:** an operating-point variable declared `v_E3` is
  reachable as `@n1[v_e3]` only (the request is lower-cased on one side of
  the lookup and not the other); a string-typed `type` parameter reads as
  polarity +1 to Enhancement-543's recognizer; `V<+` and `I<+` on one branch
  in one evaluation resolve to the **last** kind (V-then-I gives 1 mA,
  I-then-V gives 0.5 V, with L022 either way), which is the LRM's switch
  rule.

## What was measured and holds

* **Analog operators against closed forms** (op, tran, ac): an ideal switch
  branch (`V<+0` / `I<+0` by condition); `V <+ L*ddt(I)` in an RL step to
  0.5 %; `idt` with an initial condition (1e-3 V·s, exactly); `absdelay`
  (2.000 ns, phase −2πfT in AC); `transition` (1.6 / 3.2 ns edges, 1 ns
  delay); `laplace_nd` lowpass (0.632 at τ, −1.445 dB at 100 kHz, −36 dB at
  10 MHz); `slew` (0.8 / 1.6 ns); `limexp` = `exp`; `ddt(ddt(x))` = −ω²;
  `idtmod` sawtooth (0.4, 0.4, 0.25); `ddt(c0 V + c1 V²)` gives C = c0 +
  2c1V0 in AC; `ac_stim` injects 2 mA exactly; `$limit` with `pnjlim`,
  `fetlim` and a user function converges in 7 where 12 without.
* **Automatic differentiation** (`ddx`) for abs, max, min, hypot, atan2,
  pow(v+1, v), tanh, asinh, floor, limexp, sqrt, `**`, exp·sin, a ternary,
  ln and log10, through an analog function's `output` and `inout`
  arguments, and through `$limit`: every value is the analytic derivative to
  seven digits.
* **Integer and real semantics**: `-7/2 = -3`, `-7%2 = -1`, `7%-2 = 1`,
  2.5 → 3 and −2.5 → −3 on conversion, `(-2)**3 = -8`, `2**-1 = 0`
  (the LRM's integer rule), `1/2*2.0 = 0`, `3**2**2 = 81`, `repeat(2.7)`
  runs three times, 32-bit wrap on `+`/`*`; constant folding and run-time
  evaluation agree on fifteen expressions to the last digit.
* **Formats**: `%5.2f %e %10.3e %s %% %m %b %h %o %c %*d %.3g %-8.2f %+d`,
  string escapes, `%m` hierarchical (`n.x1.x2.n2`), arity and type errors
  diagnosed, `$sformat`, `$sscanf`, string `==`/`!=`/`<`, concatenation,
  ternaries on strings, `$fopen`/`$fwrite`/`$fdisplay`/`$fstrobe`/`$fclose`
  writing real files, `$fopen` with `"r"` and `"a"` modes, `$fgets` +
  `$sscanf` and `$fscanf` reading a number back (3.25) from a file; `$fgets`
  returns 4, 4, 0 across two lines and EOF, `$feof` 1, `$rewind` then 4 again.
* **Functions**: recursion refused with its own message; a function cannot
  reach a module variable (*not found in the current scope*) but can read a
  parameter; forward calls, duplicate names, an argument named like a port,
  a missing return assignment (reads 0), array arguments, too many
  arguments, an `output` bound to a literal — each handled; `output`/`inout`
  arguments; integer return; system tasks inside functions; `ddt` and events
  inside functions refused.
* **Parameters**: forward reference refused; integer with a real default
  rounds; `exclude` values and lists; array defaults and ranges; instance
  default from a model parameter; string default from a string parameter;
  `aliasparam` settable on the card (refused in the body, per LRM);
  `$param_given` per card and per line; `$port_connected`.
* **Preprocessor and CLI**: macros with arguments, nested, multi-line, string
  arguments, `ifdef`/`elsif`/`else`, `undef`, redefinition (L004),
  `__FILE__`/`__LINE__`, missing includes, wrong arity, `-D` with values,
  `-I`, `--dry-run`, `-b` batch mode keyed on the source, on an included
  file and on `-D` values alike (content-hashed cache path), spaces in the
  output path, two modules per file, zero modules refused, nonexistent and
  directory inputs, output equal to input refused, the four `--dump-*`
  options on BSIM4.
* **Structure**: two contributions add; `I(p,n)` and `I(n,p)` subtract; ten
  contributions in a loop; port probe `I(<p>)`; a current unknown for a
  voltage-contributed branch; parameter-conditional collapse at 3, 50 and
  400 internal nodes; `ground`; port-current feedback (`V <+ 10*I(<p>)` is
  10 Ω); flow-probe feedback of the same branch; probe-only branch short with
  L017; multiple analog blocks; digital blocks refused.
* **Disciplines**: thermal port with `Pwr`; custom natures and disciplines
  (with `abstol`, `ddt_nature`, `idt_nature`); signal-flow (potential-only)
  discipline; mismatched access function refused.
* **Events and noise**: `cross`, `above`, `timer`, `initial_step` with
  analysis arguments, `final_step` fire at the right instants and counts;
  `analysis()` values under op/ac/tran/dc; `$bound_step` (108 → 1 005
  points); thermal + flicker noise on a divider to the closed form, zero
  parameters finite, noise sources inert in dc and tran.
* **Lexer and scale**: 300-character identifiers, unicode in comments and
  strings, CRLF, a BOM, tabs, no final newline; 2 000 parameters in 2.5 s,
  200 ports in 2.6 s, 400 internal nodes in 5.9 s with the right current.
* **Flow probes under dynamic operators and structural hierarchy**:
  `V <+ L*ddt(I(p,n))` is a 1 mH inductor to seven digits in AC,
  `V <+ (1/C)*idt(I(p,n))` a 1 nF capacitor; a module instantiating another
  (`sub #(.r(rt)) s1(p, mid); sub #(.r(2*rt)) s2(mid, n);`) compiles,
  flattens with per-instance overrides (3 kΩ from 500 + 1 000 twice), names
  the inner nodes `n1#s1__x`, and leaves the sub-module usable as a model of
  its own; a module that only probes (a sensor) reads the node without
  disturbing it.
* **Constant-argument validation** names its rule for every operator tried:
  an improper `laplace_nd`, an identically-zero denominator, a negative
  `absdelay`, a negative `transition` rise time, zero `slew` rates, a
  non-positive `idtmod` modulus, a non-positive `zi_nd` period, a negative
  `white_noise` power, a non-positive `$bound_step`; a zero leading
  denominator coefficient (an integrator) and a negative flicker exponent
  are accepted, as they should be. 300 operating-point variables compile in
  0.2 s and all reach `show`.
* **Genvar and macros**: nested genvar loops carrying `ddt`; a genvar read
  after its loop, a real step and a body assignment refused with the rule
  named (one of them poorly, F9); `__VAMS_ENABLE__`,
  `__VAMS_COMPACT_MODELING__` and `__OPENVAF__` predefined; mutual recursion
  between two functions refused; `(* openvaf_allow="param_default_out_of_range" *)`
  silences L027 as its help text promises.
* **More operators and functions**: a string-returning analog function and
  a string argument; `$rdist_uniform` over 200 seeded draws spans
  0.011–0.991; `@(cross)` with tolerance arguments says *the time tolerance
  is accepted but not honored* and fires within one step; `absdelay` with a
  voltage-dependent delay follows it (1 ns and 3 ns measured); array
  parameters overridden per element on the instance line (`c[0]=4`) and on
  the card (`d[1]=2`) read back exactly.
* **Inside analog functions**: `absdelay`, `transition`, `laplace_nd`,
  `idt`, `last_crossing`, events and `$limit` are refused with the rule
  named; `$abstime`, `$temperature`, `$simparam` and `$bound_step` are
  allowed; `white_noise` is allowed too — leniently, against the LRM's
  operator rule — and contributes exactly as a direct source would (9.99e-8
  V/√Hz either way).
* **Distributions**: `$rdist_exponential`, `_poisson`, `_chi_square`, `_t`,
  `_erlang`, `$dist_uniform`, `_normal`, `_exponential` all compile, and
  their sample means over 400 seeded draws sit within sampling error of the
  parameters (1.91 for 2, 3.01 for 3, 3.76 for 4, 0.003 for 0, 1.46 for
  1.5, 4.84 for 5, 99.6 for 100, 3.99 for 4).
* **Small things at the edge**: `@(initial_step("trann"))` draws L021 (*no
  analysis can ever match*); `$limit` with a one-argument user function is
  refused for arity; an integer parameter given 0.5, 1.6, 2.4 on the card
  rounds to 1, 2, 2 and 2.5 rounds to 3 and is refused by its `[0:2]` range;
  Verilog escaped identifiers (`\a+b`) and `$` inside names work.
* **`$simparam` names**: `tnom` follows `.option tnom`, `iteration` counts,
  `sourceScaleFactor` reads 1, `gdev` 1e-12, and `timeStep` falls back to
  its default outside a transient.
* **Lints**: every lint in `--lints` can be provoked; `-E warnings`, `-A
  all`, unknown names refused with the list.
* **Constant contexts refuse what they should**: `$temperature` as a case
  label, an array bound or a genvar bound; `$param_given` on a variable or
  a net; `$port_connected` on an internal node or a parameter; `$strobe`,
  `$limit`, `ddt` and `V()` in a parameter default — each with a message
  that names the rule. `1.0/0.0` and `1e308*10` fold to `inf`, `'h80000000`
  and `-2147483648` to `INT_MIN`, shifts outside 0..31 warn, `0.0**0.0 = 1`,
  `atan2(0,0) = 0`, `5.0 % 0.0 = nan`.
* **Collapse edge cases**: a cycle `V(a,b)=V(b,c)=V(c,a)=0` leaves one node
  and the right current; `V(p,n) <+ 0` on the port branch with an `I(p,n)`
  probe reads the short's current; a voltage-dependent collapse of an
  internal node switches between two 1 kΩ in series and a short at the
  two biases; `V(x) <+ 0` collapses to ground.
* **Malformed input**: twenty-six deliberately broken files (empty and
  valueless attributes, `define`/`include` without arguments, a lone
  backtick, a bare `$`, unterminated strings and comments, duplicate and
  undeclared ports, empty declarations, a second `endmodule`, EOF inside an
  expression, an empty file) all end in a diagnostic, none in a crash; a
  200 kB line and 100 000 blank lines lex in 0.1 s; 5 000 sequential
  statements compile in 0.4 s to the right sum; `$strobe` with 25
  arguments; `exclude 0.5 exclude [3:4)` refuses 0.5, 3 and 3.9 and admits
  4 on the card.
* **Corpus**: 47 of 48 `VA-Models` files compile, 55 s in total.

## Coverage, honestly

* F1's cause was read from the panic location, not the source; the crash
  table is complete for the system functions tried, not for all of them.
* F2 was measured on one module shape; the model-setup placement of the
  check is inferred from where the refusal lands, not from the emitted code.
* The `zi_*` finding is against the documented approximation, not against a
  hidden defect; its severity is about the two silent edges.
* Not exercised: `generate` blocks, `$simparam$str` beyond one lint,
  `$analog_node_alias`, mixed-signal constructs beyond confirming they are
  refused, the Windows and Linux prebuilt compilers, and OSDI descriptor
  contents other than through ngspice's `show`/`showmod`.
* Probe modules and decks are under the session scratchpad `hunt4/`
  (harness `h.py`, one `.va`/`.cir` pair per probe, `corpus/` for the
  sweep's objects, `crash_temperature_default.log`).
