# Enhancement-482 — `.option silentports=ground`

```
python3 verify_groundports.py
```

59 checks. **41/59** against the binary that shipped Enhancement-481.

## What it adds

Enhancement-481 gave `.option silentports` one job: turn off the absent-terminal
warning. That job is unchanged — `silentports_examples` still scores **24/24**
against this binary. What E-481 could not do is make the deck *run*.

An omitted OSDI terminal is not grounded. `inp2n.c` binds every terminal the line
did not reach to `-1`, and `osdi/osdisetup.c` builds a private node
`<inst>#<term>` for each one — upstream behaviour that E-402 only started saying
out loud. Ten of the twelve corpus models with an optional pin tie it off with a
**potential** contribution (`Temp(t) <+ 0.0`), which puts nothing into a node
ngspice allocated itself, so the operating point dies on `singular matrix`.
E-402's answer was always *write `0` for the pin*, and a schematic front end that
hides the pin cannot write anything.

`.option silentports=ground` writes it.

## Three states

| card | warning | terminal |
|---|---|---|
| *(unset)* | 5 lines | dangles — E-402's default |
| `silentports` / `=dangle` / `=quiet` | none | **still dangles** — E-481, unchanged |
| `silentports=ground` | none | **bound to node 0** |

`1`/`true`/`yes`/`on` mean the bare card; `0`/`false`/`no`/`off` turn the feature
off; `dangle` and `quiet` are synonyms.

Grounding is asked for **by name** because it changes the circuit: the model reads
`$port_connected() == 1` and builds branches it would otherwise skip, with the
node held at 0. A word the user typed is the right gate for that; the bare card is
not.

| | default *and the bare card* | `=ground` |
|---|---|---|
| `$port_connected(t)` | 0 | **1** |
| `<inst>#t` node | created, floats | **never created** |
| `Temp(t)` in `gp_rth.va` | 10 K — the device heats its own private node | **0** — held at ground |
| `i(v1)` | −9.09090909091e-04 | **−1.00000000000e-03** |

## The two checks that carry the claim

- **[7]** `=ground` must be **indistinguishable from a netlist that typed the `0`
  itself**, value for value at `numdgt=12`.
- **[5]** its counterweight: the bare card must be indistinguishable from the
  warned default *except for the message* — which is what keeps E-481's contract
  intact. **[9]** makes the same point where it bites: on the gated shape the bare
  card silences the warning and leaves the deck **just as singular**.

**[14]** is the mirror of both: an instance that connects every terminal is
untouched in either state.

## Measured on the reproducer E-402 was decided on

`misc/bsimbulk_thermal_repro`, real BSIM-BULK:

| deck | default | bare card | `=ground` |
|---|---|---|---|
| `gnd.cir` — `t` written as `0` | `i(vd) = -6.58515e-07` | unchanged | unchanged |
| `four.cir` — `t` omitted | 5 warnings, 6 × singular, no answer | 0 warnings, **still 6 × singular** | **0 warnings, 0 singular, `i(vd) = -6.58515e-07`** |

And on ngspice's own shipped `examples/osdi/bsimbulk/`, whose decks give
BSIM-BULK four nodes for five terminals:

| deck | default | `=ground` |
|---|---|---|
| `nmos_pmos_BSIMBULK.sp` | 36 singular, all 6 sweeps abort | **0 singular, 0 aborts** |
| `bsimbulk_inverter.sp` | 12 singular, 2 aborts | **0 singular, 0 aborts** |
| `bsimbulk_ro.sp` | 12 singular, 2 aborts | **0 singular, 0 aborts** |

## The read order is load-bearing

`silentports_mode()` asks `cp_getvar` for the **CP_STRING first**, then CP_REAL
for `=1`/`=0`, and CP_BOOL last — where it now means only what it is being asked,
the bare card with no value.

Enhancement-467 gave `cp_getvar` a **CP_BOOL coercion**: it answers TRUE for any
value that is not an off-word. Exactly right for a two-state option, and it is
what E-481 relied on. Fatal for a three-state one — it swallows every value word.
Measured with the BOOL query still first, `silentports=quiet` **grounded the
terminal**, and so did `silentports=bananna`.

An unrecognised word is named once per distinct spelling and falls back to the
**default**, not to either ON state:

```
Warning: unsupported value 'bananna' for option silentports; expected 'dangle' (or 'quiet') or 'ground'. Ignored.
```

A typo must not be what silently drops a diagnostic or changes a circuit. This
follows ngspice's own handling of a bad enumerated value (`.options method=banana`
reports *unsupported integration method* and continues).

## Why the parser and not the compiler

`osdisetup.c` reads the `-1` sentinel to decide how many terminals were connected
and passes that count to `setup_instance` — the value the model reads back through
`$port_connected`. Bind the terminal in `INP2N` and everything follows on its own:
the count is right, `$port_connected` reports 1, no private node is created, and
no collapse machinery is involved. Grounding later would have to undo a decision
instead of never making it.

`INPpas2` inserts ground into the terminal symbol table before walking any device
card, so `"0"` always resolves to the existing ground node and never creates one —
checked with the OSDI card placed **first** in the deck, and from inside a
**subcircuit**, where the binding has to reach the global ground and where a front
end actually puts the instance.

## Every terminal, not just the first

The warning counts omitted terminals together ("2 of the 4 terminals ... are not
connected"), so a fix that grounded only one would still silence the message and
still leave a floating node. `gp_two.va` declares two optional terminals and check
[8] reads the terminal current back to prove the **last** one was grounded too.

## No openvaf-r change

Entirely ngspice-side. `INP2N` already knows the terminal count from the `.osdi`
descriptor, and `$port_connected` reports correctly once the terminal is bound.
