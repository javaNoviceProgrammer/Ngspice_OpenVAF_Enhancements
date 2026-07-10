# Enhancement-136 — Two-tone Harmonic Balance (frequency-domain QPSS)

The E-133 `qpss` computes a two-tone steady state by running a transient over a few
**beat** periods and DFT-ing the last one. That only works for **commensurate** tones
(a rational ratio, so they share a beat period); genuinely **incommensurate** tones
(an irrational ratio — no common period) are out of its reach, and it produces no
operating point a small-signal analysis could linearize around.

This enhancement adds a **frequency-domain two-tone Harmonic Balance** engine, selected
with a new `hb` keyword:

```
qpss <expr> <f1> <f2> hb [K1] [K2]
```

It is the **true** quasi-periodic steady state — incommensurate-capable — and it retains
its operating point for the small-signal `qpac` (Enhancement-137). The transient path
(`qpss <expr> <f1> <f2> [periods] [maxorder]`, E-133) is unchanged.

## Method

Each node voltage is a **2-D Fourier series** over the truncated harmonic box
`|k1| ≤ K1`, `|k2| ≤ K2`:

```
v(t) = Σ_{k1,k2} V_{k1,k2} · e^{j(k1·ω1 + k2·ω2)·t}
```

The KCL residual `F_{k1,k2} = I_R + [dq/dt] − Is = 0` is driven to zero by Newton with
the **2-D conversion matrix** `H_{(n),(m)} = G_{n−m} + jω_m·C_{n−m}` as the Jacobian —
the direct 2-D analogue of the E-121 matrix. Two ideas make it work for incommensurate
tones:

1. **Devices are sampled on a 2-D *phase* grid `(θ1, θ2)`.** At each grid point the node
   voltages `v(θ1,θ2)` are prescribed and the device loaded, so `G` and `C` are read as
   functions of the two phases — *time never appears*, so there is no common-period
   requirement. A **2-D DFT** gives the difference spectra `G_{d1,d2}`, `C_{d1,d2}`. As in
   E-134, the reactive current needs **no charge extraction** (`dq/dt = C(v)·v'` → the
   `jω·C` term of the conversion matrix), and junction devices are settled per sample.

2. **Sources are captured by an oversampled least-squares APFT.** The `v=0` source RHS
   is sampled at `Nt ≫ Nh` real times and the almost-periodic Fourier transform
   `(ΓᴴΓ) Is = Γᴴb` is solved for the 2-D source spectrum. Oversampling makes `ΓᴴΓ`
   well conditioned where a *square* Vandermonde APFT is catastrophically unstable beyond
   a handful of harmonics.

The dense complex Newton (`pss_csolve`) and the E-135 **source-stepping continuation**
are reused unchanged. Because the linear solver is only used to *read* `G`/`C` off the
device matrix, the engine carries the same `#ifdef KLU` complex-CSC binding as the PAC /
HB extraction and is **solver-independent** (KLU and Sparse bit-identical). A harmonic
box whose tones alias two indices to the same frequency (too commensurate for the order)
is rejected with a clear message rather than producing a singular transform.

## Verification

`verify_qpss_hb.py` (7/7), numpy-free, against analytic two-tone mixing and the E-133
transient:

- **analytic cubic IM3** — for equal tones the small-signal ratio `|IM3(2,−1)| /
  |3rd(3,0)| = 3` exactly;
- **odd nonlinearity** — even-order products vanish;
- **3:1 IP3 slope law** — doubling the drive scales the fundamental ×2 and IM3 ×8;
- **incommensurate tones** (`f2 = √2·f1`, no beat period) — converge to machine
  precision with the correct IM3, which the E-133 transient **cannot** compute;
- **HB vs transient** — the two methods agree on IM3 for a commensurate pair;
- **solver parity** — KLU and Sparse spectra are bit-identical (with a reactive `C`).

E-133's transient `verify_qpss.py` still passes 11/11 unchanged.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | the QPSS-HB engine: `QPSShb` (source APFT + frequency-domain Newton + 2-D spectrum output + operating-point retention), `qp_extract` (2-D phase-grid device sampling + 2-D DFT), `qp_build_matrix` (2-D conversion matrix), `qp_synth`, `qp_free`; retained op-point `qpss_hb_saved` for `qpac` |
| `ngspice-46/src/frontend/com_qpss.c` | detect the `hb` keyword, honour `.option klu`, build the circuit, call `QPSShb` |
| `ngspice-46/src/include/ngspice/cktdefs.h`, `frontend/commands.c` | `QPSShb` prototype; `qpss` help string updated for the `hb` form |
| `examples/qpss_examples/verify_qpss_hb.py` | the 7-check HB-mode suite |

## Scope

Two-tone frequency-domain Harmonic Balance with nonlinear resistive **and** reactive
devices, built-in and OSDI, incommensurate-capable, verified against analytic mixing and
the transient QPSS. The operating point is retained for **QPAC** (Enhancement-137, the
two-tone small-signal analogue of PAC). Follow-ups: more than two tones, a sparse block
solve to scale past the dense `Nh·N` cap, and diamond (total-order) truncation to trim
the harmonic set.
