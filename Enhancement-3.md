# Enhancement-3 — Vectored/Bus-Style Net Declarations in OpenVAF (version4)

This document describes every source-code change made to **OpenVAF** in the
`version4/` directory, on top of `version3/` (Enhancement-2, indirect branch
assignment), to implement Verilog-AMS **vectored net declarations** — bus
syntax for nets and ports, with bit-select access in branch declarations and
`V()`/`I()` branch-access calls.

The goal is to make constructs like

```verilog
module bus_buffer(in, out);
    input in;
    output [0:3] out;
    electrical in;
    electrical [0:3] out;
    analog begin
        V(out[0]) <+ 0.25 * V(in);
        V(out[1]) <+ 0.50 * V(in);
        V(out[2]) <+ 0.75 * V(in);
        V(out[3]) <+ 1.00 * V(in);
    end
endmodule
```

(the non-ANSI port style above — bare names in the module header, direction
and width declared separately in the body — is the common Verilog-A idiom
and is fully supported; see §2.8 for the fix this required.)

compile and simulate correctly end-to-end (DC, transient) through the OSDI
flow, with `branch (bus[2], bus[0]) br;`-style bit-select endpoints also
supported.

Scope, confirmed up front with the user:

- Declaration: `<discipline> [msb:lsb] name, ...;` for both `NetDecl` and
  `PortDecl` (body and module-head forms).
- Bit-select `bus[i]` valid in `BranchDecl` endpoints and `V()`/`I()`
  branch-access arguments. `i` must be a compile-time-constant integer
  (a literal, optionally unary-negated), range-checked against the bus's
  declared `[msb:lsb]`.
- Part-select `bus[hi:lo]` is **only** legal in the declaration's own width
  clause — never as a branch endpoint or call argument. This OpenVAF subset
  compiles one standalone compact model at a time (no submodule
  instantiation), and a branch endpoint is exactly one node, so there is no
  "vector branch expansion" to support.
- A bare bus name used without an index anywhere a node is expected produces
  a clean diagnostic, never a panic.

---

## 1. The idea (how bus declarations are modeled)

Unlike Enhancement-1 (`absdelay`) and Enhancement-2 (indirect branch
assignment), this feature needs **no new DAE machinery** — no implicit
equations, no new MIR places. A bus is purely a **name-resolution-time**
construct:

A declaration `electrical [3:0] bus;` is expanded, at item-tree lowering
time, into **four independent scalar `Net`/`Node` entries**, with
synthesized names `"bus[3]"`, `"bus[2]"`, `"bus[1]"`, `"bus[0]"`. OpenVAF's
`Name` type is just a `SmolStr` wrapper with no identifier-syntax
restriction, and node/port lookup throughout the compiler is plain `Name`
equality — so synthesizing non-identifier-shaped names like `"bus[3]"` is
safe and requires no change to the lookup data structures themselves.

A new HIR expression node `Expr::BitSelect { base, index }` resolves
`bus[i]`: it constant-folds `i`, range-checks it against the bus's recorded
`[msb:lsb]`, synthesizes the same `"bus[i]"` name, and resolves it exactly
like an ordinary `Expr::Path` would — producing `Ty::Node`. Because
everything downstream of `Ty::Node` (branch resolution, MIR lowering, OSDI
export) is already agnostic to *how* a `NodeId` was produced, this requires
**zero changes** in `hir_lower`, `mir*`, `sim_back`, or `osdi` — only one
match-arm addition in `hir::body::get_expr`. This is a stronger form of the
"no backend changes needed" result Enhancement-2 documented.

`BranchDecl` endpoints (`branch (bus[2], gnd) br;`) are handled the same
way, but one layer earlier: since `hir_def::BranchKind` is built directly
from `ast::BranchKind` during item-tree lowering (before any HIR body/type
inference exists), a bit-select endpoint there is constant-folded and
resolved to a synthesized `hir_def::Path` (`Path::new_ident("bus[2]")`)
right at that point, reusing the exact same `Path` type every other branch
endpoint already uses.

---

## 2. OpenVAF changes

### 2.1 `openvaf/syntax/veriloga.ungram` — grammar

- `NetDecl`/`PortDecl` gained an optional `width: Range?` field, reusing the
  pre-existing `Range` rule (`'[' Expr ':' Expr ']'`) already used by
  parameter `from`/`exclude` constraints.
- New `Expr` alternative, parallel to `PathExpr`:
  ```
  BitSelectExpr = base: Path '[' index: Expr ']'
  ```

### 2.2 `sourcegen/src/ast/src.rs` — manual `SyntaxKind` registration

`BIT_SELECT_EXPR` had to be added to the hand-maintained `nodes: &[...]`
list in `KINDS_SRC` (the `SyntaxKind` enum and `tokens/src/parser/generated.rs`
are *not* auto-derived from the ungram's node list — only the `ast`
struct/accessor codegen is). Regenerated via `cargo test -p sourcegen`.

### 2.3 Parser (`openvaf/parser/src/grammar/`)

- `items.rs`: new `pub(super) fn width_range(p)` parses `'[' expr ':' expr ']'`
  into a `RANGE` node — a small dedicated helper (the existing
  `range_or_expr`, used by parameter constraints, also has to disambiguate
  parenthesized sub-expressions and was left untouched).
- `items/module.rs`: `net_decl`/`port_decl` (covering both module-head and
  body port-decl forms) call `width_range(p)` when the next token is `[`,
  right after the discipline/`net_type` prefix and before the name list.
- `expressions.rs`: `atom_expr`'s `IDENT | ROOT_KW` arm gained a third case
  (alongside the existing call/bare-path cases): if the next token is `[`,
  parse `'[' expr ']'` into `BIT_SELECT_EXPR`. This single insertion point
  covers `V()`/`I()` call arguments and `BranchDecl` arguments for free,
  since both already parse arguments via the shared `expr()`/`atom_expr()`
  path.

### 2.4 `openvaf/syntax/src/ast/node_ext.rs` — AST extensions

- `Expr::as_bit_select(&self) -> Option<(Path, Expr)>`, mirroring the
  existing `as_path()`.
- New `BranchEndpoint` enum (`Plain(Path)` / `BitSelect(Path, Expr)`).
  `BranchKind::NodeGnd`/`Nodes` now hold `BranchEndpoint` instead of a bare
  `Path`, so a branch can mix a bit-select and a plain endpoint (e.g.
  `branch (bus[2], gnd) br;`).
- `openvaf/syntax/src/validation.rs`'s `validate_branch_decl` (which
  rejects non-identifier branch arguments with a clean `IllegalBranchNodeExpr`
  diagnostic) gained `ast::Expr::BitSelectExpr` as an accepted endpoint
  shape, alongside the existing plain-path and port-flow cases.

### 2.5 `openvaf/hir_def` — item-tree expansion and the new `Expr::BitSelect`

- `expr.rs`: new `Expr::BitSelect { base: Path, index: ExprId }` HIR
  variant, with a `walk_child_exprs` arm visiting `index`.
- `body/lower.rs`: a `collect_expr` arm lowers `ast::Expr::BitSelectExpr`
  into `Expr::BitSelect`.
- `item_tree.rs`:
  - `Module` gained `pub buses: Vec<BusDecl>`.
  - New `BusDecl { base_name, msb, lsb, ast_id }`, with `min_max()`,
    `contains_bit(bit)`, and `bit_name(bit)` helpers.
  - New `ItemTreeDiagnostic::NonConstantBusWidth { ast_id }` for a
    `[msb:lsb]` clause that doesn't constant-fold.
- `item_tree/lower.rs`:
  - `fold_width_range(range: &ast::Range) -> Option<(i32, i32)>` — a tiny
    AST-level constant folder (via `ast::Expr::as_constexprval()`, the
    existing literal/negated-literal evaluator used elsewhere for attribute
    values), restricted to integer literals.
  - `expand_bus_names(...)` — for each declared name, if a width clause is
    present and folds successfully, registers a `BusDecl` and emits one
    `(name, name_idx)` per bit (`"bus[3]"` .. `"bus[0]"`, ascending,
    declaration `[msb:lsb]` direction only affects range checks); on a
    non-constant width, pushes `NonConstantBusWidth` and falls back to an
    ordinary scalar declaration so compilation proceeds.
  - `lower_net_decl`/`lower_port_decl` now call `expand_bus_names` instead
    of iterating `decl.names()` directly; the rest of the per-name `Net`/
    `Port`/`Node` insertion logic — including the existing
    "merge into an already-declared node of the same name" path that
    already produces a clean duplicate-declaration diagnostic — is
    completely unchanged, since it already only operates on `Name`s.
  - `lower_branch` gained `resolve_branch_endpoint(ast::BranchEndpoint) ->
    Option<Path>`: a plain endpoint resolves via the existing
    `Path::resolve`; a bit-select endpoint constant-folds its index (via
    `as_constexprval`) and synthesizes `Path::new_ident("base[idx]")` —
    the exact same path the corresponding bus bit was declared under. A
    non-constant index simply fails to resolve, degrading the branch to
    `BranchKind::Missing` (the same graceful fallback any other
    unresolvable branch endpoint already takes — no panic).

### 2.6 `openvaf/hir_ty` — bit-select inference and diagnostics

- `inference.rs`:
  - `Ctx` gained an `owner: DefWithBodyId` field (set in
    `infere_body_query`) and a `find_bus(&self, name) -> Option<BusDecl>`
    helper that looks up the owning module's `BusDecl` registry (only
    meaningful inside a module body; returns `None` otherwise).
  - The existing `Expr::Path { port: false }` arm gained a bare-bus check:
    if the path is a single identifier matching a known bus's base name, a
    new `BareBusReference` diagnostic is emitted instead of attempting
    ordinary resolution (which would otherwise produce a confusing generic
    "unresolved identifier" error).
  - New `infere_bit_select(stmt, expr, base, index) -> Option<Ty>`:
    resolves `base` against the bus registry (falling through to ordinary
    path resolution — and its existing diagnostics — if it isn't a known
    bus, so a genuine typo still gets a normal error rather than a
    bus-specific one); type-checks `index` via the normal expression
    inference path, then separately requires it to constant-fold to
    `Expr::Literal(Literal::Int)` (optionally wrapped in a single
    `UnaryOp::Neg`); range-checks the result against the bus's `[msb:lsb]`;
    and finally resolves the synthesized `"base[idx]"` name through the
    same `resolve_path` machinery as ordinary identifiers, producing
    `Ty::Node`.
  - `infere_expr`'s match gained an `Expr::BitSelect { ref base, index }`
    arm dispatching to `infere_bit_select`.
  - Four new `InferenceDiagnostic` variants: `InvalidBusReference`,
    `NonConstantBitSelectIndex`, `BitSelectOutOfRange`, `BareBusReference`.
- `diagnostics.rs`: report text for all four, in the same style as
  Enhancement-2's `IndirectAssignRequiresEquality` (primary label + source
  span + help note, never a panic).

### 2.7 `openvaf/hir_def/src/item_tree/lower.rs` — non-ANSI bus ports

A module header may declare a port by bare name only
(`module m(in, out);`), with its direction/discipline/width given
separately in the body (`output [3:0] out;`) — standard non-ANSI Verilog-A
port style, and already supported for scalar ports before this enhancement
(the body declaration's exact-name match finds and fills in the header's
placeholder `Node`). For a *bus* port declared this way, the header only
ever creates **one** placeholder node under the bare base name (`"out"`),
but the body's width clause then needs to expand it into **four** nodes
(`"out[0]"`..`"out[3]"`) — a mismatch the original per-name exact-match
lookup couldn't bridge, leaving the header's `"out"` placeholder
dangling and unresolved (manifesting as `error[L016]: no direction
declared for port 'out'`).

Fix: `expand_bus_names` now marks the *first* synthesized bit of every bus
with its original base name. A new `find_node_for_decl` helper tries an
exact-name match first (the existing behavior), and — only for that
first bit — falls back to finding a still-unresolved (`decls.is_empty()`)
node under the base name and **renaming it in place** to the first bit's
name before attaching the declaration. This reuses the header's placeholder
`Node` (and its already-recorded position/identity) for bit 0, rather than
discarding it; bits 1..N are still created as brand new nodes, same as
before.

This is also why `openvaf/hir_def/src/data.rs`'s `ModuleData::module_data_query`
changed: it used to classify a module's nodes into ports vs. internal nodes
by slicing `nodes[0..num_ports]`/`nodes[num_ports..]`, where `num_ports` is
captured right after the header's port list is lowered — *before* the body
runs. A bus port expanding from 1 header placeholder to 4 nodes during body
processing therefore grew `nodes` past the already-frozen `num_ports` cutoff,
so its extra bits were silently misclassified as internal nodes instead of
OSDI terminals (`error: too many nodes connected to instance` from
ngspice, since the compiled model under-reported its terminal count).
The fix replaces the positional slice with a filter on `Node::is_port`,
which is correct regardless of when or where in `nodes` a port node was
created or expanded.

### 2.8 `openvaf/hir/src/body.rs` — the only downstream change

`BodyRef::get_expr`'s match gained `hir_def::Expr::BitSelect { .. }` as a
second pattern on the existing `hir_def::Expr::Path { .. } =>
Expr::Read(self.resolve_path(expr))` arm. `resolve_path` only consults
`infere.expr_types`, not the raw `hir_def::Expr` shape, so this one line is
sufficient — confirmed by the MIR evidence in §6 below.

---

## 3. Diff summary (version3 → version4)

| File | Kind of change |
|---|---|
| `openvaf/syntax/veriloga.ungram` | grammar: `BitSelectExpr`, `width:Range?` on `NetDecl`/`PortDecl` |
| `sourcegen/src/ast/src.rs` | register `BIT_SELECT_EXPR` in the manual `SyntaxKind` list |
| `openvaf/parser/src/grammar/items.rs` | new `width_range` helper |
| `openvaf/parser/src/grammar/items/module.rs` | wire `width_range` into `net_decl`/`port_decl` |
| `openvaf/parser/src/grammar/expressions.rs` | parse `base[index]` as `BIT_SELECT_EXPR` in `atom_expr` |
| `openvaf/syntax/src/ast/node_ext.rs` | `as_bit_select`, `BranchEndpoint`, updated `BranchKind` |
| `openvaf/syntax/src/ast.rs` | export `BranchEndpoint` |
| `openvaf/syntax/src/validation.rs` | accept bit-select as a valid `BranchDecl` endpoint shape |
| `openvaf/hir_def/src/expr.rs` | new `Expr::BitSelect` HIR variant |
| `openvaf/hir_def/src/body/lower.rs` | lower `ast::Expr::BitSelectExpr` |
| `openvaf/hir_def/src/item_tree.rs` | `Module::buses`, `BusDecl`, `ItemTreeDiagnostic::NonConstantBusWidth` |
| `openvaf/hir_def/src/item_tree/lower.rs` | `fold_width_range`, `expand_bus_names`, bus-aware `lower_net_decl`/`lower_port_decl`/`lower_branch`, `find_node_for_decl` (non-ANSI bus port merge, §2.7) |
| `openvaf/hir_def/src/data.rs` | `module_data_query`: classify ports/internal nodes by `is_port`, not a `num_ports` positional cutoff (§2.7) |
| `openvaf/hir_def/src/lib.rs` | export `BusDecl` |
| `openvaf/hir_ty/src/inference.rs` | `find_bus`, `infere_bit_select`, bare-bus check, 4 new diagnostics |
| `openvaf/hir_ty/src/diagnostics.rs` | report text for the 4 new diagnostics |
| `openvaf/hir/src/body.rs` | one match-arm addition in `get_expr` |

No changes to `openvaf/hir_lower`, `openvaf/mir*`, `openvaf/sim_back`, or
`openvaf/osdi` — see §6.

---

## 4. New diagnostics

| Diagnostic | When |
|---|---|
| `ItemTreeDiagnostic::NonConstantBusWidth` | a `[msb:lsb]` width clause doesn't constant-fold to two integer literals; the declaration falls back to an ordinary scalar net/port |
| `InferenceDiagnostic::InvalidBusReference` | a bit-select base isn't a simple identifier |
| `InferenceDiagnostic::NonConstantBitSelectIndex` | a bit-select index isn't a constant integer literal (optionally negated), e.g. `V(bus[i])` for a variable `i` |
| `InferenceDiagnostic::BitSelectOutOfRange` | a bit-select index is outside the bus's declared `[msb:lsb]` |
| `InferenceDiagnostic::BareBusReference` | a bus is referenced by its base name with no bit-select, e.g. `V(bus, n)` |

All five produce a normal compiler error with a source span and a help
note, never a panic. A bare bus name used as a `BranchDecl` endpoint
(`branch (bus, gnd) br;`) is a known, narrower gap: it degrades gracefully
to `BranchKind::Missing` (no crash, the branch just doesn't resolve) rather
than emitting one of the diagnostics above — surfacing a dedicated
`hir_def`-level diagnostic for that specific case was left out of scope
here in favor of the higher-value `V()`/`I()`-argument and declaration-time
checks, which cover the common cases.

---

## 5. Why almost no backend/OSDI changes were needed

A bus bit's `Net`/`Port`/`Node` entry is, by the time it reaches
`hir_lower`/`mir_build`/`sim_back`/`osdi`, indistinguishable from any other
scalar net or port declared the ordinary way — same `NodeId`, same
`PlaceKind::Contribute`/`IsVoltageSrc` stamping, same OSDI terminal/node
export. The *only* place that needed to know about buses at all was name
resolution (`hir_def` item-tree lowering and `hir_ty` inference); once a
bit-select expression resolves to a `NodeId`, every later stage treats it
exactly like `V(some_ordinary_net)`.

This was confirmed empirically: the new MIR snapshot test (§6) and a direct
`--dump-unopt-mir`/`--dump-mir` run on the bus example (§7.2) both show the
synthesized node names (`bus[0]`..`bus[3]`) flowing through ordinary branch
resolution, DAE/Jacobian stamping, and OSDI export with no special-casing —
and the compiled `.osdi` simulates correctly in ngspice (§7.3) without
touching a single line in `sim_back` or `osdi`.

---

## 6. Build

```bash
cd version4/OpenVAF-master
cargo test -p sourcegen                       # regenerate SyntaxKind + AST from the ungram
LLVM_SYS_181_PREFIX=/opt/homebrew/opt/llvm@18 \
  cargo build --release --bin openvaf-r --features openvaf-driver/llvm18
cp target/release/openvaf-r ../bin/macos/apple-silicon/openvaf-r
```

---

## 7. Testing & verification

### 7.1 Compiler unit / snapshot tests

`cargo test -p syntax -p hir_def -p hir_ty -p hir -p hir_lower` — all
existing tests pass unchanged (0 failures), confirming no regression in
plain scalar net/port declarations, `absdelay`, indirect branch assignment,
or any other existing construct (every pre-existing `.va` fixture has no
width clause, so `width` is simply `None` and behaves exactly as before).

New `.mir` snapshot fixture
`openvaf/test_data/mir/bus_basic.va`/`.mir`:

```verilog
module bus_test(p, n);
    inout p, n;
    electrical p, n;
    electrical [3:0] bus;
    branch (bus[2], bus[0]) br_a;
    analog begin
        V(bus[1], n) <+ 1.0;
        I(br_a) <+ V(bus[3]) * 2;
    end
endmodule
```

This exercises declaration, `branch(bus[2], bus[0])`, and `V()`/`I()`
bit-select end-to-end through `hir_lower::MirBuilder`. A direct
`openvaf-r --dump-unopt-mir`/`--dump-mir` run on the same file shows the
"Partially optimized MIR (with DAE)" output stamping `bus[0]`..`bus[3]` as
ordinary nodes (visible in the literal table: `'bus[0]'`, `'bus[1]'`,
`'bus[2]'`, `'bus[3]'`, `'flow(bus[1],n)'`), feeding the Jacobian/residual
rows exactly like any scalar net — no special-casing artifacts.

New `ui` diagnostic fixtures under `openvaf/test_data/ui/`:
`bus_bare_reference.va` (`V(bus, n)`), `bus_out_of_range.va`
(`V(bus[10], n)` against a `[3:0]` bus), `bus_nonconstant_index.va`
(`V(bus[i], n)` for a `real` variable `i`) — each produces a clear,
correctly-spanned error (e.g. `bus 'bus' requires a bit-select [i]`,
`bus bit-select index out of range`, `bus bit-select index must be a
constant`), verified by hand against the generated `.log` files.

### 7.2 End-to-end compile

`version4/bus_examples/bus_buffer.va` — a 4-tap fractional voltage buffer
using a vectored **port**, declared non-ANSI style (bare names in the
module header, direction/width given in the body — see §2.7):

```verilog
module bus_buffer(in, out);
    input in;
    output [0:3] out;
    electrical in;
    electrical [0:3] out;
    parameter real gain = 1.0 from (0:inf);
    analog begin
        V(out[0]) <+ 0.25 * gain * V(in);
        V(out[1]) <+ 0.50 * gain * V(in);
        V(out[2]) <+ 0.75 * gain * V(in);
        V(out[3]) <+ 1.00 * gain * V(in);
    end
endmodule
```

compiles to a working `.osdi` with zero errors/warnings. The bus port
expands to 5 OSDI terminals in declaration order (`in`, `out[0]`, `out[1]`,
`out[2]`, `out[3]`), connected positionally in the SPICE netlist exactly
like any other multi-terminal device.

### 7.3 ngspice simulation — new feature

`version4/bus_examples/` (`dc_sim.cir`, `ac_sim.cir`, `tran_sim.cir`),
simulated with `version4/bin/.../ngspice`:

- **DC** sweep −2V…2V: each tap tracks its exact fraction of the input
  (e.g. at `Vin = 2.0V`: `out0 = 0.5V`, `out1 = 1.0V`, `out2 = 1.5V`,
  `out3 = 2.0V` — exactly 0.25×/0.5×/0.75×/1.0× gain).
- **AC** 1kHz…1GHz: each tap shows a flat gain of −12.04 dB / −6.02 dB /
  −2.50 dB / 0 dB respectively (exactly `20*log10(tap fraction)`) and 0°
  phase across the entire sweep — as expected for a purely algebraic model
  with no reactive elements.
- **Transient** 1kHz sine input: all four taps track the input
  instantaneously (purely resistive/algebraic model, no reactive
  elements), with the same exact fractional relationship at every sample.

Raw results saved in `dc.txt`/`ac.txt`/`tran.txt`, plotted in
`dc.png`/`ac.png`/`tran.png`, in that directory (see
`bus_examples/README.md`).

### 7.4 Regression — absdelay (Enhancement-1) and indirect branch assignment (Enhancement-2)

Both `version4/absdelay_examples/absdelay.va` and
`version4/indirect_assignment_examples/opamp.va` were recompiled with the
new `openvaf-r` and re-simulated (DC) against the documented Enhancement-2
baselines:

- `absdelay` 5-stage delay line DC sweep: **bit-identical** to
  `absdelay_examples/examples/dc_sparse.txt`.
- `opamp` indirect-branch-assignment unity-gain buffer DC sweep:
  **bit-identical** to `indirect_assignment_examples/dc.txt`.

This confirms vectored net declaration support introduced no regressions
in either prior enhancement or the broader OSDI/ngspice pipeline.
