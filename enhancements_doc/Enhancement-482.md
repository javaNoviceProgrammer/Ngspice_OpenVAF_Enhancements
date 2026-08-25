# Enhancement-482 — `.option silentports=ground`

Ground the terminals a netlist leaves out, and give
[Enhancement-481](Enhancement-481.md)'s option a value table.

## Why

Enhancement-481 gave `.option silentports` one job: turn off the absent-terminal
warning Enhancement-402 added, for the case where the netlist is written by a tool
rather than by a person. **That job is unchanged here.** The bare card still means
exactly what E-481 shipped, and `silentports_examples` still scores **24/24**
against this binary.

What E-481 could not do is make the deck *run*.

An omitted OSDI terminal is **not grounded**. `INP2N` binds every terminal the
instance line did not reach to `-1`, and `osdi/osdisetup.c` then builds a private
node `<inst>#<term>` for each one. That is upstream ngspice behaviour — E-402 did
not introduce it, it only made it audible.

Ten of the twelve corpus models that declare an optional pin tie it off with a
**potential** contribution — `Temp(t) <+ 0.0` — and a potential contribution puts
nothing into a node ngspice allocated itself. The private node has nothing driving
it, so the operating point dies on `singular matrix: check node n1#t`. E-402
diagnosed that, accepted it, and gave one answer: **write `0` for the pin**.

A schematic front end cannot write anything, and neither could E-481. On the
reproducer E-402 was decided on, silencing removed five warning lines and left the
six singular-matrix reports exactly where they were. The deck was quiet and still
broken — and quiet is worse, because the warning had been the only clue.

ngspice's own shipped `examples/osdi/bsimbulk/` is the same story: four of its five
decks give BSIM-BULK four nodes for five terminals, and none of those four reaches
an operating point.

## What it adds

`.option silentports=ground` writes the `0`. Every terminal the instance line left
out is bound to ground in the parser, exactly as if the netlist had spelled it out.

| card | warning | terminal |
|---|---|---|
| *(unset)* | 5 lines | dangles on its own node — E-402's default |
| `.option silentports` | none | **still dangles** — E-481, unchanged |
| `.option silentports=dangle` | none | still dangles — the same, spelled out |
| `.option silentports=quiet` | none | still dangles — a synonym for `dangle` |
| `.option silentports=ground` | none | **bound to node 0** |

`1`, `true`, `yes` and `on` mean the bare card. `0`, `false`, `no` and `off` turn
the whole feature off.

### Grounding is asked for by name

It **changes the circuit**, and deliberately. The terminal is connected now, so the
model is told so: `$port_connected()` reports 1 and the branches it would otherwise
skip are built, with the node held at 0.

| | default *and the bare card* | `=ground` |
|---|---|---|
| `$port_connected(t)` | 0 | **1** |
| the `<inst>#t` node | created, floats | **never created** |
| `Temp(t)` in the suite's `gp_rth.va` | 10 K — the device heats its own private node | **0** — held at ground |
| `i(v1)` | −9.09090909091e-04 | **−1.00000000000e-03** |

That is a different circuit from the one the netlist describes. A word the user
typed is the right gate for it; the bare card is not — which is why the bare card
keeps E-481's meaning rather than acquiring this one, and why the option's name
still describes what the option alone does.

## The claim, and how it is checked

`=ground` must be **indistinguishable from a netlist that typed the `0` itself** —
not approximately, value for value at `numdgt=12`. That is check [7].

Check [5] is its counterweight, and it is what keeps E-481's contract intact: the
bare card must be indistinguishable from the warned default *except for the
message* — same terminal current, same `$port_connected`, same `Temp(t)`, and the
private `n1#t` node still present. Check [9] makes the same point where it bites:
on the gated shape the bare card silences the warning and leaves the deck **just as
singular**. Check [14] is the mirror of both — an instance that connects every
terminal is untouched in either state.

Measured on `misc/bsimbulk_thermal_repro`:

| deck | default | bare card | `=ground` |
|---|---|---|---|
| `gnd.cir` — `t` written as `0` | `i(vd) = -6.58515e-07` | unchanged | unchanged |
| `four.cir` — `t` omitted | 5 warnings, 6 × singular, no answer | 0 warnings, **still 6 × singular** | **0 warnings, 0 singular, `i(vd) = -6.58515e-07`** |

The last two cells of the bottom row now agree with the top row. That is the whole
claim in one table: `=ground` is the `0`.

And on ngspice's own BSIM-BULK examples:

| deck | default | `=ground` |
|---|---|---|
| `nmos_pmos_BSIMBULK.sp` | 36 singular, all six sweeps abort | **0 singular, 0 aborts** |
| `bsimbulk_inverter.sp` | 12 singular, 2 aborts | **0 singular, 0 aborts** |
| `bsimbulk_ro.sp` | 12 singular, 2 aborts | **0 singular, 0 aborts** |

## Reading a three-valued option: the string comes first

`silentports_mode()` asks `cp_getvar` for a **CP_STRING before anything else**,
then CP_REAL for `=1`/`=0`, and CP_BOOL last, where it now means only what it is
being asked — the bare card, with no value at all.

That order is load-bearing. Enhancement-467 gave `cp_getvar` a **CP_BOOL
coercion**, so a CP_BOOL query answers TRUE for any value that is not one of the
off-words. For a two-state option that is exactly right, and it is what E-481
relied on. For a three-state one it is fatal: it swallows every value word and
reports them all as a plain "on". Measured with the BOOL query still first,
`silentports=quiet` **grounded the terminal**, and so did `silentports=bananna`.

An unrecognised word is reported and then ignored, leaving the default in place:

```
Warning: unsupported value 'bananna' for option silentports; expected 'dangle' (or 'quiet') or 'ground'. Ignored.
```

Falling back to the **default** rather than to either ON state is the safe
direction — a typo must not be the thing that silently drops a diagnostic or
changes a circuit. This follows ngspice's own handling of a bad enumerated option
value (`.options method=banana` reports *unsupported integration method* and
continues). It is reported once per distinct bad word, because the reader runs per
instance line and a hundred devices should not produce a hundred copies.

## Why the parser and not the compiler

The binding has to happen where the node is chosen. `osdisetup.c` reads the `-1`
sentinel to decide how many terminals were connected, and that number is what it
passes to `setup_instance` as `connected_terminals` — the value the model reads
back through `$port_connected`. Bind the terminal in `INP2N` and every consequence
follows on its own: the count is right, `$port_connected` is right, no private node
is created, and no collapse machinery is involved.

Grounding later — in `osdisetup.c`, after the sentinel has been counted — would
have to undo a decision instead of never making it, and would leave
`$port_connected` disagreeing with the netlist.

`INPpas2` inserts ground into the terminal symbol table with a hard-coded
`char *groundname = "0"` before walking any device card, so `"0"` always resolves
to the existing ground node and never creates one. Checked with the OSDI card
placed **first** in the deck, and from inside a **subcircuit**, where the binding
has to reach the global ground — which is where a schematic front end actually puts
the instance.

## Every terminal, not just the first

The warning counts omitted terminals together ("2 of the 4 terminals ... are not
connected"), so a fix that grounded only one of them would still silence the
message and still leave a floating node behind. `gp_two.va` declares two optional
terminals and check [8] reads the terminal current back to prove the **last** one
was grounded too.

## No openvaf-r change

Entirely ngspice-side. `INP2N` already knows the terminal count from the `.osdi`
descriptor, and `$port_connected` already reports correctly once the terminal is
bound — the compiler needs no knowledge that the parser supplied the node. Two
ngspice files change and no compiler code.

## A premise worth correcting

Grounding is **not** what stock ngspice does, and never was. `git show <E-402
commit>^` shows the pre-E-402 `inp2n.c` binding `-1` for every unsupplied terminal,
and `osdisetup.c`'s private-node loop arrived with the vanilla source import and
has never been modified by this fork. Dangling is upstream; E-402 added the
message; E-481 added the way to turn the message off; E-482 adds the repair.

## Verification

`examples/groundports_examples/verify_groundports.py` — **59/59**. Against the
binary that shipped Enhancement-481 the same suite scores **41/59**; eighteen
checks discriminate, and every one of them is about the terminal's state rather
than about the message.

`examples/silentports_examples/verify_silentports.py` still scores **24/24**
unchanged, which is the machine-checked statement that E-481's contract is intact.

The suite compiles all three model shapes from source, so it exercises the real
compile-and-simulate path rather than a canned `.osdi`. It pins the default (warns,
terminal dangles, `n1#t` present and floating), the bare card (silent, everything
else identical to the default), `=ground` (silent, `$port_connected` 1, no `n1#t`
node, exact equality with a hand-written `0`), both terminals of a two-optional-port
model, the gated shape in all three states, an instance inside a subcircuit, the
whole fourteen-spelling value table, an unrecognised word, the `.spiceinit` route
for both modes, and that too many nodes is still an error.

Full regression **396/396**, both solvers. ngspice-only.
