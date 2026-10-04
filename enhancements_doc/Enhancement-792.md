# Enhancement-792: a real constant converted to an `integer` it cannot hold draws L030, and the run-time conversion saturates on every platform — x86-64 kept the low 32 bits of libc `lround`

**Scope:** D2 of the
[openvaf-r hunt of 2026-10-04](../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md).
openvaf:
- `hir_ty/src/validation/body.rs`: `BodyValidator::check_real_constant_to_int`, called for an
  inferred integer cast and for a `repeat` count; the `RealConstantSaturates` diagnostic.
- `hir_ty/src/validation.rs`: its report, under lint L030 `lossy_integer_constant`.
- `mir_llvm/src/builder.rs`: `FIcast` is now `llvm.round.f64` followed by
  `llvm.fptosi.sat.i32.f64`; new helper `call_intrinsic1`.
- `mir_llvm/src/intrinsics.rs`: the two intrinsics.
- `mir_interpret/src/lib.rs`: a comment only.

`examples/vafslips_examples/` (section [2], twenty-three checks). **openvaf only.**

**Suites:** [`vafslips_examples`](../examples/vafslips_examples/) 67 of 67 per solver. On the E-790
binaries, 6 of the 23 checks in [2] fail: the six compile-time warnings. The run-time checks pass
there on AArch64 and are what the x86-64 CI legs exercise. Also run: `hunt3diag` and `powguard`
(the integer power and its saturating cast); the workspace tests; the corpus census (below); the
full sweep, 537 of 537.

## What was wrong

**Silent at compile time.** E-590 made L030 report a constant an `integer` cannot hold in two
forms: a literal wider than 32 bits, and an integer parameter's default. A real constant
converted to an integer anywhere else was silent:
- `ic = 1e20;` ran as 2147483647;
- `ic = -3e9;` as -2147483648;
- `repeat (1e10)` looped 2 147 483 647 times.

**Different by platform at run time.** E-392 gave the conversion its rule: round to nearest
(ties away from zero), and saturate. The constant folder (`val.round() as i32`) and the MIR
interpreter follow it. The code generator emitted `llvm.lround.i32.f64`, which follows it only on
AArch64, where it is one `fcvtas`. x86-64 lowers it to a tail call of libc `lround`. That returns
a 64-bit `long` on Linux and macOS, and the caller kept the low half. On Windows, `long` is
32 bits and C leaves the out-of-range result unspecified.

Each lowering was linked into one test program, compiled for x86-64 and arm64 and run on the same
machine (x86-64 under Rosetta):

| value | folded, AArch64 | x86-64 (old) | x86-64 (new) |
|---|---|---|---|
| 2147483647.5 | 2147483647 | -2147483648 | 2147483647 |
| 3e9 | 2147483647 | -1294967296 | 2147483647 |
| -3e9 | -2147483648 | 1294967296 | -2147483648 |
| 1e20 | 2147483647 | -1 | 2147483647 |
| inf | 2147483647 | -1 | 2147483647 |
| NaN | 0 | 0 | 0 |

On an x86-64 build, a card value `v=3e9` stored into an integer was -1294967296, while the literal
`3e9` folded to 2147483647. `$rtoi` lowers through the same conversion and had the same split.

## The change

**Compile time.** A real-typed expression converted to an `integer` whose value is a compile-time
constant is checked. This covers an assignment, an argument, an index (any inferred cast) and a
`repeat` count, which `lower_repeat` converts itself. If the constant rounds outside 32 bits or is
a NaN, it draws L030:

```
warning[L030]: the real 100000000000000000000 does not fit a 32-bit integer
  |
6 | i = 1e20;
  |     ^^^^ converted to an `integer` it saturates to 2147483647
```

E-590's two forms keep their own messages and are not reported twice: the literal wider than
32 bits, and the parameter default. `openvaf_allow="lossy_integer_constant"` silences it as
before.

**Run time.** `FIcast` is `llvm.round.f64` followed by the saturating `llvm.fptosi.sat.i32.f64`.
NaN gives 0. That is the folder's rule exactly. AArch64 still emits the single `fcvtas`. x86-64
calls `round` and then clamps with `cvttsd2si`.

## The checks

vafslips [2]:

- L030 with the value and what the conversion stores, for:
  - `1e20` and `-3e9`;
  - `1e10 * 2`;
  - a `localparam` of 5e9;
  - 2147483647.5;
  - `repeat (1e10)`;
- no word for:
  - 2147483647.4 and -2147483648.4;
  - 2.5;
  - a parameter (a run-time value);
  - an allowed line;
- one warning each for the wide literal and the integer default;
- at run time, from model cards, both the conversion and `$rtoi`:
  - 3e9, -3e9, 1e20, -1e20, 2147483647.5, -2147483648.4, 2.5 and -2.5;
  - a NaN gives 0;
  - the folded `3e9` equals the run-time 3e9.

The 1 026 bundled Verilog-A files draw no new L030.

## Limits

- A value from a model card is still converted in silence, saturated now on every platform. A
  run-time warning would cost a compare at every conversion in every model.
