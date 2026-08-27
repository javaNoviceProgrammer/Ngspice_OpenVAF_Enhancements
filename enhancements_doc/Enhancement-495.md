# Enhancement-495 — seven ways a decision made once was never revisited

**Files:** `src/spicelib/parser/inpgmod.c`, `src/spicelib/analysis/dctrcurv.c`,
`src/frontend/numparam/xpressn.c`, `src/frontend/rawfile.c`.

**Suite:** `examples/binstale_examples/` — 64 checks.

## Why

Round 55 probed MOSFET **model binning**, which no earlier round had touched,
and found it soft in three ways. Following the shape it exposed — *a decision
taken once and never asked again* — led into the DC sweep, which turned out to
have the same defect twice more.

## 1. The binning tolerance was absolute, and the values are metres

`is_equal()` tested `fabs(a - b) < 1e-9`. On a channel length that is a slop of
**one nanometre**, applied whatever the geometry, so a device up to 1 nm outside
**every** declared bin was silently placed in one:

| `l` | bins reach 30n | before | after |
|---|---|---|---|
| 30n | top edge | `nch.2` | `nch.2` |
| 30.5n | 0.5 nm out | **`nch.2`** | refused |
| 31n | 1.0 nm out | **`nch.2`** | refused |
| 31.1n | 1.1 nm out | refused | refused |

The magnitude is fixed, so as a *fraction* of the device it grows without bound
as processes shrink: 0.03% of a 3 µm width, but **5% of a 20 nm channel**. A bin
limit is a number the card states exactly, so the comparison is now relative
(`1e-12`), which is far tighter than any slop a card intends and still absorbs
the decimal-to-binary error in `1u` against `1e-6`.

## 2. Adjacent bins overlapped, and `.model` order decided which one won

The function's own comment states the rule:

```c
/* the standard binning rule is: min <= value < max */
return is_equal(value, min) || is_equal(value, max) || (min < value && value < max);
```

Accepting `is_equal(value, max)` as well closes the interval, so a device on a
shared boundary matches **both** neighbours and the winner follows the order the
`.model` cards happen to appear in. With bins `[1u,2u)` and `[2u,3u)`:

| `l` | cards 1,2 | cards 2,1 | i(V1) ratio |
|---|---|---|---|
| 1.5u | `nch.1` | `nch.1` | — |
| **1.999u** | **`nch.2`** | **`nch.1`** | **2.95×** |
| **2u** | **`nch.2`** | **`nch.1`** | 2.95× |

`l=1.999u` is unambiguously inside the lower bin; the 1 nm slop of finding 1
reached backwards across the boundary and the card order picked the answer.

Selection now runs **two passes**: the documented half-open rule first, and the
closed reading only where the strict one matched nothing. That second pass is
what still admits a device sitting exactly on the **top** bin's `lmax`, which no
half-open bin can contain and which working decks rely on. Because it never runs
when the strict rule already found a bin, nothing that selects a bin today can
move — the Enhancement-493 shape.

## 3. An OSDI model could not be binned at all

The binnable set was eleven hardcoded built-in names, so a Verilog-A model
written exactly as a BSIM PDK writes one died with

```
Unable to find definition of model nv
```

for a model defined twice — the symptom, not the cause, and the same shape as
the resistor named `r` in Enhancement-493. OSDI types are now asked through the
predicate Enhancement-323 already provides, so every model any `.osdi` file
defines is covered with no list to maintain. The four bin limits are not
Verilog-A parameters, so `INPgetMod` consumes them on the card the way it
consumes `level`; without that the selected bin's own card reported four unknown
parameters.

## 4. A degenerate distribution spec was silently flattened

`agauss`/`gauss` are right to refuse a variation or a sigma that is zero or
negative, but they did it without a word — and the result does not look like a
failure. Every draw returns the nominal, so a Monte Carlo run over a parameter
that never moves reports a **yield of 100%**:

```
.param vo = agauss(1000, 100, 3)    ->  yield 0.12 against a [995,1005] spec
.param vo = agauss(1000, 100, 0)    ->  yield 1.00, silently
```

one character apart, and silent under every option including `warn_physics`.
Six spellings reach it. The behaviour is unchanged — a deck may legitimately zero
a variation to disable it — but it is now audible, once per run per function,
naming which of the four degeneracies it found. `unif`, `aunif` and `limit` are
deliberately left alone: they have no such guard, and a negative variation there
describes the same symmetric interval as its absolute value.

## 5-6. A `.dc` sweep never revisited what setup decided

Enhancement-471's own comment says it:

> `.dc` — including the parameter sweeps of Enhancement-427 — has never done
> that: it sets the circuit up once and walks its points inside the analysis.

and, of reusing a setup:

> the topology is frozen at whatever the first point decided, and the sweep
> quietly draws a flat line.

E-471 gave the **`sweep`** command the machinery to notice and rebuild. `.dc`
never got it, so two structural boundaries are crossed silently:

* **the model bin** — a swept `l`/`w` that leaves the bin the device was *parsed*
  into keeps the old bin, and every point past the boundary is computed with the
  wrong model. Measured **2.9× out**.
* **an OSDI node collapse** — a swept parameter that changes it keeps the matrix
  built for the old topology, and the sweep returns a **flat line**: −1.000e-03
  at rs = 0, 500 and 1000, where the answers are −1e-3, −6.67e-4 and −5e-4.

Both siblings are correct. `alter` re-selects the bin through
`if_set_binned_model()` and re-decides the collapse on its next analysis;
`sweep` runs a whole job per point. That is the same disagreement Enhancement-427
recorded two comments higher in the same file.

Rebuilding the matrix in the middle of a running analysis is a far larger change
than this evidence supports, and the command that does it correctly already
exists. So **`.dc` now refuses the point it cannot compute** and names `sweep`,
rather than publishing a number that is wrong without saying so — Enhancement-485's
rule that a wrong answer is worse than a refusal.

The detection is exact and costs nothing when nothing moves:

* the collapse is read from the flag `OSDItemp` **already sets** on every
  parameter write (Enhancement-417) and that `CKTdoJob` already consumes —
  `DCTsetInstParam` calls `DEVtemperature` and simply never asked;
* the bin is checked by reading the four limits off the model the device is bound
  to, and only for a model chosen by binning.

A sweep that stays inside one bin, or changes no collapse, is untouched.

**The refusal does not borrow Enhancement-427's message.** That one says *"the
device refused … the same value is refused on the instance line and by `alter`"*,
which would be false on both counts here: the device took the value, and `alter`
computes the case correctly. The specific message stands on its own, and a value
the device really does refuse still reports exactly as before.

## 7. The ascii rawfile was one digit short of a double

`#define DEFPREC 15` is the precision of a `%.*e`, so it emitted **sixteen**
significant digits — and seventeen are needed before an IEEE754 double reads back
as itself. `write` then `load` therefore changed values in the last ulp
(`0.15717672547758987` came back `…985`) while the **binary** format, which
stores the bits, was exact. Over 200000 random doubles `%.15e` fails to
round-trip 51390 of them and `%.16e` none. The comment calling 15 "(max)" was
wrong twice: not a maximum, and not enough. `set rawfileprec` still overrides.

## What must not move

* **Bin selection that works today** — every `l` from `1u` to `3u` binds to the
  same card in either declaration order, and the top bin's `lmax` still binds.
* **`alter` and `sweep`**, which already crossed both boundaries correctly.
* **`unif`, `aunif`, `limit`**, and a healthy `agauss`, which stay silent.
* **A value the device refuses**, which still reports as a device refusal.
* **An ordinary source sweep**, an `m` multiplier sweep, and a `.dc` sweep of a
  single **unbinned** model — the last exact against a deck parsed at each width.
* **The binary rawfile**, and an explicit `rawfileprec`.

## Verification

```
python3 examples/binstale_examples/verify_binstale.py   # 64/64
python3 examples/run_regression.py                      # 409/409
```

**40/64** against the pre-fix binary, so **24 of 64 checks discriminate**. The
other forty are controls that must not move, and do not -- most of them the ones
that make each of these easy to get wrong: bin selection in either card order,
the top bin's `lmax`, `alter` and `sweep` crossing both boundaries, a genuine
device refusal still reported as one, and a `.dc` sweep of an unbinned model
staying exact.
