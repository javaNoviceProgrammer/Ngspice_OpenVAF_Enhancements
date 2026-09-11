# Enhancement-608: a device's internal node can be named by `.ic`, `.nodeset`, `.tf` and `.pz`, and a job bound to one stays bound

**Scope:** `src/spicelib/analysis/cktmkvol.c` (`CKTmkSignal`: adoption of a parse-time
node, revival of a retired one; `CKTmkVolt`/`CKTmkCur` on it, `cktmkcur.c`),
`cktdltn.c` (a device-local node retired, not freed; an adopted one left in place —
`CKTdltNNum` and E-470's `CKTdltNodeSet`), `cktsetnp.c` (the pending `.ic`/`.nodeset`
entries), `cktsetup.c` (placed after the devices' setup), `cktdest.c`,
`src/include/ngspice/cktdefs.h` (`CKTnode.adopted`, `CKTretiredNodes`,
`CKTpendingNodeParms`), `src/spicelib/parser/inppas3.c` (`.ic`/`.nodeset` on
`<instance>#<node>` kept for setup), `examples/internalnode_examples/` (new, 11 checks
per solver); `examples/sweepparam_examples/` [5] re-pinned. **ngspice only; built-in devices and OSDI alike.** Finding N2 of the
2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)),
a stock ngspice defect — and, found on the way, a use of freed memory.

**Suites:** [`internalnode_examples`](../examples/internalnode_examples/) 11 of 11 per
solver, both solvers; `inputguard` (E-429's phantom check), `teardown` (E-470), `dcpath`,
`osdireload`, `lifecycle`, `netinit`, `mcfastpath` unchanged; `sweepparam` [5], which pinned the
refusal as a uniform limitation, re-pinned to the new behaviour; full sweep 502 of 502 (one sweep, Enhancements
604–608 folded together).

## What was wrong

A device builds its internal nodes — `n1#mid` for a Verilog-A `electrical mid`,
`d1#internal` for a diode with `rs` — at setup, after the deck is parsed.

```
.nodeset v(n1#mid)=0.7
.ic v(n1#mid)=0.7
.tf v(n1#mid) v1
.op
.print op v(n1#mid) v(out)
```

- **Two nodes of one name.** The `.tf` card had the deck reader make a node `n1#mid`
  ahead of the device (Enhancement-429's `inp_analysis_node`, which is what lets a
  `.tf` card precede the devices defining its nodes), and at setup `CKTmkVolt`, told by
  `IFnewUid` that the name existed, went on and linked a **second** node under it. The
  deck's node floated ("held only by gmin", singular-matrix warnings, an operating
  point that needed gmin and source stepping and a transient ramp), the `.nodeset` and
  `.ic` went to it, `.print op v(n1#mid)` printed its 0 next to the real 0.75 in the op
  listing, and E-429 refused the `.tf` output as a node "no device connects to" — true
  of that one. A `.ic`/`.nodeset` without a `.tf` beside it was simply refused, "on
  non-existent node, ignored".
- **A job bound to freed memory.** Interactively, `tf v(n1#mid) v1` typed after an
  `op` bound to the live internal node; the run's own unsetup then **freed** it
  (`CKTdltNNum`), setup built a new one, and the job read the old pointer: a transfer
  function of −5e-4 for a divider's mid node (0.75), the same number as its output
  impedance.

## What changed

- **Adoption.** `CKTmkSignal` (the one routine behind `CKTmkVolt` and `CKTmkCur`),
  finding the name taken by a parse-time node (its number at or below
  `prev_CKTlastNode`'s), adopts that node as the device's internal node: `devRef` and
  `adopted` set, the type set, nothing linked. It is the deck's node, so `CKTdltNNum`
  and `CKTdltNodeSet` leave it in place at unsetup — where a parse-time number used to
  be a fatal "removing a non device-local node" — and the next setup adopts it again.
  Every card that bound to it is bound to what the device stamps.
- **Revival.** A device-local node is not freed at unsetup: `CKTdltNNum` retires it
  under its name (a hash on the circuit, the name a private copy since `IFdelUid`
  frees the symbol table's), and `CKTmkSignal` of that name at the next setup revives
  the same struct — a job's pointer stays valid, and its `number` is the new one.
  `CKTdestroy` frees what is left.
- **`.ic`/`.nodeset` on `<instance>#<node>`.** INPpas3 keeps such an entry by name
  when the part before the '#' names an instance of the deck (`CKTpendNodPm`), and
  `CKTsetup` places it once the devices have built their nodes, at every setup. A
  suffix the device does not build is reported there, once: "IC on non-existent node
  - n1#mdi, ignored (n1 has no internal node 'mdi')" — no floating node is made for
  it. A name that is no instance's is refused as before.

The built-in diode ignores a node-level `.ic` on `d1#internal` under `uic` (it computes
its junction from its own `ic` parameter); that is the device's convention, untouched.

## Verification

| check | before | now |
|---|---|---|
| batch `.tf v(n1#mid) v1` | refused, the node duplicated, gmin/source stepping | 0.75 and 375 Ω; one node; `.print op v(n1#mid)` 0.75; no warning |
| `op`, then `tf v(n1#mid) v1`, again, then `op` | −5e-4 / −5e-4 (freed memory) | 0.75 / 375 Ω both times; the op still 0.75 |
| `.ic v(n1#mid)=0.3`, `tran uic` | "IC on non-existent node, ignored" | the node starts at 0.3 |
| `.nodeset v(n1#mid)=0.7`, `.op` | refused | accepted; 0.75 |
| `.pz ... n1#mid ...`; `.noise v(d1#internal) v1` | refused / refused | the pole at −1e6 (= −1/RC); a total > 0 |
| `.ic v(n1#mdi)` (wrong suffix) | refused at parse | reported once at setup, naming the instance; no floating node |
| `.nodeset v(nosuch#mid)` | refused | refused as before |
| the diode's `d1#internal` in a `.tf` (batch and after an `op`) | refused / wrong | ≈0.99 (rs into 1 kΩ); one vector of the name |
| 20 `op` runs | — | the node revived each time; one vector; 0.75 |

Full sweep 502 of 502 on both solvers.
