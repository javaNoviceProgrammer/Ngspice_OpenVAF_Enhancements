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
