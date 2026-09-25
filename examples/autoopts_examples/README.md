# autoopts_examples — Enhancement-572: a dig into `autobus`, `autoadapt`, `saveused` and `automc`

`verify_autoopts.py` pins, under **both** linear solvers, what a probe battery
over the four options found. It compiles its own `bus1.va` (a one-bit bus port)
and the models of the `autobus`, `autoadapt` and `osdimc` suites.

| option | found | now |
|---|---|---|
| `autobus` | a one-bit bus port (`inout [0:0] a`) has as many terminals as ports, so `N1 a b bus1` in shorthand was taken as spelled out and bound `a` as a plain node, a different node from `a[0]`, in silence | indexed like every other width; the explicit, KiCad and ground forms stay as written |
| `autobus` | a bus base the deck also uses as a plain node (`Rx a 0 1k` beside `N1 a b busdev`) sat on a node nothing else touched, in silence | named in pass 3, with the bit spelling to write instead |
| `saveused` | the deck's own `.meas`, `.print`, `.plot` and `.four` cards were not scanned, so their vectors went unsaved and the cards failed | scanned; they add to the set and never decide whether the option acts |
| `autoadapt` | a control block that still names the bits of a node the option split failed as "vector b is not available" | the split is named, the line quoted, `b_f` / `b_r` offered |
| `automc` | `mcseed=1.5` and `mcseed=abc` silently became seed 1 | said, once |
| all four | the documented OFF spellings (`nosaveused`, `noautobus`, `noautoadapt`, `noautomc`, `noosdimc`) were reported as unknown options | registered |

The trial rules of `automc` are pinned as documented behaviour rather than
changed: one trial per run-class command, a whole `sweep` being one trial, an
`op` and a following `tran` two, `montecarlo` one per sample.

Run it:

```
python3 verify_autoopts.py
```

Since [E-670](../../enhancements_doc/Enhancement-670.md) (hunt F17): the later
spelling of an option pair wins — `.option autocorner noautocorner`, two cards,
`set noautocorner` after a deck's `.option autocorner`, `noosdimc` against
`osdimc`/`automc`, `nosavemc` against `savemc` — where the `no` spelling used
to be accepted and ignored beside the positive.

## Enhancement-723: the control block and the parse-time options

Since [E-723](../../enhancements_doc/Enhancement-723.md) (five-options dig, F7 of
2026-09-25) the block's own `set saveused`, `set saveused=<value>`, `set nosaveused`
and `unset saveused` lines decide the option — the later line wins, the block beats
the cards — because `saveused` is decided from the block's text before the block
runs; `set nosaveused` under `.option saveused` had saved `out` alone, `set saveused`
with no card everything, in silence. `autobus` and `autoadapt` act while the deck is
parsed and cannot be reached from the block: every `set`, `setcs` or `unset` of
`autobus`, `noautobus`, `autoadapt`, `noautoadapt` or `adapter` there draws a note
that it comes too late and that a deck card or `.spiceinit` decides. Eight checks;
six fail on the E-722 binaries.
