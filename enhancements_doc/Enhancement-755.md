# Enhancement-755: a compiled instance's negative multiplier draws one warning, from the layer that decides — the parser's built-in sentence ("the device's contribution is sign-inverted") was printed beside the OSDI setter's ("the value is ignored") on one instance line, and only the second was true; the setter's warning now names the instance and says what is done

**Scope:** options-and-convergence hunt F6 and workflows hunt F10, the same
defect seen twice. Four files: `include/ngspice/devdefs.h` gains a device
flag, `osdi/osdiinit.c` sets it on every compiled device, the parser's
multiplier check in `spicelib/parser/inpdpar.c` leaves a flagged device's
negative `m` alone, and the OSDI setter's warning in `osdi/osdiparam.c` names
the instance. The built-ins, `m=0` ([E-751](Enhancement-751.md)), a
non-finite `m` and [E-529](Enhancement-529.md)'s refusal itself are
unchanged.

**Suites:** `inputguard` 107 of 107 (102 of 107 on the E-754 binary: the
five one-warning checks), `guardspell` 54 of 54, `lrmosdi` 10 of 10,
`barevalue` 21 of 21, `instknobs` 126 of 126, `osdiparam` 3 of 3,
`hunt12diag` 26 of 26 and `guardpair` 65 of 65 unchanged; the full sweep
533 of 533.

## What was wrong

`nr1 a 0 nmod m=-1` on a compiled resistor printed, in this order:

```
Warning: nr1: multiplier m=-1 is negative; the device's contribution is sign-inverted (a passive device becomes active) and any noise contribution becomes NaN.
Warning: multiplier m=-1 is negative; the value is ignored (a negative multiplicity sign-inverts the device and makes its noise NaN).
```

and ran the device at `m=1`: 0.5 V across it and 0.5 mA through it, exactly
the unmultiplied answer. The first line described what does not happen.

Two layers each had a reason to speak. [E-426](Enhancement-426.md) put the
first sentence in the parser (`inpdpar.c`), where every instance line's
parameters pass, and it is true of a built-in: ngspice stamps the negative
value, a 2 kΩ resistor with `m=-1` sources current, and the sentence warns
of exactly that. [E-529](Enhancement-529.md) put the second in the OSDI
instance setter (`osdiparam.c`), the one place every route to a compiled
instance's multiplier ends, and made it refuse the value, because the
compiled noise factor is `sqrt(m)` and a negative `m` turned a `.noise` run
into NaN. Both fired on a deck-written `m`, one after the other, and the
parser could not tell a compiled device from a built-in, so it announced the
built-in's behaviour for a device that would not perform it.

## What changed

The device table gets a flag. `DEV_OSDI` in `devdefs.h`, beside
[E-746](Enhancement-746.md)'s `DEV_VARTERMS`, says the device is a compiled
module whose own setter rules on the multiplier, and `osdiinit.c` sets it on
every `IFdevice` it builds. The parser's check keeps its non-finite branch
for every device and, in its negative branch, returns for a flagged device:
the OSDI setter will see the value and speak. That setter's warning now
names the instance, as the parser's did, and says what is done:

```
Warning: n1: multiplier m=-1 is negative; the value is ignored and the instance keeps the multiplier it had (a negative multiplicity would sign-invert the device and make its noise NaN).
```

One line, on every route, and it says the true thing on each: the instance
line, the `_mfactor=` spelling, a subcircuit called with `m=-1` (the
flattened name, `n.x1.n1`), a `.model` card's `_mfactor=-1` default (one
line per instance the card disables the value for), and an `alter` of `m`
at run time, where "the multiplier it had" is whatever the instance was
running with, `m=2` included. A built-in device keeps the parser's sentence
and keeps inverting.

## Verification

Measured on a compiled 1 kΩ resistor across a 1 V source, both binaries:

| route | E-754 binary | now |
|---|---|---|
| `n1 a 0 rmod m=-1` | two warnings, i = 1 mA (m = 1) | one warning naming `n1`, i = 1 mA |
| `_mfactor=-2.5` | two warnings | one warning, `m=-2.5` |
| `x1 a 0 sub m=-1` | two warnings, the parser's naming `n.x1.n1` | one warning naming `n.x1.n1` |
| `.model rmod rm _mfactor=-1`, two instances | two lines, unnamed | one line per instance, each named |
| `alter` of `m` to -1 after `m=2` | one warning (the setter's), i = 2 mA | the same, now naming `n1`, i = 2 mA |
| built-in `r1 a 0 1k m=-1` | one warning, i = -1 mA (inverted) | unchanged |

The `inputguard` suite pins the seven rows: one "is negative" line and its
instance name on each compiled route, the multiplier the instance runs at
afterwards, and the built-in's sentence and inverted current. `lrmosdi`'s
`alter` check and `guardspell`'s built-in check pass unchanged, since both
look for "is negative", which every warning still says.

## What this does not do

A compiled instance still refuses a negative multiplier rather than invert
as a built-in does: E-529's reason stands, the compiled `sqrt(m)` noise
factor. The parser's non-finite check is unchanged for both kinds of
device. A compiled model that declares its own `m` (options hunt F7 and F8)
is a different slot with a different id, untouched here. The built-in
sentence is unchanged.
