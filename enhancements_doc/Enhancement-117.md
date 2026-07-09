# Enhancement-117 — Periodic steady state (PSS) productionized

Periodic steady state analysis (`.pss`) computes a circuit's periodic operating
point directly — via a shooting method that iterates the fundamental frequency and
the initial state until the waveform repeats — instead of integrating transients
until they settle. It is the entry point of the RF **periodic** suite (the periodic
small-signal analyses PAC / pnoise / PXF build on a converged PSS).

ngspice already contained a working shooting-method PSS (`dcpss.c`), but it was
**experimental** in two disqualifying ways, so it had never really shipped:

1. **Gated behind `--enable-pss`.** The standard configure omits it, so `.pss` was
   an *"unimplemented dot command"* in every shipped binary. It could only be
   exercised by specially rebuilding ngspice.
2. **Deafening output.** When enabled, a single `.pss` run printed **~230 lines**
   of shooting-loop trace to stderr (per-iteration frequency estimates, residuals,
   breakpoint bookkeeping, delta control) — unusable in production.

This enhancement turns PSS into a first-class, shipped analysis.

## 1. Built by default

`configure.ac`: the PSS feature flag is flipped from opt-in to **default-on**
(`if test "x$enable_pss" != xno` and `AM_CONDITIONAL([PSS_WANTED], …!= xno)`), the
help text becomes `--disable-pss … Default=enabled`, and `configure` is
regenerated (autoconf 2.73). A plain `./configure` now defines `WITH_PSS`, so
`.pss` works in the shipped binary; `--disable-pss` still omits it.

## 2. Quiet by default, full trace on demand

`dcpss.c`: the shooting-loop diagnostics are routed through a new gate

```c
#define PSSDBG(...) do { if (ft_ngdebug) fprintf(stderr, __VA_ARGS__); } while(0)
```

69 debug prints become `PSSDBG(...)`; the converged summary and genuine errors
(*"Convergence reached … fundamental frequency is F Hz"*, *"PSS analysis aborted"*,
transient failures) stay always-on. A normal `.pss` run drops from **232 to 31
lines** of output; `set ngdebug` restores the full ~217-line trace for debugging.

## 3. Sparse-domain (KLU guard)

PSS's shooting loop **does not converge under the KLU solver** — it stalls at the
first shooting cycle and spins indefinitely — even though a plain `.tran` on the
same circuit runs fine under KLU. The failure is specific to the periodic
breakpoint/timestep machinery's interaction with KLU, not KLU transients in
general. Rather than let a `.option klu` + `.pss` deck hang, `DCpss` now fails fast:

```
Error: periodic steady state analysis (.pss) is not supported with 'option KLU';
use 'option sparse' (the default solver) for .pss.
```

PSS is therefore a **Sparse-1.3-domain** analysis, consistent with the other
Sparse-only cases (balanced-output pole-zero). Fixing KLU-PSS convergence is left
as a separate future investigation.

## Verification

A 1 MHz-driven RC low-pass (`R=1k`, `C=1n`): PSS converges to the drive frequency
and its fundamental harmonic equals the analytic AC response
`|H(1MHz)| = 1/sqrt(1 + (2πfRC)²) = 0.15714`.

```
Convergence reached … (iteration n° 22) … fundamental frequency is 999999.8976 Hz
  harmonic 1:  9.999999e+05 Hz   1.571762e-01     (analytic 0.157136)
```

`examples/rfpss_examples/` carries the deck (`rc_pss.cir`), a README documenting
the `.pss Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff [uic]`
syntax, and `verify_rcpss.py`, which checks the converged frequency, the
fundamental magnitude, and that the default output carries no shooting-loop trace.
(PSS is a shooting method — it simulates many drive periods — so the example runs
~1–2 minutes and is deliberately single-solver.)

## Files changed

| File | Change |
|---|---|
| `ngspice-46/configure.ac` (+ regenerated `configure`) | PSS built by default; `--disable-pss` opts out |
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `PSSDBG` gate for the shooting-loop trace (232 → 31 lines by default); fail-fast KLU guard directing `.pss` to `.option sparse` |
| `examples/rfpss_examples/` | new: `rc_pss.cir`, `verify_rcpss.py`, `README.md` |

## Scope

PSS ships and is verified under Sparse 1.3. It is the foundation for the periodic
small-signal analyses (PAC / pnoise / PXF), which remain future work, as does
harmonic balance (HB) and KLU-PSS convergence.
