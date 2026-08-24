# Enhancement-474 — `.for` / `.endfor` in the netlist

A deck often needs a run of near-identical instance lines that differ only by an
index: a ladder, a stack of periodic sections, a bank of taps. Written out by
hand they are long, and wrong in ways that are hard to see — one node name out
of step in the middle of forty lines still parses, still simulates, and still
gives an answer.

```
.for i in range(1,4)
XP{{i}} P{{i}} P{{i+1}} hl_periodic n1={nL}
.endfor
```

expands, before anything else looks at the deck, to exactly

```
XP1 P1 P2 hl_periodic n1={nL}
XP2 P2 P3 hl_periodic n1={nL}
XP3 P3 P4 hl_periodic n1={nL}
XP4 P4 P5 hl_periodic n1={nL}
```

## The forms

| | |
|---|---|
| `.for i in range(first,last)` | **both bounds included** |
| `.for i in range(first,last,step)` | step may be negative |
| `.for i in [7,2,9]` | an explicit list, in that order |

`range(1,4)` gives **four** iterations, not Python's three. That is deliberate —
an index range in a netlist reads as "1 through 4", the way a bus range does —
but it is the one thing a Python-literate reader will assume wrongly, so it is
stated first here and pinned by its own check in the suite. `range(3,1)` counts
down; an explicit step that contradicts the bounds is refused rather than
silently producing nothing.

Inside the body, `{{i}}` is the index and `{{ expression }}` is integer
arithmetic over it — `+ - * / %`, parentheses and unary minus, so `{{i+1}}`,
`{{2*i}}` and `{{i*10+j}}` all work. The result is substituted as text, which is
what lets it build node names (`P{{i+1}}`), instance names (`XP{{i}}`), model
names (`.model rmod{{k}} ...`) and parameter values alike.

Loops nest, and an inner bound may be written in terms of an outer index:

```
.for i in range(1,3)
.for j in range(1,{{i}})
```

## Why `{{ }}` and not `{ }`

numparam already owns single braces, and the body in the example carries both:
`{{i}}` belongs to this construct and `{nL}` to numparam. Doubling the brace
keeps them apart with no ordering rule for the user to remember, and this pass
removes every `{{ }}` it introduces, so numparam never sees one.

## Why it runs first

The expansion happens at the top of `inp_readall`'s processing — before the
syntax check, before the scope tree, before numparam, before bus expansion and
subcircuit expansion. It produces ordinary netlist lines and nothing else, so
every later stage sees exactly what the user would have typed by hand, and no
later stage has to know the construct exists. `.include` and `.lib` have already
been pulled in by then, so a `.for` works in an included file, and inside a
`.subckt` body.

The cost of that placement is that **the loop bounds cannot be `.param`
values** — numparam has not run yet. Reordering the two to suit a text macro
would put the whole deck's evaluation order at risk, so instead a non-literal
bound is refused by name:

```
Error: .for: "{n}" is not a whole number
  the bounds are read before `.param` values exist, so they must be written out;
  an expression over an enclosing loop's index, spelled {{...}}, is fine
```

A `.control` block is skipped entirely — it has its own `foreach`, and this
construct must not disturb it.

## Refusals

A `.for` that cannot be expanded is not left for the device parser to
misinterpret; the deck is refused. Each fault produces **one** message:

- `.for` with no `.endfor`, and `.endfor` with no `.for`
- a missing loop variable, a missing `in`, trailing text after the list
- `range(` or `[` never closed, an empty list, a zero step, a step that
  contradicts the bounds
- a bound that is not a whole number
- `{{` with no closing `}}`, and `{{...}}` outside any loop
- more than 100000 iterations in one loop, or 2000000 generated lines in a deck

That "one message" is a property worth stating: a header that failed to parse
also retires its own `.endfor`, because otherwise the walk meets that `.endfor`
later and reports a second error about a line that is perfectly correct,
pointing away from the mistake.

## Verification

`examples/forloop_examples/verify_forloop.py` — **31/31**, both solvers.

**The oracle throughout is the hand-written deck.** Every behavioural check runs
the `.for` version and the lines it is meant to stand for, and requires the two
to agree — the expansion line for line, and the solved result character for
character. A construct that expands to *something plausible* is the failure mode
that matters here, and an analytic comparison would not catch a ladder wired one
node out of step.

Covered: the example above, line for line and as a solved circuit (v(P5) = 1/7);
the list form giving an identical deck; `range` including both bounds; step,
descending, single-value and list forms; index expressions; nesting, including
an inner bound over the outer index; a `.for` inside a `.subckt`; a 2000-section
ladder identical to the hand-written equivalent; a `.for` in an `.include`d
file; `{nL}` surviving beside `{{i}}`; a `.control` `foreach` left alone; and
each of the fourteen refusals above producing exactly one error.

Full regression **388/388**, both solvers. ngspice-only.
