# Enhancement-904: a TXL or CPL line starts its transient from the operating point — a line carrying dc current dropped its far end from 0.496 V to 0.183 V under a constant source

**Scope:** found while digging into F9 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md).
The rest of the dig is [E-905](Enhancement-905.md) to [E-908](Enhancement-908.md).

ngspice:
- `spicelib/devices/txl/txlload.c`, `spicelib/devices/cpl/cplload.c`: the delayed current history
  and the current convolutions start at the operating point's port currents.
- `include/ngspice/swec.h`: `idc1`, `idc2` on both lines.

**ngspice only.**

**Suites:**
- [`txlcpl_examples`](../examples/txlcpl_examples/), new: checks [1] and [2]. 7 of 7 per solver;
  on the E-903 binaries all 7 fail.
- `cplfix` passes; the full sweep: 596 of 596.

## What was wrong

TXL and CPL are recursive-convolution lines. Each port's current is formed from the other port's
voltage and current one delay earlier, and from convolution states that carry their history. On
the first transient step both read their starting state from the operating point, where the line
is its dc resistance (`MODEDC` stamps R·length) and carries the circuit's dc current:
- The voltages were taken from it: the delayed values before the first delay, and the convolution
  states of the voltage terms, −V·c/x each.
- The currents were not. Before the first delay the delayed currents were 0, and so were the states
  of the current convolutions. CPL also recorded 0 for both currents in its first history point.

A line that carries dc current therefore started from a state with no current. Under a constant
1 V source through 50 Ω, a line of 8.5 Ω/m over 0.1 m and a 50 Ω load:

| | operating point | transient |
|---|---|---|
| TXL | 0.4958 V | dips to 0.1834 V, then back |
| CPL | 0.4958 V | dips to 0.1838 V, then back |
| LTRA | 0.4958 V | 0.4958 V throughout |

TXL had one more slip there: for a complex pair of the voltage-propagation terms it set each of the
pair's two stored parts to −V·c/x in real arithmetic, where the pair is one complex −V·c/x.

## The change

- At the first transient step the port currents are read from the operating point's branch currents,
  kept as `idc1` and `idc2`, and recorded in the first history point.
- Before the first delay the delayed currents are those currents.
- The current convolutions start at −I·c/x: for a complex pair, in complex arithmetic, as the voltage
  ones already did in CPL and now do in TXL.

## The checks

`txlcpl_examples`:
- **[1]** A TXL carrying dc current holds its operating point under a constant source: 0.4957858 V
  from the first point to the last. E-903: down to 0.1834 V.
- **[2]** The same for a CPL line. E-903: 0.1838 V.
