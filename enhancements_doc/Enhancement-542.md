# Enhancement-542: a Verilog-A module named like an ngspice built-in is usable, never silently replaced, and case-twins are caught

**Scope:** the two registry findings of the 2026-09-04 bug hunt
([`docs/bug_hunts/2026-09-04_ngspice-osdi-integration.md`](../docs/bug_hunts/2026-09-04_ngspice-osdi-integration.md),
F1 and F2), plus a worse route that turned up while fixing them. A module
whose name is one of ngspice's own — a built-in device's name (`diode`) or a
`.model` type keyword (`res`, `d`, `sw`, `nmos` …) — could not be used from a
netlist, and on one route **the built-in silently simulated in its place**;
two modules in one `.osdi` whose names differ only in case collapsed into one
without a word; and `pre_osdi -f` on such a module **replaced the built-in for
the session**.

**Suites:** [`examples/multimod_examples/`](../examples/multimod_examples/)
grows from 16 to **24 checks**, both solvers; the compiler's L018 UI fixture
pins two keyword-named modules. Cargo 209 fast / 235 slow; full sweep
453/453. **Both tools change.**

## What went wrong

Compile a module called `diode` — a name any model library would reach for —
and load it:

```
Warning(osdi): device "diode" is already registered; keeping the existing device and ignoring this one
```

That is the same wording used when two `.osdi` *files* clash; nothing said
the collision was with a built-in, nor what to do. Then:

| the deck | what happened |
|---|---|
| `n1 2 0 md` / `.model md diode` | `incorrect model type! Expected OSDI or nport device` — loud, cause never named |
| `d1 2 0 md` / `.model md diode is=1e-20` | **the built-in junction diode ran**, took `is=1e-20` because it has that parameter too, and the deck finished with a plausible, wrong answer |
| `pre_osdi -f lcdiode.osdi` (any deck) | ngspice's junction diode was **swapped out of the device table**: every plain `.model … d` card ran the Verilog-A module for the rest of the session |

Two families of names collide. The `.model` type keywords `INPdomodel`
matches before it consults the device table — `c cpl csw d l ltra nhfet njf
nmf nmos npn nsoi phfet pjf pmf pmos pnp psoi r res sw txl urc vdmos vdmosn
vdmosp` (plus `ndev`, `numd`/`nbjt`/`numos`, `poly` in NDEV/CIDER/XSPICE
builds) — were not even refused: a module named `res` was registered and then
could never be selected, because every `.model … res` card became the
built-in resistor. And every built-in *device name* — `diode`, `resistor`,
`capacitor`, `inductor`, `bjt`, `jfet`, `switch`, `vsource`, `isource`,
`asrc`, `bsim4`, `hicum2`, `vbic` … — was refused with the generic line above.
The CMC reference sources sidestep all this by convention (`bsim4va`,
`hicumL2va`, `diode_va`, `resistor_va`), which is why it bites hardest on a
user-written module with a natural name.

The compiler's lint **L018** already warned at compile time for the
device-name family (the hunt's compile step had filtered that line out); it
did not cover the keyword family.

## F2: two modules differing only in case

```verilog
module Foo(p, n); … I(p, n) <+ V(p, n) * 1e-3; endmodule   // 1 mA at 1 V
module foo(p, n); … I(p, n) <+ V(p, n) * 7e-3; endmodule   // 7 mA at 1 V
```

Legal — Verilog-A is case-sensitive — and the compiler accepts both into one
`.osdi`. ngspice resolves a `.model` card's type case-insensitively, so only
the first could ever be reached: `.model m2 foo` gave `Foo`'s 1 mA, and
**nothing was printed**. The hunt blamed a case-sensitive comparison in the
registry's duplicate guard; the real cause was that the guard's scan stopped
at `DEVNUM`, which is only advanced after the whole file has been processed,
so a module never saw the ones registered *earlier in the same load*. Every
sibling check in the family already worked — two parameters differing only in
case warn, two model cards warn, a module colliding with a built-in is caught
case-insensitively — module-against-module within one file was the one
comparison never made.

## The fix

**Shadowing, and re-binding where the meaning is unambiguous.** An `n`-line
instance can mean nothing but an OSDI device, and ngspice materialises a
model *lazily* — at the first instance line that uses it, not at the `.model`
card. So the ambiguity is decided at the one place it is not ambiguous:

* **The loader** (`spicelib/devices/dev.c`) registers a colliding module under
  its own slot — for the keyword family it asks the parser through a new
  `INPbuiltinModelTypeKeyword`, which reads the same table `INPdomodel` does
  — and records it as **shadowed**, saying what the name costs:
  `Warning(osdi): Verilog-A module "res" (from "x.osdi") has the same name as
  ngspice's built-in Resistor (a .model type keyword). A .model ... res card
  resolves to the built-in; only an n-line instance re-binds such a card to
  this module, any other device letter gets the built-in. Rename the module
  to avoid the ambiguity (a _va suffix is the convention the reference compact
  models use).` `INPtypelook` returns the first match, so every card still
  resolves to the built-in and no deck that worked before changes.
* **`INPdomodel`** keeps the card's type token on the model entry
  (`INPmodTypeName`).
* **The N-line parser** (`inp2n.c`), before `INPgetMod` materialises the
  model, re-binds a card whose type resolved to a built-in to the shadowed
  module of that name: `Note(osdi): .model mm: type "res" is ngspice's
  built-in Resistor, but this n-line instance can only mean the Verilog-A
  module "res" from "x.osdi" -- binding the card to it.` A `.model mm res
  r=2000` on an `n` line now gives `-5.00000e-04`.
* **Materialisation as a built-in** (`create_model`, `inpgmod.c`) says so at
  that moment — the one place it is certain a built-in device letter is
  using the card: `Warning: .model md: created as ngspice's built-in Diode.
  The Verilog-A module "diode" loaded from "x.osdi" has the same name and is
  reached only from an n-line instance; this card is used by another device
  letter, so the built-in simulates.`
* **One card cannot serve both letters.** `n` first, then `d`: the `d` line
  fails ("incorrect model type"). `d` first, then `n`: the `n` line's error
  explains — *"model "md" was already created as ngspice's built-in Diode by
  another instance line … give this n line a .model card of its own, or
  rename the module"*.
* **The deck-reading pre-pass** (`inpcom.c`) no longer pre-judges `n` lines
  at all. It runs while the deck is being read, before any `pre_osdi` has
  loaded a library, so it cannot know about shadowed modules — and INP2N
  reports every genuine n-line mismatch later, naming the built-in the card
  resolved to.
* **`pre_osdi -f`** swaps the shadowed module's *own* slot and never the
  built-in's.
* **F2**: the duplicate scan covers the devices added earlier in the same
  load, and reports both spellings: `device "foo" is already registered as
  "Foo" by this same library; the two names differ only in case, which a
  .model card cannot tell apart, so "foo" is unreachable and every card of
  that type gets "Foo"`.

**The compiler** extends L018 to the keyword family with its own wording, and
both wordings now match the simulator: `.model <name> res` *resolves to* the
built-in Resistor, and ngspice re-binds such a card to the module only for an
`n`-line instance; the `_va` convention is in the help text.

## What this does not do

A `.model` card of a shadowed type used by a built-in device letter still
runs the built-in — that is what the letter asks for, and existing decks
depend on it. The difference is that it now says so at the moment it happens,
in the one place that is certain, instead of in silence. And the module's
author still hears about the ambiguity twice — at compile time (L018) and at
load — because a name that means two things to two tools is worth avoiding
even when both tools now cope with it.

## Verification

| check | result |
|---|---|
| `.model mm res r=2000` on an `n` line | `-5.00000e-04` (was "incorrect model type") |
| `vcvs` module on an `n` line (the E-29 segfault fixture) | 1 mA — runs |
| `d1` on a card of type `diode` | built-in runs; materialisation warning names the module and the library |
| `n` then `d` / `d` then `n` on one card | each fails loudly on the second user |
| `pre_osdi -f` on a shadowed module | `reloaded … (1 device)`; `showmod` of a plain `d` card still says *Junction Diode model* |
| `Foo`/`foo` in one `.osdi` | warned with both spellings; both cards audibly get `Foo` |
| genuine n-line mismatch, nothing loaded | INP2N: *"… but model "mm" is ngspice's built-in Resistor"* |
| cargo / sweep | 209 fast, 235 slow / 453 of 453 suites, both solvers |
