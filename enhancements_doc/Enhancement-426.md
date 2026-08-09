# Enhancement-426 — inputs that were never checked

A node name, a sweep argument, a temperature, a tolerance, a multiplier and a
number. Each was taken at face value, and the answer that followed was reported
with complete confidence — or blamed on something else entirely.

Thirteen findings went in. Five came back out on evidence, three more were
narrowed, and the review that did the narrowing turned up a **SIGSEGV**, a heap
**write** overflow, a **13,400x** silent iteration blow-up, and a latent bug in
one of this repo's own example decks.

## A node that does not exist

Enhancement-349 already refuses `.tf v(out) v1` when `out` is not a node. It
gated the check on `CKTisSetup`, and its own write-up states the assumption:
*"From the `.control` section the circuit is already set up."*

That is false for the **first** analysis of a session. Nothing has run, so
`CKTsetup()` has not run either, and the typo was still invented as a node:

```
tf   v(nosuch) v1      transfer_function = 0.0        no diagnostic
tf   v(a,nosuch) v1    transfer_function = 1.0        no diagnostic
sens v(nosuch)         every sensitivity = -0.0       no diagnostic
noise v(nosuch) ...    onoise_total      = 0.0        no diagnostic
```

The same typo after any `op` was diagnosed correctly, which is exactly what hid
it for so long. `tf v(a,nosuch)` is the sharpest form: mistype the *second* node
of a differential output and you get back the most plausible number there is.

A card that `if_run()` synthesised from a `.control` command is, by construction,
not deck parsing — whatever `CKTsetup()` has or has not done. That path now says
so explicitly instead of inferring it.

### The phantom node was also an out-of-bounds heap access

`CKTrhs` and `CKTrhsOld` are sized from `SMPmatSize()`, which counts only nodes a
device actually stamped; the analyses index them with `node->number`, drawn from
`CKTmaxEqNum`, which counts the phantom too. ASAN reports a heap-buffer-overflow
read at `tfanal.c:121` and `noisean.c:465` against the buffer allocated in
`nireinit.c:37`, and `tfanal.c:153-154` **writes** through the same index. On a
one-resistor deck the shipped binary printed what it read:

```
transfer_function = 3.999110e+252
```

The parser fix cannot close this half: a **deck** card may legitimately precede
the devices that define its nodes, so creation has to stay allowed there. A
bounds check at the analysis entry is the last line of defence, and it leaves the
forward-reference case (E-349's own regression check) working.

### It found a real bug in this repo

`examples/rfpss_examples` ran `.pss 1meg 20u 1 1024 8 50 5m uic` on a circuit
whose nodes are `in`, `a`, `out` and `0`. There is no node `1`. ngspice invented
it, and the PSS retained-operating-point self-check had been printing

```
retained op-point self-check: osc-node swing [0, 0] over the period
```

— a flat zero — ever since, unnoticed, because the check only asserted that the
card auto-ran. The node is now `out`, where the swing is `[-2e-09, 0.353684]`.

## Sweep arguments: `.tran` validates, almost nothing else did

`.tran` rejects a zero or negative tstep and tstop by name. `.ac` did not merely
accept a bad value — it **substituted a default and ran a different sweep**,
reporting all of it with one generic warning:

| written | actually run |
|---|---|
| `ac dec 10 100k 1k` | 31 points, 1e5 … 1e8 |
| `ac dec 10 -1k 100k` | 51 points, 1 … 1e5 |
| `ac dec 0 1k 100k` | 21 points (count replaced by 10) |

`noise` with an inverted range was worse: it published `onoise_total = 0.0`, a
plausible number manufactured from a loop that never executed. `sp` had no
validation at all. `.dc` with a step pointing away from stop produced a plot
containing no vector.

**The whole difficulty here is the boundary, and it is not where the report put
it.** Re-measurement withdrew most of the `.dc` finding: `dc v1 1 1 1`,
`dc v1 0 1 1.5` and `dc v1 0 1 2` all correctly produce **one point** — the
original "0 rows" was a `print`-output regex that does not match a single-row
plot. Thirteen decks in `examples/` are single-point sweeps and two are
descending with a negative step. Only the sign mismatch is real, in two
mirror-image spellings, and the predicate is exactly

```c
if ((stop - start) * step < 0.0)
```

which is false when `start == stop` (product zero) and false for a genuine
descending sweep. Equal endpoints are legitimate in all four analyses and are now
pinned: 19 `.ac`, 4 `.noise`, 9 `.sp` and 13 `.dc` cards depend on them.

## `meas` over a vector that holds one point

`@device[param]` is a scalar snapshot of the most recent point unless it is named
in a `.save`. That is documented, and `save all` deliberately does not cover it —
the manual says so twice, and its own worked example is `.save all @m2[vdsat]`,
which exists *because* `all` alone is not enough. So the snapshot is right.

Consuming it as a waveform is the defect. Every meas loop is
`for (i = 0; i < d->v_length; i++)` against the full-length scale, so it ran once
and `MAX`/`MIN`/`PP`/`INTEG` reported that single sample as the extremum. The
`at= 0.00000e+00` in the output was the tell — the scale was only ever read at
index 0. A zero-length vector (which E-418 already warns about at save time)
reported a measurement of exactly zero.

Six entry points share the missing check. XSPICE event vectors carry their own
time base in `d->v_scale` and are legitimately a different length, so they are
exempt.

### A heap write overflow, in the same function

`measure_rms_integral` sizes three buffers from the **scale** and fills them from
the **data** vector, appending unconditionally to `d->v_length`. A measured
vector longer than the scale — reachable with `setplot tran1` followed by
`meas tran m RMS tran2.v(b)` — writes past the end of all three. The buffers are
now sized from whichever is longer, which cannot change any well-formed deck.

## A temperature below absolute zero

`.options temp`, the `.temp` card, `option temp=`, `set temp=`, an instance
`dtemp=` and a `.dc temp` sweep all accepted a value that makes the Kelvin
temperature negative. `ckttemp.c` turned it straight into a negative thermal
voltage, and a Verilog-A model read `$vt = -0.0195 V` in silence.

Three of the paths share one funnel (`CKTsetOpt`, case `OPT_TEMP`); `.dc temp`
writes `CKTtemp` directly and instance `dtemp` is composed per device, so those
two need their own guards. −25 °C is perfectly ordinary and one deck here uses
it: **the line is absolute zero, not freezing.**

`dtemp=-300` is *not* part of this. It gives 0.15 K, a physical temperature, and
the resulting −5.4e+20 A is the model's own arithmetic. That piece of the
original evidence is withdrawn; only negative Kelvin is refused.

## Tolerances, and one iteration limit that matters

A tolerance ≤ 0 makes the convergence test unsatisfiable, and the run then blamed
the circuit — "Dynamic gmin stepping failed", "Timestep too small". After the
guard the same decks converge normally with the previous value.

`itl2` is the one with teeth, and the first analysis of it was wrong. It is not
"stored and never used": `CKTdcTrcvMaxIter` is consumed as an **unfloored**
continuation threshold — `iters <= itl2/4` and `iters > 3*itl2/4` — by four
separate gmin- and source-stepping heuristics in `cktop.c`. With `itl2=0` the
first test is permanently false and the second permanently true, so the ramp
collapses to its slowest schedule: **736,920 Newton iterations against 55**. The
probe that missed this was a diode OP that converges in seven iterations and
never enters gmin stepping at all.

For `itl1` and `itl4` the original analysis does hold — `NIiter` floors every
limit at 100, so those two are reporting hygiene. That floor is upstream and
deliberate and is **not** touched.

**`itl6` is a table synonym for `srcsteps`**, where 0 is documented and four
decks rely on it. The guard keys on the `OPT_` enum, never on the option name.
`itl5` never reaches the switch at all — its table entry deliberately omits
`IF_SET`.

## A multiplier, a duplicate model, and a discarded one

`m=-1` does not scale a device, it **inverts** it: a 2 kΩ resistor stamps −2000 Ω
and a passive device becomes active. On an OSDI device it additionally poisons
noise with a NaN, because the compiled model takes `sqrt($mfactor)`.

The guard identifies the multiplier by parameter **id**, not keyword — for an
OSDI device `m` and `_mfactor` are two spellings of one slot, and a model that
declares its own `m` has a different id whose range OpenVAF already enforces.

**`m=0` is deliberately left alone.** It is the ordinary "disable this instance"
idiom and behaves cleanly. The "singular matrix" message that appears with some
models is ngspice correctly reporting that `m=0` left an *internal* node
unconnected, and it names the node.

Two `.model` cards with one name were silently reduced to one, first wins.
Warning, not error: three of ngspice's own shipped decks carry byte-identical
duplicates, while two others carry duplicates with different values where the
second is plainly the intended one and is silently discarded.

And `m` written on a `.model` card is discarded while `_mfactor` on the same card
works. That discard is **not** changed — making it work would silently multiply
any deck that has carried a stray `m=` for years — only made audible.

## Numbers

`1e400` became `inf` and a resistor silently became an open circuit; `0e400`
became NaN and the operating point then failed five levels away with nan printed
for every node. This product has already ruled on exactly this twice —
Enhancement-425 refuses `r = 1e309;` in Verilog-A source and Enhancement-396
refuses `1e400` in a table data file — on the reasoning that a *literal* which
cannot be represented is a mis-written constant. A netlist literal is the same
mistake. Underflow stays untouched: `1e-400` is 0.0 and `1e-320` is a subnormal,
both defined by IEEE 754.

The exponent was accumulated into a plain `int`, so `1e2147483648` was signed
overflow — undefined behaviour that happened to yield `pow(10, INT_MIN)` = 0 —
and `1e21474836480` wrapped to exactly 0 and returned the bare mantissa. It now
saturates at 100000, far outside the double range, so the representability check
produces a real message instead of a wrapped answer. Deliberately not clamped to
308: that would turn an overflow into a plausible finite value.

An exponent marker with no digits was **swallowed**, which let the next letter be
read as a scale factor: `10Emitter` came out as 0.01 and `1em` as 1e-3. Both
contradict the tree's own rule (`src/ngspice.txt:499`): *letters immediately
following a number that are not scale factors are ignored*. The marker now
rewinds and becomes ordinary trailing text.

**What is documented is preserved, and pinned by name:** `1k2` → 1000,
`2meg5` → 2e6, `1e5x` → 1e5, `1kk` → 1000 (the manual's own `MMhos` shape),
`0x10` → 0, `5kohms` → 5000.

**`1..2` → 1.0 is deliberately left alone.** A census found `version=4.8.2` — the
universal BSIM4 spelling, present in two decks here — which reads as 4.8 by
exactly this rule. A warning would fire on essentially every modern MOS model
card in existence.

## A crash, found while reviewing the fix scope

A model whose `setup_model` failed had its error **overwritten by the next
model's success**, so `OSDIsetup` returned OK while that model's instances were
never set up. ngspice then loaded them and dereferenced a NULL jacobian pointer.

```
.model r_ok  nres r=1000
.model r_bad nres r=-5      ->  rc=139, ZERO bytes of output
```

Put the failing card first and it was a clean "Parameter r is out of bounds!".
**The deck order decided crash versus diagnostic.** Same signature class as
E-396's `$limit` NULL func_ptr. The first error is now latched; `continue` stays,
so every bad model is still reported.

## Two things read back, one added and one deliberately not

The temperature-scaled resistance a device actually stamps had no accessor. With
`tc1=0.001` at 227 °C the device stamps 1200 Ω — the current says so — while
`@r1[resistance]` reads the nominal 1000. The handlers for `conductance` and
`acconduct` already existed in `resask.c` and were simply missing from the
parameter table, i.e. dead code. Read the effective value as
`1/@r1[conductance]` = 1200.0 exactly.

**`@r1[resistance]` is not changed, and the reason is a measured defect in the
device that already does it.** The capacitor overwrites `CAPcapac` with the
scaled value, so `@c1[capacitance]` returns it — and that corrupts the round
trip: at 227 °C with `tc1=0.001`, sweeping `@c1[capacitance]` applies the
temperature factor a second time (1n → 1.2n → 1.44n, permanently). Making the
resistor scale would import that bug. Read-only is the house pattern for a
derived quantity — the diode's `gd`, MOS1's `vdsat`. The cap/ind round-trip
corruption is a separate, previously unreported defect and is flagged, not fixed.

## `$finish` reaches three analyses out of eleven

The reported headline — *"$finish/$stop print nothing and silently truncate a
`.dc` sweep"* — **does not reproduce.** ngspice prints
`Note: $finish requested by a Verilog-A device (sweep value 0.56).` and the
truncation is correct E-55 behaviour. The hunt harness filtered out every line
containing `"Note:"` and then grepped for `"OSDI"`/`"tripped"`, which that
message does not contain. Two layers of the same blindness.

The real defect is narrower and was invisible from that angle: `$finish`/`$stop`
are honoured by `tran`, `dc` and `noise` only. Under `.ac` a model that asked the
simulation to stop had its request dropped in silence and the whole frequency
sweep ran to completion. `.ac` now aborts, following the E-56 precedent that
`noise` has used since it was written; `.op` reports it but keeps its result,
because a single point has nothing to truncate. `pz`/`tf`/`disto`/`pss`/`sp`/
envelope are deliberately left alone — no evidence was measured there.

## Verification

* **`examples/inputguard_examples` — 88/88.** Every fix is measured as numbers,
  and every boundary is pinned from **both** sides: the refusals *and* the
  legitimate forms that must keep working (equal endpoints, single-point and
  descending `.dc`, `m=0`, `itl6=0`, `-25 °C`, `1k2`/`2meg5`/`1e5x`/`1kk`/`0x10`,
  and E-349's forward-reference `.tf` card).
* **Full regression 343/343**, both solvers (342 before this suite).
* The suite captures **stdout and stderr together** by construction — ngspice
  writes its own `$finish` Notes to stdout while the OSDI log callback writes
  WARN/ERR/FATAL to stderr, and watching one stream scores the other as silent.

## Found by

Round 33 of the ngspice+OSDI hunt, then an adversarial scope review run before
any code was written. Three notes on method.

**The census is what makes a fix safe.** Two proposals died on it: a per-line
rule for the double decimal point (killed by `version=4.8.2`), and rejecting a
`.dc` sweep that computes no points (killed by 13 single-point decks). A third,
"make `save all` include `@dev[...]`", died on the manual.

**The refutation pass caught a wrong root cause.** `itl2` was written off as
"stored and never used" on the strength of a probe that never entered gmin
stepping. It is a 13,400x performance defect. The differential has to exercise
the stage the input actually feeds — the same lesson as round 32.

**Five of the thirteen reported findings were withdrawn or narrowed on
re-measurement**, four of them because of a harness artefact rather than
anything in ngspice: a `"Note:"` filter, a single-row `print` regex, a physical
0.15 K read as nonsense, and documented scale-factor behaviour read as a bug.
