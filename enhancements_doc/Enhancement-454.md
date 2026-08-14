# Enhancement-454 — one option, two readers, two answers

`.option autobus` is decided in two places, and they disagreed. The same card
switched the feature **on** inside a subcircuit and **off** at the top level, or
the reverse, depending only on how it was spelled.

## The subcircuit reader accepted `=` and never read the value

Enhancement-449's path reads the option cards directly — it has to, because the
option variable is not published until after subcircuit expansion. It matched
the name with a `strstr` plus a token-boundary test. The boundary test worked:
`noautobus`, `myautobus` and `autobusx` were all correctly ignored. But `=` is
neither alphanumeric nor `_`, so it passed as a clean terminator and **the value
was never looked at**:

```
.option autobus=0        ->  bus BOUND, silently
.option autobus=false    ->  bus BOUND, silently
.option autobus=no       ->  bus BOUND, silently
```

Every spelling that means *off* meant *on*. Enhancement-450 had already fixed
exactly this shape for `savecurrents` — which gets all four spellings right —
so autobus was its unguarded sibling.

## The top-level reader saw only one spelling

Enhancement-444's path (in INP2N) asks `cp_getvar("autobus", CP_BOOL, ..)`. But
the spelling decides the type the options machinery publishes:

| written | published as |
|---|---|
| `.option autobus` | BOOL `TRUE` |
| `.option autobus=1` | NUMBER `1` |
| `.option autobus=true` | STRING `true` |

A `CP_BOOL`-only query therefore saw the bare form and nothing else, so
`.option autobus=1` — an ordinary way to write a boolean option, and **not**
reported as an unknown option — silently left a top-level bus port unbound.

## Which makes one deck mean two things

| spelling | in a subcircuit | at the top level |
|---|---|---|
| `autobus` | ON | ON |
| `autobus=1`, `=true` | ON | **off** |
| `autobus=0`, `=false` | **ON** | off |

Both readers now answer by the same words. `e454_value_is_off` in
`frontend/inp.c` is the single list of off-words, and `savecurrents` was moved
onto it too, so the two options cannot drift apart again. The card reader
recognises the bare flag, `name=value` and the `noname` spelling, exactly as
`e450_savecurrents_card` does.

**Precedence is deliberately matched to the options machinery, not to
`savecurrents`.** Within one card the later token wins; *across* cards ngspice
keeps the first (`.option autobus` then `.option autobus=0` publishes `TRUE`).
The top-level reader can only follow what is published, so making the card
reader "last card wins" — which is what `savecurrents` does — would put the two
paths back into disagreement. Both orders are pinned by checks.

A deck card now also beats a `set autobus` from `.spiceinit`; it used to be
OR'd, so an init file could turn the feature on and no deck could turn it off.
With no card mentioning `autobus` at all, the init-file setting still applies.

## A bus could be declared, but not passed down

A bus port could be bound by name at the level that declared it, but not handed
to a subcircuit one level in:

```
.subckt inner a[0:4] b
N1 a b busdev            <- fine
.ends
.subckt outer a[0:4] b
Xi a b inner             <- "Error: too few nodes: xi a b inner"
.ends
```

The expansion was allowed on an OSDI device line only. It now applies to a
subcircuit call as well, so a bus travels by name through any depth of nesting.

The two spend their node budget differently, which is the whole subtlety:
`numnodes` for an OSDI line counts the **tokens written**, so each token costs
one however many nodes it expands to; for an X line it is the **callee's formal
count**, so a token standing for five nodes must spend five. `e449_expand_bus_port`
therefore returns the number of actuals it emitted instead of a flag.

At the top level a short X call still fails — cleanly, with *"Too few parameters
for subcircuit type"* — because there is no enclosing formal list to take the
bits from. With `.option autobus` off, X lines behave exactly as before; both
are pinned.

## The fix

| file | change |
|---|---|
| `src/frontend/inp.c` | `e454_value_is_off` (shared with savecurrents), `e454_opt_onoff` token scanner, `e454_autobus_var`; the card scan replaces the `strstr` loop and gives deck cards precedence |
| `src/spicelib/parser/inp2n.c` | `autobus_enabled()` — accept the BOOL, NUMBER and STRING spellings, honour the off-words |
| `src/frontend/subckt.c` | `e449_expand_bus_port` returns a count; the expansion is allowed on X lines with the callee's node budget; `inp_set_autobus` just stores the resolved answer |

## Verification

**`examples/autobusopt_examples` — 27/27** under both solvers, and **15/27 on
the previous binary**, where the twelve failures are exactly the defect checks
while every control passes on both.

* all fourteen spellings — bare, `=1`, `=true`, `=yes`, `=on`, `=0`, `=false`,
  `=no`, `=off`, `noautobus`, `myautobus`, `xautobus=1`, `autobusx`, and no
  option at all — mean the same thing on **both** paths
* both precedence orders agree across the two paths
* a bus binds correctly through one, two and three levels of subcircuit, and
  when the inner call is spelled out
* with the option off a short X call is still the old clean error, and does not
  crash

The audit that produced these also confirmed a good deal of the feature is
**correct and was left alone**: ascending *and* descending `.subckt` bus
declarations both match the explicit spelling (Enhancement-411's rule, one level
up), a bus port that is not first, a one-bit bus, array instances
(Enhancement-441), the >1024-bit guard, and the sparse and over-wide formal
lists which warn and error respectively.

Existing bus and option suites all still pass: autobus, subbus, busportsub,
busdir, busoverflow, busname, busnodes, sweepbus, savecur, savecuroff and
optname. Full regression **368/368**, both solvers.
