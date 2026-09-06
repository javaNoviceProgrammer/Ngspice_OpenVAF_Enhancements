# Enhancement-563: paramsets per LRM 6.4 — the module's names reused, chains, aliases, output variables and statements, out-of-module `localparam`s, and instantiation inside a module

**Scope:** §3.3 and the crash of §3.1 of the
[coverage audit of *A Practical Guide to Verilog-A*](../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md).
The grammar and parser (`openvaf/syntax/veriloga.ungram`, `openvaf/parser/src/grammar/{items,expressions}.rs`,
the regenerated AST), the item tree and body lowering (`openvaf/hir_def/src/item_tree.rs`,
`item_tree/{lower,diagnostics}.rs`, `body.rs`, `body/lower.rs`), validation
(`openvaf/hir_ty/src/validation.rs`, `validation/body.rs`), the elaboration passes
(`openvaf/hir/src/{elaborate,db}.rs`) and the OSDI output-variable list
(`openvaf/sim_back/src/module_info.rs`). **Compiler only; ngspice is unchanged.**

**Suites:** new [`paramsetlrm_examples`](../examples/paramsetlrm_examples/) (22 checks per
solver, both solvers); `paramset`, `paramsetguard`, `paramsethsp`, `modelparamset`,
`lrmdata`, `alias`, `hierdev`, `hiername`, `hiernode`, `hierbranch`, `lrmhier`, `lrm`,
`langguard`, `defparam`, `mfactor`, `hierparam`, `instarray`, `implicitnet`, `portbranch`
pass; full sweep 461 of 461; the compiler's front-end crate tests pass; the 92-model
corpus compiles as before (91 of 92 standalone, the EPFL-HEMT baseline). Handbook
[§2.1](../docs/handbook/02-verilog-a-language.md), the
[compliance matrix](../docs/compliance/OpenVAF_Verilog-A_LRM_Compliance.md) §3.2 and §6,
the suite README.

## What was wrong

Enhancement-21 compiled a `paramset` into a *twin module*: the target module's items
under the paramset's name, the paramset's own parameters added as card parameters, each
`.x = e;` turning the target's `x` into a localparam holding `e`. That covered the
`.model` card route for a paramset that invents its own parameter names, and nothing
the chapter — or LRM 6.4's own `nch` example — actually writes:

* `parameter real L = 3u; .L = L;` — the paramset's `L` and the module's `L` landed in
  one scope: *'L' was already declared* (`u07`). Every paramset in the book reuses the
  module's names.
* `paramset child base; .KIND = "metal";` — a paramset of a paramset shared the parent's
  parameter items by id, so the twin's parameters were not in textual order and the
  forward-reference check refused them: *definition of 'MAT' references parameter 'KIND'
  defined afterwards* (`u08`).
* `aliasparam LL = LEN;` in a paramset was a parse error, and an alias named in an
  instance override (`rp #(.LL(3u))`, a module's alias too) was *names no parameter*
  (`w03`).
* `(* desc="dissipated power" *) real pdis; pdis = .reff * 1e-6;` — variables and
  statements in a paramset (LRM 6.4.1, 6.4.3) were a parse error (`u11`).
* `.RSH = fab.rsh_poly * fab.bias;` — a hierarchical out-of-module reference to another
  module's `localparam`, which 6.4.1 allows, resolved, typed, and then **crashed the
  compiler** in code generation, which has no value for another module's parameter
  (`u10`, the only crash the audit found).
* And a paramset **instantiated inside a module** rendered the target module's text at
  its defaults: `rk #(.KOHM(4.0)) r1(a, b)` over `.R = KOHM*1000.0` ran at the module's
  1 kΩ, silently — the divider the book builds from paramsets never computed what it
  said.

## What changed

* **Two namespaces, one twin.** The twin now *clones* every target parameter, variable
  and function into fresh items (in textual order, which also settles the
  paramset-of-paramset ordering); a target declaration whose name the paramset reuses
  is cloned as `name$paramset`, and every piece of target-authored text — the analog
  body, parameter defaults, variable initialisers, function bodies — is read through a
  rename map when it is lowered. The map composes level by level through a chain, so
  each text is read in the namespace it was written in. A target parameter the paramset
  reuses but does not assign becomes a localparam at its default: the paramset's own
  declaration is the card parameter, as LRM 6.4 says (an instance "would generate an
  error" overriding the module's). A paramset parameter named like a *net*, *branch*
  or *array* of the module is refused, since those cannot step aside.
* **Chains.** A paramset may target another paramset and assign the parent's own
  parameters; assigning a `localparam`, or a parameter an earlier level already fixed,
  is *paramset assigns 'R', which is not a parameter of 'base'* with the rule.
  `.$mfactor` at an inner level is replaced by an outer one's.
* **Aliases.** `aliasparam` is a paramset item; the twin exports it on the card, and
  an instance override naming an alias of a paramset or of a module binds the parameter
  it aliases (LRM 3.4.7).
* **Variables and statements.** `integer`/`real` declarations (with `(* desc *)`,
  output variables per 6.4.3) and the statements of an analog function are paramset
  items; `.name` in an expression is the target's declaration of that name. The
  statements join the twin's analog body after the target's; `.var = expr;` on a target
  variable is such a statement. A paramset output variable named like the module's
  replaces it (the module's is hidden from the OSDI list), one without a description
  hides the module's. A contribution, an event control, a named block or an access
  function in a paramset statement is refused with the clause.
* **Out-of-module `localparam`s.** A new elaboration pass substitutes `M.p` in a
  paramset's text — `M` a module of the file, `p` its `localparam` — by the folded
  default in parentheses (sibling localparams substituted in turn), before the item
  tree is built; a reference to a non-local `parameter` is refused, as 6.4.1 requires.
* **Instantiation.** An instance of a paramset is an instance of the module at the
  end of its chain: each level's own parameters take the instance's override (alias
  names resolved) or their default, its `.x = e;` texts become the next level's values,
  `.$mfactor` composes with the instance's, an override of a parameter the paramset
  fixes is refused, and the levels' variables and statements are appended to the
  flattened body — `.name` resolving to the module's flattened declarations and each
  inner level's — so `@n1[rc__pdis]` reads the paramset's output variable of instance
  `rc`.

## Verification

| check | result |
|---|---|
| `rp`: own `L`, `W`, `KIND`; `.RSH = fab.rsh_eff` (localparam of localparams); `.$mfactor = 2` | `reff` = 290.939 at the defaults, 289.455 with `L=6u W=2u` on the card; `RSH=5` on the card ignored |
| `rmetal rp`: `.KIND = "metal"; .L = LEN;` with `aliasparam LL = LEN;` | `reff` = 192.98; `LL=5u` → 486.857 |
| `rpd`: `pdis = scratch * 2.0` from `scratch = .reff * 1e-6`; `fig = .reff / 100.0` | `pdis` = 6e-4, `fig` = 3 (replacing the module's −1); `WID=2u` → 3e-4 |
| the divider: `rmetal #(.LL(LA))`, `rp #(.W, .L, .$mfactor(3))`, `rpd #(.WID(2u))` inside a module | `i(vin)`, `v(out)`, `ra__reff`, `rb__reff` (m = 6), `rc__pdis`, `rc__fig` exact |
| the audit's `u07`, `u08`, `u10`, `u11`, `w03`, and `t14` without its overloaded paramset | compile; `t14`'s divider draws 2.58442 mA as computed |
| forbidden statements; a net-named parameter; a fixed parameter assigned; a non-local hierarchical reference; an instance overriding a fixed parameter | each refused with its named diagnostic |
| `paramsetlrm_examples`; nineteen paramset, alias and hierarchy suites; full sweep | 22 / 22 both solvers; all pass; 461 of 461 |
| front-end crate tests; model corpus | pass; 91 of 92 standalone (baseline) |

Still open, and recorded in the compliance matrix: overloaded (same-name) paramsets
with the 6.4.2 selection rules, and a random draw in an override (Enhancement-545's
documented statistics design).
