# Laplace-domain transfer-function examples (version5)

Self-contained correctness examples for OpenVAF/ngspice **Laplace
transform filter** operator support (`laplace_nd`/`laplace_np`/
`laplace_zd`/`laplace_zp`), covering **DC**, **AC**, and **transient**
analysis. Everything here uses the **version5** toolchain:

- compiler : `../OpenVAF-master-20260610/target/release/openvaf-r` (or `../bin/macos/apple-silicon/openvaf-r`)
- simulator: `../bin/macos/apple-silicon/ngspice`

See `../Enhancement-4.md` (Part 1) for the full implementation writeup.

## The model: a first-order RC-style low-pass filter

`laplace_lpf.va` realizes `H(s) = 1/(1+tau*s)` purely via `laplace_nd`,
with no actual resistor/capacitor in the model — the pole comes entirely
from the operator's internal state-space realization:

```verilog
`include "disciplines.vams"

module laplace_lpf(in, out);
    input in;
    output out;
    electrical in, out;

    parameter real tau = 1e-6 from (0:inf);

    analog begin
        V(out) <+ laplace_nd(V(in), '{1.0}, '{1.0, tau});
    end
endmodule
```

`'{1.0}'` is the numerator polynomial `1` (constant), `'{1.0, tau}'` is
the denominator polynomial `1 + tau*s` (ascending powers of `s`). At
compile time this is converted into a single-state controllable-canonical
realization (one implicit equation, `dx/dt = -x/tau + V(in)`,
`V(out) = x/tau`) — see `../Enhancement-4.md` §2.1 for the general
derivation. Array-literal arguments may also be written without the
leading apostrophe (`{1.0}` instead of `'{1.0}'`) — both spellings are
accepted identically (see `../Enhancement-4.md` §3.1).

`laplace_variants.va` exercises all **four** `laplace_*` forms side by
side, to cross-check the coefficient-array and root-array (pole/zero)
code paths against each other:

```verilog
V(out_nd) <+ laplace_nd(V(in), '{1.0}, '{1.0, tau});               // H(s) = 1/(1+tau*s)
V(out_np) <+ laplace_np(V(in), '{1.0/tau}, '{-1.0/tau});           // same H(s), pole form
V(out_zd) <+ laplace_zd(V(in), '{-2e6}, '{3e12, 4e6, 1.0});        // 2nd-order, zero + den-poly form
V(out_zp) <+ laplace_zp(V(in), '{-2e6}, '{-1e6, -3e6});            // same 2nd-order system, full pole/zero form
```

`laplace_zd_only.va` is a single-call isolation fixture used to
cross-check `laplace_variants.va`'s `out_zd` result column-by-column.

`laplace_mixed_var_literal.va` exercises mixing an **array-variable**
argument with an **array-literal** argument in the same `laplace_zd`
call — a bare reference to a module-body array variable (`zero_coeffs`,
declared `real [0:0] zero_coeffs;`) stands in for the zero-list array
literal, while the denominator is still given as an ordinary `'{...}'`
literal:

```verilog
real [0:0] zero_coeffs;
analog begin
    zero_coeffs[0] = -2e6;
    V(out) <+ laplace_zd(V(in), zero_coeffs, '{3e12, 4e6, 1.0});
end
```

See `../Enhancement-4.md` Part 3 (§17-21) for why this needed dedicated
(if contained) compiler support beyond Parts 1 and 2 individually.

## The test circuit

All three `.cir` files for the primary model instantiate `laplace_lpf`
with `tau=1e-6` (a 1us time constant, corner frequency
`f_pole = 1/(2*pi*tau) ≈ 159.2 kHz`) and a single voltage source driving
`in`:

```
.model lpf1 laplace_lpf (tau=1e-6)
Ndut in out lpf1
```

## Results

| Analysis | Sweep | Expected | Observed |
|---|---|---|---|
| DC | `V(in)` from −2V to 2V | `out = V(in)` exactly (`H(0) = 1/(1+0) = 1`) | exact 1:1 match across the sweep |
| AC | 1 kHz – 1 GHz | single-pole Bode: 0 dB / 0° well below `f_pole`, **−3.0 dB / −45.0°** exactly at `f_pole`, −20 dB/decade rolloff above it, phase → −90° | matches analytically — e.g. 158.5 kHz → −2.99 dB, −44.88° |
| Transient | 0→1V step at `t=0` | exponential rise, `V(out) = 1 - e^(-t/tau)` | `V(out) = 0.6321` at `t = tau` (exactly `1 - e^-1`) |

<p align="center">
  <img src="dc.png" width="32%">
  <img src="ac.png" width="32%">
  <img src="tran.png" width="32%">
</p>

The four-forms cross-check (`dc_variants.cir`) confirms `laplace_nd` and
`laplace_np` agree exactly on `H(0)=1`, and `laplace_zd`/`laplace_zp`
agree exactly on the second-order system's `H(0) = 2e6/3e12 ≈ 6.667e-7`
(`out_zd = out_zp = 1.3333e-6` at `V(in)=2.0`).

`dc_mixed.cir` confirms the array-variable/array-literal mixed-argument
form agrees too: `V(out) = 1.3333e-6` at `V(in) = 2.0`, exactly
`2.0 · 6.667e-7`.

## Diagnostics (not included as `.cir`/CI fixtures, verified by hand — see Enhancement-4.md §15)

- Improper transfer functions, `zi_*` (z-domain) filters, and a handful of
  other narrower gaps are documented as known limitations in
  `../Enhancement-4.md` §8.

## Layout

```
laplace_examples/
  laplace_lpf.va         first-order H(s) = 1/(1+tau*s) via laplace_nd
  laplace_lpf.osdi       compiled with version5 openvaf-r (macOS/Apple Silicon snapshot)
  laplace_variants.va    all four laplace_* forms, two equivalent transfer functions
  laplace_variants.osdi  compiled with version5 openvaf-r (macOS/Apple Silicon snapshot)
  laplace_zd_only.va     isolated laplace_zd fixture (cross-check helper)
  laplace_zd_only.osdi   compiled with version5 openvaf-r (macOS/Apple Silicon snapshot)
  laplace_mixed_var_literal.va   array-variable + array-literal argument mix
  laplace_mixed_var_literal.osdi compiled with version5 openvaf-r (macOS/Apple Silicon snapshot)
  dc_sim.cir             DC sweep of V(in), laplace_lpf
  ac_sim.cir             AC sweep 1kHz-1GHz, laplace_lpf
  tran_sim.cir           step response, laplace_lpf
  dc_variants.cir        DC sweep, all four laplace_* forms
  dc_zd_only.cir         DC sweep, isolated laplace_zd
  dc_mixed.cir           DC sweep, array-variable + array-literal mix
  _setup.sh              picks the right bin/<os>/<arch> binaries and recompiles
                         all four models for this platform (sourced by run_examples.sh)
  run_examples.sh         runs dc/ac/tran/dc_variants/dc_zd_only/dc_mixed with
                         ngspice and writes the corresponding .txt files
  plot_results.py        plots dc/ac/tran.txt (laplace_lpf) to dc/ac/tran.png
  dc.txt, ac.txt, tran.txt        raw wrdata output from the last laplace_lpf run
  dc_variants.txt, dc_zd_only.txt,
  dc_mixed.txt                    raw wrdata output from the cross-check runs
  dc.png, ac.png, tran.png        plotted laplace_lpf results (see above)
```

`dc_sim.cir`/`ac_sim.cir`/`tran_sim.cir`/`dc_variants.cir`/
`dc_zd_only.cir`/`dc_mixed.cir` reference `OSDIFILE`/`OSDIFILE_VARIANTS`/
`OSDIFILE_ZD`/`OSDIFILE_MIXED`/`RESULTFILE` placeholders rather than
hardcoded paths — `run_examples.sh` substitutes them at run time, so the
checked-in netlists stay portable across machines and OS/architectures.

## Reproduce

```bash
# run DC, AC, transient, and the cross-checks (compiles all three models
# for this platform first)
bash run_examples.sh

# plot the laplace_lpf results
python3 plot_results.py
```
