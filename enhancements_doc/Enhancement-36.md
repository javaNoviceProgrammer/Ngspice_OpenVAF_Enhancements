# Enhancement-36 — probe-only branches / ideal ammeter + flow-only signal flow

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to give **probe-only branches** their LRM-mandated **0V-source (ideal
ammeter) semantics** — which simultaneously completes support for **flow-only
signal-flow disciplines**. One new pass in the DAE builder (`sim_back`); no
OSDI/ngspice change.

## The bug

Verilog-AMS distinguishes conservative disciplines (`electrical`: potential +
flow, KCL/KVL) from signal-flow disciplines (`voltage`: potential only;
`current`: flow only). Probing the flow of a branch that is never *contributed*
to is a fundamental idiom:

```verilog
branch (p, n) sense;
V(out) <+ rtz * I(sense);      // ideal ammeter + transimpedance readout
I(onp, com) <+ k * I(sense);   // CCCS on a sense branch (current mirror)
```

Per the LRM, such a **probe-only branch behaves as a short** — a potential source
of 0 V — whose current is the probed value. In OpenVAF it instead read **0** and
conducted **nothing**: the "ammeter" was an *open circuit*, silently breaking the
surrounding series path. The same mechanism underlies flow-only (`current`
discipline) signal-flow nets — an input port only *probes* its net's flow — so
entire current-signal chains produced 0.

### Root cause

The topology only materialises branches that are **contributed** to (it is keyed
off the `IsVoltageSrc` outputs, which are created per contribution). A branch
that is merely probed never passes through `build_branch`/`add_source_equation`,
so its current unknown never exists and the OSDI eval falls back to the
"always zero" path — the same failure family as Enhancement-29's port-flow stub.

## The fix

A new `build_probe_only_branches()` pass in `sim_back/src/dae/builder.rs`, run at
the start of `finish()` right after Enhancement-29's `build_port_flow_equations`
(its direct template). For every live `ParamKind::Current` (named or unnamed
branch; port flows excluded — E-29 owns those) whose `Current` unknown was not
materialised by the contribution-driven pass, it synthesises exactly the system
`add_source_equation` builds for a voltage branch with a zero source expression:

```text
residual[Current(br)] = -V(hi,lo)      (nature Potential -> equation V(hi,lo) = 0)
residual[KCL(hi)]    += I(br)
residual[KCL(lo)]    -= I(br)
```

The branch current `I(br)` is the very parameter the model reads, so probes and
any sources built on them see the solved through-current; the Jacobian entries
come out of the ordinary derivative machinery since the pass runs before
`sim_unknown_reads`/`auto_diff`. One caveat inherent to the semantics: putting
*several* probe-only branches in parallel across the same node pair is degenerate
(parallel ideal 0V sources), exactly as paralleling ideal voltage sources is.

## Verification — `signalflow_examples/`

`signalflow_demo.va` packs all four system styles: a conservative ideal ammeter
with transimpedance readout, a CCCS current mirror on a probe-only sense branch,
a potential-only (`voltage` discipline) gain chain, and a flow-only (`current`
discipline) source → gain → converter chain. `verify_signalflow.py` (ALL PASS):

1. the **ammeter** shorts (the series 2 V / 1 kΩ loop conducts its full 2 mA —
   it used to be open) and reads it (`v(out) = 2 V` exactly);
2. it reads **displacement current** in AC (series 1 nF at ω = 10⁶: `v(out) =
   j·1 V` exactly — the 0V source is fully linear and reactive-aware);
3. the **current mirror** senses 3 mA and outputs 6 mA;
4. the potential-only signal-flow chain gives `1.5 × 3 × 2 = 9 V` (this style
   already worked and is regression-locked here);
5. the flow-only chain gives `1 mA × 5 × 1 kΩ = 5 V` (used to be 0), with the
   probed signal net sitting at exactly 0 V — textbook signal-flow semantics
   (the probe shorts the net and takes its total inflow as the signal).

Regressions: all **32** version11 example verify suites ALL PASS; the
`sim_back` snapshot tests remain at their pre-existing 9-pass/15-fail baseline
(no new failures).

## System-style support after E-36

| style | status |
|-------|--------|
| conservative (`electrical`) | full (unchanged) |
| signal-flow, potential-only (`voltage`) | full (already worked; now regression-locked) |
| signal-flow, flow-only (`current`) | **full (new)** |
| probe-only branches / ideal ammeters / CCCS-on-sense | **full (new)** |
