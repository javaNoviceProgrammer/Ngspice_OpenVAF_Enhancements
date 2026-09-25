# Enhancement-723: `set saveused`, `set nosaveused` and `unset saveused` in the control block count, the later line winning — and a `set` of `autobus` or `autoadapt` there, which comes after the deck was parsed and changed nothing, says so; E-670's "from the control block, for every pair" held for the options read when a run starts and not for the three that act before the block runs

**Scope:** F7 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/frontend/dotcards.c` (`e469_block_decision`, `ft_saveused`),
`src/frontend/inp.c` (`inp_note_parse_time_sets`, called before `ft_saveused`).
[`examples/autoopts_examples/`](../examples/autoopts_examples/) (section E-723, 8 checks,
43 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page.

**Suites:** `autoopts` 43 of 43 per solver, both solvers (37 of 43 on the E-722
binaries); `saveused`, `saveforms`, `savenoise`, `savekw`, `savemiss`, `autobus`,
`autobusopt`, `busmix`, `busmixed`, `subbus`, `autoadapt` 27 of 27, `adaptmsg`,
`adaptlisted`, `adaptquiet`, `silentaccept`, `optknown`, `hunt12diag`, `autocorner`
23 of 23, `vacorner`, `cornerscmd`, `savecorner`, `osdimc`, `savemc` unchanged; no new
build warnings; full sweep, run alone.

## What was wrong

| deck | control block | before |
|---|---|---|
| `.option saveused` | `set nosaveused` before the `op` | `out` alone saved |
| none | `set saveused` | everything saved |
| `.option autobus` | `set noautobus` | the line expanded |
| none | `set autobus` | not expanded |
| `.option autoadapt adapter=…` | `set noautoadapt` | adapted |
| none | `set autocorner`, `set osdimc` | the pass runs, the draws happen |

Nothing was printed in the five silent rows. [E-670](Enhancement-670.md)'s heading
says "the later spelling of an option pair wins … from the control block" and handbook
§3.7 listed `nosaveused`, `noautobus` and `noautoadapt` among the pairs that follow
that rule; E-670's own suite pinned `set noautocorner` from the block, and the deck-card
forms for the rest. The rule is true of every option read when a run starts —
`autocorner`, `osdimc`, `savemc` and the others `cp_getvar` at that point — and was
never true of the three that act earlier: `autobus` in `INP2N` and `autoadapt` in
`INPadapt` while the deck is parsed, `saveused` in `ft_saveused` "immediately before
the control block executes" ([E-469](Enhancement-469.md)). A `set` inside the block
runs after all three, in either direction, and the deck kept what its cards (or
`.spiceinit`, E-454) had decided while the line looked honoured.

## What changed

**`saveused` honours the block's lines** (`dotcards.c`, `e469_block_decision`). The
option is decided from the block's *text* before the block runs — its output commands
are read the same way — so a `set` inside it is not too late here. The block's last
`set saveused`, `set saveused=<value>`, `set nosaveused` or `unset saveused` line
decides (on one line the last word), and the block is later than the cards: `set
nosaveused` under `.option saveused` saves everything, `set saveused` with no card keeps
what the block reads, `set saveused=off` and `unset saveused` turn it off, `unset
nosaveused` changes nothing. `controls` reaches `ft_saveused` in reverse order (inp.c
reverses it after the call), so the first match is the block's last such line.

**`autobus` and `autoadapt` say a control-block `set` comes too late** (`inp.c`,
`inp_note_parse_time_sets`, run before the block): every `set`, `setcs` or `unset` of
`autobus`, `noautobus`, `autoadapt`, `noautoadapt` or `adapter` in the block draws,
once per line,

```
Note: `set noautobus` in the control block comes too late for this deck: autobus acts while the deck is parsed, before the block runs, and a deck card (.option autobus, .option noautobus) or .spiceinit decides it; the line changes nothing here
```

The deck's behaviour is as it was (the card decides); what changes is that the line
is named. Executing those lines ahead of the parse was considered and not done: a
`set` inside an `if` the block never reaches would then act, and the two options'
whole design is that the deck's cards are read where the deck is read.

**The handbook** says which pairs the control block reaches and which two act earlier.

## Verification

`autoopts` section E-723: `.option saveused` with `set nosaveused` in the block saves
everything (was `out` alone); `set saveused` with no card keeps `out` alone (was
everything); `set nosaveused` then `set saveused` keeps `out` alone, the later line;
`unset saveused` and `set saveused=off` each turn it off; `.option autobus` with `set
noautobus` still expands (0.5) and the line is named with "autobus acts while the deck
is parsed"; `set autobus` with no card does not expand (0) and is named; `.option
autoadapt adapter=amod` with `set noautoadapt` still adapts (0.3278689) and is named;
nothing is said when the block does not mention them. On the E-722 binaries six of the
eight fail. The 35 checks of E-572 and E-670 unchanged.

By hand: the hunt's six decks; the 26 suites; the sweep.

## What this does not do

- It does not make `set autobus` or `set autoadapt` act from the block. They cannot:
  the deck is already parsed. The note says where they act.
- `saveused`'s block scan reads text, not control flow, exactly as its output-command
  scan does (E-469): a `set nosaveused` inside an `if` the run never enters still
  turns the option off for that deck.
- The options read when a run starts are untouched; E-670's rule stands for them.
