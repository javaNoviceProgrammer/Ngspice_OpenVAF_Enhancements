# Enhancement-223 — XSPICE a-device model-type validation (`MIFgetMod`)

Fuzzing the netlist parser ([E-222](Enhancement-222.md)) left **one** residual
crash, in XSPICE rather than the netlist parser. This enhancement fixes it.

## The bug

An `a` device is an XSPICE **code-model** instance; the last token on its card is
a model name. `MIF_INP2A` (`xspice/mif/mif_inp2.c`) hands that name to
`MIFgetMod` (`xspice/mif/mifgetmod.c`), which looks the model up in the pass-1
table and — if it hasn't been instantiated yet — processes its `.model` card **as
a code model**: it casts `INPmodfast` to `MIFmodel`, reads the device's XSPICE
`DEVpublic` fields (`param`, `num_param`), and matches the `.model` parameters
through the MIF parameter path.

Nothing checked that the resolved model *is* a code model. If an `a` device's
model name happens to match a **non-code-model** `.model` — a diode, a BJT, a
resistor model — `MIFgetMod` walked all of that machinery over a structure that is
not a `MIFmodel` and over `DEVpublic` fields that a built-in SPICE device leaves
unset, reading unrelated memory as the wrong type → **SIGSEGV**.

The crash bit hardest when the non-code-model's parameter keywords **collide**
with the a-device's: a diode `.model` has `is`/`n`, so the parameter loop found a
keyword match and dereferenced the type-confused `setModelParm` path. The
fuzz-found trigger (E-222 residual) was exactly this, reached through an
[E-221](Enhancement-221.md) bus-expanded a-device inside a subcircuit:

```
.model dm d(is=1e-14 n=1)
.subckt rect a b
 a[0:0] D1 a b dm      ; a-device "a[0]" whose model dm is a *diode*
Rb b 0 1k
.ends
```

## The fix

A code model is *exactly* a device that carries a code-model evaluation function.
`cmpp` emits `.cm_func = <fn>` for every code model (`xspice/cmpp/writ_ifs.c`),
and it is the pointer XSPICE calls to evaluate the model
(`mifload.c`/`evtload.c`); every built-in SPICE device sets `.cm_func = NULL`.

`MIFgetMod` now validates that before treating anything as a code model:

```c
if (modtmp->INPmodType >= DEVmaxnum ||
    DEVices[modtmp->INPmodType]->DEVpublic.cm_func == NULL) {
    *model = NULL;
    return tprintf("MIF-ERROR - model %s is not a code model; an `a' "
                   "device requires an XSPICE code-model .model\n", name);
}
```

The guard sits *before* the `MIFmodel` cast and the parameter loop, so it catches
the model whether or not it has already been instantiated by an ordinary device
of the same name. A NULL guard on the inner `strcmp` was rejected as
whack-a-mole — the crash merely shifts to the next type-confused access; the model
**type** is the thing to validate. Legitimate code models are unaffected
(`cm_func != NULL`).

Scope: XSPICE only, one file (`xspice/mif/mifgetmod.c`); no change to the netlist
parser, devices, solver, or OSDI.

## Verification (`examples/xspicemodel_examples`)

`verify_xspicemodel.py` (8 checks, both solvers) asserts that six pathological
decks — an a-device pointing at a diode (with and without colliding params), a
BJT, a resistor model, the bus-expanded-in-a-subckt fuzz repro, and an undefined
model — now yield a **clean, bounded** error (no signal/abort, no hang), and that
a legitimate `adc_bridge` code-model a-device still binds and simulates (the
analog divider node solves to 0.5). Full regression: 182/182.
