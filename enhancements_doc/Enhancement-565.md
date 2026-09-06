# Enhancement-565: paramset overloading per LRM 6.4.2, inside a module and on the `.model` card

**Scope:** the last paramset item of §3.3 of the
[coverage audit of *A Practical Guide to Verilog-A*](../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md).
The item tree (`openvaf/hir_def/src/item_tree.rs`, `item_tree/lower.rs`, `data.rs`), the
HIR (`openvaf/hir/src/lib.rs`), elaboration (`openvaf/hir/src/elaborate.rs`), the OSDI
side tables (`openvaf/sim_back/src/module_info.rs`, `openvaf/osdi/src/{lib,metadata}.rs`,
`openvaf/hir_ty/src/table_source.rs`), and in ngspice the registry and the model
materialisation (`src/osdi/{osdiregistry,osdiinit}.c`, `src/include/ngspice/osdiitf.h`,
`src/spicelib/parser/inpgmod.c`). **Compiler and ngspice.**

**Suites:** new [`paramsetoverload_examples`](../examples/paramsetoverload_examples/)
(14 checks per solver, both solvers); `paramsetlrm`, `paramset`, `paramsetguard`,
`paramsethsp`, `modelparamset`, `osdireload`, `paramgiven`, `osdidist`, `genhier`, `lrm`,
`langguard`, `instdep`, `mcpolicy` pass; full sweep 463 of 463; the compiler's front-end
crate tests pass; the 92-model corpus compiles as before (91 of 92 standalone, the
EPFL-HEMT baseline). Handbook [§2.1](../docs/handbook/02-verilog-a-language.md), the
[compliance matrix](../docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md) §3.2 and §6,
the suite README.

## What was wrong

LRM 6.4.2: "Paramset identifiers need not be unique: multiple paramsets can be declared
using the same paramset_identifier … During elaboration, the simulator shall choose an
appropriate paramset from the set that shares a given name for every instance that
references that name", by four rules and three tie-breaks the book explains at length. A
second `paramset nch nmos3;` was *'nch' was already declared in this scope* (`u12`, `t14`),
so there was never a set to choose from.

## What changed

* **A family of twins.** A paramset declared under a name already taken by a paramset
  becomes the twin module `<name>__2` (then `__3`, …, in declaration order), and every
  member of the family, the first included, records the shared name. Nothing else about a
  member changes: each is a complete OSDI module, usable by its own name.
* **Selection inside a module.** An instance of the shared name is resolved at
  elaboration by the clause's rules: every parameter the instance overrides (an alias
  counts) is a parameter of the member; the member's own parameters, overridden or
  defaulted, lie within their declared ranges; its local parameters within theirs; the
  module at the end of its chain has every port connected by name. Among the survivors,
  the fewest un-overridden parameters, then the most ranged local parameters, then the
  fewest unconnected ports. None left, or more than one, is a located error naming each
  member's reason. A value or a bound that is not a literal is taken as satisfied.
* **Selection on the `.model` card.** The object carries, per descriptor, the family name
  (`OSDI_PARAMSET_FAMILIES`) and the literal default of every parameter
  (`OSDI_PARAM_DEFAULTS`, NaN when the default is not a constant) beside Enhancement-558's
  range texts; older objects and simulators simply lack the symbols. When a `.model` card
  names a family, ngspice applies the same rules as the card is materialised — every
  parameter the card gives is one of the member's own (a parameter the paramset fixed is
  not), the given values and the un-given defaults lie within the ranges parsed from the
  range texts, the fewest un-overridden parameters win — binds the card to the member, and
  announces it: *paramset 'nch' resolved to its member 'nch__2' (LRM 6.4.2)*. A card
  naming a member (`nch__4`) is taken as written. None applying, or several, is the card's
  error with every member's reason.

## Verification

The LRM's own example — the default, mismatch, short-channel and long-channel `nch` over a
conductance stand-in whose current and `uu` reveal the member:

| check | result |
|---|---|
| `m1 #(.l(1u), .w(5u), .mm(1))` | mismatch: u0 = 600, i = kp·5·(600/650) |
| `m3 #(.l(1u), .w(10u))` | default: u0 = 650 (mismatch's `mm = 0` is outside `(0:1]`; long-channel would leave two parameters un-overridden) |
| `m4 #(.l(3u), .w(5u), .ad(1.2p), .as(1.3p))` | long-channel: u0 = 640, nfs = 0.7e12 |
| `.model dm nch mm=1` / `l=1u w=10u` / `l=3u w=5u ad=1.2p as=1.3p` / `l=0.5u ad=1p` / `nch__4` | `nch__2` / `nch` / `nch__4` / `nch__3` / `nch__4`, values as above |
| `.model dm nch zz=1`; `nch l=0.1u` | *no paramset 'nch' applies to .model dm (LRM 6.4.2): nch: 'zz' is not one of its parameters; nch__2: …* |
| two identical members; a value outside every member's range, instantiated | *paramset 'rr' is ambiguous for instance 'u1'*; *no paramset 'rr' applies to instance 'u2'* |
| `paramsetoverload_examples`; thirteen paramset and model-creation suites; full sweep | 14 / 14 both solvers; all pass; 463 of 463 |
| front-end crate tests; model corpus | pass; 91 of 92 standalone (baseline) |
