# Enhancement-492 — a node named only in a control position

```
python3 verify_ctrlnode.py
```

37 checks, a few seconds. **19/37** against the pre-fix binary — **18**
checks discriminate.

## What it is

`E`, `G` and `S` take a controlling node **pair**, and those two names were bound
exactly the way the output pair is — `INPtermInsert`, which **creates** the node.
So a typo simply invented a node and the run continued against it.

## The one that answers anyway

For `E` and `G` the invented node has no path to ground, the matrix goes singular,
and the run fails — with the wrong explanation (*"check node nosuch"*, a node the
user never wrote). **A switch does not fail.** It only *reads* its control voltage
to decide open or closed and stamps nothing for it, so the matrix stays
non-singular and the solve succeeds:

| | v(b) | state |
|---|---|---|
| `S1 a b ctl 0 sw` | 0.999001 | CLOSED |
| `S1 a b nosuch 0 sw` | **9.99999e-07** | **OPEN** |

`rc=0`, no diagnostic. A factor of a million from one mistyped character.

**A phantom reference is dangerous exactly where it is read but not stamped.**

## Everything else already checked

* `.ic` / `.nodeset` → *"IC on non-existent node - nosuch, ignored"*
* `F`, `H`, `W`, B-source `i()` → *"unknown controlling source vnope"*
* all thirteen output constructs name a missing vector
* `warn_physics` validates the switch's own `ron`, `roff`, `vh`

Only the controlling-node pair skipped it.

## The controls

Half the suite pins what must **not** move, because the fix sits in the node
table every device shares:

* a control node that **is** connected — including the source's **own output**
  (`E1 out 0 out 0 2`), one defined **later** in the deck, **ground**, and one
  passed through a **subcircuit port**.
* `F`, `H` and `W`, which already named their missing controlling source.
* `.ic` on a non-existent node — [E-429](../../enhancements_doc/Enhancement-429.md)'s
  own path, whose `devRef` mechanism this reuses.
* a real Verilog-A `$fatal`, still named as such and still pointing at its
  `OSDI(fatal)` line.
* both solvers on an ordinary divider, and a mixed-signal KLU run, which must get
  no empty-matrix note.

## The model

`ctrlnode.va` holds one module, `vfatal`, which raises `$fatal` above a trip
voltage. It is the control for the other half of the round: CKTop's abort message
names Verilog-A, and it used to name Verilog-A for **any** `E_PANIC` that reached
it — including decks containing no Verilog-A device at all. When a `$fatal` really
is raised, the message must still say so.
