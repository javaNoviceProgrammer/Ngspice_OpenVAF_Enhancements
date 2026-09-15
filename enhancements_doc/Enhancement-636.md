# Enhancement-636: an out-of-range array index at run time is reported

**Scope:** F2 of the
[2026-09-14 hunt](../docs/bug_hunts/2026-09-14_openvaf-r-parameters-arrays-and-hierarchy.md).
`parameter integer k = 3; real a[0:2]; … a[k]` read `a[0]` and `a[k] = v`
landed nowhere, with nothing said. Compiler:
`openvaf/hir_lower/src/expr.rs` (`lower_flat_array_index` judges every
dimension and reports through the deferred `$warning` path),
`openvaf/hir_lower/src/stmt.rs` (the write names its array),
`openvaf/hir_ty/src/{inference,diagnostics}.rs` (the constant-index refusal
is worded for an array). New suite
[`arrayrange_examples`](../examples/arrayrange_examples/) (9 checks per
solver). **Compiler side.**

**Suites:** `arrayrange_examples` 9 of 9 per solver, both solvers; `array`,
`mdarray`, `paramarray`, `rtdomain`, `funcarray`, `arrayout`, `arrayret`,
`arraycase`, `arraycast`, `arrayinst`, `arrayport`, `arrayscale`,
`tablearray` green; the `hir_ty` and `hir_lower` crate tests green; full
sweep 509 of 509.

## What was wrong

A dynamic index — a parameter, or a value computed while solving — is
lowered as a select chain over the array's elements (E-14/E-328): the flat
position is compared with each element's position and the element whose
position matches is chosen, `elems[0]` being the default. E-489 made that
the deliberate answer for an index that matches nothing: no pointer
arithmetic, so no index can read out of bounds, and no NaN, because a
variable index can pass through any value mid-solve and a NaN would poison
the iteration. What E-489 left in place was the silence: `a[7]` on `a[0:2]`
read `a[0]`, `a[7] = v` changed nothing, and a 2-D `m[1][-1]` on
`m[0:1][0:1]` was worse — its flat position folded to 1, which *is* an
element, so it read `m[0][1]` rather than the first element. A model kept
running on a wrong number with no way to know.

A constant index has always been refused at compile time, but as a bus:
`a[-1]` on `real a[0:2]` was `bus bit-select index out of range … this bus
was declared with width [0:2]`.

## What changes

* Every dimension is checked (`0 <= pos_k < size_k`, so the 2-D fold can no
  longer land on an element), and when any fails the access is reported
  through the same deferred `$warning` path a model's own `$warning` uses —
  once per accepted point, never for a transient mid-solve value (LRM
  9.4.6), immediately inside an event block or `analog initial` — naming the
  array, the index per dimension, the declaration and what the access does
  instead:

  ```
  OSDI(warn) n1: index [3] of `a`, declared [0:2], is out of range; the read returns a[0]
  OSDI(warn) n1: index [3] of `a`, declared [0:2], is out of range; the assignment is dropped
  OSDI(warn) n1: index [1][-1] of `a`, declared [0:1] [0:1], is out of range; the read returns a[0][0]
  ```

  The returned position is −1 for any out-of-range access, so a read is the
  first element in every case (E-489's answer, now uniform) and a write is
  dropped in every case. Variable arrays, parameter arrays (E-405) and the
  write path share the one lowering.
* The constant-index refusal says what it refused: `array index out of
  range … help: the array 'a' is declared [0:2]` (a 2-D one: `that dimension
  of the array 'a' is declared [0:2]`); a vectored net keeps `bus bit-select
  index out of range … this bus was declared with width [0:3]`.

Two things stay as they were, on purpose. The first-element read is E-489's
decision and this enhancement adds the voice, not a different value. And a
parameter-only access is init-resident code (E-535), so its warning prints
at setup like any `$warning` there — twice per operating point, because the
setup runs twice; that is the existing behaviour of every hoisted message and
is noted in the hunt's smaller notes rather than changed here.

## Verification

| check | result |
|---|---|
| `a[k]`, `k` = 3, −1, 100 on `a[0:2]` | reads `a[0]`, warned with the index and the declaration |
| `a[k] = 100`, `k` = 3 | dropped, warned as dropped |
| `k` = 2 read, `k` = 1 write | 30 mA, 140 mA, no warning |
| `a[1][-1]` on `a[0:1][0:1]` | reads `a[0][0]` (was `a[0][1]`), warned with both indices; `a[1][1]` silent |
| a parameter array, `k` = 7 | warned |
| a node-dependent index, sine input | warned at the 56 accepted points of the half period where it is out of range, silent in the other half |
| `@(initial_step) x = a[5]` | printed at the operating point |
| literal `a[-1]`, `a[0][3]`, a parameter array's `a[3]`, a bus's `a[4]` | "array index out of range" naming the array / the dimension; "bus bit-select" for the bus |
| `arrayrange_examples` | 9 / 9, both solvers |
| full sweep | 509 of 509 |
