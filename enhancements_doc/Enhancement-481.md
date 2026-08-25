# Enhancement-481 — `.option silentports`

An opt-in way to turn off the absent-terminal warning Enhancement-402 added, for
the case where the netlist is written by a tool rather than by a person.

## Why

E-402 made an omitted OSDI terminal audible, and that stays the **default**. The
reasoning holds: an omitted terminal looks exactly like a typo, and it
**dangles** rather than grounding, so the natural assumption is the wrong one and
the deck simulates a different circuit in silence.

What E-402 did not account for is a netlist nobody typed. A schematic front end
emits the short form for every instance of a model that declares an optional
thermal port, and the schematic author has no way to add the pin — so a
five-device sheet collects twenty-five lines of warning about a choice they did
not make and cannot change. KiCad's SPICE exporter is the case that prompted
this.

```
Warning: instance n1: 1 of the 5 terminals of model type 'bsimbulk' are not connected.
         terminal 5 ('t') is absent
         The model sees $port_connected() = 0 for these, and any branch
         to them carries no current. They are NOT grounded -- connect
         them to 0 explicitly if that is what you meant.
         Line: n1 d g 0 0 nm
```

## What it does

`.option silentports` suppresses that warning. Nothing else changes: the
terminal is still absent, `$port_connected()` still reports 0, the branch still
carries no current, and the circuit solved is the same one.

It is **opt-in**. A deck that does not ask keeps the warning, so the default
behaviour of every existing deck is untouched.

A front end that generates netlists but cannot edit them can ship
`set silentports` in `.spiceinit` instead of adding a card to every file.

## What it deliberately does NOT do

**It silences a warning. It does not make an ill-posed circuit well posed.**

Measured on `misc/bsimbulk_thermal_repro`, the reproducer E-402 was decided on:

| deck | default | with `.option silentports` |
|---|---|---|
| `gnd.cir` — `t` written as `0` | clean, `i(vd) = -6.58515e-07` | unchanged |
| `four.cir` — `t` omitted | 5 warning lines **+ 6 × `singular matrix: check node n1#t`** | 0 warning lines, **still 6 × singular matrix** |

BSIM-BULK pins its thermal node with a *potential* tie-off, so with the terminal
absent the node carries no current and the operating point fails. That is
E-402's decided territory and the answer is unchanged: **write `0` for the
pin**. Ten of the twelve corpus `$port_connected` models are built this way.

So the option helps a front end whose models stay well posed with the port
absent, and for the rest it removes five lines while leaving the six that
actually matter. Checks [7]–[9] pin that distinction so a later reader does not
take `silentports` for a fix.

Both shapes are compiled in the suite: `sp_rth.va` contributes its thermal
network unconditionally (well posed, silencing gives a completely clean run) and
`sp_gated.va` gates it on `$port_connected` (node floats, singular matrix
unaffected).

## No openvaf-r change

The warning is raised entirely inside ngspice, in `INP2N`, from
`numnodes < *dev->terms` against the terminal count already carried in the
`.osdi` descriptor. Compiling a model with an unused optional port, openvaf-r
prints nothing at all — it declares the ports, and `$port_connected` already
reports correctly. Two ngspice files change and no compiler code.

## Registered in both places

`if_is_option()` keeps a list of names that are options, and a type dispatch
beside it decides what each one does. A name known to only one of the two either
gets honoured while being reported as "unknown option ... ignored"
(Enhancement-451) or draws a warning about a setting the run then honours
(Enhancement-445's note). Both teach the reader to ignore the check, so
`silentports` is registered in both.

The first build had exactly this fault — the option worked and `.options
silentports` still printed "unknown option" — which is how the second
registration point was found.

## Every off-spelling is tested

`cp_getvar(.., CP_BOOL, ..)` reports a variable that is merely **present** as
true, so `silentports=0`, `=false`, `=no` and `=off` would each have turned the
feature **on**. Enhancements 450, 451, 454, 466 and 467 each shipped that defect
exactly once, so the reader is `autobus_enabled()`'s, which tests the value and
not just the presence. Check [5] walks all nine spellings.

## Verification

`examples/silentports_examples/verify_silentports.py` — **24/24**. Against the
shipped pre-fix binary the same suite scores **11/24**: 13 checks discriminate.

The suite compiles both model shapes from source, so it tests the real
compile-and-simulate path rather than a canned `.osdi`, and it pins the default
(still warns), the option (silences), all nine spellings, the `.spiceinit`
route, the singular-matrix case that is deliberately unchanged, and that too
many nodes is still an error.

Full regression, both solvers. ngspice-only.
