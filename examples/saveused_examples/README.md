# Enhancement-469 — `.option saveused`

```
python3 verify_saveused.py
```

23 checks, both linear solvers. No model compile is needed — the whole suite
runs on a four-resistor divider, because what is being tested is *which vectors
survive*, not what they contain.

## What it does

Saves only the vectors the `.control` block actually reads:

```
.option saveused        (or `set saveused` from .spiceinit)
```

On the 2448-unknown deck this was written for, a 201-point parameter sweep:

| | |
|---|---|
| no `save` | 104.73 s — 521 ms/point |
| hand-written `save` of the four written vectors | 7.22 s — 35.9 ms/point |
| `.option saveused`, no `save` line | **7.08 s — 35.2 ms/point** |

with byte-identical results.

## The observable

Every check reads the vector set of the resulting plot with `display`. The
unrestricted circuit holds `{in, mid, out, v1#branch}`; a restricted run holds
only what was asked for. **Names are compared, not counted** — a count alone
would let a check pass on the right number of the wrong vectors, and an early
draft of this suite did exactly that (the count was off by one because the
sweep scale's name contains a hyphen).

## The check that matters most

```
let r = v(out) - v(mid)
wrdata results.txt r
```

Only `r` is written, and `r` is not a node. A scan of the `wrdata` arguments
alone would save nothing useful and the deck would fail where it used to work.
The suite asserts both halves: that `mid` and `out` are kept, and that the run
produces no missing-vector complaint. **Under-saving would turn a performance
option into a wrong answer**, which is why the implementation scans the whole
block rather than just the output commands.

## Standing aside

Three cases must leave the run untouched: an explicit `save`/`.save`, `all` as
an argument, and a block with no output command. The explicit-`save` case is
asserted *identical with the option on and off* rather than merely "restricted",
because the point is not that something is saved but that the author's own line
still means exactly what it says.

## Spellings

All ten are pinned — `.option saveused`, `=1`, `=true`, `=yes`, `=on` and
`set saveused` on; `=0`, `=false`, `=no`, `=off` and `nosaveused` off. This
project has had to repair that same off-word defect four times (E-450, E-451,
E-454, E-466), so a new boolean-ish option ships with its off-words tested.
