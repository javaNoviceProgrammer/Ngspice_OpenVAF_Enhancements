# concat_examples — `{...}` concatenation & `{n{...}}` replication (Enhancement-34)

Demonstrates the Verilog-AMS **concatenation** and **replication** operators, using
**the committed** `openvaf-r` and `ngspice-46`.

## What was broken

OpenVAF conflated the two brace constructs: `{...}` was parsed as just another
spelling of the `'{...}` array-**aggregate** literal. Consequently:

- whole arrays could not appear inside `{...}` (`{p, q}` → "requires a bit-select");
- the replication form `{n{...}}` did not parse at all;
- string operands made a useless *string array* instead of the LRM's concatenated
  string.

## The fix

`{...}` is now the real **concatenation operator** (and `'{...}` stays the
aggregate literal, untouched):

```verilog
w = {half1, {3{k2}}, 3.0*k2};        // arrays + replication + scalars, flattened
scale = avg4({1, 3, 2.0, 2.0});      // concat as a whole-array function argument
tag = {"con", "cat"};                // runtime STRING concatenation -> "concat"
```

Numeric concats flatten scalars / whole arrays / nested concats into one flat
array; `{n{...}}` repeats the list (`n` a positive integer literal, diagnosed
otherwise); string concats produce a runtime string via the `$swrite` machinery.
Works in array assignment, function arguments, `laplace_*`/`zi_*` coefficient
vectors and `case`. Pure front-end change. See `../Enhancement-34.md`.

**Behaviour change**: nested bare-brace literals (`{{1,2},{3,4}}`) now *flatten*
(concat semantics); multi-dimensional aggregates use the LRM form
`'{'{..},'{..}}` as before.

## Run

```
python3 verify_concat.py
```

Checks (ALL PASS): compiles (arrays-in-braces / replication / string concat all
used to fail); the DC conductance equals `2·(3·k1 + 6·k2)` exactly for two
parameter sets (concat + replication + integer casts + string gate all correct);
`{0{...}}` and non-literal replication counts are clean diagnostics.
