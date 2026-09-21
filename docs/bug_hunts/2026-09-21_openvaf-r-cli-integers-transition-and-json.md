# openvaf-r bug hunt — the command line, integer arithmetic, the `transition` filter, and the JSON dump

**Date:** 2026-09-21, one hour (12:21–13:21; the probes ran until 13:05, the write-up
interleaved from 12:46 on), at head `1b892ae6` (after E-689…E-692, the analyses,
node-lookup and probe fixes of the morning). **Binaries:** the repo's
`OpenVAF-master-20260610/target/opt/openvaf-r` (built 09:07) and
`ngspice-46/build/src/ngspice` (built 11:30), both from the E-692 tree. **Method:**
~330 small Verilog-A modules and decks written for the hour, compiled and (where
they compile) run on ngspice through a throw-away harness in the scratchpad
(`hunt2/h.py`, `p1.py … p100.py`), each probe checked against the VAMS-2023 text
(`pdftotext -layout docs/VAMS-LRM-2023.pdf`), IEEE 1364-2005 where VAMS defers to
it, or against the textbook response. Nothing was fixed; this is the list.
The ground chosen was what the earlier compiler hunts had not walked: the
command line itself (every flag, output paths, batch mode, cross targets, the
`--dump-json` and `--print-expansion` dumps), bus ports and bit-selects, the
integer operators at their 32-bit edges (shifts by 32 and by −1, `**` with
negative and overflowing exponents, `INT_MIN / −1`, `$rtoi` of infinities), two
modules per file, the format conversions of `$sformat`/`$strobe` one by one,
string semantics (aliasing in `$sformat`, concatenation, comparison, `case` on
strings), user functions named like built-ins or ports, `output`/`inout` function
arguments, the argument forms of `slew`, `transition`, `absdelay`, `idt` and the
event operators, the Newton Jacobian through pass-through operators, loops with a
solution-dependent trip count, potential-form noise, include resolution, the
`pre_osdi` failure modes, and the declaration and preprocessor diagnostics.
Areas the earlier hunts covered in depth (parameters and arrays, events in
transient, `$table_model`, the corners, the loop commands, hierarchy, the delays
under the Transient-op fallback) were only touched in passing.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--transition-rise-and-fall-times-scale-with-the-amplitude-of-the-step) | *(fixed in [E-698](../../enhancements_doc/Enhancement-698.md): `transition` and `slew` are realised by the simulator -- LRM 4.5.8's ramps scheduled from the accepted changes of the input, corners as breakpoints, the interruption rule; `slew` the ideal limiter on the accepted output -- no tracking loop, no fixed rate, no tail)* the rise and fall times of `transition()` scale with the amplitude of the step: `transition(x, 0, 1u, 1u)` takes 1 µs from 0 to 1, **5 µs from 0 to 5, 0.2 µs from 0 to 0.2, 3 µs from 0 to −3**; under `` `default_transition 1u `` a 1 → 1.1 step takes 0.1 µs. LRM 4.5.8 says the filter "forces all positive transitions of expr to occur over rise_time" — the time, not a rate. The operator is lowered as `slew(absdelay(x, td), 1/trise, 1/tfall)`, a rate that assumes a unit swing (the lowering's own comment calls it "an approximation for arbitrary-amplitude inputs") | wrong result, silent |
| [F2](#f2--transition-and-slew-settle-off-target-after-a-step-when-the-timestep-is-longer-than-the-ramp) | *(fixed in [E-698](../../enhancements_doc/Enhancement-698.md): `transition` and `slew` are realised by the simulator -- LRM 4.5.8's ramps scheduled from the accepted changes of the input, corners as breakpoints, the interruption rule; `slew` the ideal limiter on the accepted output -- no tracking loop, no fixed rate, no tail)* under the default trapezoidal integration, a `transition` or `slew` output that ramps faster than the timestep overshoots its target (1.00020 for a 1 µs rise at a 10 µs step, 1.00198 for a zero rise at a 1 µs step) and then **stays 2e-4 to 6e-4 off it for the rest of the plateau** (0.999811 at 0.5 ms and 0.999814 at 0.9 ms after a delayed edge; 1.00057 and 1.00056 after an undelayed one; 1.82e-4 instead of 0 after the fall); `slew` of the same comparator shows the same 1.00057, `absdelay` alone is exact, `method=gear` settles exactly (overshoot 8e-5 remains); a ramp at or above the step is exact. **Through `ddt` the error is no longer small:** a switched capacitor `ddt(1n * transition(cmp, 0, 1u, 1u))` into 1 kΩ puts the right 1 V pulse on the load for 1 µs and then 0.57–0.84 V for the whole plateau where it should be 0 (gear: 0). The tracking loop's time constant is trise/1000 = 1 ns, and the trapezoidal rule neither damps its corner error nor decays it: the factor per 10 µs step is (1 − h/2τ)/(1 + h/2τ) ≈ −0.9996 | wrong result, silent |
| [F3](#f3--integer--saturates-where-every-other-integer-operator-wraps) | *(fixed in [E-693](../../enhancements_doc/Enhancement-693.md): the integer power is exponentiation by squaring in wrapping i32 -- `x ** 2` is literally `x * x` -- and the lint's twin follows)* integer `**` saturates at ±2147483647 where `+`, `−`, `*` and `<<` wrap: at run time `(2*k)**31` is 2147483647 while `2*2*…*2` (31 times) is −2147483648, `(46341*k)**2` is 2147483647 while `(46341*k)*(46341*k)` is −2147479015, so `x**2 ≠ x*x` past 46340; the folded defaults agree with the run time, and L030 says "clipped to 2147483647" for `2**31` and "wraps to −2147483648" for the same value written as a product. The integer power is lowered through `llvm.pow.f64` and a saturating real-to-integer cast | wrong result, silent, edge |
| [F4](#f4----dump-json-writes-invalid-json-for-any-module-with-a-fatal-error-warning-or-info) | *(fixed in [E-694](../../enhancements_doc/Enhancement-694.md): every string the dump writes is escaped per RFC 8259)* `--dump-json` writes a file no JSON parser accepts whenever the module contains a `$fatal`, `$error`, `$warning` or `$info` (with or without a message): the lowering appends a real newline to the message (`hir_lower/src/ctx.rs:254`) and the serializer writes string constants raw, without escaping (`mir/src/serialize.rs:170`), so the `"sconst"` value spans two lines. `$strobe`, `$display`, `$finish`, noise names and source-escaped literals survive only because their escapes are still the two source characters | tool output |
| [F5](#f5--an-unknown---target_cpu-prints-llvms-warning-33-times-garbled-and-compiles-anyway) | *(fixed in [E-695](../../enhancements_doc/Enhancement-695.md): the E-453 probe target machine is created with stderr captured and LLVM's complaint becomes one error with a help line; exit 65, no output)* `--target_cpu bogus` compiles with exit 0 and prints LLVM's "'bogus' is not a recognized processor for this target (ignoring processor)" 33 times, interleaved from the parallel codegen threads into lines such as `''bogus_cpubogus_cpu' is not a recognized processor…` — the option is validated nowhere, the message is not the compiler's, and the code is generated for LLVM's generic CPU, not the one asked for | diagnostic |
| [F6](#f6--slew-and-transition-arguments-outside-their-domain-at-run-time-are-projected-in-silence) | *(fixed in [E-696](../../enhancements_doc/Enhancement-696.md): the rates and times go through E-651's `project_or_warn` -- named once per accepted point, a zero rate drops the limit in that direction)* a `slew` rate or a `transition` time that reaches the model from the card outside its domain is projected onto it without a word: `rate=0` **freezes the `slew` output at its initial value for the whole run**, a negative maximum positive rate is used as its magnitude, a positive maximum negative rate as its negative, `neg=0` never lets the output fall (and it overshoots to 1.0057), a negative rise time makes the `transition` instantaneous, a negative delay is 0. The same values as literals are compile errors ("must be greater than zero", "must not be negative"), and `absdelay` with the same negative delay from the card prints a run-time warning and says it used 0 | run-time domain silence |
| [F7](#f7--a-slew-rate-of-1e13-vs-or-more-aborts-the-transient-at-the-first-edge) | *(fixed in [E-697](../../enhancements_doc/Enhancement-697.md): a side at or above 1e12 V/s takes the infinite-rate path -- no clamp, the fixed 1e9/s gain -- instead of a ramp the timestep control cannot resolve)* a `slew` whose rate is 1e13 V/s or more (from the card or written in the model) aborts the transient at the first edge — "Timestep too small; time = 0.001, timestep = 6.25e-19: trouble with node n1#implicit_equation_0" — or grinds for a minute first (`pos=1e15` with `neg=-1e5`); 1e12 runs, 1e13 fails at a 10 µs step and passes at 0.5 µs, 1e14 and above fail at both, and 1e299 runs again because the lowering's `HUGE` guard (1e300 on the tracking gain, i.e. a rate above 1e297) switches to the fixed 1e9/s gain. A model that writes a huge rate to switch the limiter off cannot; `transition` with a 1e-18 s rise time is unaffected | abort |

Dropped after checking the LRM or the code: a string literal assigned to an integer
variable (`k = "5"` gives 53, `"abc"` gives 6382179: IEEE 1364-2005 2.6.3 makes a string
literal an unsigned integer of its packed ASCII bytes, so this is conformant; that the
same literal is refused in `1 + "5"` is the inconsistency, noted below); `-8 >> 1` =
2147483644 (4.2.10, the logical shift); `1 << −1` and `1 << 32` = 0 (the count is
unsigned); `2 ** −1` = 0 (Table 5-6, already E-420); `INT_MIN / −1` = INT_MIN
(E-286's guard); `(k > 0) ? 1 : 2` divided by 4 = 0 (integer division, both arms
integer); `case (1)` with solution-dependent labels (legal, works); `$discontinuity(−1)`
(LRM 4.5.4: −1 is the `$limit` form, so accepted); `timer(t0, −1m)` (a non-positive
period is a one-shot); a two-`inout` function called with the same variable twice
(copy-in, copy-out, the second write wins); `$param_given(alias)` refused (3.4.7: an
alias is a card spelling, not a name in the body); `transition` in `ac` passing the
small signal through unchanged (4.5.9's rule for `slew` when not slewing).

## What was read and run

LRM sections read for the probes: 2.6.3 (string literals as integers), 3.2 (the integer
range), 3.4.7 (`aliasparam`), 4.2.4 and 4.2.10 (integer power, shifts), 4.5.4
(`$discontinuity`), 4.5.7–4.5.9 (`absdelay`, `transition`, `slew`; the small-signal
rule), 4.5.10 (`last_crossing`), 4.6.4 (noise as a potential contribution), 5.10 (`case`
labels as expressions), 9.17.3 (`$discontinuity(−1)` with `$limit`), IEEE 1364-2005
5.1.5 and 5.4.1 (the power operator and expression bit lengths).

Compiler source read: `openvaf-driver/src/cli_def.rs` (the flag list), `hir_lower/src/expr.rs`
(`lower_int_pow` at 1015, `lower_transition` at 4324, `lower_rate_limited_track` at 4446
and the TRACK_C comment), `hir_lower/src/ctx.rs` (`runtime_fatal`, 254), `mir_llvm/src/builder.rs`
(the Idiv/Irem guard, 844), `mir_opt/src/const_eval.rs` (the same guard at fold time),
`mir/src/serialize.rs` (the JSON writer, 160–176).

Probe families, in the order they ran (`hunt2/pN.py`):

- **p1, p58, p81** — the command line: `-o` to a directory, a path without an
  extension, an unwritable directory, a read-only file; `-A`/`-W` by name and by
  number; `-D` with a value containing spaces, with a backtick, twice; `-I` to a
  missing directory; both cross targets; `--target_cpu bogus`; `-O 5` and `-O -1`;
  `--dump-json --dry-run` naming; `-C`; no file, two files, a missing file, an empty
  file, a file without a module; `-b` with `-o`; a path with spaces and umlauts; two
  modules of one name; `` `include <…> ``; including a directory and an empty file.
- **p2** — bus ports: `[0:3]`, `[3:0]`, `[1:4]`, a genvar loop over bits, bit-to-bit
  branches, named branches on bits, a parameter as the bit index, an internal bus,
  an out-of-range bit, the whole bus without a select, a part-select.
- **p3, p6, p35** — integer edges at run time and at fold time (the parameter defaults):
  shifts by 31, 32, 33, −1 (both `>>` and `>>>`), `**` with negative, 31, 40 and
  overflowing exponents, `+`/`−`/`*` overflow, `abs(INT_MIN)`, `−INT_MIN`, `$rtoi`
  of ±1e300 and NaN, `k / 0`, `INT_MIN / −1` and `% −1`, `1 << 63`, the bitwise
  operators on negative operands, `1.0/inf`, `inf − inf`, mixed-type ternaries,
  `case (1)`, `casez`/`casex`, comparisons against infinities, `min`/`max`/`floor`
  of infinities; each at `-O 0` against `-O 3` (identical).
- **p4** — two modules in one file, one instantiating the other, a third differing
  only in case.
- **p5, p5b, p82** — every format conversion of `$sformat` and `$strobe` with widths,
  precisions, flags, `*` widths, `%c` of 0/−1/955, `%x`/`%o`/`%b` of −1, infinities
  and NaN, `%m`, `%l`, `%t`, `%r`, `%5.2s`, `%%`, a parameter string as the format,
  a `%` at the end, `100%d`, the empty forms.
- **p7** — batch mode: a changed include file, a changed `-D`, a changed `-O`, a changed
  `-A`, the second identical build (each keyed correctly).
- **p8** — include resolution: the includer's directory against a decoy in the cwd,
  `-I`, a nested include relative to the nested file.
- **p9, p66, p66b, p66c** — `--dump-json` on a plain module, on one with events,
  noise, delays, a Laplace filter and a `$fatal`, then the bisection to the four
  message tasks.
- **p10, p77** — strings: `$sformat` with the destination among its arguments,
  self-copy, self-doubling, a ternary of strings, `{}` concatenation, `==`/`!=`/`<`,
  `case` on a string, appending in a loop, a string literal into an integer or
  real, a string variable or parameter into an integer, `1 + "5"`, `+"a"`.
- **p11, p84** — user functions named `exp`, `abs`, `max`, the module, a port;
  variables named `ln`/`sqrt`; `output` arguments given a parameter, a literal, a
  probe; two `inout` arguments bound to one variable; an integer function returning
  a real; a function that never assigns its result; a `string` function and a
  `string` argument; duplicate directions and disciplines; a port without a
  discipline; `V(l1.a)`; names shared between nets, branches, variables and ports.
- **p12, p52, p53** — operator forms: `slew` with one, a zero and a negative rate,
  both rates positive, a solution-dependent rate; `ddt(x, abstol)`; four-argument
  `idt`; `transition` with a solution-dependent delay, a five-argument form, a
  negative rise or delay, an integer input; `absdelay` with a negative and a
  solution-dependent `maxdelay`; `I(<a>)` read and contributed; `$realtime`;
  `$discontinuity(−1)` and `(2)`; `ddt` of an integer.
- **p13, p19** — events: five-argument `cross` with `enable` 1 and 0, `cross or timer`,
  `above` with four arguments, `timer` with three and four, a negative period,
  `initial_step("tran", "dc")`, `final_step("tran")`, `initial_step or final_step`,
  direction 2, `cross` in a conditional, a nested event, `cross` of an integer and
  of a constant; `timer` counts over seven start/period/step/stop combinations.
- **p14, p14b, p17** — the Newton Jacobian of a diode whose voltage passes through
  `slew`, `transition`, `absdelay(…, 0)`, `absdelay(…, td)` with `td = 0`,
  `last_crossing` (24 iterations and the same solution in every form).
- **p15, p20, p63, p63b** — parameter defaults from `$temperature`, `$mfactor`,
  `$abstime`, `$random`, `$vt`, `$simparam`, `$param_given`; a string instance
  parameter, a string with a space on the instance line, a bad member of the set,
  an unquoted value; a 120-character parameter and opvar name; a zero-port module; a
  40-port module; `$param_given` in a default, read per model and per instance.
- **p16** — `pre_osdi` of a text file, a missing file, the same file twice, two
  libraries defining one module, a `.va` file, and no `pre_osdi` at all.
- **p18, p18b, p36, p59, p83** — `transition`: the settled value and the extrema across
  four steps and three rise times, the amplitude sweep with and without
  `` `default_transition ``, `method=gear` against `trap`, the samples around the edge.
- **p22** — a `while` fixed-point loop, a `repeat` and a `for` with a solution-dependent
  bound, a `while (1)` with `break`, a Newton solve inside the model (the outer Newton
  converges in 5 iterations, the AD through the loop is right).
- **p23** — thermal noise of a resistor as a flow contribution, as a potential
  contribution, and as a potential source in series with a flow (2.879e-9 V/√Hz in
  all three, the textbook value for 500 Ω).
- **p95, p96, p97** — `altermod`/`alter` of string parameters, a bad member after
  `alter`, `showmod` of strings with escapes and unicode, a string parameter as a
  vector (refused with a clear line), a 600-character `desc`, escapes in `units`.
- **p98, p99, p100** — every `slew`/`transition` argument set to 0, negative, 1e-30 or
  1e30 on the card (F6), then the rate scan 1e12 … 1e300 at two steps (F7); `laplace_nd` with a zero constant, leading or numerator
  coefficient from the card.
- **p92b, p91** — the value at t = 0 of `absdelay`, `transition`, `slew` and
  `laplace_nd` when the input is already 1 (all 1, no spurious ramp), and a device
  with both terminals on ground, on one node, or reversed under `op`, `ac` and `tran`.
- **p93, p94** — `slew` of the pulse and of an in-model comparator at four steps and
  three rates; `transition` with and without a delay against `slew(absdelay(…))`,
  `slew` alone and `absdelay` alone, the bisection behind F2.
- **p67, p70, p74** — `absdelay` of a 1 kHz sine against the exact delayed sine at four
  steps; the small-signal gain of `transition`, `slew` and `absdelay` outputs from 1 Hz
  to 1 GHz; a `maxdelay` of 1, 1e6 and 1e300 (no memory or time cost).
- **p76, p85** — expression and preprocessor diagnostics: duplicate `case` labels,
  `if (y = 1)`, `"a" == 1`, `"a" + "b"`, an alias in a default, assignment to a
  parameter and to a port, `1 < 2 < 3`, a string in a condition, `2 ** "3"`;
  `` `ifdef (A && B) ``, a lone `` `elsif ``, an extra `` `endif ``, an unterminated
  `` `ifdef ``, two `` `else ``, `` `define `` with no name, `` `define module ``,
  `` `undef `` of an unknown macro, the literals `1e`, `1e+`, `0x10`, `1.5f`, `1.5F`,
  `1.5meg`, `_1`, `1__0.5`, `1_.5`.

## F1 — `transition` rise and fall times scale with the amplitude of the step

**Observed.** A module that follows a comparator with the transition filter:

```verilog
parameter real amp = 1.0, td = 0.0, tr = 1u, tf = 1u;
y = transition(V(a,b) > 0.5 ? amp : 0.0, td, tr, tf);
```

driven by a 0/1 pulse, `tran 0.05u 60u`, the 10 %–90 % times measured with `meas`
and divided by 0.8 to give the full-swing time (`hunt2/p36.py`):

| `amp` | rise (LRM: 1 µs) | fall (LRM: 1 µs) | max | min |
|---|---|---|---|---|
| 1 | 1.00 µs | 1.00 µs | 1.00068 | −2.97e-4 |
| 5 | **5.00 µs** | **5.00 µs** | 5.00068 | −2.97e-4 |
| 0.2 | **0.20 µs** | **0.20 µs** | 0.20007 | −2.97e-4 |
| −3 | **3.00 µs** | **3.00 µs** | 2.97e-4 | −3.00068 |

The same under `` `default_transition 1u `` with no time arguments (`hunt2/p83.py`):
a 0 → 1 swing takes 1.00 µs, 0.2 → 1 takes 0.80 µs, 0 → 5 takes 5.00 µs, 1 → 1.1 takes
0.10 µs. The time is proportional to the swing: the operator has a fixed *rate* of
1/trise volts per second, not a fixed *time*. The interruption rule inherits it: a
0 → 2 transition over 100 µs reversed after 50 µs is at 0.5 at the reversal, where
4.5.8's ramp is at 1.0 (`hunt2/mr2.va`).

**Expected.** LRM 4.5.8: "transition() forces all positive transitions of expr to
occur over rise_time and all negative transitions to occur in fall_time" — the
transition time is the time from the old value to the new one whatever the two
values are; Figure 4-5 draws a swing of arbitrary height over `rise_time`. A model
that switches a 5 V or a 3.3 V logic level, an on/off conductance of 1e-3 S, or a
resistance in ohms with `transition(…, 0, 10n, 10n)` gets a ramp 5, 3.3, 0.001 or
1000 times the length it wrote.

**Where.** `hir_lower/src/expr.rs`, `lower_transition` (4324): the doc comment says
the operator is lowered as `slew(absdelay(x, td), 1/trise, 1/tfall)` and that
"trise/tfall are transition *times* in the LRM … so they are converted to rates by
assuming a unit-amplitude transition (rate = 1/t) — exact for the common case of a
comparator-style 0/1 input, an approximation for arbitrary-amplitude inputs." The
rate limit is the E-512 tracking loop of `lower_rate_limited_track` (4446). A
correct rate needs the size of the pending swing — the loop would have to latch the
input at each change (it already detects the change for the delay) and divide
`|new − old|` by the time. The 09-14 hunt's check of "`transition` and `slew` with
overridden times and rates" did not vary the swing, which is why it passed.

**Kind.** Wrong result, silent; every `transition` with a non-unit swing. Not
platform-specific.

*Fixed in [E-698](../../enhancements_doc/Enhancement-698.md).* The operator is no
longer a tracking loop compiled into the model: the compiled code emits the
synthetic input node and stores td, rise and fall in instance data, and ngspice
schedules the ramp from the change of the *accepted* input -- from the current
output to the new value over rise_time or fall_time, so a 5 V swing takes 1 µs
for `tr = 1u`, as does a 0.2 V or a −3 V one -- with breakpoints at both
corners and 4.5.8's readjustment rule for an interrupted ramp (the 0 → 2 ramp
reversed after 50 µs is at 1.0, and falls to 0 in 50 µs more from the
original destination's slope). `` `default_transition `` and the delay-only
form ramp over the directive's time at any swing.

## F2 — `transition` and `slew` settle off target after a step when the timestep is longer than the ramp

**Observed.** The same module with `amp = 1`, the pulse rising at 1 ms and falling at 3 ms,
`td = 1m`, `tran <step> 6m`, `meas` extrema and spot values (`hunt2/p59.py`):

| integration | step | trise = tfall | max | min | y at 2.5 ms | y at 2.9 ms | y at 5.5 ms |
|---|---|---|---|---|---|---|---|
| trap (default) | 10 µs | 1 µs | 1.00020 | −1.998e-4 | **0.999811** | **0.999814** | **1.82e-4** |
| gear | 10 µs | 1 µs | 1.00008 | −7.08e-5 | 1.000000 | 1.000000 | 0.000000 |
| trap | 10 µs | 10 µs | 1.000000 | −5.9e-19 | 1.000000 | 1.000000 | −1.9e-20 |
| trap | 10 µs | 20 µs | 1.00033 | −1.2e-18 | 0.999972 | 0.999979 | −1.8e-20 |
| trap | 1 µs | 0 | 1.00198 | −1.985e-3 | 1.00009 | 1.00002 | −1.58e-6 |
| gear | 1 µs | 0 | 1.00195 | −1.699e-3 | 1.000000 | 1.000000 | 0.000000 |
| trap | 100 µs | 1 µs | 1.00002 | −2.0e-5 | 1.00001 | — | −5.9e-6 |
| trap | 0.5 ms | 1 µs | 1.00002 | −1.67e-5 | 0.999987 | — | 2.4e-6 |

The delay is not the cause. The same module with `td = 0`, and `slew` fed the same
comparator, at a 10 µs step (`hunt2/p94.py`):

| form | max | min | y at 2.5 ms | y at 2.9 ms | y at 5.5 ms |
|---|---|---|---|---|---|
| `transition(cmp, 0, 1u, 1u)` | 1.00096 | −1.2e-18 | **1.00057** | **1.00056** | −3.5e-20 |
| `transition(cmp, 1m, 1u, 1u)` | 1.00020 | −2.0e-4 | 0.999811 | 0.999814 | 1.82e-4 |
| `slew(absdelay(cmp, 1m), 1e6)` | 1.00020 | −2.0e-4 | 0.999811 | 0.999814 | 1.82e-4 |
| `slew(cmp, 1e6)` | 1.00096 | −2.2e-5 | **1.00057** | **1.00056** | 5.2e-20 |
| `absdelay(cmp, 1m)` | 1.000000 | 0 | 1.000000 | 1.000000 | 0 |
| `slew(V(a,b), 1e6)` (the pulse itself, `p93.py`) | 1.00001 | −1.2e-18 | 1.000000 | — | −2.6e-20 |

`transition` is exactly `slew(absdelay(…))` (F1's lowering), and the two agree to the
last digit; the error belongs to the rate-limited tracking loop when its input steps
*between* timepoints (a comparator inside the model places no breakpoint, the pulse
source's own edge does, which is why the last row is clean).

The ramp ends at 2.001 ms; half a millisecond later the output is still 1.9e-4 short,
and 0.9 ms later it has moved by 3e-6. After the fall it rests at +1.82e-4 instead of 0.
The transition output is outside the range of its input (above 1, below 0) in every
trapezoidal row, by up to 0.2 % for an instantaneous transition at a 1 µs step; the
09-19 hunt's F1 check and the E-512 suite sample with a step at or below the
transition time, where the row reads exactly 1.

**Mechanism.** `lower_rate_limited_track` integrates `dy/dt = clamp(K (x − y), −neg, +pos)`
with `K = 1e3 · rate` (TRACK_C), so the tail after the linear ramp has τ = trise/1000
= 1 ns for a 1 µs rise. When the input steps inside a timestep, the trapezoidal
rule's first implicit step carries the ramp's slope through the corner and lands
past the target (the overshoot); ngspice's trapezoidal rule applied to the tail
`dy/dt = −(y − 1)/τ` then multiplies that error by (1 − h/2τ)/(1 + h/2τ) per step —
at h = 10 µs that is −0.9996 — so it changes sign every step and decays with a time
constant of ~2500 steps = 25 ms, longer than the plateau; sampled every step, it
reads as a constant bias of either sign. Gear's factor is 1/(1 + h/τ) ≈ 1e-4,
which is why the gear rows settle on the first step. The E-512 comment's "the
settled value is exactly 1.0" holds for a step that resolves the ramp, not for the
common case of a 1–10 ns logic edge inside a 1 µs-step transient. The overshoot at
a zero rise time (1.00198) is the first trapezoidal step past the corner, where the
loop's slope is the full `TRACK_GAIN_INF` gain (1e9/s) and the implicit step lands
beyond the target.

**Consequence.** The error is small on the output and large on anything that
differentiates it. A switched capacitor written the textbook way,
`ic = ddt(c * transition(cmp, 0, 1u, 1u))` with `c = 1n`, at a 10 µs step under the
default method (`hunt2/sc.va`): the edge current peaks at the right 1 mA for 1 µs,
and then a **spurious current of up to 0.84 mA persists across the whole plateau**
(−0.57 mA at 2.5 ms, 1.5 ms after the edge) — the trapezoidal `ddt` of the
sign-alternating 2e-4 V error, which it amplifies by 2/h. `method=gear` gives 0; a
0.1 µs step gives 3e-17 A. In a circuit (`hunt2/sc2.va`: the same contribution from a
control node into a 1 kΩ load) the load node reads the right 1 V pulse for 1 µs and
then **0.57 V at 2.5 ms and up to 0.84 V across the plateau** where it should read 0;
`method=gear` reads 0 and a 0.1 µs step reads 3e-14 V.

**Kind.** Wrong result, silent; default integration method; the magnitude is 2e-4 to
2e-3 of the swing on the operator's output, and of the order of the edge current on
its `ddt`.

*Fixed in [E-698](../../enhancements_doc/Enhancement-698.md).* There is no tail to
ring: `transition`'s output is a piecewise-linear function of time the
simulator stamps as a source (`V(z) = ramp(t)`), and `slew`'s is the ideal
limiter on the output accepted at the previous point,
`clamp(V(y), y_last − neg·h, y_last + pos·h)`, exact while tracking and an
exact ramp while limiting. Every row of both tables reads 1.000000 and 0
under trap at a 10 µs step; the switched capacitor's `ddt` reads 1 mA on the
edge (the leading corner enters the breakpoint table, so the integrator
restarts at order one there instead of ringing 2, 0, 2, 0 down the ramp) and
exactly 0 across the plateau.

## F3 — integer `**` saturates where every other integer operator wraps

**Observed.** With `parameter integer k = 1` so nothing folds (`hunt2/p6.py`, `show n1`):

| expression | result | the same value by multiplication |
|---|---|---|
| `(2*k)**31` | 2147483647 | `2*2*…*2` (31 times) → −2147483648 |
| `(2*k)**40` | 2147483647 | (wraps to 0) |
| `(46341*k)**2` | 2147483647 | `(46341*k)*(46341*k)` → −2147479015 |
| `(3*k)**20` | 2147483647 | (wraps to −808182895) |
| `(-2*k)**31` | −2147483648 | (the same, by coincidence: INT_MIN is its own wrap) |

The folded parameter defaults agree with their run-time twins (`2**31` → 2147483647,
`46341*46341` → −2147479015), and so does L030: `2**31` is "clipped to 2147483647"
while the product of thirty-one 2s "wraps to −2147483648", both correct
descriptions of what the compiler does and contradictory descriptions of one
arithmetic. `x**2` and `x*x` differ for every |x| > 46340; `big + k`, `neg − 2k`,
`big * 2k` and `k << 31` all wrap (`hunt2/p3.py`).

**Expected.** IEEE 1364-2005 5.1.5 defines `**` on integers with Table 5-6 (E-420
implemented its negative-exponent rows); 5.4.1 makes the result width that of the
operands (32 bits for `integer`), and 3.2/4.2.1 make integer arithmetic two's
complement modulo 2³² — the same rule the compiler applies to every other operator
and that E-675 wrote into L030's help text ("integer arithmetic is 32-bit two's
complement and wraps on overflow"). `2 ** 31` as an `integer` is −2147483648, and
`x ** 2` is `x * x`.

**Where.** `hir_lower/src/expr.rs`, `lower_int_pow` (1015): the non-negative branch
casts both operands to real, calls `llvm.pow.f64` and converts back with `ficast`, the
saturating real-to-integer cast (E-392/E-420's own choice for `$rtoi`, right there,
wrong here). `mir_opt/src/const_eval.rs` folds `Pow` in `f64` the same way. A wrapping
integer power (repeated squaring in `i32` with wrapping multiply, or a wrapping cast of
the exact value while it fits in 53 bits) is the fix; E-675's lint already knows how.

**Kind.** Wrong result, silent; edge (an overflowing power is rare, but `x**2` on an
integer is not).

*Fixed in [E-693](../../enhancements_doc/Enhancement-693.md).* The non-negative arm of
`lower_int_pow` is exponentiation by squaring in wrapping `Imul`: a constant exponent
gets the minimal multiply chain (`x ** 2` is the one instruction `x * x`), a run-time
one the unrolled 31-bit chain; `int_pow_wrapping` is the lint's twin, L030 says
"wraps to −2147483648" for `2 ** 31` like the product spelling, and the MIR
interpreter's `+`, `-`, `*` wrap too. Table 5-6, `$rtoi` and a real `**` unchanged;
`hunt3diag` pins the fourteen values at `-O 0` and `-O 3`.

## F4 — `--dump-json` writes invalid JSON for any module with a `$fatal`, `$error`, `$warning` or `$info`

**Observed.** `openvaf-r m.va --dump-json --dry-run` on a module with
`if (V(a,b) > 100) $fatal(1, "too much: %g", V(a,b));` writes `m_m.json` that
`json.loads` rejects with "Invalid control character at line 226 column 36": the
value entry is

```
{
    "sconst": "too much: %g
    ",
    "uses": [ 89 ]
}
```

with a real newline inside the string. Bisected over eight variants (`hunt2/p66b.py`,
`p66c.py`): `$fatal` with a format, `$fatal` with a plain message, `$fatal(0)` with no
message (`"$fatal\n"`), `$error`, `$warning` and `$info` all produce it; `$strobe("a\nb")`,
`$strobe("x\n")`, `$display`, `$finish`, a `string` variable holding `"x\ty"`, a
literal with `\"`, and the noise source names all produce valid files. The full
module of `p66.py` (events, noise, four delay operators, a Laplace filter) is valid
without the `$fatal` line and invalid with it.

**Where.** `hir_lower/src/ctx.rs:254–255` builds the run-time message as
`format!("{msg} %g\n")` / `format!("{msg}\n")` — a real newline, since it goes to
`printf` at run time. `mir/src/serialize.rs:170` writes every string constant as
`"\"sconst\": \"{}\","` with no escaping, so any control character or `"` in an interned
string breaks the file; source literals survive because the lexer keeps their escapes
as the two characters `\` `n`, which happen to be valid JSON (a raw tab typed inside a
literal also survives, `hunt2/p90.py`). Any other lowering that adds a control
character to an interned string would break the same way.

**Kind.** Tool output; the E-640 JSON dump is unusable for any model with a
diagnostic task, which is every production compact model.

*Fixed in [E-694](../../enhancements_doc/Enhancement-694.md).* `json_escaped` in
`mir/src/serialize.rs` produces a JSON string body per RFC 8259 §7 and is applied to
the string constants, the input names and every key; the lowering keeps its newline
and the dump reads it back as `"too much: %g\n"`. `hunt13slips` [8] pins the five
message constants round-tripping.

## F5 — an unknown `--target_cpu` prints LLVM's warning 33 times, garbled, and compiles anyway

**Observed.** `openvaf-r cli.va --target_cpu bogus_cpu` exits 0 and prints 33 lines
on stderr (`hunt2/p1.py`): 16 clean copies of `'bogus_cpu' is not a recognized processor
for this target (ignoring processor)`, and 17 fragments where two threads wrote at
once — `''bogus_cpubogus_cpu' is not a recognized processor for this target' is not a
recognized processor for this target (ignoring processor)`, `'bogus_cpu'' is not a
recognized processor for this targetbogus_cpu (ignoring processor)`, bare
`(ignoring processor)`. Every other bad flag value (`-O 5`, `-A L999`, a missing
`-I` directory, `--target x86_64-unknown-linux` on this build) is refused before
compilation with the compiler's own message and the valid values. `--target_cpu` is
passed through to LLVM per codegen unit, which warns once per unit per thread and
falls back to a generic CPU: the user asked for `skylake`, mistyped it, and got
generic code with 33 lines of someone else's warning to say so.

**Kind.** Diagnostic; the flag's documented purpose ("to distribute the output to
people with unknown hardware set this option to generic") makes a typo plausible.

*Fixed in [E-695](../../enhancements_doc/Enhancement-695.md).* `LLVMBackend::probe`
creates the one E-453 probe target machine with fd 2 redirected into a pipe and
turns LLVM's complaint into the compiler's refusal — one `error:` naming the flag,
the value and the target, one `help:` with `'native'` (this machine's CPU),
`'generic'` and `llc -mcpu=help` — exit 65, no output, nothing from LLVM. Unix
capture; `batchkey` pins it.

## F6 — `slew` and `transition` arguments outside their domain at run time are projected in silence

**Observed.** `slew(cmp, pos, neg)` and `transition(cmp, td, tr, tr)` with every argument
a parameter, the defaults `pos = 1e5`, `neg = −1e5`, `tr = 10u`, `td = 0`, a 0/1
comparator input stepping at 1 ms and 3 ms, `tran 0.5u 4m`, the 10 %–90 % times
divided by 0.8 (`hunt2/p100.py`, the earlier `p98.py` agrees):

| card | `slew` rise | `slew` fall | `transition` rise | `ys` at 2.5 ms | any message |
|---|---|---|---|---|---|
| (defaults) | 10 µs | 10 µs | 10 µs | 1.0 | — |
| `pos=0` | never | never | 10 µs | **0.0** | none |
| `pos=-1e5` | 10 µs | 10 µs | 10 µs | 1.0 | none |
| `neg=1e5` | 10 µs | 10 µs | 10 µs | 1.0 | none |
| `neg=0` | 10 µs | never | 10 µs | **1.00569** | none |
| `tr=-10u`, `tr=-1e30` | 10 µs | 10 µs | **0** | 1.0 | none |
| `td=-1m` | 10 µs | 10 µs | 10 µs | 1.0 | none |

A zero rate does not mean "unlimited", it means the output cannot move: with `pos=0`
the `slew` output is 0 for the entire transient while its input is 1 for two
milliseconds of it. `neg=0` holds the output at 1 after the fall and, because the
tracking loop's clamp is now one-sided, lets it overshoot by 0.6 % on the rise.

**Expected.** LRM 4.5.9: the maximum positive slew rate "shall be positive", the
maximum negative "shall be negative"; 4.5.8: `td`, `rise_time` and `fall_time` "if
specified shall be non-negative". The compiler enforces exactly this for literals
(`hunt2/p52.py`: "slew: the maximum positive rate must be greater than zero, but is
0", "the maximum negative rate must be less than zero, but is 1000", "transition:
the rise time must not be negative, but is -0.000001", "the delay must not be
negative"), and for `absdelay` a negative delay from the card is warned at run time
("absdelay: the delay is -0.001, negative (LRM 4.5.7 requires a non-negative delay);
0 is used", `hunt2/p12.py`). The same policy for the same class of argument is the
expectation: a run-time warning naming the operator, the value and what was used —
or, for a zero rate, which cannot be projected onto anything, the `$fatal` that
`laplace_nd` raises for a zero leading coefficient (`hunt2/p99.py`).

**Where.** `hir_lower/src/expr.rs`: E-651's `project_or_warn` (652) is the facility
that projects a card-fixed argument and names it once per accepted point; its call
sites are the noise power, the distribution arguments and `absdelay`'s delay
(3705). `lower_slew` (4159) takes the absolute value of both rates ("for its own
reasons", says the E-504 comment in `lower_transition`), and `lower_transition`
clamps a non-positive time to zero, whose reciprocal is the infinite rate — both
deliberate projections, both without it, so a value the deck fixed is projected the
way a run-time quantity is: in silence, which the comment at 640 reserves for values
that "may pass through any value on the way to the solution". A zero rate is not
projected at all — the clamp simply admits no motion. The 09-18 hunt's F12 recorded
the same silence for other run-time domains.

**Kind.** Run-time domain silence; a card typo (`rate=0`, a sign) turns a limiter
into a dead output or a passthrough with no line in the log.

*Fixed in [E-696](../../enhancements_doc/Enhancement-696.md).* `slew_rate_or_warn`
and `transition_time_or_warn` route the rates, the times and the delay through
E-651's `project_or_warn`: a deck-fixed wrong sign is named and its magnitude
used, a zero or NaN rate drops the limit in that direction and says so, a negative
time or delay is named with LRM 4.5.8 and "0 is used"; run-time quantities stay
silent. `domainwarn` [21]–[28] pin the table above.

## F7 — a `slew` rate of 1e13 V/s or more aborts the transient at the first edge

**Observed.** The F6 module (`slew(cmp, pos, neg)` and `transition(cmp, td, tr, tr)` on
a 0/1 comparator stepping at 1 ms and 3 ms), rates set on the card, `tran <step> 4m`
(`hunt2/p100.py`, the last two scans):

| card | step 0.5 µs | step 10 µs |
|---|---|---|
| `pos=1e12 neg=-1e12` | runs | runs |
| `pos=1e13 neg=-1e13` | runs | **aborts at 3 ms** (timestep 1.2e-17) |
| `pos=1e14 neg=-1e14` | **aborts at 3 ms** (4.0e-18) | **aborts at 1 ms** (1.25e-17) |
| `pos=5e14 … 1e30` | **aborts at 1 ms** (6.25e-19) | **aborts at 1 ms** (1.25e-17) |
| `pos=1e15 neg=-1e5` | **60 s timeout** | **60 s timeout** |
| `pos=1e299 neg=-1e299`, `1e300` | runs | runs |
| `tr=1e-14 … 1e-18` (transition, rate 1e14 … 1e18) | runs | runs |

The abort is ngspice's "doAnalyses: TRAN: Timestep too small; time = 0.001, timestep =
6.25e-19: trouble with node "n1#implicit_equation_0"; tran simulation(s) aborted" —
the slew's own implicit equation. Nothing in the model is wrong: the LRM puts no upper
bound on a slew rate, and a rate of 1e15 V/s on a 1 V signal is a 1 fs edge, which
every other operator (a 1 fs `transition`, a 1 ns `absdelay`) takes in stride.

**Mechanism.** `lower_rate_limited_track` sets the loop gain `K = 1e3 · rate`
(F2's TRACK_C); at 1e13 V/s that is 1e16/s, a 0.1 fs time constant that ngspice's
LTE control cannot resolve once the clamp releases near the target, so the step
shrinks until it underflows. The `HUGE` guard (1e300) in the same function was
written for an *infinite* rate (a zero transition time) and only triggers above
1e297, three hundred decades past where the loop already fails. `transition` with a
1e-14 … 1e-18 s rise time ran in the same decks; the difference was not traced. A
cap on the gain (the 1e9/s `TRACK_GAIN_INF` is already the
right value: beyond the rate any transient resolves, a limiter is a passthrough)
or a lower `HUGE` would close it.

The rate written as a literal in the model (`slew(cmp, 1e14)`) aborts the same way, and
`.option method=gear` (with or without `maxord=1`) does not change it.

**Kind.** Abort; a legal model on a legal deck. Anyone who writes `slew(x, 1e15)` or
`1e30` to mean "no limit" hits it.

*Fixed in [E-697](../../enhancements_doc/Enhancement-697.md).* In
`lower_rate_limited_track` a side whose rate is at or above 1e12 V/s is replaced by
`+inf` before the gain and the clamp are formed, so it takes the infinite-rate path
the loop already had (no clamp, the fixed 1e9/s gain); per side, so an asymmetric
`transition` keeps its finite edge; rates at or below 1e12 unchanged. `transedge`
pins 1e13, 1e30 and a 0.1 ps rise; every row of the table above runs.

## Smaller notes (not pursued)

- **`--cache-dir` must exist.** `-b --cache-dir cache` on a missing directory is
  "invalid value 'cache' for '--cache-dir <DIR>': No such file or directory"; a cache
  directory is the one path the compiler could create. `-b` refuses `-o` ("cannot be
  used with"), by design, and the cache keys on the include contents, `-D`, `-O` and
  `-A` correctly (`hunt2/p7.py`).
- **`inf` as an expression** (`parameter real p = inf;`) gets the right parse error
  ("unexpected token 'inf'; expected an expression") and then a knock-on "the default
  of parameter 'p' overflows to infinity" for the same token (`hunt2/p35.py`).
- **A module with no ports** compiles without a word; no ngspice line can instantiate
  it (`n1 m` → "could not find a valid modelname"). A note at compile time would save
  the round trip (`hunt2/p15.py`).
- **`V(l1.a)`** (a hierarchical reference, illegal in Verilog-A) is refused as "'l1__a'
  was not found in the current scope" — the mangled internal name, not the rule
  (`hunt2/p84.py`).
- **Two `` `else `` in one `` `ifdef ``** compile silently; **`` `define `` with no name**
  takes the next line's `module` as the macro name and fails there with "unexpected
  token identifier; expected 'discipline', 'nature' or 'module'" (`hunt2/p85.py`).
- **Duplicate `case` labels** (`1: …; 1: …;`) compile without a word; the second arm is
  unreachable (`hunt2/p76.py`).
- **String literals in integer contexts** are accepted in an assignment (`k = "5"` is
  53, `k = "abc"` is 6382179 — the packed ASCII of 1364-2005 2.6.3) and refused in
  arithmetic (`1 + "5"`: "expected integer value or real value but found string
  literal"); `s = +"a"` (unary plus on a string) is accepted. One rule or the other
  (`hunt2/p77.py`).
- **`"a" + "b"`** is refused as "type mismatch: invalid function arguments" — nothing
  points at `{"a", "b"}`, the LRM's concatenation (`hunt2/p76.py`).
- **`$strobe("")`, `$strobe()` and `$strobe("%s", "")`** print nothing; the LRM's
  `$strobe` with no arguments prints a newline (`hunt2/p82.py`).
- **`%ld`** prints `__.__d`: `%l` is consumed as the library-binding placeholder
  (`__.__`) and the `d` is literal; `%m` prints the instance name, `%t` prints the
  value — none of the three is documented for OSDI (`hunt2/p5b.py`).
- **`save all @n1[y]`** before a `tran` warns "'y' has no value yet — it is an
  operating-point variable and no analysis has computed one. It is recorded per point
  once an analysis runs" — the wording says the usage is fine, the "Warning:" label
  says it is not; every deck that records an opvar per point sees it.
- **`absdelay` interpolation error** for a 1 kHz sine: 2.3e-6 at a 1 µs step, 2.4e-4 at
  10 µs, 7.6e-3 at 50 µs, 1.6e-2 at 100 µs — quadratic in the step, as linear
  interpolation of the history gives; expected, recorded for reference (`hunt2/p67.py`).
- **`-o` to a read-only file** surfaces as the linker's "ld: can't write output file"
  plus "clang: error: linker command failed" before the compiler's own line.
- **`m=0` on an instance line** removes the device in silence (0 A, no line), where
  `m=-1` gets two warnings and a model-card `k=-1` is refused (`hunt2/p88.py`).
- **A `$fatal` label** has a double space: `OSDI(fatal) n1:  100% (at the operating point)`.

## Checked and clean, for the record

- **Command line:** `-o` to a directory refused ("is not a file"), `-o outdir/x` writes
  `x` as named, `-W L004` by number accepted, `-D FOO=1 + 2` with spaces and `-D FOO`
  (= 1), `-I` to a missing directory refused, `--target x86_64-*` refused with the
  three targets this binary carries, `-O 5`/`-O -1` refused, `-C foo=bar` warned and
  ignored, no file / two files / a missing file refused, an empty file and a file
  without a module refused with the unterminated-comment hint, a path with spaces
  and umlauts, `-D F=`G` located in the synthesized defines file with a note naming
  the argument, `-D F(x)=…` refused with the macro-name rule, `--dump-json --dry-run`
  writes `<stem>_<module>.json` (valid on every module without a message task).
- **Batch mode** recompiles on a changed include, `-D`, `-O`, `-A`, and reuses the entry
  on an identical rebuild.
- **Include resolution:** the includer's directory beats a decoy in the cwd; `-I`; a
  nested include relative to the nested file; an empty include; including a directory
  refused ("is a directory").
- **Bus ports:** `[0:3]`, `[3:0]`, `[1:4]`, a genvar loop over the bits (1+2+3+4 mA),
  bit-to-bit branches, named branches on bits, a parameter as the index, an internal
  bus (`n1#n[0]` 0.667 V), an out-of-range bit and the bus without a select refused,
  `a[1:2]` refused as a part-select.
- **Integer edges:** every entry of `hunt2/p3.py` and `p35.py` listed under "Dropped"
  and in F3; `-O 0` and `-O 3` produce identical results for both modules.
- **Two modules per file**, one instantiating the other (2 kΩ + 2 kΩ series → 0.25 mA),
  a case-differing third warned as unreachable (E-542) and skipped.
- **Formats:** `%d %5d %-5d %05d %x %o %b %c %h %X`, `%f %.2f %10.3f %-10.3e %g %G %E`,
  `%s %10s %-10s`, an integer through `%f %e %g`, extra arguments ignored, `%*d`,
  `%-*d`, `%.*f`, `%5.3d`, `%+d`, `% d`, `%#x`, `%#o`, `%0.0f`, `%.0e`, `%#.0f`,
  `%20.15g`, `%.40f`, `%1000d`, `%5.2s`, `%c` of 0/−1/955, `%x`/`%o`/`%b` of −1
  (`ffffffff`, `37777777777`, 32 ones), inf/−inf/nan, `100%%d`; a parameter string
  used as a format prints literally (`%d %s %n` on stdout, no injection); a trailing
  `%`, `%u`, `%z`, `%i`, `%q`, a real under `%d`, an integer under `%s`, too few
  arguments all refused at compile time.
- **Strings:** `$sformat(s, "%s!", s)` (aliasing) gives `abc!`; self copy and self
  doubling; ternary; `{}` concatenation; `==`, `!=`, `<`; `case` on a string parameter
  per model; appending in a loop; a string instance parameter (`imode="x y"` with a
  space) and a bad member of a `from {}` set refused with the set; an unquoted card
  value refused with "if it is meant as a string value, quote it".
- **Functions:** `exp`, `abs`, `max`, `ln`, `sqrt` as user names refused as keywords; a
  function named like the module works; one named like a port refused; `output`
  bound to a parameter, a literal or a probe refused; a `string` return and a
  `string` argument work; an integer function rounds its real result; an unassigned
  result is 0.
- **Operators:** `slew` with one rate (fall = −rise), zero, negative, both positive and
  a solution-dependent rate refused or handled per 4.5.9; `ddt(x, abstol)`;
  four-argument `idt` holds 0.5; `transition` with a solution-dependent delay
  (a 1 ms / 2 ms delay tracked per edge), five arguments, an integer input;
  negative rise or delay refused at compile time; `absdelay` with a negative `td`
  warned at run time and 0 used, a solution-dependent `maxdelay` refused, a
  `maxdelay` of 1e300 free; `I(<a>)` read (1 mA), contributed refused;
  `$realtime` accepted with the deprecation warning; `$discontinuity(−1)`.
- **Events:** the counts of `hunt2/p13.py` and `p19.py` — `cross` ×3 with enable, 0
  with enable 0, `cross or timer` 6, `above` 3, `timer(0.5m, 1m)` 10 over 10 ms and
  `timer(0, 1m)` 11 (t = 0 counts), a negative period one-shot, `timer(10m, 1m)` once
  at the end; direction 2, an event in a conditional and a nested event refused.
- **Jacobian through pass-through operators** — identical solution and iteration count
  (24) for the diode behind `slew`, `transition`, `absdelay(…, 0)`, `absdelay(…, td = 0)`,
  `last_crossing`; the small-signal gain of all three outputs is 1.0 from 1 Hz to 1 GHz.
- **Initial values:** `absdelay`, `transition`, `slew` and `laplace_nd` all start at
  the input's t = 0 value (1 for a source that is 1 at t = 0, 0 otherwise) with no
  ramp or filter transient; `analog initial` blocks compile and run.
- **An interrupted transition** (rising 0 → 1 over 100 µs, reversed at 0.5) returns
  to 0 in 50 µs, the slope 4.5.8's Figure 4-7 rule gives for a unit swing; `%m` in a
  child instance prints `n1.k1`.
- **Degenerate connections:** an instance with both terminals on ground, both on one
  node, or reversed runs `op`, `ac` and `tran` without a warning and with the right
  currents.
- **Loops:** a `while` fixed point, `repeat`/`for` with solution-dependent bounds, a
  50-step inner Newton (outer Newton 5 iterations, matches the reference to 1e-9);
  `while (1)` with `break` refused ("loop condition is always true").
- **Noise** as a flow, a potential, and a series potential source: 2.878895e-9 V/√Hz,
  the textbook 4kT·500 Ω.
- **Parameter defaults** from `$temperature`, `$mfactor`, `$abstime`, `$random`, `$vt`
  refused ("not allowed in constants"); `$simparam("gmin")` allowed with L015;
  `$param_given(p1)` in a default follows the card (3 unset, 2 set) and an
  instance-parameter dependency is promoted with L028 and read per instance.
- **`pre_osdi`** of a text file (dlopen's message), a missing file, the same file twice
  (skipped with the `-f` hint), two libraries with one module (the first kept), a
  `.va` file, and a card before any `pre_osdi` — each with a clear line.
- **Declarations:** duplicate direction, duplicate discipline, a port without a
  discipline, two branches of one name refused; a net, a variable, a branch and a
  parameter named like a module or a port coexist.
- **Preprocessor and literals:** `` `ifdef (A && B) ``, a lone `` `elsif ``, an extra
  `` `endif ``, an unterminated `` `ifdef ``, `` `include <…> `` refused; `` `undef `` of
  an unknown macro warned; `1e`, `1e+`, `0x10`, `1.5F`, `1.5meg` refused as malformed;
  `1.5f` = 1.5e-15; `1__0.5` = 10.5.

## Coverage, honestly

Not touched this hour: the Windows and Linux binaries (F1–F4 are in the compiler's
lowering and serializer, F5 in LLVM's own output; none is platform-specific, but
F5's line count and interleaving will differ with the thread count); `transition`
with a *continuous* input (the LRM leaves it undefined); a fix-size check of F2
under `.option reltol`/`trtol` variations (only the default tolerances were run);
`transition` events inside a child module; the JSON dump's content beyond validity
(the cfg, instructions and outputs were not cross-checked against the MIR); the
`verilogae` API; `--print-expansion` beyond a smoke test; noise in transient; the
IHP library; KLU against Sparse; the RF analyses; `$table_model`; the corner and
loop commands; hierarchy beyond the two-module file and the `V(l1.a)` refusal. F3
was not run on a model that overflows an integer power by accident — the 46341
threshold is the analysis, not a field report. The clock ran from 12:21 to 13:05
of probing, the write-up interleaved from 12:46; F7's minute-long timeouts and the
threshold scan were the last thing run.
