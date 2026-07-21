# vafcrash4_examples — Enhancement-263

openvaf-r robustness: three compiler **panics** found by a fuzzing campaign,
each turned into a clean compile or a clean diagnostic.

Three fuzzing strategies were run against the committed `openvaf-r` — byte/token
mutation of the whole `.va` corpus, grammar-aware *structured* adversarial
inputs, and *valid-but-pathological* modules that compile through to the backend
— and each surfaced one distinct panic (the E-213 class: memory-safe, caught by
the panic hook, but a crash instead of a diagnostic):

| # | Reproducer | Cause | Fix |
|---|---|---|---|
| 1 | `nested_ddt.va` | deeply nested `ddt`/`idt`/`absdelay` → a cached value with no init-time definition (`ValueDef::Invalid`) crashed the instance-setup cache builder and the OSDI backend | `sim_back/init.rs`: substitute a constant init value into eval / default an `Invalid` mapping to 0 instead of feeding it to the cache-slot codegen |
| 2 | `ddx_badunknown.va` | `ddx(V,5)` — a non-probe 2nd argument — crashed `hir_lower` (`unwrap_param`); the type checker's diagnostic was dead code (it tested the ddx call, not the unknown) | `hir_ty/inference.rs`: test the *unknown* → clean "invalid ddx unknown" error |
| 3 | `malformed_module.va` | a malformed module whose item *tree* recorded an instantiation but whose parsed *AST* item list was empty crashed the hierarchy-flatten pass (`items.first().unwrap()`) | `hir/elaborate.rs`: empty item list → return the module verbatim (no-op) |

## Verify

```
python3 verify_vafcrash4.py
```

Passes iff none of the three reproducers CRASH or HANG — each now compiles
cleanly (#1) or emits a clean diagnostic (#2, #3). Full dual-solver regression
(214/214) and openvaf-r's own `cargo test` are unchanged: no production model
exercises the fixed paths.
