# Enhancement-199 — N-port Touchstone device (`snp2va.py`)

Instantiate a measured or simulated **S-parameter block** — a filter, cable,
connector, package, or amplifier stored in a Touchstone `.sNp` file — as a circuit
element that works in **AC *and* transient**. ngspice had no native n-port element
(its `.sp` "ports" are tagged voltage sources used to *measure* a circuit's
S-parameters; `rdsnp`/`wrsnp` from [E-64](Enhancement-64.md)/[E-72](Enhancement-72.md)
are reader/writer commands, not a device), so this fills a real gap.

## Approach: Touchstone → Verilog-A, not a native convolution device

S-parameters are frequency-domain; a time-domain model needs a *rational*
representation of the response. Rather than write a native convolution device (with
its own history buffers and stability headaches), `snp2va.py` converts the file into
a **Verilog-A** n-port realized with `laplace_nd`. OpenVAF's OSDI laplace machinery
([E-31](Enhancement-31.md), complex poles) then supplies **both** the AC response and
the transient (recursive-state) response — no convolution code at all.

```
parse Touchstone -> S(f) -> Y(f) -> common-pole vector fit -> Verilog-A
   I(p_i) <+ sum_j [ laplace_nd(V(p_j), num_ij, den) + e_ij*ddt(V(p_j)) ]
```

- **Parse** any port count (`.s1p`, `.s2p`, `.s3p`, …); `S`, `Y`, or `Z` data;
  `MA` / `DB` / `RI` formats; `Hz`–`GHz`; arbitrary reference impedance.
- **Convert to admittance** `Y = (1/z0)(I - S)(I + S)^{-1}`.
- **Vector-fit** every `Y_ij(f)` with a *shared* pole set (Gustavsen). Two details
  matter: the fit is done in **normalized frequency** (without it the `s·e` column
  is ~10⁹ and the `1/(s-p)` columns ~10⁻⁷, and the least-squares is hopelessly
  ill-conditioned), and the pole relocation is done as **polynomial roots** of the
  sigma numerator (Durand–Kerner) rather than a matrix eigensolve.
- **Emit** the model. The subtlety is that `Y` is *improper* whenever a network has
  shunt capacitance (`Y ~ sC` at high frequency), and `laplace_nd` — a ratio of
  polynomials — cannot represent that (it produced a 63 % AC error at the band
  edge). The fix is to give `laplace_nd` only the strictly-proper (pole) part and
  emit the `e·s` term as an explicit **`ddt`** (a capacitance). AC error then drops
  to ~10⁻⁶.

## Hardening

- **Automatic order selection** climbs the pole count and keeps the best *stable*
  fit. It returns as soon as the fit reaches the tolerance (a genuine rational match
  — a delay/comb response only "engages" once enough poles are present, and is
  *uniformly* poor at low orders, so the selection must not quit on a small
  between-order improvement there). Otherwise it stops at the "knee" — but only once
  the error is already near a floor, so *noisy* data is fit at its noise floor rather
  than over-fitted into an unstable model. It breaks when a fit turns unstable
  (polynomial-root finding degrades at high degree) and returns the best stable fit.
  (This behavior was refined by stress-testing against a transmission line — a pure
  delay — which the first version quit on at 2 poles and now fits with ~12.)
- **Stability** is enforced — right-half-plane poles are reflected into the left
  half plane — so the emitted model is always BIBO-stable (a noisy, even
  *non-passive*, fit still stays bounded in transient).
- **Passivity** is checked and reported; `snp2va` warns when a fit is non-passive
  (passivity *enforcement* by residue perturbation is a documented non-goal for now).

## Pure Python, no numpy

The converter is pure standard library. The three primitives vector fitting needs
are reimplemented: least-squares via **Householder QR**, complex matrix inverse via
**Gauss–Jordan**, and polynomial roots via **Durand–Kerner** — each validated
against numpy to machine precision during development.

## Usage

```sh
python3 snp2va.py bandpass.s2p -o bandpass.va -m bandpass
openvaf-r bandpass.va -o bandpass.osdi
# deck:  N1 p1 p2 mm   /   .model mm bandpass   /   .control pre_osdi bandpass.osdi
```

## Verification

[`examples/nport_examples/verify_nport.py`](../examples/nport_examples/verify_nport.py)
— 6 checks, each generating a Touchstone file from a network whose response is known
*exactly*, running `snp2va.py` + OpenVAF, and confirming the device matches the
ORIGINAL network in ngspice: the converter runs and compiles; the device matches an
R-L-C resonator in **AC** to 5×10⁻⁶ (including the transmission peak) and in
**transient** to 5×10⁻³ (one model, both analyses); a **5-pole LC ladder** converts
(order selection scales past two poles); a **3-port** star network matches on both
coupled outputs to 4×10⁻⁹; and a **noisy** measurement is fit at its noise floor,
reported non-passive, yet stays bounded in transient (stability enforced). Full
example regression: 163/163.

Beyond the pinned checks, the converter was stress-tested to near machine precision
on resonators, notches, high-Q blocks, and multi-pole ladders. A delay-dominated
transmission line degrades gracefully: the AC response is accurate over the fitted
band, while transient pulse edges ring — inherent to rational fitting of a pure
delay, for which a `T`/`LTRA` line is the right model.
