# Enhancement-468 — seven numbers that were wrong

Seven defects from a one-hour hunt over ngspice and OSDI. Two are wrong
*numbers* in code with no test coverage at all; the rest are measurements or
cards that answered instead of saying they could not.

Two further candidates from the same hunt are **not** here — re-verification
showed both were my own measurement error. See *Withdrawn*.

## 1. `psd` reported a total power set by the window, not the signal

A constant 1 V signal has total power exactly 1 V². `psd` reported:

| `specwindow` | before | after |
|---|---|---|
| `none` | **1.000000** | 1.000000 |
| `hanning` *(default)* | 1.499908 | **1.000000** |
| `hamming` | 1.362744 | **1.000000** |
| `blackman` | 1.726652 | **1.000000** |
| `gaussian` | 1.215261 | **1.000000** |

The rectangular case being exact is what identified the cause. `fft_windows`
scales every window for unit **coherent** gain, so that a sinusoid keeps its
amplitude in the spectra `fft` and `spec` produce — which is right for them. A
PSD sums **squared** bins, and a squared unit-coherent-gain window has power gain
Σw²/length, not 1. Normalising by `length²` therefore inflated the total by
exactly that ratio.

Zero padding inflated it again by N/length, because E-241 had corrected this
normalisation from `N²` to `length²` — the padding factor it removed belongs on
*one* of the two lengths, not neither. So the same signal reported **1.5 V² at
one stop time and 3.0 V² at another**, a total power that depended on where the
transient happened to end.

Parseval over the padded sequence gives Σ|X|² = N·Σ(x·w)², so the normalisation
is `N · Σw²`. For a rectangular window with no padding that is `length²`
identically — which is why the one case that was already right stays
bit-for-bit right.

`psd` has **no suite in the tree**, which is how this survived. `fourier`,
`spec`, `fft` and `.noise` integration were all checked against analytic values
during the hunt and are correct.

## 2. numparam's `**` and `^` dropped the sign of a negative base

```
.param {(-2)**1}  ->  2      (correct -2)
.param {(-2)**3}  ->  8      (correct -8)
.param {(-3)**3}  -> 27      (correct -27)
```

It computed |base|^exp. Two oracles inside the same simulator disagreed with it:
`pow(-2,3)` in the *same* evaluator returns −8, and `**` in a B-source returns
−8.

**Enhancement-446 fixed exactly this defect, in the other evaluator.** Its suite
builds its decks as `B1 nb 0 v={expr}`, so it exercises `ptfuncs.c` and never
reaches `xpressn.c` — the same simulator answered −8 for a B-source and +8 for a
`.param`. The rule here is copied from `pt_pow_default` deliberately, so the two
cannot drift again: a negative base has a real answer only for an integer
exponent and keeps its sign there; for a non-integer exponent the historical
magnitude is returned rather than NaN, because a NaN poisons the Newton
Jacobian. The suite asserts the two evaluators agree, not merely that each is
right.

## 3. Measurements over a nested `.dc`

A nested sweep restarts its inner variable at every outer step, so the scale
reads `0,1,2,0,1,2,...`. The window measurements integrate along it with a
signed trapezoid, and every restart subtracts what the previous curve added:

| | before | correct |
|---|---|---|
| `INTEG` | 0.5 | — |
| `AVG` | 0.25 | — |
| `RMS` | *"out of interval"* | — |
| `MAX`/`MIN` | 1.0 / 0.0 ✓ | 1.0 / 0.0 |

0.25 is neither the average of any single curve (0.5 / 0.3333 / 0.25) nor the
mean of the nine points (0.3611). One plot produced a silent wrong number, a
refusal, and two correct answers, all from one code path.

There is no defensible single number — an average "over the sweep" has to say
which sweep — so `avg`, `rms` and `integ` now refuse and explain, and `max`/`min`
are left working. A single sweep is untouched: avg 0.5, integ 1.0, rms √⅓, all
exact.

## 4. `meas dc` measured plots that were not dc — a regression from E-467

E-467 added a fallback to the plot's own default scale so that a future sweep
kind would still be measurable. It asked only *"is there a default scale?"*,
which is true of every plot, so `meas dc` stopped refusing a transient or ac plot
and silently measured it instead, returning exactly what `meas tran` returns.
The mirror cases went on refusing correctly, so one of four analysis names had
quietly become "measure whatever is current".

The fallback is now gated on the plot actually being a dc plot. E-467's own case
— a `.dc` of a device parameter, whose scale is `param-sweep` — still works.

## 5. `sens` reported `nan`

The engine perturbs every settable parameter by a relative step, or by an
absolute one when the value is zero. Zero is also how several models spell "this
effect is off", so the perturbation can switch a branch on with a degenerate
parameter. `sens v(mid)` on an ordinary diode reported `d1:ikf = nan` for every
model that leaves `ikf` at its default — it was the only non-finite number
produced across op, dc, ac, tran, noise, disto, tf and sens, and across eight
device types.

A NaN there is worse than a missing number: it propagates through any sum or plot
built from the table and reads as a result rather than an undefined derivative.
The entry now reads 0 and says once, naming the parameter, that the derivative is
undefined at this operating point. Every finite entry beside it is unchanged.

## 6. Duplicate parameters were silent for built-in devices

```
.model dm d is=1e-14 is=9e-14     ->  i(v1) -5.67e-03 becomes -5.10e-02
D1 in 0 dm area=1 area=4          ->  area 4, current x4
```

Both took the last value with nothing said — while a duplicate `.model` **card**
is reported ("model 'dm' is already defined"), and a duplicate `.subckt` is
reported too.

Enhancement-395 built exactly this check and scoped it to OSDI, because
`aliasparam` is a Verilog-A construct. The defect it protects against is not
Verilog-A's. Extending it needed one more change than removing the gate:
**built-in parameter ids are enum tags, not dense indices** — a diode's model ids
start at `DIO_MOD_LEVEL = 100` — so the id-indexed array E-395 used tracked
nothing at all here. The tracker now keeps a short list of the ids already
written and searches it, which does not care how they are numbered. A ten-
parameter MOSFET model and an ordinary deck stay silent.

## 7. The XSPICE `limit` block stopped limiting

A negative `limit_range` widens the linear region instead of narrowing it: with
limits ±1 and `limit_range=-5` the thresholds became ±6, so an input of 1.5
passed straight through while the model still declared an upper limit of 1.
Ranges of 0.01, 0.1, 0 and −0.01 all clamp correctly, so it was silent on
everything except a value large enough to swallow the limits. An inverted pair
(lower above upper) was accepted too.

`CLIMIT`, the sibling model, tests its linear range and refuses; `LIMIT` tested
nothing. A negative range is now clamped to zero — hard limiting at the bounds
the deck asked for, the only reading that still honours them — and both faults
are reported with CLIMIT's message convention.

**Note on measurement**: this was first measured against the *installed*
`/usr/local/lib/ngspice/analog.cm`, dated February 2025, because that is what a
bare `ngspice` loads. The repo's own freshly built code model had the same
defect; the fix and its suite run against the local build, as `_setup.py`
arranges.

## Withdrawn

Two candidates were **re-verified and are not defects** — both were my own
measurement error, in the same way:

- **`sens` was said to report all zeros for instance-valued passives**, and to
  omit independent sources. It does neither. The **principal** parameter is
  reported under the bare instance name, so a resistor's own sensitivity is
  `r1`, not `r1:resistance`, and the source's is `v1`. Measured:
  `r1 = -2.499998e-04` and `v1 = 0.5000000000`, both exactly analytic; the ac
  case is likewise nonzero. The grep behind the finding matched only
  colon-separated **model** parameters, so it saw the model zeros and concluded
  the table was empty. The claim that an OSDI device works while the built-in
  beside it reports zeros was the same artifact — both work.
- **A bare `.probe` was said to be silently ignored.** It emits
  `Note: Empty .probe command, treated as .probe alli`; the filter that found it
  "silent" did not include `Note:` lines.

A third was caught mid-hunt before it was ever written down: a NaN sweep that
matched my own deck **title**, "nan scan", rather than any number.

## Verification

`examples/mathguard_examples/verify_mathguard.py` — **57/57**, both solvers.
Every check is a differential against an analytic value or an oracle already in
the tree, and each records what the pre-fix binary produced.

Deliberately pinned unchanged: the rectangular-window psd case that was already
right; positive bases in both evaluators; the two evaluators agreeing with each
other; a single dc sweep's avg/integ/rms; `meas tran` on its own plot and E-467's
device-parameter `.dc`; every finite `sens` entry beside the NaN, a model that
does set `ikf`, and an ordinary resistor's own sensitivity; an ordinary deck and
a ten-parameter MOSFET model raising no duplicate warning; valued `.ic` and
`.nodeset`, and a bad node name reporting as before.

Full regression: see the change report. ngspice-only — the compiler is untouched.
