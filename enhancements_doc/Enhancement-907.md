# Enhancement-907: TXL and CPL keep their time in 64 bits — past 2.147 ms of simulated time both froze, without a word

**Scope:** found while digging into F9 of the
[analyses correctness campaign of 2026-10-16](../docs/bug_hunts/2026-10-16_ngspice-openvaf-r-analyses-correctness-campaign.md)
([E-904](Enhancement-904.md)).

ngspice:
- `spicelib/devices/txl/txlload.c`, `spicelib/devices/cpl/cplload.c`: the time, the step and the
  history's time stamps in picoseconds are `long long`.
- `include/ngspice/swec.h`: the history points' `time`.

**ngspice only.**

**Suites:**
- [`txlcpl_examples`](../examples/txlcpl_examples/): checks [5] and [6].
- The full sweep: 596 of 596.

## What was wrong

Both lines keep the simulation time, the step and each history point's time stamp as a whole
number of picoseconds, in an `int`. 2³¹ ps is 2.147 ms. Past it the time wrapped negative: the
lines found no new time point, stopped advancing their history, and returned the same response at
every step. A 10 kHz sine through a 200 m line, at the same phase each period:

| | 1.025 ms | 1.925 ms | 2.225 ms | 2.925 ms |
|---|---|---|---|---|
| TXL, lossless | 0.4985 | 0.4985 | 0.1085 | 0.1085 |
| CPL | 0.4987 | 0.4987 | 0.1430 | 0.1430 |

Nothing was printed. Any TXL or CPL transient longer than 2.147 ms was wrong from there on.

## The change

The time and step in picoseconds, their arguments, and the history points' time stamps are
`long long`, good for 106 days of simulated time. Where they meet a double (the delay, the
interpolation fraction, the step for the slopes) the conversion is written out.

## The checks

`txlcpl_examples`:
- **[5]** A lossless TXL keeps following a 10 kHz source past 2.147 ms: its peaks at 1.025, 1.925,
  2.225 and 2.925 ms equal to 1e-3. E-903: 0.4985 then 0.1085.
- **[6]** The same for a CPL line. E-903: 0.4987 then 0.1430.
