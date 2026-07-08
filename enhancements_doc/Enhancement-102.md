# Enhancement-102 — name-then-range array-valued parameters

Enhancement-101's probe sweep surfaced a small asymmetry in how array
dimensions may be written on a parameter declaration. This enhancement closes
it.

## The gap

Verilog-AMS lets an unpacked-array dimension be written either *before* the name
(type-then-range) or *after* it (name-then-range). openvaf-r accepted both forms
for local variables, nets, and ports (Enhancement-18/89/91), but for
**parameters** only the type-then-range form parsed:

```verilog
parameter real [0:2] c = '{1.0, 2.0, 3.0};   // worked
parameter real c[0:2] = '{1.0, 2.0, 3.0};    // error: unexpected token '['
```

Since the more common spelling in practice is name-then-range (the dimensions
sit next to the name they belong to), the rejection was a real, if minor, gap.

## The fix

The array-variable grammar (`var()`) already accepted name-then-range
dimensions; the parameter grammar (`parameter()`) did not — it expected `=`
immediately after the name. The fix mirrors `var()`:

- **Parser** (`openvaf/parser/src/grammar/items.rs`): `parameter()` now consumes
  a `[msb:lsb]` run after the name before the `=`, so the dimensions become
  `Range` children of the `PARAM` node. `Param` gains a `widths()` accessor
  (`veriloga.ungram` + generated AST).
- **Item tree** (`openvaf/hir_def/src/item_tree/lower.rs`): `lower_param` now
  resolves the width set **per name** — the shared decl-level dims
  (type-then-range) if present, otherwise this name's own dims
  (name-then-range). Everything downstream — element expansion, per-element
  OSDI parameters, the initializer-length diagnostic (Enhancement-43) — is the
  existing Enhancement-14/15 machinery, reused unchanged.

Because the width is now resolved per name, a **multi-name** declaration may mix
widths, and **multi-dimensional** names work too:

```verilog
parameter real a[0:1] = '{10.0, 20.0}, b[0:2] = '{30.0, 40.0, 50.0}, g = 7.0;
parameter real m[0:1][0:1] = '{'{1.0, 2.0}, '{3.0, 4.0}};
localparam integer w[0:1] = '{3, 5};
```

## Verification

`paramarray_examples` (11/11): `paramarray_demo.va` declares single-name,
multi-name (mixed widths), multi-dimensional, and integer-`localparam`
name-then-range arrays, exposing element values as operating-point variables
read back in ngspice. It checks that (a) the file compiles, (b) every element
default resolves to its initializer value, (c) a per-element `.model` override
(`c[1]=99`) changes only that element (the OSDI per-element parameters are
intact), and (d) the type-then-range form still compiles. Full regression: all
verify suites plus the OpenVAF integration tests remain green.
