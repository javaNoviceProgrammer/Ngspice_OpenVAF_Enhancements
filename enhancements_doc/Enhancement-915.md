# Enhancement-915: `.option scale` is applied to compiled instances — a compiled BSIM4 with `w=1 l=0.1` under `scale=1e-6` was simulated as a transistor one metre wide, while the built-in beside it was scaled

**Scope:** F2 of the
[options-and-convergence hunt of 2026-09-26](../docs/bug_hunts/2026-09-26_ngspice-osdi-options-and-convergence.md).

ngspice:
- `osdi/osdiparam.c` (`osdi_geom_scaling`: the setter scales, the ask unscales);
- `osdi/osdiregistry.c` (the geometric instance parameters of each compiled model);
- `include/ngspice/osdiitf.h`.

**ngspice only.**

**Suites:**
- [`scaleoption_examples`](../examples/scaleoption_examples/) (new): 10 checks per solver, 7 of which
  fail on E-913.
- The full sweep: 605 of 605.

## What was wrong

`.option scale` multiplies the geometry of every built-in MOSFET in its parameter setter:
- `w`, `l`, `ps` and `pd` by the scale;
- `as` and `ad` by its square.

That is b4par.c, hsm2par.c, mos1par.c and the rest. Nothing scaled a compiled instance. The OSDI
layer answered `$simparam("scale")` (E-394), which only the CMC models read.

| instance line | option | compiled BSIM4 `v(out)` | built-in |
|---|---|---:|---:|
| `w=1u l=100n` | — | 0.084861 | 0.083282 |
| `w=1 l=0.1` | `.option scale=1e-6` | **0.025341** | 0.083282 |

A deck written for `scale=1e-6`, common in foundry flows, simulated a compiled transistor as
1 m × 10 cm, with no message.

## What changed

The compiled layer scales the same parameters the built-ins do, when it can tell they are
geometry.

**Which parameters.** An instance parameter qualifies when it is a real scalar named
- `w`, `l`, `ps` or `pd`, declared in metres, or with no units and a description that says
  length, width or perimeter;
- `as` or `ad`, declared in square metres, or with no units and a description that says area.

The VA-Models BSIM4 declares `as`, `ad`, `ps` and `pd` with units "" and descriptions such as
"Source to Substrate Junction Area". PSP103 gives them `m` and `m^2`.

**Which are left alone.**
- A parameter of those names with another unit is not geometry: an inductance `l` in henries is
  untouched.
- One with neither a unit nor a description is used as written, and one warning per model says
  why:

```
Warning: .option scale=1e-06 is not applied to the compiled model 'nounits's instance parameter 'w': it declares no units, so ngspice cannot tell it is a length; the value is used as written.
```

**A model that applies the scale itself** is not scaled again. The CMC models (r2_cmc, r3_cmc,
VBIC, PSP-HV) declare a model parameter `scale`, "scale factor for instance geometries", whose
default is `$simparam("scale")`, and multiply their geometry by it. A model declaring a parameter
`scale` lists no geometry.

**The value reads back as written.** Under `scale=1e-6`, `print @n1[w]` gives 1 for `w=1`. The
machine routes read a parameter through the ask and write it back through the setter: the
restore of a `.dc @n1[w]` sweep, a `sens` perturbation. A value read back scaled would be scaled again.

The built-ins read back the scaled value, and their dc sweep restore does scale it twice. A
built-in BSIM4 under `scale=1e-6` reads `@m1[w] = 1e-12` after `dc @m1[w] 1 2 0.5`, and `v(out)`
moves from 0.0833 V to 1.1999 V. That is upstream behaviour and is not changed here.

`alter n1 w=2` under scale is 2 µm, as `w=2` on the line is. A `.model` card's instance default
(`w=1` on the card) is scaled the same way.

## The checks

`scaleoption_examples` (new), under both solvers:

| check | what | E-913 |
|---|---|---|
| [1] | `w`, `l`, `ps`, `pd` (no units, a description) times 1e-6, `as`, `ad` times 1e-12, each giving the current its value in metres gives | 1e6 and 1e12 times it |
| [2] | `@n1[w]` reads back 1, and after `dc @n1[w] 1 3 1` the point and the parameter are what they were | the point is 1000 times off |
| [3] | `alter n1 w=2` under scale is 2 µm | 1000 times off |
| [4] | an `l` in henries is not scaled | passes |
| [5] | a `w` with no units and no description: used as written, one warning | no warning |
| [6] | a model with its own `scale` parameter is not scaled twice | passes |
| [7] | the VA-Models BSIM4 with `w=1 l=0.1` and junction geometry: the point of the same device in metres, 4e-5 from the built-in | 0.019067 V: 1 m wide, with 0.2 m² junctions |
| [8] | PSP103 likewise | 0.032032 V against 0.065578 V |

## Limits

- **The scale in force when the value is written** is the one applied, as for the built-ins: a
  `scale` changed after the netlist is read does not rescale the instances, and their values then
  read back through the new scale.
- **A model that reads `$simparam("scale")` without declaring a `scale` parameter** would be
  scaled twice. None in the VA-Models corpus does; EKV, fbh_hbt and MVSG define the macro and do
  not use it.
- **The built-ins' dc sweep restore** under `scale` is left as it is (above).
