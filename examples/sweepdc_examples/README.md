# sweepdc — `sweep` hands eligible op sweeps to one dc analysis

Regression suite for Enhancement-533. With the default `-analysis op`, a
single dc-sweepable knob and evenly spaced points, the `sweep` command no
longer solves npt independent **cold** operating points (one full `op` job and
one plot per point) — it runs **one dc analysis** under the hood, a warm
NIiter continuation from point to point, and serves the sweep's outputs from
the dc plot. Measured on the motivating deck (a 1000-device OSDI ladder, 9900
points): **21.2 s → 2.16 s**, bit-identical to a direct `.dc` and within
Newton tolerance of the per-point loop.

The safety net is that the two engines were already built as complements:
`.dc` **refuses** a point that moves an OSDI node collapse or leaves a model
bin (E-495 — its message recommends `sweep`), and aborts on device-rejected
values (E-427) or non-convergence. Every such outcome makes the handover fall
back to the per-point loop unchanged — fast when the circuit cooperates, the
old behavior to the letter when it does not. `-perpoint` forces the loop up
front.

What stays on the loop, by design: log/uneven spacing (`.dc` regenerates
points as start + k·step), model-parameter and `.param` knobs (no dc arm),
`-vs` families, `-overlay`, live `@dev[param]` outputs (only the loop can
read the circuit at each point — prescreened, so no dc is wasted), and
`sweep temp` when the deck contains any OSDI device (`dc temp` holds one
setup and cannot follow a temperature-moved collapse — the known-open finding
the `sweeptemp` suite pins; built-in-only decks keep the speedup).

Semantics that change with the engine, stated honestly: dc points run under
`MODEDCTRANCURVE` (a Verilog-A `analysis("dc")` is true where the loop's op
had `analysis("static")`), and a warm continuation tracks a solution branch
where independent cold ops re-decide it every point. Both are `.dc`'s own
readings; `-perpoint` restores the old ones.

| File | Pins |
|---|---|
| `sdccoll.va` | An instance-parameter-gated node collapse: sweeping `@N1[rs]` across 0 makes `.dc` refuse (E-495), the sweep announces the fallback, and the per-point loop lands on the closed-form series-resistance values exactly. |
| `verify_sweepdc.py` | 15 checks, both solvers: bit-identity with `.dc`, tolerance-agreement with `-perpoint`, knob restore, every ineligible spelling, the OSDI temp decline, and the refusal fallback. |

Run it:

```bash
python3 verify_sweepdc.py
```
