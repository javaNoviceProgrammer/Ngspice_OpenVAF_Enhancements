# Enhancement-908: TXL and CPL say where they hold — a lossy TXL settled to 7/6 of its resistance, a CPL to almost none, and a TXL model above R/L = 1.6e9 became a CPL, all without a word

**Scope:** F9 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md):
"Neither model states the limit." With [E-904](Enhancement-904.md) to
[E-907](Enhancement-907.md).

ngspice:
- `spicelib/devices/txl/txlsetup.c`: a Note for a lossy line, and for one simulated lossless.
- `spicelib/devices/cpl/cplsetup.c`: a Note for a lossy line.
- `spicelib/parser/inpdomod.c`: a Note when a TXL model is simulated as CPL.
- `spicelib/devices/txl/txldefs.h`, `cpl/cpldefs.h`: each instance notes once.

**ngspice only.**

**Suites:**
- [`txlcpl_examples`](../examples/txlcpl_examples/): check [7].
- The full sweep: 596 of 596.

## What was wrong

TXL fits a lossy line with three-pole Padé approximations of its characteristic admittance and
propagation, expanded about s = ∞. Evaluated against the exact line, for G = 0:

| ω/(R/L) | 0.001 | 0.01 | 0.1 | 1 | 10 and above |
|---|---|---|---|---|---|
| two-port error | 14 % | 14 % | 6.7 % | 1.9e-4 | 5e-10 |

The two-port's dc limit is the ratio of the fits' slopes at s = 0, and it comes out at 7/6 of
R·length for every line: the transient settles to that resistance, 1.155 to 1.169 times R·length
when measured, while the operating point (`MODEDC`) has R·length. The campaign's 6 % TXL error was
a line driven at 0.065 R/L. A better three-pole fit cannot cure it: a characteristic admittance of
three poles optimised over the band, with its dc value held, is still 7.6 % off over
[0.01, 10⁴]·R/L. Holding the dc resistance exact instead costs 1 % at R/L, where the fit is now
2e-4.

Three more things happened silently:
- **TXL dropped R.** With R/L below 5e5 (and G below 0.01), TXL simulates the line lossless: its
  resistance R·length is dropped.
- **A TXL model became CPL.** With R/L above 1.6e9 the parser makes a TXL model a single CPL line.
  The branch meant for R/L above 1.6e10 made it a TXL first and was then overwritten.
- **CPL lost its resistance.** A lossy CPL line keeps almost none of its resistance at low
  frequency. Stepped from 0 and settled, single lines kept under 1 % of R·length as their dc
  resistance, and two coupled lines none. A 200 m line of R·length = 100 Ω swung 0.4987 V at
  10 kHz where the exact line gives 0.25 V.

## The change

Each line notes once, at setup, when R·length is at least 1 % of its characteristic impedance:
- A lossy TXL: `txl's lossy-line fits hold above the line's RC corner R/(2 pi L) = … Hz; a
  decade below it they are 7 % off, and the dc resistance the transient settles to is 7/6 of
  R*length = … ohm. LTRA (an O element) is exact at any frequency.`
- A TXL simulated lossless: `R/L = … is below 5e5, and txl simulates the line lossless: its
  resistance R*length = … ohm is dropped. LTRA (an O element) keeps it.`
- A lossy CPL: `cpl does not model a lossy line below its RC corner R/(2 pi L) = … Hz: there it
  loses most of the line's resistance, and a dc current sees almost none of R*length = … ohm.
  LTRA (an O element) is exact for a single line.`
- A TXL model above R/L = 1.6e9: `.model …: a txl with R/L = … above 1.6e9 is simulated as a
  single cpl line.` The model is made once, as CPL.

## The checks

`txlcpl_examples`:
- **[7]** A lossy TXL, a TXL that drops its resistance, a TXL model simulated as CPL, and a lossy
  CPL each print their Note. E-903: none.

## Limits

- **CPL's time scale.** CPL's fitted poles come out in units of the frequency `Scaling_F`
  = 1/√(LC) that its setup normalises by, and the load uses them as if in rad/s. Scaled back, its
  characteristic-admittance fit matches the exact line to 1e-6 at high frequency. A model of the
  CPL two-port built from the scaled fits did not reproduce CPL's measured transient, so the
  scaling was not changed. This is the likeliest cause of CPL's lost resistance and is left open.
- **TXL in its RC regime.** Accurate there would take more poles per function than the load's three.
- **CPL with R = 0.** Its setup ends ngspice with "Gaussian elimination (mult) fails"; as before.
- **The dead fallback.** `inp2y.c`'s three-section RC fallback for R/L above 1.6e10 is unreachable
  (such models are CPL), and its resistances are 3/(R·length) where R·length/3 was meant.
