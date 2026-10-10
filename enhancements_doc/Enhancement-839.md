# Enhancement-839: the derivative guards of `sqrt`, `pow`, `hypot` and `atan2` replace only the singular point — they moved every derivative by about 1e-18/x, 5 % at x = 1e-17

**Scope:** F2 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

openvaf-r:
- `openvaf/mir_autodiff/src/builder.rs`: the derivative caches of `Sqrt`, `Pow`, `Hypot` and
  `Atan2`.
- `openvaf/mir_autodiff/src/builder/tests.rs`: four expected MIR texts regenerated; their
  numeric checks are unchanged and pass.
- `openvaf/test_data/{dae,init}/diode_va_*.snap`: five snapshots, renumbered.

`examples/vafsqrtguard_examples/` (section [8] and `smallarg.va`, new). **Compiler only.**

**Suites:**
- [`vafsqrtguard_examples`](../examples/vafsqrtguard_examples/): 20 of 20 per solver. 7 of the 8
  checks in [8] fail on the E-838 compiler; the other is the compile.
- [`hypotzero_examples`](../examples/hypotzero_examples/): unchanged.
- The compiler workspace tests, with the known sourcegen drift excluded.
- The full sweep: 549 of 549.

## What was wrong

Four derivative guards keep the Jacobian finite where a natural derivative is infinite at an
argument of zero, the usual DC initial guess:
- **`sqrt`, Enhancement-261:** `x'/(2*sqrt(x))`.
- **`pow` with a fractional exponent, Enhancement-262:** `x'*y*x^(y-1)`.
- **`hypot` and `atan2`, Enhancement-580:** the 0/0 forms at the origin.

Each did it by shifting the argument at every point, not only at zero:
- the `sqrt` cache became `2*sqrt(x + a)` with `a` = 1e-18;
- the `pow` caches became `y/(x + a)`, `ln(x + a)` and `(x + a)^y`;
- the `hypot` cache became `hypot(h, a)`;
- `atan2` added `a²` to `x² + y²`.

All three write-ups said the shift was "below the ULP" for any nonzero argument. It is not.
The relative change is about `a/x`:

| x | change to the `sqrt` derivative |
|---|---|
| 1e-15 | 0.05 % |
| 1e-17 | 5 % |
| 1e-30 | a factor of 10⁶ |

Compact models written in SI units take these functions of quantities that small all the time:
squared charges, products of doping and permittivity, areas. Family A of the campaign compares
every corpus model's loaded Jacobian with finite differences of its own currents. It found
HiSIM-SOI's (`vacode140`) gm 7.8 % low and gds about 10 % off, with the dc currents identical,
so every `ac`, `noise`, `pz`, `tf` and `sens` result of such a model was wrong. A bisect of the
compiler put the first bad commit at E-261's.

The same module with each operator of `s*V`, `s` = 1e-17, at V = 1:

| | exact g | E-838 | now |
|---|---|---|---|
| `1e6*sqrt(s*V)` | 1.581139e-3 | 1.507557e-3 (−4.7 %) | exact |
| `1e15*hypot(s*V, 0)` | 1.0e-2 | 9.950e-3 (−0.5 %) | exact |
| `1e30*pow(s*V, 2)` | 2.0e-4 | 2.2e-4 (+10 %) | exact |
| `1e6*pow(s*V, 0.5)` | 1.581139e-3 | 1.507557e-3 (−4.7 %) | exact |
| `1e-3*atan2(s*V, s)` | 5.0e-4 | 4.975e-4 (−0.5 %) | exact |

The `pow` guard reached integer exponents too, since E-262 shifted every `pow`.

## The change

Each guard now replaces only the singular value, with a `select`, which composes through
downstream operators as the shifted value did:

| operator | cache now |
|---|---|
| `sqrt` | `x > 0 ? 2*sqrt(x) : 2*sqrt(1e-18)` |
| `pow` | `xr = (x == 0) ? 1e-18 : x`, giving `y/xr`, `ln(xr)` and `xr^y`; at `x ≠ 0` the last is the result itself |
| `hypot` | `h > 0 ? h : 1e-18` |
| `atan2` | `1/r²` with `r² = x² + y²` when positive, else `1e-36` |

Results:
- **Away from the singular point:** every derivative is the unguarded one, bit for bit.
- **At the singular point:** each keeps its guard's finite value. That is what E-261's tests of
  `K*sqrt(V)` and `G0/(1+sqrt(V))` from a zero initial guess check, and they pass unchanged.

On the corpus, HiSIM-SOI's loaded gm is −2.384235672388e-4 against the finite difference's
−2.384235671801e-4. The relative difference is 2.5e-10, the same as before E-261.

Re-run with this compiler, the campaign's Jacobian family clears more than F2's two files:

| models | E-838 compiler | now |
|---|---|---|
| HiSIM-SOI `vacode140` n4, n5 | 7.8e-2 to 8.7e-2 | within 1e-3 |
| HiSIM-HV ×9 (three releases, three variants each) | 2.1e-3 to 2.4e-3 | within 1e-3 |
| HiSIM-SOTB ×2 | 1.0e-2 and 1.7e-2 | within 1e-3 |

The campaign page had put HiSIM-HV and HiSIM-SOTB down to the finite difference's truncation,
because they closed at a smaller step. The step was not the cause: the smaller step only raised
the comparison's noise floor above the error. Of the 79 models that run, 78 now agree. The
one mismatch left is bsimsoi's floating body at 1 Hz, which is not a Jacobian error.

## The checks

`vafsqrtguard_examples` [8], with `smallarg.va`:
- the five operators at `s` = 1e-17, each against its closed form to 1e-12;
- `sqrt` and `pow(., 2)` at `s` = 1e-30.

Sections [1] to [7], E-261's and E-262's convergence and exactness checks, pass unchanged.
`hypotzero_examples`, E-580's origin cases, passes unchanged. The four autodiff unit tests
whose MIR changed are second-order `pow` and third-order `asin`, `acos` and `acosh`; their
numeric checks against closed forms at 10 ε pass.
