# Enhancement-851: the `meas` command keeps every digit — its result was `let name = %e`, 7 significant digits, and a vector named after `at=` or `val=` went back into the line the same way

**Scope:** F7 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

ngspice: `frontend/measure.c`:
- `com_meas` stores its result with 17 significant digits;
- the vector it substitutes after an `=` gets 17 too;
- `meas_card_vector`, a `.meas` card's result (E-802), gets 17 instead of 16.

`examples/meascmd_examples/` (new). **ngspice only.**

**Suites:**
- [`meascmd_examples`](../examples/meascmd_examples/): 4 of 4 per solver. On the E-844 binaries
  checks [1] to [3] fail; [4] is a control.
- The full sweep: 557 of 557.

## What was wrong

```spice
v1 1 0 sin(0 1 1meg)
r1 1 0 1k
.meas tran card find v(1) at=0.123456789u
.tran 1n 1u
.control
set numdgt=17
run
meas tran cmd find v(1) at=0.123456789u
print card cmd
```

`card` = 0.700215328413115, and `cmd` = 0.7002153. `com_meas` stored its result by running
`let name = %e`, which keeps 7 significant digits. [Enhancement-802](Enhancement-802.md) gave a
`.meas` card's result its own vector with `%.15e`.

The same `%e` put a vector back into the line when the command named one after `val=`, `at=`,
`from=` or `to=`. A measurement script that builds on earlier results lost digits at each step:
- two crossings 1.8 fs apart both read 8.333343e-8, and their difference was 0;
- `meas tran v2 find v(1) at=t2` read v(1) at a rounded `t2`: 0.5, where the crossing it names
  is at 0.50000001.

## The change

The three strings are printed with `%.17g`. Seventeen significant digits identify a double
exactly, and both readers are correctly rounded since [Enhancement-643](Enhancement-643.md):
`let`'s `ft_numparse` and the measure parser's `INPevaluate` hand the digits to `strtod`. So the
vector holds the measured double itself.

The line the command prints is unchanged. It is a display, and keeps its format.

## The checks

`meascmd_examples`:
- **[1]** The command's FIND equals the same `.meas` card's, bit for bit.
- **[2]** Two crossings 1.8 fs apart: the commands' difference is the cards' difference.
- **[3]** `find v(1) at=t2`, `t2` a vector: v(1) at `t2` is 0.50000001.
- **[4]** (control) The card's result is the linear interpolation of the samples, to 1e-15.
