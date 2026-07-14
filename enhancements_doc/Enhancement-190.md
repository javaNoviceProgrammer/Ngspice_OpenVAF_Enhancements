# Enhancement-190 — Nested multi-knob sweep (`sweep … -vs …`)

The second usability follow-up to the [Enhancement-146](Enhancement-146.md) `sweep` command (the first was the [Enhancement-189](Enhancement-189.md) `-overlay` waveform family). `sweep` stepped **one** knob and recorded each output's last value into a `sweep` transfer curve. `-vs <knob> <spec>` (alias `-family`) adds **outer** knobs: the inner (positional) knob stays the x-axis, and the outer knobs' **cartesian product** forms a curve family — one curve per output per outer combination — the parametric family that `.dc … SWEEP …` and HSPICE's nested `.dc` produce.

## The change

`sweep <inner> <spec> [-vs <knob> <spec>]… [-analysis …] [-output …] [-overlay]`. Each `-vs` contributes an outer knob (up to `SW_MAXKNOB = 4` knobs total, cartesian points capped at `SW_MAXPTS`). The summary `sweep` plot uses the inner knob's values as the scale; for each output and each outer-knob combination it emits one curve named `<output>_<outerknob>_<value>…`. `-overlay` composes: each cartesian point's full waveform becomes a `sweepwave` vector named with **every** knob's value (inner first), so a single knob is `<output>_<value>` exactly as in E-189.

The spec parser (`lin|dec|oct`, `list`, `start stop step`) was factored into `sw_parse_spec` and is now used for both the inner knob and each `-vs` knob, so all knobs accept the same three forms.

**By construction, a single knob reduces to E-146:** with one knob the cartesian product has one outer combination, so the curve is named `<output>`, the messages are the E-146 wording, and the data indexing is identical. Existing `sweep` and `sweepwave` examples pass untouched.

## Set ordering — the subtle part

Each knob is applied with E-146's mechanism: a `.param` needs `alterparam` + `reset` (a full re-source), while an instance/model knob is an in-place `alter` / `altermod`. In a cartesian product these interact — a `reset` re-sources the whole deck and drops every in-place `alter` — so the order matters. The loop iterates with the inner knob fastest and, at each point:

- **re-sources once only when a `.param` knob's value actually changed** since the previous point (i.e. at outer-loop boundaries; an inner `.param` still resets every point as in E-146, a pure in-place sweep never resets), staging every `.param` with `alterparam` before the single `reset`;
- **then re-applies every in-place knob after that reset**, so an inner `alter` survives an outer `.param`'s re-source.

## Correctness

The example is an RC low-pass driven by a 1 V step, sweeping R (inner) and C (outer), so each family curve is the exact transfer characteristic `v(out)|_{t=T} = 1 − exp(−T/(R*C))` as a function of R at that C. `verify_nestedsweep.py` compares every family value to that closed form — worst error **< 5e-6**. A dedicated check uses a `.param` **outer** knob (a reset at each outer step with the inner `alter` re-applied afterward) and confirms the family still matches, proving the ordering.

## Verification

[`examples/nestedsweep_examples/verify_nestedsweep.py`](../examples/nestedsweep_examples/verify_nestedsweep.py) — 5 checks: the cartesian run/curve counts are reported correctly (3×2 = 6 runs, 2 curves); each family curve matches `1−exp(−T/(R*C))` to < 5e-6; a `.param` outer knob (reset/alter ordering) matches; `-overlay` composes with the family (`<out>_<R>_<C>` names); and a single knob still names its curve plainly `vo` (E-146 unchanged). A [`nestedsweep_demo.cir`](../examples/nestedsweep_examples/) sweeps R × C into a two-curve family. Front-end and solver-independent, so it runs once. Full example regression: 154/154.
