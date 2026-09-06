# Enhancement-570: "singular matrix: check node" names the node whose equation is vacuous — the same one under KLU and Sparse

**Scope:** the singular-matrix report shared by the DC and AC Newton loops
(`SMPgetError()` in `src/maths/KLU/klusmp.c`, new `SMPzeroLine()`,
`src/include/ngspice/smpdefs.h`), both solvers. Found while answering "what if an OSDI
input node is floating" for Enhancement-569: a BSIM4 whose gate hung on a Verilog-A
capacitor was reported as "check node g" by Sparse and "check node d" by KLU.
**ngspice only.**

**Suites:** new [`singularname_examples`](../examples/singularname_examples/) (12 checks
per solver, both solvers; compiles `va_cap.va` and `va_vcvs.va`, uses the benchmark
BSIM4); `floatnode`, `solvercore`, `ctrlnode`, `silentports`, `groundports`,
`explicitvalue`, `oprobust` — every suite that pins a "check node" name — pass; full
sweep 469 of 469 on both solvers.

## What was wrong

When a factorization fails, `NIiter` and `NIacIter` ask `SMPgetError()` which unknown to
blame and print "singular matrix: check node X". Under Sparse the answer is the step at
which `spFactor` found no pivot; under KLU it is `klu_factor`'s `singular_col`. Both are
the column at which *that* solver's elimination order first ran out of pivots — and for
a rank-deficient block of more than one unknown, that is any of the block's columns,
decided by the ordering heuristic. The same defect could therefore carry two names.

The deck that showed it: a BSIM4 (through OSDI) with its gate reached only through a
Verilog-A capacitor. In DC the gate's row is all zero — no gate conductance, the
capacitor contributes nothing — and the gate and drain form one singular block. Sparse
named `g`, the node with no equation; KLU named `d`, the node that happens to be
eliminated last in its AMD order. Only the first tells the user anything, and a reader
comparing the two solvers sees a disagreement where there is none. A CMOS inverter
chain with its input open showed the same thing more quietly: Sparse said `in` six
times, KLU said `in` five times and `o2` once.

## What changed

`SMPgetError()` looks at the loaded matrix before it trusts the pivot. A row whose
values are all zero is a node whose equation is vacuous — nothing conducts to it in
this analysis — and that node is named, whatever the pivot order; an all-zero column
(an unknown no equation mentions) is the same thing seen from the other side and is
named when no zero row exists. Only when the matrix has neither does the factorization's
own index stand. The scan (`SMPzeroLine()`, one pass over the values) runs only after a
singular factorization, so it costs nothing on a solve that works, and it reads the
values a failed factorization leaves behind: KLU never touches its arrays, and under
Sparse a zero line stays zero through elimination, since every update it receives is a
multiple of one of its own zeros. The complex values are read when the matrix is
complex, so the AC path, which reports through the same call, is covered.

Both solvers now say `g` for the capacitor-coupled gate, the open BSIM4 gate and the
open MOS1 gate; `in`, and only `in`, for the inverter chain; `x` for a capacitor alone
on a node and for a Verilog-A module's probed port (Enhancement-569's zero diagonal). The
fallback is unchanged and pinned: two ideal voltage sources in parallel and two ideal
inductors in parallel have no zero line, and both solvers still name a source or
inductor branch as before.

Noticed on the way and left for its own enhancement: an AC analysis on a node the
operating point holds only by gmin (Enhancement-569's read-only node) still fails with
"matrix is singular", because the AC matrix carries no gmin at all. The deck could not
reach its AC before E-569 either.

## Verification

| check | result |
|---|---|
| BSIM4 gate through a Verilog-A capacitor | every report "check node g" under both solvers (KLU said `d`); v(g) = 0.5987, v(d) = 0.4371 unchanged |
| BSIM4 open gate; built-in MOS1 open gate; a capacitor alone on a node; a Verilog-A probed port | `g`, `g`, `x`, `x` under both solvers |
| CMOS inverter chain with its input open | only `in` under both solvers (KLU also said `o2`) |
| two ideal voltage sources in parallel; two ideal inductors in parallel | no zero line: `v1#branch` and `l2#branch` as before, both solvers |
| AC on the capacitor-only deck | the operating point's reports name `x`; the AC runs |
| `singularname_examples`; the seven suites that pin a "check node" name; full sweep | 12 / 12 both solvers; all pass; 469 of 469 |
