# hierub_examples — Enhancement-757

A child instance's **unnamed branch is the child's own**. LRM 5.5 makes the
unnamed branch `(a, b)` a per-module object: every `I(a,b)`/`V(a,b)` inside one
module names the same branch, but a child instance wired to the same two nets
owns its own. openvaf-r flattens hierarchy by rewriting the child's text into the
parent, and the child's `(p, n)` used to be spelled with the parent's net names,
so it *became* the parent's branch (2026-09-08 hierarchy hunt F1).

```
python3 verify_hierub.py
```

16 checks per solver. Eleven fail on the E-756 compiler: the dropped source
(1.333 V), the parent probe reading the child's current, the shorted
probe-only branch, the sibling order dependence, the source-beside-capacitor
pair, the conditional parent, the summed sources (3 V), the multiplied child's
per-copy probe, the cross-instance flow probe (a compile error), and a named branch over a `ground` net (it floated).

| model | shape | answer |
|---|---|---|
| `hb3` | child `V(p,n) <+ 1.0`, parent `I(p,n) <+ V/2k` | 1.0 V, no L022 |
| `hb` | parent `iop = I(p,n)` beside a child conductance | the parent's own 1 mA |
| `hb7` | parent probe-only `I(p,n)`, child conductance | a short: 0 V, L023 |
| `hb11`/`hb12` | source leaf beside resistor leaf, both orders | 1.0 V |
| `sib`/`sib2` | source leaf beside capacitor leaf | 1.0 V, 0 at 1 MHz |
| `hb8` | conditional parent flow under a child source | 1.0 V |
| `hb10` | two ideal sources in parallel | reported singular |
| `hb9` | child on the parent's internal node | 1.5 V |
| `hb5` | a NAMED child branch (control) | 1.0 V |
| `swh` | switch-branch child under a leakage | 0 V / 1.998 V |
| `rev` | reverse-order probe and contributions | negated, one branch |
| `mf` | `#(.$mfactor(2))` child, reverse-order contribution | 2 mA + 1 mA, per-copy probe -1 mA |
| `gnd` | the ground branch `(p)` | 1.0 V |
| `e86` | `I(top.d1.branch(p, m))` from outside | the child's own 0.5 mA |
| `gb` | a named `branch (a, gnd)` over a `ground` net | 1 mA, as the unnamed `I(gnd, a)` |
