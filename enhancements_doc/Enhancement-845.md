# Enhancement-845: a relational or logical result meets an integer as the integer 1 or 0 — a ternary, `==`, `!=` and `case` cast the integer to Bool, and an untyped parameter with such a default panicked the compiler

**Scope:** F1 of the
[second robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-second-robustness-campaign.md).

openvaf-r:
- `openvaf/hir_ty/src/inference.rs`:
  - `resolve_function_args`: one more tie-break among overloads that match equally well;
  - the `case` statement: a Bool case expression with an integer item is compared as an
    integer;
  - an untyped parameter's expected type.
- `openvaf/hir_ty/src/db.rs`: `param_ty`, through the new `param_value_ty`.

`examples/boolint_examples/` (new). **Compiler only.**

**Suites:**
- [`boolint_examples`](../examples/boolint_examples/): 30 of 30 per solver. On the E-844
  compiler, 11 fail. `boolparam.va` panics there, so its 10 checks cannot run. The 8 that pass
  are the first compile and 7 controls.
- The campaign's Family A (Verilog-A semantics against a Python reference) and Family B
  (random-expression derivatives against finite differences), re-run on their seeds and on
  fresh ones: 19 200 comparisons and 8 000 checks, no flags. Before, 16 and 5 flagged. Family B
  now includes the integer ternaries it had to leave out.
- The compiler workspace tests: 222 passed, with the known sourcegen drift excluded.
- The full sweep: 552 of 552.

## What was wrong

```verilog
parameter integer n = 5;
analog begin
  V(o1) <+ ((n > 0) ? n : (n < 0));    // 5 -- was 1
  V(o2) <+ (n == (n > 0));             // 0 -- was 1
  V(o3) <+ (n != (n > 0));             // 1 -- was 0
  case (n > 0)
    5: V(o4) <+ 1;                     // no match -- matched
    default: V(o4) <+ 2;
  endcase
end
```

The values were silently wrong, with exit 0, whether the operands were literals, parameters or
node voltages.

openvaf-r types a relational or logical result (`a < b`, `a && b`, `!a`, `$param_given(p)`)
as `Bool`. The LRM's are the integer 1 or 0, so where one meets an integer the integer must
survive. Overloads are tried in three stages:
1. signatures every argument converts to;
2. those whose arguments are semantically equivalent;
3. those matched exactly.

What is left after that is taken in table order. Integer and Bool are semantically equivalent,
so for an Integer and a Bool argument both the Integer and the Bool signature passed stage 2,
and neither was exact. Two tables list Bool first:
- `SELECT`, for `?:`;
- `ANY_COMPARISON`, for `==` and `!=`.

So both resolved to Bool, and the integer was cast to 0 or 1. Arithmetic, bitwise and
relational operators list Integer first and were right. The `case` statement typed its items
as its expression, so a Bool expression cast an integer item to Bool. An integer expression
with a logical item, the `case (1)` idiom, was already compared as an integer.

The campaign found it through Family A, which compiles random expressions three ways and
compares them with a Python reference that follows the LRM. All 16 of its mismatches in 9 528
comparisons were this. So were the 5 of Family B, through charges such as `((4 << 2) ==
(100 && 13)) ? 4 : -V(a,c)`, whose capacitance came out 0.

## The change

- **Overload resolution:** a fourth stage. Among the overloads still tied, keep those that do
  not narrow an integer argument to a Bool parameter, unless none does. Bool to Integer loses
  nothing, and `Type::union` already gives Integer for Bool with Integer. The ternary and the
  equality now resolve to Integer, and the logical operand is cast up.
- **`case`:** as Enhancement-647 does for a real item, a Bool case expression with an integer
  item is cast to Integer, and every item is expected as Integer.

An expression of two logical operands is still Bool, and nothing that resolved exactly or by a
single candidate changes.

## An untyped parameter with a logical default

The dig found the same Bool where a parameter's type comes from its default:

```verilog
parameter integer n = 5;
parameter pb = (n > 0);
```

A parameter declared without a type takes its default's type, here Bool. No parameter can have
that type, and the parameter lowering hit `unreachable!()` in `CmpOps::from_ty` and panicked.
It panicked even when the parameter was never read. The same happened for `&&`, `!`,
`$param_given(n)`, a `localparam`, an array of comparisons, and the ternary above. On the E-844
compiler all seven exit 101.

Such a parameter is now an integer, element-wise for an array. `param_ty` reports Integer
where the default is Bool, and the default is cast to it. `pb/2` is 0, by integer division, and
`pb=7` on a model card sets 7.

## The checks

`boolint_examples`, at a parameter and from a node voltage:
- **[1]** the ternary, with the logical branch on either side, and its controls: a real
  branch, and two logical branches;
- **[2]** `==` and `!=` against a logical result, `$param_given(n) == 2` among them;
- **[3]** `case (n > 0)` with the item 5, and the controls `case (n > 0) 1:` and `case (1)`;
- **[4]** the ternary into an integer variable;
- **[5]** the same at run time, from a node voltage;
- **[6]** `boolparam.va`: untyped parameters whose defaults are a comparison, `&&`, `!`,
  `$param_given`, a localparam, an array, and the ternary. Each reads as an integer (`pb/2` is
  0), and `pb=7` on the card is taken.
