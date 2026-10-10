# uicstart_examples — Enhancement-852

[E-852](../../enhancements_doc/Enhancement-852.md): F8 of the
[second robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

`uic` loads the circuit once and solves nothing at t = 0, so no point was written there. The
run began at the first step, and `meas` and `fourier` with it.

The point at t = 0 is now solved, with a step a millionth of the first:
- each capacitor at its initial voltage;
- each inductor at its initial current;
- the sources at t = 0.

Where a source makes a capacitor jump, a second solve from that point gives the finite currents
at t = 0+, not the jump's impulse. Everything is put back before the first step, so the run
after t = 0 is the run without the point, bit for bit.

The checks:
- **[1]** An RC under `uic` with `.ic v(2)=0.3`: `time[0]` = 0, v(2) = 0.3, v(1) = 0.
- **[2]** A divider a source drives, at t = 0: 1.25 V, and the source's current.
- **[3]** A diode, a capacitor with `ic=`, an inductor with `ic=`, and an `.ic` a source
  contradicts.
- **[4]** A CMOS inverter whose supply node starts at 0 V: the supply's current at t = 0 is
  finite.
- **[5]** After t = 0, the samples equal the same run's with `tstart` = 1e-30, bit for bit.
- **[6]** `meas tran find v(2) at=0` reads the initial condition.
- **[7]** (control) Without `uic`, `time[0]` = 0 is the operating point.
- **[8]** (control) `uic` with `tstart` > 0: no point before `tstart`.

Run: `python3 verify_uicstart.py` (8 checks per solver). On the E-844 binaries [1] to [6]
fail.
