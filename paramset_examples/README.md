# paramset_examples — Verilog-AMS `paramset` blocks (Enhancement-21)

Demonstrates **`paramset`** blocks, using **version11's own** `openvaf-r` and
`ngspice-46`. A `paramset` defines a named, instantiable model that specialises
an existing behavioural module by binding some of its parameters — the
Verilog-AMS way of shipping a *model library* (one module, several named
pre-configured variants), analogous to a set of SPICE `.model` cards but written
in Verilog-AMS and able to *compute* the bound values.

## Syntax

```verilog
paramset <name> <target_module>;
    parameter real <p> = <default>;   // the paramset's own (card) parameters
    .<target_param> = <expr>;         // bind a target-module parameter
endparamset
```

`<name>` becomes its own OSDI model (usable as `.model foo <name>` in a netlist).
It has the same terminals and analog behaviour as `<target_module>`, but each
bound target parameter takes the value of its `<expr>` (which may reference the
paramset's own parameters) and is no longer settable from the model card.
Target parameters that are *not* bound remain settable (pass-through).

## What `paramset_demo.va` shows

One behavioural module `conductor` = `g0*(1 + k*V)` (a mildly nonlinear
conductance) and three paramsets:

- **`res_1k`** — a fixed 1 kΩ resistor (both parameters bound to constants);
- **`res_kohm`** — resistance set in kΩ through a card parameter `kohm`, with the
  conductance computed as `1/(kohm*1000)`;
- **`varistor`** — binds only `k` (from card parameter `kv`) and leaves `g0`
  settable (pass-through).

## Run

```
python3 verify_paramset.py
```

Expected:

```
res_1k        I(1V)  = V/1kOhm    ... PASS
res_kohm(k=2) I(1V)  = V/2kOhm    ... PASS
res_kohm(.5)  I(1V)  = V/500      ... PASS
varistor      I(0.4) nonlinear    ... PASS
varistor      bound k not settable... PASS
varistor      AC gm = g0(1+2kV)   ... PASS
conductor     base module intact  ... PASS
ALL PASS
```

The checks prove that constant bindings, card-parameter-driven binding
expressions, and pass-through of unbound parameters all work; that a **bound**
parameter is **not** settable from the card (setting `k=9` is ignored); that the
**derivative flows through the paramset** (the AC conductance `gm = g0(1+2kV)` is
exact — the autodiff Jacobian runs on the shared body under the paramset); and
that the base module `conductor` still works independently.

## Notes / limitations

- The target module must be declared in the same file.
- Bound parameters become internal `localparam`s of the specialised model.
- Not supported (future work): multiple `paramset`s sharing one name with
  instance-based *selection*, and `aliasparam`/statement-based selection blocks —
  each `paramset` here maps to exactly one model.
