# Enhancement-435 — the fourth consumer of a hierarchical model name

```
sweep @x1.rmod[res] 1k 3k 1k -analysis op -output v(out)

    Error: no such parameter res.
    0   5.000000e-01
    1   5.000000e-01        <- three points, rc=0, a plottable FLAT curve
    2   5.000000e-01
```

A `.model` declared inside a subcircuit is renamed by expansion to
`<instance-path>:<model>`, and Enhancement-433 taught ngspice to accept the
dotted `@x1.rmod[res]` that users actually write. It reached three consumers —
`altermod`, `optimize -mparam`, and `@`-readback — because all three resolve
names through `finddev`/`finddev_special`.

`sweep` does not. `sw_kind()` calls `ft_sim->findModel()` itself, right where it
classifies the knob, so it never saw the fallback.

## Why the failure was worse than a refusal

An unrecognised `@name[param]` does not stop the sweep. It falls through to the
instance branch, `alter` reports *"no such parameter"* for what is a **model**
parameter, and the sweep proceeds with a knob that never moved — producing a
full set of points, `rc=0`, and a perfectly believable flat line. The diagnostic
scrolls past in the middle of the run; the artefact that survives is a curve.

That is the shape Enhancement-431 removed for a `-output` that never resolved.
Here it is the *knob* rather than the output, and the resulting curve is not
zero but constant, which is if anything easier to mistake for a result.

The fix is one condition, mirroring the two funnels:

```c
if (*mod && ft_curckt && ft_curckt->ci_ckt &&
    (ft_sim->findModel(ft_curckt->ci_ckt, (IFuid) mod) ||
     if_find_model_hier(ft_curckt->ci_ckt, mod)))
    return SW_MODEL;
```

Once classified as a model knob, application already worked: `sw_set_inplace`
issues `altermod`, which Enhancement-433 taught to resolve the dotted name.

## Scope: only `sweep`

`sw_kind()` has exactly one caller. `montecarlo`, `highsigma` and `wcd` perturb
Gaussian `.param` values rather than named knobs, and `optimize` classifies its
own with `-param`/`-mparam`/`-dparam`, whose model path already worked. So this
is one command, checked rather than assumed.

## Verification

`examples/hierdev_examples` — 43 checks (was 38). The four spellings that must
work now do, against the analytic divider `v(out) = 1k/(res+1k)` over
res = 1k, 2k, 3k → 0.5, 0.3333, 0.25:

* `@x1.rmod[res]` — dotted, the case that was broken
* `@x1:rmod[res]` — the real flattened name, which always worked
* `@x1.x2.rmod[res]` and `@x1.x2:rmod[res]` — nested, both spellings
* a plain top-level `@rmod[res]`, which the new fallback must not disturb

**Positive-controlled:** with the change reverted and rebuilt, exactly the two
dotted checks fail, each with the flat `0.5, 0.5, 0.5` that is the whole point.
The colon forms and the top-level model pass either way — they are the
no-regression controls.

Full regression 346/346, both solvers.

## Known, not fixed

A knob that fails to apply still yields a flat curve with `rc=0`. This change
removes the most likely *cause* of that for model parameters, but the general
case remains: `sweep @x1.nosuch[res]` and `sweep @x1.rmod[nosuch]` both print an
error and then sweep three identical points. Catching it properly means
verifying after the first application that the knob actually took — Enhancement-385's
`sw_read_knob` can already read a knob back — and refusing the sweep when it did
not. That is a behaviour change with its own regression surface (wildcards,
`.param` knobs, parameters that are set-only), so it is recorded here rather
than bundled in.

## Found by

The question *"how do I sweep a model parameter that is inside a subcircuit?"*
The answer was `@x1:rmod[res]`, and finding it meant noticing that the dotted
spelling — the one Enhancement-433 had just made work everywhere else — silently
produced a flat curve instead.
