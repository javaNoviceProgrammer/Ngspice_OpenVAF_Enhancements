# Enhancement-662: a corner named `tt`, `nom` or `nominal` is refused at compile time, the loops never visit one, and a name listed twice runs once

**Scope:** F3 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
Compiler: `openvaf/sim_back/src/module_info.rs` (`CornerNameReserved`, the
seventh corner diagnostic). ngspice: `src/osdi/osdisetup.c`
(`osdimc_corner_is_nominal_name`; the declared-name collector leaves the
nominal's spellings out), `src/frontend/com_sweep.c` (`corners -list` folds
duplicates). `examples/vacorner_examples/` (one check added, 27 per solver),
`examples/cornerscmd_examples/` (one, 22). Handbook
[§2.13](../docs/handbook/02-verilog-a-language.md) row and
[§3.7](../docs/handbook/03-ngspice-workflows.md). **Compiler and ngspice
together.**

**Suites:** [`vacorner_examples`](../examples/vacorner_examples/) 27 of 27 and
[`cornerscmd_examples`](../examples/cornerscmd_examples/) 22 of 22 per solver,
both solvers (the new check of each fails on the E-661 binaries); `autocorner`
unchanged; the compiler's workspace tests green (the three sourcegen rewrites
are the known drift); full sweep 529 of 529.

## What was wrong

`(* corner="tt=5, nom=6, ss=7, Nominal=8" *)` compiled without a word. In
ngspice `.option corner=tt`, `nom` and `nominal` *are* the nominal by
[E-654](Enhancement-654.md)'s rule, so the declared `tt`, `nom` and `Nominal`
entries could never be selected — `set corner=tt` gave `a = 1`, not 5. And the
`corners` command's default set, which puts `tt` first and then every declared
name, became `tt tt nom ss nominal`: the nominal run three times under three
names, and `.option autocorner`'s set the same. `corners -list TT,SS,ss` ran
`ss` twice as well: the listed names were folded to lower case but not folded
together.

## What changed

- **The compiler refuses the nominal's spellings** as corner names, after the
  case fold, with the seventh corner diagnostic: *corner 'tt' names the
  nominal: ngspice's `.option corner=tt` (`nom`, `nominal`) selects the nominal
  and never reaches this entry* — help: *the nominal needs no entry — a
  parameter sits at its default there; give a process corner another name (ss,
  ff, sf, fs, …)*. One error per attribute, located in it, as the other corner
  diagnostics are.
- **ngspice's declared-name collector leaves those spellings out**, so an
  object from a compiler before E-662 that declares one is looped over at its
  real corners only: the `corners` default set, `.option autocorner`'s set and
  the *declared: …* list of a refused name all say `tt ss` for the model above.
  A `tt` entry is unreachable either way; now it is also not a corner to visit.
- **`corners -list` folds a name listed twice**, after the case fold and the
  nominal fold (`nom` and `TT` are the same `tt`): *corners: 'ss' is listed
  twice; it runs once*, once per duplicate, and the set is `tt ss`.

## Verification

| check | result |
|---|---|
| `tt=5`, `Nominal=8`, `nom=6` on three parameters | three errors naming the nominal, each in its attribute, with the help; no object written |
| the pre-E-662 object with `tt`, `nom`, `nominal`, `ss` on the new ngspice | `corners` default set `tt ss` (was `tt tt nom ss nominal`); `autocorner` the same; *declared: ss* |
| `corners -list TT,SS,ss,nom -output rsh=…` | 2 corners (tt ss), 100 115; 'ss' and 'tt' each said to be listed twice and run once |
| the E-661 binaries on the same suites | the new check of each fails |

Full sweep 529 of 529 on both solvers.

## What this does not do

- The nominal's three spellings are the only reserved names; every other name
  is a corner, `TT` included when it is meant as the nominal (it folds to `tt`
  and is refused too).
- A `.lib`-section corner named `tt` is ngspice's ordinary library mechanism
  and untouched.
