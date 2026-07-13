# Exact separable cyclostationary folding + the HB DC-source fix (Enhancement-178)

E-177 fixed folded flicker in the *stationary* periodic-noise loops and left
the *cyclostationary* mode documented as frequency-flat-limited: its identity
`onoise = (1/P)Σ_s S(t_s)|A_s|²` cannot see that noise folded from sideband q
originates at |f + q·f0|. This enhancement removes the limitation exactly —
and its cross-machinery check caught a second bug that had silently doubled
every DC bias voltage inside both harmonic-balance solvers.

## The exact separable model

For S(t, f) = m(t)²·g(f) — a colored stationary process amplitude-modulated
along the orbit — the exact output noise is

    onoise(f) = Σ_g Σ_q |B_q(g)|² · g_g(|f + q·f0|)
    B_q(g)    = (1/P) Σ_s m_g(t_s)·dA_s(g)·e^{+jq·θs},  A_s(j) = Σ_k Ψ_k(j) e^{−jk·θs}

Per-generator amplitudes are recovered with **no device-API change**: the
noise-summary machinery gives one density per generator, and load
**polarization** against a fixed reference load R = Ψ₀ (five `DEVnoise` sweeps
per orbit sample: A±R, A±jR, R) extracts `ĉ = √S·dA` up to a phase that
cancels in |B_q|². Spectral shapes are **measured pointwise** at the folded
frequencies (`noise_table` works). Flat generators keep the original identity
(exact for any quadratic form, including correlated pairs). The stationary
limit reduces to the E-177 sum, the flat limit to the old identity (Parseval).
Ported 2-D to `qpnoise … cyclo` at |f + q1·f1 + q2·f2|.

## The physics: flicker sees ⟨m⟩², white sees ⟨m²⟩

For modulation far above the analysis band only the DC of the envelope m(t)
feeds the 1/f band — the AC components are shifted to ±f0, ±2f0 sidebands
where 1/f is negligible. The old identity collapsed *all* envelope power onto
the analysis frequency: 23% high (π²/8) for |sin|-modulated flicker, **34%
high** on the conversion circuit here. The new sweep lands on a from-scratch
referee to ≤3e-4.

![cyclofold](cyclofold.png)

## The HB DC-source bug the cross-machinery check caught

Running the same circuit through the **QPSS-HB orbit** came out exactly
**4×**. A differential experiment (AF = 0/1/2 → ratio 1/2/4) pinned a doubled
bias current; a trivial `VDC=1` deck showed `2.000000` in the harmonic table.
Both HB Newtons (`hb`, `qpss … hb`) fold the settle-mode rhs — which already
carries the DC source values — into I_R, then subtract `λ·Is` which carries
them **again**: every DC bias voltage converged to exactly 2×, corrupting all
bias-dependent noise and conversion (flicker ∝ I^AF off by 2^AF) while every
AC-driven validation stayed exact (the fourth accidental-correctness
occurrence: E-171, E-175, E-177). Fixed: the unscaled DC source block is added
back, making the net DC drive exactly −λ·Is_DC. With it, `qpnoise … cyclo`
agrees with `pnoise … cyclo` **digit-for-digit** across the two orbit
machineries.

## Files

- **`verify_cyclofold.py`** — 6 checks × both solvers: exact referee (≤0.5%),
  old flat-model signature absent, white cyclo ≡ stationary (Parseval,
  digit-exact), the (8/π²)⟨I²⟩ law (≤2%), LTI limit ≡ `.noise`, two-tone
  collapse (≤0.5%).
- **`make_cyclofold_fig.py`** → **`cyclofold.png`**, **`cyclofold_demo.cir`**.

## Running

```sh
python3 verify_cyclofold.py     # 6 checks x {sparse, klu}
python3 make_cyclofold_fig.py   # figure
ngspice -b cyclofold_demo.cir   # demo
```
