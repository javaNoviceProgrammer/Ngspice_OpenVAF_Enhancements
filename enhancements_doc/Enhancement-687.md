# Enhancement-687: `showmod` lists every card of a group and `altermod m=` is refused as the card refuses it — the simulator-owned instance parameters on a `.model` card, made consistent

**Scope:** F5 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/frontend/device.c` (`showmod`: one block of instance defaults per card of the
group, named when the group has more than one), `src/frontend/spiceif.c`
(`altermod_instance_default`: `m` refused with the card's reason). `examples/carddefault_examples/`
(four checks, 19). **ngspice only.**

**Suites:** [`carddefault_examples`](../examples/carddefault_examples/) 19 of 19 per solver, both
solvers (2 of the 4 new checks fail on the E-680 binaries: the per-card listing and the `altermod`
refusal; the "no block for a card without defaults" and the `_mfactor` control pass there);
`paramsetinst` (which pins the single-card wording) unchanged; full sweep 531 of 531.

## What was wrong

The hunt wrote that a `.model` card's `temp=60` and `dtemp=10` were honoured but hidden from
`showmod`, while its `_mfactor=2` was listed. On re-check the card path records all three
([E-599](Enhancement-599.md)'s `defaults` list) and a single card lists them; the hunt's probe was
`showmod mt1 mt2 mt4` — three cards of one type in one command — and **the listing printed the
first card's defaults only**, mt4's `_mfactor 2`, under the heading of the group. The other two
cards' defaults looked skipped. That is the real defect on the `showmod` side.

On the `altermod` side: [E-426](Enhancement-426.md) decided that `m` on a `.model` card stays
ignored, audibly ("`m` on a .model card is ignored; the multiplier is an instance parameter —
write it on the instance line (or as `_mfactor` on the model card)"), because making it work would
silently multiply any deck that has carried a stray `m=` for years. E-599's `altermod <model>
<instance parameter>=` path, added later, took `altermod mres m=3` and applied it to every
instance that follows the card — the very thing the card refuses, through the other door.

## What changed

**`showmod` prints one block per card of the group.** The E-599 listing is called once per
card through the group iterator (`dgen_for_n`), headed "instance defaults on card `<name>`:" when
the group has more than one card and "instance defaults on this card:" — the wording
`paramsetinst` pins — when it has one. A card without defaults gets no block.

**`altermod <model> m=` is refused**, in the card's words: "`altermod mres m=` is refused, as
`m` on the .model card is: the multiplier is an instance parameter — set it on the instance
(`alter <instance> m=...`), or `_mfactor` on the card and `altermod ... _mfactor=`". `_mfactor`
keeps working on both paths, as do `temp`, `dtemp` and `dt`, which the card path always recorded.

## Verification

| check | result |
|---|---|
| `showmod am am2 am3` with defaults on `am` and `am2` | a block for each under its own name, `am2`'s `width 5` under `am2`; no block for `am3` |
| `showmod am2` alone | "instance defaults on this card:" |
| `altermod am m=3` | refused with the card's reason; the instances unchanged |
| `altermod am _mfactor=2` | "'_mfactor' is an instance parameter; 2 is now the default …", as before |
| the hunt's `.model mt1 tres temp=60` / `mt2 … dtemp=10` / `mt4 … _mfactor=2`, `showmod mt1 mt2 mt4` | three blocks: `temp 60`, `dtemp 10`, `_mfactor 2` |
| the E-680 binaries on the suite | 2 of the 4 new checks fail |
| full sweep | 531 of 531 |

## What this does not do

- `m` on a `.model` card stays ignored with E-426's warning; this makes the command agree with
  the card, not the card with the command.
- A group with more cards than fit one screen width lists the defaults of the cards of the
  first pass only, as the parameter columns do.
