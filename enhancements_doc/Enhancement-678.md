# Enhancement-678: `idt` with `assert` returns its initial condition at any timescale — the reset decay is sized from the transient step and made deadbeat at the onset

**Scope:** F9 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
openvaf: `hir_lower/src/expr.rs` (`lower_integral`, the reset branch: the
time constant from `$osdi$tstep`, the gain capped at 2/h from `$osdi$delta`,
the bound 2τ). ngspice: `src/osdi/osdiload.c` (the two private simparams).
`examples/idtassert_examples/` (`idtfast` and eight checks, 17);
`examples/reportguard_examples/` (its simparam drift check skips the
private namespace). Handbook
[§2.6](../docs/handbook/02-verilog-a-language.md) row; the
[compliance document](../docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md)'s
entry. **Both sides**; a model picks the change up when it is recompiled.

**Suites:** [`idtassert_examples`](../examples/idtassert_examples/) 17 of 17
per solver, both solvers (the 8 new checks fail on the E-670 binaries);
`opargs` 16 of 16, `idtic` unchanged; `reportguard` 31 of 31 with its drift
check told about the private namespace; the compiler workspace tests green
apart from the three pre-existing sourcegen drift failures; full sweep 531
of 531.

## What was wrong

LRM 4.5.4: with both an initial condition and `assert`, `idt` *returns* the
initial condition whenever `assert` is nonzero, and once it is zero the
integral restarts from the last instant it was nonzero.

```verilog
y = idt(1e6, 0.5, V(a,b) > 0.5);   // a pulse on a: 1 V from 1 us to 3 us
```

| t (µs) | 0.5 | 1.5 | 2 | 2.5 | 3 | 3.5 | 4 | 5 |
|---|---|---|---|---|---|---|---|---|
| LRM | 1.0 | 0.5 | 0.5 | 0.5 | 0.5 | 1.0 | 1.5 | 2.5 |
| was | 1.0 | **1.45** | **1.41** | **1.36** | **1.32** | **1.82** | **2.32** | **3.32** |

[E-52](Enhancement-52.md) realises the reset as a first-order decay toward
`ic`. The decay is the right mechanism: an algebraic jump in the stored
charge is the E-27 impulse — the transient integrator's d/dt term sees it,
and self-resetting integrators ring and run away. But its time constant was
a **fixed 10 µs**, sized for the second-scale models of E-52's suite, where
it is invisible. At the microsecond scale a 2 µs hold reached 1.32, not 0.5,
and the integral resumed from 1.32, so every later value carried the amount
that had not relaxed. A sample-and-hold or a reset integrator written with
`assert` — the LRM's own use case — held the wrong value, silently; a zero
integrand hid it.

## What changed

**The time constant follows the analysis.** ngspice serves the transient's
print step through `$osdi$tstep`, a private, namespaced simparam (the `$…$`
convention [E-215](Enhancement-215.md) uses for plusargs — not an LRM name,
and not the `timestep` the simparam table refuses as a user-facing one: no
model spells it). The realisation sets τ = tstep/1000, so a reset completes
within a thousandth of a print step at whatever scale the run has. A
simulator that does not serve it gets the old constant.

**The gain is capped at 2/h.** ngspice also serves the step under way
(`$osdi$delta`), and the gain is min(1/τ, 2/h). The trapezoidal rule's
response to a stiff decay flips sign past λh = 2, and the step at which a
reset first takes effect is chosen before the model can bound it: with
τ = 2 µs a 5 µs onset step took E-52's relaxation oscillator from 1.0
through 0.44 to −0.11, where its release event fired. At λh = 2 the rule is
deadbeat instead — the onset step halves the deviation, the next (bounded to
2τ) removes it and leaves the trapezoidal history clean, whatever the onset
step was. Gear is L-stable and never flipped; it settles in a few steps too.
The bound while the decay is active is 2τ, as it was 2/K before.

## Verification

| check | result |
|---|---|
| `idt(1e6, 0.5, V(rst) > 0.5)`, pulse 1–3 µs, `.tran 0.1u 5u`: at 1.5 and 3.0 µs | 0.5 (was 1.45, 1.32) |
| the same at 3.5 and 5 µs | 0.9985, 2.4985 = 0.5 + 1e6·(t − 3001.5 ns), the release seen at the accepted point after the falling edge (was 1.82, 3.32) |
| the same under `method=gear` | the same |
| the onset, traced | 1.5003 → 1.0002 → 0.5834 → 0.5000 over steps of 0.3, 0.2, 0.2 ns; then 0.5 at every point of the hold |
| E-52's relaxation oscillator, `.tran 0.002 5` | 1.0 → 0.499 → 3e-6 in two steps; peaks 0.9986, valleys 2.5e-6, period 0.9986 s (was 0.99999 s; below) |
| E-52's other checks; `opargs`; `idtic` | unchanged |
| data rows of the hunt's run | 89 (87 on the old binaries) |
| the E-670 binaries on the suite | the 8 new checks fail |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- The release instant is the accepted point at which the assert expression
  is first seen false, up to one step after the edge, and the first step
  after it carries the trapezoidal rule's half-step on the derivative jump.
  The 3e-4 in the table's resumed values is that; a `cross` on the assert
  expression pins the instant.
- A hold shorter than the settling — the onset step plus about 2τ — resumes
  from wherever the decay got to.
- **Seen on the way, left for its own finding:** a `cross` event that fires
  on a *rejected* step attempt keeps its side effect. The oscillator's
  `rst = 1` was set by a 2 ms attempt whose predictor overshot 1.0; the
  attempt was rejected, the variable stayed, and the reset stood at the
  retry, 1.4 ms before the ramp reached 1.0. The old dynamics happened to
  undo it — at λh ≫ 2 the flipped value fired the *release* cross in the same
  attempt — which is why the period read 0.99999 s. That is a property of
  variable persistence across rejected attempts, not of the reset, and the
  hunt document records it.
