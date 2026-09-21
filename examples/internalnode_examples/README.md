# internalnode_examples — Enhancement-608

A device builds its internal nodes (`n1#mid`, `d1#internal`) at setup, after the
deck is parsed. A `.tf`/`.pz` card naming one had the deck reader make a node of
that name ahead of the device, and the device then built a second node beside it
(the deck's floated, the `.tf` was refused, `.print op v(n1#mid)` printed 0); a
`.ic`/`.nodeset` on the name was refused outright; and an interactive `tf
v(n1#mid) v1` after an `op` bound to the live node, which the run's own
unsetup/setup freed and rebuilt — the job read freed memory (a transfer function
of −5e-4 for a 0.75 divider). The device now adopts the parse-time node, a
retired device-local node is revived as the same struct at the next setup, and a
`.ic`/`.nodeset` on `<instance>#<node>` is placed by `CKTsetup` once the node
exists.

Enhancement-681 (N1 of the 2026-09-21 hunt) adds five checks: the adoption above also
took in a *device line* that named `n1#mid` — the netlist's node and the model's
internal node became one node in silence (a source wired to `n1#mid` drove the
model's internal node; a BJT's `q1#base` drawn to 3 V put 1e35 A through the
source). `CKTmkSignal` now says so once, naming the node, the internal node and the
instance (or the source, for a `v1#branch` name); the connection itself is kept, and
E-608's own cards stay silent.

Run: `python3 verify_internalnode.py` (19 checks per solver, both solvers).

Enhancement-688 (F6 of the 2026-09-21 hunt) adds three checks: a `.nodeset` or `.ic` on an
internal node the model collapsed (`V(a, ai) <+ 0`) is applied to the node it collapsed into,
with a Note naming it (it was refused as "has no internal node"); a `.save` of the name says
which node carries it ("save v(a) instead"); a name that is no internal node keeps the old
refusal.
