# Enhancement-389 — closing the open openvaf-r items

An audit of everything still recorded as open for `openvaf-r` found four items —
one silent simulator hang, two language/feature gaps, and the pair of code
generators [E-379](Enhancement-379.md) had to quarantine. All four are fixed
here. The same audit retired six items that were recorded as open but had in
fact already been closed (see the end).

## 1. A loop whose control variable is written but never changes

[E-375](Enhancement-375.md) rejects a loop that provably cannot finish, because
there is no correct object code for such a model — it can never complete one
evaluation. It asked whether the condition's variables are **written**, which is
not the same question as whether they can **change**:

```verilog
for (k = 0; k < 10; k = k + 0)   // writes k on every pass, never changes it
    x = x + 1.0;
```

compiled cleanly, emitted a valid `.osdi`, and then hung ngspice at the operating
point with **no diagnostic at all** — exactly the outcome E-375 exists to
prevent, reached by a different shape. `k = k`, `k = 0 + k`, `k = k - 0`,
`k = k * 1`, `k = k / 1` and the same writes in a `while` body all behaved the
same way.

A write that provably leaves the value alone is no longer counted as progress.
The arithmetic identities are recognised **only on integers**: on reals
`k = k + 0.0` is not quite the identity — it turns `-0.0` into `+0.0`, and a
condition can observe that (`1.0/k < 0` flips from `-inf` to `+inf`), so a loop
really can terminate because of it. This analysis is sound in the reject
direction, so reals get only the exact copy `k = k`.

**What must keep compiling matters more than what is now rejected.** `k = k - 1`
looks just as wrong and is *not* rejected: it terminates by 32-bit signed wrap
after about 2³¹ iterations (measured, `i(v1) = -2.147e+06`, exit 0) —
pathologically slow, not infinite.

## 2. ANSI-style analog function arguments

Only the separated form was accepted. Both

```verilog
analog function real f; input real x; ...        // combined declaration
analog function real f(input real x); ...        // ANSI header
```

were parse errors (`unexpected token 'real'` / `unexpected token '('`). Both now
work, and in an ANSI header a later argument may restate neither direction nor
type — `f(input real x, y)` gives `y` both of `x`'s, per the LRM.

The type is genuinely **applied**, not merely parsed and discarded: an `integer`
argument declared either way rejects a real literal exactly as the separated form
always did. Array arguments still need the separated form; the declaration-level
range machinery has no counterpart in these positions, and that limit is recorded
in the handbook rather than silently hit.

The implementation is deliberately small. `FunctionArg` gained an optional type
and `FunctionArg::ty()` prefers it; the separated form leaves it `None` and takes
its type from the matching variable declaration as before. Nothing downstream
changed, because `declarations` fed exactly one thing — the argument's type —
while name resolution has always used `FunctionArgId` directly.

## 3. `$table_model` with runtime array data

The data had to be a compile-time literal or a data file. Array *variables*
filled in by the body — the LRM p274 form — were rejected with
`'xs' requires a bit-select [i]`, an error about the wrong thing.

```verilog
real xs[0:3]; real ys[0:3];
analog begin
  xs[0]=0.0; ... ys[3]=scale*9.0;              // depends on a model-card parameter
  I(p,n) <+ 1e-3*$table_model(V(p,n), xs, ys, "1L");
end
```

Inference needed its own path (the generic one calls `infere_expr` on every
argument, which rejects a bare array reference before `infere_array_arg` can
special-case it — the same reason `laplace_*` has one), and lowering interpolates
with the abscissae as MIR values instead of constants.

The shape is otherwise **identical to the compile-time interpolator, on purpose**:
same segment expressions, same select chain, so `mir_autodiff` differentiates it
the same way. The small-signal conductance is the exact analytic segment slope —
`3.000000000000e-03` for a slope of 3 — and matches the compile-time table's to
every printed digit. The table must be ascending in `x`, which the LRM already
requires and which cannot be checked here: those values do not exist at compile
time.

## 4. The two quarantined code generators

E-379 found both `sourcegen` tests broken and `#[ignore]`d them rather than
repair ~370 enhancements of drift. Running either deleted checked-in source.

**`gen_osdi_structs`** was behind for two reasons, and only one was about the
header having grown:

- `trim` skipped whitespace but **not comments**, so the first `/* … */` written
  inside a struct body left `parse_ty` looking at `/` and the `unwrap()`
  panicked. Documenting a header field is ordinary practice; the parser simply
  could not read it.
- comments were then **discarded**, so regenerating deleted the documentation the
  checked-in files carried — which is why running it always looked destructive.
  They are now carried onto the generated item as doc comments, from the header,
  where a field's explanation belongs. (`quote!` cannot emit `///`, so the
  attributes it does emit are rewritten to doc comments after formatting.)

Running it then surfaced what the drift had hidden: `EVAL_RET_FLAG_DISCONT` was
in the header but **missing from the generated Rust**, and
`OSDI_VERSION_MINOR_CURR` read 4 in the header and 5 in the generated file while
the compiler stamps **7** (`OSDI_VERSION` in `osdi/src/lib.rs`, the value ngspice
gates on). A reader had three answers and no way to tell which was live; nothing
reads the generated constant, so the header now says 7 as well.

**`ast`** was behind in three ways, each hand-patched around in the output:

- `KINDS_SRC` was missing 8 keywords and 11 node kinds — `casex`/`casez`,
  `repeat`, `do`, `paramset`/`endparamset`, `defparam`, `or`, and the
  concat / replication / generate-if / generate-case / disable / paramset nodes
  — so regenerating deleted real language features shipped by earlier work.
- `veriloga.ungram` had no rules for those node types at all.
- the generator emitted one accessor per field, but the AST carries a dual
  singular/plural pair (`width:Range*` → `width()` **and** `widths()`), and
  `{n{…}}` needs its replicated `elems` to skip the repetition count that
  precedes them. Both are now derived: a singular label gets both accessors, and
  a repetition skips the preceding single fields **of its own type**, excluding
  its own singular companion — the subtlety that first produced a wrong
  `BitSelectExpr::indices()` and broke `bus_basic.va`.

Regeneration is now **purely additive** against what was checked in: no struct,
accessor or enum variant is lost. It gains `DoWhileStmt`'s paren/semicolon tokens
and three `width()` accessors the grammar always implied. That property is what
makes the tests safe to run, and it is now enforced by running them.

`cargo test --workspace`: **207 passed / 158 ignored → 209 passed / 156
ignored.**

## Verification

`examples/vafopenitems_examples` — 28 checks, **28/28 fixed, 11/23 pre-fix**
(fewer checks run pre-fix, because the ones gated behind a successful
`$table_model` compile never execute).

Twelve of the 28 are the accept half, and they are the ones that matter: making a
compile-time check stricter is the change that can break working models, so every
terminating loop shape is re-run and its result checked numerically, and both
compile-time `$table_model` forms are re-proved including their conductance.

Output-preserving on the whole model corpus: **124/124 byte-identical `.osdi`**
(sha256, compiled to the same output path — the file embeds its own name, so
comparing across directories always "differs"). The corpus also replays through
an **assertions-enabled** build with **0 panics**, which is where the last
deferred item from [E-317](Enhancement-317.md) — an assertions-only PHI type
mismatch — would have shown up; it no longer reproduces.

Regression 312/312 → **313/313**.

## Retired: recorded as open, already closed

The audit that produced this change also found six items still recorded as open
that were not. They are noted here so the next audit does not re-tread them:
the `while (1)` CFG crash (closed by [E-375](Enhancement-375.md)), runtime shift
masking (E-335 — re-verified: `1 << nsh` with a runtime `nsh = 32` yields 0, not
the masked 1), the 65-nested-`ddx` bitset panic (E-331), the `builder.rs:143`
read-before-loop ICE (E-308), the missing file/string system functions (all
present; `is_unsupported` now gates nothing), and round-7's six "still open"
findings (all fixed by E-335/E-336).
