# Enhancement-757: a child instance's unnamed branch is the child's own — the flattening spelled a child's `(p, n)` with the parent's net names, so it became the parent's branch: a leaf's ideal source was dropped under a parent conductance (1.333 V for 1.0 V), a parent's `I(p,n)` probe read the child's current too, two sibling leaves answered by the order they were written, and two ideal sources summed to 3 V; and a named branch over a `ground` net floated

**Scope:** hierarchy hunt F1 (2026-09-08), with the named-branch-over-ground
gap found on the way. Compiler only: `hir/src/elaborate.rs` (the rewrite, the
cross-instance flow probe, the pre-scan, the ground-aware declaration) and
`hir/src/lib.rs` (a named branch's `ground` low endpoint is ground). ngspice
is unchanged.

**Suites:** `hierub` (new) 16 of 16 per solver (5 of 16 on the E-756
compiler); `hierbranch`, `lrmcontrib`, `lrmhier`, `lrmvoice`, `paramsetlrm`,
`hiernode`, `hierdev`, `hiername`, `instdep`, `genhier`, `arrayinst`,
`elabguard` and `binstale` unchanged; `cargo test -p hir` 16 of 16; the full
sweep 534 of 534 (the new suite included).

## What was wrong

LRM 5.5 makes the unnamed branch `(a, b)` a per-module object: every
`I(a,b)`/`V(a,b)` inside one module names the same branch, but a child
instance wired to the same two nets owns its own. openvaf-r flattens
hierarchy by rewriting the child's text into the parent, and the child's
`(p, n)` was spelled with the parent's net names after the rewrite, so the
branch-identity pass saw one branch. The hunt's decks, measured on the
E-756 compiler:

| shape | was | LRM |
|---|---|---|
| leaf `V(p,n) <+ 1.0` under a parent `I(p,n) <+ V/2k`, 2 V through 1 kΩ | 1.333 V, L022, the source dropped | 1.0 V |
| parent `iop = I(p,n)` beside a child conductance, 1 V applied | 3 mA, the child's included | the parent's own 1 mA |
| parent probe-only `I(p,n)`, child conductance | 0.667 V, no short | a short: 0 V |
| source leaf beside resistor leaf | 0.667 V or 1.0 V by the order written | 1.0 V |
| source leaf beside capacitor leaf | 2.0 V at the operating point, 0.157 at 1 MHz, one order | 1.0 V and 0 |
| conditional parent flow under a child source | 1.333 V, silent | 1.0 V |
| child `V(p,n) <+ 1.0` under a parent `V(p,n) <+ 2.0` | 3.0 V, the two summed | two sources in parallel: no answer |
| a `#(.$mfactor(2))` child's per-copy `I(n,p)` probe | -1.5 mA | -1 mA |
| `I(top.d1.branch(p, m))` from outside, `p` a port | a compile error | the child's own 0.5 mA |

Named branches kept their mangled names and so their identity, which is why
they were safe; a `V(p,n)` under a parent that contributed nothing to the
pair was right by luck. Idiomatic leaf modules (an ideal source, a switch, a
capacitor) under a parent that adds its own conductance or reads `I(p,n)`
were exactly the affected shape.

## What changed

**Every access of a child's body over its own nets that names a branch gets
a per-instance named branch.** A contribution target, or a flow probe,
`I(a,b)`/`V(a,b)`/`I(a)` over the child's nets is rewritten onto
`<prefix>ub__<a>__<b>` (`<prefix>ub__<a>` for the ground branch), declared
once over the final flattened nets; a potential probe reads the nodes and is
left alone. The nets are taken in sorted order, so an access in the reverse
order negates: a probe becomes `(-I(name))`, a direct contribution
`V(name) <+ -(rhs)`, with the `#(.$mfactor(n))` factor folded in for a flow
and the target handed to the multiplier transform as already done; an
indirect target needs no sign. Named branches, port-branch probes,
hierarchical arguments (E-526's own transform) and bus-bit arguments are
untouched. The elaborated text for the first row reads:

```
branch (p, n) l1__ub__n__p; // Enhancement-757: the instance's own unnamed branch
analog V(l1__ub__n__p) <+ -(1.0);
analog I(p,n) <+ V(p,n)/2k;
```

**A flow probe of a child's unnamed branch from outside reads that branch.**
E-86's `I(<chain>.branch(a, b))` used to expand to the flattened net pair,
which was the child's branch only because of the merge; it now names the
per-instance branch, negated for the reverse order, and a pre-scan of every
module's text lets the child declare a pair it never accesses itself. A
port net works too (it was "not found" before). `V(<chain>.branch(a, b))`
keeps reading the nets.

**A named branch's `ground` low endpoint is ground.** `branch (a, gnd) b;`
over a `ground`-declared net kept `gnd` as a node of its own that nothing
else touched, so ngspice reported it floating and the matrix singular, while
the unnamed `I(a, gnd)` had always been folded onto ground; the HIR now
folds the declaration the same way. The elaborator never puts a ground net
first in a synthesized declaration: such a pair is declared the other way
round and every access of it negated, the cross-instance probe included.

## What this does not do

A user-written `branch (gnd, a)` — ground as the HIGH endpoint — is left as
written and still floats; only `(a, gnd)` and `(a)` are branches to ground.
A child access with a bus-bit argument (`I(a[1], b)`) stays on the flattened
pair. Two ideal sources in parallel across the boundary are now what they
are, a singular system, rather than a sum. The multiplier transform's known
gap for E-526's aliased probes is unchanged.
