# Nested multi-knob sweep — `sweep … -vs …` (Enhancement-190)

The `sweep` command (Enhancement-146) steps **one** knob — an instance
parameter, a model parameter, a `.param`, a source value — runs an inner
analysis at each point, and records each output's last value into a `sweep`
transfer curve. `-vs <knob> <spec>` (alias `-family`) adds an **outer** knob.

The inner (positional) knob stays the x-axis; the outer knobs' **cartesian
product** forms a curve *family* — one curve per output per outer combination,
named `<output>_<outerknob>_<value>…`. Several `-vs` knobs compose into a full
grid (bounded to a few knobs). A single knob reduces exactly to E-146.

```
sweep R1 lin 6 1k 6k -vs C1 list 1n 2n -analysis tran 5n 4u -output vo=v(out)
```
```
sweep: r1 over 6 points x c1(2) = 12 runs -> 2 curves per output, ...
sweep: 2 curves x 1 output into the 'sweep' plot (now current);
       `plot <output>_...` to view the family vs r1.
```

`plot vo_c1_1e_09 vo_c1_2e_09` then overlays the two transfer curves vs R1, one
per C — the classic parametric family (`.dc … SWEEP …` / HSPICE nested `.dc`).

## Correctness

The testbed is an RC low-pass driven by a 1 V step, so each family curve is the
exact transfer characteristic at fixed C:

```
v(out)|_{t=T} = 1 - exp(-T / (R*C))   as a function of R.
```

`verify_nestedsweep.py` compares every family value against that closed form and
finds the **worst error < 5e-6**.

## Set ordering is the subtle part

Each knob is applied with the right mechanism (E-146): a `.param` needs
`alterparam` + `reset` (re-source), while an instance/model knob is an in-place
`alter` / `altermod`. In a cartesian product these interact: a `reset` re-sources
the whole deck and drops every in-place `alter`, so the order matters.

The loop iterates with the inner knob fastest and, at each point, **re-sources
once only when a `.param` knob's value actually changed** (i.e. at outer-loop
boundaries), then re-applies every in-place knob *after* that reset. A pure
in-place sweep never resets; an inner `.param` resets every point (as in E-146).
The verification includes a `.param` **outer** knob — which forces a reset at
each outer step with the inner `alter` re-applied afterward — and confirms the
family still matches the closed form, proving the ordering.

## Verification

`verify_nestedsweep.py` — 5 checks: the cartesian run/curve counts are reported
correctly; each family curve matches `1-exp(-T/(R*C))` to < 5e-6; a `.param`
outer knob (exercising the reset/alter ordering) matches too; `-overlay` composes
with the family (waveforms named with *both* knob values, `<out>_<R>_<C>`); and a
single knob still names its curve plainly `vo` (E-146 unchanged). Front-end and
solver-independent, so it runs once.

## Running

```sh
python3 verify_nestedsweep.py
ngspice -b nestedsweep_demo.cir
```
