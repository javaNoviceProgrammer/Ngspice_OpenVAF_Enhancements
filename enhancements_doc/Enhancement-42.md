# Enhancement-42 — correlated (same-named) noise sources (version11)

This document describes the changes made to **OpenVAF-r** and **ngspice-46** in
the `version11/` directory to implement **noise-source correlation by name**:
noise functions that carry the same name argument model the *same* physical
source and must sum **coherently** (as amplitudes) at the output, per
Verilog-AMS LRM 4.6.4.

## The gap

The LRM defines the name argument of `white_noise` / `flicker_noise` /
`noise_table` as source *identity*: two noise functions with identical names
are the **same source** — perfectly correlated — so their contributions to the
output add as complex amplitudes,

```
onoise^2 = | Σ_k  f_k · sqrt(pwr_k) · T_k |^2        (same-named group)
```

not as powers,

```
onoise^2 =   Σ_k  f_k^2 · pwr_k · |T_k|^2            (independent sources)
```

where `f_k` is the (signed) contribution factor and `T_k` the complex transfer
from the source's branch to the noise output.

Before this enhancement the name was used only to *label* the per-source output
vectors. Every source was independent — a two-fold same-named source pair read
`sqrt(2)`× instead of `2`×, and even a **negated** contribution of the same
source (`<+ -white_noise(S, "n")`, anti-phase, should cancel) *added* power.

The three `// TODO noise` markers in the OSDI crate (`metadata.rs`, `load.rs`)
turned out to be stale — the code below them is complete — and the
`lineralize.rs` "complex noise power" note is an optimization idea, not a gap.
Correlation was the real leftover.

## The fix (two-sided)

**OpenVAF — `openvaf/osdi/src/load.rs`** (`load_noise` codegen): the
contribution factor used to be folded into the loaded power as `pwr * fac²`,
destroying its sign. It is now folded as `pwr * fac * |fac|` — identical
magnitude, but the loaded power **carries the factor's sign**. ngspice's noise
analysis takes `fabs()` of each source's power before using it, so nothing
changes for independent sources; the sign is what enables anti-phase
cancellation inside a correlated group. (Supporting fix:
`openvaf/mir_llvm/src/intrinsics.rs` never registered `llvm.fabs.f64` — one
`ifn!` line.)

**ngspice — `src/osdi/osdinoise.c`** (`N_DENS`): the per-source loop first
records each source's complex transfer `T_k = (CKTrhs[n1]−CKTrhs[n2]) +
j(CKTirhs[n1]−CKTirhs[n2])` (the adjoint solution), then walks the sources
grouping same-named ones **within the instance** (`strcmp` on the OSDI
descriptor's `noise_sources[].name`) and sums signed amplitudes
`sign(pwr_k)·sqrt(|pwr_k|)·T_k` coherently before squaring:

- a uniquely-named source reduces *exactly* to the classic `|pwr|·|T|²`;
- the group's power is assigned to the group's **first** source (its
  `onoise_<inst>_<name>` vector shows the group total; members show 0), so the
  per-source reporting, log-slope integration and total-noise machinery are
  untouched;
- grouping is per-instance by construction (the loop runs inside one
  instance's descriptor), so identical names in *different* instances — or in
  the RFSPICE S-parameter noise path, which keeps the independent per-source
  form — remain uncorrelated, as they must.

## What now works (`noisecorr_examples/`, all exact)

With PSD `1e-12` sources on a unity-transfer series chain (`sqrt`-PSD amplitude
`1e-6 V/√Hz` each):

| case | onoise before | onoise after |
|---|---|---|
| same name twice | 1.414e-6 | **2e-6** (amplitudes add) |
| distinct names | 1.414e-6 | 1.414e-6 (unchanged) |
| same name, one negated | 1.414e-6 | **0** (anti-phase cancels) |
| `2*wn(S,"n") + wn(S,"n")` | 2.236e-6 | **3e-6** (linear weights) |
| same name, two instances | 2.828e-6 | 2.828e-6 (unchanged) |
| white + flicker, one name | 1.414e-6 @1Hz | **2e-6** (kind-agnostic) |

`verify_noisecorr.py`: 7/7 PASS. Full version11 regression: 38/38 suites PASS
(including the Enhancement-9 noise_table suite, byte-identical results — all
its sources are uniquely named).

## Notes

- Unnamed noise functions get compiler-synthesised unique names, so they can
  never group accidentally.
- Correlation is *total* (same source). Partial correlation is out of scope —
  the LRM models it by composing shared and private named sources, which this
  enhancement makes work.
