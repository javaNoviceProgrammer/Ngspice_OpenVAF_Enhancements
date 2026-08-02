# Variable-type example (version10, Enhancement-9)

Demonstrates `real`, `integer`, and `string` analog-block **variables**, and the
Enhancement-9 fix for uninitialized `string` variables.

## Background

`real` and `integer` variables were always fully supported. A `string`
variable worked only if it was given an initializer at declaration
(`string s = "x";`); an **uninitialized** `string s;` crashed the compiler,
because the type-based default-value assignment only handled `Real` (→ 0.0) and
`Integer` (→ 0) and fell through to an `unreachable!` for `String`
(`hir_def/src/body.rs`). Enhancement-9 gives `string` variables the LRM-correct
empty-string (`""`) default, so `string s;` works like the other types.

## The model

`vartypes.va` builds a conductance from all three variable types: `count`
(integer) resistors of `Rbase` (real) ohms combined per `mode` (string,
declared without an initializer and therefore defaulting to `""`).

## Running

```sh
../OpenVAF-master-20260610/target/opt/openvaf-r vartypes.va -o vartypes.osdi
python3 verify_vartypes.py
```

## Verified behaviour

```
  default (uninit string -> "" -> "series")    V(b)=0.666667  PASS
  Rbase=1500 (real param override)             V(b)=0.750000  PASS
```

- The uninitialized `string mode` defaults to `""`; the `mode == ""` test then
  selects `"series"`, giving `Rtot = Rbase*count = 2000` and `V(b) = 2000/3000`.
- `real` (`Rtot`, `Rbase`), `integer` (`count`), and `string` (`mode`) variables
  all assign, compare, and drive the output correctly at eval time.
