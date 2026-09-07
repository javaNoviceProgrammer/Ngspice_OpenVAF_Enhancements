# openvaf-r language semantics and runtime — a one-hour hunt

**Date:** 2026-09-07, 11:45–12:45 · **Commit under test:** `40fcc1c4` ·
**Compiler:** locally built `OpenVAF-master-20260610/target/opt/openvaf-r`
(OpenVAF-Reloaded 23.6.0, build of 2026-09-07 06:58) · **Simulator:** locally built
`ngspice-46/build/src/ngspice` (build of 2026-09-07 11:35, after Enhancement-577) ·
**Method:** black-box. Small Verilog-A modules were written for every suspicion,
compiled, loaded with `pre_osdi`, and their operating-point variables, small-signal
currents (`ac` at 1 kHz with a 1 V source, so `i(v1)` is minus the derivative) or
transient samples were compared with hand-computed LRM answers. Only one finding
needed the compiler source (`openvaf/mir_autodiff/src/builder.rs`, for F1). No fixes
were applied; every deck is inline so a run can be repeated.

The earlier compiler hunts (2026-09-04, 2026-09-05) covered the parser, generate
blocks, `$table_model`, strings, `$mfactor`, distributions in `osdimc` and the
`--target` path. This hour deliberately went elsewhere: arithmetic and shift
semantics, automatic differentiation at singular points, the analog operators
(`ddt`, `idt`, `idtmod`, `absdelay`, `transition`, `slew`, `laplace_*`,
`last_crossing`), the preprocessor, format strings, `$random`/`$rdist_*`, noise
sources, parameter dependencies and temperature, `$limit`, branch and contribution
rules, the constant folder against the runtime, and compile-time scaling.

**Result: seven defects confirmed with plain decks, none of them wrong-answer bugs in
ordinary models but two of them (F1, F2) able to break a legitimate model, plus
nineteen smaller observations.** The long list of things that came out exactly right
is in "Coverage, honestly" at the end, because it is most of the hour.

| # | finding | severity |
|---|---|---|
| [F1](#f1--hypot-has-a-nan-derivative-at-0-0-so-a-model-using-hypot-of-a-node-quantity-cannot-find-an-operating-point) | `hypot(x, y)` has a NaN derivative when both arguments are zero; a contribution `I(p,n) <+ k*hypot(V(p,n), 0)` at the V=0 DC initial guess makes every operating-point method fail. `abs`, `sqrt` and `pow` at zero are already guarded; `hypot` is not | **medium** — op failure for a legal model |
| [F2](#f2--random-and-rdist_-never-write-the-seed-back-and-re-seeding-mid-sequence-is-ignored) | `$random(seed)` and the `$rdist_*` functions never update the seed variable, assigning the seed again does not restart the sequence, and — found in the last minutes — a call site draws **once per instance and returns the same number on every later evaluation**, so `$rdist_uniform` inside a transient is a constant instead of a new draw per time step | **medium-high** — LRM 9.13 deviation, silent; a per-step random model is silently deterministic |
| [F3](#f3--the-constant-folder-drops-the-sign-of-negative-zero) | `-0.0`, `0.0 * -1.0` and `1.0/(-0.0)` are folded with the sign of zero lost: `1/(-0.0)` gives +inf and `atan2(0, -0.0)` gives 0 instead of π. The runtime path and `-zero` (negating a parameter) are right | low-medium — IEEE deviation, rare in practice |
| [F4](#f4--compile-time-is-quadratic-in-the-length-of-an-array) | compile time grows quadratically with the length of any array: a 10 000-entry real or integer array parameter takes 72 s (2 500 entries 5 s, 5 000 entries 19 s), a plain `real tab[0:9999]` module variable filled in a loop 68 s, and a 10 000-entry *instance* array parameter 375 s with a 5.8 MB object | **medium** — table-driven models with large arrays |
| [F5](#f5--10--00-folds-to-nan-silently-while-the-same-expression-at-run-time-is-a-fatal) | `1.0 % 0.0` in a constant expression folds to NaN with no diagnostic; the same expression at run time is a `$fatal`, and `ln(0.0)`, `sqrt(-1.0)`, `asin(2.0)` constants are compile-time errors | low — inconsistent diagnostics |
| [F6](#f6--x-x-and-t-format-specifiers-are-rejected-and-a-missing-argument-is-blamed-on-display) | `%x`, `%X` (IEEE 1364-2005 synonyms of `%h`) and `%t` are rejected as unknown format specifiers; a missing format argument is reported as "$display system task is missing an argument" even for `$strobe` and `$write` | low |
| [F7](#f7--lint-l026-fires-on-a-literal-format-string-whenever-a-string-argument-is-not-the-last-argument) | lint L026 ("this format string is not a literal, so it is printed rather than interpreted") fires on `$strobe("name=%s k=%g", nm, k)` although the format is a literal and is interpreted correctly; the trigger is a string-typed argument that is not the last argument | low — false-positive warning |

## What was read and run

Every probe lives in a scratch directory (`hunt/*.va`, `hunt/syn/*.va`,
`hunt/stress/*.va`) driven by a 30-line helper that compiles a module, generates a
deck with one instance across a 1 V source, runs `op` and prints every operating-point
variable declared with a `desc` attribute. About 120 modules were compiled and 90 of
them run. The compiler source was opened once, for the derivative rules in
`openvaf/mir_autodiff/src/builder.rs` (F1 and the `pow` regularisation noted under
Obs B).

## F1 — `hypot` has a NaN derivative at (0, 0), so a model using `hypot` of a node quantity cannot find an operating point

```verilog
`include "disciplines.vams"
module sing(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter integer sel=1;
real x, f;
analog begin
  x = V(p,n);
  case (sel)
    4: f = abs(x);
    6: f = hypot(x, 0.0);
    7: f = sqrt(x*x);
    16: f = sqrt(x);
    default: f = x;
  endcase
  I(p,n) <+ f * 1e-3;
end
endmodule
```

```
* sing one
.model m sing
V1 p1 0 dc 0 ac 1
N1 p1 0 m sel=6
.control
pre_osdi sing.osdi
op
ac lin 1 1k 1k
print i(v1)
.endc
.end
```

With `sel=6` the operating point fails outright ("Dynamic gmin stepping failed",
"True gmin stepping failed", "source stepping failed", "The operating point could not
be simulated successfully"). Every other selector at V = 0 solves: `abs` gives a
derivative of 1, `sqrt(x*x)` 0, `sqrt(x)` a large finite number, `pow(x, 2.0)` 2e-18.

**Root cause.** `builder.rs` around line 868 implements
`d/du hypot(x,y) = (x*x' + y*y') / hypot(x,y)`, which is 0/0 = NaN when both
arguments are zero. The NaN lands in the Jacobian and poisons the whole matrix. The
same singularity was already regularised for `sqrt` (Enhancement-261) and for `pow`
(the `x + 1e-18` shift documented in the comment above `Opcode::Pow`); `hypot` was left
out. V = 0 is ngspice's DC initial guess, so any model that takes `hypot` of a node
voltage or branch current that starts at zero hits this on the very first Newton
iteration.

**Fix direction.** Divide by `hypot(x,y) + 1e-18` (matching the `pow` guard), or select
a zero derivative when `hypot(x,y) == 0`. The value path is untouched either way.

## F2 — `$random` and `$rdist_*` never write the seed back, and re-seeding mid-sequence is ignored

```verilog
`include "disciplines.vams"
module seed(p,n); inout p,n; electrical p,n;
(* type="instance" *) parameter integer s = 7;
integer sv, i;
(*desc="random first"*) real q1; (*desc="random second"*) real q2; (*desc="seed var after"*) real q3;
(*desc="rdist_uniform"*) real q4; (*desc="seed var after uniform"*) real q5;
analog begin
  @(initial_step) begin
    sv = s; i = $random(sv); q1 = i; i = $random(sv); q2 = i; q3 = sv;
    sv = s; q4 = $rdist_uniform(sv, 0.0, 1.0); q5 = sv;
  end
  I(p,n) <+ V(p,n)/1k;
end
endmodule
```

```
* seed
.model m seed
V1 p1 0 1
N1 p1 0 m s=7
N2 p1 0 m s=7
N3 p1 0 m s=8
.control
pre_osdi seed.osdi
op
print @n1[q1] @n2[q1] @n3[q1] @n1[q2] @n1[q3] @n1[q4] @n1[q5]
.endc
.end
```

Output: `q1` is identical for `n1` and `n2` (seed 7) and different for `n3` (seed 8),
`q2` differs from `q1`, and `q3 = q5 = 7`: the seed variable is read once and never
written. A second probe (`rnd.va`) did `s0 = 7; a = $random(s0); s0 = 7; b = $random(s0);`
and got `a != b`, so assigning the seed again does not restart the sequence either;
the state is per call site. LRM 9.13 defines the seed as an inout integer variable
that each call updates so that the sequence can be continued, stored or restarted.
Run-to-run and instance-to-instance determinism is fine, `$rdist_normal(seed, 3.0,
0.0)` returns exactly 3, and all degenerate arguments (negative sigma, start above
end, non-positive mean, zero degrees of freedom, zero Erlang stages,
`$dist_uniform(seed, 5, 5)`) are compile-time errors with clear messages.

**Fix direction.** Store the advanced generator state back into the seed variable after
each call and seed from the variable's current value on every call, so the LRM's
sequence contract holds; a fresh draw per evaluation would then follow naturally.

**Late addition (12:37).** `rtr.va` draws `r = $rdist_uniform(seed, -1.0, 1.0)` on
every evaluation and contributes `I(p,n) <+ V(p,n)*1e-3*(1 + 0.5*r)`: the operating
point converges (which it could not if the draw changed per Newton iteration), and in
a 2 µs transient `i(v1)` at samples 10 and 20 equals the operating-point value to
nine digits. So a call site draws exactly once per instance and then returns the same
number for the rest of the run; only different call sites (and different seeds) give
different numbers. Together with the seed never being written back this means a model
that expects a fresh random number per time step, as LRM 9.13 promises, silently gets
a constant. The same holds for plain `$random(seed)` and for `$arandom(seed)`: over a
108-point transient (`rtr2.va`, values written with `wrdata`) each has exactly one
distinct value. For `$arandom` a per-instance constant is the intended Monte-Carlo
meaning; for `$random` and `$rdist_*` it is not. Whether the per-site freeze is a
deliberate convention or an accident of how the hidden state is keyed, it is not
documented and it differs from the LRM.


## F3 — the constant folder drops the sign of negative zero

```verilog
`include "disciplines.vams"
module nz0(p,n); inout p,n; electrical p,n;
parameter real zero = 0.0;
parameter real cneg = -0.0;
parameter real cneg2 = -zero;
parameter real cneg3 = 0.0 * -1.0;
(*desc="1/(-0.0 literal)"*) real q1; (*desc="1/(-zero)"*) real q2; (*desc="1/(0*-1)"*) real q3;
(*desc="1/(-zero runtime)"*) real q4; (*desc="atan2(0,-0.0)"*) real q5; (*desc="atan2(0,-zero) rt"*) real q6;
(*desc="1/(-0.0 inline)"*) real q7;
real r;
analog begin
  q1 = 1.0/cneg; q2 = 1.0/cneg2; q3 = 1.0/cneg3;
  r = -zero; q4 = 1.0/r;
  q5 = atan2(0.0, cneg); q6 = atan2(zero, r);
  q7 = 1.0/(-0.0);
  I(p,n) <+ V(p,n)/1k;
end
endmodule
```

Output: `q1 = +inf`, `q3 = +inf`, `q7 = +inf`, `q5 = 0` where IEEE 754 gives −inf,
−inf, −inf and π. The runtime path is right (`q4 = -inf`, `q6 = 3.141593`) and so is
`-zero` on a parameter (`q2 = -inf`), so the loss happens only when a literal or a
constant-times-constant product is folded. Rare in device models, but `atan2` on a
folded zero is exactly where a phase computation would trip over it.

## F4 — compile time is quadratic in the length of an array

Generated modules with a single 10 000-entry array in four forms, plus a model
parameter at three sizes:

| module | array | compile | object size |
|---|---|---|---|
| `arr2500l` | `parameter real tab[0:2499]`, summed in a loop | 5.1 s | 0.83 MB |
| `arr5000l` | `parameter real tab[0:4999]`, summed in a loop | 19.3 s | 1.6 MB |
| `bigarr` | `parameter real tab[0:9999]`, summed in a loop | 75.9 s | 3.1 MB |
| `arr10000n` | same, only `tab[5] + tab[k]` read | 71.7 s | 3.1 MB |
| `intarr` | `parameter integer tab[0:9999]`, two reads | 72.0 s | 2.9 MB |
| `locarr` | `real tab[0:9999]` module variable, filled by a `for` loop, two reads | 67.8 s | 0.95 MB |
| `instarr` | `(* type="instance" *) parameter real tab[0:9999]`, two reads | 375.2 s | 5.8 MB |

Four times the time for twice the entries, the same whether the array is a real or
integer parameter default, a plain module variable with no constant data at all, or
merely read twice; and an instance parameter costs another factor of five. So the
cost is in how the compiler represents an array of N elements (something walks or
copies the whole aggregate once per element), not in the constant data or in the code
that uses it. For contrast a 300-node resistor ladder compiles in 4 s, a 500-branch
`if/else if` chain in 0.1 s and a 2 000-label `case` in 0.8 s. Not profiled this
hour. Table-driven models that carry measured curves as arrays, and any model with
a per-instance array, are the ones that pay.

## F5 — `1.0 % 0.0` folds to NaN silently while the same expression at run time is a `$fatal`

```verilog
parameter real c14 = 1.0 % 0.0;        // compiles; c14 = nan
parameter real zero = 0.0, one = 1.0;
...  r14 = one % zero;                 // OSDI(fatal): %: the second operand (the modulus divisor) is zero
```

`ln(0.0)`, `sqrt(-1.0)` and `asin(2.0)` in a parameter default are compile-time errors
("the result would be NaN"), and their run-time counterparts are fatal, so the
compile-time and run-time checks agree there; the real modulus is the one operator
where they disagree. `1.0/0.0` folds to inf and runs to inf, `0.0**0.0` is 1 both
ways, `1e308*10` is inf both ways, `atan2(0,0)` is 0 both ways, `exp(1000)` is inf
both ways.

## F6 — `%x`, `%X` and `%t` format specifiers are rejected, and a missing argument is blamed on `$display`

```verilog
$strobe("E: %x %o %b %h %X", 255, 8, 5, 255, 255);   // error: failed to parse format specifier; unexpected character x
$strobe("H: %r %t %v", x, x, x);                       // error: ... unexpected character t (and v)
$strobe("C: no args %d");                              // error: $display system task is missing an argument
```

IEEE 1364-2005 17.1.1.2, which Verilog-AMS 2.4 inherits, lists `%x` as a synonym of
`%h`; `%t` is the time format. Everything else printed correctly: `%d %f %e %g %s %c
%o %b %h %H %r %m %l %%`, widths, precision, `-` and `0` flags, `$write` without a
newline, `$monitor`, `$debug`, a bare string argument, and a `$strobe` with only a
real argument.

## F7 — lint L026 fires on a literal format string whenever a string argument is not the last argument

```verilog
parameter string nm = "abc"; parameter real k = 2.0; string s;
$strobe("name=%s k=%g", nm, k);   // warning[L026] ... not a literal   (prints "name=abc k=2" correctly)
$strobe("%s %s", nm, nm);         // warning[L026]
$strobe("a=%s b=%g", s, k);       // warning[L026]
$strobe("k=%g name=%s", k, nm);   // clean
$strobe("a=%s %g", "lit", k);     // clean
$strobe("name=%s", nm);           // clean
```

The format string is a literal in every case and every case prints correctly; the
warning appears exactly when a string *variable or parameter* argument is followed
by another argument, so the lint is looking at that argument as if it were a
nested format string. Harmless, but it fires on the most common way of printing a
string parameter next to a number, and models compiled with `--deny` on lints would
fail on it.

## Status after the fixes (2026-09-07, later the same day)

F5, F6 and F7 are closed by [Enhancement-578](../../enhancements_doc/Enhancement-578.md),
pinned by `examples/fmtdiag_examples` (40 checks, 16 of them passing against the shipped
compiler): `%x`/`%X`/`%t`/`%T` are conversions, a missing format argument names its task,
L026 steps over the operands a literal format consumes, and a constant zero real modulus
divisor is a compile error naming LRM 4.2.4.

F3 and F4 are closed by [Enhancement-579](../../enhancements_doc/Enhancement-579.md),
pinned by `examples/arrayscale_examples` (29 checks): the constant table no longer
aliases −0.0 onto +0.0, and the quadratic compile time turned out to be a chain of
per-element CFG blocks — a three-block `if` per element for dynamic reads and writes
and for retained-variable init, one per parameter in the setup function, three and
four per parameter in the OSDI access and given-query functions — replaced by a new
branchless `select` instruction in MIR, table-driven access and given-query
functions, and `-O0` setup modules above 1024 parameters. A 10,000-entry model array
parameter compiles in 4.2 s (was 71 s), an instance array in 5.9 s (was 375–410 s); a
10,000-element local array rewritten in a loop each evaluation still takes 26 s (was
68 s), which is LLVM optimising a 10,000-phi loop in the evaluation function.
F1 (`hypot`) and F2 (`$random`) stand as written.

## Smaller notes (not pursued)

- **Obs A** — `-7 >> 1` gives 2147483644. That is LRM-correct (4.2.10 makes `>>` a
  logical shift); `-7 >>> 1` gives −4 with a warning that the arithmetic shift is an
  openvaf extension in analog blocks. `1 << 33` warns "shift distance outside 0..=31"
  and gives 0. `a >> 32` and `a >> -1` give 0.
- **Obs B** — the `pow` derivative is evaluated at `x + 1e-18` (deliberate, per the
  comment in `builder.rs`), so `d/dV pow(V, 2)` at V = 0 reads 2e-18 and `d/dV sqrt(V)`
  at 0 reads 5e8. Harmless, and it is what keeps `pow(V, frac)` solvable.
- **Obs C** — run-time `$fatal` for `a % 0` (integers, LRM 4.2.4) and for
  `pow(-8, 1/3)` ("the base has no real power for this exponent"), and compile-time
  refusal of the constant forms. By design; note that after a fatal every
  operating-point variable of the deck is unreadable, which is expected.
- **Obs D** — `idt(0.0)` (no initial condition) yields "singular matrix: check node
  n1#implicit_equation_0". Degenerate input, but a legal expression produces a singular
  matrix rather than 0.
- **Obs E** — (ngspice side) when the operating point falls back to the ramped
  transient op (as it did because of Obs D), every `idt`/`idtmod` state carries the
  1e-5 s of ramp time into the transient: `idt(1.0, 0.5)` starts at 0.50001. Without
  the fallback the integrator is exact (`idt(1.0, 0.5) = t + 0.5` to all digits).
- **Obs F** — `absdelay(x, 1u, 0.5u)` (delay above `maxdelay`) silently clamps the
  delay to 0.5 µs; `laplace_nd` with a zero highest-order denominator coefficient is a
  run-time fatal; an improper filter (numerator order above denominator order) is a
  clear compile-time error; `laplace_zp(x, {}, ...)` with an empty zero list is a parse
  error ("empty concatenation `{}` is not allowed") and `laplace_np` is the workaround.
- **Obs G** — the integer literal `3000000000` in a parameter default saturates to
  2147483647 with no diagnostic; `2147483647 + 1` folds to −2147483648. Same family as
  the 2026-09-04 F5.
- **Obs H** — `electrical.potential.abstol` and `Voltage.abstol` are rejected
  ("expected a scope but found discipline"); `p.potential.abstol` works and reads 1e-6.
- **Obs I** — a model that declares `(* type="instance" *) parameter real m` or `temp`
  silently takes over ngspice's multiplier and per-instance temperature: with
  `N1 ... m=2 temp=50` the Verilog-A parameters get the values, `$mfactor` stays 1 and
  `$temperature` stays 300.15 K, and there is no lint. `dtemp`, `l`, `area`, `off` and
  `ic` pass through as expected.
- **Obs J** — (ngspice side) an operating-point variable literally named `i` triggers
  "instance parameter 'i' is declared more than once differing only in case" from
  `osdiinit.c`, although nothing differs in case; it collides with a loader-provided
  `i` keyword. Cosmetic.
- **Obs K** — a nature declared without `abstol` compiles silently; LRM 3.6.2 makes
  `abstol` a required attribute.
- **Obs L** — (ngspice side) a string parameter must be double-quoted on the model or
  instance line: `mode=slow` is a hard exit ("Error in netlist line no. 3"), and an
  out-of-list value reports `range from "fast" from "slow"!` (wording). `mode="slow"`
  works on both `.model` and instance lines and `alter @n2[mode]="slow"` works;
  `print @n1[mode]` reports "can not handle string value" (ngspice cannot print string
  parameters).
- **Obs M** — the arithmetic-shift `>>>`/`<<<` warning and the `1364-2005` keyword-set
  warning ("treated as VAMS-2023") are noisy but correct.
- **Obs N** — `$bound_step(0.0)` and a negative constant bound are compile-time errors;
  a run-time zero bound (`$bound_step(x*1e-6)` at x = 0) is silently ignored; the
  E-series guards for `$bound_step(1e-300)` and a `$discontinuity` on every evaluation
  fire and keep the run finite (26 s and 22 s for an 8 µs transient, which is the
  guard's floor of 8e-12 s).

- **Obs O** — an array cannot be passed to an analog function argument declared as
  an array (`input a; real a[0:3];` then `sum4(t)` gives "'t' requires a bit-select
  [i]"); whether the LRM allows array arguments to analog functions is not settled
  here, so this is a note, not a finding.
- **Obs P** — run-time array indexing out of range (`tab[idx]` with an instance
  parameter `idx` of 4, −1 or 1 000 000 on a four-element array) is memory-safe: the
  read returns the first element, the write is dropped, and there is no diagnostic.
  A non-integral value for an integer parameter is rounded with a warning from the
  loader. (Compile-time constant indices out of range were covered on 2026-09-05.)

- **Obs Q** — `$info`, `$warning`, `$error` print with their severity and continue;
  `$fatal(0, ...)` aborts the operating point with its message; `$finish` and `$stop`
  complete and report the operating point with a note. A bare `$fatal` or `$fatal(1)`
  (no message) aborts with "see the OSDI(fatal) message above for the cause" although
  no OSDI(fatal) line was printed. Cosmetic.

- **Obs R** — (ngspice side) `$simparam("tnom")` returns 27, the nominal temperature
  in Celsius, which is upstream ngspice's deliberate convention (`CKTnomTemp -
  CONSTCtoK`, noted in Enhancement-394); LRM 2.4 Table 9-27 describes `tnom` in
  Kelvin, so a model that feeds it into a Kelvin formula gets 27 K. Worth settling
  against the LRM text; not a compiler matter. `gmin`, `gdev`, `iteration` (3 at the
  op, 119 at the end of a 5 ns transient), `sourceScaleFactor`, `simulatorVersion`
  (46) and `scale` are provided; `timeStep`, `maxStep`, `tstart`, `tstop` and `shrink`
  fall back to the caller's default.

- **Obs S** — (ngspice side) omitting a terminal on the instance line (`N1 p 0 m` for
  a three-port module whose model guards its third port with `$port_connected(q)`)
  warns "1 of the 3 terminals ... are not connected" and then walks through
  "singular matrix: check node n1#q", gmin stepping and source stepping failures
  before the ramped transient op finally solves it; the result (`$port_connected`
  false, the guarded branch absent) is right. The loader creates an internal node for
  the missing terminal that nothing touches, and Enhancement-575's DC-path walk skips
  `#` internal names, so the node gets no gmin. Grounding or gmin-tying an unconnected
  terminal in the loader would remove the detour.

## Coverage, honestly

Verified correct this hour (each with a deck, values matched by hand):

- **Arithmetic and conversion:** integer division and modulus signs (`-7/2 = -3`,
  `-7 % 2 = -1`, `7 % -2 = 1`), real modulus (`2.5 % 1.0 = 0.5`, `-2.5 % 1.0 = -0.5`),
  `~0`, `1 << 31`, `**` with integer and negative exponents, `$rtoi(-2.5) = -2`,
  `floor(-2.5) = -3`, `min(1, 2.5)`, `0**0`, `pow(0.0, 0.5)`, real-to-integer rounding
  (`integer i = 2.5` gives 3, `-2.5` gives −3, `1e10` saturates), `parameter integer
  a = 2.7` rounds to 3, untyped parameters take the type of their default, integer
  literal scale factors and every real scale factor (`K M m u f a T G p n k`), `1_000`,
  `100_000.5`, `1E-3`, `1.5e+2`, `'h1F`, `8'd255`, `3.` rejected, `.5` rejected.
- **Automatic differentiation:** `pow(x, 2.0)`, `x ** 2.0`, `pow(x, e)`, `pow(x, x+2)`,
  `pow(x, 3)`, `pow(2.0, x)`, `abs`, `max`/`min` with ties (`max(x, x)`,
  `min(x, 2x)`), `sqrt(x*x)`, `pow(abs(x), 1.5)`, `atan2(x, 0)`, `floor`, `x*ln(x+1)`,
  `pow(x*x, 0.5)`, `limexp` (its converged derivative equals `exp`'s, as it must),
  `ddx` of `x³` and nested `ddx`, `ddx` with respect to a branch flow, `$table_model`
  slopes, all at x = 0 and x = 0.5.
- **Analog operators (transient, 20 cases):** `ddt(1.0) = 0`, `idt(1.0, 0.5) = t + 0.5`,
  `idt(x)`, `idt` with reset and with the four-argument form, `idtmod`, `absdelay` with
  zero and non-zero delays, `transition` with zero and non-zero times and with a
  continuous input, `slew`, `ddt(x*x)`, `last_crossing` (−1 before the first crossing,
  then the crossing times to the sample), `ddx(x*x, V(p)) = 2x`, `laplace_nd` as an
  integrator and with a zero numerator, `laplace_np` and `laplace_zp` normalisation
  (`(1 - s/p)` form, unity DC gain), a `(1 + 1e-6 s)/(1 + 1e-7 s)` lead network, and an
  undamped `1/(1 + 1e-12 s²)` resonator.
- **Placement rules:** `ddt` inside a parameter-only `if` or `case` and inside a genvar
  loop is accepted; inside a node-dependent condition, a mixed condition, an integer
  loop, an analog function or an event block it is rejected with the LRM reason;
  contributions inside event blocks are rejected; recursive analog functions and
  module-variable access from a function are rejected.
- **Preprocessor:** macros with arguments, nested macros, line continuations, a string
  containing a comma as a macro body, redefinition (warned), `undef`,
  `ifdef/ifndef/elsif/else`, recursive macros (error, no hang), undefined macros,
  missing include files, `__FILE__`/`__LINE__`, a backtick inside a string literal
  (left alone), comments inside macro bodies, `-D` on the command line, `timescale`,
  `celldefine`, `default_nettype`, `resetall`, `begin_keywords`. Macro default
  arguments are SystemVerilog and rightly rejected.
- **Parameters and environment:** `from [0:1) exclude 0.5 exclude (0.7:0.8]`,
  `aliasparam` from the netlist, arrays sized by a parameter, replication `{2{1.0,
  2.0}}`, `'{...}` defaults, a parameter default depending on a model parameter that is
  overridden on the model card and on an instance parameter overridden on the instance
  line (`b = a*2`, `ib = ia*2`, `ic = ia + b` all follow the overrides), `$param_given`
  on model and instance parameters, `$port_connected`, `$mfactor` from `m=`,
  `$temperature` and `$vt` following `.option temp`, `$vt(300)`, `$simparam("gmin")`
  following `.option gmin`, `$simparam` with a default for an unknown name, `altermod`
  and `alter` between operating points, string parameters with a `from` list on model
  and instance lines, `paramset`, escaped identifiers, a real `for` loop variable,
  named-block variables shadowing module variables, variables retaining values across
  evaluations, uninitialised variables reading 0.
- **Branches and contributions:** named branches (`branch (p,n) b`, `branch (p) g`)
  adding with unnamed contributions, a port branch probe `I(<p>)`, contributions in a
  loop (four of them add), potential contributions through an internal node,
  conditional collapse (`V(p,m) <+ 0` when a resistance is zero), indirect assignment
  `V(m): V(m) == ...`, a zero-only contribution, a flow probe on an uncontributed
  branch (warned, shorted), `V(p,p)` rejected, a potential and a flow contribution on
  the same branch (warned; the flow one wins, per LRM), a voltage contribution against a
  voltage source (singular matrix from ngspice, as it must be), a thermal port with
  `Pwr(t)`, a user-defined nature and discipline, an electrical/thermal branch
  rejected as incompatible, `V(n,p)` sign, `analysis()` in `op`, `ac` and `tran`.
- **Noise:** `white_noise(0)`, a run-time negative PSD (silently contributes nothing),
  `flicker_noise` with exponents 0, −1 and 5, a voltage-dependent PSD, a one-point
  `noise_table`, all matching the analytic output spectrum with the source resistor's
  thermal floor; a negative constant PSD is a compile-time error.
- **`$limit`:** the built-in `pnjlim` and a user function `(vnew, vold, a, b)` both
  converge a diode deck; a user function with an output argument is rejected.
- **Malformed input:** empty right-hand side, missing `end`/`endmodule`, unknown
  discipline, port without discipline, undefined variable, CRLF line endings, a UTF-8
  BOM, a non-ASCII identifier, an empty file, 2 kB of random bytes, unterminated
  comment and string, three-argument `V(...)`, duplicate module, duplicate port, a
  20 000-term expression and 3 000 nested parentheses ("expression nests too deeply",
  no crash), a 5 000-character identifier — every one produced a clear diagnostic and
  no panic.

- **Late additions (12:29–12:33):** the AC small-signal path of `absdelay`
  (100 µs at 1 kHz reads −36°), `ddt`, `ddt(x²)`, `laplace_nd`, `laplace_zp` with a
  zero at the origin (the LRM's `s` factor), `slew`, `transition`; `analysis()`
  dependent conductances across `op`, `ac` and `tran` (the AC linearisation uses the
  `static` path, `analysis("dc")` is false in AC, `analysis("noise")` false in AC);
  `initial_step("ac"|"tran"|"dc")` and `final_step(...)` filters; `@(cross)` and
  `last_crossing` in a DC sweep (no crossings, −1); `transition` with a 2 µs delay,
  with 8 µs ramps longer than the pulse, and `absdelay` with a voltage-dependent delay;
  run-time parameter range violations on model and instance lines (clear messages,
  the integer form omits the offending value); `-D NAME="string"`, `-D` values,
  `-I` include directories, `-D` without a value (a type error, as it should be), a
  duplicate `-D` (warned); the two-argument `ddt(x, abstol)` form.

**Not covered:** `zi_*` filters (F8 of the 2026-09-04 hunt stands), `$table_model`
file inputs and 2-D interpolation (covered on 2026-09-05), hierarchical instantiation,
`--target`, noise in the `sp` analysis, `@(cross)` tolerances (the compiler says
"accepted but not honored"), and anything in the OSDI loader beyond what the decks
above touched. The array-parameter scaling (F4) was measured but not profiled.
