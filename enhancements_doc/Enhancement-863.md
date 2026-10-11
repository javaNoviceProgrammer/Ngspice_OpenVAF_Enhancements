# Enhancement-863: `let` takes tan(0) — the range check refused a result of 0

**Scope:** F8 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice: `maths/cmaths/cmath1.c`, `d_tan`.

`examples/lettan_examples/` (new). **ngspice only.**

**Suites:**
- [`lettan_examples`](../examples/lettan_examples/): 5 of 5 per solver. On the E-861 binaries
  3 fail; [4] and [5] are controls.
- The full sweep: 568 of 568.

## What was wrong

`d_tan`, the front end's tangent of a real vector, checked `rcheck(tan(x) != 0, "tan")` before
taking the tangent. That refused a valid result:
- `let x = tan(0)` failed "argument out of range for tan", while `tan(0.5)` was fine;
- so did any vector with a 0 in it, and `tan(0)` under `set units=degrees`.

`tan(0)` is 0 in a `.param` and in a B-source, and the complex `tan` took 0 already. The pole
the check presumably meant to guard, cos(x) = 0, is never exactly met by a double: tan(π/2
rounded) is 1.6e16, which the check let through anyway.

## The change

The tangent is taken first, and the check is that it is finite. tan of a finite argument always
is, so only a NaN or an infinite argument is refused now, which has no tangent.

## The checks

`lettan_examples`:
- **[1]** `let a = tan(0)` is 0 (refused on E-861).
- **[2]** A vector with a 0 in it: tan of each element.
- **[3]** With `units=degrees`: tan(0) is 0, tan(45) is 1 to rounding.
- **[4]** (control) `tan(0.5)`, `tan(-0.5)` and a complex `tan(0)`.
- **[5]** (control) The `.param` and the B-source give 0 for `tan(0)`.
