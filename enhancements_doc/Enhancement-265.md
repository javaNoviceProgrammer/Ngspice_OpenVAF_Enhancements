# Enhancement-265 — openvaf-r: `laplace_*`/`zi_*` coefficient argument panic → clean diagnostic

A fifth robustness-campaign find (following Enhancement-213/-220/-230/-263): a
malformed coefficient argument to an analog filter operator crashed the compiler
instead of producing a diagnostic.

## The panic

```verilog
analog V(p,n) <+ laplace_nd(1.0, 1.0, p);   // 3rd arg is a NET, not an array
```

The numerator / denominator (and, for the `*_zp`/`*_np`/`*_zd` forms, the
pole/zero) argument of a `laplace_*`/`zi_*` operator must be a **real coefficient
array** (LRM 9.19). Passing a bare **net reference** (`p`) there — or a branch, or
a string — exited `openvaf-r` with a panic (exit 101, "OpenVAF encountered a
problem and has crashed") rather than a type error.

Every *ordinary* value context already rejects a net used as a value cleanly:
`V(p,n) <+ p`, `x = p`, `p + 1.0`, and even the `laplace_*` **input** argument all
report *"type mismatch: expected real value but found net reference."* Only the
**coefficient** argument was different.

## Root cause

`laplace_*`/`zi_*` cannot use the generic argument-checking path (that path calls
`infere_expr` on every argument, which would reject a bare array-variable
reference before the operator's own special-case can accept it). So the num/den
arguments go through `hir_ty::inference::infere_array_arg`, which accepts two
shapes — an **array literal** (`'{a, b, c}'`) and a **bare array-variable
reference** (`coeffs` for `real coeffs[0:n];`) — and falls back to plain
`infere_expr` for anything else (a scalar coefficient, or a typo).

That fallback returned the inferred type **without requiring it to be a real
value**. A net reference infers to a "net reference" type, which was accepted, so
type checking passed and lowering ran. In `hir_lower`, decomposing the coefficient
"array" lowered the bare net reference as a value; `resolve_path`
(`hir/src/body.rs`) has no `Ref` for a net used as a value and hits its
`panic!("invalid HIR: path .. was not resolved")` invariant — a compiler crash on
malformed input.

## Fix

`hir_ty/src/inference.rs`, `infere_array_arg` fallback: after inferring the type,
**require a real value** — the exact requirement the `laplace_*` input argument and
every other value context already enforce:

```rust
let ty = self.infere_expr(stmt, arg)?;
self.expect::<false>(arg, None, ty.clone(), Cow::Borrowed(&[TyRequirement::Val(Type::Real)]));
Some(ty)
```

Now a net/branch/string coefficient raises the standard *"type mismatch: expected
real value but found …"* diagnostic and compilation stops before lowering — the
crash is gone. The array-literal and array-variable shapes are handled by the two
branches above and never reach the fallback, so they are unaffected; a real scalar
coefficient still matches (a length-1 vector), and an integer scalar matches with
the usual integer→real conversion (the same coercion the coefficient lowering
already applies).

The check lives in `infere_laplace` (not in the shared `infere_array_arg`, which
is also used by `case` discriminants/items and concatenations that legitimately
carry integer or string values), so those contexts are untouched.

### Also: empty direct denominator

The same fuzzing surfaced a second, adjacent crash: an **empty direct
denominator** — `laplace_nd(V, 1.0, '{})`. The state-space realization computes
`n = den.len() - 1` and reads `den[n]`; for a zero-length denominator that
underflows and indexes out of bounds, crashing. `infere_laplace` now also rejects
an empty **direct** denominator (`*_nd`/`*_zd`) with a type-mismatch diagnostic. An
empty *numerator* stays legal (it means `H(s) = 0`), and an empty *pole* list in
the `*_np`/`*_zp` root forms stays legal (the denominator polynomial is the empty
product, `1`) — only the one crashing shape is rejected. This needs the operator
kind, so `infere_laplace` now takes it as a parameter.

## Verification

`examples/vaflaplace_examples/verify_vaflaplace.py` (15 checks): six malformed
coefficient arguments (net as denominator, net as numerator, branch, string, net
in `zi_zp` roots, and an empty direct denominator) now emit a clean type-mismatch
error where each previously exited 101; and the well-formed shapes still compile —
real and integer-looking array literals, a scalar coefficient, a bare
array-variable reference, the `zi_nd` form, an empty *numerator* (`H(s) = 0`), and
an empty *pole* list (`*_np`, denominator polynomial `1`). A focused re-fuzz of
6000 random malformed `laplace_*`/`zi_*` calls against the fixed compiler finds no
surviving panic. Behaviour-preserving for valid input: the full dual-solver
example regression passes (including the `laplace`/`zi` filter models in the
complex-pole and RF-convolution suites), and openvaf-r's own `cargo test` is
unchanged — no MIR/OSDI snapshot moved (the fix only rejects invalid coefficient
arguments; no production model uses one).

## Scope

One source file (`openvaf/hir_ty/src/inference.rs`). No public interface, OSDI ABI,
or generated-code change.
