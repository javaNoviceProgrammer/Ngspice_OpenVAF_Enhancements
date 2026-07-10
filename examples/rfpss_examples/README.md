# PSS (periodic steady state) — Enhancement-117

Periodic steady state analysis (`.pss`) computes the periodic operating point of a
driven or autonomous (oscillator) circuit directly, via a shooting method, instead
of integrating transients until they settle. It is the foundation of the RF
periodic small-signal suite (PAC / pnoise / PXF, future work).

Before Enhancement-117 PSS was experimental: it was gated behind the
`--enable-pss` configure flag — so `.pss` was an *"unimplemented dot command"* in
every shipped ngspice — and, when enabled, it printed ~230 lines of shooting-loop
trace to stderr per run. E-117 makes PSS **build by default** and routes the
per-iteration trace through `set ngdebug`, so normal runs show a clean converged
summary and the harmonic table.

## `.pss` syntax

```
.pss Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff [uic]
```

| field | meaning |
|---|---|
| `Fguess` | initial guess for the fundamental frequency |
| `StabTime` | stabilization time run before shooting starts |
| `OscNode` | the probe/oscillation node |
| `Points` | time samples per period (for the DFT) |
| `Harmonics` | number of harmonics reported |
| `SC_iter` | maximum shooting-cycle iterations |
| `Steady_coeff` | steady-state detection coefficient |
| `uic` | optional — use initial conditions |

## `rc_pss.cir`

A 1 MHz-driven RC low-pass (`R=1k`, `C=1n`). PSS converges to the drive frequency
and its fundamental harmonic equals the analytic AC response
`|H(1MHz)| = 1/sqrt(1 + (2*pi*f*R*C)^2) = 0.15714`. `verify_rcpss.py` checks the
converged frequency, the fundamental magnitude, and that the default output is
free of shooting-loop trace.

**Note:** PSS is a shooting method — it simulates many drive periods — so this
deck takes ~1–2 minutes and is intentionally run under a single linear solver.

To see the full shooting-loop diagnostics, add `set ngdebug` in the `.control`
block before `run`.

## RF periodic small-signal suite (Enhancements 119–121)

Built on the retained PSS operating point, `rc_pss.cir` also exercises the periodic
small-signal chain that leads to periodic AC (PAC):

- **E-119** retains the converged periodic operating point (node voltages + device
  states per sample) on the analysis job instead of freeing it.
- **E-120** turns it into the harmonics `G_k`, `C_k` of the periodically
  time-varying device Jacobian `G(t) = ∂I/∂V`, `C(t) = ∂Q/∂V`.
- **E-121** assembles those harmonics into the **harmonic conversion matrix**
  `H_{nm} = G_{n−m} + j·ω_m·C_{n−m}` (size `(2M+1)N`) and solves it — injecting a
  unit current at the osc node in the 0-th sideband and reporting the response at
  each sideband `f_in + k·f0`. This is the numerical engine of PAC / periodic
  noise / PXF.

For the linear RC the conversion matrix is block-diagonal, so the sideband-0
response equals the ordinary AC driving-point impedance at `f_in = f0/2`
(`|Z| = 1/|1/R + j·2π·f_in·C| = 303.3 Ω`) and the ±1 sidebands carry no converted
energy — exactly what a non-mixing circuit should show. `verify_rcpss.py` checks
all of this. A pumped nonlinear circuit fills the off-diagonal blocks and produces
real conversion gain through the same path.

## `.pac` command (Enhancement-122)

`rc_pac.cir` drives the same RC through the user-facing **periodic-AC** command:

```
.pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
     <DEC|OCT|LIN> Npts Fstart Fstop
```

The first seven fields are the `.pss` parameters (PAC runs a PSS to find the
operating point it linearizes around); the tail is an `.ac`-style sweep. `.pac`
runs PSS, then sweeps the small-signal input frequency and, at each point, solves
the E-121 conversion matrix — emitting the **0-th-sideband node responses** as a
complex `PAC Analysis` plot you read back with `print`/`plot`/`wrdata`:

```
.pac 1meg 1u b 1024 10 50 5u dec 10 10k 1meg
```

For the linear RC the swept sideband-0 response at node `b` equals the AC
driving-point impedance `|Z(f)| = 1/|1/R + j·2π·f·C|` across the whole band —
998 Ω at 10 kHz down to 157 Ω at 1 MHz. `verify_rcpac.py` asserts every swept
point against `|Z(f)|` (worst-case `1.6e−7`). A pumped nonlinear circuit's
sideband-0 response is the genuine periodic-AC response (differs from a plain
`.ac`) through the same path.

### Source-referenced stimulus and conversion sidebands (Enhancement-123)

`.pac` takes an optional trailing `maxsideband` and honours a netlist `AC` source:

```
.pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
     <DEC|OCT|LIN> Npts Fstart Fstop [maxsideband]
```

- **Source-referenced stimulus** — if a source carries an `AC <mag>` spec (as in
  `.ac`), that source is the PAC input, so the result is a **transfer / conversion
  gain**, not a driving-point impedance. `rc_pac_src.cir` drives
  `V1 a 0 DC 0 AC 1 SIN(0 1 1meg)`, so the sideband-0 response at `b` is the
  low-pass transfer `|H(f)| = 1/√(1 + (2πfRC)²)` (0.998 at 10 kHz → 0.157 at
  1 MHz) — a thousand-fold different from the unit-current driving-point impedance.
- **Multi-sideband output** — `maxsideband = Ksb` emits the response at every
  conversion sideband `f_in + k·f0` (`k = −Ksb … Ksb`). Sideband 0 keeps the node
  name (`plot b`); the conversion sidebands are `b_usb1`, `b_lsb1`, … For the linear
  RC they are ~0 (no mixing); a pumped nonlinear circuit fills them with real
  conversion gain.

`verify_rcpac.py` checks both the E-122 (unit-current) and E-123 (source +
sidebands) decks.

**Note:** `.pac` runs a PSS shooting method (~2 minutes per deck) and
`verify_rcpac.py` runs under the Sparse solver only.

## `.pnoise` command — periodic noise (Enhancement-124)

`.pnoise` propagates **noise** through the periodic operating point. Each device's
noise sources are converted between sidebands, and the output noise at a frequency
is every source folded through the harmonic conversion matrix:

```
.pnoise Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
        OutNode InSrc <DEC|OCT|LIN> Npts Fstart Fstop
```

It reuses ngspice's device noise routines unchanged: it solves the **adjoint** of
the conversion matrix (`Hᵀ Ψ = e_{out,0}`), loads the sideband-`k` transfer into
`CKTrhs`/`CKTirhs`, and calls each device's noise routine once per sideband,
accumulating `Σ_k S·|ΔΨ_k|²` — so resistors, OSDI/Verilog-A devices, and transistors
all fold correctly. Output is a `PNoise Analysis` plot with `onoise_spectrum` and
`inoise_spectrum`.

`rc_pnoise.cir` runs it on the RC (output `b`, input `v1`):

```
.pnoise 1meg 1u b 1024 10 50 5u b v1 dec 10 10k 1meg
```

For this linear circuit the conversion matrix is block-diagonal, so only sideband 0
contributes and `.pnoise` reduces to ordinary `.noise`: the output noise density is
the thermal-noise result `4·k·T·R1 / (1 + (2πf·R1·C1)²)` (1.65e−17 V²/Hz at 10 kHz →
4.10e−19 at 1 MHz). `verify_rcpnoise.py` checks it against both the analytic law and
a plain `.noise` run (which it matches to every digit). A pumped nonlinear circuit
folds noise between sidebands (up/down-conversion, phase noise) through the same
path.

### Cyclostationary noise (Enhancement-126)

The E-124 `.pnoise` above evaluates each device's noise PSD at one operating point.
For a **pumped** device whose noise depends on the bias (a diode's shot noise
`2qI(t)`, a resistor's flicker `∝|I(t)|²`) that PSD varies along the PSS period. A
trailing `cyclo` keyword switches to the cyclostationary treatment:

```
.pnoise <pss> OutNode InSrc <DEC|OCT|LIN> Npts Fstart Fstop cyclo
```

It evaluates the noise at **every** PSS sample's bias and folds it through the
*time-domain* adjoint transfer `A_s(j) = Σ_k Ψ_k(j)·e^{j2πks/P}`, averaging over the
period: `onoise(f) = (1/P)·Σ_s S(t_s)·|ΔA_s|²`.

- **Reduction** — for a bias-independent source (a resistor's thermal noise), `S(t)`
  is constant and by Parseval the cyclostationary result reduces *exactly* to the
  stationary one; on the linear RC it matches `.noise` to every digit.
- **`rc_flicker_cyclo.cir`** — a resistor with a flicker model carries the RC current
  `I(t)`, so its flicker noise is cyclostationary. With a flat transfer the output
  satisfies `onoise·f = R1²·KF·⟨I²⟩` (a constant, `4.88e−10` here), using the
  period-**average** `⟨I²⟩` rather than a single sample. `verify_rccyclo.py` checks
  both the reduction and this quantitative result.

## `.pxf` command — periodic transfer function (Enhancement-125)

`.pxf` is the **adjoint** of `.pac`: it fixes one output and gives the transfer from
the input at each sideband, completing the PSS → PAC → Pnoise → PXF suite.

```
.pxf Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
     OutNode <DEC|OCT|LIN> Npts Fstart Fstop [maxsideband]
```

It solves the adjoint of the conversion matrix (`Hᵀ Ψ = e_{out,0}`) and dots each
sideband block of `Ψ` with the netlist AC-source pattern to get the input→output
transfer `xf_k = Σ_j Ψ_k(j)·B0(j)`. Output is a `PXF Analysis` plot with `xf`
(sideband 0) plus `xf_usb<k>`/`xf_lsb<k>`.

`rc_pxf.cir` runs it on the RC (output `b`, input `V1 AC 1`):

```
.pxf 1meg 1u b 1024 10 50 5u b dec 10 10k 1meg 1
```

By the identity `(H⁻¹B)_out = (H⁻ᵀe_out)ᵀB`, the sideband-0 transfer is **exactly**
the PAC response `mag(b)` — the low-pass transfer `1/√(1+(2πfRC)²)` (0.998 at 10 kHz
→ 0.157 at 1 MHz) — a reciprocity cross-check between the adjoint and forward solves.
The conversion sidebands `xf_usb1`/`xf_lsb1` are ~0 (a linear circuit does not
convert). `verify_rcpxf.py` checks `xf` against the analytic transfer and the
sidebands against zero.
