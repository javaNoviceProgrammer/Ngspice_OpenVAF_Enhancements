# Enhancement-30 — variadic `analysis(arg1, arg2, ...)` (version11)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to support the **multi-argument list form** of the Verilog-AMS
`analysis()` system function.

## What `analysis()` is

`analysis()` (Verilog-AMS LRM 4.7.1) queries the analysis currently being run. It
takes a **list** of analysis-name strings and returns true (1) if the current
analysis matches **any** of them:

```verilog
if (analysis("ic", "dc"))         ...   // static / DC-like phases
if (analysis("ac", "noise"))      ...   // small-signal phases
```

Recognised names are `"ac"`, `"dc"`, `"tran"`, `"ic"`, `"static"`, `"noise"`,
`"nodeset"`. Several can hold at once — e.g. an operating point sets both
`"static"` and `"dc"`.

## The bug

The single-argument form already worked end-to-end (the stdlib `analysis()` reads
`sim_info->flags` and ngspice sets those flags correctly for op/dc/ac/tran/noise).
But the builtin was declared with exactly **one** signature:

```rust
ANALYSIS = const {
    fn ANALYSIS_SIG(Val(String)) -> Integer;
}
```

so `max_args = 1`, and any list form was rejected at compile time:

```
error: invalid argument count: expected 1 arguments but found 2
  |     if (analysis("ac", "tran")) ...
```

Only `analysis("ac")` compiled — you had to chain `analysis("ac") || analysis("tran")`
by hand, which is not what the LRM prescribes.

## The fix

Two small changes:

1. **`hir_ty/src/builtin.rs`** — `analysis` is redefined as a **varargs** builtin
   (like `$display`/`$limit`): one mandatory `String` argument, no upper bound.
   ```rust
   const ANALYSIS: BuiltinInfo = BuiltinInfo::varargs(
       &[SignatureData { args: Cow::Borrowed(&[Val(String)]), return_ty: Type::Integer }],
       false,   // pure / read-only, no side effects
   );
   ```
   The generic vararg path (`max_args == None`) accepts the extra arguments; the
   now-unused `ANALYSIS_SIG` signature index is removed.

2. **`hir_lower/src/expr.rs`** — the lowering emits the `Analysis` callback for
   **each** argument and **bitwise-OR**s the results:
   ```rust
   BuiltIn::analysis => {
       let mut acc: Option<Value> = None;
       for &arg in args {
           let name = self.lower_expr(arg);
           let hit = self.ctx.call1(CallBackKind::Analysis, &[name]);
           acc = Some(match acc { None => hit, Some(prev) => self.ctx.ins().ior(prev, hit) });
       }
       acc.unwrap()   // min_args == 1 guarantees ≥1 argument
   }
   ```
   OR (not a sum) matters: at an operating point both `"static"` and `"dc"` return
   1, so a sum would yield 2 — the bitwise OR clamps the result to a proper 0/1.

No OSDI ABI change and no ngspice change — the stdlib `analysis()` and ngspice's
flag-setting were already correct; only the compiler front-end arity was wrong.

## Verification — `analysis_examples/`

`analysis_demo.va` is a conductance that is `g_static` at the DC operating point and
`g_dynamic` for the dynamic analyses, selected by a single list-form call
`if (analysis("ac", "tran", "noise")) g = g_dynamic;`. `verify_analysis.py`
(ALL PASS) checks, end-to-end through version11's own `openvaf-r` + `ngspice`:

1. the multi-argument list form **compiles** (it used to be a hard error);
2. **DC** → `g_static` (none of `ac`/`tran`/`noise` match);
3. **AC** → `g_dynamic` (matches `"ac"`);
4. **TRAN** → `g_dynamic` (matches `"tran"`);
5. **OR, not sum** — `analysis("static","dc","ic")` at `.op` returns exactly 1,
   even though both `"static"` and `"dc"` are set.

Single-argument `analysis()` is unchanged and still works (regression-checked
against `simparamstr_examples/`).
