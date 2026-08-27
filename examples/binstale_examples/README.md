# Enhancement-495 — seven ways a decision made once was never revisited

```
python3 verify_binstale.py
```

64 checks, a few seconds. **40/64** against the pre-fix binary -- **24**
checks discriminate.

## What it is

Round 55 probed **MOSFET model binning**, which no earlier round had touched.
It was soft in three ways, and the shape it exposed — *a decision taken once and
never asked again* — led into the DC sweep, which had the same defect twice more.

## 1-3. Binning

| | before | after |
|---|---|---|
| `l` 1 nm outside **every** bin | silently binned | refused |
| `l` on a shared boundary | bin follows `.model` **order** (2.95× in i(V1)) | the half-open rule decides |
| `l=1.999u`, inside the lower bin | **upper** bin | lower bin |
| an OSDI model with bin names | *"Unable to find definition of model nv"* | bins correctly |

`is_equal()` compared with an **absolute** `1e-9` — one nanometre on values in
metres, so the slop was 0.03% of a 3 µm width but **5% of a 20 nm channel**. It
is now relative. `in_range()` also accepted `is_equal(value, max)`, closing an
interval its own comment documented as `min <= value < max`, so adjacent bins
overlapped; selection now asks the strict rule first and the closed one only
where the strict rule matched nothing, which keeps a device sitting exactly on
the **top** bin's `lmax` working.

## 4. A distribution that cannot vary

```
.param vo = agauss(1000, 100, 3)    ->  yield 0.12 against a [995,1005] spec
.param vo = agauss(1000, 100, 0)    ->  yield 1.00, silently
```

One character apart. The guard was right to refuse a zero or negative variation
or sigma, but it discarded them without a word, and a Monte Carlo run over a
parameter that never moves reports success. Now audible; behaviour unchanged.

## 5-6. `.dc` never revisited what setup decided

Enhancement-471 wrote that `.dc` "sets the circuit up once and walks its points
inside the analysis", and that a frozen topology means "the sweep quietly draws a
flat line". It gave **`sweep`** the machinery to notice and rebuild; `.dc` never
got it:

* a swept `l`/`w` leaving its bin keeps the parse-time model — **2.9× out**;
* a swept parameter changing an OSDI node collapse keeps the old matrix — a
  **flat line** (−1.000e-03 at rs = 0, 500, 1000, where the answers are −1e-3,
  −6.67e-4, −5e-4).

`alter` and `sweep` both get these right. `.dc` now **refuses** the point it
cannot compute and names `sweep`, rather than publishing a wrong number. The
collapse is read from a flag `OSDItemp` already sets on every parameter write
(E-417) and that `CKTdoJob` already consumes — `.dc` simply never asked.

## 7. The ascii rawfile

`DEFPREC 15` emitted sixteen significant digits where a double needs seventeen,
so `write` + `load` changed the last ulp while the binary format was exact.
Over 200000 random doubles `%.15e` fails to round-trip 51390 of them, `%.16e`
none.

## What must not move

Bin selection that works today (every `l` from `1u` to `3u`, in either card
order, and the top bin's `lmax`); `alter` and `sweep`; `unif`/`aunif`/`limit` and
a healthy `agauss`; a value the device really refuses; an ordinary source sweep,
an `m` sweep, and a `.dc` sweep of a single **unbinned** model; the binary
rawfile and an explicit `rawfileprec`.
