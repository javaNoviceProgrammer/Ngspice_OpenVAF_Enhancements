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

Run: `python3 verify_internalnode.py` (28 checks per solver, both solvers).

Enhancement-688 (F6 of the 2026-09-21 hunt) adds three checks: a `.nodeset` or `.ic` on an
internal node the model collapsed (`V(a, ai) <+ 0`) is applied to the node it collapsed into,
with a Note naming it (it was refused as "has no internal node"); a `.save` of the name says
which node carries it ("save v(a) instead"); a name that is no internal node keeps the old
refusal.

Enhancement-690 (F8 of the 2026-09-21 hunt) adds seven checks: `sens v(n1#mid)`, `pz … n1#mid …`,
`tf v(n1#mid) vin` and `noise v(n1#mid) …` typed as the *first* analysis of a session were refused
with "no such node" (nothing is set up yet, so the node is not in the parser's table, and the
command rule of E-426 read it as a typo) while the same commands after an `op` ran. A name
whose instance is an OSDI device and whose suffix the module declares is entered as a
parse-time node the device adopts; a suffix it does not declare is refused with nothing left
behind; a built-in device's node keeps the limit and the message says to run an analysis
first. A collapsed internal node named this way is bound to the node it collapsed into (a
synthetic short, as a collapse merge is) or, after a setup, resolved to it with a Note. `sens`
and `pz` refuse a phantom output node as `tf` and `noise` have since E-429 (a mistyped
`.sens` card printed a table of −0.0).

Enhancement-692 adds two checks: E-690's collapsed-twin test fetched every internal node of
every OSDI instance by number at every setup (a walk of the node list each time) -- nine seconds
before a photonic chip's sweep started. The candidate deck nodes are now collected once per
setup and matched by name; 1000 instances of a 40-internal-node module set up in 0.07 s
instead of 1.7 s, and four times the instances cost twice the time, not fourteen times.
