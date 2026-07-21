# Enhancement-263 — openvaf-r robustness: three compiler panics → clean errors

A robustness-fuzzing campaign on `openvaf-r` (the fourth such pass, following
Enhancement-213/-220/-230). Three fuzzing strategies were run against the
committed compiler: byte/token mutation of the full `.va` corpus (examples +
integration tests + test-data models), grammar-aware *structured* adversarial
inputs (malformed preprocessor / literals / attributes / ranges / analog
operators), and *valid-but-pathological* modules generated to compile all the
way through to the backend. Each strategy surfaced exactly one distinct panic —
three in total, all the E-213 class (caught by the panic hook, memory-safe, but
a crash instead of a diagnostic). All three are fixed.

## The three panics

**1. Nested analog operators → an undefined init-cache value
(`sim_back/src/init.rs`).** A valid module such as

```verilog
I(p,n) <+ absdelay(ddt(ddt(absdelay( ... ))), 1e-9, 1e-6);
```

crashed the whole compiler. A value tagged for the instance-setup cache maps,
in the *init* function, to a value with no defining instruction — for these
deeply nested `ddt`/`idt`/`absdelay` chains the init contribution collapses to a
`Const` or has no init definition at all (`ValueDef::Invalid`). `build_init_cache`
assumed every cached value is a computed instruction result and called
`unwrap_result()`/`unwrap_inst()`, and even once that was survived the OSDI
LLVM backend read a `BuilderVal::Undef`. Fix: before allocating a cache slot,
handle the non-instruction cases — **substitute a constant init value directly
into the eval function** (a `Float`/`Int`/`Str`/`Bool` constant needs no runtime
slot; eval simply uses the init-time value), and treat an **`Invalid`** init
mapping like the existing dead-value path (default to `0`). Only a genuine
instruction result takes the slot-and-optbarrier path. No cache slot or codegen
ever sees a constant/undefined value again.

**2. `ddx(f, <non-probe>)` → `unwrap_param` panic
(`hir_ty/src/inference.rs`).** `ddx(V(p,n), 5)` — a `ddx` whose second argument
is not a potential/flow probe — crashed in `hir_lower` at
`value_def(unknown).unwrap_param()`. The type-checker *had* a diagnostic for an
invalid ddx unknown, but its guard tested `expr` (the `ddx` call itself, which is
*always* an `Expr::Call`) instead of `unknown`, so the diagnostic was dead code
and the malformed call slipped through to codegen. Fix: test `unknown` — a
non-call unknown (a literal, a plain variable, …) now correctly raises
*"invalid unknown was supplied to the ddx operator"* and compilation stops
before lowering.

**3. Malformed module → empty item list with a recorded instantiation
(`hir/src/elaborate.rs`).** A malformed top-level module for which the item
*tree* recorded an instantiation but the parsed *AST* `module_items()` came back
empty (parser error-recovery and item-tree construction disagreeing) crashed the
Enhancement-5/-49 hierarchy-flattening pass at `items.first().unwrap()`. Fix:
when the AST item list is empty there is nothing to flatten, so return the module
text verbatim — the same no-op the pass already takes for a module with no
instantiations.

## Verification

`examples/vafcrash4_examples/verify_vafcrash4.py`: a minimal reproducer for each
of the three causes now terminates cleanly — the nested-analog-operator module
compiles to a valid `.osdi`, and the `ddx` and malformed-module inputs produce a
clean diagnostic — where each previously exited 101 (panic) on the shipped
binary. Behaviour-preserving for valid input: the full dual-solver example
regression passes (214/214, both solvers), openvaf-r's own `cargo test` suite is
unchanged (no MIR/OSDI snapshot changed — no real model exercises the new
paths), and a re-fuzz of the fixed compiler across all three strategies finds no
surviving panics.

## Scope

Three source files (`sim_back/src/init.rs`, `hir_ty/src/inference.rs`,
`hir/src/elaborate.rs`). The init-cache fix is the only one that can affect code
generation, and it only changes the handling of constant/undefined cached values
— which no production model produces (proven by the unchanged snapshot suite and
the clean 214/214 regression).
