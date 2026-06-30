# Enhancement-4 — Laplace-Domain Transfer-Function Operators in OpenVAF (version5)

This document describes every source-code change made to **OpenVAF** in the
`version5/` directory, on top of `version4/` (Enhancement-3, vectored/bus
net declarations), to implement:

1. Verilog-A's four **Laplace transform filter** analog operators
   (§1-8 below).
2. **Array-variable declarations** (`real [msb:lsb] x;`), added as a
   follow-up once it became clear `laplace_*`'s array-literal *arguments*
   (`'{...}'`) were a different feature from array *variables* — see §9.

## Part 1: Laplace transform filter operators

The four operators:

```verilog
laplace_nd(in, num_coeffs, den_coeffs)   // num/den given as polynomial coefficients
laplace_np(in, num_coeffs, den_poles)    // num as coefficients, den as poles (roots)
laplace_zd(in, num_zeros, den_coeffs)    // num as zeros (roots), den as coefficients
laplace_zp(in, num_zeros, den_poles)     // both num/den given as roots
```

The goal is to make constructs like

```verilog
module laplace_lpf(in, out);
    input in;
    output out;
    electrical in, out;
    parameter real tau = 1e-6 from (0:inf);
    analog begin
        V(out) <+ laplace_nd(V(in), '{1.0}, '{1.0, tau});
    end
endmodule
```

(a first-order RC-style low-pass filter, `H(s) = 1/(1+tau*s)`) compile and
simulate correctly end-to-end (DC, transient) through the OSDI flow, for
all four `laplace_*` forms, with coefficient/root lists given as
`'{...}'` array-literal arguments.

Scope, confirmed up front with the user:

- All four forms — `laplace_nd`, `laplace_np`, `laplace_zd`, `laplace_zp`.
- `num`/`den` (or `zero`/`pole`) arguments are compile-time-constant real
  array literals (`'{...}'`), as already enforced by pre-existing
  `hir_ty` validation (see §1.3) — this was *not* new validation written
  for this enhancement.
- The optional trailing tolerance (`laplace_*_tol`) / nature argument is
  accepted for signature compatibility but has no effect: the realization
  built here is an exact algebraic transformation of the transfer
  function into an ODE system, not an approximation that would need an
  error tolerance to converge.
- `zi_nd`/`zi_np`/`zi_zd`/`zi_zp` (the z-domain/discrete-time analogues)
  remain out of scope and still report `is_unsupported`.

---

## 1. What was actually there already (and what wasn't)

Before writing any new logic, the existing scaffolding for `laplace_*`
turned out to be **front-end-complete but parser/lowering-incomplete** —
a more interesting starting state than Enhancement-3's bus feature, which
started from nothing:

1. `BuiltIn::laplace_nd/np/zd/zp` already existed as recognized keywords,
   with `hir_ty` signatures (`LAPLACE_FILTER`, taking two
   `ArrayAnyLength{ty: Real}` arguments plus optional tolerance/nature)
   already wired up — **but** marked `is_unsupported()`, so any use was
   rejected with a hard compile error ("function ... is currently not
   supported by OpenVAF") before reaching `hir_lower` at all.
2. The array-literal expression syntax (`'{a, b, c}'`, `ARRAY_EXPR` in the
   ungram/`SyntaxKind`/AST layers) was **fully scaffolded but never
   parsed**: `openvaf/parser/src/grammar/expressions.rs` had a complete
   `array_expr` parser function sitting commented out behind a `// TODO
   properly implement arrays` marker, with `atom_expr` never dispatching
   to it. So `'{1.0, 2.0}'` was a syntax error everywhere, independent of
   `laplace_*`.
3. `hir_ty::inference::infere_array` (the array-literal type-checker) had
   a latent bug: it returned `Ty::Val(ty)` — the *element* type — instead
   of `Ty::Val(Type::Array { ty, len })`, so even with parsing fixed, a
   3-element real array literal would type-check as a bare `real`, not an
   array, failing every `ArrayAnyLength` signature match.
4. `openvaf/hir_lower/src/expr.rs::lower_array` was `todo!("arrays")` —
   arrays were never lowered as general MIR values (and still aren't;
   they remain a syntax-only construct consumed positionally by builtins
   like `laplace_*`/`noise_table`, never materialized as a runtime array
   value — see §2.2).

So this enhancement closes three latent gaps (#2-#4) in addition to the
actual new feature (the transfer-function-to-DAE lowering, #5 below).

---

## 2. The idea (how Laplace operators are modeled)

### 2.1 No new "Laplace" DAE primitive — reuse of `idt`'s machinery

Unlike `absdelay` (Enhancement-1), which needed a genuinely new
simulator-side mechanism (history-based delay lookup, `PlaceKind::
AbsDelayTime`, a dedicated `OsdiAbsDelayInfo` struct), a Laplace transfer
function `H(s) = num(s)/den(s)` can be realized **exactly** as an
ordinary linear ODE system — no approximation, no new backend concept.

The standard **controllable canonical form** state-space realization is
used: for a proper rational `H(s)` of order `n = deg(den)`, with `n`
state variables `x_0..x_{n-1}`:

```
dx_0/dt     = x_1
dx_1/dt     = x_2
   ...
dx_{n-2}/dt = x_{n-1}
dx_{n-1}/dt = u - (a_bar_0 * x_0 + a_bar_1 * x_1 + ... + a_bar_{n-1} * x_{n-1})

y = c_0*x_0 + c_1*x_1 + ... + c_{n-1}*x_{n-1} + d*u
```

where `u` is the operator's input expression, `a_bar_i = den[i]/den[n]`
is the monic-normalized denominator, `d = num[n]/den[n]` is the direct
feedthrough term (only present when `num` is exactly proper, i.e.
`deg(num) == deg(den)`), and `c_i = (num[i] - d*den[i])/den[n]`.

Each state `x_i` is **exactly** the same shape as the existing `idt()`
builtin's implicit equation: a fresh implicit unknown (`ctx.
implicit_equation`) with a *reactive* residual of `x_i` (contributing
`d(x_i)/dt` to KCL) and a *resistive* residual of `-(RHS of dx_i/dt)`, so
that the simulator's standard `d(react)/dt + resist = 0` stamping
produces exactly `dx_i/dt = RHS`. This is the **same** mechanism
`lower_integral` already uses for `idt(arg)` (`react = val`,
`resist = -arg` there). The output `y` is then a **purely algebraic**
linear combination of state values (plus `d*u`) — it needs no implicit
equation of its own.

Because this reduces entirely to ordinary implicit-equation residuals
(the same primitive `idt`/`absdelay` already use), **no changes were
needed in `sim_back` or `osdi`** — exactly the same "no backend changes"
result Enhancement-3 reported for bus nets, but here it falls out of
reusing an *existing* DAE primitive rather than needing none at all.

### 2.2 Root-to-polynomial expansion for `np`/`zd`/`zp`

`laplace_np`/`laplace_zd`/`laplace_zp` give one or both of `num`/`den` as
a list of **roots** (poles/zeros) rather than polynomial coefficients.
These are expanded into ascending-power coefficients at MIR-build time by
repeated synthetic polynomial multiplication by `(s - root)`:

```
poly := [1]                              // the empty product
for each root r:
    poly := poly * (s - r)               // convolution, fully unrolled
```

Since the *number* of roots/coefficients is always known at compile time
(it's the literal length of an `'{...}'` array — no constant-folding of
the array *length* is needed, unlike the array *element values*, which
are MIR `Value`s computed normally via `lower_expr` and may depend on
instance parameters), this unrolls into a small, fixed sequence of
`fmul`/`fsub`/`fneg` MIR instructions per call site — no runtime loop, no
new MIR opcode.

### 2.3 Why arrays are still not general MIR values

`lower_array`/`Expr::Array` remain syntax-only: a `'{...}'` argument to
`laplace_*` is never lowered as a single array `Value`. Instead,
`array_elems()` reads the raw `hir::Expr::Array` node directly (bypassing
`lower_expr` for the array as a whole) and lowers each element
individually with the ordinary `lower_expr`. This mirrors how
`noise_table_log('{...})` and other pre-existing `ArrayAnyLength`
consumers were always implicitly expected to work, and avoids having to
invent a real "array value" MIR representation for a four-builtin,
syntax-only feature.

---

## 3. OpenVAF changes

### 3.1 `openvaf/parser/src/grammar/expressions.rs` — enable array-literal parsing

- `atom_expr`'s dispatch gained `T!["'{"] | T!['{'] => array_expr(p)`
  (previously a commented-out TODO covering only `'{`).
- The `array_expr` parser function itself was uncommented and fixed: the
  original draft checked `p.at(T![']'])` for its loop-exit condition (a
  copy-paste bug from a `[...]` array sketch) instead of `T!['}']`, which
  would have looped past the actual closing brace. Now parses
  `('{ | '{) (Expr (',' Expr)*)? '}'` into an `ARRAY_EXPR` node, matching
  the pre-existing `BIT_SELECT_EXPR`-style structure already wired through
  the rest of the AST/HIR/type-inference stack (§3.2-3.3 confirm those
  layers were already complete).
- **Both `'{a, b, c}'` and bare `{a, b, c}'` are accepted** as the opening
  delimiter, lexed as distinct tokens (`ArrStart` for `'{`, `OpenBrace`
  for plain `{`) but parsed identically — `array_expr`'s opening bump
  uses `p.bump_ts(TokenSet::new(&[T!["'{"], T!['{']]))` rather than a
  single fixed token. This matches a precedent already in the codebase:
  `openvaf/parser/src/grammar/items.rs`'s `constraint` parser (for
  parameter `from`/`exclude` array-style constraints) already accepted
  both spellings (`p.eat(T!["'{"]) || p.eat(T!['{'])`) before this
  enhancement touched anything — `array_expr` simply needed to follow the
  same convention. Verified end-to-end: `laplace_nd(V(in), {1.0}, {1.0,
  tau})` (bare braces) and `laplace_nd(V(in), '{1.0}, '{1.0, tau})` (with
  leading `'`) compile to bit-identical MIR and produce identical
  simulated results.

This is a prerequisite for *any* array literal anywhere in the language,
not just `laplace_*` arguments — `noise_table_log` and other pre-existing
`ArrayAnyLength`-typed builtins benefit identically as a side effect.

### 3.2 `openvaf/hir_ty/src/inference.rs` — fix `infere_array`'s return type

`infere_array` (the array-literal type-checker) returned `Ty::Val(ty)` —
the unified *element* type — instead of `Ty::Val(Type::Array { ty:
Box::new(ty), len })`. This made every non-empty array literal type-check
as a bare scalar of its element type, so it could never satisfy an
`ArrayAnyLength{ty: Real}` parameter requirement (only the *element* type
matched, not "is an array"), failing overload resolution for every
`laplace_*`/`noise_table_log` call with a literal array argument. Fixed
to construct the correct `Type::Array` value, matching the
`(Ty::Val(Type::Array{ty: ref ty1, ..}), TyRequirement::ArrayAnyLength{ty:
ty2}) => equiv.compare_ty(ty1, ty2)` match arm in `hir_ty/src/types.rs`
that was already correctly written to expect it.

### 3.3 `openvaf/hir_def/src/builtin.rs` / `sourcegen/src/hir_builtins.rs` — mark Laplace as supported

`laplace_nd`/`laplace_np`/`laplace_zd`/`laplace_zp` removed from the
`UNSUPPORTED` list in `sourcegen/src/hir_builtins.rs` (the source of
truth; `openvaf/hir_def/src/builtin.rs` is regenerated from it via
`cargo test -p sourcegen`, so it was *not* hand-edited directly). `zi_*`
(z-domain) builtins were left in `UNSUPPORTED`, out of scope.

### 3.4 `openvaf/hir_lower/src/lib.rs` — new implicit-equation kind

- New `ImplicitEquationKind::LaplaceState(u32)` variant — purely a
  descriptive tag (mirroring `AbsDelayInput`/`AbsDelayOutput`/
  `IndirectBranch`) for debug/MIR-dump readability; nothing downstream
  pattern-matches on `ImplicitEquationKind` beyond `hir_lower` itself
  (confirmed by grep — only `lineralize.rs`'s unrelated inline-`ddt()`
  handling and `hir_lower/src/stmt.rs`'s `IndirectBranch` push do, and
  neither needed to change), so this needed no further wiring.

### 3.5 `openvaf/hir_lower/src/expr.rs` — the actual lowering

- `lower_builtin`'s match gained a `BuiltIn::laplace_nd | laplace_np |
  laplace_zd | laplace_zp => self.lower_laplace(builtin, args)` arm.
- `lower_laplace`: lowers the input expression, lowers each `num`/`den`
  (or `zero`/`pole`) array element via the ordinary `lower_expr`, and
  dispatches `num`/`den` through `laplace_roots_to_poly` for whichever of
  the two (if either) the specific builtin variant gives as roots
  (`laplace_zd`/`laplace_zp` for `num`, `laplace_np`/`laplace_zp` for
  `den`), then calls `laplace_state_space`.
- `array_elems`: reads `hir::Expr::Array` directly off `self.body` for a
  given `ExprId` (falling back to treating the expression as a
  single-element array if it somehow isn't a literal array — defensive,
  not expected to trigger given the type-level `ArrayAnyLength`
  requirement).
- `laplace_roots_to_poly`: the polynomial-from-roots expansion of §2.2.
- `laplace_state_space`: builds the controllable-canonical-form
  realization of §2.1 — normalized denominator, direct feedthrough,
  output coefficients, `n` implicit equations with paired
  reactive/resistive residuals, and the final algebraic output
  combination. Handles the degenerate `n == 0` case (constant-gain,
  dynamics-free) directly as `(num[0]/den[0]) * input`.

### 3.6 No changes needed in `sim_back` or `osdi`

As in Enhancement-3, confirmed empirically (§5 below): once a Laplace
call lowers to ordinary implicit-equation residuals, every later stage
(topology linearization, Jacobian/residual stamping, OSDI export)
treats the resulting states exactly like any other `idt()`-style
implicit unknown.

---

## 4. Diff summary (version4 → version5)

| File | Kind of change |
|---|---|
| `openvaf/parser/src/grammar/expressions.rs` | enable `'{...}'` array-literal parsing (`array_expr`, dispatch in `atom_expr`) — fixes a pre-existing dead/buggy stub, prerequisite for any array-literal use |
| `openvaf/hir_ty/src/inference.rs` | fix `infere_array` to return `Type::Array{..}` instead of the bare element type — pre-existing latent type-inference bug |
| `sourcegen/src/hir_builtins.rs` | remove `laplace_nd/np/zd/zp` from `UNSUPPORTED` (regenerates `openvaf/hir_def/src/builtin.rs`) |
| `openvaf/hir_lower/src/lib.rs` | new `ImplicitEquationKind::LaplaceState` |
| `openvaf/hir_lower/src/expr.rs` | `lower_laplace`, `array_elems`, `laplace_roots_to_poly`, `laplace_state_space` — the actual transfer-function-to-DAE lowering |

No changes to `openvaf/hir_def` item-tree/lowering, `openvaf/mir*`,
`openvaf/sim_back`, or `openvaf/osdi`.

---

## 5. Why almost no backend/OSDI changes were needed

Once `laplace_state_space` finishes, every state `x_i` is, from
`mir_opt`/`sim_back`/`osdi`'s point of view, indistinguishable from an
`idt()` integrator's implicit unknown: same `ImplicitEquation` index
space, same `PlaceKind::ImplicitResidual{equation, reactive}` stamping,
same OSDI Jacobian-entry generation. The output value `y` is a plain
algebraic MIR expression (sums and products of state/parameter values),
so it needs no special handling at all — it flows into the branch
contribution exactly like any other expression.

This was confirmed via `--dump-unopt-mir`/`--dump-mir` on the test
fixtures in `laplace_examples/`: the `Implicit equations:` section of the
HIR interner dump lists one `LaplaceState(i)` entry per state (one for a
first-order `laplace_nd`/`laplace_np` filter, two for a second-order
`laplace_zd`/`laplace_zp` filter), feeding ordinary reactive/resistive
residuals with no special-casing artifacts anywhere in the dump.

---

## 6. Build

```bash
cd OpenVAF-master-20260610
cargo test -p sourcegen                       # regenerate is_unsupported() from hir_builtins.rs
LLVM_SYS_181_PREFIX=/opt/homebrew/opt/llvm@18 \
  cargo build --release --bin openvaf-r --features openvaf-driver/llvm18
cp target/release/openvaf-r ../bin/macos/apple-silicon/openvaf-r
```

---

## 7. Testing & verification

### 7.1 Compiler unit / snapshot tests

`cargo test -p syntax -p hir_def -p hir_ty -p hir -p hir_lower` — all
existing tests pass unchanged (0 failures), including the Enhancement-2
(`mir::indirect_branch.va`) and Enhancement-3 (`mir::bus_basic.va`) MIR
snapshot fixtures, confirming the array-literal parser/type-inference
fixes and the new Laplace lowering introduced no regression in any
existing construct.

### 7.2 End-to-end compile

`laplace_examples/`:

- `laplace_lpf.va` — `laplace_nd(V(in), '{1.0}, '{1.0, tau})`, a
  first-order RC-style low-pass filter (single bus-free port pair).
- `laplace_variants.va` — all four forms side by side: `laplace_nd`/
  `laplace_np` both realizing the same `H(s) = 1/(1+tau*s)` (coefficient
  form vs. pole form), and `laplace_zd`/`laplace_zp` both realizing the
  same second-order `H(s) = (s+2e6)/((s+1e6)(s+3e6))` (zero-with-
  coefficient-denominator form vs. fully factored pole/zero form).
- `laplace_zd_only.va` — an isolated single-call fixture used to
  cross-check the multi-call comparison file's results column-by-column.

All compile to a working `.osdi` with zero errors/warnings.
`--dump-unopt-mir`/`--dump-mir` confirm the expected implicit-equation
counts: 1 state for each first-order filter, 2 states for each
second-order filter (`openvaf-r --dump-mir laplace_zd_only.va` shows
`0 : LaplaceState(0)` / `1 : LaplaceState(1)`).

### 7.3 ngspice simulation — new feature

`laplace_examples/` (`dc_sim.cir`, `ac_sim.cir`, `tran_sim.cir` for the
primary `laplace_lpf` model, plus `dc_variants.cir`/`dc_zd_only.cir` for
the four-forms cross-check), simulated via `bash run_examples.sh`. Raw
results saved in `dc.txt`/`ac.txt`/`tran.txt`, plotted via
`plot_results.py` (matplotlib) into `dc.png`/`ac.png`/`tran.png`:

- **DC** (`dc.txt`/`dc.png`), `laplace_lpf` (first-order, `tau=1e-6`):
  `out` tracks `in` exactly 1:1 across a -2V..2V sweep — correct, since
  `H(0) = 1/(1+0) = 1`.
- **DC**, `laplace_variants` (`dc_variants.txt`): at `in = 2.0`,
  `out_nd = out_np = 2.0` (both realize `H(0)=1`) and
  `out_zd = out_zp = 1.33333e-6` (both realize the second-order system's
  `H(0) = 2e6/3e12 = 6.667e-7`, so `2.0 * 6.667e-7 = 1.3333e-6`) —
  **all four forms agree exactly** on equivalent transfer functions,
  cross-validating the coefficient and root-expansion code paths against
  each other.
- **AC** (`ac.txt`/`ac.png`), `laplace_lpf` swept 1kHz..1GHz: a textbook
  single-pole Bode response — flat 0 dB / 0° well below the corner
  frequency `f_pole = 1/(2*pi*tau) = 159.2 kHz`, exactly **-3.0 dB /
  -45.0°** at `f_pole` (read directly off the AC sweep data, e.g.
  `158.5 kHz -> -2.99 dB`, `-0.7833 rad = -44.88°`), a **-20 dB/decade**
  rolloff above it, and phase asymptoting to -90° at high frequency —
  confirming the realization's frequency-domain behavior, not just its
  DC/step response, matches the analytic transfer function.
- **Transient** (`tran.txt`/`tran.png`), `laplace_lpf` step response: a
  0→1V step at `t=0` produces `V(out) = 0.632...` at `t = tau = 1us` —
  exactly `1 - e^-1 = 0.63212...`, the analytic first-order step
  response, confirming the state-space realization's *dynamics* (not
  just its DC gain) are correct.

### 7.4 Regression — bus nets (Enhancement-3), absdelay (Enhancement-1), indirect branch assignment (Enhancement-2)

`bus_examples/bus_buffer.va`, `absdelay_examples/absdelay.va`, and
`indirect_assignment_examples/opamp.va` all recompile cleanly with the
new `openvaf-r` (zero errors/warnings), and their corresponding `hir_lower`
MIR snapshot tests (`mir::bus_basic.va`, plus the full
`-p hir_lower` suite) pass unchanged — confirming the parser/type-checker
fixes needed for array literals (§3.1, §3.2) didn't disturb bit-select
expressions, branch resolution, or any other prior-enhancement construct.

---

## 8. Known limitations

- **Improper transfer functions are not diagnosed.** If `deg(num) >
  deg(den)` (more numerator coefficients than the state-space
  realization can use), the extra high-order numerator terms are
  silently dropped rather than producing a diagnostic or supporting
  differentiation of the input. Enhancement-3 set a precedent of
  documenting this kind of narrower gap rather than blocking on it (its
  bare-bus-as-branch-endpoint case); the same call is made here given
  improper transfer functions are an unusual/degenerate modeling case.
  A `hir_ty`-level diagnostic (comparing `num`/`den` array-literal
  lengths, no constant-folding needed) would be the natural follow-up.
- **`zi_nd`/`zi_np`/`zi_zd`/`zi_zp`** (z-domain/discrete-time filters)
  remain unimplemented (`is_unsupported`), as scoped up front.

---

## Part 2: Array-variable declarations (`real [msb:lsb] x;`)

### 9. Motivation and prior state

`laplace_*`'s `'{...}'` arguments (Part 1) are **array-literal
expressions** — fixed-size constant lists, never assigned to or indexed
by a runtime-variable index, and not a storage location. Verilog-A
separately allows declaring an **array variable** — a named, indexable
piece of mutable storage, e.g.:

```verilog
real [0:4] coeffs;
analog begin
    coeffs[0] = 0.1;
    V(out) <+ coeffs[0] * V(in);
end
```

This was previously **unsupported**: `VarDecl`'s grammar rule
(`openvaf/syntax/veriloga.ungram`) had no width/range field at all (unlike
`NetDecl`/`PortDecl`, which already gained one in Enhancement-3), so
`real [0:4] x;`/`real x[0:4];` were both syntax errors.

### 10. Design: same compile-time-constant-index expansion as bus nets

Rather than building genuine runtime-indexable array storage (a much
larger change — a new MIR memory/array primitive, since today's MIR only
has scalar SSA values, confirmed by `hir_lower::lower_array` still being
unimplemented, see §2.3 in Part 1), array variables are modeled exactly
like Enhancement-3's bus nets: `real [msb:lsb] x;` is expanded at
item-tree lowering time into independent scalar `Var` entries (`"x[4]"` ..
`"x[0]"`), and `x[i]` reuses the **already-generic** `Expr::BitSelect`
machinery from Enhancement-3 — `i` must be a compile-time-constant
integer (a literal, optionally unary-negated), range-checked against the
declared `[msb:lsb]`. This is a real, if narrower, capability than a
general indexable array: a for-loop with a runtime-variable index into
the array (`x[i]` for non-constant `i`) is not supported, same constraint
bus-net bit-select already had.

The syntax chosen is `<type> [msb:lsb] name;` — the *prefix*-range form
already established for `NetDecl`/`PortDecl` in this codebase — rather
than chasing the LRM's postfix `name[size]` declarator form, for
consistency with the existing bus-declaration convention.

### 11. Why this needed almost no new machinery

The key discovery, made before writing any code: `Expr::BitSelect`
resolution (`hir_ty::inference::infere_bit_select`) was **already fully
generic** past the point of finding a `BusDecl` and constant-folding the
index — its *only* bus-specific step was the final match on what the
synthesized `"x[i]"` name resolved to:

```rust
match self.resolve_path(stmt, expr, &synth_path)? {
    ScopeDefItem::NodeId(node) => Some(Ty::Node(node)),
    _ => None,   // a Var resolution was silently dropped here
}
```

Adding one arm — `ScopeDefItem::VarId(var) => Some(Ty::Var(self.db
.var_data(var).ty.clone(), var))` — was the *entire* change needed for
`x[i]` to work as a value (read) **and** as an assignment target (write):

- **Reads**: `infere_bit_select` returning `Ty::Var` flows into
  `hir::body::BodyRef::get_expr`'s existing `Expr::BitSelect => Expr::Read
  (self.resolve_path(expr))` arm (added in Enhancement-3 §2.8) completely
  unchanged — `resolve_path` there already dispatches off `Ty::Var`
  identically for ordinary variable reads, producing `Ref::Variable(var)`
  and ultimately `ctx.read_variable(var)` in `hir_lower`.
- **Writes**: `hir_ty::inference::infere_assignment_dst` (which resolves
  an assignment statement's LHS expression, e.g. `x[i] = ...;`) calls the
  same generic `infere_expr` used for any expression, and **already** had
  a `Ty::Var(ty, var) => (AssignDst::Var(var), ty)` arm — so once
  `infere_bit_select` can produce `Ty::Var`, assignment-to-a-bit-select
  works immediately, with no further code. Same for `hir::body`'s
  `as_assignment_lhs` (`Expr::Read(Ref::Variable(var)) =>
  AssignmentLhs::Variable(var)`).

So unlike Part 1 (which needed a genuinely new lowering, `lower_laplace`),
this feature needed no new `hir_lower`/`mir`/`sim_back`/`osdi` code at
all — each expanded scalar `Var` is, from MIR onward, indistinguishable
from a variable declared without a width clause.

### 12. OpenVAF changes

#### 12.1 `openvaf/syntax/veriloga.ungram` — grammar

`VarDecl` gained an optional `width: Range?` field, reusing the
pre-existing `Range` rule, identical in shape to `NetDecl`/`PortDecl`'s:

```
VarDecl =
  AttrList* Type width:Range? (Var (',' Var)*) ';'
```

#### 12.2 `openvaf/parser/src/grammar/items.rs` — parser

`var_decl` calls the existing `width_range(p)` helper (built for
`NetDecl`/`PortDecl` in Enhancement-3) when the next token is `[`, right
after the type and before the name list — the same insertion pattern
`net_decl`/`port_decl` already use.

#### 12.3 `openvaf/hir_def/src/item_tree.rs` — registry

- `Module` gained `pub var_arrays: Vec<BusDecl>`, kept as a separate list
  from `buses` (nets/ports) purely so the two declaration kinds stay
  distinguishable for diagnostics/debugging — `BusDecl` itself (base
  name, `msb`, `lsb`, `ast_id`) is reused verbatim, since an array
  variable is structurally identical to a bus: a base name plus an
  `[msb:lsb]` range expanding into independent scalar entries.
- New `ItemTreeDiagnostic::ArrayVarUnsupportedScope { ast_id }` for a
  width clause that appears somewhere array-variable resolution doesn't
  support (§12.4).

#### 12.4 `openvaf/hir_def/src/item_tree/lower.rs` — expansion, and scope restriction

`lower_var` (shared by module-body `VarDecl`s, `analog function`-body
`VarDecl`s, and nested `begin..end`-block `VarDecl`s) gained a
`var_arrays: Option<&mut Vec<BusDecl>>` parameter:

- The module-body call site (inside `lower_module_items`) passes
  `Some(&mut var_arrays)`, an accumulator threaded through `lower_module`
  exactly like `buses` already is, attached to the final `Module {
  ..., var_arrays }`.
- The `analog function`-body and nested-block call sites pass `None` —
  array-variable bit-select resolution is **module-body scope only**
  (mirroring `find_bus`'s existing `DefWithBodyId::ModuleId`-only lookup;
  a function has its own `DefWithBodyId::FunctionId` owner, so a registry
  keyed only on the module wouldn't be reachable from inside one anyway
  without further plumbing). A width clause in either unsupported scope
  triggers `ArrayVarUnsupportedScope` and degrades gracefully to an
  ordinary scalar variable, never a panic.

When `var_arrays` is `Some` and the width constant-folds, each declared
name expands into one scalar `Var` per bit (ascending `lo..=hi`,
synthesized name `"x[i]"` via the same `bus_bit_name` helper Enhancement-3
added), and a `BusDecl` is recorded. A non-constant width falls back to
`NonConstantBusWidth` (the same diagnostic bus nets already use) plus a
scalar declaration, exactly mirroring `expand_bus_names`.

A default initializer on an array declaration (`real [0:4] x = 1.0;`) is
silently ignored (not assigned to any bit) — see §13.

#### 12.5 `openvaf/hir_ty/src/inference.rs` — resolution

- New `find_var_array(&self, name) -> Option<BusDecl>`, identical in
  shape to `find_bus` but querying `Module::var_arrays`.
- `infere_bit_select`: the base-name lookup is now `self.find_bus(&name)
  .or_else(|| self.find_var_array(&name))` — a bit-select base can be
  *either* a bus or an array variable (the two can't collide on the same
  name, since they'd already conflict as ordinary duplicate
  declarations).
- The final resolution match gained `ScopeDefItem::VarId(var) =>
  Some(Ty::Var(self.db.var_data(var).ty.clone(), var))` (§11) — the one
  line that makes everything else work.
- The bare-reference check (`Expr::Path` with no bit-select) now also
  checks `find_var_array`, so `V(out) <+ coeffs * V(in);` (forgetting the
  `[i]`) reuses the existing `BareBusReference` diagnostic rather than
  falling through to a generic "unresolved identifier" error. Its message
  text was generalized from "bus referenced..."/"select a single bit" to
  "bus/array referenced..."/"select a single element" to read sensibly
  for both cases (`openvaf/hir_ty/src/diagnostics.rs`).

### 13. New/changed diagnostics

| Diagnostic | When |
|---|---|
| `ItemTreeDiagnostic::ArrayVarUnsupportedScope` | a `[msb:lsb]` width clause on a `VarDecl` inside an `analog function` body or a nested `begin..end` block (only module body scope is supported); falls back to a scalar variable |
| `ItemTreeDiagnostic::NonConstantBusWidth` | (reused) a width clause that doesn't constant-fold, on an array variable same as on a bus net |
| `InferenceDiagnostic::BareBusReference` | (reused, generalized wording) an array variable referenced by its base name with no bit-select, e.g. `V(out) <+ coeffs * V(in);` |
| `InferenceDiagnostic::BitSelectOutOfRange` | (reused) `coeffs[10]` against a declared `[0:4]` array |
| `InferenceDiagnostic::NonConstantBitSelectIndex` | (reused) `coeffs[i]` for a non-constant/variable `i` |

All confirmed via hand-written `.va` fixtures producing clean, correctly
spanned errors, never a panic (see §15).

### 14. Diff summary (additive to Part 1's table)

| File | Kind of change |
|---|---|
| `openvaf/syntax/veriloga.ungram` | `VarDecl` gains `width: Range?` |
| `openvaf/parser/src/grammar/items.rs` | `var_decl` calls the existing `width_range` helper |
| `openvaf/hir_def/src/item_tree.rs` | `Module::var_arrays`, `ArrayVarUnsupportedScope` diagnostic |
| `openvaf/hir_def/src/item_tree/lower.rs` | `lower_var` gains array expansion + module-body-only scope restriction; `lower_module`/`lower_module_items` thread the new `var_arrays` accumulator |
| `openvaf/hir_def/src/item_tree/diagnostics.rs` | report text for `ArrayVarUnsupportedScope` |
| `openvaf/hir_ty/src/inference.rs` | `find_var_array`; `infere_bit_select` checks both registries and resolves `ScopeDefItem::VarId`; bare-reference check covers array variables too |
| `openvaf/hir_ty/src/diagnostics.rs` | generalized `BareBusReference` wording |

No changes to `openvaf/hir`, `openvaf/hir_lower`, `openvaf/mir*`,
`openvaf/sim_back`, or `openvaf/osdi` (§11).

### 15. Testing & verification

`array_var_examples/array_var_fir.va` — a 5-tap weighted-sum model
exercising declaration, indexed write, and indexed read end-to-end:

```verilog
module array_var_fir(in, out);
    input in;
    output out;
    electrical in, out;
    real [0:4] coeffs;
    analog begin
        coeffs[0] = 0.1;
        coeffs[1] = 0.2;
        coeffs[2] = 0.3;
        coeffs[3] = 0.2;
        coeffs[4] = 0.2;
        V(out) <+ (coeffs[0]+coeffs[1]+coeffs[2]+coeffs[3]+coeffs[4]) * V(in);
    end
endmodule
```

(coefficients sum to 1.0, so `V(out)` should track `V(in)` exactly — a
closed-form expected result, same spirit as `bus_examples/bus_buffer.va`).
Compiles with zero errors/warnings; `dc_sim.cir` DC sweep (`dc.txt`)
confirms `V(out) = V(in)` exactly across a -2V..2V sweep.

Diagnostics verified by hand with isolated fixtures: `coeffs[10] = 1.0;`
(out-of-range, against `[0:4]`), `coeffs * V(in)` (bare reference), and a
`real [0:2] tmp;` declared inside an `analog function` (unsupported
scope) — each produces a clean, correctly spanned error, never a panic.

Regression: `cargo test -p syntax -p hir_def -p hir_ty -p hir -p
hir_lower` passes unchanged (only one snapshot intentionally updated —
`test_data/ui/bus_bare_reference.log`'s wording, for the generalized
bare-reference message in §12.5). All Part 1 (Laplace), Enhancement-3
(bus nets), Enhancement-2 (indirect branch assignment), and Enhancement-1
(absdelay) examples recompile cleanly with the rebuilt `openvaf-r`.

### 16. Known limitations

- **No runtime-variable indexing.** `x[i]` for a non-constant `i` (e.g. a
  `for` loop accumulating into an array) is not supported — `i` must
  constant-fold, identical to bus-net bit-select's existing constraint.
  Genuine indexable array storage would need a new MIR memory/array
  primitive (`hir_lower::lower_array` is still `todo!`), out of scope
  here.
- **Module-body scope only.** Array variables inside `analog function`
  bodies or nested `begin..end` blocks degrade to scalars with a
  diagnostic (§12.4) rather than being supported — extending
  `find_var_array`'s lookup to function/block scope would need a registry
  keyed on more than just the owning module.
- **Default initializers are silently dropped** on array declarations
  (`real [0:4] x = 1.0;` doesn't assign to any bit) — there's no
  well-defined per-bit meaning for a single scalar initializer on an
  array declaration; a diagnostic rejecting the combination outright
  would be the natural follow-up.
