# Enhancement-836: an OSDI instance's internal rows carry the name, the kind and the nodeset of the node they stand for — after a node collapse they were another node's

**Scope:** F1 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md),
with [Enhancement-837](Enhancement-837.md) and [Enhancement-838](Enhancement-838.md).

ngspice: `osdi/osdisetup.c` (the loop in `OSDIsetup` that creates an instance's internal rows).
`examples/osdirows_examples/` (new, section [1]). **ngspice only.**

**Suites:**
- [`osdirows_examples`](../examples/osdirows_examples/): 20 of 20 per solver. 4 of the 5 checks in
  [1] fail on the E-835 binaries; the other is a control.
- The full sweep: 548 of 548.

## What was wrong

`collapse_nodes` merges the nodes a model shorts (`V(p, a1) <+ 0` when `r1 = 0`) and numbers
what is left from 0, so an instance's rows are a compacted list. The loop that then creates
each internal row read the name, the kind (voltage node or branch current) and the nodeset
initializer from `descr->nodes[i]`, where `i` is the row's index after compacting. Once any node
below it had collapsed, that was another node of the descriptor. The loop carried the upstream
comment `// TODO handle currents correctly`.

A ten-line module shows it. `p - a1 - a2 - n` is `r1` + 1k + 1k, and `V(t) <+ 0` ties terminal
`t` to ground:

| with `r1 = 0` (`a1` collapses into `p`) | before | now |
|---|---|---|
| the midpoint, 0.5 V | vector `n1#a1` | `n1#a2` |
| `print v(n1#a2)` | not available | 0.5 |
| `print v(n1#a1)` | 0.5, the midpoint | not available, as for any collapsed node (E-688) |
| the 0 V branch of `t` | voltage node `n1#a2` | current `n1#flow(t)` |

The corpus models hit the same thing whenever a model collapses its series resistances, as
every one does at its defaults. BSIM-BULK with `rs = 0` named its self-heating branch `n1#si`
and its two noise rows `n1#di` and `n1#di1`. HICUM named its thermal branch `n1#xf1` or
`n1#ei`. The consequences:
- Every vector of such a row had the wrong name.
- A branch current made as a voltage node was tested against `vntol` instead of `abstol`, and
  the reverse.
- E-45's nodeset initializer went on the wrong row.
- Every message naming a row named the wrong one. The campaign's F1 lead followed
  `singular matrix: check node n1#si` into BSIM-BULK's source network, while the singular row
  was the thermal branch: a voltage source loop, which is Enhancement-837's subject.
  Enhancement-833's warning `no DC path from node 'n1#di1'` meant the noise node `N2`.

## The change

Each row is the group of descriptor nodes mapped to it, and `collapse_nodes` keeps the smallest
index as the group's survivor, the node the row stands for. `OSDIsetup` builds that map
(`row_node`) from the instance's local mapping before creating the rows, and takes the name,
`is_flow` and the nodeset from `descr->nodes[row_node[i]]`. With nothing collapsed, the map is
the identity and nothing changes.

Every other reader of `descr->nodes[]` indexes it by descriptor node and goes through the node
mapping, so those were right already:
- the residual and state loops;
- E-416's collapse owner;
- E-688's `OSDIcollapsedNode`;
- E-833's dc-path marking.

## The checks

`osdirows_examples` [1]:
- `r1 = 0`: `n1#a2` = 0.5 V and no `n1#a1` vector; `display` lists `n1#a2` as a voltage.
- 1 mA into the lone net of `t`: `n1#flow(t)` is a current of 1 mA, and `v(tt)` = 0.
- `save v(n1#a1)` names `p`, the node that carries it (E-688). The wrongly named row used to
  answer instead.
- `r1 = 1k`, nothing collapsed: `n1#a1` = 2/3 V and `n1#a2` = 1/3 V (control).
