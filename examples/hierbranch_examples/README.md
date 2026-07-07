# hierbranch_examples — hierarchical branch probes (Enhancement-86)

The LRM page-119 forms: probing another instance's branches from outside it.
`hier_probe.va`'s `probes` module reads, from a sibling:

| Probe | Form | Expected |
|---|---|---|
| `V(top.a1.b)` | named branch of instance `a1` | 1.34 V |
| `V(top.d1.branch(va, vb))` | unnamed branch of instance `d1` | 2.5 V |
| `I(top.d1.branch(<p>)) * 1k` | `d1`'s own current into its port `p` | 5 V |

`d1` and `d2` are identical 1k loads in parallel, so the node carries 10 mA —
the port-branch probe pinning 5 V proves the synthesized 0V ammeter reads
**instance** current, not node current. `$root.top…` spellings resolve
identically, and modules holding absolute references (the monitor) are
hierarchy-bound: their standalone copies are omitted from the flattened
output, since only the inlined copies can resolve.

Two pre-existing DAE defects fixed en route (both pinned by check [5] and a
permanent `sim_back` snapshot test): a voltage-source branch feeding an
internal node was mis-classified as a zero-DC small-signal network (its
conduction silently moved to the AC-only residual — an open circuit at DC),
and a probed `V(x,y) <+ 0` branch was node-collapsed away, making its
`I(branch)` read zero.

Run: `python3 verify_hierbranch.py` (6 checks).
