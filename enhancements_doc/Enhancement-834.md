# Enhancement-834: under `osdimc` the bins of one binned model draw one process deviate

**Scope:** F18 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `osdi/osdisetup.c`:
  - `osdimc_def_hash`, `osdimc_def_name`: a card's definition, its name without a bin's
    `.<digits>`;
  - `osdimc_walk_slot` and the bin table: walk coordinates and weight factors shared by bins;
  - the keys of `osdimc_apply_type`, `osdimc_apply_derived` and the importance weight;
  - `osdimc_walk_count`.

`examples/seedac_examples/` (section [3], four checks). **ngspice only.**

**Suites:** [`seedac_examples`](../examples/seedac_examples/) 20 of 20 per solver (3 of the 4
checks in [3] fail on the E-831 binaries; the fourth is the unbinned control). The full sweep,
547 of 547.

## What was wrong

`nch.1` and `nch.2`, one device type at two sizes, with `(* std_rel=0.1 *) g` and the same
nominal, under `.option osdimc`:

| trial | `@nch.1[g]` | `@nch.2[g]` |
|---|---|---|
| 1 | 0.930m | 0.869m |
| 2 | 1.100m | 1.113m |

Process variation moves a whole device type together, so a transistor's process shift jumped
at a bin boundary. A process parameter's draw was keyed on the model card
(`hash(GENmodName)`), and the bins are separate cards.

## The change

A card's definition is its name, less a bin's `.<digits>` suffix. That is the
`<base>.<digits>` spelling ngspice's binning resolves an instance line's `nch` to, the rule
Enhancement-826 reads. A process parameter's draw is keyed on the definition, so every bin of
`nch` takes one deviate in each place the draws are used:
- **A plain trial.** The key is the same, so the z is the same. With different nominals the
  relative shift is shared: `g` = 1m and 3m both move by ×1.0403, then ×0.9932, ×0.9279.
- **`-lhs`.** The dimension key is the same, so the stratum is the same.
- **A walk (`wcd`).** A later bin takes the coordinate its first bin took and consumes none.
  `osdimc_walk_count` counts it once, so `wcd` reports one statistical dimension for the two
  bins (it reported two).
- **The importance weight (`highsigma`).** A shared deviate is one factor, not one per bin.
  Two bins give the estimate one unbinned card gives (2.5544e-02 ± 3.94e-03 both).
- **`-inflate`.** The scope is tested on the definition's name, so `@nch[g]` inflates every bin.
  A spec naming one bin matches nothing.

Any other name is its own definition, and its key is the hash of the whole name, exactly as
before. Mismatch (instance) draws are keyed on the instance, unchanged. The verbose lines
still name the card.

## The checks

`seedac_examples` [3], a module with `(* std_rel=0.1 *) g` and binning limits, cards
`nch.1` (g = 1m) and `nch.2` (g = 3m), `.option osdimc mcseed=42`:
- Three trials after the nominal baseline: `@nch.1[g]/1m` = `@nch.2[g]/3m` in each, and the
  shift moves.
- Two unbinned cards `pa` and `pb` still differ (control).
- `wcd`: `1 statistical dimension` (was 2), and the walk's point puts both bins at one
  relative shift.
- `highsigma 400 -scale 2`: two bins, and one card `nch`, give the same `P(fail)` and error.

## Limits

- A card named `x.1` that no instance reaches through binning is still taken as a bin of `x`.
- Copies of a `.model` inside a `.subckt` still draw per copy. That is the
  [statistics proposal](../docs/proposals/2026-10-06_statistics-vary-block.md)'s phase 0,
  undecided.
