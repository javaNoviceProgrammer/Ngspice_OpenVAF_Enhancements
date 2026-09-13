# Enhancement-627: the other spelling of the bits a bus port expands to is named

**Scope:** `src/spicelib/parser/inp2n.c` — the bus bases Enhancement-572 remembers at
expansion now carry every bit in both spellings (`autobus_note_base` takes the port's
terminal names), and the pass-3 report (`INPreportBusBases`) also says when the deck
wires the *other* spelling of those very bits — `in[0]` where the bits became `in_0_`
under `.option autobus=kicad`, or `in_0_` (a KiCad export) where they became `in[0]`
under the default spelling. `examples/autobuskicad_examples/` grows 27 → 31 checks per
solver. **ngspice only.** F15 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`autobuskicad_examples`](../examples/autobuskicad_examples/) 31 of 31 per
solver, both solvers; `autobus`, `autobusopt`, `autoopts`, `busmixed`, `busname` green;
full sweep 505 of 505.

## What was wrong

```spice
.option autobus=kicad
.model kb kbus r=1k              ; inout [0:4] a
V1 in[0] 0 1
V2 in[1] 0 2
V3 in[2] 0 3
V4 in[3] 0 4
V5 in[4] 0 5
Rb b 0 1
N1 in b kb
.control
pre_osdi kbus.osdi
op
print v(in_0_) v(in_4_) v(in[0])   ; 0  0  1
.endc
```

Under the KiCad spelling `in` expands to `in_0_ .. in_4_`; the sources sit on
`in[0] .. in[4]`. Two nodes per bit, nothing in common: the device's bits floated and the
output was 0 V, with nothing said — not even a warning here (the hunt's variant drew the
gmin notes of E-569, which name the symptom). Enhancement-572 names a bus *base* the deck
also uses as a plain node (`Rx in 0 1k`); the other spelling of the bits themselves was
never checked. The mirror image is the commoner accident: a KiCad-exported deck whose
nets are `/in_0_` run without `autobus=kicad`, so the bits become `/in[0]` and every net
of the sheet misses them.

## What changed

- **Each expanded base remembers its bits in both spellings** — the one it used and the
  one it did not — for every bit of the port (the indices are the model's, so a `[4:1]`
  port compares `in_1_ .. in_4_` against `in[1] .. in[4]`).
- **Pass 3 names the other spelling the deck wires.** With every node known, each base is
  checked once against the other spelling of each of its bits, and the ones that exist as
  nodes are listed — under `autobus=kicad`:

  ```
  Warning: instance n1: 'in' was expanded to the 5 bus bits in_0_ .. in_4_ (the KiCad
           spelling, .option autobus=kicad), but the deck also wires in[0], in[1], in[2], in[3], in[4] -- the
           bracket spelling of the same bits, a different node from each, so the bits float.
           Write them as in_0_ .. in_4_, or set `.option autobus` without `=kicad` to expand to in[0] ..
  ```
  and under the default spelling, for `in_0_`, `in_2_` wired beside `N1 in b kb`:
  ```
  Warning: instance n1: 'in' was expanded to the 5 bus bits in[0] .. in[4], but the deck
           also wires in_0_, in_2_ -- KiCad's spelling of the same bits, a different node from
           each, so the bits float. Set `.option autobus=kicad` to expand to in_0_ .. in_4_
           (what a KiCad export needs), or write them as in[0] ..
  ```
  Singular wording for one node. Only the exact other-spelling names of the expanded bits
  are looked for, so an ordinary node that happens to end in `_1_` beside an unrelated bus
  is not mistaken for one — the same care E-490 took when it made the underscore spelling
  count only under the option.
- Nothing binds differently: the two spellings stay two nodes, as E-462 established; the
  deck is told which cure it wants. Consistent decks of either spelling draw no warning.

## Verification

| check | result |
|---|---|
| `V1 a[0] 0 1 … V5 a[4] 0 5`, `N1 a b kb`, `autobus=kicad` | the warning names all five, the cures; `a_0_`, `a_4_` read 0, `a[0]` reads 1 |
| `V1 a_0_ 0 1`, `V3 a_2_ 0 3` beside `N1 a b kb`, default spelling | the warning names the two, offers `autobus=kicad` |
| one node of the other spelling | singular wording |
| the reference ladders of both spellings | no such warning |
| the 27 existing checks; `autobus`, `autobusopt`, `autoopts` (the one-bit path), `busmixed`, `busname` | unchanged |
| `autobuskicad_examples` | 31 / 31, both solvers |
| full sweep | 505 of 505 |
