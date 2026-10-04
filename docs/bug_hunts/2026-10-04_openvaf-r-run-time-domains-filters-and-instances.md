# openvaf-r hunt — run-time domains, filters, instances, functions and timers

**Date:** 2026-10-04, 07:16–08:16, at head `614ea22a` (E-788). **Binaries:** the repo's
`OpenVAF-master-20260610/target/opt/openvaf-r` (built 2026-10-03 from the E-787 tree; E-788
changed only ngspice) and `ngspice-46/build/src/ngspice` (built 2026-10-03, E-788).
**Method:** throw-away harnesses in the session scratchpad (`hunt/*.py`, driven by `probe.py`,
which compiles one model at a time under a 12 GB RSS cap and a timeout): several hundred probe
compiles, 760 mutation-fuzz compiles, a 94-file lint census and about 250 ngspice runs. Each probe compares against an analytic
value, the LRM, or the compiler's own behaviour on an equivalent input (a literal against
the same value from a model card). Ten openvaf-r pages came before this one, so the hunt
went where they had not: derivatives at kinks, the preprocessor and lexer, `$strobe`
formats, analog-function legality, disciplines, `analysis()`, timers and step bounds, the
`laplace_*` filters, noise functions, `ddx`, strings and `case`, `$simparam`, module
instantiation inside Verilog-A, events, `idtmod`, `absdelay`, instance parameters, `m=` and
`dtemp`, operating-point variables, compile scaling, and a lint census over the corpus.
Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | an analog function whose return value is not assigned on some path returns 0 without a word | medium |
| [F2](#f2) | a `timer` event that lands on one of ngspice's own breakpoints (the stop time, a PWL corner) is approached in halving steps down to 0.2–1.2 ps, and the step-count guard blames a `$bound_step` the model never calls | medium |
| [F3](#f3) | zero coefficients are not normalised: a `laplace_nd`/`laplace_zd` denominator whose highest-order coefficient is 0 stops every analysis with `$fatal`, the compile-time order check counts list lengths, and a pole-zero pair at the origin (any form) makes the operating point singular — all well-defined filters | medium |
| [F4](#f4) | an instance parameter override outside the child's declared range runs: a literal draws only a warning naming the mangled `x1__r`, a value from the parent's card is not checked at all | high |
| [F5](#f5) | the domain checks made on literal arguments have no run-time counterpart for nine arguments: a card value is clamped, ignored or projected in silence | medium |
| [F6](#f6) | under `sens`, `@(initial_step)` fires seven times and `@(final_step)` once | low (ngspice side) |
| [F7](#f7) | lint L037 ("`$mfactor` scales this flow contribution a second time") fires 20 times on the CMC standard `r3_cmc`, where `$mfactor` enters only the mismatch statistics | low |
| [F8](#f8) | a complex pole or zero given without its conjugate is accepted, and the imaginary part of the resulting coefficient is dropped in silence: a different, real filter runs | medium |
| [D](#d) | sixteen smaller slips | low |

<a id="f1"></a>
## F1 — an analog function whose return value is not assigned on some path returns 0 without a word

```verilog
analog function real f; input x; real x; real y; begin y = x; end endfunction      // never assigns f
analog function real g; input x; real x; begin if (x > 2) g = 7; end endfunction   // assigns g on one path
analog function integer h; input x; real x; begin end endfunction                 // empty body
```

All three compile with no diagnostic; `f(3.0)`, `g(1.0)` and `h(1.0)` return 0 at run time.
The missing assignment is almost always a typo (the result assigned to a misspelled local,
a forgotten `else`), and C compilers warn on the same shape. The compiler already refuses a
write to an `input` argument and a recursive call, so the function body is analysed; a
"return value not assigned on every path" warning is the missing piece.

An `output` argument assigned on only some paths has the same hole, with a side effect: in

```verilog
analog function real f; input x; output y; real x, y; begin if (x > 5) y = 1; f = x; end endfunction
...  t = 7; u = f(1.0, t);
```

`t` is 0 after the call — the unassigned output copies its zero-initialised value back over
the caller's 7. The same warning, extended to `output` arguments, would cover it.

<a id="f2"></a>
## F2 — a timer event on one of ngspice's breakpoints is approached in halving steps, and the warning blames `$bound_step`

```verilog
@(timer(0, 1e-7)) n = n + 1;
```

with `tran 10n 2u`: 221 time points instead of 208, a minimum step of 1.22 ps, and

```
Warning: n1: $bound_step(1.2207e-12) would need 1.64e+06 steps to cross this analysis; using 2e-12 (1e+06 steps) instead. A device cannot demand an unbounded step count.
```

The model calls no `$bound_step`. The tiny steps are all at the very end: 9.76, 4.89, 2.44,
1.22 and 1.22 ps up to 2 µs. It happens for every period that divides the stop time,
exact or not in floating point (1e-7, 2e-7, 2.5e-7, 4e-7, 5e-7, 1e-6 all show it), and for
none that does not (1.7e-7, 3e-7: 208 or 209 points, minimum step 0.1 ns). So the timer's
step bound toward an event that coincides with a breakpoint chases it in halving steps,
and E-504's step-count guard (`osditrunc.c`) then reports the bound as if the model had asked for it. A
timer whose period divides the run length is the normal case (a clock, a sampler).

It is not the stop time as such but any coincidence with a breakpoint ngspice keeps itself
(`tran 10n 2u`, smallest step and point count):

| timer | source | points | smallest step |
|---|---|---|---|
| `timer(1u)`, one shot | sine (no breakpoint at 1 µs) | 209 | 0.1 ns |
| `timer(2u)`, one shot at the stop time | sine | 221 | 1.05 ps |
| `timer(1u)`, one shot | `pwl(0 0 1u 1 2u 0)`, a corner at 1 µs | 236 | 0.2 ps |
| `timer(0, 0.5u)` | the same `pwl` | 249 | 0.2 ps |

Each run with a coincidence also prints the `$bound_step(…) would need … steps` warning.

It is specific to `timer` against a breakpoint ngspice owns. Three instances whose
`timer(0, 0.3u)` events coincide with each other run clean (209 points, 0.1 ns), as do a
`cross` event landing exactly on a PWL corner or at the stop time, and `absdelay` or
`transition` breakpoints that coincide with source corners, and an explicit `$bound_step(0.5u)`
whose steps land on the PWL corners (211 points, 0.1 ns). So the fault is in how a timer
event is landed, not in step bounding as such.

<a id="f3"></a>
## F3 — a zero highest-order denominator coefficient stops every analysis with `$fatal`, and a common factor of s is not cancelled

```verilog
V(b) <+ laplace_nd(V(a), {1.0}, {1.0, 1.5915e-4, 0.0});   // = 1/(1 + s/w0) after trimming
```

compiles without a word and then, at the operating point of any analysis:

```
OSDI(fatal) n1: laplace_nd: the denominator's highest-order coefficient must be a finite non-zero number, but is 0
Error: a Verilog-A device raised $fatal during the operating point; aborting.
```

The same with `laplace_zd`, with the coefficient from a card parameter
(`{1.0, 1/w0, c2}` and `c2=0`, the natural way to switch a second-order term off), and with
a parameter-array element set on the card (`den[1]=0` turns `{1, 1/w0}` into the constant
1). The trimmed denominator is a proper, well-defined filter in each case. A trailing zero
in the *numerator* runs when the lists have equal length (`{1.0, 0.0}` over `{1.0, 1/w0}`
gives 0.5−0.5j at 1 kHz, as it should), but the compile-time order check counts list
*lengths*, not orders: `{1.0, 0.0, 0.0}` over `{1.0, 1/w0}` — the same filter — is refused
with "the numerator is order 2 against a denominator of order 1; such a filter has unbounded
gain", and so is `{1.0, n1, n2}` whatever the card gives `n1` and `n2`. Both checks, the
compile-time order test and the run-time leading-coefficient test, would be right if trailing
zero coefficients (literal or at run time) were trimmed first, failing only when every
coefficient is 0.

The other end of the lists has the same gap. A common factor of s — a zero constant term in
both numerator and denominator — is not cancelled:

```verilog
V(b) <+ laplace_nd(V(a), {0.0, 1.0}, {0.0, 1.0, 1e-4});   // = 1/(1 + 1e-4 s), DC gain 1
```

compiles without a word, and the operating point is singular ("singular matrix: check node
n1#implicit_equation_0"); dynamic gmin, true gmin and source stepping all fail. The
pole-zero forms fail the same way for a pair at the origin — `laplace_zp(V(a), {0,0},
{0,0, -5000,0})` and `laplace_zd(V(a), {0,0}, {0, 1, 2e-4})` — while a cancelling pair
elsewhere (`laplace_zp` with a zero and a pole both at −1000) runs and is exact. So a pole at
the origin is realised as an integrator state whether or not a zero cancels it, and that
state has no DC solution.

<a id="f4"></a>
## F4 — an instance parameter override outside the child's declared range runs

```verilog
module ch(p, n); ... parameter real r = 1k from (0:inf); analog I(p,n) <+ V(p,n)/r; endmodule
module pq(a); ... ch #(.r(-5)) x1(a, gnd); endmodule
```

compiles with only

```
warning[L027]: the default value of parameter 'x1__r' violates its own range
```

— naming the flattened internal `x1__r` and calling the override a "default" — and the
circuit runs with r = −5 (a negative resistor: `i(v1)` = +0.2 A at 1 V). With the value
coming from the parent's card (`ch #(.r(rp))`, `.model mm pq rp=-5`) there is no warning at
all, and still a negative resistor; `rp=0` divides by zero and ngspice reports
"Transient op failed, timestep too small", which points nowhere near the cause. The same
values on the child's own card (`.model mc ch r=-5`) are refused at setup as out of bounds.
So a child's range guards its card but not its instantiation. The same mangled name and
"default" wording appear for L030 on `ch #(.k(2.6))` (an integer parameter).

It holds for every kind of range. With the child declaring `r` `from (0:inf) exclude 500` and
`parameter string mode = "a" from {"a", "b"}`, the override `.r(500)` runs with r = 500 and
`.mode("zzz")` runs with mode = zzz — a literal draws the same L027 (`'x1__r'`,
`'x1__mode'`), a value from the parent's card draws nothing.

<a id="f5"></a>
## F5 — literal arguments are checked, the same values from a card are not

The compiler checks the domain of these arguments when they are literals; when the value
comes from a model-card parameter, the run goes on with a substitute:

| argument | literal | from the card |
|---|---|---|
| `absdelay(x, td)`, td < 0 | error: "the delay must not be negative" | treated as no delay (`td=-0.3u`: the output follows the input) |
| `absdelay(x, td, maxdelay)`, td > maxdelay | warning citing LRM 4.5.7 | clamped to maxdelay without a word (`td=1u`, max 0.5u: delayed 0.5 µs) |
| `$bound_step(b)`, b ≤ 0 | error: "must be greater than zero" | ignored |
| `timer(t0)`, t0 < 0 | error: "the start time must not be negative" | fires at t = 0 |
| `timer(t0, period)`, period ≤ 0 | **accepted** (fires once) | fires once |
| `idtmod(x, ic, modulus)`, modulus ≤ 0 | error: "the modulus must be greater than zero" | no wrapping: the plain integral (1.25 at 1.25 µs for modulus 0 or −1) |
| `idt(x, ic, assert, abstol)`, abstol < 0 | error: "must be greater than zero" | accepted |
| `transition(x, td, tr)`, td < 0 or tr < 0 | error: "must not be negative" | projected (no delay, a 1 ns-class edge); also the 2026-09-21 page's F6 |
| `slew(x, rp, rn)`, rn > 0 | error: "the maximum negative rate must be less than zero" | the magnitude is used (`rn=1e6` falls at 1 V/µs); also the 2026-09-21 page's F6 |

Three arguments do have the run-time check: a card-supplied `cross` or `last_crossing`
direction of 2 and a `zi_nd` sampling period of 0 or −1 ns each raise a clear `OSDI(fatal)`
naming the argument. The rows above should follow them (a fatal, or for `absdelay`'s maxdelay the LRM's
substitution with a run-time warning). The `timer` period row is also a compile-time gap:
`timer(0, 0)` and `timer(0, -1u)` are accepted as literals, while a negative start is
refused.

<a id="f6"></a>
## F6 — `sens` fires `initial_step` seven times and `final_step` once

```verilog
@(initial_step) $strobe("IS");  @(final_step) $strobe("FS");
```

| analysis | `initial_step` | `final_step` |
|---|---|---|
| op, dc sweep, ac, tran, noise, tf | 1 | 1 |
| `sens v(a)` | 7 | 1 |

DC sensitivity re-solves the operating point once per perturbed parameter, and each solve
starts a fresh analysis on the device side. A model that opens a file in `initial_step` and
closes it in `final_step`, or resets a counter or a seed there, sees the pair unbalanced.
The plumbing is ngspice's (the perturbation loop), not the compiler's.

<a id="f7"></a>
## F7 — L037 fires 20 times on the CMC standard `r3_cmc`

```
warning[L037]: `$mfactor` scales this flow contribution a second time
723 |         I(b_rb)    <+  Irb;
```

`r3_cmc` reads `$mfactor` once (`mMod = $mfactor`, line 309) and uses it in the mismatch
statistics — the per-device sigma scales as 1/sqrt(m), lines 388–401, the CMC way of saying
that m parallel devices average their mismatch — and in a switch condition, which L037
exempts. None of its contributions is proportional to m. The lint tracks any data
dependence on `$mfactor`, so it cannot tell the LRM's `badres` (`I <+ V/r*$mfactor`) from a
model that is right; a production model compiles with 20 warnings. Restricting L037 to a
contribution whose value is multiplied or divided by `$mfactor` (or a value proportional to
it) would keep `badres` and drop these.

<a id="f8"></a>
## F8 — an unpaired complex root is accepted and silently turned into a different real filter

```verilog
V(b) <+ laplace_np(V(a), {1.0}, {-1000.0, 500.0});       // one pole at -1000 + j500, no conjugate
V(b) <+ laplace_zd(V(a), {-1000.0, 500.0}, {1.0, 1e-3}); // one zero at -1000 + j500, no conjugate
```

Both compile without a word (and the same with the imaginary part from a card parameter),
and both run. At 1 kHz the first gives 0.0381−0.1914j: not the single complex pole
(−0.0549−0.1824j), not the conjugate pair (−0.0295−0.0097j), but exactly 1/(1 + 8e-4·s) — the
real part of the complex coefficient −1/p = 8e-4 + 4e-4j, i.e. a real pole at −1250. The zero
case gives 0.8049−0.0310j, again exactly the real part of its coefficient. A filter with real
coefficients needs its complex roots in conjugate pairs; an unpaired one is a mistake in the
model (a missing pair, an odd-length list), and the result should be a diagnostic — at
compile time for literals, a run-time fatal for card values — not a filter with a moved root.

The root lists have two more silent cases. A list of odd length,
`laplace_np(V(a), {1.0}, {-1000.0, 0.0, -2000.0})`, takes the dangling −2000 as a real root
(its response is exactly that of poles at −1000 and −2000), where the list is malformed. And
the z-domain form accepts an unpaired root too: `zi_zp(V(a), '{0.5, 0.0}, '{0.3, 0.4}, 1u)`
compiles and runs.

<a id="d"></a>
## D — smaller slips

- **D1** The expression-depth error quotes the whole source line: a 100 000-term sum on one
  line produces 800 KB of diagnostic.
- **D2** A literal real outside the integer range assigned to an integer saturates without
  a word (`ic = 1e20;` is 2147483647); conversion is otherwise exact (ties away from zero,
  the same folded and at run time).
- **D3** `%c` of 0 in `$strobe` ends the C string: the rest of the line is lost.
- **D4** `from [0:inf]` (a closed bracket at an infinite bound) is accepted without a word.
- **D5** `` `define include 7 `` redefines a directive name without a diagnostic (IEEE 1364
  19.3.1 makes that illegal); using it then fails with "expected a string literal".
- **D6** `@(timer(0, 1e-18))` fires 416 times in a 2 µs transient instead of ~2·10¹², with
  no word about the period being below the time resolution.
- **D7** `$info`, `$warning`, `$error` called in that order at the operating point print as
  WARN, ERR, INFO.
- **D8** Integer `0 ** -1` is 0 without a word (folded and at run time alike).
- **D9** Two modules whose names differ only in case (`Res`, `res`) compile without a
  compile-time note; ngspice warns at load and keeps the first.
- **D10** `%d` with a real argument is a type error; SystemVerilog converts it. To check
  against the Verilog-AMS LRM before changing.
- **D11** A noise source costs about 350 KB of compile memory: 4 000 `white_noise`
  contributions take 16.7 s and 1.4 GB (2 000: 7.1 s, 600 MB). Real models have tens.
- **D12** A module with no ports compiles without a note, and ngspice cannot instantiate it:
  `N1 mm` takes `mm` for a node and answers "could not find a valid modelname".
- **D13** A real literal that underflows (`1e-400`) becomes 0 in silence; one that overflows
  (`1e309`) is an error.
- **D14** Two `.osdi` libraries that both define `pq`, loaded with two `pre_osdi`, draw
  "device "pq" is already registered; keeping the existing device and ignoring this one" —
  naming neither library (the case-collision warning does name the file). The first loaded
  wins.
- **D15** Compile memory grows about quadratically with the nesting depth of `if` blocks:
  500 levels 83 MB / 0.2 s, 2 000 322 MB / 0.7 s, 5 000 1.5 GB / 3.8 s, 8 000 3.45 GB /
  7.5 s (a flat `else if` chain of 2 000 arms is 275 MB / 0.5 s). Real models nest tens deep;
  the robustness campaign's quadratic cases (2026-09-23 F7, F9) were tables and filter states.
- **D16** `cross` treats *reaching* zero as a crossing, one way only. With
  `pwl(0 0 1u 0.5 2u 0)` and `cross(V(a)-0.5, ...)` — the expression rises to exactly 0 at
  1 µs and falls back, never positive — `dir = 0` and `dir = +1` fire at 1 µs and `dir = −1`
  never fires; a flat stretch at 0 followed by a fall behaves the same. A threshold equal to
  a source level (a PWL plateau, an ideal logic level) is a common case. Whether touching
  zero is a crossing is for the LRM to settle; the asymmetry (entering zero counts as rising,
  leaving it does not count as falling) is the part to look at.

## Verified clean

- **Derivatives at awkward points**, 31 cases against analytic values (`.ac` conductance and
  op value): `pow` with zero, negative and variable bases and exponents, `x**2.0` at −1,
  `abs`/`min` at their kinks (a one-sided slope each), `atan2` both ways, `asinh`/`acosh`/
  `atanh`, `limexp` (linear beyond exp = 1e30), `log`, `ln`, `tanh`, `asin`/`acos`/`tan`,
  `hypot`, `sqrt`, `x/x`, real `%`, `floor`, `exp`.
- **Real to integer**: rounding ties away from zero, saturation, folded = run time.
- **Integer `/` and `%`**: `INT_MIN / -1` and `% 0` are guarded in the code generator.
- **Preprocessor and lexer**, 25 cases: recursive and mutually recursive macros, missing
  arguments, `` `ifdef `` without `` `endif ``, a stray `` `else ``, unterminated comment and
  string, self-include, a missing include, 200 nested `` `ifdef ``, a comma inside a macro
  argument, escaped identifiers, CRLF continuations, `` `__FILE__ ``/`` `__LINE__ `` (right
  with CR-only line ends), a NUL byte, invalid UTF-8 in a comment, a BOM, a macro name
  inside a string (not expanded).
- **`$strobe` formats**, 29 cases (27 exact; `%r` prints `1.500000n`, implementation-defined, and `%c` of 0 is D3): `%e %g %5.2f %-6d %06d %0d %h %o %b %c %s %10s %% %m %x
  %.3s`, escapes `\101 \t \"`, `INT_MIN`, negative numbers in `%b %o %h`, inf.
- **Analog functions**: recursion (direct and mutual), `ddt`, net access, events in a
  function, writing an input, wrong argument count, an expression or parameter or node as
  an `output` argument, a 300-deep call chain; aliased `inout` arguments copy in and out.
- **Disciplines and natures**: flow on a potential-only discipline, incompatible
  disciplines on a branch, `ground` declarations, abstol 0 and negative, nature cycles,
  derived natures, undeclared disciplines.
- **Parameter ranges**: empty ranges, `exclude` points and ranges, card values out of range
  and excluded, two `from` ranges (a union), a range referring to a later parameter.
- **`analysis()`** across op, dc sweep, ac, tran and noise against the LRM table.
- **`laplace_nd/zd/np`** at 1 kHz against closed forms; the transient step response at τ
  and 3τ; per-element card arrays (`den[1]=`).
- **Noise**: `white_noise`, `flicker_noise` with exponents 0.5, 1, 2, `noise_table` and
  `noise_table_log` (unsorted input, extrapolation both ends, a repeated frequency refused),
  two sources of the same name (uncorrelated), `m=4` (power ×4), `dtemp`.
- **`ddx`**, 12 cases: partials of a branch voltage, conditionals, nested `ddx`, flow probes,
  `$temperature`, a branch argument (L011).
- **Strings, `case`, loops**: equality on literals and card values, concatenation,
  `$sformat`, `case` on strings and reals, the first matching item wins, two `default`s
  refused, `repeat` with negative and real counts.
- **Operators**, 21 cases folded and at run time: `-2**2`, `**` left-associative, `>>` logical
  and `>>>` arithmetic on negatives, shifts by 31 and 32, negative `/` and `%`, `~`, `^`, `~^`.
- **Branches**: a switch branch statically and toggled in a transient, per-instance node
  collapse from a model parameter, indirect contributions (follower and inverting
  amplifier), V and I contributions to one branch (the last decides, L022).
- **Instantiation**: unknown parameter or port, too many positional overrides, port count
  mismatches, unknown module, duplicate instance, self-instantiation, `$param_given` after an
  override, a two-level override chain, an unconnected child port.
- **Events**: `cross` both ways and filtered, `above` (fires at the initial step when true),
  `or`, `initial_step or final_step`, crossing times within 0.1 ns; `last_crossing`;
  `idtmod` wrapping with positive and negative integrands and an offset.
- **ngspice side**: `$simparam` of gmin, tnom, reltol, abstol, vntol, temp, iteration,
  sourceScaleFactor; instance parameters (instance over model, out of range refused);
  operating-point variables through op and tran; `localparam` on a card (warned); a generate
  `if` on a parameter (refused with a clear reason); quoted and unquoted string values.
- **Robustness**: 760 mutants of six corpus models (token deletion, duplication, swap,
  replacement, truncation, line duplication and deletion) — no panic, signal or hang; compile
  time on 2 000 `else if` arms, `case` items, parameters, internal nodes, `ddt` operators and
  `$strobe` calls stays within 1.8 s.
- **Small-signal forms of the time operators**: `idt` (1/jω), `ddt` (jω), `absdelay`
  (e^−jωτ), `transition` with and without a delay, `idtmod`; `white_noise` adds nothing to a
  transient. (`zi_*` is the documented bilinear image, recorded on the 2026-09-04 and
  2026-09-21 pages: a unit delay on a step swings to −1 before rising.)
- **Branches after E-782 and E-757**: `I(a,b)` with `I(b,a)` (sign), `V(a,b)` with `V(b,a)`,
  `V(a)` with `V(a,g)` for a declared ground, a named branch beside the unnamed one, a swapped
  flow probe; a child's own-branch probe beside the parent's contribution on the same nets,
  and a reversed second child.
- **Events and analyses**: `initial_step("dc"|"ac"|"tran"|"noise"|"static")`, a two-name list,
  `final_step("tran")` per analysis; `$debug` per evaluation; contributions and `ddt` in events
  refused; two `analog` blocks; port direction errors.
- **Misc**: `$limit` with pnjlim and with a function identifier (same op as unlimited, within
  tolerance; a quoted unknown name falls back with L020); potential-noise contributions;
  `openvaf_allow` on a statement and a module; `-D` and `-I` (the including file's directory
  first); 300 ports; `$rtoi`, `$itor`, `$vt` (CODATA 2018); string value sets on the card;
  three instances sharing one `$fopen` file name; a numeric-literal battery (scale factors
  with `M` = mega, based and sized integers, `_`, denormals).
- **Late checks**: a `dc temp` sweep (`$temperature` per point, `analog initial` re-run per
  point); `$param_given` in another parameter's default; noise summed over two child
  instances; `analysis("nodeset")` during a `.nodeset` op; `.ic` with and without `uic` on an
  OSDI capacitor (τ = RC); `laplace_nd` coefficients following `altermod`; 10 000-character
  `$strobe` literals and 20 000-character `%s` and `$sformat` strings (width above 4096
  refused); the `--cache-dir` build after an include changes; `-o` equal to the input (refused,
  source intact), a missing output directory, a missing or directory input; `$finish`, `$stop`
  and `$fatal` in a transient; argument conversion into analog functions.
- **Last minutes**: `ddt` and `idt` with an abstol or a nature argument; an analog function in
  a parameter default (re-evaluated for a card value); `$mfactor` through a Verilog-A hierarchy
  under an ngspice `m=2`; array `input` and `output` arguments; extra `$strobe` arguments
  (appended); 12th- and 20th-order `laplace_nd` exact at 1 kHz and 1 MHz; `cross` events on a
  PWL corner and at the stop time (no step halving).
- **Lint census** over the 94 corpus files: the expected three failures (EPFL-HEMT's
  `V(si,si)`, two macro-only files); L029, L035, L032, L027, L022, L028 and L015 sampled
  at their first sites and right there (L027's `Fb = 0.0 from (0.0:inf)` in `fbh_hbt` is a real
  slip in the model). L037 is F7.
