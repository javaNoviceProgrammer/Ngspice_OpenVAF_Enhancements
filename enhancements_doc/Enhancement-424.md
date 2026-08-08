# Enhancement-424 — the noise source that wasn't there

```verilog
for (k = 0; k < 1; k = k + 1)
    I(p, n) <+ white_noise(4e-21);     // contributed exactly nothing
```

`onoise_total` came back **bit-identical to a model with no noise source in it**.

And not "registered but zero" — the device registered **no source at all**.
Printing the per-source vectors in the `noise2` plot shows
`onoise_total_n1_unnamed0` for the working spelling and **no `n1` source
whatsoever** for the loop one. That distinction is what turned "the number looks
wrong" into a diagnosis.

It affected `white_noise`, `flicker_noise`, `noise_table` and `noise_table_log`,
in `for`, `while` and `repeat` alike — and `ac_stim` with them, which rides the
same small-signal pipeline (Enhancement-51) and went from mag **500 to 0**. It
was silent even under `-E all`, so it was not a suppressed lint.

## Why rejecting it is the fix, rather than making it work

The question was settled by the siblings, not by reasoning. Every other member of
this family was **already an error** in exactly this position:

```
error: analog operator 'ddt' is not allowed in loops
```

`ddt`, `idt`, `absdelay`, `transition` and `laplace_*` are all rejected inside a
loop (LRM 4.5.1). The noise builtins are simply not in `is_analog_operator()`, so
they fell past that check and were discarded further down instead of being
reported. Noise was the family member nobody had joined up.

**The restriction is loop-only, deliberately.** A noise source inside an `if`, an
`else` or a `case` is legitimate — gating noise on a mode flag is ordinary
compact-model practice — and works correctly today. That is why this uses its own
`is_small_signal_source()` predicate rather than being folded into
`is_analog_operator()`, which also drives the "not in a conditional" and "only in
the main analog block" checks. Folding it in would have broken working models.

**`generate` keeps working, and is the right answer** for a model that wants
per-finger or per-segment noise: a genvar loop unrolls at elaboration, so it
creates one source per iteration. The example suite checks that as a number — two
iterations give two sources and, after subtracting the resistor floor's power,
**exactly 2.000000000000× the noise power** of one.

## One behaviour change worth naming

Assigning a noise source to a variable inside a loop and contributing outside it:

```verilog
for (k = 0; k < 1; k = k + 1) t = white_noise(4e-21);
I(p, n) <+ t;
```

**used to work** — it contributed correctly. It is rejected now.

That is not an over-reach, and the check that says so is in the suite:
`t = ddt(...)`, `t = idt(...)` and `t = laplace_nd(...)` in exactly that position
are **already** rejected. The restriction has always been on the call site being
inside a loop, not on how the result is used. Leaving the noise spelling alone
would have kept one member of the family behaving differently from all the
others — which is precisely how this defect came about.

## `$finish` / `$stop` diagnostic level

IEEE 1364-2005 §17.1.2 gives the optional argument exactly three meanings: 0
prints nothing, 1 prints the time and location, 2 adds statistics. `$finish(3)`,
`$finish(99)`, `$finish(-1)` and `$stop(7)` select nothing at all and were
accepted in silence. Same shape as the `last_crossing` direction Enhancement-420
rejected, and checked the same way — literals only, so a runtime argument is left
alone.

## Verification

* **`examples/noiseloop_examples` — 36/36.** Every source × every loop form on the
  reject side; every legitimate placement on the accept side.
* **The accept half is measured as numbers, not silence.** A model with no noise
  registers no `n1` source and sits at the resistor floor; a plain source
  registers one and rises above it; the conditional spelling gives a total
  *identical* to the plain one; and the genvar spelling registers two sources at
  exactly twice the power.
* **164 real models — the 124-model VA_TEST industry corpus and the 40-model
  `integration_tests` corpus — compiled with the previous shipped binary and this
  one: ZERO differences.** No industry model puts a small-signal source in a
  run-time loop, so nothing real was silently losing noise, and rejecting it
  breaks nothing.
* `cargo test --features llvm18` **210/210**, no snapshot moved.
* **Full regression 341/341**, both solvers.

## Found by

A round-30 hunt over openvaf-r. Two things about how it was found are worth
keeping.

**The probe that mattered was `print all` in the `noise2` plot** — listing which
per-source vectors exist. Without it the evidence was "this number is smaller
than that one"; with it, the evidence was "the source was never created", which
is a different and much stronger claim.

**The noise deck cost two false readings first.** A single-frequency `noise` run
warns *"Noise measurement at a single frequency"* and produces **no total at
all** — every reading comes back empty, which reads exactly like "the noise
source contributes nothing". Measuring at the source node shorts the noise the
same way. Both are now recorded as standing harness traps.

The same round verified a large surface clean, and one result is worth recording:
analog-function `output`/`inout` arguments are correct **including the
derivative** — the same physics via a return value and via an output argument
agree exactly at DC and AC, with a reactive term. Module instantiation cycles
(self, two- and three-module) are all rejected; `(*type=…*)` warns on any unknown
value; and `$display`'s surplus arguments are printed per IEEE 1364 §17.1.1,
which is correct behaviour and not the asymmetry it first looked like.
