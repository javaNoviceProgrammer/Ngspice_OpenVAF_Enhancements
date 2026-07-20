# Enhancement-249 — URC / LTRA transmission-line input validation

Input validation for two **core** transmission-line devices (`urc`, `ltra`) that
accepted degenerate or out-of-range parameters, producing a silently wrong result
or a resource-exhaustion hang rather than a clean error. Same class as E-248 (the
CPL find) — core-device parameter validation.

## URC — unbounded / degenerate lump count

The URC uniform-RC line (`Uxxx n1 n2 n3 model l=len n=lumps`) is expanded at
setup (`spicelib/devices/urc/urcsetup.c`) into a ladder of `n` resistor +
capacitor(/diode) sections, one node group per lump, and `n` is also an exponent
of `pow(k, n)`:

```c
for (i = 1; i <= here->URClumps; i++) {   /* builds a section + nodes per lump */
    ...
    r1 = (r0*(p-1))/((2*(pow(p,(double)here->URClumps)))-2);
```

The user-supplied `n` was never bounds-checked:

- **`n ≤ 0`** ran the loop zero times — no lumps, so the output node was left
  silently unconnected and `v(out) = 0`. A wrong answer with no diagnostic.
- **large `n`** (e.g. a typo `n=100000000`, or `2000000000` near `INT_MAX`)
  exhausted memory / hung while instantiating the ladder; even `n≈20000` takes
  tens of seconds. The source itself carried a
  `/* may want to limit lumps to <= 100 or something like that */` comment.

**Fix.** Require `1 ≤ n ≤ URC_MAX_LUMPS` (1000 — the auto-computed count is
typically 3–30, so 1000 is far above any realistic discretization), reporting a
clean `E_BADPARM` error otherwise. Validated after the auto-lump default so it
covers both the given and the computed count.

## LTRA — negative parameters

The lossy line (`spicelib/devices/ltra/ltraset.c`) selects its RLGC "special
case" with `!= 0` tests:

```c
if ((model->LTRAresist == 0) && (model->LTRAconduct == 0) &&
    (model->LTRAcapac != 0) && (model->LTRAinduct != 0)) {
    model->LTRAspecialCase = LTRA_MOD_LC;   /* ... uses sqrt(L/C), sqrt(L*C) */
```

A **negative** L or C satisfies `!= 0`, so it fell through to `sqrt(L/C)` /
`sqrt(L*C)` in `LTRAtemp`, yielding a `NaN` characteristic impedance and delay and
a degenerate (all-zero) run instead of an error. (A zero / too-few-parameter line
was already handled — *"at least two of R,L,G,C must be specified and nonzero"*.)

**Fix.** Reject any negative R/L/G/C up front with a clean error — R, L, G and C
are per-unit-length line parameters and must be physical (non-negative).

## Verification

`examples/tlinefix_examples/verify_tlinefix.py` (8 checks, both solvers): a valid
5-lump URC divider and a valid LTRA lossless line still simulate; `URC n=0`,
`n=-3` and `n=100000000` are each rejected with a clean error (the huge case
*instantly*, no hang); `URC n=1000` (the maximum) still runs; and `LTRA` with
negative C is rejected cleanly while a C=0 line keeps its pre-existing "nonzero"
error.

## Scope

Core ngspice, two device setups (`urc/urcsetup.c`, `ltra/ltraset.c`); the ngspice
binary is rebuilt. No solver, analysis, or numerical change; a validly-specified
URC or LTRA line is unaffected. Full regression: all examples pass.
