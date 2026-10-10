# Enhancement-844: a parameter without a type that reads itself, or a later parameter, is an error — it panicked the compiler on a query cycle

**Scope:** F7 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

openvaf-r: `openvaf/hir_ty/src/inference.rs`, a new `Ctx::param_ref_ty` used at the three
places a parameter read is typed.

`examples/paramcycle_examples/` (new). **Compiler only.**

**Suites:**
- [`paramcycle_examples`](../examples/paramcycle_examples/): 12 of 12. The 7 checks in [1] fail
  on the E-840 compiler with exit 101; the other 5 are controls.
- [`elabguard_examples`](../examples/elabguard_examples/): Enhancement-414's self-reference
  checks, unchanged.
- The compiler workspace tests: 222 passed, with the known sourcegen drift excluded.
- The full sweep: 551 of 551.

## What was wrong

```verilog
module m(a); inout a; electrical a;
parameter p p = 1;
analog V(a) <+ p;
endmodule
```

openvaf-r printed the right error, `unexpected token identifier; expected '='`, and then
panicked. It exited with status 101, printed the "please open an issue" banner and wrote a crash
log:

```
salsa::Cycle <- SyncMap::claim <- HirTyDB::inference_result <- hir_ty::db::param_ty
  <- Ctx::infere_expr <- … <- hir::diagnostics::collect_body_diagnostcs
```

A parameter declared without a type takes the type of its default. `param_ty` gets that type
by inferring the parameter's own body, which holds its default and its range. A read of a
parameter inside that body asked `param_ty` for the parameter read. When that was the
parameter itself, the inference asked for its own result while still computing it. salsa
detects the cycle and panics, since no recovery is declared for `inference_result`.

The parse error was not needed. The fuzz found the panic through error recovery, which leaves
the default reading the parameter. Every untyped spelling of a self-reference does the same:

| declaration | E-840 compiler |
|---|---|
| `parameter p = p;` | panic |
| `parameter p = 2*p + 1;` | panic |
| `parameter p = 1 from [0:p];` | panic |
| `localparam l = l + 1;` | panic |
| `parameter p = q; parameter q = p;` | panic |
| `parameter p = al; aliasparam al = p;` | panic |
| `parameter real p = p;` | "definition of 'p' references itself" |
| `parameter q = p; parameter p = 1;` | "references parameter 'p' defined afterwards" |

With a type, `param_ty` reads the declared type and nothing is inferred, so Enhancement-414's
"references itself" and the older "defined afterwards" errors were reported. A forward reference
that does not lead back is inferred without a cycle and reported the same way.

## The change

Validation already rejects every read in a parameter's body of a parameter that is not strictly
earlier in the file: itself, or one declared afterwards. Inference now types such a read
without asking for the parameter's type, when that type would have to be inferred. It gets
`Type::Err`, and the existing error is what the user sees. `Err` converts to and from every
type, so no type-mismatch errors follow from it.

Parameters share one arena per file, and its order is the order of the source. Every inference
left asks only for strictly earlier parameters, and their inference does the same, so no chain
can come back around. Typed parameters are read as before.

Code that compiles is untouched: none of its parameter bodies reads a parameter that is not
earlier. Each declaration in the table now reports its error with exit 65. The fuzz's spelling
reports the parse error and, from the recovery, "definition of 'p' references itself". The alias
case also reports Enhancement-517's "parameter alias 'al' referenced inside the module body"
(LRM 3.4.7), as it should.

## The checks

`paramcycle_examples`:
- **[1]** Each of the seven panicking spellings is reported with exit 65 and no crash.
- **[2]** The typed spellings, reported as before (control).
- **[3]** Untyped parameters reading earlier ones still compile and keep their defaults' types.
  `n = 3`, `k = n*2`, `x = 1.5`, `y = x*k` and the current `(k/4 + y)*1e-3*V` give 10 mA at 1 V:
  `k/4` is integer division, 1 and not 1.5 (control).
