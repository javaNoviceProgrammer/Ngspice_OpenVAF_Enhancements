# pnoise noise-folding referee + the folded-flicker frequency fix (Enhancement-177)

The E-175 RF audit left one honest gap: periodic noise analysis was *correct by
construction, not correct by measurement* — the folding of device noise through
LPTV conversion had never been checked against anything independent. This
enhancement builds that referee — and it caught a real bug.

## The referee (three independent layers)

1. **From-scratch Python conversion matrix** for a 1-node LPTV-conductance
   circuit (`G(t) = g0 + g1·sin(ω0t)` pumping node b, fed by a noisy 10k):
   `onoise(f) = Σ_k |Z_k(f)|²·S(|f + k·f0|)` — same physics, zero shared code.
2. **TRNOISE transient Monte-Carlo** (no shared code *or theory*): the same
   noise injected as a time-domain source, 198-segment Welch PSD, pumped vs
   unpumped ratio — cancels the TRNOISE amplitude convention entirely.
3. **LTI and white limits** anchored to plain `.noise`.

White-noise folding: pnoise matched the referee to **6 digits** — the sideband
bookkeeping (adjoint, thermal density, sum) was measured-correct. The MC
arbiter confirmed the ~1.86× pumped/unpumped folding ratio within statistical
error.

## The bug the referee caught

The stationary `pnoise`/`qpnoise`/`phasenoise` sideband loops set the
noise-evaluation frequency **once, to the output frequency**. But the
sideband-k adjoint carries noise that **originates at |f + k·f0|** — a
frequency-dependent source PSD (flicker `1/f`, `noise_table`) must be
evaluated there. Pre-fix pnoise reproduced the referee's deliberately-wrong
"evaluate-everything-at-f" model **digit-for-digit** (`1.114323e-14` vs
`1.114323e-14` at 1 kHz — a 21% overestimate on this circuit, unbounded as
f ≪ f0); post-fix it reproduces the correct model digit-for-digit
(`9.175472e-15`).

Why nothing caught it before: white noise is frequency-flat, and LTI circuits
have no k≠0 transfer — the third occurrence of the accidental-correctness
pattern (E-171 determinant, E-175 parametric term).

For **`phasenoise`** the same fix matters most: folded far-sideband blocks near
a carrier were evaluated at the tiny offset frequency, inflating the flicker
(1/f³) region.

![pnoisefold](pnoisefold.png)

## Cyclostationary scope note

The `cyclo` mode's time-domain identity (`onoise = (1/P)Σ_s S(t_s)·|A_s|²`)
treats the source PSD as frequency-flat across the folding span — **exact for
modulated-white noise**, and for flicker on conversion-free circuits (the
shipped use cases). Folded flicker through k≠0 conversion cannot be collapsed
into that product with the aggregate device-noise API; use the stationary mode
there (now exact). Documented in `dcpss.c` at both cyclo sites.

## Files

- **`verify_pnoisefold.py`** — 5 checks × both solvers: white folding vs
  referee (≤0.1%), flicker folding vs referee (≤0.5%, sample-0 bias read from
  the retained orbit), pre-fix signature absent, pump/no-pump ratio == referee
  ratio, LTI limit == `.noise`.
- **`make_pnoisefold_fig.py`** → **`pnoisefold.png`**, **`pnoisefold_demo.cir`**.

## Running

```sh
python3 verify_pnoisefold.py     # 5 checks x {sparse, klu}, runs in ~2 s
python3 make_pnoisefold_fig.py   # figure
ngspice -b pnoisefold_demo.cir   # demo
```
