# rfanalyses_examples — S-parameters, transient noise, and PSS with Verilog-A (OSDI) devices (Enhancement-63)

Round 2 of the Enhancement-62 analysis-coverage work: the RF-flavored
ngspice analyses, probed with OSDI devices against built-in twins.

## Results

| analysis | verdict |
|---|---|
| `.sp` S-parameters | **exact** — series-R S11 = S21 = 0.5 textbook values; a frequency-dependent OSDI RC is *bit-identical* to the built-in twin over three decades. **Fully N-port**: a 3-port junction reproduces Sii = −1/3 / Sij = +2/3, and 3-/4-port OSDI resistor stars give the analytic 1/3 and 1/4 exactly (only the donoise NF/SOpt block — inherently two-port concepts — requires exactly 2 ports) |
| `.sp … 1` (noise figure) | OSDI noise pipeline reaches S-parameter noise figures **exactly** (NF = 10·log10(1 + R/Z0)); **found + fixed a stock ngspice NaN** (see below) |
| transient noise (`TRNOISE`) | propagates through OSDI devices correctly; device-*internal* noise doesn't enter `.tran` for built-ins either (parity) |
| `.pss` (periodic steady state) | OSDI devices are **full citizens**: linear RC converges to the analytic fundamental and matches the built-in twin to 7 digits; a mildly-driven OSDI diode converges in 2 shooting iterations (the built-in twin wanders longer). Strongly nonlinear rectifiers are hard for the shooting method with built-ins and OSDI alike. |

## The fix (`span.c`)

S-parameter noise extraction computes `Ysopt = sqrt(Ycor.re² + Gu/Rn)`.
For a fully-correlated noise topology (a single series resistor as the only
noise source) the uncorrelated noise conductance `Gu` is analytically
**zero**, and floating-point rounding could land the sqrt argument at
−1e-18 — poisoning NF/SOpt/NFmin with NaN. The OSDI twin's rounding
happened to stay ≥ 0, which is how the parity test exposed it. The
argument is now clamped to its physical range (≥ 0); both paths agree
with the analytic 4.7712 dB and multi-source circuits are unchanged.

## PSS needs a special build

`.pss` is experimental and compile-time optional. Build ngspice with
`--enable-pss` (all other flags as usual):

```bash
mkdir ngspice-46/build-pss && cd ngspice-46/build-pss
../configure --with-x --with-readline=... --disable-openmp --enable-pss CFLAGS=... LDFLAGS=...
make -j8
```

`verify_rfanalyses.py` prefers `ngspice-46/build-pss/src/ngspice` when it
exists, probes the default binary otherwise, and **SKIPs** the PSS checks
cleanly when neither supports `.pss`.

## Run

```bash
python3 verify_rfanalyses.py    # 15 checks (12 + 3 PSS)
```
