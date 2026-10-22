# Enhancement-914: `.option tnom` reaches compiled models — the option moved every built-in and no compiled model, and the VA-Models BSIM4, which falls back to 25 °C when its `tnom` is not given, ran 1.5 % off its built-in twin by default

**Scope:** F1 of the
[options-and-convergence hunt of 2026-09-26](../docs/bug_hunts/2026-09-26_ngspice-osdi-options-and-convergence.md).

ngspice:
- `osdi/osdisetup.c` (`osdi_model_nominal_temp`, run before every `setup_model`),
  `osdi/osdiregistry.c` (the model's `tnom` parameter, and a reference-temperature parameter for a
  model without one), `osdi/osdiparam.c` (a written `tnom` is the user's), `osdi/osdidefs.h` (a
  flags word in each compiled model's data), `include/ngspice/osdiitf.h`;
- `include/ngspice/tskdefs.h`, `include/ngspice/cktdefs.h`, `spicelib/analysis/cktsopt.c`,
  `cktntask.c`, `cktdojob.c`: whether `.option tnom` was written.

**ngspice only.**

**Suites:**
- [`tnomoption_examples`](../examples/tnomoption_examples/) (new): 14 checks per solver, 12 of which
  fail on E-913.
- `paramgiven` [7], [9], [10] and `singularname` (the BSIM4 gate on a capacitor): re-pinned. They
  had pinned the compiled BSIM4 at its 25 °C fallback; at 27 °C its drain current is
  −1.14022e-4 A where it was −1.12387e-4 A, and v(d) 0.4283 V where it was 0.4371 V. paramgiven
  [8] now prints twelve digits: its two draws agree to six at 27 °C.
- The full sweep: 605 of 605.

## What was wrong

A built-in model whose card gives no `tnom` measures its parameters at the circuit's nominal
temperature, `CKTnomTemp`, which `.option tnom` sets (27 °C otherwise). The OSDI layer served that
temperature only as `$simparam("tnom")`, which the industry models do not read: their `tnom` is an
ordinary model parameter with a literal default. Nothing ever set it.

A common-source stage of the VA-Models BSIM4 4.8 beside the built-in BSIM4 4.8 (`w=1u l=100n`,
20 kΩ load, `vin` 0.6 V):

| deck | compiled `v(out)` | built-in `v(out)` |
|---|---:|---:|
| no tnom anywhere | 0.084861 | 0.083282 |
| `.option tnom=50` | **0.084861** (unmoved) | 0.067959 |
| `tnom=50` on both cards | 0.067957 | 0.067959 |
| `tnom=27` on both cards | 0.083278 | 0.083282 |

The banner of the second run read *TNOM = 50*. The first row is the default case going wrong as
well: the VA-Models BSIM4 tests `$param_given(tnom)` and falls back to `DEFAULT_TNOM`, 25 °C, with
the comment "Verilog-A does not support access to the modelcard default Tnom value". By default it
measured its parameters 2 °C below the built-in, which `showmod` (printing *tnom 27*) did not show.
EKV does the same with a sentinel default of 1e21.

## What changed

Before each `setup_model`, a compiled model whose card gives no `tnom` gets the circuit's nominal
temperature in it, as every built-in does, in two cases:
- **`.option tnom` was written.** It reaches every compiled model, as it reaches every built-in.
- **The model's own default asks for it.** That is a default equal to the SPICE nominal temperature
  (27 °C, 300.15 K) or a "not given" sentinel that is no temperature at all (BSIM4's fallback test,
  EKV's 1e21). With no option, BSIM4 and EKV now run at 27 °C. A model with a literal 27 runs
  where it ran.

Models whose authors chose another default keep it until `.option tnom` is written: DIODE_CMC's
21 °C, fbh_hbt's 20 °C, angelov's 25 °C.

**The parameter** is a real scalar model parameter named `tnom`, in any case and under any of its
aliases.

**Its unit** is read from its default before its `units` attribute, which the corpus does not keep
straight:
- HiSIM-HV and ASM-HEMT 1.0.1 declare `TNOM = 27.0` with units "K", and use it in Celsius;
- the OpenVAF test diode and resistor declare `tnom = 300` with units "Kelvin";
- EPFL-HEMT declares `TNOM = 300` with no units.

A default between 150 and 1000 is Kelvin, any other temperature Celsius, and a sentinel defers to
the `units` attribute. The default is the object's literal one when it exports the table, and
otherwise the value the model's first setup left in the parameter. The judgement is made once per
model.

**A written value is the user's.** A `tnom` on the card, from `altermod` or from a sweep is never
touched. A value the simulator wrote is refreshed at every setup, so `option tnom=60` between runs
takes effect, an `altermod tnom=40` after it holds, and `reset` keeps the option (E-756).

**Out of range.** A nominal temperature outside the parameter's declared range is not written; a
warning says so once, and the model keeps its default:

```
Warning: model mm: the nominal temperature 50 C is outside the range of its 'TNOM' (from [22:32]); the model keeps its own default.
```

**A model without a `tnom`** gets a note, once, when `.option tnom` is written. The note names the
parameter its description calls its reference temperature, which for PSP is `TR` and for MEXTRAM
`tref`:

```
Note: model mm: .option tnom does not reach it -- the model has no 'tnom' parameter; its reference temperature is 'TR' ("nominal (reference) temperature"), set on the .model card.
```

## The checks

`tnomoption_examples` (new), under both solvers. Each small module copies one family's pattern,
with R(T) = r·(1 + tc·(T − tnom)) at 27 °C, so the current reads the nominal temperature back. A
built-in resistor with `tc1` is the twin.

| check | what | E-913 |
|---|---|---|
| [1] | the BSIM4 pattern runs at 27 °C by default, as the built-in twin does | 0.980 mA, its 25 °C |
| [2] | `.option tnom=50` reaches it: the built-in twin's 1.2987 mA | unmoved |
| [3] | a `tnom` on the card wins over the option | passes |
| [4] | the DIODE_CMC pattern keeps its 21 °C, and takes the option | the option is lost |
| [5] | a `tnom` in Kelvin keeps its 300 K and takes the option as 323.15 K | the option is lost |
| [6] | `TNOM = 27.0` with units "K" is read as Celsius | the option is lost |
| [7] | the EKV pattern's sentinel takes 27 °C | 25 °C |
| [8] | 50 °C outside [22:32] is not written, and a warning names the range | no warning |
| [9] | a model without `tnom`: a note names its `TR`, only with the option | no note |
| [10] | the option between runs, `altermod`, then `reset` | the option is lost |
| [11] | the VA-Models BSIM4: the point of `tnom=27` on its card, 4e-5 from the built-in, and `.option tnom=50` gives its card's `tnom=50` | 0.084861 V |

## Limits

- **The name.** Only a parameter named `tnom` takes the option. PSP's `TR` and MEXTRAM's `tref`
  are reference temperatures, but `tr` is a transit time in Gummel-Poon, VBIC and HiCUM, so a
  name rule cannot include them. The note says where to set them.
- **A Kelvin `tnom` without a literal default and without units** is read as Celsius.
- **`$simparam("tnom")`** answers as before.
