# Enhancement-734: source stepping puts the diagonal gmin back when it is done — the transient operating point, every transient time point and every DC sweep point after a source-stepped operating point were solved with a gmin shunt on every node (a 1e11 Ω divider read 0.476 V for 0.5 V, a 1e14 Ω node 990 V for 100 kV, on both solvers, silently), and under Sparse an unsolvable loop of voltage sources "converged" with 1/gmin amperes; a floating node that nothing holds is refused instead, and a `.tf` card naming a phantom node is refused before the operating point

**Scope:** F1 of the
[second KLU/Sparse solver-core hunt of 2026-09-25](../docs/bug_hunts/2026-09-25_klu-sparse-solver-cores-second-hunt.md)
(F2's symptom with it). **ngspice only.** `src/spicelib/analysis/cktop.c` (`gillespie_src`
exits with `CKTdiagGmin = CKTgshunt`), `cktsetup.c` (the E-566 warning under a missing hold
says nothing holds the node), `tfanal.c` (the E-426/E-429 output-node checks run before
`CKTop`, as in `noisean.c`), `acan.c` (the E-571 comment).
[`examples/oprobust_examples/`](../examples/oprobust_examples/) (section [R5], 6 checks, 38
per solver). Five suites that had pinned the leaked point move with it:
[`solvercore`](../examples/solvercore_examples/) (F1: the values under the default hold,
the naming and the refusal under `dcpath=off`; 18 per solver),
[`dcpath`](../examples/dcpath_examples/) (the `dcpath=off` road ends in a refusal),
[`singularname`](../examples/singularname_examples/) (the probed port is named and refused),
[`paramrange`](../examples/paramrange_examples/) (the rejected HiSIM-SOI's noise aborts
cleanly after a refused point), [`floatnode`](../examples/floatnode_examples/) (the open
gate's transient-op point without the shunt; the no-hold warning's new text). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page.

**Suites:** `oprobust` 38 of 38 per solver, both solvers (34 of 38 under Sparse and 35 of 38
under KLU on the E-733 binaries); `solvercore` 18 of 18 (17 of 18 on E-733), `dcpath`,
`singularname` 12 of 12 (11 of 12), `paramrange`, `floatnode` 16 of 16 (15 of 16) per solver,
both solvers; `inputguard`, `acgminhold`, `internalnode`, `convhelp` 35 of 35, `opfatal` 8 of
8, `klusingular` 16 of 16, `ptcont` 21 of 21, `linesearch`, `tranopdelay`, `bsrcconv`
unchanged; no new build warnings; full sweep, run alone.

## What was wrong

```spice
* a diode clamp with a 10 Gohm bias network, and a 100 Gohm divider beside it
.option noopiter gminsteps=0
V1 in 0 5
R1 in a 1e10
R2 a 0 1e10
D1 a 0 dm
.model dm d(is=1e-15)
Vs s 0 1
Rs s z 1e11
Rz z 0 1e11
.control
op
print v(z)
tran 1u 10u
print v(z)[5]
.endc
.end
```

The options only send the ladder straight to source stepping, which completes. Node `z` is
0.5 V by inspection; the operating point said so; the transient that followed said 0.4762 V
under both solvers — exactly 0.5 × 2e-11 / (2e-11 + 1e-12), a 1e-12 S shunt on the node
through every time point. A `dc` sweep after the point carried the same shunt, and so did the
transient operating point: an inductor across an ideal source beside `I9 0 z 1n`, `R9 z 0
1e14` read `v(z) = 990.1` where the node alone reads 1e5 V, and `9.999` with `gmin=1e-10`.
Nothing was printed. And under Sparse a loop of three voltage sources whose values do not sum
to zero — a netlist with no solution — ended in "Transient op finished successfully" with
1e12 A circulating (1 V over gmin; 1e10 A at `gmin=1e-10`), where KLU refused it.

`gillespie_src`, the default source stepping (`cktop.c:755-946`), ended with

```c
        ckt->CKTdiagGmin = ckt->CKTgmin = gminstart;
```

on every exit, success or failure — a leftover from when the rung raised `CKTgmin` itself.
Every other rung restores `CKTdiagGmin` to `CKTgshunt` (0 by default) when it is done:
`dynamic_gmin`, `spice3_gmin`, `new_gmin`, `pseudo_transient`, and the inner gmin ladder of
source stepping too. `NIiter` factors with `trGmin = ckt->CKTdiagGmin` on every call and
`LoadGmin` adds it to every diagonal the matrix has, and nothing between jobs clears the
field, so once source stepping had run, the `optran` rung that follows a failed one, every
transient point, every later DC sweep point and the next job's plain Newton all carried the
shunt. Any deck whose operating point needs source stepping — the ordinary reason being a
hard nonlinear circuit at its first `tran` — and has a node above a few hundred megohms was
affected: 0.1 % at 1e9 Ω, 10 % at 1e11 Ω. The AC path knew: [E-571](Enhancement-571.md)'s
comment in `acan.c` read "the ladder leaves CKTdiagGmin at gmin and optran solves with it"
and held its own zero rows to match.

Under Sparse the loop "succeeded" because the shunt landed on the voltage-source *branch
rows* as well: Sparse creates a missing diagonal element during pivoting
(`ExchangeRowsAndCols`, `spfactor.c:2068-2077`), so after the first singular factorization
the branch rows own a `Diag[]` entry that `LoadGmin` feeds, turning `v(a) − v(b) = 1` into
`v(a) − v(b) + gmin·i = 1`. KLU's `LoadGmin_CSC` adds gmin only to stamped diagonals, so it
could not, and refused.

## What changed

**The exit puts the diagonal gmin back.** `gillespie_src` ends with `CKTdiagGmin =
CKTgshunt` like its siblings; `CKTgmin` still goes back to its start value. The divider
reads 0.5 V through the transient and the sweep, the 1e14 Ω node 1e5 V, and the loop is
refused on both solvers, since nothing regularises it any more.

**What the leak had been holding up.** Three kinds of deck had been reaching a "successful"
operating point only through it, and they are honest now:

- A node nothing conducts to under `.option dcpath=off` ([E-566](Enhancement-566.md)'s zero
  diagonal): gmin stepping converges at every rung and then, by design, re-solves without
  the diagonal gmin (`dynamic_gmin`'s last `NIiter`), so the node fails there, source
  stepping fails, and `optran` used to "solve" it with the leftover shunt — the I/gmin that
  E-566's suite pinned. Under the default `dcpath` the hold is [E-575](Enhancement-575.md)'s
  explicit stamp and the node reads I/gmin in plain Newton, as before; with the hold off
  the point is refused, naming the node. The E-566 warning printed on that path said "it is
  held only by gmin"; it now says "connected to nothing that conducts, and nothing holds
  it" — the same line is reached for a name the walk passes by (one carrying `#`).
- A device that a model rejects in eval (`paramrange`'s HiSIM-SOI with `COBCNODE = 0`)
  contributes nothing, its nodes float, and the noise analysis E-571 saw complete "with the
  device absent" was standing on the leak. The point is refused naming `ndut#dp` and the
  noise aborts cleanly — the stop [E-56](Enhancement-56.md) wrote for, and the answer to the
  question E-571 left open.
- An OSDI BSIM4 with an open gate goes through the ladder to `optran` (the walk does not
  hold the gate; its own capacitances carry it in the transient): the point it settles at
  moves by 0.7 mV, the shunt gone.

**A `.tf` card naming a phantom node is refused first.** [E-429](Enhancement-429.md)'s
"output node does not exist (no device connects to it)" and [E-426](Enhancement-426.md)'s
bounds test sat after `CKTop` in `tfanal.c`, so a card naming `x1.n1#mid` on a resistive
divider first sent that node — held by nothing — down the whole ladder, and the refusal was
reached only because `optran` "succeeded" on the leak; with the leak closed the point was
refused and the card's message never printed. The two checks now run before the operating
point, where `noisean.c` already has them.

## Verification

`oprobust` [R5], six checks: with source stepping forced, the operating point is 0.5 V and
the rung ran; the transient after it reads 0.5 V (0.4762 on E-733); the dc sweep after it
0.5 and 1.0 V (0.4762 and 0.9524); the clamp node agrees with the unforced point; the 1e14 Ω
node beside the inductor across a source reads 1e5 V (990); the loop is refused on both
solvers (Sparse "succeeded" on E-733 — 34 of 38 under Sparse, 35 of 38 under KLU there).
The five moved checks each fail on E-733 (the leaked values), and `inputguard` [11] passes
again with the checks moved.

By hand: the hunt's decks (`sv/H/expo.cir`, `B2/hz.cir`, `H/persist_*.cir`, `B2/loopdbg.cir`)
on the new binary; `set ngdebug` traces of the E-566 deck under `dcpath=off` and of the
probed-port and open-gate decks; the 16 ladder-related suites; the sweep twice.

## What this does not do

- Sparse's pivoting still creates branch-row diagonals, and the gmin ladder's own rungs
  still feed them: during gmin stepping the two solvers regularise different equations. The
  loop is refused because the *final* solves carry no diagonal gmin, not because the rungs
  agree. That is the hunt's F2 mechanism, and it stays open.
- A node the DC-path walk passes by (a name with `#`, an OSDI gate whose entries the walk
  reads as a path) is not held; it goes down the ladder as before, and reaches `optran`
  honestly or not at all.
- `dynamic_gmin`'s closing solve without the diagonal gmin is unchanged; a floating node
  with the hold off cannot be "held only by gmin" by that rung, which is why the warning's
  text moved.
- `.noise` already checked its output node first; `.tf` now does. No other analysis takes
  an output node from a card.
