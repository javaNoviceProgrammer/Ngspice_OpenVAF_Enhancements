# openvaf-r — Full Change Report

**Every modification applied to the OpenVAF-Reloaded compiler in this
project, with its reason.** The baseline is the pristine OpenVAF-Reloaded
source tree (as vendored in the project's `original/` snapshot); the
current state is the tree committed in this repository under
`OpenVAF-master-20260610/`. Each entry links the enhancement write-up in
[`enhancements_doc/`](../../enhancements_doc/) that carries the full
engineering detail and the verifying example suite. The companion
document [ngspice_changes_full-report.md](ngspice_changes_full-report.md)
covers the simulator side.

> **Maintenance note:** this report is updated whenever an enhancement
> touches compiler sources. The per-enhancement index at the end tells
> you the last change it covers.

**Scope summary.** ~120 modified source files across the compiler
pipeline, two new files (`hir/src/elaborate.rs` — the elaboration pass —
and `hir_def/src/item_tree/diagnostics.rs`), plus three classes handled
wholesale: the `test_data/` fixtures and snapshots (95 files — new test
inputs and snapshots regenerated whenever a feature legitimately changed
descriptor contents), the `integration_tests/*/​*.osdi` reference objects
(regenerated at each ABI bump), and the removal of the AGPL `vacask`
submodule. The compiler builds **warning-free**; every change below was
regression-gated by the example-suite arsenal, the integration suite, and
the VA_TEST industry-model corpus.

---

## 1. Lexer — `openvaf/lexer/` (`lib.rs`, `cursor.rs`)

- **Based integer literals** (`8'hFF`, `'sb101`): the lexer had only a
  commented sketch; underscores crashed it. Both the sized and unsized
  forms now lex, requiring a digit after the base (a silent-0 trap
  otherwise) ([E-46](../../enhancements_doc/Enhancement-46.md)).
- **Don't-care digits** `x/X/z/Z/?` accepted in the binary/octal/hex
  digit runs for `casex`/`casez` items
  ([E-78](../../enhancements_doc/Enhancement-78.md)).
- **Escaped identifiers** (`\my-net!`) lexed per the LRM
  ([E-46](../../enhancements_doc/Enhancement-46.md)).
- **`// comment at EOF` hang fixed**: with no trailing newline the
  line-comment loop spun forever on the EOF character — the only
  EOF-unsafe loop in the lexer
  ([E-35](../../enhancements_doc/Enhancement-35.md)).

## 2. Tokens and grammar — `openvaf/tokens/`, `openvaf/parser/`, `veriloga.ungram`, `sourcegen/`

`tokens/src/parser/generated.rs` gains the keywords and node kinds each
language feature needed, threaded through `parser/src/grammar/*`
(`stmts.rs`, `expressions.rs`, `items.rs`, `items/module.rs`), the
grammar source of truth `syntax/veriloga.ungram`, and the `sourcegen/`
generators (`ast/src.rs`, `hir_builtins.rs`, `mir_instructions.rs` — the
templates the generated token/AST/builtin/instruction tables come from):

- `do … while` post-test loops ([E-19](../../enhancements_doc/Enhancement-19.md));
- `paramset`/`endparamset` blocks ([E-21](../../enhancements_doc/Enhancement-21.md));
- `{…}` concatenation and `{n{…}}` replication as real operators, with
  `'{…}` remaining the typed aggregate
  ([E-34](../../enhancements_doc/Enhancement-34.md));
- array-literal expressions actually parsed (they were fully scaffolded
  but unreachable) ([E-4](../../enhancements_doc/Enhancement-4.md), [E-14](../../enhancements_doc/Enhancement-14.md));
- vectored (bus) net declarations and bit-selects
  ([E-3](../../enhancements_doc/Enhancement-3.md)), multi-index bit-selects
  for N-D arrays ([E-15](../../enhancements_doc/Enhancement-15.md)), and the
  LRM name-then-range declaration order
  ([E-18](../../enhancements_doc/Enhancement-18.md));
- module instantiation items ([E-5](../../enhancements_doc/Enhancement-5.md)),
  `generate for`/`genvar` ([E-8](../../enhancements_doc/Enhancement-8.md)),
  and `generate if`/`generate case` with optional block labels
  (previously mis-parsed into a broken `GENERATE_FOR`;
  [E-67](../../enhancements_doc/Enhancement-67.md));
- `defparam` — a reserved word with no grammar rule
  ([E-58](../../enhancements_doc/Enhancement-58.md));
- event **OR lists** `@(cross(…) or timer(…))` via a new `or` keyword and
  looped event grammar ([E-59](../../enhancements_doc/Enhancement-59.md));
- `casex`/`casez` sharing the case rule, the keyword token carrying the
  flavor ([E-78](../../enhancements_doc/Enhancement-78.md));
- `@(initial_step)`/`@(final_step)` with analysis-phase lists
  ([E-7](../../enhancements_doc/Enhancement-7.md), [E-53](../../enhancements_doc/Enhancement-53.md));
- indirect branch assignment `V(x): V(y) == expr;`
  ([E-2](../../enhancements_doc/Enhancement-2.md));
- the `<<<`/`>>>` arithmetic-shift tokens (plus a pre-existing lexer bug
  fix) ([E-6](../../enhancements_doc/Enhancement-6.md));
- **hierarchical parameter override targets** (`#(.blk.p(4))`): the
  extra `.segment`s are consumed so the parse stays clean instead of
  cascading -- elaboration then rejects the block-scoped override with a
  targeted diagnostic ([E-87](../../enhancements_doc/Enhancement-87.md));
- **hierarchical branch reference tails** (`.branch(a,b)` / `.branch(<p>)`)
  swallowed into the path node so the enclosing item's CST stays whole
  for the elaboration rewrite (a keyword in path position used to shred
  the item, leaving the hole scanner truncated text) ([E-86](../../enhancements_doc/Enhancement-86.md));
- **part-selects in instance connections** (`inst (out[3:2], in)`): the
  bit-select bracket accepts an optional `: expr`, with the colon token
  in the CST distinguishing a range from multi-dimensional indexing —
  no new node kind ([E-85](../../enhancements_doc/Enhancement-85.md));
- **module-level `generate for`/`if`/`case` without the optional
  `generate`/`endgenerate` keywords**: `module_items` handled a
  `generate … endgenerate` region but had no bare `FOR_KW`/`IF_KW`/`CASE_KW`
  arm, so a keyword-less loop at module scope fell to error recovery —
  `unexpected token 'for'`, or a silent drop of the loop when a following
  `analog` block let recovery resync. New arms parse it into the same
  `GENERATE_FOR`/`IF`/`CASE` nodes the nested/`generate`-wrapped forms
  produce ([E-96](../../enhancements_doc/Enhancement-96.md));
- **panic-free direction parsing**: `port_decl`/`func_arg` asserted the
  next token was a direction (`bump_ts`), which any non-Verilog text
  reaching a module-head port list turned into a compiler crash; both
  now emit a diagnostic with one token of forced progress
  ([E-84](../../enhancements_doc/Enhancement-84.md));
- **operator precedence corrected against LRM Table 4-2**: `%` bound
  tighter than `*`/`/` (so `6*7%4` evaluated to 18, not 2), and xnor
  split from xor ([E-38](../../enhancements_doc/Enhancement-38.md));
- derived-nature parents emitted the wrong node kind (`NAME_REF` where
  the AST wanted `Path`), leaving the entire inheritance machinery
  unreachable ([E-39](../../enhancements_doc/Enhancement-39.md)).

## 3. Preprocessor — `openvaf/preprocessor/` (+ `basedb` diagnostics)

- **Ten compiler directives** that previously hard-failed as undefined
  macros: `` `default_discipline ``, `` `celldefine ``/`` `endcelldefine ``,
  `` `unconnected_drive ``/`` `nounconnected_drive ``, `` `timescale ``,
  `` `line ``, `` `pragma ``, `` `undefineall ``, `` `default_nettype ``
  ([E-6](../../enhancements_doc/Enhancement-6.md)).
- **`` `default_transition ``** parsed and threaded to `transition()`
  lowering ([E-47](../../enhancements_doc/Enhancement-47.md)).
- **Recursive macro expansion crashed the compiler** (stack overflow,
  direct and mutual): the `MacroRecursion` diagnostic existed but was
  never emitted, and its report renderer was a `todo!()`. The guard
  pushes around the macro *body* expansion only — an entry-scoped guard
  false-positives on the legal `QUAD(x) = TWICE(TWICE(x))` nesting
  ([E-65](../../enhancements_doc/Enhancement-65.md)).

## 4. Syntax / AST — `openvaf/syntax/` (`ast.rs`, `generated/nodes.rs`, `expr_ext.rs`, `node_ext.rs`, `name.rs`, `validation.rs`, `error.rs`)

- Typed AST nodes for every new construct above (generated from the
  ungrammar).
- **Literal decoding** (`expr_ext.rs`): based-int parsing with
  size/sign handling ([E-46](../../enhancements_doc/Enhancement-46.md)) and
  the mask-aware variant returning `(value, x_mask, z_mask)` for
  casex/casez ([E-78](../../enhancements_doc/Enhancement-78.md)); a compiler
  crash on large bare-integer-shaped literals fixed by falling back to a
  float constant ([E-4](../../enhancements_doc/Enhancement-4.md)).
- **String unescaping rewritten as a single pass**: the sequential
  `str::replace` chain corrupted overlapping escapes (`\\n`) and octal
  `\ddd` was missing; all consumers route through one function
  ([E-48](../../enhancements_doc/Enhancement-48.md)).
- **`Name::resolve` ate the last character of escaped identifiers**
  (the committed `std.va` snapshot had baked the bug in as `logi`)
  ([E-46](../../enhancements_doc/Enhancement-46.md)).

## 5. Elaboration — `openvaf/hir/src/elaborate.rs` (new file)

The compile-time flattening pass: every stage downstream of the parser is
architected around exactly one flat module per artifact, so hierarchy is
resolved by recursively inlining instantiated modules — alpha-renamed per
instance, ports bound to the caller's nets, parameters bound to
overrides — into an ordinary flat module *before* the rest of the
pipeline runs. Built for module instantiation
([E-5](../../enhancements_doc/Enhancement-5.md)) and grown into the home of
every structural feature:

- `generate for`/`genvar` unrolling ([E-8](../../enhancements_doc/Enhancement-8.md)),
  nested loops, anonymous blocks, `generate if`/`case` with elaboration-
  time constant folding, and the genvar-substitution fix (genvars in
  ordinary expressions were routed through identifier renaming, which
  re-escaped `1e3*(i+1)` into a broken escaped identifier; they now
  become literal-value holes)
  ([E-67](../../enhancements_doc/Enhancement-67.md));
- **implicit nets** from undeclared instance connections, discipline
  derived from the connected port, prefixed per instance so no
  cross-instance shorts ([E-41](../../enhancements_doc/Enhancement-41.md));
- **hierarchical names** `u1.u2.node` and `$root` via an instance-chain
  map and a hole scanner ([E-49](../../enhancements_doc/Enhancement-49.md));
- **`defparam`** resolved through the same chain rewrite, with the
  LRM-mandated precedence over instance `#()` overrides
  ([E-58](../../enhancements_doc/Enhancement-58.md));
- **net concatenation in port connections** expanded bit-by-bit onto
  vectored ports ([E-59](../../enhancements_doc/Enhancement-59.md));
- bus slicing onto instance arrays and bus ports
  ([E-5](../../enhancements_doc/Enhancement-5.md)); paramset twin-module
  rendering ([E-21](../../enhancements_doc/Enhancement-21.md)); net
  initializers preserved through re-rendering
  ([E-45](../../enhancements_doc/Enhancement-45.md)); escaped identifiers
  re-rendered correctly ([E-46](../../enhancements_doc/Enhancement-46.md));
- **undefined instantiation targets are a hard error** — they used to be
  silently dropped from the rendered output, turning a typo'd module
  name into an invisible open circuit; discipline-named mis-parses
  (`electrical out[0:2];` parses as an instantiation) and paramsets
  dropped over unresolvable targets get tailored messages
  ([E-84](../../enhancements_doc/Enhancement-84.md));
- **name-then-range net/port declarations** (`input in[0:2]`,
  `electrical out[0:2]`, LRM 3.6/3.7): a textual pre-pass rewrites the
  `<head> <name>[range]` form to the range-then-name form (Enhancement-3),
  reusing all bus/port machinery; the `(`-after-range instance rule keeps
  instance arrays untouched ([E-89](../../enhancements_doc/Enhancement-89.md)).
  Extended to **multi-name** lists (`input a[0:1], b[0:3], c;`), split into
  one range-then-name declaration per name with per-name widths; a
  multi-dimensional name is left untouched (unsupported in both orders)
  ([E-91](../../enhancements_doc/Enhancement-91.md));
- **parameter-dependent declaration widths** (`electrical [0:N-1] out;`,
  `real w[0:N-1];`): a textual pre-pass folds a declaration range whose
  bounds reference a parameter to a literal range, using the module's
  constant-integer parameter defaults (a fixpoint resolves one default
  through another; `from`/`exclude` constraints are skipped). Only
  declaration ranges (with a `:`) are folded, not bit-selects; the shared
  constant-integer evaluator gained an optional parameter map (empty map =
  the E-88 literal-only behavior). The width is fixed at the default -- a
  structural parameter, since OSDI has one node count per module (E-67/88
  decision) ([E-91](../../enhancements_doc/Enhancement-91.md)). A parameter
  that shaped a width is then **frozen to a `localparam`**
  (`freeze_width_parameters`): a multi-parameter declaration is split so only
  the structural names freeze, and a range constraint is dropped from a frozen
  name. This keeps structure and behaviour consistent under a netlist override
  -- without it, overriding a width parameter that also bounds a runtime loop
  left the frozen array size behind, a silent out-of-bounds
  ([E-92](../../enhancements_doc/Enhancement-92.md));
- **the legacy `generate <id> (start, end [, incr])` statement**
  (obsolete Verilog-A 1.0 analog-block loop-unroll, LRM Annex C.4)
  unrolled by a textual pre-pass: the index substitutes to a literal per
  iteration (with bit-select bracket folding, since a bus bit-select needs
  a literal index), constant bounds only -- a parameter bound cannot shape
  the unroll (E-67 scope decision) ([E-88](../../enhancements_doc/Enhancement-88.md));
- **`` `__FILE__``/`` `__LINE__`` expanded by a textual pre-pass** run
  before the other passes (preprocessor tokens are (kind, span) pairs
  into existing source and cannot carry synthesized literals):
  `` `__FILE__`` becomes the root file's basename (machine-portable
  provenance, the E-58 rule), `` `__LINE__`` the exact 1-based line;
  string/comment occurrences are skipped and replacements are inline so
  later line numbers stay true ([E-85](../../enhancements_doc/Enhancement-85.md));
- **part-select actuals sliced onto bus ports** in `bind_port`
  (`base[msb:lsb]`, constant bounds; positional and named forms;
  width-1 slices onto scalar ports degrade to the bit-select) with the
  same ascending bit-order convention as full-bus slicing
  ([E-85](../../enhancements_doc/Enhancement-85.md));
- **block-scoped parameter override rejected** with a targeted message
  (a named instance override `#(.blk.p(4))` naming a hierarchical target
  is collected and bailed like the unknown-module errors; block-scoped
  parameters are local to their block and take their value from their
  initializer, which may reference the module's parameters)
  ([E-87](../../enhancements_doc/Enhancement-87.md));
- **hierarchical branch probes** ([E-86](../../enhancements_doc/Enhancement-86.md)): the top module's
  absolute chain map rides into every inlined child so SIBLING bodies
  resolve `V(top.a1.b)`/`$root...` references; unnamed-branch forms
  expand to the flattened node pair; port-branch probes
  `I(inst.branch(<p>))` read a 0V ammeter synthesized at flattening
  (which also fixes child-declared `branch (<p>)` port branches, broken
  after inlining); hierarchy-bound monitor modules are omitted from
  standalone output; `ground`/net-type declarations in inlined children
  keep their keyword;
- **`$port_connected` resolved at flattening time** to a literal
  `(1)`/`(0)` per instance — after inlining, an open port is just a
  synthesized local net, so the builtin used to fail validation in
  exactly the unconnected case it exists to detect; top-level modules
  keep the native OSDI connected-flag path ([E-84](../../enhancements_doc/Enhancement-84.md)).

## 6. Definition layer — `openvaf/hir_def/` (+ `openvaf/hir/` mirrors)

`body.rs`/`body/lower.rs`/`body/pretty.rs`, `expr.rs`, `item_tree*`,
`nameres*`, `builtin.rs`, `data.rs`, `types.rs`, `db.rs`, plus the new
`item_tree/diagnostics.rs` and the `hir` façade (`body.rs`, `lib.rs`,
`db.rs`, `diagnostics.rs`):

- statement/expression collection for every new construct: `do…while`
  ([E-19](../../enhancements_doc/Enhancement-19.md)), `repeat` and
  `disable` ([E-9](../../enhancements_doc/Enhancement-9.md)), event OR
  lists ([E-59](../../enhancements_doc/Enhancement-59.md)), concat/
  replication ([E-34](../../enhancements_doc/Enhancement-34.md)), array
  aggregates and whole-array assignment
  ([E-14](../../enhancements_doc/Enhancement-14.md)), `CaseKind` + per-item
  don't-care masks with a stray-literal list
  ([E-78](../../enhancements_doc/Enhancement-78.md));
- **N-D array machinery**: per-dimension size lists, multi-index
  bit-selects, per-element parameter expansion
  ([E-15](../../enhancements_doc/Enhancement-15.md)); declaration
  initializers on (N-D) arrays via a `Var::array_index` leaf split
  ([E-43](../../enhancements_doc/Enhancement-43.md));
- **`localparam`** made genuinely non-overridable (it behaved exactly
  like `parameter`) with derived localparams still tracking inputs
  ([E-9](../../enhancements_doc/Enhancement-9.md)); paramset lowering as
  twin modules whose bound params are localparams with override
  expressions ([E-21](../../enhancements_doc/Enhancement-21.md));
- **name resolution**: `electrical ground gnd;` ordering
  ([E-9](../../enhancements_doc/Enhancement-9.md)), nature-attribute access
  (`net.potential.abstol` — the third "scaffolded-but-unwired resolver
  boundary" found) ([E-45](../../enhancements_doc/Enhancement-45.md)),
  derived-nature resolution
  ([E-39](../../enhancements_doc/Enhancement-39.md));
- **`builtin.rs`** (the system-function registry): the noise-table pair
  ([E-9](../../enhancements_doc/Enhancement-9.md)), the full
  `$random`/`$dist_*`/`$rdist_*` family
  ([E-10](../../enhancements_doc/Enhancement-10.md)), file I/O and string
  functions ([E-11](../../enhancements_doc/Enhancement-11.md)), the last
  fallback group (`$simprobe`, aliases, plusargs) — after which
  `is_unsupported()` is empty
  ([E-12](../../enhancements_doc/Enhancement-12.md)), `$simparam$str`
  ([E-25](../../enhancements_doc/Enhancement-25.md)), `$realtime`
  ([E-59](../../enhancements_doc/Enhancement-59.md)), `$table_model`
  ([E-16](../../enhancements_doc/Enhancement-16.md));
- **new diagnostics file**: wrong-arity calls produced invalid HIR and
  crashed downstream — now a proper diagnostic (functions and parameters
  both) ([E-43](../../enhancements_doc/Enhancement-43.md));
- multiple `analog` blocks collect into `entry_stmts` in source order —
  the as-if-concatenated LRM semantics, by construction
  ([E-60](../../enhancements_doc/Enhancement-60.md));
- **bus-port node ordering** (`item_tree/lower.rs`): a non-ANSI header
  bus port (`module m(in, y); input [0:2] in;`) had its first bit merged
  into the header placeholder but the remaining bits appended after later
  ports, scrambling OSDI terminal order whenever the bus was not the last
  port. A pre-scan of body port widths now expands the bus into contiguous
  bits in header order at placeholder-creation time
  ([E-90](../../enhancements_doc/Enhancement-90.md)).

## 7. Types and validation — `openvaf/hir_ty/`

`inference.rs` (+ `inference/fmt_parser.rs`), `builtin.rs` +
`builtin/generated.rs` (signature tables), `lower.rs`, `types.rs`,
`validation.rs`, `validation/body.rs`, `diagnostics.rs`:

- **signature tables** — a recurring defect source: `ANALYSIS` made
  variadic ([E-30](../../enhancements_doc/Enhancement-30.md));
  `$table_model` given shape-synthesized varargs signatures for any
  dimension (a generic-varargs fallthrough *truncated* multi-arity
  signature lists — varargs builtins with signature lists need their own
  inference arm) ([E-40](../../enhancements_doc/Enhancement-40.md));
  `TRANSITION`'s table was one argument short (3-argument calls crashed,
  4-argument worked by accident)
  ([E-47](../../enhancements_doc/Enhancement-47.md)); `transition()` input
  typed Real, a `$dist` typo fixed
  ([E-49](../../enhancements_doc/Enhancement-49.md));
  `SIMPARAM_STR` returned Real instead of String
  ([E-25](../../enhancements_doc/Enhancement-25.md));
- **format-string inference** (`fmt_parser.rs`): terminates on every
  conversion character and reports it, so `%5d`/`%-8s`/`%08x` type their
  arguments correctly — previously only real conversions accepted
  flags/width ([E-71](../../enhancements_doc/Enhancement-71.md));
- **array inference**: element-wise array `case`, array-literal function
  arguments (which previously bound nothing and silently returned 0),
  integer arrays typed Real, output-literal args accepted silently — all
  fixed ([E-33](../../enhancements_doc/Enhancement-33.md)); whole-array
  function arguments/outputs/returns
  ([E-18](../../enhancements_doc/Enhancement-18.md), [E-20](../../enhancements_doc/Enhancement-20.md), [E-23](../../enhancements_doc/Enhancement-23.md));
  untyped function args default to Real instead of an ICE masquerading
  as an initializer bug ([E-43](../../enhancements_doc/Enhancement-43.md));
- **`Type::base_type` infinite loop** on any array-type check (it looped
  on `self` instead of the cursor) — hung the compiler on simple type
  mismatches ([E-14](../../enhancements_doc/Enhancement-14.md));
- **string handling**: ternary over strings (SELECT + string binary ops
  appended to the operator tables)
  ([E-37](../../enhancements_doc/Enhancement-37.md));
- **validation**: loop bodies get their own context so the
  analog-operator restriction reports "loops" (LRM 4.5.1), not
  "conditions" ([E-70](../../enhancements_doc/Enhancement-70.md));
  call-graph cycles among analog functions are clean errors naming the
  cycle instead of a recursive-inliner stack overflow
  ([E-59](../../enhancements_doc/Enhancement-59.md)); casex/casez
  restrictions (stray don't-care literals, `x` digits under `casez`,
  non-integer discriminants)
  ([E-78](../../enhancements_doc/Enhancement-78.md)); `domain discrete`
  with natures rejected per LRM 3.6.2.2
  ([E-50](../../enhancements_doc/Enhancement-50.md)); parameter **defaults
  exempt from their own ranges** (the CMC "feature disabled" idiom —
  stock rejected diode_cmc, BSIM-CMG, PSP-HV and the HiSIM family at
  setup) while given values stay fully validated
  ([E-56](../../enhancements_doc/Enhancement-56.md));
- **part-selects outside port connections diagnosed** (the E-78
  stray-list pattern: body lowering collects them, validation reports
  a dedicated error naming the supported connection form)
  ([E-85](../../enhancements_doc/Enhancement-85.md));
- **contributions to port branches diagnosed** (`ContributeToPortFlow`,
  with the declaration site labeled): `I(pb) <+ …` on a
  `branch (<p>) pb;` slipped through the write path unvalidated and
  panicked during lowering ([E-84](../../enhancements_doc/Enhancement-84.md));
- **contributions to an all-`ground` branch diagnosed**
  (`ContributeToGround`): `V(gnd) <+ …` / `V(gnd, gnd) <+ …` reduce both
  endpoints to the fixed 0 reference (no unknown) and hit an
  `unreachable!()` in `lower_contribute_unnamed_branch` — an ICE. The write
  path now checks the branch's `is_gnd` nodes and reports a clean error; a
  real node-to-ground branch and a `V(gnd)` probe are untouched
  ([E-97](../../enhancements_doc/Enhancement-97.md)).

## 8. Lowering — `openvaf/hir_lower/`

`expr.rs`, `stmt.rs`, `ctx.rs`, `callbacks.rs`, `parameters.rs`,
`state.rs`, `fmt.rs`, `lib.rs`:

- **analog operators**: `laplace_nd/np/zd/zp` via exact state-space
  realization ([E-4](../../enhancements_doc/Enhancement-4.md)) with complex
  pole/zero pairs per the LRM's (re, im) convention
  ([E-31](../../enhancements_doc/Enhancement-31.md)); `zi_*` via bilinear
  transform ([E-6](../../enhancements_doc/Enhancement-6.md));
  `slew`/`transition` as a saturating tracking loop
  ([E-6](../../enhancements_doc/Enhancement-6.md)) with the LRM negative
  `max_neg_rate` convention honored (the sign defect made `slew` ignore
  its input and ramp away)
  ([E-61](../../enhancements_doc/Enhancement-61.md)) and a DC-singularity
  clamp via an `EnableIntegration` identity
  ([E-47](../../enhancements_doc/Enhancement-47.md)); `idtmod`'s modulo
  wrap moved off the reactive residual (it diverged) and an argument-
  index bug fixed ([E-27](../../enhancements_doc/Enhancement-27.md));
  `idt` initial conditions survive into transient
  ([E-28](../../enhancements_doc/Enhancement-28.md)); the `idt`
  assert/reset forms with smooth reset dynamics
  ([E-52](../../enhancements_doc/Enhancement-52.md)); `limexp` kept
  stateless as a documented decision
  ([E-13](../../enhancements_doc/Enhancement-13.md));
- **`$table_model`**: 1-D piecewise-linear lowered to differentiable MIR
  so autodiff yields the Jacobian for free
  ([E-16](../../enhancements_doc/Enhancement-16.md)); N-D multilinear as
  recursive 1-D ([E-17](../../enhancements_doc/Enhancement-17.md),
  [E-40](../../enhancements_doc/Enhancement-40.md)); natural cubic splines
  with the precomputed moment matrix
  ([E-22](../../enhancements_doc/Enhancement-22.md));
- **events**: `cross`/`above`/`timer` with persistent previous-value
  slots ([E-8](../../enhancements_doc/Enhancement-8.md)); OR lists folded
  with a select-based bool-or (a raw `ior` ICEs const-eval)
  ([E-59](../../enhancements_doc/Enhancement-59.md)); final-step gating and
  phase-list AND-ing ([E-53](../../enhancements_doc/Enhancement-53.md));
- **variable persistence**: genuine per-instance `hidden_state` storage
  behind a two-pass MIR build
  ([E-7](../../enhancements_doc/Enhancement-7.md)), typed slots so integer
  state stopped crashing instruction selection
  ([E-32](../../enhancements_doc/Enhancement-32.md));
- **callbacks** (`callbacks.rs`, `fmt.rs`): the `$display` family with
  the full `[flags][width][.precision]` surface and `%h/%b/%r`
  translation ([E-71](../../enhancements_doc/Enhancement-71.md)); file I/O
  and string formatting through a generalized `PrintDst` sink
  ([E-11](../../enhancements_doc/Enhancement-11.md)); the deterministic
  seed-and-salt RNG lowering
  ([E-10](../../enhancements_doc/Enhancement-10.md)); `$simparam$str`
  ([E-25](../../enhancements_doc/Enhancement-25.md)); simulation-control
  return flags ([E-55](../../enhancements_doc/Enhancement-55.md));
  `$discontinuity` ([E-24](../../enhancements_doc/Enhancement-24.md));
- **operator fixes**: unary `~` emitted arithmetic negate; the constant
  folder sign-extended `>>` where the runtime was unsigned — const and
  runtime disagreed ([E-37](../../enhancements_doc/Enhancement-37.md));
- masked casex/casez comparisons (two `iand`s ahead of the existing
  integer equality) ([E-78](../../enhancements_doc/Enhancement-78.md));
  array function-argument writeback
  ([E-20](../../enhancements_doc/Enhancement-20.md)) and array returns via
  a function-named var-array
  ([E-23](../../enhancements_doc/Enhancement-23.md));
- **named port branches** (`branch (<p>) pb;` — LRM 3.7.2): a flow probe
  of a PortFlow-kind branch routes through the same `CurrentKind::Port`
  param as a direct `I(<p>)`, so E-29's defining equation covers both
  spellings; probing one used to hit `unreachable!()`
  ([E-84](../../enhancements_doc/Enhancement-84.md));
- **literal `if` conditions lower only the taken branch** — a dead
  analog operator (`transition()` under `if ((0))`, the exact shape the
  `$port_connected` rewrite produces) survived const-folding as a
  detached-but-interned op whose state setup read optimized-away values
  and aborted codegen ([E-84](../../enhancements_doc/Enhancement-84.md)).

## 9. MIR core and optimization — `openvaf/mir*`

`mir/` (`instructions.rs` + `instructions/generated.rs`, `dfg.rs` with
`dfg/phis.rs` and `dfg/uses.rs`, `dominators.rs`, `flowgraph.rs` with
`flowgraph/transversal.rs`, `layout.rs`, `cursor.rs`, `lib.rs`,
`builder/generated.rs`), `mir_opt/` (`simplify_cfg.rs`, `simplify.rs`,
`const_eval.rs`, `global_value_numbering.rs`), `mir_autodiff/`
(`builder.rs`, `lib.rs`, `live_derivatives.rs`), `mir_llvm/`
(`builder.rs`, `intrinsics.rs`), `mir_build/`, `mir_interpret/`:

- **three pre-existing general CFG bugs**, all found via event-counter
  verification: a dangling-reference bug in unreachable-block removal, a
  multi-exit post-dominance bug in the dominator-tree builder, and a
  block-merge bug that could corrupt which block the DAE builder treated
  as the exit ([E-8](../../enhancements_doc/Enhancement-8.md));
- the **post-dominator sink-root pathology** that let dead-code
  elimination delete op-dependent `$fatal` calls (side-effecting
  callbacks under op-dependent control now stay in eval; control
  dependence computed by arm-reachability)
  ([E-55](../../enhancements_doc/Enhancement-55.md));
- `split_tainted.rs` **tolerates layout-detached branch instructions**
  (a branch whose condition const-folded has no CFG effect to taint;
  it used to unwrap and panic) ([E-84](../../enhancements_doc/Enhancement-84.md));
- const-eval agreement with runtime semantics for shifts and the
  bitwise-not fix ([E-37](../../enhancements_doc/Enhancement-37.md));
- **autodiff**: noise operators process before any `ddt` (a shared ddt
  evaluated between two noise operators silently dropped the second
  source), and the reactive coupling of a `ddt`-shaped noise wave is
  registered so small-signal pruning keeps it
  ([E-54](../../enhancements_doc/Enhancement-54.md));
- **`llvm.fabs.f64` registered** in the LLVM intrinsics table — it never
  had been, and the signed noise-power convention needed it
  ([E-42](../../enhancements_doc/Enhancement-42.md));
- new opcodes/instructions supporting the operator work (barrier/
  integration-identity forms; MIR deliberately has no `fabs`, so
  lowering composes it) ([E-47](../../enhancements_doc/Enhancement-47.md),
  [E-52](../../enhancements_doc/Enhancement-52.md)).

## 10. DAE construction — `openvaf/sim_back/`

`dae.rs` + `dae/builder.rs`, `topology*` (incl. `lineralize.rs`,
`small_signal_network.rs`), `noise.rs`, `context.rs`, `lib.rs`:

- **implicit equations** for indirect branch assignment (one new unknown
  + residual per statement)
  ([E-2](../../enhancements_doc/Enhancement-2.md)) and the absdelay
  synthetic two-node form
  ([E-1](../../enhancements_doc/Enhancement-1.md)) — with equation indices
  kept stable by mapping dead/collapsed unknowns to zero-contribution
  placeholders instead of renumbering;
- **port-flow probes `I(<port>)`**: a TODO stub returning 0 became a
  synthesized DAE unknown mirroring the node's KCL residual
  ([E-29](../../enhancements_doc/Enhancement-29.md));
- **probe-only branches**: probing a never-contributed branch read 0 and
  an open circuit — a 0 V-source pass materializes them, enabling ideal
  ammeters and flow-only signal-flow disciplines
  ([E-36](../../enhancements_doc/Enhancement-36.md));
- **noise factors** (`noise.rs`): equation-path noise was silently lost
  (never attached to the DAE); factors generalize to `re + jω·im` with
  no extra matrix unknowns
  ([E-54](../../enhancements_doc/Enhancement-54.md)); same-named source
  grouping metadata ([E-42](../../enhancements_doc/Enhancement-42.md));
- `idt` reset-mode charge dynamics and conditional step bounding
  ([E-52](../../enhancements_doc/Enhancement-52.md)).

- **voltage-source branches feeding internal nodes were open circuits
  at DC**: the small-signal (noise/`ac_stim`) pruner keyed node
  registration on the branch's LIVE voltage unknown, so a pure
  `V(a, f) <+ expr` (V(a,f) never read) registered nothing and the
  node's conduction silently moved to the AC-only residual; any
  voltage-capable branch now disqualifies its nodes
  ([E-86](../../enhancements_doc/Enhancement-86.md));
- **probed `V(x,y) <+ 0` branches were node-collapsed away**, making
  `I(branch)` read zero; hint pairs whose branch current is a DAE
  unknown are suppressed (the unprobed collapse idiom is untouched)
  and `NodeCollapse::hint` tolerates suppressed pairs; pinned by the
  permanent `vsrc_internal_node` snapshot test. Behavior change: a
  collapsible branch whose current the model references (MVSG_CMC's
  access resistances carry noise on `flow(d,drc)`) stays a real 0V
  source — electrically identical, two extra matrix rows
  ([E-86](../../enhancements_doc/Enhancement-86.md)).

## 11. OSDI code generation — `openvaf/osdi/`

`lib.rs`, `metadata.rs` + `metadata/osdi_0_4.rs`, `inst_data.rs`,
`eval.rs`, `load.rs`, `setup.rs`, `compilation_unit.rs`, `ndatable.rs`,
`stdlib.c`, `build.rs`, reference headers:

- **descriptor emission** for every ABI evolution (see the ngspice
  report's ABI table): the absdelay/last_crossing info arrays
  ([E-1](../../enhancements_doc/Enhancement-1.md), [E-6](../../enhancements_doc/Enhancement-6.md)),
  `OsdiNode.nodeset` ([E-45](../../enhancements_doc/Enhancement-45.md)),
  the `ac_stim` source array + `load_ac_stim`
  ([E-51](../../enhancements_doc/Enhancement-51.md)), stride-2 signed noise
  pairs in `load_noise`
  ([E-54](../../enhancements_doc/Enhancement-54.md)) — the version tuple
  lives in `osdi/src/lib.rs`;
- **`metadata.rs`**: the `PARA_FLAG_FIXED` parameter-descriptor flag (a free
  bit of the `flags` field, additive — no layout/ABI change) set on every
  `localparam`, so the simulator can warn when a netlist tries to set a
  non-settable parameter (a `localparam`, or a structural width parameter
  frozen by Enhancement-92) ([E-93](../../enhancements_doc/Enhancement-93.md));
- **`eval.rs`**: final-step flag gating
  ([E-53](../../enhancements_doc/Enhancement-53.md)); simulation-control
  return flags ([E-55](../../enhancements_doc/Enhancement-55.md)); the
  `ac_stim` large-signal value (was an `unreachable!()` panic)
  ([E-26](../../enhancements_doc/Enhancement-26.md));
- **`inst_data.rs`**: absdelay slot layout
  ([E-1](../../enhancements_doc/Enhancement-1.md)); hidden-state slots
  typed by the variable (`ty_f64` was hardcoded — integer state fed f64
  loads into integer MIR ops and aborted instruction selection)
  ([E-32](../../enhancements_doc/Enhancement-32.md));
- **`compilation_unit.rs`** (print codegen): the `%b` **segfault** — the
  binary-formatted string was remembered for `free()` but never pushed
  to the `snprintf` argument list, so the matching `%s` consumed a
  garbage pointer ([E-71](../../enhancements_doc/Enhancement-71.md)); the
  print-callback machinery with its shadowed-`fun` and volatile-table
  IPO traps ([E-11](../../enhancements_doc/Enhancement-11.md));
- **`stdlib.c`**: the file-descriptor table behind `$fopen`/`$fdisplay`/…
  ([E-11](../../enhancements_doc/Enhancement-11.md)); the splitmix64
  `osdi_rng_*` runtime ([E-10](../../enhancements_doc/Enhancement-10.md));
  a `simparam_str` loop/return bug
  ([E-25](../../enhancements_doc/Enhancement-25.md));
- **`ndatable.rs`**: `ddt`/`idt` natures resolved through
  `resolve_nature_index` instead of panicking on derived natures
  ([E-39](../../enhancements_doc/Enhancement-39.md));
- **`setup.rs`**: range validation with default-exemption
  ([E-56](../../enhancements_doc/Enhancement-56.md)); a 64-line abandoned
  unsafe experiment (`VoidAbortCallback`) deleted in the warning cleanup
  ([E-66](../../enhancements_doc/Enhancement-66.md));
- **`build.rs`**: the copied-target stdlib compilation trap fixed
  ([E-10](../../enhancements_doc/Enhancement-10.md)).

## 12. Driver, libraries, and infrastructure

- `openvaf-driver/src/main.rs`: **hard errors now exit non-zero** — the
  error arm printed the failure but fell through to a success exit, so
  every elaboration failure looked like a successful compile to shell
  scripts (a quirk first noticed during E-58's work)
  ([E-84](../../enhancements_doc/Enhancement-84.md));
- `openvaf-driver/src/crash_report.rs`, `linker/src/lib.rs`,
  `lib/bforest/` (`map.rs`, `pool.rs`, `set.rs`),
  `lib/typed_indexmap/` (`set.rs`): the **zero-warning cleanup**
  (44 → 0 across 13 crates: lifetime annotations, dead code, nightly
  cfgs, an unused LLVM-prefix probe)
  ([E-66](../../enhancements_doc/Enhancement-66.md));
- `basedb/` (`ast_id_map.rs`, `lints.rs`, `lib.rs`,
  `diagnostics/preprocessor_error.rs`, `diagnostics/syntax_error.rs`):
  AST-id
  plumbing for elaboration-created items (the `AstId::from_erased`
  placeholder used by array returns;
  [E-23](../../enhancements_doc/Enhancement-23.md)), preprocessor/syntax
  diagnostic rendering for the new errors;
- `.llvm-version` pins the LLVM 18 toolchain expectation; the `hir` and
  `preprocessor` `Cargo.toml`s carry the dependency additions their new
  code needed.

## 13. The test suite — `openvaf/openvaf/tests/`, `lib/mini_harness/`, `test_data/`, `integration_tests/`

The fork's own integration suite over real compact models had **never
run in this project**: its OSDI loader was frozen at ABI 0.4, its
optional VACASK legs panicked on a never-initialized submodule, and the
tests hide behind `RUN_DEV_TESTS=1`. Fixed test-side only
([E-68](../../enhancements_doc/Enhancement-68.md)):

- `tests/load/osdi_0_4.rs` + `load/mod.rs`: loader structs synced to
  ABI 0.7; `mock_sim/mod.rs`: stride-2 noise convention;
  `mini_harness`: missing directories skip with a note instead of
  panicking;
- **VACASK removed entirely** (`.gitmodules`, the submodule, 34 harness
  legs and their stale snapshots): AGPL-3.0 cannot be vendored here;
- `test_data/` (95 files as a class): new fixtures for new features and
  snapshots regenerated whenever descriptor contents legitimately
  changed — every regeneration reviewed (the diffs are the project's own
  features: `flow(<port>)` unknowns, probe-only branches,
  implicit-equation nodes); `integration_tests/*/​*.osdi` regenerated at
  each ABI bump.

---

## 14. Per-enhancement index (compiler-touching enhancements)

| Enhancement | Pipeline areas | One line |
|---|---|---|
| [E-1](../../enhancements_doc/Enhancement-1.md) | sim_back, osdi | `absdelay()` synthetic-node DAE + descriptor arrays |
| [E-2](../../enhancements_doc/Enhancement-2.md) | parser→hir_lower, sim_back | indirect branch assignment (implicit equations) |
| [E-3](../../enhancements_doc/Enhancement-3.md) | parser, hir_def | vectored (bus) nets with bit-selects |
| [E-4](../../enhancements_doc/Enhancement-4.md) | hir_lower, syntax, parser | `laplace_*` state-space + array-literal parsing |
| [E-5](../../enhancements_doc/Enhancement-5.md) | elaborate.rs (new), parser | module instantiation via compile-time flattening |
| [E-6](../../enhancements_doc/Enhancement-6.md) | preprocessor, parser, hir_lower, osdi | directives, shifts, slew/transition, zi_*, last_crossing |
| [E-7](../../enhancements_doc/Enhancement-7.md) | hir_lower (state), osdi | `@(initial_step)` gating + variable persistence |
| [E-8](../../enhancements_doc/Enhancement-8.md) | parser, elaborate, hir_lower, **mir/mir_opt** | generate for + events; three general CFG bug fixes |
| [E-9](../../enhancements_doc/Enhancement-9.md) | hir_def, hir_lower, sim_back | noise tables; localparam/ground/strings; repeat/disable |
| [E-10](../../enhancements_doc/Enhancement-10.md) | hir_lower, osdi stdlib | `$random`/`$dist_*` deterministic RNG |
| [E-11](../../enhancements_doc/Enhancement-11.md) | hir_lower, osdi | file I/O + string functions (PrintDst) |
| [E-12](../../enhancements_doc/Enhancement-12.md) | hir_def, hir_lower | last unsupported builtins as LRM fallbacks |
| [E-13](../../enhancements_doc/Enhancement-13.md) | hir_lower | `limexp` kept stateless (documented decision) |
| [E-14](../../enhancements_doc/Enhancement-14.md) | hir_def, hir_ty, hir_lower | array literals/params/dynamic indexing; base_type hang |
| [E-15](../../enhancements_doc/Enhancement-15.md) | hir_def, hir_ty, hir_lower | N-D arrays |
| [E-16](../../enhancements_doc/Enhancement-16.md)/[17](../../enhancements_doc/Enhancement-17.md)/[22](../../enhancements_doc/Enhancement-22.md)/[40](../../enhancements_doc/Enhancement-40.md) | hir_ty, hir_lower | `$table_model`: 1-D, N-D multilinear, cubic spline, varargs sigs |
| [E-18](../../enhancements_doc/Enhancement-18.md)/[20](../../enhancements_doc/Enhancement-20.md)/[23](../../enhancements_doc/Enhancement-23.md)/[33](../../enhancements_doc/Enhancement-33.md) | hir_ty, hir_lower, basedb | arrays in analog functions: in/out/return/literals + array case |
| [E-19](../../enhancements_doc/Enhancement-19.md) | tokens→hir_lower | `do … while` |
| [E-21](../../enhancements_doc/Enhancement-21.md)/[44](../../enhancements_doc/Enhancement-44.md) | parser, elaborate, hir_def, sim_back | paramset + hidden system parameters |
| [E-24](../../enhancements_doc/Enhancement-24.md)/[55](../../enhancements_doc/Enhancement-55.md) | hir_lower, mir, osdi | `$discontinuity`; `$finish`/`$stop`/`$fatal` honored |
| [E-25](../../enhancements_doc/Enhancement-25.md) | hir_ty, osdi stdlib | `$simparam$str` |
| [E-26](../../enhancements_doc/Enhancement-26.md)/[51](../../enhancements_doc/Enhancement-51.md) | osdi, sim_back | `ac_stim`: crash fix, then full AC-RHS injection |
| [E-27](../../enhancements_doc/Enhancement-27.md)/[28](../../enhancements_doc/Enhancement-28.md)/[52](../../enhancements_doc/Enhancement-52.md) | hir_lower, sim_back | the `idt` family: modulo, IC, assert/reset |
| [E-29](../../enhancements_doc/Enhancement-29.md)/[36](../../enhancements_doc/Enhancement-36.md) | sim_back | port-flow probes; probe-only branches |
| [E-30](../../enhancements_doc/Enhancement-30.md) | hir_ty, hir_lower | variadic `analysis()` |
| [E-31](../../enhancements_doc/Enhancement-31.md) | hir_lower | complex poles/zeros in root forms |
| [E-32](../../enhancements_doc/Enhancement-32.md) | osdi inst_data | integer persistent state (crash fix) |
| [E-34](../../enhancements_doc/Enhancement-34.md) | tokens→hir_lower | `{…}` concat + `{n{…}}` replication |
| [E-35](../../enhancements_doc/Enhancement-35.md) | lexer | EOF comment hang |
| [E-37](../../enhancements_doc/Enhancement-37.md)/[38](../../enhancements_doc/Enhancement-38.md) | hir_lower, mir_opt, parser | operator + precedence audits (`~`, `>>` fold, `%` level) |
| [E-39](../../enhancements_doc/Enhancement-39.md) | parser, hir_ty, osdi | derived natures unwired at the node-kind boundary |
| [E-41](../../enhancements_doc/Enhancement-41.md)/[49](../../enhancements_doc/Enhancement-49.md)/[58](../../enhancements_doc/Enhancement-58.md)/[59](../../enhancements_doc/Enhancement-59.md) | elaborate | implicit nets; hierarchical names; defparam; port concat + OR lists |
| [E-42](../../enhancements_doc/Enhancement-42.md)/[54](../../enhancements_doc/Enhancement-54.md) | sim_back noise, mir_autodiff, mir_llvm, osdi | correlated + node-free complex noise factors |
| [E-43](../../enhancements_doc/Enhancement-43.md) | hir_def (+diagnostics), hir_ty | initializers completed; arity diagnostics |
| [E-45](../../enhancements_doc/Enhancement-45.md) | osdi, hir_def, elaborate | nodesets + nature-attribute access (ABI 0.5) |
| [E-46](../../enhancements_doc/Enhancement-46.md)/[48](../../enhancements_doc/Enhancement-48.md) | lexer, syntax | escaped ids, based literals, single-pass unescaper |
| [E-47](../../enhancements_doc/Enhancement-47.md) | preprocessor, hir_ty, hir_lower | `` `default_transition `` + transition fixes |
| [E-50](../../enhancements_doc/Enhancement-50.md) | hir_ty validation | domain-binding validation |
| [E-53](../../enhancements_doc/Enhancement-53.md) | hir_lower, osdi eval | `@(final_step)` + phase lists |
| [E-56](../../enhancements_doc/Enhancement-56.md) | hir_ty, osdi setup | parameter defaults exempt from ranges |
| [E-59](../../enhancements_doc/Enhancement-59.md) | tokens→hir_lower, hir_ty | `$realtime`; OR lists; recursion diagnostics |
| [E-61](../../enhancements_doc/Enhancement-61.md) | hir_lower | `slew` sign fix (operator-args audit) |
| [E-65](../../enhancements_doc/Enhancement-65.md) | preprocessor | macro-recursion guard |
| [E-66](../../enhancements_doc/Enhancement-66.md) | 13 crates | zero-warning cleanup (44 → 0) |
| [E-67](../../enhancements_doc/Enhancement-67.md) | tokens, parser, syntax, elaborate | generate audit: genvar fix, nesting, if/case |
| [E-68](../../enhancements_doc/Enhancement-68.md) | tests, mini_harness | integration suite enabled; VACASK removed |
| [E-70](../../enhancements_doc/Enhancement-70.md) | hir_ty validation | loop-context diagnostics |
| [E-71](../../enhancements_doc/Enhancement-71.md) | hir_ty fmt, hir_lower fmt, osdi | display-format surface + `%b` segfault |
| [E-78](../../enhancements_doc/Enhancement-78.md) | lexer→hir_lower, hir_ty | `casex`/`casez` don't-care masks |
| [E-84](../../enhancements_doc/Enhancement-84.md) | parser, elaborate, hir_ty, hir_lower, mir_opt, driver | LRM example sweep: 6 defect fixes (port-branch panic, parser robustness, silent undefined modules, `$port_connected` on open ports, dead-op codegen, exit codes) |
| [E-85](../../enhancements_doc/Enhancement-85.md) | parser, elaborate, hir_def, hir_ty | `` `__FILE__``/`` `__LINE__`` + connection part-selects (the last two sweep findings) |
| [E-86](../../enhancements_doc/Enhancement-86.md) | parser, elaborate, **sim_back** | hierarchical branch probes + 2 DAE fixes (V-source-to-internal open circuit, collapse-of-probed-branch) |
| [E-87](../../enhancements_doc/Enhancement-87.md) | parser, elaborate | block-scoped parameters (validated) + clean diagnostic for the illegal `#(.blk.p())` override |
| [E-88](../../enhancements_doc/Enhancement-88.md) | elaborate | legacy `generate <id> (start,end)` analog-block loop-unroll (textual pre-pass) |
| [E-89](../../enhancements_doc/Enhancement-89.md) | elaborate | name-then-range net/port decls (textual normalize) + Annex E SPICE-primitives example library |
| [E-90](../../enhancements_doc/Enhancement-90.md) | hir_def (item_tree) | multi-bit input bus port bit reads: pre-scan body widths so a non-last bus port's bits stay contiguous in header/terminal order |
| [E-91](../../enhancements_doc/Enhancement-91.md) | elaborate | multi-name name-then-range declarations + parameter-dependent declaration widths (folded from the parameter default) |
| [E-92](../../enhancements_doc/Enhancement-92.md) | elaborate | freeze structural (width) parameters to `localparam` (split multi-parameter decls) so a netlist override cannot desync the frozen width from behaviour |
| [E-93](../../enhancements_doc/Enhancement-93.md) | osdi (metadata) | flag `localparam` OSDI parameters non-settable (`PARA_FLAG_FIXED`, additive) so ngspice can warn on a netlist override (ngspice side too) |
| [E-96](../../enhancements_doc/Enhancement-96.md) | parser (module grammar) | parse a module-level `generate for`/`if`/`case` without the optional `generate`/`endgenerate` keywords |
| [E-97](../../enhancements_doc/Enhancement-97.md) | hir_ty (validation) | clean diagnostic (was an ICE) for a contribution to an all-`ground` branch (`V(gnd) <+ …`) |
| [E-101](../../enhancements_doc/Enhancement-101.md) | hir_ty (builtin), mir_opt / mir_interpret / mir_llvm | `$clog2`: accept one argument (`INT_MATH_1`, was a 2-arg signature) and compute `ceil(log2 n)` = `bit_width(n-1)` in all three backends (was `floor(log2 n)+1`, wrong on exact powers of two) |
| [E-102](../../enhancements_doc/Enhancement-102.md) | parser (items), syntax (ungrammar + ast), hir_def (item_tree) | name-then-range array-valued parameters (`parameter real c[0:2]`); `parameter()` accepts post-name `[range]`, `lower_param` resolves dims per name |
| [E-103](../../enhancements_doc/Enhancement-103.md) | mir_llvm (intrinsics) | register the `llvm.ceil.f64` intrinsic (was missing; `ceil()` of a non-constant argument crashed codegen -- `floor` was registered) |
| [E-104](../../enhancements_doc/Enhancement-104.md) | syntax (name), hir_def (builtin), hir_ty (builtin), hir_lower (expr) | add `$rtoi` (real->int, truncate toward zero via `ficast((x<0)?ceil:floor)`) and `$itor` (int->real) conversion builtins |
| [E-105](../../enhancements_doc/Enhancement-105.md) | hir_lower (expr, callbacks), osdi (compilation_unit, stdlib.c) | `$sscanf`/`$fscanf` honour the format conversion base -- parse the format string, dispatch integer fields to base-specific scanners (`%h`/`%x` hex, `%o` octal, `%b` binary) |
| [E-106](../../enhancements_doc/Enhancement-106.md) | hir_ty (types, inference), hir (signatures), hir_lower (expr, callbacks), osdi (compilation_unit, stdlib.c) | string relational comparison (`<`/`<=`/`>`/`>=`) via a lexicographic `osdi_strcmp` callback (`RELATIONAL_COMPARISON` adds the STR signature; `a<op>b` lowers to `strcmp(a,b)<op>0`) |
| [E-107](../../enhancements_doc/Enhancement-107.md) | syntax (name), hir_def (builtin), hir_ty (builtin), hir_lower (expr, callbacks), osdi (stdlib.c) | add `$fgetc(fd)` single-character read as a `FileOp::Getc` -> `osdi_fgetc` (completes the file I/O family) |
| [E-108](../../enhancements_doc/Enhancement-108.md) | syntax (name), hir_def (builtin), hir_ty (builtin), hir_lower (expr, callbacks), osdi (stdlib.c) | add `$ungetc(c, fd)` one-character pushback as a 2-arg `FileOp::Ungetc` -> `osdi_ungetc` (companion to `$fgetc`) |
| [E-109](../../enhancements_doc/Enhancement-109.md) | hir_lower (callbacks), osdi (load) | correct `noise_table` (piecewise-linear in `f`) and `noise_table_log` (log-log, `P=10^lerp(log10 p, log10 f)`) interpolation to LRM 4.6.4.3/4.6.4.4 -- both were nonconformant (lin-log, and a mis-keyed log-freq input) |

Enhancements not listed (57, 60, 62–64, 69, 72–77, 79–83, 94–95, 98–100) changed no
compiler sources — they were validation suites, documentation, benchmark
tooling, or ngspice-side work (see the
[ngspice report](ngspice_changes_full-report.md)).
