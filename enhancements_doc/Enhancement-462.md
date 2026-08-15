# Enhancement-462 — `.option autobus=kicad`

Enhancement-444 lets one node name stand for a whole Verilog-A bus port:

```
.option autobus
N1 a b busdev        ->    N1 a[0] a[1] a[2] a[3] a[4] b busdev
```

The bit names copy the bracket text from the model's own terminal names, which
is the right name everywhere except the one place a bus port is most useful: a
schematic.

## KiCad cannot write `a[0]`

KiCad's SPICE exporter rewrites every `[` and `]` in a net name to `_`. A sheet
labelling a wire `AA[0]` puts `/AA_0_` in the netlist, and the rule keeps
multi-digit indices intact:

| sheet label | KiCad's internal net | what the SPICE netlist says |
|---|---|---|
| `AA[0]` | `/AA[0]` | `/AA_0_` |
| `ZA[10]` | `/ZA[10]` | `/ZA_10_` |

The internal name still has the brackets — the `kicadxml` export shows them — so
the rewrite belongs to the SPICE exporter alone, and nothing on the schematic
side can prevent it.

`/AA_0_` never unifies with autobus's `/AA[0]`, so under KiCad the bits of a bus
port could not be

- **labelled** on the sheet — the label made a *different* node and the bit floated,
- **wired to ordinary parts** — a resistor drawn to `AA[0]` landed on `/AA_0_`,
- **plotted**, because the simulator's signal list is built from schematic nets:
  it offered `/AA`, which after expansion has no device on it at all, and
  answered `vector V(/AA) not or not yet available`.

The only workable sheet was one where every net was a whole bus, joining one bus
device straight to another.

## What the option does

`.option autobus=kicad` changes the generated **spelling** and nothing else:

```
N1 /AA /BB bp     ->     N1 /AA_0_ /AA_1_ /AA_2_ /AA_3_ /BB_0_ ... /BB_3_
```

The indices still come from the model's own terminal names, so a port declared
`[4:1]` still expands 1..4 and never invents an `a_0_`. Only the punctuation
changes, at the one point where the token and the index are concatenated.

With it, the bits *are* ordinary schematic nets: they can be labelled, wired to
resistors, and picked from the signal list — where KiCad displays them under
their internal names, `/AA[0]`.

## One reader, not two

The expansion has always had two possible homes, and only one of them
synthesises a name. `inp2n.c` builds `token + index` from the model's terminal
table — that is the one this changes. The subcircuit path
(`e449_expand_bus_port`, Enhancement-449) maps a bus base onto the **formals the
`.subckt` line already declares**, so it has no name to spell and no choice to
make. The suite pins that a subcircuit gives bit-identical answers in both
modes, rather than leaving that to reasoning: two readers disagreeing about one
option is exactly what Enhancement-454 had to repair here.

## A style that does not exist is reported

`.option autobus=kicad2` enables the feature in the *default* spelling, so a
deck written for KiCad keeps solving — the bus binds to fresh `a[k]` nodes and
every `a_k_` is left dangling at the source voltage. The only symptom is a
number that looks plausible, which is the silent-degenerate shape Enhancements
447, 451 and 455 each had to go back and fix. Unknown styles are therefore
reported:

```
Warning: unknown autobus style 'kicad2'; expected 'kicad'. Using the default a[k] spelling.
```

once per distinct spelling, so a large deck does not repeat it per device line.
The on-words (`true`, `yes`, `on`) are not styles and are not warned about; the
off-words are handled before this is ever reached, by `e454_value_is_off`.

## Verification

`examples/autobuskicad_examples/verify_autobuskicad.py` — **27/27**, both
solvers. Every check that matters is a differential: the same circuit in the two
spellings must give bit-identical values on a ladder where all five bits differ,
and **each spelling must produce only its own node names** — an expansion
emitting both, or neither, would otherwise pass a value check on whichever nodes
happened to exist. Also pinned: multi-digit indices (`a[10]` → `a_10_`), a
`[4:1]` declaration, two bus ports with ordinary parts wired straight to the
bits, all five off-spellings still off, the unknown-style warning and its
fallback, a fully spelled-out line unaffected, and the subcircuit equivalence
above.

A note found while writing it: asked for an absent `a[0]`, ngspice reports
`vector a is not available` — with no such *node* it falls back to reading the
brackets as an index into a vector `a`. Absence has to be checked by the absence
of a value, not by the text of the message.

Full regression **376/376**, both solvers. This is an ngspice-only change; no
compiler change, so no corpus differential applies.

## Measured end to end through KiCad

`version12/KiCad/example3` is a two-pin symbol for an eight-terminal device
(`inout [0:3] a; inout [0:3] b;`), driven by ordinary resistors wired to the
individual bits. `kicad-cli sch export netlist --format spice` produces

```
Rs0 /drv /AA_0_ 1k
...
N1 /AA /BB bp
```

which runs to the hand-computed values on all eight bits, through the ngspice
executable and through `libngspice` — the library KiCad's own simulator loads.
ERC is clean.

Two things that sheet has to do, neither of them about this option: the
`.option` line rides in `models.lib` because KiCad's exporter drops schematic
text, and the `.osdi` load lives in `.spiceinit` because an `.include` is
expanded after the `pre_` pre-pass. A third: KiCad's per-pin **current probes**
(`.probe alli` / `.probe allp`) must be off, since a single series 0 V source
cannot measure the four independent currents a bus pin carries.
