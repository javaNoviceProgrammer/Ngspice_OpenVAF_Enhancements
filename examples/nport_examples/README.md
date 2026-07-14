# N-port Touchstone device — `snp2va.py` (Enhancement-199)

Drop a measured or simulated **S-parameter block** (a filter, cable, connector,
package, or amplifier stored in a Touchstone `.sNp` file) straight into an ngspice
simulation. `snp2va.py` converts the file into a **Verilog-A n-port model** that —
through OpenVAF's OSDI `laplace` machinery — works in **AC *and* transient**, with
no convolution engine to write.

```sh
python3 snp2va.py bandpass.s2p -o bandpass.va -m bandpass   # Touchstone -> Verilog-A
openvaf-r bandpass.va -o bandpass.osdi                      # compile to OSDI
# then in a deck:  N1 p1 p2 mm  /  .model mm bandpass  /  pre_osdi bandpass.osdi
```

## How it works

S-parameters are frequency-domain, so a time-domain model needs a *rational*
representation. The converter builds one:

```
parse Touchstone -> S(f) -> Y(f) -> common-pole vector fit -> Verilog-A
   I(p_i) <+ sum_j [ laplace_nd(V(p_j), num_ij, den) + e_ij*ddt(V(p_j)) ]
```

- **Vector fitting** (Gustavsen) fits every `Y_ij(f)` with a *shared* set of poles.
  The key detail is realizing it in Verilog-A: the strictly-proper (pole) part goes
  through `laplace_nd`, while the `e·s` term — a shunt capacitance, which makes `Y`
  *improper* and can't be represented by `laplace_nd` — is pulled out as an explicit
  `ddt`. `laplace_nd` then gives both the AC response and the transient
  (recursive-state) response for free.
- **Automatic order selection** grows the pole count until the fit converges *or*
  the error stops improving (the "knee") — so a clean model fits to machine
  precision, while noisy measured data is fit at its noise floor rather than
  over-fitted.
- **Stability** is enforced (right-half-plane poles are reflected), so the model is
  always BIBO-stable; **passivity** is checked and reported (`snp2va` warns when a
  noisy fit is non-passive).

Pure Python **standard library** — no numpy. The three primitives vector fitting
needs (least-squares via Householder QR, complex matrix inverse, polynomial roots
via Durand–Kerner) are included.

Touchstone coverage: any port count (`.s1p`, `.s2p`, `.s3p`, …); `S`, `Y`, or `Z`
data; `MA` / `DB` / `RI` formats; `Hz` / `kHz` / `MHz` / `GHz`; arbitrary reference
impedance.

## The sample

`bandpass.s2p` — a series R-L-C bandpass 2-port (resonance ≈ 159 MHz). Converting
and simulating it reproduces the original network to ~5e-6 in AC and ~5e-3 in
transient.

## Verification

`verify_nport.py` — 5 checks, each generating a Touchstone file from a network whose
response is known *exactly*, running `snp2va.py` + OpenVAF, and confirming the device
matches the ORIGINAL network in ngspice: the converter runs and compiles; the device
matches an R-L-C resonator in **AC** (including the transmission peak) and in
**transient** (one model, both analyses); a **3-port** star network converts and
matches on both coupled outputs; and a **noisy** measurement is fit at its noise
floor, reported non-passive, yet stays bounded in transient (stability enforced).

## Running

```sh
python3 verify_nport.py
python3 snp2va.py bandpass.s2p -o bandpass.va && ngspice ...  # see the workflow above
```

## Limitations

Frequency-domain fitting cannot invent behavior outside the tabulated band, so keep
the `.sNp` band wider than the simulation's spectral content. Passivity is *checked
and reported* but not yet *enforced* by residue perturbation; for a non-passive fit
on noisy data, clean the data or pin the order with `--order`. Very high model orders
(sharp, many-resonance blocks) stress the polynomial `laplace_nd` form.
