# Enhancement-509 — a domain the compiler refuses in source but not from the deck

```
python3 verify_domainrt.py
```

28 checks, both linear solvers. 14 of them fail without the fix.

## What was wrong

Eight math builtins and `$vt` have a compile-time domain guard that fires for a
literal and a `localparam`, naming the builtin, the value and the domain. The
same value on a **model card** is a `parameter`, deliberately not folded
([Enhancement-426](../../enhancements_doc/Enhancement-426.md)), so it reached
libm untouched.

| written in the model | from the deck |
|---|---|
| `sqrt(-4.0)` — refused, named | `sqrt(q)`, `q=-4` → **nan** |
| `ln(0.0)` — refused, named | `ln(q)`, `q=0` → **-inf** |
| `asin(2.0)`, `acos(-3)`, `acosh(0.5)`, `atanh(1)`, `log(-1)` | **nan** / **inf** |
| `pow(-4, 0.5)`, `-4 ** 0.5` | **nan** |

Silent in an operating-point variable, exit code 0. In a residual it became
*"Timestep too small; cause unrecorded"*, naming neither the model nor the call.

**`$vt` changed what a device is.** A diode `Is*(limexp(V/$vt(tabs)) - 1)` went
from −1.207e−04 A at `tabs=300` to **−6.0e−07 A** at `tabs=-300` — the 1 MΩ shunt
alone. A negative absolute temperature inverts the exponential, so the diode
stopped conducting, silently.

**An integer parameter that overflows.** `(int) round(1e300)` is undefined
behaviour and saturates here to 2147483647 — and it did so *before* the range
check, so `from [0:2147483647]` accepted `1e300` by landing exactly on its own
upper bound. `sp=200` against `[0:100]` was refused correctly all along.

## The half that must not be guarded

`sqrt(V(p,n))` goes briefly negative during Newton iteration in working models.
Refusing every out-of-domain argument would abort them — the mistake
[Enhancement-508](../../enhancements_doc/Enhancement-508.md) made with
`$discontinuity` and had to take back.

The guard is emitted **only for a parameter-derived argument** — literals,
`localparam`s and `parameter`s — which is fixed once the model card has been read
and therefore cannot fire spuriously. Checks [10]–[13] hold that line.

## Withdrawn at fix time

Round 65 also reported `idtmod` with a deck modulus ≤ 0 degenerating to plain
`idt`, measured as a bit-identical match.
[Enhancement-504](../../enhancements_doc/Enhancement-504.md) chose that
deliberately — *"fall back to the UNWRAPPED integral, which is exactly what
`idtmod` means with no modulus supplied"*. The identity is the decision working.

## Files

| file | what it holds |
|---|---|
| `mathdom.va` | the eight domains, each argument a `parameter` |
| `rtarg.va` | the same builtins with RUN-TIME arguments — must not be refused |
| `vtdiode.va` | the diode whose thermal voltage comes from the card |
| `intrange.va` | an integer parameter with `from [0:2147483647]` and `from [0:100]` |
| `litdom.va` | the compile-time half, which must stay refused |
