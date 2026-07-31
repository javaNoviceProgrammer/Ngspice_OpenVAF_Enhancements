# Enhancement-381 — `stb` handed its probe sources back zeroed

`stb` measures loop gain by injecting through two **existing** sources: it drives
one with `ac = 1` while holding the other at `ac = 0`, then swaps them. When
finished it restored them — to zero:

```c
/* restore the probes to quiescent */
alter <vname> ac = 0;
alter <iname> ac = 0;
```

Zero is only "quiescent" if that is where the probe started. A source carrying a
real AC drive had that value destroyed, and any following `.ac` came back with
**every node exactly `0.00000000e+00`** — no warning, no error:

```
@v1[acmag]  before stb = 1.0        ac before stb:  vm(mid) = 0.3333333333
@v1[acmag]  after  stb = 0.0        ac after  stb:  vm(mid) = 0.0000000000
```

## The fix

Read each probe's `acmag` before the first injection, and write those exact values
back afterwards instead of forcing zero.

Only the magnitude is saved: the injection writes `ac = N`, which sets `acmag` and
leaves `acphase` untouched. That was verified rather than assumed, and the example
asserts it so the assumption cannot rot silently.

## Scope — narrower than it first looks

This only bites when a probe carries a non-zero `ac` value that the caller still
needs. In the documented usage the probes are dedicated injection sources sitting
at `ac 0`, and restoring zero happens to be right.

It becomes wrong when an existing, already-driven source is named as the probe —
which is legal, is what the fuzzer did (`stb V1 V2`, where `V1` was the deck's own
`ac 1` source), and gives no indication that the drive has been destroyed. The
accept half below pins the ordinary `ac 0` case so the fix cannot regress it.

## How it was found

Cross-analysis **state** fuzzing with a **numeric** oracle —
`result(B after A) == result(B alone)` — the same instrument that found
[E-380](Enhancement-380.md). Re-running the 196-pair campaign against the E-380
binary left four mismatches, and this was the only genuine one.

The other three were `→ hb` deviations of **1e-17 to 1e-23** on near-zero
harmonics. Their *relative* deviation reached 30%, which looks alarming and means
nothing: it is the classic no-absolute-floor trap, the same one that produced a
false 2.12e-07 "mismatch" in the metamorphic campaign. With `atol = 1e-12` they
are all within tolerance.

## What this closes out

The chase started from an asymmetry in `dcpss.c`: **five `spSetComplex` calls and
zero `spSetReal`**. That turned out **not** to be a defect. The matrix mode is
managed per factorization by the SMP layer — `SMPcLUfac`/`SMPcReorder` set
complex, `SMPluFac`/`SMPreorder` set real — so there is nothing to restore.
`dcpss.c` sets it manually because it assembles **G + jC** by hand
(`spSetComplex` → `CKTload` for the real halves → `CKTacLoad` for the imaginary
halves → factor), which is the intended pattern and the reason it is the only file
in the tree that calls `spSetComplex` directly.

## Verification

`examples/stbrestore_examples` — 7 checks.

```
   fixed:     7/7
   pre-fix:   4/7
```

The three pre-fix failures are the defect. The four that pass on **both** binaries
are the accept half: a probe that legitimately started at `ac 0` still ends at
`ac 0`; `acphase` survives; `stb` still reports a loop gain; and `stb` run twice
reports the same one. `stb`'s own answer is **bit-identical** across the fix
(`|T[0]| = 9999995.004562`, phase `-0.00100110002572`), and its existing suite
`examples/stb_examples` passes 5/5 unchanged.

Regression 304/304 → 305/305.
