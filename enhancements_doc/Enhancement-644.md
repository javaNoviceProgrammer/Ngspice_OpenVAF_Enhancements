# Enhancement-644: a paramset's own parameters are instance parameters, and an instance selects its member (IHP hunt C1, C2)

**Scope:** C1 and C2 of the
[2026-09-15 IHP SG13G2 hunt](../docs/bug_hunts/2026-09-15_ihp-sg13g2-paramset-library.md).
Compiler: `openvaf/sim_back/src/module_info.rs` (a paramset's own parameter
is `is_instance` unless `(* type="model" *)`). ngspice:
`src/osdi/osdiinit.c` (`osdi_select_paramset_member` with an instance line's
parameters; `osdi_paramset_family_head`/`_of`; the collision warning skips a
bound parameter; no bare `i` alias over a model's own `i`),
`src/spicelib/parser/inp2n.c` (the per-instance selection: the first `n`
line binds the card, a later one needing another member gets a clone card),
`src/spicelib/parser/inpgmod.c` + `inpmkmod.c` + `include/ngspice/inpdefs.h`
(`INPmodOsdiSel`), `include/ngspice/osdiitf.h`. New suite
[`paramsetinst_examples`](../examples/paramsetinst_examples/) (14 checks per
solver). **Both sides.**

**Suites:** `paramsetinst_examples` 14 of 14 per solver, both solvers (7 fail
on the E-643 binaries); every paramset suite (`paramset`, `paramsethsp`,
`paramsetlrm`, `paramsetoverload`, `paramsetguard`, `modelparamset`,
`cardbound`, `macrofold`, …) green; workspace `cargo test` green; full sweep
517 of 517.

## What was wrong

**C1.** A paramset's own parameters became the twin module's *model*
parameters, so the one way to set them was a `.model` card:

```
n1 n1 0 0 rsil l=0.5u w=0.5u mm_ok=0
Error … unknown parameter (l): it is a model parameter of this device -- set it on the .model card, not on the instance line
```

That is not what a paramset is. LRM 6.4 makes the paramset's parameters
what an *instance* of it sets — `rsil #(.l(0.5u), .w(0.5u), .mm_ok(1))
r1(n1, gnd, gnd)` in the IHP decks — and 6.4.2 selects the member per
instance from exactly those values. A SPICE device library is written the
same way: one card per device kind, geometry on the instance line. With
model-only parameters every geometry needed its own `.model` card, and the
selection could only look at the card.

**C2.** The E-335 case-collision warning ("declared more than once differing
only in case; only one of them can be set from a netlist") fired for pairs
in which nothing can be set wrongly: a target-module parameter the paramset
*bound* — PSP's `SWSOA` under the paramset's own `swsoa`, `sp_resistor`'s
`r` alias under the paramset's `R` — is `PARA_FLAG_FIXED` and takes no
netlist value at all; and the loader's own bare `i` alias for a two-terminal
device (E-394) collided with a model's `(* desc="Current" *) real i`, where
the model's entry wins the lookup anyway.

## What changed

- **Compiler.** A parameter declared inside the `paramset` a twin was
  lowered from (`Module::paramset_decl_range`, E-643) is an instance
  parameter unless it carries `(* type="model" *)`; a pass-through
  target-module parameter is what its own declaration says. Everything
  downstream already knew how to treat an instance parameter: the card
  gives the instances' defaults (`showmod` lists them as "instance defaults
  on this card"), the instance line and `alter` set them, and E-546's
  fixpoint promotes the bound parameters whose overrides read them
  (`.resistance = 7.0 * l / w`) to per-instance evaluation, silently, as it
  does for any localparam.
- **Selection per instance.** `osdi_select_paramset_member(type, card,
  inst, …)` takes the instance line's `name=value` pairs beside the card's
  — an instance value replaces the card's for the same name; a name no
  member declares (`m=`, `temp=`, a misspelling INPdevParse refuses later)
  takes no part. In `INP2N`, before the card is materialised: a card that
  heads a family and is not yet bound is bound to the member this instance
  selects (`INPmodOsdiSel` records it, so `create_model` does not select
  again); a card already bound to another member gets a **clone**,
  `<card>.<member>` (the bin cards' naming), made once by `INPmakeMod` on
  the same card line and shared by every instance selecting that member —
  with a note: `n5: paramset 'rsil' resolved to its member 'rsil__2' for
  this instance's parameters, where .model rsil is bound to 'rsil' -- a
  second card, rsil.rsil__2, is made for it (LRM 6.4.2)`. The card-only
  route (E-565, a card used by no `n` line yet) is unchanged, and an
  instance that gives nothing on a card that gives nothing is still the tie
  error.
- **C2.** `osdi_warn_case_collisions` takes the descriptor and skips a pair
  in which either entry is `PARA_FLAG_FIXED`; the bare `i` alias is not
  synthesised when the model declares an `i` of its own (instance parameter
  or operating-point variable), so `@n1[i]` is the model's value as before
  and nothing is warned. Two settable `gain`/`GAIN` still warn.

## Verification

| check | result |
|---|---|
| `n1 1 0 r0 l=1u w=0.5u mm_ok=0` over a paramset with own `w`, `l`, `mm_ok` and a `(* type="model" *) tc` | accepted, read back, I = 1 V / 14 Ω; `tc` on the instance line refused as a model parameter; the card's `l=2u` reaches an instance that does not set it (1 V / 28 Ω); `showmod` lists `w` under the instance defaults and `tc` among the model parameters |
| `.model r0 rs` + `n1 … mm_ok=0` + `n2 … mm_ok=1` | n1 is `rs` (7 Ω), n2 is `rs__2` (mm = 2, 3.5 Ω) through the clone `r0.rs__2`, noted |
| the first instance selects `rs__2`; two later `mm_ok=0` instances | the card is bound to `rs__2` (noted), n2 and n3 share one clone `r0.rs` |
| card `mm_ok=0`, first instance `mm_ok=1` | the instance's value selects (`rs__2`), and being first it binds the card itself |
| `mm_ok=2` on the instance / `m=2 temp=30` beside `mm_ok=1` / nothing anywhere | refused with each member's reason / selected, the builtins ignored / the tie error |
| IHP `resistor_paramset.va` (E-641's fold, E-643's ranges): one `.model rsil rsil` card, `l`/`w`/`mm_ok` on the instance lines | rsil/rppd/rhigh at 1 mA give the gnucap values; an `mm_ok=1` instance beside `mm_ok=0` ones gets `rsil.rsil__2` |
| IHP `sg13g2_moslv_paramset.va`: one `.model nmos sg13g2_lv_nmos_psp` card, `w`, `l`, `ng`, `as`, … on two instance lines | Id = 85.558 µA at w = 0.3 µ (the gnucap reference) and 174.9 µA at 0.6 µ, from one card |
| the collision warnings on the IHP objects (`sp_resistor`'s `i`; `ptap1`/`ntap1`/`Rparasitic`'s `r`; PSP's `swsoa`) | none; `gain`/`GAIN` still warns |
| every paramset suite; `cardbound`, `macrofold` | green |
| workspace `cargo test` | green |
| `paramsetinst_examples` | 14 / 14 per solver, both solvers; 7 / 14 fail on the E-643 binaries |
| full sweep | 517 of 517 |

## What this does not do

`alter` of an own parameter after the instance is bound (`alter @n5[mm_ok]=0`)
changes the value, not the member — selection is an elaboration-time act in
the LRM too, and the member's own range (`mm_ok from [1:1]`) refuses the
value. The clone card's name (`rsil.rsil__2`) is an internal one, listed by
`showmod` like a bin card's.
