# Enhancement-852: a `uic` transient has its t = 0 point — nothing solved it, and the run began at the first step, `meas` and `fourier` with it

**Scope:** F8 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

ngspice: `spicelib/analysis/dctran.c`, `uic_t0_point` and its call at the output of the first
accepted point.

Examples:
- `examples/uicstart_examples/` (new);
- `firststep_examples` [2], which read the first step as `time[0]`.

**ngspice only.**

**Suites:**
- [`uicstart_examples`](../examples/uicstart_examples/): 8 of 8 per solver. On the E-844
  binaries checks [1] to [6] fail; [7] and [8] are controls.
- Five circuits under `uic` (an RC with `.ic`, a diode with an inductor, a BJT stage, a CMOS
  inverter, a Verilog-A diode), each under trap, Gear, KLU and Sparse: every sample after t = 0
  is bit for bit the sample of the HEAD binary, which has no t = 0 point.
- The full sweep: 557 of 557.

## What was wrong

The deck in F2 with `uic` started at `time[0]` = 1 ns. Without `uic`, `time[0]` = 0 and
`v(1)[0]` is the operating point. `dctran.c` wrote a point under `uic` only for `CKTtime > 0`,
because nothing solved one at t = 0: `uic` loads the circuit once and returns. `CKTrhsOld` then
holds the `.ic` values and zeros, so a node that a source drives reads 0 V there. Upstream left
that point out rather than write it.

So the initial condition, the waveform's value at t = 0, was never output. `meas` and `fourier`
over such a run started at the first step, and `find v(2) at=0` was out of interval.

## The change

The point at t = 0 is the circuit with:
- each capacitor at its initial voltage;
- each inductor at its initial current;
- the sources at their t = 0 values.

That is the limit of the first backward-Euler step as the step goes to zero. `uic_t0_point`
solves it with a step a millionth of the first. A capacitor's voltage moves by i·h/C there, a
millionth of what the first step moves it. Its conductance C/h is a million times the first
step's, which is of the order of the circuit's own conductances, so the factorization keeps
about ten digits.

Where a source contradicts an initial condition, a capacitor jumps at t = 0. Examples are a
supply node starting at 0 V under its capacitances, or a device's junctions at their `IC=`
values, which default to 0. That solve's current is then the jump's impulse, C·ΔV/h: −600 A
for a CMOS inverter's supply, where the first step shows −8.9 mA. A second solve starts from the
point found, with its charges as the history. The voltages stay, and the currents are the finite
ones at t = 0+: −2.9 mA. Where nothing jumps, the second solve changes nothing but O(h).

The point is written, and then everything the solves touched is put back:
- the solution and the right-hand side;
- states 0 and 1;
- the mode, the step, the step history and the order;
- the solver's state.

The first step starts from what it always started from, and the run after t = 0 is unchanged.

If either solve fails to converge, no point is written, as before. The point is not solved:
- with `tstart` > 0;
- in a circuit with XSPICE event-driven instances, whose t = 0 has its own handling;
- if the number of states changed during the solve.

## The checks

`uicstart_examples`:
- **[1]** An RC under `uic` with `.ic v(2)=0.3`: `time[0]` = 0, v(2) = 0.3, v(1) = 0.
- **[2]** A divider a source drives, at t = 0: 1.25 V, and the source's current −1.25 mA.
- **[3]** A diode, a capacitor with `ic=`, an inductor with `ic=`, and an `.ic` that a source
  contradicts: the source's 5 V, 0.2 V, the inductor's 1 mA, and 10 V across 10 kΩ.
- **[4]** A CMOS inverter whose supply node starts at 0 V: the supply's current at t = 0 is
  finite and below the first step's.
- **[5]** After t = 0, the samples are those of the same run with `tstart` = 1e-30, which writes
  no t = 0 point, bit for bit.
- **[6]** `meas tran find v(2) at=0` reads the initial condition.
- **[7]** (control) Without `uic`, `time[0]` = 0 is the operating point.
- **[8]** (control) `uic` with `tstart` = 1 ns: no point before `tstart`.

`firststep_examples` [2] judged the first step through `time[0]` and `v(1)[0]`. It now reads
index 1.
