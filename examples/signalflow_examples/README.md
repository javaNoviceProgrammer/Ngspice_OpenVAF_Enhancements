# signalflow_examples — probe-only branches & signal-flow systems (Enhancement-36)

Demonstrates **probe-only branches (ideal ammeters)** and all four Verilog-AMS
system styles — conservative, potential-only signal-flow, flow-only signal-flow —
using **the committed** `openvaf-r` and `ngspice-46`.

## What was broken

Probing a branch that is never contributed to (`I(p,n)`, or `branch (p,n) sense;`
used only in `I(sense)`) read **0** and left the branch an **open circuit**. Per
the LRM it must behave as a **short** (0V potential source) whose current is the
probed value — the ideal-ammeter idiom, and the mechanism flow-only (`current`
discipline) signal-flow nets ride on, so entire current-signal chains produced 0.
Root cause: the DAE only materialised *contributed* branches (same failure family
as Enhancement-29's port-flow stub).

## The fix

A `build_probe_only_branches()` pass in the DAE builder (template: E-29's
port-flow pass) synthesises the 0V-source system for every probed-but-never-
contributed branch:

```
residual[I(br)] = -V(hi,lo)   (V = 0)      KCL(hi) += I(br)      KCL(lo) -= I(br)
```

See `../Enhancement-36.md`.

## Run

```
python3 verify_signalflow.py
```

Checks (ALL PASS): the ammeter **shorts and reads** (2 mA / 2 V exactly; used to
be open/0); it reads **displacement current** in AC (`j·1 V` exactly); a CCCS
current mirror on a probe-only sense branch (3 mA → 6 mA); the potential-only
signal-flow gain chain (`1.5 × 3 × 2 = 9 V`); and the flow-only chain
(`1 mA × 5 × 1 kΩ = 5 V`, probed net at exactly 0 V — textbook signal-flow).
