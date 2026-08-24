# Enhancement-474 — `.for` / `.endfor` in the netlist

```
python3 verify_forloop.py
```

31 checks, both linear solvers.

## What it does

```
.for i in range(1,4)
XP{{i}} P{{i}} P{{i+1}} hl_periodic n1={nL}
.endfor
```

becomes exactly

```
XP1 P1 P2 hl_periodic n1={nL}
XP2 P2 P3 hl_periodic n1={nL}
XP3 P3 P4 hl_periodic n1={nL}
XP4 P4 P5 hl_periodic n1={nL}
```

| form | |
|---|---|
| `range(first,last)` | **both bounds included** — `range(1,4)` is four iterations |
| `range(first,last,step)` | step may be negative; `range(3,1)` also counts down |
| `[7,2,9]` | an explicit list, in that order |

`{{i}}` is the index; `{{ expression }}` is integer arithmetic over it
(`+ - * / %`, parentheses, unary minus). The result is substituted as text, so
it builds node names, instance names, model names and parameter values alike.
Loops nest, and an inner bound may be an expression over an outer index.

**`range` includes both bounds, unlike Python's.** Check `[2]` exists to pin
that, because it is the one thing a Python-literate reader will assume wrongly.

## Why `{{ }}`

numparam owns single braces, and the body above carries both kinds: `{{i}}` is
this construct's, `{nL}` is numparam's. The pass removes every `{{ }}` it
introduces, so numparam never sees one — check `[11]`.

## Why the oracle is the hand-written deck

Every behavioural check runs the `.for` version *and the lines it stands for*,
and requires them to agree — the expansion line for line, and the solved result
character for character.

A construct that expands to *something plausible* is the failure worth guarding
against. Comparing against an analytic value would not catch a ladder wired one
node out of step; comparing against the deck the user would have typed does.
That is also why check `[12]` builds a 2000-section ladder both ways.

## What it must not disturb

- a `.control` block has its own `foreach` — check `[10]`
- `.param` values, which are numparam's and are still `{single}` braces

The bounds cannot be `.param`s: this runs before numparam exists, and that is
refused by name rather than misread. See the enhancement write-up for why the
ordering is that way round.

## Refusals

Fourteen malformed loops, each of which must be refused with exactly **one**
message — checks `[13]`–`[26]`. One fault, one message: a header that fails to
parse also retires its own `.endfor`, or the walk would report a second error
about a line that is perfectly correct.
