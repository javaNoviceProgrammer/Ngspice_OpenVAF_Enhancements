# Enhancement-9 — Verilog-A noise sources: completing `noise_table` / `noise_table_log` (version10)

This document describes the source-code changes made to **OpenVAF-r** in the
`version10/` directory, on top of `version9/` (Enhancement-8, `generate
for`/`genvar` and `cross()`/`above()`/`timer()`), to make the Verilog-A
**noise analog operators** fully usable for ngspice `.noise` analysis.

All work is in `version10/` only; all simulation verification uses
`version10/ngspice-46`'s own locally built binary and
`version10/OpenVAF-master`'s own `openvaf-r`.

## 0. Scope, and the honest starting point

The requested feature was "noise sources". A gap analysis of the version10
baseline (which is upstream OpenVAF-Reloaded plus Enhancements 1–8) showed that
the noise-source family was **two-thirds already functional and one-third
crashing**:

| operator | baseline status |
|---|---|
| `white_noise(pwr [, "name"])` | **already worked end-to-end** — never touched by any prior enhancement; it is stock upstream functionality |
| `flicker_noise(pwr, exp [, "name"])` | **already worked end-to-end** |
| `noise_table(...)` / `noise_table_log(...)` | **crashed the compiler** — front-end recognised the builtins and type-checked all four call forms, but no data was ever read and the OSDI backend hit `unimplemented!("noise tables")` |

This was verified empirically before writing any code:

- `white_noise`: a `white_noise(4kT/R)` thermal resistor compiled and simulated
  with the *unmodified* baseline, and its `.noise` output matched the
  closed-form `4kT` result to the last digit (see §4).
- `flicker_noise`: a `flicker_noise(pwr, 1)` element produced the correct
  `1/√f` density rolloff on the unmodified baseline.
- `noise_table`: a one-line `I(a,b) <+ noise_table("f","g")` model **crashed**
  `openvaf-r` with `index out of bounds: the len is 0 but the index is 0` in
  `sim_back/src/topology/lineralize.rs:45`.

Enhancement-9 therefore **implements `noise_table`/`noise_table_log`
end-to-end** (the genuinely-missing noise source) and ships an
**analytically-verified example suite covering all four operators**
(`noise_examples/`), including `white_noise`/`flicker_noise` as verified
reference examples. No changes to `white_noise`/`flicker_noise` were needed or
made; a regression run confirms their output is byte-identical before and after
(see §4).

Four further unrelated defects found during this work are also fixed here:
`localparam` being silently overridable, contrary to the LRM (§5); the
`electrical ground gnd;` net-declaration ordering failing to parse (§6); a
**regression** in which Enhancement-8's regeneration of `builtin.rs` re-disabled
`slew`/`transition`/`last_crossing`/`zi_*` (implemented back in Enhancement-6) —
now re-enabled (§7); and an uninitialized `string` variable crashing the
compiler (§8). The `repeat` loop, previously unsupported entirely, is also
implemented (§9), as is the `disable` early-exit statement (§10).

## 1. Why `noise_table` crashed: a three-part gap

`noise_table`/`noise_table_log` were "wired for show" in the baseline — every
layer between the parser and codegen referenced them, but three links in the
chain were stubs:

1. **No data was ever read.** `hir_lower`'s builtin-lowering created the
   callback with a hard-coded placeholder table and **no arguments**:
   ```rust
   let noise_table = NoiseTable::new([(0.0, 0.0)], log, name, idx);
   self.ctx.call1(CallBackKind::NoiseTable(Box::new(noise_table)), &[])  // <-- &[]
   ```
   (`NoiseTable::new` even carried a `// TODO: read from disk`.) Neither the
   inline-array argument nor the file-name argument was consulted.

2. **The empty arg list crashed topology construction.**
   `sim_back::topology::lineralize`'s `builid_analog_operators` unconditionally
   read `instr_args(operator_inst)[0]` for *every* analog operator. `ddt`,
   `white_noise` and `flicker_noise` all have at least one MIR value argument,
   so this never fired before — but `noise_table` legitimately has **zero**
   value args (its data lives in the callback), so `[0]` panicked.

3. **The OSDI backend refused to emit code.** Both frequency-dependent noise
   entry points in `osdi/src/load.rs` (`load_noise` and `load_noise_params`)
   had `NoiseSourceKind::NoiseTable { .. } => unimplemented!("noise tables")`.

## 2. The implementation

### 2.1 Reading the table data (`hir_lower/src/expr.rs`)

The `noise_table`/`noise_table_log` lowering arm now gathers the real
`(frequency, power)` pairs before building the callback:

```rust
let table_vals = self.noise_table_data(signature, args);
let noise_table = NoiseTable::new(table_vals, log, name, idx);
```

`noise_table_data` dispatches on the resolved call signature (the same four
signatures `hir_ty` already defines — `NOISE_TABLE_INLINE`,
`NOISE_TABLE_FILE`, and their `_NAME` variants):

- **Inline array** `noise_table({f0, p0, f1, p1, ...})`: the first argument is a
  real `Expr::Array`; each element is folded to a constant via a small
  `eval_const_real` helper (literal `Real`/`Integer`, with an optional leading
  unary `+`/`-`), then the flat list is paired up into `(f, p)` tuples.
- **File** `noise_table("path")`: the first argument is a string literal; a new
  `read_noise_table_file` helper resolves it **relative to the compilation root
  file's directory** and parses a two-column whitespace-separated
  `<frequency> <power>` file (blank lines and `#`/`//`/`*` comment lines
  skipped).

Path resolution needed the on-disk directory of the root source file. Rather
than widen `hir_lower`'s dependency surface (it depends on `hir`, but `basedb`
is only a `hir_lower` *dev*-dependency), a small public accessor was added to
the `hir` crate:

```rust
// openvaf/hir/src/db.rs
pub fn root_file_dir(&self) -> Option<VfsPath> {
    self.file_path(self.root_file).parent()
}
```

Missing/unreadable files and malformed lines degrade gracefully to an empty
table (which the codegen renders as a constant-zero noise source) rather than
crashing — matching the codebase's existing soft-degradation conventions for
other builtins.

### 2.2 Fixing the topology crash (`sim_back/src/topology/lineralize.rs`)

`arg0` is only ever consumed by the non-noise (`ddt`) branch, so it is now read
defensively:

```rust
let arg0 =
    self.func.dfg.instr_args(operator_inst).first().copied().unwrap_or(F_ZERO);
```

This removes the panic for zero-argument noise operators without changing
behaviour for `ddt`/`white_noise`/`flicker_noise` (all of which still supply
`arg0`).

### 2.3 OSDI interpolation codegen (`osdi/src/load.rs`)

The core of the enhancement. `load_noise(inst, model, freq, noise_dens)` is the
per-frequency evaluator ngspice calls during `.noise`. For a table source it
now emits, via a new `build_noise_table_interp` helper, LLVM IR that:

1. computes `lx = log10(freq)` (the `llvm.log10.f64` intrinsic);
2. performs **piecewise-linear interpolation of the tabulated power over
   `lx`**, fully unrolled into a chain of `select`s. Every segment's slope and
   intercept is a compile-time constant, so each segment costs exactly one
   `fmul`, one `fadd`, one `fcmp olt` and one `select`;
3. **clamps** to the first/last tabulated point outside `[x[0], x[n-1]]`.

The unrolled form walks segments from the top down; after the loop the
surviving `select` is precisely the bracketing segment (the lowest-index
segment whose upper bound exceeds `lx`), and a final `select` clamps the
below-range case to `y[0]`. Degenerate tables are handled (`n == 0` → constant
`0`, `n == 1` → constant `y[0]`). The existing `pwr * factor²` scaling that
`white_noise`/`flicker_noise` already apply is reused unchanged, so a
`k * noise_table(...)` contribution scales correctly.

The second entry point, `load_noise_params(inst, model, power, exponent)`, is a
white/flicker-oriented ABI slot (it exposes a single scalar power and a single
frequency exponent). A frequency-dependent table has neither, and **ngspice
never calls this function** (its OSDI noise path uses only `load_noise` — see
§3), so the table case there returns `0.0` with an explanatory comment rather
than fabricating a meaningless scalar. The real, frequency-aware evaluator is
`load_noise`.

### 2.4 Interpolation semantics (why the `log` flag needs no run-time handling)

`hir_lower::NoiseTable::new` stores the table keyed by `log10(frequency)` in
**both** cases: for `noise_table` it applies `.log10()` to the (linear)
frequency column; for `noise_table_log` it stores the column as-is (the user
already supplied `log10(f)`). Because the stored key domain is identical, the
run-time lookup key is always `log10(freq)` and the `log` flag is fully consumed
at build time — the codegen ignores it. This is confirmed by the examples:
`noise_table.txt` (linear `1, 100, 10000`) and `noise_table_log.txt`
(`0, 2, 4`) produce **bit-identical** spectra (§4). The interpolated quantity is
the linear power spectral density; interpolation is linear-in-power over
log-frequency.

## 3. ngspice-46: no changes required (and why)

`ngspice-46/src/osdi/osdinoise.c` already drives the OSDI noise ABI generically:
in `N_CALC`/`N_DENS` it calls `descr->load_noise(inst, model, data->freq,
noise_dens)` once per frequency and folds the result into the output-noise
integral. It does **not** branch on `noise_source_type`, so `NOISE_TYPE_TABLE`
sources flow through the exact same path as white/flicker ones — the
table-specific behaviour lives entirely inside the OSDI-generated `load_noise`
function produced in §2.3. `load_noise_params` is not referenced anywhere in
ngspice-46. The full `.noise` verification in §4 uses the **unmodified**
prebuilt `version10/ngspice-46/build/src/ngspice`. No OSDI ABI header change
(`osdi_0_4*.h`) and no ngspice C change were needed.

## 4. Verification

All verification lives in `noise_examples/` and is automated by
`noise_examples/verify_noise.py`, which compiles each model with version10's
`openvaf-r`, runs the matching `.noise` deck through version10's `ngspice`,
reads back the `onoise_spectrum` (output-noise voltage density, `V/√Hz`), and
compares it point-by-point against an independent closed-form computation.

Measurement topology (identical for every deck):
`V(in) —[r1 = 1 kΩ]— V(out) —[n1 = OSDI noise device]— gnd`, with `.temp 26.85`
(= 300.00 K) so ngspice's own `r1` thermal noise matches the models' `Temp=300`.
Then `S_out(f) = (S_i,device(f) + 4kT/R1)·Zout²`, `Zout = R1‖R_device`.

```
white       : max relative error = 1.6e-07   PASS   (flat 4kT spectrum)
flicker     : max relative error = 1.5e-07   PASS   (1/f + white floor)
table       : max relative error = 2.5e-09   PASS
table_log   : max relative error = 2.5e-09   PASS
table_log vs table: max |diff| = 0.0         PASS   (bit-identical)
```

- **`white_noise`** — the same thermal-divider example run on the *unmodified*
  baseline and on the patched compiler produces byte-identical
  `onoise_total = 3.881810e-06`, `inoise_total = 4.269991e-06`, matching
  `√(4kT·(1/1k + 1/10k)·Zout²)` analytically.
- **`noise_table`** — includes a non-trivial interpolated point: at `f = 1 kHz`
  (`log10 f = 3`, midway between the `log10 f = 2` and `log10 f = 4` table
  nodes) the interpolated power is
  `1e-12 + (1e-16 − 1e-12)·(3−2)/(4−2) = 5.0005e-13`, i.e.
  `onoise = √(5.0005e-13)·1000 ≈ 7.0714e-4 V/√Hz`, which ngspice reproduces as
  `7.071414e-4`. End-of-range clamping is confirmed by sweeping down to 0.1 Hz
  (below the first node) and up to 10 kHz — both flatten to the endpoint values.

See `noise_examples/README.md` and `noise_examples/noise_spectra.png` for the
full write-up and plots.

### Regression

- `cargo test -p sim_back` — all **24** tests pass, including every noise
  topology test (`correlated_noise`, `conditional_noise`, `unused_noise`,
  `manual_correlated_noise`).
- `cargo test -p hir` and `cargo test -p hir_lower` — all pass (the new
  `root_file_dir` accessor and `noise_table_data` helpers included).
- Regression-recompiled the pre-existing example models
  (`cross_examples`, `laplace_examples`, `instantiation_examples`,
  `bus_examples`, `generate_examples`, `absdelay_examples`, `timer_examples`,
  `initial_step_examples`, `variable_persistence_examples`)
  through the patched compiler — 18/18 compile unchanged.
- `white_noise`/`flicker_noise` `.noise` output is byte-identical pre/post.

## 5. Follow-up fix: `localparam` is now non-overridable (LRM conformance)

While verifying the noise models (which use `localparam` for physical
constants), a gap analysis of parameter handling surfaced a second, unrelated
pre-existing defect: **`localparam` was treated identically to `parameter`.**

### The defect

The parser records an `is_local` flag for `localparam` declarations
(`hir_def::item_tree`), but that flag was **set and never read anywhere** — it
was not even carried into `hir_def::ParamData`. Consequently every `localparam`
was exposed to the simulator as an externally-settable model/instance parameter
and could be overridden from the `.model` card, which the Verilog-AMS LRM
forbids (a `localparam` is a local constant, not overridable). Confirmed on the
baseline: `.model m lptest(G=0.01)` for a `localparam real G = 0.001;` changed
the device's behaviour to `G = 0.01`.

### The fix

`is_local` is now threaded from `ParamData` (`hir_def`) → `hir::Parameter::is_local`
→ the OSDI setup functions. In `osdi::setup` (`setup_model`/`setup_instance`),
the runtime **"given" flag fed to the parameter-initialization code is forced to
a constant `false` for every `localparam`**. The parameter-init MIR is left
completely unchanged, so its `given ? override : default` selection always
resolves to the default expression; the constant-`false` condition is folded by
LLVM (robust), not by the MIR optimizer.

### Why the fix lives in `osdi::setup`, not the param-init MIR

The default-value store is physically emitted inside the *not-given* branch of
the param-init `make_cond` (so a defaulted parameter is written only when the
simulator did not supply a value). Two more direct-looking approaches were tried
and rejected because they corrupted **derived** localparams (`localparam G =
1/R`): forcing the make_cond condition to a MIR constant `false` triggered a
constant-branch mis-fold that leaked the uninitialized override slot, and a
dedicated straight-line param-init path evaluated the default outside the
context where the dependency `R` resolves. Forcing the *runtime given input*
false at the OSDI/LLVM boundary keeps the MIR pristine — so `1/R` still resolves
correctly — while guaranteeing the default is always stored.

### Verified behaviour (`localparam_examples/`)

`localparam_examples/verify_localparam.py` (a `GAIN*G = GAIN/R` conductance in a
divider) exercises every case end-to-end through ngspice:

```
  rdiv()                 V(out)=0.333333  PASS   defaults
  rdiv(R=2000)           V(out)=0.500000  PASS   parameter R overridable
  rdiv(R=500)            V(out)=0.200000  PASS   parameter R overridable
  rdiv(G=0.5)            V(out)=0.333333  PASS   localparam G override ignored
  rdiv(GAIN=10)          V(out)=0.333333  PASS   localparam GAIN override ignored
  rdiv(R=4000 G=9 GAIN=9)V(out)=0.666667  PASS   only R applies
```

A **derived** localparam (`G = 1/R`) is verified to still track its underlying
`parameter` (`R=2000` → `V(out)=0.5`) while ignoring any direct override of `G`.
Regular `parameter` overrides are unaffected, and the full unit-test suite and
all pre-existing example models (18/18) compile and simulate unchanged.

## 6. Follow-up fix: `electrical ground gnd;` now parses

The Verilog-A `ground` net-type (which declares a node as the global V = 0
reference, collapsed to the circuit ground) already worked, but the
net-declaration parser only accepted the net-type **before** the discipline
(`ground electrical gnd;`). The equally-valid **discipline-first** ordering
`electrical ground gnd;` failed with `unexpected token NET_TYPE; expected
identifier`, even though `port_decl` already accepted a net-type in that
position.

`net_decl` (`openvaf/parser/src/grammar/items/module.rs`) now eats an optional
`NET_TYPE` token after the discipline in the discipline-first branch — a
one-line mirror of what `port_decl` does. All four natural orderings now parse to
an identical device (`ground_examples/verify_ground.py`, all end-to-end through
ngspice):

```
  ground electrical gnd;         a=1.0  b=0.6667  PASS   (already worked)
  electrical ground gnd;         a=1.0  b=0.6667  PASS   (fixed here)
  electrical gnd; ground gnd;    a=1.0  b=0.6667  PASS
  ground gnd; electrical gnd;    a=1.0  b=0.6667  PASS
```

The internal `ground` node correctly acts as the 0 V reference (`V(b) =
2000/3000`). A bare `ground gnd;` with no discipline remains a (correct) error.
The `parser` test suite (15 tests) passes and the change is a strict superset —
ordinary net declarations (`electrical a, b;`) are unaffected because `eat`
consumes a `NET_TYPE` only when one is actually present.

## 7. Regression fix: `slew`/`transition`/`last_crossing`/`zi_*` re-enabled

These analog operators were implemented in **Enhancement-6** (version7): their
`BuiltIn::is_unsupported()` gate was removed and full lowering — plus, for
`last_crossing`, ngspice runtime support — was added. They worked in version7
and version8.

**Enhancement-8 (version9) silently regressed them.** That enhancement
regenerated `openvaf/hir_def/src/builtin.rs` (via `cargo test -p sourcegen
ast`), and the regeneration **re-added the `is_unsupported()` entries** for
`zi_nd`/`zi_np`/`zi_zd`/`zi_zp`, `last_crossing`, `slew`, and `transition` —
shadowing the still-present, still-correct lowering with a hard
"function is currently not supported" validation error. version10 inherited the
regression. (Confirmed by diffing `is_unsupported()` across versions: the seven
entries are absent in v7/v8 and present in v9/v10, and the only difference is
those seven lines; the lowering code was untouched.)

Enhancement-9 removes those seven entries again (with a comment noting the
history so a future regeneration doesn't silently reintroduce them). No other
change was needed — the lowering and `last_crossing` ngspice runtime from
Enhancement-6 are intact. All four example folders now compile **and simulate**:

```
  slew_examples/slew_demo.va                 compiles + tran OK
  transition_examples/transition_demo.va     compiles + tran OK
  last_crossing_examples/last_crossing_demo.va  compiles + DC/AC/tran OK
  zi_examples/zi_lpf.va                      compiles + tran OK
```

After this fix, **39/39** example models across all folders compile, and the
unit-test suite is unaffected.

## 8. Follow-up fix: uninitialized `string` variables no longer crash

`real` and `integer` analog-block variables were always fully supported, as was
a `string` variable **with** an initializer (`string s = "x";`). But an
**uninitialized** `string s;` crashed the compiler: the type-based default-value
assignment for a variable declared without an initializer
(`hir_def/src/body.rs`) only handled `Real` (→ `0.0`) and `Integer` (→ `0`) and
fell through to `unreachable!("invalid var type")` for `String`:

```rust
let default_val = match db.var_data(var).ty {
    Type::Real    => Literal::Float(Ieee64::with_float(0.0)),
    Type::Integer => Literal::Int(0),
    Type::String  => Literal::String("".into()),   // added in Enhancement-9
    _ => unreachable!("invalid var type (TODO arrays)"),
};
```

Enhancement-9 gives `string` variables the LRM-correct empty-string (`""`)
default. `string s;` now behaves like the other types — verified end-to-end
(`vartype_examples/`): an uninitialized `string mode` defaults to `""`, the
`mode == ""` test then assigns `"series"`, and the string-selected branch drives
the output correctly (`V(b) = 2000/3000`), alongside `real` and `integer`
variables in the same model.

## 9. New feature: `repeat` loop

The Verilog-AMS **`repeat (count) statement`** loop was entirely unsupported —
`repeat` was not a recognized keyword, so `repeat (4) begin ... end` failed to
parse. Enhancement-9 implements it across the full pipeline:

- **Tokens/grammar/AST** (`tokens/parser/generated.rs`, `syntax/veriloga.ungram`,
  `syntax/src/ast/generated/nodes.rs`): a `repeat` keyword (`REPEAT_KW`) and a
  `RepeatStmt` node (`repeat '(' count:Expr ')' body:Stmt`). The generated files
  were hand-edited rather than regenerated via `cargo test -p sourcegen ast`, to
  avoid re-triggering the kind of regeneration regression documented in §7.
- **Parser** (`parser/src/grammar/stmts.rs`): a `repeat_stmt` production,
  mirroring `while_stmt`.
- **HIR** (`hir_def::Stmt::Repeat`, `hir::Stmt::Repeat`, body lowering, pretty
  printer, `hir_ty` inference + validation): the count expression is
  type-checked/validated as an ordinary value and the body as a child statement.
- **MIR lowering** (`hir_lower/src/stmt.rs`, `lower_repeat`): the count is
  evaluated **once**, coerced to an integer (Verilog-AMS real→integer =
  round-to-nearest, via `FIcast`), and the body is run that many times as a
  counted loop. The integer counter is carried by a header phi spliced into the
  top of the loop-condition block (`FuncCursor::at_first_inst`), so no new
  `PlaceKind`/persistent-state surface was needed.

### Verified behaviour (`repeat_examples/`)

```
  count=0     -> 0 iters   V(b)=1.00000  (body never runs)
  count=1..10 -> exact     integer counts run exactly
  count=3.4   -> 3 iters   round down
  count=3.6   -> 4 iters   round up
  count=2.5   -> 3 iters   round half away from zero
```

Nested `repeat` loops multiply (`repeat(P) repeat(Q)` runs the inner body `P*Q`
times), and `repeat` composes with `for`/`while`/`if`. The `parser` (15) and all
touched-crate unit tests pass, and 40/40 example models compile — the shared
token/AST/HIR changes are a strict superset (existing statements unaffected).

## 10. New feature: `disable` (loop break / early exit)

Verilog-A has no `break`/`continue` keywords — **`disable <named_block>;`** is
the language's early-exit mechanism, and it was unsupported (the `disable`
keyword tokenised but had no grammar/parser/lowering). Enhancement-9 implements
it:

- **Tokens/grammar/AST/parser**: a `DISABLE_STMT` node (`disable name ;`) and a
  `disable_stmt` parser production (the `DISABLE_KW` keyword already existed).
- **HIR**: `hir_def::Stmt::Disable { name }`, plus the enclosing block's label is
  now recorded on `Stmt::Block` (`name: Option<Name>`) so a `disable` can be
  matched to it. Threaded through `hir::Stmt`, body lowering, pretty-printer,
  and hir_ty (validation; inference covers it via its catch-all).
- **MIR lowering** (`hir_lower`): a stack of enclosing named blocks and their
  MIR exit blocks is kept on `LoweringCtx` (`disable_scopes`). Entering a
  *named* `begin : label ... end` creates an exit block and pushes
  `(label, exit)`; `disable label` branches to the matching exit and continues
  lowering in a fresh (dead) block, exactly like the existing `$fatal`
  early-termination idiom. Unnamed blocks are still lowered inline (no overhead).

### Idioms and verification (`disable_examples/`)

Both loop-control idioms are built from `disable` and verified end-to-end:

```
break    (named block wraps the loop; disable it -> loop exits, code after runs)
  STOP=2/4/8 -> 2/4/8 iterations   V(b)=0.667 / 0.800 / 0.889   PASS
continue (loop *body* is the named block; disable it -> skip the iteration)
  8 iterations, 4 contribute       V(b)=0.800                   PASS
```

Disabling the whole `analog` block terminates it (contributions after the
`disable` are skipped) — also verified. An unresolved block name degrades to a
no-op. The `parser` (15) and touched-crate unit tests pass, and 41/41 example
models compile.

## 11. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/hir_lower/src/expr.rs` | Read real table data (`noise_table_data`, `read_noise_table_file`, `eval_const_real` helpers) from an inline array or a file resolved relative to the root source file; pass it to `NoiseTable::new` instead of the `[(0.0,0.0)]` placeholder |
| `openvaf/hir/src/db.rs` | New `CompilationDB::root_file_dir()` accessor for resolving source-relative paths |
| `openvaf/hir_lower/src/callbacks.rs` | Replaced the stale `// TODO: read from disk` with a doc comment describing the now-populated `NoiseTable::new` contract |
| `openvaf/sim_back/src/topology/lineralize.rs` | **Crash fix**: read `arg0` defensively so zero-argument noise operators (`noise_table`) no longer panic (§1, item 2) |
| `openvaf/osdi/src/load.rs` | **Codegen**: `build_noise_table_interp` emits `log10`-domain piecewise-linear, endpoint-clamped interpolation for `load_noise`; `load_noise_params` returns a documented zero fallback for tables (§2.3) |
| `noise_examples/` | New analytically-verified example suite for all four noise operators (`.va` models, `.noise` decks, data files, `verify_noise.py`, `README.md`, plot) |
| `openvaf/hir_def/src/data.rs` | **localparam fix**: `ParamData` now carries `is_local`, populated from the item tree (§5) |
| `openvaf/hir/src/lib.rs` | **localparam fix**: new `Parameter::is_local()` accessor (§5) |
| `openvaf/osdi/src/setup.rs` | **localparam fix**: force the "given" flag to constant `false` for `localparam`s in `setup_model`/`setup_instance`, so they are never externally overridable (§5) |
| `localparam_examples/` | New end-to-end verification of `localparam` non-overridability, incl. derived-localparam tracking (`rdiv.va`, `verify_localparam.py`, `README.md`) |
| `openvaf/parser/src/grammar/items/module.rs` | **ground fix**: `net_decl` now accepts an optional net-type after the discipline, so `electrical ground gnd;` parses like the other three orderings (§6) |
| `ground_examples/` | New end-to-end verification of the `ground` net-type across all four declaration orderings (`rgnd.va`, `verify_ground.py`, `README.md`) |
| `openvaf/hir_def/src/builtin.rs` | **regression fix**: removed the `is_unsupported()` entries for `slew`/`transition`/`last_crossing`/`zi_*` that Enhancement-8's `builtin.rs` regeneration erroneously re-added, shadowing their Enhancement-6 implementation (§7) |
| `openvaf/hir_def/src/body.rs` | **string-variable fix**: an uninitialized `string` variable now defaults to `""` instead of hitting `unreachable!` and crashing (§8) |
| `vartype_examples/` | New end-to-end verification of `real`/`integer`/`string` analog-block variables, incl. an uninitialized `string` (`vartypes.va`, `verify_vartypes.py`, `README.md`) |
| `openvaf/tokens/src/parser/generated.rs`, `openvaf/syntax/veriloga.ungram`, `openvaf/syntax/src/ast/generated/nodes.rs` | **`repeat` loop**: `REPEAT_KW`/`REPEAT_STMT` tokens + `RepeatStmt` AST node (§9) |
| `openvaf/parser/src/grammar/stmts.rs` | **`repeat` loop**: `repeat_stmt` parser production (§9) |
| `openvaf/hir_def/src/expr.rs`, `body/lower.rs`, `body/pretty.rs`, `openvaf/hir/src/body.rs`, `openvaf/hir_ty/src/inference.rs`, `validation/body.rs` | **`repeat` loop**: `Stmt::Repeat` through the HIR + type-check/validate (§9) |
| `openvaf/hir_lower/src/stmt.rs` | **`repeat` loop**: `lower_repeat` builds the counted loop with a header-phi integer counter (§9) |
| `repeat_examples/` | New end-to-end verification of the `repeat` loop (`repeat_demo.va`, `verify_repeat.py`, `README.md`) |
| `openvaf/tokens/src/parser/generated.rs`, `openvaf/syntax/src/ast/generated/nodes.rs`, `openvaf/parser/src/grammar/stmts.rs` | **`disable`**: `DISABLE_STMT` token + `DisableStmt` AST node + `disable_stmt` parser (§10) |
| `openvaf/hir_def/src/expr.rs`, `body/lower.rs`, `body/pretty.rs`, `openvaf/hir/src/body.rs`, `openvaf/hir_ty/src/validation/body.rs` | **`disable`**: `Stmt::Disable` + block-label recording on `Stmt::Block` through the HIR (§10) |
| `openvaf/hir_lower/src/ctx.rs`, `stmt.rs` | **`disable`**: `LoweringCtx::disable_scopes` named-block-exit stack; branch to the matching exit on `disable` (§10) |
| `disable_examples/` | New end-to-end verification of `disable` as break/continue (`break_demo.va`, `continue_demo.va`, `verify_disable.py`, `README.md`) |

No OSDI ABI header extension and **no `ngspice-46` C-side changes** were needed
— see §3.

## 12. Deferred to follow-up work

- **`log`-power tables.** The interpolation is linear-in-power; a `_log`
  variant that also interpolates the *power* column in log space (log-log
  interpolation) is not implemented, matching upstream's storage convention
  (`NoiseTable::new` never transforms the power column). Documented in §2.4.
- **A real diagnostic** for a missing/malformed `noise_table` file or an
  odd-length inline array (currently a graceful degrade to an empty/zero
  table), consistent with other soft-degradation sites in this codebase.
- **`load_noise_params` for tables** (only relevant to non-ngspice OSDI hosts
  that consume that ABI slot).
