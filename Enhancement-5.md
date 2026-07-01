# Enhancement-5 — Verilog-A Module Instantiation in OpenVAF (version6)

This document describes every source-code change made to **OpenVAF** in the
`version6/` directory, on top of `version5/` (Enhancement-4, Laplace-domain
transfer-function operators), to implement **Verilog-A module
instantiation** — one module placing other modules as sub-circuit elements
on its own nets, e.g.:

```verilog
module resistor(p, n);
    inout p, n;
    electrical p, n;
    parameter real r = 1000;
    analog begin
        I(p, n) <+ V(p, n) / r;
    end
endmodule

module divider(in, out, gnd);
    inout in, out, gnd;
    electrical in, out, gnd;
    resistor #(.r(1e3)) r1(in, out);
    resistor #(2e3) r2(.p(out), .n(gnd));
    resistor rarr[0:1](out, gnd);
endmodule
```

Full feature scope, confirmed up front with the user ("full support and
implementation", not a cut-down v1):

- Both **positional** (`resistor r1(in, out);`) and **named**
  (`resistor r1(.p(in), .n(out));`) port connections, including **open
  ports** (`inst(a, , c);` — a blank slot leaves that port internally
  floating).
- Both **positional** (`#(1e3, 2e3)`) and **named** (`#(.r(1e3))`)
  parameter overrides.
- **Instance arrays** (`resistor rarr[0:3](out, gnd);`), expanding to N
  independent instances at compile time.
- **Arbitrary nesting depth** (a module instantiating a module
  instantiating a module, ...).
- **Cyclic instantiation is a hard compile error**, diagnosed by name
  (not a stack overflow).

---

## 1. What was actually there already (and what wasn't)

Unlike Enhancement-4's `laplace_*` operators (front-end-complete but
lowering-incomplete), module instantiation had **zero support anywhere** in
the compiler before this enhancement:

- The grammar's `ModuleItem` production (`openvaf/syntax/veriloga.ungram`)
  had exactly 7 variants (`BodyPortDecl`, `NetDecl`, `AnalogBehaviour`,
  `Function`, `BranchDecl`, `VarDecl`, `ParamDecl`, `AliasParam`) — no
  instantiation form, and no parser code path for it either.
- `hir::ScopeDef::ModuleInstance(Module)` existed but was dead code from a
  user's perspective: it's only ever produced for **top-level module
  declarations** (`ScopeDefItem::ModuleId` in the root scope), never for an
  actual instantiation statement, because no such statement could be
  parsed.
- Everything downstream of `hir_def` — `hir_ty`, `hir_lower`, `mir*`,
  `sim_back::DaeSystem`, `osdi::OsdiDescriptor` — is architected around
  **exactly one flat module per compiled artifact**: per-module-local node
  IDs (`LocalNodeId = Idx<Node>`), one `DaeSystem` built per module, one
  flat node/parameter/Jacobian table per OSDI descriptor. There is no
  composition/nesting primitive anywhere in that stack, and building one
  would mean risky, invasive surgery through the entire backend.
- No TODOs, comments, or partial scaffolding anywhere suggested hierarchy
  was ever planned.

### 1.1 Why this isn't solved with a CST/HIR-level splice

The first design instinct — clone the sub-module's parsed syntax subtree,
rename its identifiers, and splice it into the parent's tree before
`hir_def` runs — **does not work with this codebase's architecture**.
Every layer that consumes syntax (`basedb::AstIdMap`, `hir_def::ItemTree`,
`hir_def::body::Body::body_with_sourcemap_query`, lint/diagnostic
collection) independently re-derives its input from `db.parse(root_file)`,
keyed purely by `FileId`, using `(TextRange, SyntaxKind)` pointers into
*that one real parse*. There is no seam to hand a mutated/spliced tree to
all of those consumers at once — a change made at one layer (e.g. after
parsing) is invisible to every other layer, which independently re-parses
the *original* file text.

**The only mechanism consistent with this architecture is text-level
elaboration**: synthesize a fully flattened Verilog-A source for any module
that contains instantiation statements — inlining each instantiated
module's own declarations, alpha-renamed per instance, with ports bound to
the caller's net expressions and parameters bound to the caller's override
expressions — register that synthesized text as a new file, and feed *that*
through the **entirely unmodified** parse → `hir_def` → `hir_ty` →
`hir_lower` → `mir*` → `sim_back` → `osdi` pipeline. This is conceptually
the same trick SPICE simulators use for `.subckt`/`X`-instance expansion.

---

## Part 1: Grammar and parser (`openvaf/syntax`, `openvaf/parser`, `sourcegen`)

### 2. New grammar productions

`openvaf/syntax/veriloga.ungram` gained a `ModuleItem` variant and five
supporting rules:

```
Instantiation =
  AttrList* module:NameRef ParamOverrides?
  (InstanceUnit (',' InstanceUnit)*) ';'

ParamOverrides =
  '#' '(' (ParamAssign (',' ParamAssign)*)? ')'

ParamAssign =
  ('.' name:Name '(' val:Expr ')') | val:Expr

InstanceUnit =
  name:Name width:Range? PortConns

PortConns =
  '(' (PortConn (',' PortConn)*)? ')'

PortConn =
  ('.' name:Name '(' net:Expr ')') | net:Expr
```

`Range` (the `[msb:lsb]` clause) is reused verbatim from Enhancement-3/4's
vectored-net support for instance-array ranges. `PortConn`/`ParamAssign`
each produce a single AST node with two independently-optional fields
(`name`, `net`/`val`) rather than a named/positional enum — a bare
`PortConn` with neither field present represents an **open/unconnected
port** (an empty slot between commas, e.g. `inst(a, , c)`).

New `SyntaxKind`s (`INSTANTIATION`, `PARAM_OVERRIDES`, `PARAM_ASSIGN`,
`INSTANCE_UNIT`, `PORT_CONNS`, `PORT_CONN`) were registered in
`sourcegen/src/ast/src.rs`'s `KindsSrc::nodes` list; running
`cargo test -p sourcegen ast` regenerated
`openvaf/tokens/src/parser/generated.rs` and
`openvaf/syntax/src/ast/generated/{nodes,tokens}.rs` from the updated
ungram (standard workflow in this codebase — the test writes the files and
fails once, then passes on the immediate re-run).

### 3. Parser disambiguation

`openvaf/parser/src/grammar/items/module.rs`'s `module_items()` dispatch
previously sent every bare `IDENT` unconditionally to `net_decl::<false>`
(a discipline-name-first net declaration, e.g. `electrical p, n;`). Module
instantiation (`resistor r1(in, out);`) also starts with a bare `IDENT`, so
a 2-token lookahead disambiguates the two, added as a new `is_instantiation`
guard before the existing `IDENT` arm:

- `#` immediately after the first identifier is an unambiguous
  instantiation signal (`resistor #(...) r1(...)`) — net declarations never
  contain `#`.
- Otherwise: a second `IDENT` followed by `(` or `[` (instance ports, or an
  instance-array range) means instantiation; followed by `,`/`;` means an
  ordinary (possibly single-net) net declaration.

This is exact and requires no backtracking. `instantiation()`,
`param_assign()`, `instance_unit()`, `port_conns()`, and `port_conn()` were
added to `module.rs` mirroring the existing `branch_decl`/`net_decl`
parsing style.

---

## Part 2: `hir_def` item tree, name resolution, diagnostics

### 4. Item tree representation

`openvaf/hir_def/src/item_tree.rs` gained `ModuleItem::Instantiation` and a
new `Instantiation` item-tree node:

```rust
pub struct Instantiation {
    pub name: Name,           // instance name (or synthesized "r[2]" for an array element)
    pub unit_idx: usize,      // which comma-separated InstanceUnit this is
    pub array_index: Option<i32>,
    pub module: Name,         // referenced module name, unresolved
    pub ast_id: AstId<ast::Instantiation>,
}
```

One `Instantiation` entry is created per array element (mirroring how
`Net`/`Var`/`Param` handle comma-separated declarations — all names from
one source statement share an `ast_id`, disambiguated by index), reusing
`bus_bit_name`/`fold_width_range` from Enhancement-4's bus-range folding
for the `[msb:lsb]` instance-array expansion. Deliberately **not** captured
here: port/parameter binding details — those are read straight from the
AST (via `ast_id`) by name resolution and by the elaboration pass, exactly
like how `Net`/`Port` only cache their discipline in the item tree and
leave everything else to the AST.

### 5. Name resolution (`openvaf/hir_def/src/nameres/collect.rs`)

Module instantiation needed the collector to change from a **single
forward pass** to **two passes**: originally, `collect_root_map()` called
`collect_module()` once per module in file order, which both registered
the module's name in the root scope *and* processed its internal items in
the same step. A module instantiating another module declared **later** in
the same file would then fail to resolve, purely because of a body/root
collector ordering, not a Verilog-A semantic. Fixed by splitting
`collect_module` into `predeclare_module` (registers every module's name
and opens its scope) and `collect_module_items` (processes internal items,
including instantiation resolution), and running all predeclarations
before any item collection.

Each instantiation is resolved against the (now fully predeclared) root
scope, producing a new `ScopeDefItem::InstantiationId(InstantiationId)` —
deliberately **not** reusing `ScopeDef::ModuleInstance`, which represents a
module *definition*; an instantiation is a *use*. `InstantiationId`/
`InstantiationLoc` follow the exact `impl_intern!` pattern already used for
`BranchId`/`FunctionId`/etc.

### 6. New diagnostics

A DFS with a 3-color visiting-set over the file's instantiation graph
detects cycles (`DefDiagnostic::CyclicInstantiation`) before any per-site
resolution runs, so a self-/mutually-recursive instantiation is a clean
compile error rather than infinite recursion. Per-instantiation-site
diagnostics (checked once per distinct `InstanceUnit`, not once per array
element, to avoid N duplicate reports for an N-wide array) resolve against
the target module's own item tree, no flattening required:

- `UnknownInstantiatedModule` — referenced module doesn't exist in the file.
- `InstancePortCountMismatch` — positional port list length ≠ target's port count.
- `UnknownInstancePort` — a named `.port(net)` names a port the target doesn't have.
- `UnknownInstanceParam` — a named `.param(value)` names a parameter the target doesn't have.
- `TooManyInstanceParams` — more positional overrides than the target has parameters.

All five are `hir_def::nameres::diagnostics::DefDiagnostic` variants (the
existing channel used for `AlreadyDeclared`), rendered through the same
`Diagnostic`/`Report` machinery as every other compiler error.

---

## Part 3: Elaboration — the text-flattening pass (`openvaf/hir/src/elaborate.rs`)

### 7. Where it runs

`elaborate_instantiations(db: &mut CompilationDB)` runs once, as ordinary
Rust code, at the very end of `CompilationDB::new` (`openvaf/hir/src/db.rs`)
— **not** as a salsa query hooked into the `preprocess`/`parse` chain (that
was the original plan; direct inspection of `AstIdMap`/`item_tree`/
`body_with_sourcemap_query`, which all independently call
`db.parse(root_file)`, showed there's no query-graph seam to intercept —
see §1.1). Instead:

1. Cheap fast path: `db.item_tree(root_file)` is checked for **any**
   `ModuleItem::Instantiation` anywhere in the file; if none, return
   immediately. This keeps the pass a true no-op (one item-tree lookup) for
   the overwhelming majority of `.va` files, which never use the feature.
2. If `def_map.diagnostics` already contains a `CyclicInstantiation`
   diagnostic, skip elaboration entirely (a cyclic graph can't be
   flattened — recursing would never terminate) and let the normal
   diagnostic-printing path surface the cycle against the *original* file.
3. Otherwise, walk the root file's already-parsed `SourceFile::items()`;
   for each `ModuleDecl`, `flatten_top_level_module` produces its final
   text (verbatim, unless it directly contains an instantiation).
4. The concatenated result is registered as a new virtual file via
   `Vfs::add_virt_file`, the original file's `include_dirs`/`macro_flags`/
   `global_lint_overwrites` salsa inputs are copied onto the new `FileId`
   (they're per-`FileId` inputs, so the synthetic file needs its own copies
   to behave identically to the real one), and `CompilationDB::root_file`
   is redirected to it via a new `pub(crate) fn set_root_file`.

Everything from `hir_def::item_tree` onward — `hir_ty`, `hir_lower`,
`mir*`, `sim_back`, `osdi`, `mir_llvm` — required **zero changes**: they
simply compile what looks like an ordinary, hand-written flat module.

### 8. How flattening actually works

`render_with_holes(text, holes, scope)` is the one primitive everything
else is built from: it tokenizes `text` (via the existing `lexer` crate),
rewrites `SimpleIdent` tokens using an exact-match `scope.subst:
HashMap<String, String>`, and — for each `(byte_range, replacement)` in
`holes` — emits the replacement verbatim instead of individually
inspecting the tokens inside that range. That last property is what makes
composing renamed scopes correct: an already-fully-resolved nested
instance's text, or an override expression written in a caller's scope, is
never accidentally re-renamed using the wrong module's `subst` map,
because the tokenizer never looks inside a hole.

`scope: Scope` bundles two things: `subst` (plain whole-identifier
renames) and `bus_ports: HashMap<Name, BTreeMap<i32, String>>` (bus-typed
ports — see below). `render_with_holes` always starts by computing bus-port
holes via `find_bus_port_holes` and merging them with whatever holes the
caller already had, before doing the token pass.

Rendering one instantiated module (`render_instance_content`) builds a
`Scope` covering every name the target module itself declares:

- **Scalar ports** are bound to the caller's connected net text (already
  resolved at the *caller's* level — see "resolve, then recurse" below),
  or, if left open, get a fresh internal net (`{prefix}open__{port}`,
  redeclared with the port's own discipline) — inserted into `scope.subst`.
- **Bus-typed ports** need a fundamentally different mechanism: an
  ordinary rename (`p` → `prefix__p`) is one whole-token substitution, but
  a bus port's bit 0 and bit 1 need to become *different* identities, and
  the source text only ever contains the bare base identifier with the
  bit-select as separate tokens right after it — there's no single token
  to hang a per-bit answer on. These go into `scope.bus_ports[base]`
  instead: a per-bit map, each bit either the caller's binding (itself
  possibly *sliced* from a caller-scope bus of matching width — see below)
  or a freshly declared net if left open. `find_bus_port_holes` then scans
  for `ident '[' int_literal ']'` token sequences matching a `bus_ports`
  base name and replaces the whole sequence as one hole.
- **Internal nets/vars/branches/functions/alias-params** get a unique
  per-instance prefix (`{prefix}{name}`) in `scope.subst`.
- **Internal bus/array nets and variables** (Enhancement-3/4) are renamed
  by their *base* name only (`bus` → `{prefix}bus`) in `scope.subst` —
  `bus[3]`-style bit-select syntax keeps the base identifier as its own
  token, so this one substitution correctly renames every bit without
  needing per-bit entries (this is the mechanism internal buses use, in
  contrast to bus *ports*, which can't use it — see above).
- **Parameters** are renamed like other locals; an override (if supplied)
  replaces only the *default-value* sub-expression inside the parameter's
  own (renamed) declaration — resolved once at declaration time, not
  patched at every reference site.

The target module's own port-direction (`inout p, n;`) and
discipline (`electrical p, n;`, including a vectored `electrical [3:0]
p;`) declarations are **dropped**, not merely renamed, when inlining an
instance — a port's identity now refers to an already-declared net from an
outer scope (or a freshly declared one), so re-declaring it inside the
inlined body would collide with that outer declaration. `NetDecl`/
`BodyPortDecl` items get filtered per-*base*-name (a single `electrical`
line may legally mix port and non-port names/buses).

**Resolve, then recurse:** an instantiation's port/parameter argument
expressions are written in the *instantiating* module's scope. Each
recursive call receives already-fully-resolved (renamed) bindings — the
resolution (`apply_rename`/`resolve_port_bindings` against the parent's own
`Scope`) happens once, in the parent, immediately before recursing, never
inside the child. This is what lets `#(.r(r_base*2))` (an override
expression referencing the *parent's own* parameter) and arbitrarily deep
nesting compose correctly without a second rename pass ever touching
already-resolved text.

**Bus/array slicing** (`find_matching_caller_bus`) is the one heuristic
layered on top of "resolve, then recurse": a port actual, or an
instance-array port actual, is sliced per-bit/per-element only when it's a
*bare identifier* naming a bus, in the instantiating module's own scope,
whose bit width exactly matches what needs slicing:

- A **bus-typed target port** (`bus_resistor br(a, b);`, where `bus_resistor`
  declares `input [1:0] p; electrical [1:0] p;`) slices caller bus `a` bit
  `i` onto target port `p` bit `i` (`bind_port`, aligned by relative
  position, not absolute index — so a caller bus `[7:4]` correctly maps
  onto a target bus `[3:0]`).
- An **instance array** (`resistor rarr[0:3](p, gnd);`) slices a
  matching-width caller bus `p` onto array element `i`'s port
  (`expand_instantiation`'s per-element loop) — this is the array-level
  analogue of the same idea, reusing the identical `find_matching_caller_bus`
  width/name check.

Anything that doesn't match this heuristic (a plain scalar net, a
mismatched width, a non-trivial expression) falls back to plain
bind/broadcast — e.g. `resistor rarr[0:3](out, gnd);` where `out` is an
ordinary scalar net still connects every array element to the same
`out`/`gnd`, exactly like the original (pre-slicing) behavior.

---

## Part 4: Verification

### 9. End-to-end result

`instantiation_examples/resistor_divider.va` exercises the full feature
set in one file: nested instantiation (`divider` → `buffer` → `resistor`),
named and positional ports, named and positional parameter overrides, and
an instance array.

- **MIR/DAE structural check**: building `divider`'s `CompiledModule`
  produces a `DaeSystem` with exactly 3 unknowns (`in`, `out`, `gnd` — the
  module's 3 real ports; no spurious extra unknowns, confirming port
  binding merges node identities rather than adding equations) and 7
  Jacobian entries, consistent with two parallel-resistor groups
  cross-coupling those 3 nodes.
- **Real OSDI + ngspice DC sweep**: `openvaf-r resistor_divider.va -o
  resistor_divider.osdi` (built with `--features llvm18` against a
  Homebrew LLVM 18 toolchain) produces a working `.osdi` shared library;
  loaded into ngspice (`instantiation_examples/dc_sim.cir`), a `.dc Vin -2
  2 0.5` sweep is cross-checked in
  `instantiation_examples/compare_divider.py` against the analytically
  combined resistor network (`buffer` ‖ `r1` between `in`/`out`; `r2` ‖
  `rarr[0]` ‖ `rarr[1]` between `out`/`gnd`) — **matches to ~1e-9**, i.e.
  solver precision.
- **Bus-port/array-slicing check** (`openvaf/test_data/ui/instantiation_bus.va`):
  a module with a 2-bit bus port (`bus_resistor`, ports `p`/`n` each
  `[1:0]`) instantiated as `bus_resistor br(a, b);` where `a`/`b` are
  2-bit buses in the caller, plus `resistor rarr[0:1](a, c);` (per-element
  array slicing onto the same bus `a`) and `resistor rbroadcast[0:1](c,
  d);` (plain scalars — confirms broadcast still applies where slicing
  doesn't). Compiled to a real `.osdi` and driven with ideal DC sources at
  `a[0]=1V`/`a[1]=2V`: with nothing else loading `b[0]`/`b[1]`, the
  zero-current KCL condition through `br`'s resistors forces `b[0]=a[0]`
  and `b[1]=a[1]` *exactly* — confirmed by ngspice (`v(b[0])=1.0`,
  `v(b[1])=2.0`), verifying the bus port bound bit `i` to bit `i`, not some
  other pairing.
- **Regression**: every pre-existing `.va` example from Enhancements 2-4
  (`laplace_examples`, `bus_examples`, `array_var_examples`,
  `bessel_filter_examples`, `combined_examples`, `absdelay_examples`,
  `indirect_assignment_examples`), plus `resistor_divider.va`, still
  compile unchanged through the pipeline after the bus-port/slicing work.
  The full fast test suite (`cargo test --workspace`, minus two
  pre-existing failures confirmed to already fail identically and
  unmodified in `version5` — a stale MIR-value-numbering snapshot in
  `sim_back`'s `dae`/`init`/`topology` unit tests, and a header-parsing
  quirk in `sourcegen`'s `osdi::gen_osdi_structs` — neither touched by this
  enhancement) passes with zero new failures.

- **Cross-`` `include `` instantiation** (`instantiation_examples/
  resistor_divider_include.va` + `resistor_lib.va`): a module can
  instantiate a target declared in a *different* file, pulled in via
  `` `include ``, with no special-casing anywhere in the elaboration code.
  This falls directly out of where the pass sits in the pipeline (§7):
  `` `include `` is a preprocessor directive, resolved by the
  `preprocessor` crate *before* `db.parse` ever runs, so by the time
  elaboration inspects `parse.tree().items()`, the included file's modules
  are already merged into the same single parse tree as the including
  file's own modules — indistinguishable from a same-file declaration.
  The flattened output (and every DC/AC/transient result) is
  byte-for-byte/numerically identical to the equivalent same-file version.

New fixtures:

- `openvaf/test_data/item_tree/instantiation.{va,item_tree,def_map}` —
  positional/named ports, positional/named params, and an instance array,
  checked at the item-tree and name-resolution level.
- `openvaf/test_data/ui/instantiation_errors.{va,log}` — exercises all four
  new diagnostics in one file (unknown module, port-count mismatch, unknown
  param override, mutually-recursive cycle).
- `openvaf/test_data/ui/instantiation_ok.{va,log}` — the nested/positional/
  named/array-instance case, asserting **zero** diagnostics.
- `openvaf/test_data/ui/instantiation_bus.va` — bus-typed ports and
  per-element array slicing (both the sliced and the broadcast case in one
  file), asserting **zero** diagnostics.

---

## 10. Known limitations

- **No span provenance into inlined code.** Diagnostics for code that
  originated inside an instantiated module point at the synthesized
  flattened file (`<name>__elaborated.va`), not the original module's
  source location. The codebase's `preprocessor::sourcemap` machinery
  (`CtxSpan`/`SourceContext`) solves exactly this problem for
  `` `include``/macro expansion, but hooking into it would have meant
  operating at the token-stream level inside the `preprocess` salsa query
  — which, per §1.1/§7, isn't where this pass can run. Diagnostics
  are still fully readable, just not pointing at the file the user
  actually wrote for inlined content.
- **Bus-typed ports and per-element instance-array slicing are supported**,
  via one heuristic (`find_matching_caller_bus`, `openvaf/hir/src/
  elaborate.rs`): a port actual is sliced only when it is a *bare
  identifier* naming a bus, in the instantiating module's own scope, whose
  bit width exactly matches what needs slicing — the target bus port's
  width (`bus_resistor br(a, b);`, wiring bit `i` of port `p`/`n` to bit
  `i` of caller-scope buses `a`/`b`), or the instance array's element count
  (`resistor rarr[0:3](p, gnd);` where `p` is itself a matching-width bus,
  wiring element `i` to `p[i]`). Anything else (a non-bus net, a
  mismatched width, a non-trivial expression) falls back to plain
  bind/broadcast, matching the original (v1) semantics — so `resistor
  rarr[0:1](out, gnd);` where `out` is an ordinary scalar net still
  connects every array element to the same `out`/`gnd`, as before.
  A bus port needed a different substitution mechanism than everything
  else in this pass, since a plain identifier-rename can't express "bit 0
  and bit 1 become different identities" — `find_bus_port_holes` scans for
  `ident '[' int_literal ']'` token sequences matching a bus port's base
  name and replaces the whole sequence as one hole, reusing the existing
  hole-splicing machinery rather than teaching the core renamer a new
  substitution kind. Combining both at once (a bus-typed port *on* an
  array instance, e.g. `bus_resistor barr[0:3](p, q);`) is not sliced on
  the array dimension — only the per-bit port dimension is resolved.
- **Escaped identifiers** (`\foo `) inside an instantiated module aren't
  renamed by the token-level substitution (only `SimpleIdent` tokens are
  matched) — a very rare Verilog-A construct in practice.
- A module that is instantiated by another **also continues to be
  compiled as its own standalone top-level OSDI descriptor** if it appears
  at the top level of the file, unchanged from today's `collect_modules`
  behavior (every top-level module is always compiled).

## 11. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/syntax/veriloga.ungram` | New `Instantiation`/`ParamOverrides`/`ParamAssign`/`InstanceUnit`/`PortConns`/`PortConn` grammar rules |
| `sourcegen/src/ast/src.rs` | Registers the 6 new `SyntaxKind`s consumed by codegen |
| `openvaf/tokens/src/parser/generated.rs`, `openvaf/syntax/src/ast/generated/{nodes,tokens}.rs` | Regenerated via `cargo test -p sourcegen ast` |
| `openvaf/parser/src/grammar/items/module.rs` | 2-token lookahead disambiguation + instantiation/param/port parsing |
| `openvaf/hir_def/src/item_tree.rs` | `Instantiation` item-tree node, `ModuleItem::Instantiation`, `NonConstantInstanceArrayWidth` diagnostic |
| `openvaf/hir_def/src/item_tree/{lower,diagnostics,pretty}.rs` | Lowering, diagnostic rendering, pretty-printing for the new node |
| `openvaf/hir_def/src/lib.rs` | `InstantiationId`/`InstantiationLoc` interning |
| `openvaf/hir_def/src/db.rs` | New `intern_instantiation` salsa query |
| `openvaf/hir_def/src/nameres.rs` | `ScopeDefItem::InstantiationId` variant + all exhaustive-match sites |
| `openvaf/hir_def/src/nameres/collect.rs` | Two-pass module collection (predeclare, then collect items); instantiation resolution + 5 new diagnostics |
| `openvaf/hir_def/src/nameres/diagnostics.rs` | 5 new `DefDiagnostic` variants + `Report` rendering |
| `openvaf/hir_ty/src/inference.rs` | `ScopeDefItem::InstantiationId` treated as `Ty::Scope` (matches `ModuleId`/`BlockId`) |
| `openvaf/hir/src/lib.rs` | `ScopeDefItem::InstantiationId` in the "implementation detail" bucket of `declarations()` |
| `openvaf/hir/src/db.rs` | `pub(crate) fn set_root_file`; calls `elaborate::elaborate_instantiations` at the end of `CompilationDB::new` |
| `openvaf/hir/src/elaborate.rs` | **New** — the text-flattening elaboration pass (§7-8) |
| `openvaf/hir/Cargo.toml` | Adds `lexer`/`tokens` path dependencies (for token-level rename) |
| `openvaf/test_data/item_tree/instantiation.*`, `openvaf/test_data/ui/instantiation_*.*` | New regression fixtures |
| `instantiation_examples/` | New end-to-end example + ngspice cross-check (§9) |

No changes to `openvaf/mir*`, `openvaf/sim_back`, `openvaf/osdi`, or
`openvaf/mir_llvm` — by design, per §1.1/§7.
