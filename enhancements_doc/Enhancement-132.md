# Enhancement-132 — periodic S-parameters (`.psp`)

A new analysis, **`.psp`**, computes **periodic small-signal S-parameters**: the
scattering matrix of a circuit linearised around a **periodic** (large-signal)
operating point, including conversion between the input frequency and its
**sidebands** `f_in + k·f0`. This is the S-parameter view of a mixer, switched
circuit, or any periodically-pumped network — where an ordinary `.sp` (which
linearises around a static DC point) cannot see the frequency conversion.

`.psp` sits on top of the PSS → conversion-matrix suite (E-117–126): it reuses the
periodic operating point (E-119), the harmonic Jacobian (E-120), and the same
`(2M+1)N` conversion matrix the PAC / pnoise / PXF analyses share (E-121). It also
reuses the RFSPICE port framework (`portnum` / `z0` on voltage sources) and the
exact power-wave convention of `.sp`.

## Usage

```
* ports are voltage sources tagged with portnum + z0 (as for .sp)
V1 in  0 DC 0 AC 1 portnum 1 z0 50
V2 out 0 DC 0 AC 1 portnum 2 z0 50
...
* .psp Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff
*      <DEC|OCT|LIN> NumPts Fstart Fstop [maxsideband]
.psp 1meg 1u osc 1024 10 50 5u dec 20 10k 1meg 1
.control
run
print s_2_1 s_1_1                 ; sideband-0 S-parameters
print s_2_1_usb1 s_2_1_lsb1       ; ±1 conversion sidebands (with maxsideband ≥ 1)
.endc
```

- The leading arguments are the ordinary **PSS** parameters (guessed frequency,
  stabilisation time, oscillator/probe node, sample points, harmonics, shooting
  iterations, steady-state coefficient) — identical to `.pss` / `.pac`.
- Then a frequency sweep of the small-signal **input** frequency:
  `<dec|oct|lin> NumPts Fstart Fstop`.
- Optional trailing **`maxsideband`** `Ksb` emits the conversion sidebands: the
  output vectors are `S_<j>_<i>` (sideband 0) plus `S_<j>_<i>_usb<k>` /
  `S_<j>_<i>_lsb<k>` for the upper/lower conversion bands. `S_<j>_<i>` is the
  wave from source port *i* to measured port *j*.

Output is a complex `PSP Analysis` plot vs frequency; sideband-0 uses the plain
`S_j_i` names so it lines up directly with an ordinary `.sp` run.

## How it works

After PSS converges, `psp_sweep` (in `dcpss.c`):

1. extracts the Jacobian harmonics once (`pac_extract_harmonics`, E-120/121);
2. at each swept input frequency, **excites each RF port in turn** — driving that
   port's voltage source to 1 in the 0-th sideband through the conversion matrix
   (exactly as `.sp`'s `VSRCspupdate` does, so the other ports stay `z0`-terminated
   by the `g0 = 1/z0` shunt already stamped in the Jacobian);
3. reads each port's voltage and branch current at every sideband and forms the
   **Kurosawa power waves** `a = ki·(V + z0·I)`, `b = ki·(V − z0·I)` with
   `ki = 1/(2√z0)` — the same definition `.sp` uses;
4. assembles the incident matrix `A` (sideband 0) and one scattered matrix
   `B^(k)` per output sideband, and computes `S^(k) = B^(k) · A⁻¹` with the dense
   complex library (`cinverse` / `cmultiply`) `.sp` also uses.

Because `S = B·A⁻¹` is **invariant to the excitation basis**, driving each port
with a unit voltage yields the same S as `.sp`'s power-wave excitation. For a
**time-invariant** circuit the conversion matrix is block-diagonal (all Jacobian
harmonics above `h = 0` vanish), so the sideband-0 block reduces **exactly** to the
ordinary `.sp` S-matrix and every conversion sideband is zero.

Implementation notes: `pac_solve_at`'s conversion-matrix assembly was factored into
a shared `pac_build_matrix` used by both the PAC solve and the new per-port PSP
solve `psp_solve_port`; a `PSSdoPSP` flag + `psp` PSS parameter carry the mode; the
`.psp` card is parsed by `dot_psp` (a sibling of `dot_pac`). **Sparse-solver only**,
like the rest of the PSS suite.

## Verification

`verify_psp.py` builds each network, runs `.sp` (reference) and `.psp`, and
compares the complex S-parameters. For a time-invariant circuit PSP's sideband 0
must equal `.sp` exactly and its conversion sidebands must be zero (7/7 checks):

- **resistive 2-port** — `S = B·A⁻¹` matches `.sp` to ~10⁻¹⁶.
- **reactive 2-port** (R + series L + shunt C) — complex S (magnitude **and**
  phase) matches `.sp` across a 100–500 MHz sweep, `max |ΔS| = 0`.
- **1-port reflection** — 75 Ω on a 50 Ω port gives Γ = 0.2 exactly (N-general
  machinery down to a single port).
- **3-port resistive star** — matches `.sp` for N > 2.
- **conversion sidebands** — with `maxsideband = 1`, a time-invariant network's
  ±1 conversion terms are ~10⁻¹⁷ while sideband 0 is not (the sideband machinery is
  exercised and correctly yields zero conversion with no pumping).
- **reciprocity** — `S21 == S12` for a passive network.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `psp_sweep` (per-port conversion-matrix solve → periodic S-matrix) + `psp_solve_port`; `pac_build_matrix` factored out of `pac_solve_at`; PSP dispatch in `DCpss` |
| `ngspice-46/src/spicelib/parser/inp2dot.c` | `dot_psp` parser + `.psp` card dispatch |
| `ngspice-46/src/spicelib/analysis/psssetp.c` | `psp` PSS parameter (setter + table) |
| `ngspice-46/src/include/ngspice/pssdefs.h` | `PSSdoPSP` flag + `PSP_DOPSP` param id |
| `examples/psp_examples/` | `verify_psp.py` |

## Scope

Periodic small-signal S-parameters around a PSS operating point, verified to reduce
exactly to `.sp` for time-invariant networks (1/2/3-port, resistive and reactive,
magnitude and phase) with correctly-zero conversion sidebands. The conversion
machinery is N-port and multi-sideband by construction, so a pumped network reports
its frequency-conversion S-parameters; a fast, analytically-checked pumped-mixer
reference (mixer conversion gain vs an ideal-switch model) is the natural
follow-up, along with periodic noise figure and a Touchstone writer for the
sideband blocks.
