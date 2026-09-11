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

Run: `python3 verify_internalnode.py` (11 checks per solver, both solvers).
