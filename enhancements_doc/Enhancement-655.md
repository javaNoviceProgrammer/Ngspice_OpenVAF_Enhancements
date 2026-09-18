# Enhancement-655: the `corners` command — the analysis at every process corner the loaded Verilog-A models declare, and `-mc N` for a montecarlo per corner

**Scope:** `src/frontend/com_sweep.c` (`com_corners`; `co_is_flag`,
`co_destructive`, `co_quote`), `src/frontend/com_sweep.h` and `com_commands.h`,
`src/frontend/commands.c` (the entry in both tables), `src/frontend/typesdef.c`
(the `corners` plot type), `src/frontend/mcsave.c` (the `corner` column, present
from the first cornered row on; `corner` a fixed column's name), `src/osdi/osdisetup.c`
and `src/include/ngspice/osdiitf.h` (`OSDImcCornerNames`, `OSDImcCornerName`; a
nominal asked for by name is a corner to `savemc`), `examples/cornerscmd_examples/`
(new, 18 checks per solver); handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
**ngspice only.** Phase 2 of the corner design ([E-654](Enhancement-654.md) is phase
1); `.option autocorner` is phase 3.

**Suites:** [`cornerscmd_examples`](../examples/cornerscmd_examples/) 18 of 18 per
solver, both solvers (18 fail on the E-654 binaries: the command does not exist
there); `vacorner`, `savemc`, `writemc`, `plotorder`, `mcyield`, `osdimc`,
`sweepanalysis`, `mcrecord` unchanged; full sweep 528 of 528.

## What was asked

E-654 lets a Verilog-A parameter declare its position at each process corner and
`.option corner=<name>` select one for a run. A corner analysis is all of them:
the same measurement at `tt`, `ss`, `ff`, `sf`, `fs`, side by side, and — the
foundry flow — a mismatch Monte Carlo at each. That was a `.control` loop of
`set corner=…`, an analysis, a `print`, and bookkeeping by hand.

## What changed

```
corners [-list <c1>[,<c2>...]] [-nonominal] [-analysis <cmd>] [-output <expr> ...]
corners [-list ...] [-nonominal] [-analysis <cmd>] -mc <N> <montecarlo arguments>
```

- **The set.** The nominal `tt` first, then every corner any loaded Verilog-A
  model declares, in declaration order. `-nonominal` drops the nominal; `-list`
  names the set (commas or spaces; `tt`, `nom`, `nominal` are the nominal), and a
  name no loaded model declares is refused up front, naming the declared ones. A
  circuit whose models declare no corner is refused.
- **The loop.** For each corner the command sets the `corner` variable, runs the
  `-analysis` command (default `op`; the E-341 list of analyses that would
  destroy the circuit is refused) and evaluates each `-output` expression, its
  last value, as `sweep` does. A corner whose analysis failed, or an output that
  did not resolve there, is NaN — a gap, not a number that looks real; an output
  that resolves at no corner is an error and is not recorded. Without `-output`
  the corners are run, the per-corner plots kept, and nothing recorded, said.
- **The plot.** `corners<n>`, scale `corner` = the corner's index (0, 1, …), one
  vector per `-output`; the names are printed in a table beside the values and
  kept in `$corners_names`, with `$corners_plot` and `$corners_n` (all cleared by
  a refusal).
- **`-mc <N>`.** The rest of the line is a `montecarlo` command, run once per
  corner as `montecarlo <N> <arguments>`, so every montecarlo feature (`-spec`,
  `-expr`, `-track`, `-writemc`, `-lhs`, `-warm`) applies per corner: the corner
  pins the process parameters ([E-654](Enhancement-654.md)), the mismatch draws
  go on. An `-analysis` given before `-mc` is forwarded; a quoted analysis
  reaches montecarlo intact. The plot then holds `yield`, `npass`, `nsamples`
  and `nfailed` per corner, and the table the yields. `-output` under `-mc` is
  refused: a corner is a montecarlo run there, whose `-expr` records values.
- **`savemc`.** A row records the corner it ran at: the file gains a `corner`
  column after `status` with the first cornered row (a file with none keeps its
  three fixed columns, so nothing an existing reader sees changes), the csv/txt
  header rewritten then, the `.xlsx` workbook likewise; `writemc corner=…` is
  refused as the other fixed names are. A nominal asked for by name —
  `.option corner=tt`, or the loop's `tt` — tags its rows `tt`.
- **Afterwards.** The `corner` variable is put back: an earlier `set corner=ff`
  holds and the next run is at `ff`; none stays none; a deck's `.option corner`
  is back in force.

## Verification

| check | result |
|---|---|
| `corners -output v(out) rsh=… r=…` | tt, ss, ff, fs in order; 100/115/88/100 and 100/110/90/100; `corners1` with the `corner` scale |
| `-list ff,ss`, `-list ff ss nom` | ff, ss; ff, ss, tt |
| `-nonominal` | ss, ff, fs |
| `$corners_n`, `$corners_names`, `$corners_plot`; after a refusal | 2, `tt ss`, `corners1`; unset |
| `-list sss` | the error naming ss, ff, fs; nothing runs |
| `-analysis reset`, `-bogus`, `-mc 0`, `-output` under `-mc` (both orders), `-list` alone | each refused |
| `-output nothere=v(nowhere)` | "never resolved", not recorded; the others intact |
| a corner whose analysis fails | "(the analysis failed)", nan, the others intact |
| `-mc 4 -analysis op -spec … -seed 5` | a montecarlo per corner; the table and plot; rows tagged, the cornered parameter 110 under ss and drawn under tt |
| `-analysis op` before `-mc`; `-analysis "tran 1u 3u"` | forwarded; intact |
| `set corner=ff` before; none before | ff after, the next run at ff; none |
| `.option savemc`, a plain `op` then `corners` | the `corner` column appears, the first row's cell empty; the `.xlsx` too |
| `.option corner=tt` | rows tagged `tt` |
| `writemc corner=5` | refused |
| no `-output` | said; the plot holds the scale alone |
| models without corners | refused |
| `oldhelp corners` | the entry |
| `.option corner=ff` in the deck | tt visited; ff back afterwards |

Full sweep 528 of 528 on both solvers.

## What this does not do

- No `.option autocorner` yet (phase 3): a plain `op` in a deck runs one corner.
- One value per output per corner: a waveform's last value, as `sweep` records
  it; overlaying per-corner waveforms is what the kept per-corner plots and
  `sweep -overlay` are for.
- The corner names are printed and kept in `$corners_names`; a plot vector
  cannot hold them, so the scale is the index.
- A `.lib` corner section is not a corner the command visits; it is a different
  model card.
