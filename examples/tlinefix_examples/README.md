# URC / LTRA transmission-line input validation (Enhancement-249)

Input validation for two **core** transmission-line devices that accepted
degenerate or out-of-range parameters, leading to a silently wrong result or a
resource-exhaustion hang instead of a clean error.

## URC — lump count (`urcsetup.c`)

The URC uniform-RC line is expanded at setup into a ladder of `n` (the `n=`
parameter, "number of lumps") resistor + capacitor(/diode) sections — one node
group per lump — and `n` is also used as an exponent of `pow(k, n)`. The lump
count was never validated:

- **`n ≤ 0`** built *no* lumps, leaving the output silently unconnected
  (`v(out) = 0`) — a wrong answer with no diagnostic.
- **large `n`** (a typo such as `n=100000000`) exhausted memory / hung while
  instantiating the ladder — already ~20 000 lumps takes tens of seconds; the
  source even carried a `/* may want to limit lumps to <= 100 */` comment.

E-249 requires `1 ≤ n ≤ URC_MAX_LUMPS` (1000 — far above the auto-computed
count, which is typically 3–30), reporting a clean error otherwise.

## LTRA — negative parameters (`ltraset.c`)

The lossy line selects its RLGC "special case" using `!= 0` tests, so a
**negative** L or C passed the checks and reached `sqrt(L/C)` / `sqrt(L*C)` in
`LTRAtemp`, producing a `NaN` characteristic impedance / delay and a degenerate
(all-zero) run. E-249 rejects any negative R/L/G/C up front. (A zero /
too-few-parameter line was already a clean error — *"at least two of R,L,G,C must
be specified and nonzero"*.)

## Verification

`verify_tlinefix.py` (8 checks, both solvers): a valid 5-lump URC divider and a
valid LTRA lossless line still simulate; `URC n=0` / `n=-3` / `n=100000000` are
each rejected with a clean error (the huge case *instantly*, no hang); `URC
n=1000` (the maximum) still runs; and `LTRA` with negative C is rejected cleanly
while a C=0 line keeps its pre-existing "nonzero" error.

```
python3 verify_tlinefix.py
```

## Scope

Core ngspice, two device setups (`urc/urcsetup.c`, `ltra/ltraset.c`); the ngspice
binary is rebuilt. No solver, analysis, or numerical change; a validly-specified
URC or LTRA line is unaffected.
