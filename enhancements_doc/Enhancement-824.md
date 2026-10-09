# Enhancement-824: a `.model` card inside a `.subckt` no longer makes the parse quadratic in the instance count

**Scope:** F8 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `spicelib/parser/inplkmod.c`: `INPlookMod` asks the model hash table.
- `xspice/mif/mifgetmod.c`: `MIFgetMod` starts its walk at the model the hash names.

`examples/libsens_examples/` (section [2], four checks). **ngspice only.**

**Suites:** [`libsens_examples`](../examples/libsens_examples/) 18 of 18 per solver (3 of the 4
checks in [2] fail on the E-822 binaries; the fourth is a control: two subcircuits, each with
its own card). The full sweep, 544 of 544.

## What was wrong

Subcircuit expansion copies a card defined inside a subcircuit once per instance (`x1:gm`,
`x2:gm`, …). Each instance then looks its model up with `INPlookMod`, a linear `strcmp` walk
of the whole model list. The hunt sampled the 32 000-instance run in that loop. One `op`,
wall time, on the E-822 binaries:

| 32 000 wrappers | card inside | card at top level |
|---|---|---|
| built-in R card | 7.9 s | 0.13 s |
| OSDI card | 2.8 s | 0.15 s |
| XSPICE `gain` card (16 000) | 4.2 s | 0.37 s |

The wrapper idiom, a Verilog-A device in a subcircuit that holds its own card, is exactly this
shape.

`INPmakeMod` keeps a hash table of the same models, `modtabhash`, beside the list. The list
and the hash are swapped together when the current circuit changes, and `INPgetMod` already
asked the hash. `INPlookMod` and XSPICE's `MIFgetMod` still walked the list.

## The change

- **`INPlookMod`** returns the hash's answer when the table exists. It walks the list only when
  there is no table. The names are unique, since `INPmakeMod` refuses a second card of a name,
  and the comparison is the same `strcmp`.
- **`MIFgetMod`** starts its walk at the model the hash names. Nothing before that model can
  match.

## The checks

`libsens_examples` [2]. Each time is the fastest of three runs.
- 32 000 wrappers with a built-in card inside: under four times the time with the card at
  top level (0.23 s against 0.13 s; was 60×). The copies cost about 1.6× of their own, a model
  and its setup per instance; a loaded CI runner measured 2.2×.
- The same with an OSDI card (0.24 s against 0.15 s; was 18×).
- 16 000 wrappers with an XSPICE card (0.24 s against 0.18 s under KLU; was 11×). This check
  is skipped, and says so, where no `analog.cm` sits beside the binary.
- Two subcircuits, each holding a card `gm` (1m and 2m): each copy is its own card, i(v1) =
  −4 mA (control).

Doubling the count doubles the time: 0.49 s at 64 000 wrappers and 1.1 s at 128 000, for
either card.

## Limits

- Under the Sparse solver, XSPICE code models that share one node are still quadratic in their
  number, wherever their card is: 1.3 to 1.6 s for 32 000 with the card at top level, before
  and after. A profile puts the time in Sparse's matrix-element lookup (`spGetElement`), which
  walks that node's column. Under KLU the 16 000-instance deck takes 0.18 s, against 0.41 s
  under Sparse.
