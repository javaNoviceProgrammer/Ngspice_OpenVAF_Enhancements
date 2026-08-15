# Enhancement-464 — a bus formal and a local bus on one instance line

Inside a subcircuit declared with **bit-level formals**, an OSDI instance could
carry one of each:

```
.subckt s a[0] a[1] a[2] a[3]
N1 a b mymodel1          <- `a` is a bus formal, `b` is a local bus
```

Enhancement-449 expands `a` into the caller's four actuals, because the formals
`a[0]`..`a[3]` exist. `b` has no formals, so it stayed **one token**. The line
then carried five node tokens where autobus needs two (one per port) or eight
(one per terminal). It is neither, so INP2N expanded nothing and the tokens
bound **positionally**: `a[0..3]` correctly, `x1.b` onto `b[0]`, and the top
three bits dangling.

| the same circuit | answer |
|---|---|
| inside the subcircuit | **1.0** — with `3 of the 8 terminals of model type 'chan' are not connected`, `b[1] b[2] b[3] absent` |
| flattened by hand | **0.5238095** |

It warned, but the warning named the missing terminals rather than the cause,
and the deck still ran and produced a wrong answer.

## The fix

Once **any** port on the line has been expanded from formals, the line cannot
still be in shorthand — so every remaining bus port is expanded at the same
point, to `x1.b[k]`. That is exactly the node INP2N would have produced, and the
same node a `b[0]` written elsewhere in the subcircuit translates to, so
references unify as before.

The widths come from the model, which is reachable at flattening time even
though the model *table* is not: `pre_osdi` has already registered the module,
and the deck's own `.model` cards map a model name onto it, so
`.model mymodel1 chan` plus `INPtypelook("chan")` gives the `IFdevice`. The port
grouping is `INPbusPorts` — INP2N's own function, exported rather than copied,
so the two cannot drift.

Only mixed lines change. A line whose ports are all formals, an all-local line,
a bus-**base** formal (`.subckt s2 a`, which always worked), and a scalar port
beside a bus formal are each pinned unchanged.

## The second defect, found while fixing the first

The first version of the fix spelled the local bus's bits with brackets even
under `.option autobus=kicad`, so `x1.b[k]` never met the `b_0_` written beside
it and the bits floated — the failure the fix was meant to remove, in a new
place.

The cause is the one Enhancement-454 already had to repair in this same option:
**the `autobus` variable is not published at flattening time.** That is the
entire reason `inp_set_autobus()` exists — inp.c reads the option cards directly
and hands the answer down. Asking `INPbusKicadStyle()` there, which reads the
published variable, silently returned "brackets" for every deck. The style now
travels with the flag, resolved with the same precedence: a deck card wins,
otherwise a `set autobus=kicad` from `.spiceinit`.

Two readers of one option, disagreeing, for the third time in this feature's
history. The suite pins the kicad spelling on a mixed line so there is not a
fourth.

## Interaction with Enhancement-463

A mixed line now leaves flattening in fully explicit form, and `.option
autoadapt` only considers lines in one-token-per-port shorthand. So a local bus
shared by two devices on **mixed** lines is not auto-adapted, where the same
bus on all-local lines is. That is a narrowing of `autoadapt`'s reach, not of
correctness — before this change the same circuit was simply wrong — and it is
recorded here rather than fixed, since extending `autoadapt` to recognise
terminal-level bus groups is its own change.

## Verification

`examples/busmix_examples/verify_busmix.py` — **13/13**, both solvers. Every
check is a differential: the subcircuit form must equal the same circuit written
flat, on a ladder where all four bits read differently so a mis-ordered or
partial expansion cannot pass by coincidence. One device and two, the kicad
spelling, the four must-not-change forms above, and `autobus` off leaving the
old behaviour exactly as it was.

Enhancement-449's own suite (`subbus`, 16/16), `autobus` (12/12), `autobuskicad`
(27/27), `autoadapt` (26/26) and `busportsub` (9/9) all still pass on the changed
path. Full regression **378/378**, both solvers. ngspice-only.
