# Enhancement-901: `.sp`'s noise figure is referred to T₀ = 290 K — at 27 °C a passive two-port's NF read up to 0.149 dB low, and 1.6 dB at 146 °C

**Scope:** F7 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).

ngspice:
- `spicelib/analysis/span.c`: the noise parameters are normalised by 4kT₀, T₀ = 290 K.

**ngspice only.**

**Suites:**
- [`spnoisetemp_examples`](../examples/spnoisetemp_examples/), new: 7 of 7 per solver; on the
  E-899 binaries 5 of 7 fail.
- [`rfanalyses_examples`](../examples/rfanalyses_examples/): the two noise figures it pins move
  to the IEEE values.
- The full sweep: 594 of 594.

## What was wrong

`.sp … 1` computes the noise correlation matrix Cy of a two-port and from it Rn, NFmin, SOpt and
the noise figure NF at the port-1 reference impedance. `span.c` divided Cy by 4k·`CKTtemp`
before the extraction. The IEEE noise parameters are normalised by 4kT₀ with T₀ = 290 K, and
the noise figure is defined with the source at T₀. Cy already holds every device's noise at its
own temperature, so the normalisation has to be T₀.

A passive two-port at physical temperature T has F = 1 + (T/T₀)(1/G_a − 1). Dividing by 4kT gave
1/G_a, which holds only at T = T₀:
- A 100 Ω / 100 Ω attenuator between 50 Ω ports at 27 °C: NF 8.7506 dB, where the IEEE value is
  8.8804 dB.
- 110 passive two-ports of the campaign at 27 °C were 0.009 to 0.149 dB low. The asymptote,
  where their own noise dominates, is 10·log₁₀(300.15/290).
- Rn read T₀/T of its value: 3.4 % low at 27 °C.
- A resistor given its own `temp=` was referred to the circuit's temperature instead of T₀.

Only the normalisation was wrong, so for any network, active or passive, F − 1, Rn and Gu were
all T₀/T of their values, T being the circuit's temperature. The noise figure was off by up to
10·log₁₀(T/T₀), the bound reached where the network's own noise dominates:

| circuit temperature | NF, at most | Rn |
|---|---|---|
| 27 °C | 0.149 dB low | 3.4 % low |
| 125 °C | 1.38 dB low | 27 % low |
| 146.6 °C | 1.60 dB low | 31 % low |
| −40 °C | 0.95 dB high | 24 % high |

The worst of the random two-ports below, at 146.6 °C, was 1.604 dB off, within 0.002 dB of the
bound.

Cy itself was right: within 2.5e-12 of 2kT(Y + Yᴴ) in the campaign's 420 passive runs. SOpt is a
ratio of the noise parameters, and was right too.

## The change

`knorm = 4·k·T₀` with T₀ = 290 K (`SPNOISE_T0`), in place of 4·k·`CKTtemp`. At 16.85 °C nothing
changes. The manual's list of outputs (Rn, NF, NFmin, SOpt) is unchanged. Rn is now the IEEE
noise resistance, ⟨|v_n|²⟩/(4kT₀).

## The checks

`spnoisetemp_examples`. The reference is the network itself: every resistor's 4kT/R at its own
temperature, folded to the ports' short-circuit currents, turned into the chain form and
normalised by 4kT₀.
- **[1]** The attenuator at 27 °C: NF, NFmin and Rn as the IEEE definition gives them. E-899:
  NF 8.7506 dB against 8.8804 dB.
- **[2]** The same at 16.85 °C: NF = 10·log₁₀(1/G_a) = 8.7506 dB, as before.
- **[3]** A series 100 Ω at 27 °C: Rn = R·T/T₀ = 103.5 Ω. E-899: 100 Ω.
- **[4]** A resistive T network at 125 °C and −40 °C. E-899: 1.2 dB and 0.82 dB off.
- **[5]** An active stage (a VCCS with resistors and capacitors) at 60 °C, at 50 Ω and 75 Ω
  ports: NF, NFmin, Rn and SOpt at four frequencies. E-899: NF 0.34 dB off, Rn 13 %.
- **[6]** A series resistor at `temp=-196` in a circuit at 27 °C: F = 1 + (T_R/T₀)·R/Z₀.
  E-899: (T_R/300.15)·R/Z₀.
- **[7]** Cy is unchanged: 4kT·Re(Y) at the circuit's 125 °C. It passes on E-899 too.

`rfanalyses_examples` [3]: the series 100 Ω between 50 Ω ports is 10·log₁₀(1 + (T/T₀)·R/Z₀) =
4.8714 dB, where it pinned 4.7712 dB. The two-resistor network is 7.3229 dB, where it pinned
7.2016 dB.

200 random two-ports under both solvers:
- Passive and active networks of R, L, C and VCCS, at −50 °C to 150 °C, some with a resistor at
  its own temperature, compared with the same reference.
- E-899 is exact at 16.85 °C and up to 1.6 dB off elsewhere.
- Now NF agrees to 1.7e-12 dB, Rn to 2e-13 and SOpt to 4e-12.
- NFmin agrees to 4.8e-8 dB. The largest differences are at points where almost nothing is
  transmitted (NF about 100 dB) and Gu cancels to near zero; both solvers give the same value.
- The campaign's own Family C: passive NF now within 5e-14 dB of the IEEE value over all 110
  two-ports.
