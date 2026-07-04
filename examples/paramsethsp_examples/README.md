# paramsethsp_examples — paramset hierarchical system parameters (Enhancement-44)

Demonstrates **paramsets setting hierarchical system parameters** —
`.$mfactor = 8;` alongside ordinary target-parameter bindings, the LRM 6.4
"quad device" idiom — using the committed `openvaf-r` and `ngspice-46`.

## What was broken

`$mfactor`, `$xposition`, `$yposition`, `$angle`, `$hflip`, `$vflip` were
already fully working at the instance level (readable in expressions;
settable as `m=` / `_xposition=` … on ngspice instance lines; `$mfactor`
scaling flows, leaving potentials invariant, and scaling noise PSDs exactly).
But a paramset could not set them: `.$mfactor = 8;` was a parse error
("unexpected token system function identifier").

E-44 parses the form, stores each override as a hidden localparam in the
E-21 twin module (named `$paramset$mfactor` so ngspice's `m=` alias keeps
pointing at the instance value), and composes it with the instance-level
value in `sim_back` — rewriting **every** use of the system parameter:
explicit reads, the DAE builder's automatic flow scaling, its noise scaling,
and the derivative code. Composition follows the LRM hierarchy rules:
**multiplicative** for `$mfactor`/`$hflip`/`$vflip`, **additive** for
`$xposition`/`$yposition`/`$angle` — so `m=3` on a `.$mfactor = 8` paramset
gives an effective multiplicity of 24. Override expressions may reference the
paramset's own card parameters (`.$mfactor = nf;`).

## Run

```
python3 verify_paramsethsp.py
```

Checks (ALL PASS, exact): quad idiom 2 kΩ/8 → 250 Ω; netlist `m=3` composes to
24×; all six parameters read composed values with instance overrides on top;
`.$mfactor = nf` tracks `nf` from the model card; noise PSD scales with the
paramset multiplicity exactly like netlist `m=`; `.$vt = 1;` rejected with a
named diagnostic ("'$vt' is not a hierarchical system parameter").
