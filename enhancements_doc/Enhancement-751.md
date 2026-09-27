# Enhancement-751: `m=0` on a compiled instance is announced — the instance stays disabled, as E-426's idiom says, and a Note names it on every route that reaches the compiled layer (the instance line, `_mfactor=`, a subcircuit called with `m=`, a card's `_mfactor=` default, `alter` at run time), ten lines at most and one more saying the rest are not listed; the built-ins keep their silence

**Scope:** F5 of the
[options-and-convergence hunt](../docs/bug_hunts/2026-09-26_ngspice-osdi-options-and-convergence.md).
One file changes behaviour, `osdi/osdiparam.c` (the compiled layer's instance
setter, where every spelling of the multiplier ends); `parser/inpdpar.c` gets
a comment beside its unchanged m=0 silence. A message only: nothing binds,
parses or solves differently, and `m=0` still disables the instance.

**Suites:** `inputguard` 100 of 100 (94 of 100 on the E-750 binary: the six
route checks added here), `barevalue` 21 of 21 per solver (20 of 21 on the
E-750 binary), `guardspell` 54 of 54 per solver and `instknobs` 126 of 126
unchanged; the full sweep 532 of 532.

## What was wrong

```
V1 in 0 dc 1
R1 in a 1k
nr1 a 0 nmod m=0
.model nmod nres(r=1k)
```

`v(a)` is 1.0 V and `@nr1[i]` is 0: the resistor is gone from the circuit,
and nothing says so. `_mfactor=0` does the same, so does `m=0` on the `X`
line of a subcircuit holding the instance, so does `_mfactor=0` on the
`.model` card as the instances' default, and so does `alter @nr1[m] = 0`
between two analyses. A negative multiplier has been reported since E-447
(parser layer) and E-529 (compiled layer, every route); zero, the one value
that removes the device outright, was the value both checks let through.

That was a decision, not an oversight. E-426 established `m=0` as the
"disable this instance" idiom, exactly as for the built-ins, E-447 considered
warning on it and deliberately did not, and three suites asserted the
silence. The decision was right about the *behaviour* — a deck that writes
`m=0` usually means it — and wrong about the *silence*: a multiplier that a
parameter expression evaluated to zero, or a subcircuit called with `m=0`
by a generator's mistake, looked exactly like one written on purpose, and
the only trace was a node voltage that had risen to the source.

## What changed

The compiled layer's setter, `OSDIparam`, prints one Note per instance when
its `$mfactor` slot is set to zero, and then applies the value as before:

```
Note: nr1: m=0 disables the instance -- it stays in the netlist and contributes nothing (a positive m re-enables it).
```

Every route ends in that setter, so every route is covered by the one line:

| route | what is printed |
|---|---|
| `nr1 a 0 nmod m=0` | the Note, naming `nr1` |
| `nr1 a 0 nmod _mfactor=0` | the same |
| `X1 a 0 sub m=0` with `nr1` inside `sub` | the Note, naming `n.x1.nr1` (the flattened instance) |
| `.model nmod nres(r=1k _mfactor=0)` with two instances | one Note per instance |
| `alter @nr1[m] = 0` at run time | the Note at the `alter`; `alter @nr1[m] = 2` afterwards re-enables the device in silence |
| any positive `m` | nothing |
| a built-in `R2 a 0 1k m=0` | nothing (E-426's silence, the parser-layer check is unchanged) |

It is a Note and not a Warning, because the deck is not wrong; it is on
stderr beside the multiplier warnings of the same function, so a harness that
reads both channels sees it and one that filters Warnings does not lose it.
Twelve instances given `m=0` print ten Notes and then

```
Note: further instances disabled by m=0 are not listed.
```

so a generator that disables a thousand devices gets eleven lines. The
counter is per process, as the E-543 message caps are.

The three suites that asserted the silence now assert the Note: `inputguard`
[6] gains the routes above, `barevalue` [8] adds "announced by E-751's Note"
to its "no Warning", and `guardspell`'s check stays as it was, because it
tests a built-in resistor.

## Verification

`examples/inputguard_examples/verify_inputguard.py`, section [6], nine
checks where one was: the line, `_mfactor=0`, the subcircuit route (the Note
names `x1.n1` through whatever prefix the flattening adds), the `alter`
route with its currents at -0.5 mA, 0 and -1 mA around the disable and the
re-enable, the card default naming both instances, twelve instances giving
ten Notes and the "not listed" line, `m=0.5` silent, and a built-in resistor
at `m=0` silent. On the E-750 binary the six route checks fail with no Note
in the output and the three silences pass.

## What this does not do

- It does not refuse `m=0`, and it does not change what the instance
  contributes: E-426's idiom stands, and `instknobs`' `device m=0` check
  reads 0 A as before.
- The built-in devices keep E-426's silence, including BSIM4's own fatal on
  `m=0` and the resistor's and diode's silence. Announcing those is a
  parser-layer decision the hunt did not ask for.
- F6 of the same hunt, the two contradicting warnings for a negative `m`
  (parser layer and compiled layer, in that order), is untouched; it sits
  eleven lines above this change in `osdiparam.c` and in `inpdpar.c`.
- The cap is a fixed ten lines with no option, and the counter does not
  reset on `source`; a second deck in one session that disables more
  instances starts from where the first left off.
