# Enhancement-362 — fuzzing analysis-card sweep parameters

[Enhancement-361](Enhancement-361.md) found one `(int)NaN` conversion in
`.disto`'s point count. That looked like a family rather than a one-off, so this
enhancement fuzzes analysis-card parameters against an ASan+UBSan build.

**Seven defects, all pre-existing, all reachable from ordinary input.** Three of
the counts involved are used as **allocation sizes**, and one reached the
allocator negative.

---

## The harness

`examples/sweepguard_examples/fuzz_analysis.py` drives every sweep-taking
analysis — `.disto`, `.ac`, `.noise`, `.sens`, `.sp`, `.dc`, `.tran`, `.four`,
`.fft` — with degenerate and extreme parameters, classifying each run as
`ok` / `SANITIZER` / `CRASH` / `HANG` and keeping one repro per signature.

The value pool targets arithmetic rather than realism: zero and negative step
counts (divide), equal endpoints (`0/0`), a zero start frequency (`log(inf)`),
and `INT_MAX` (overflow before the cast). It is not run by the regression — it
needs a sanitizer build to be worth anything.

## What it found

| site | defect |
|---|---|
| `distoan.c` DECADE | count `±inf` or `> INT_MAX` → `(int)` UB → `DstorAlloc` size |
| `distoan.c` OCTAVE | same |
| `distoan.c` LINEAR | `DnumSteps+1` **signed int overflow** at `INT_MAX`, before any double-valued guard could run |
| `distoan.c` LINEAR | final count could be **negative** → ASan: `requested allocation size 0xfffffffffffffff0` |
| `dctran.c` | `CKTtimeListSize` overflow → `TMALLOC` size, and `osdiaccept.c` sizes a buffer from it |
| `cktsens.c` ×2 | sweep count cast UB |
| `dctrcurv.c` | `.dc` unbounded: no point-count limit, and a step below the start's ULP **never advances** |

The `.dc` case is the one a user hits by accident: `dc V1 0 1 1e-30` — a typo for
`1e-3` — runs forever with no diagnostic, while `.tran` declines the equivalent
request and a zero step is already refused.

## One fix made things worse before it made them better

My first `dctran.c` attempt **clamped** the timepoint count to a representable
value. That regressed `tran 1e6 1e30 1e6` from *errors out* to *hangs* — because
ngspice's existing rejection of absurd transients **was** this very overflow
producing an allocation size that failed. Clamping made the allocation succeed
and the transient then ran essentially forever.

The accidental rejection had to become a deliberate one: the guard now returns
`E_PARMVAL`. Absurd transients return `rc=1` exactly as before, and ordinary ones
are bit-identical.

## Two findings that were not bugs

An enormous but finite sweep is **slow, not hung**, and a timeout cannot tell
them apart.

- `sens ac dec 1000000` over 300 decades: 0.05 / 0.20 / 1.78 / 17.4 s at
  1 / 10 / 100 / 1000 steps — linear, so simply large.
- `ac oct 1000000 1e300 1e6`: 12.8 s on both the shipped and fixed builds,
  exceeding the fuzzer's timeout only under ASan's ~5× slowdown.

Neither was "fixed". Only counts that cannot be represented, and loops that
cannot advance, are rejected. The scaling check that distinguishes the two is
documented in the harness so a later run does not chase them again.

## Verification

Final fuzz run: **400 iterations, SANITIZER=0, CRASH=0**, no real hangs.

`examples/sweepguard_examples` pins all eleven repros plus six ordinary sweeps
that must be unaffected. It is a proven trigger: against the pre-fix build it
reports

```
FAIL  no nonsense sweep spec hangs
      [HANG: ["dc, step below the start's ULP", 'dc, count exceeds int',
              'sens, count overflows int']]
```

Note that its "produces no output" check passes even pre-fix — an ordinary build
cannot observe an undefined conversion, only its consequences. That is why the
sanitizer harness ships alongside it.

Regression 286/286 — 285 as before, plus the `sweepguard` suite this enhancement
adds. The fuzz harness is deliberately *not* among them: the runner discovers
`examples/*_examples/verify_*.py`, so `fuzz_analysis.py` is excluded by name, and
it refuses to run at all unless `NGSPICE_BIN` points at a sanitizer build.
