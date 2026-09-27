# Enhancement-748: the native `nport` device has thermal noise — a passive block imported from a Touchstone file contributes 4kT·Re(Y) to `.noise` and to the noise figure of `.sp`, as correlated sources between its ports

**Scope:** F9 of the
[Touchstone-import hunt](../docs/bug_hunts/2026-09-26_touchstone-import.md),
for the native backend. `src/spicelib/analysis/nevalsrc.c` and
`src/include/ngspice/noisedef.h` (`NevalSrcVec`, a correlated multi-node
source, usable by any device), `src/spicelib/devices/nport/nportnoise.c`
(new: `NPORTnoise`), `nportdefs.h` (the per-instance noise state),
`nportinit.c`, `nportext.h`, `Makefile.am`, `examples/nport_native_examples/`
(six checks). **ngspice only.** The `-osdi` route's emitted Verilog-A is
untouched and stays noiseless (below).

**Suites:** [`nport_native_examples`](../examples/nport_native_examples/) 18
of 18 per solver, both solvers (12 of 18 on the E-747 binary); `noise`,
`noisecorr`, `noisefigure`, `rfanalyses`, `savenoise`, `noiseloop`,
`lrmnoise`, `noisejw`, `modelnoise`, `noisetable`, `presnp` unchanged; full
sweep 532 of 532.

## What was wrong

E-242's device table had no noise entry, and nothing in the fit file says
anything about noise. A block imported from a measured filter, package or
cable therefore contributed nothing to `.noise`, and the noise figure `.sp`
computes through it was that of the surrounding circuit only. Measured on
the hunt's RC two-port, `noise v(p2) Vin lin 1 1meg 1meg`:

| block | `onoise_spectrum` at 1 MHz |
|---|---:|
| built-in R and C | 1.090e-9 V/√Hz |
| `pre_snp -native` | 3.447e-13 V/√Hz — the 1 GΩ load's noise through the block, nothing from the 100 Ω |

The physics is fixed by the data the block already carries. A passive
linear N-port at temperature T has, between its ports, the noise-current
correlation matrix C(f) = 4kT·Re(Y(f)) (Bosma's theorem, the generalized
Nyquist relation): the diagonal is each port's thermal noise, the
off-diagonal the correlation a shared loss puts between ports.

## What changed

**A correlated multi-node source for the noise evaluator.** `NevalSrcVec`
evaluates one noise process of density `psd` injecting `amp[k]·n(t)` from a
reference node into node k for every k — a rank-one correlation
`psd·amp·ampᵀ`. Its output density is `|Σ_k amp_k·T_k|²·psd` with `T_k` the
adjoint transfer from (node k, ref), the quantity `NevalSrc` reads for a
two-node source; under the S-parameter noise analysis the same per-port
machinery `NevalSrc` uses (the adjoint per port, the conversion through the
port admittances, the accumulation into the noise correlation matrix) is
applied to the summed source. It sits beside `NevalSrc` and `NevalSrc2` in
`noisedef.h` for any device with a correlated set of sources.

**The device's noise function.** At each frequency `NPORTnoise` forms C =
4kT·sym(Re Y(jω)) from the fit through `NPORTadmittance`, decomposes it
(cyclic Jacobi, N×N) into C = Σ λ_m v_m v_mᵀ, and evaluates each term with
λ_m > 0 as one independent source of density λ_m and amplitude v_m through
`NevalSrcVec`. The temperature is the circuit's, as for a resistor without
`temp=`. Re(Y) is symmetrized before the decomposition — a fit of a
reciprocal network is symmetric, and the theorem is stated for passive
blocks — and a negative eigenvalue, which a non-passive fit can carry, is
dropped: no source can be negative. The bookkeeping (the last density, the
integrated output and input noise, the summary vectors) follows the
resistor's; the device carries one summary source per instance,
`onoise_<inst>` and the `_total_` pair.

## Verification

Six checks in `verify_nport_native.py`, no compiler, both solvers, each
against a built-in twin of the same admittance whose noise ngspice has
always had:

| network | twin | result |
|---|---|---|
| the RC one-port (G = 1 mS, C = 1 nF) behind 1 kΩ, `noise v(p1)` at 0.1, 1, 10 MHz | R‖C | equal to 1e-6 |
| the Pi two-port, g to p2 through 1 kΩ and 4 kΩ | a series 1 kΩ between the ports and two shunt capacitors | equal to 1e-6 — the series resistor's noise current enters the two ports with opposite signs, fully correlated: the off-diagonal of 4kT·Re(Y) |
| the RLC one-port (Re Y from the fit's pole pair, frequency-dependent), around resonance | the series R-L-C | equal to 1e-5 |
| `.temp 77` | the same twin at 77 | equal to 1e-6, and the amplitude scaled by √(350.15/300.15) from the 27 °C run |
| the resistor quiet (`noisy=0`), `noise ... 1` | — | `onoise_n1` exists and is the whole spectrum |
| `.sp lin 1 1meg 1meg 1` through the Pi block | the twin | NF 13.612351 dB both, to 1e-6 |

On the E-747 binary the six fail: the block's share is missing from every
spectrum, the summary vector does not exist, and the block's NF is that of
the ports alone. The eleven noise suites and `presnp` are unchanged.

## What this does not do

* **The `-osdi` route stays noiseless.** The Verilog-A the converter emits
  has no noise source, and Verilog-A cannot express a frequency-shaped,
  port-correlated `4kT·Re(Y(f))` with its `white_noise` and `flicker_noise`
  primitives; giving that route noise means filtering white sources through
  the same `laplace_nd` states, a separate piece of work. Until then, a
  block whose noise matters should be imported with `pre_snp -native`.
* The theorem is for passive blocks in thermal equilibrium. An amplifier's
  Touchstone file describes its gain, not its noise; its noise parameters
  are the rows both readers still refuse (the hunt's F2 and F4), and no
  correlation matrix is built from them.
* No instance temperature: the block is at the circuit's temperature. A
  `temp=` on the instance line, as a resistor has, is not added.
* A non-passive fit's negative eigenvalues are dropped silently; E-745's
  limit and `pre_snp`'s passivity note are the signals for such a fit.
