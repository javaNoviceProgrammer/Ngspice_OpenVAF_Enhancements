# vafhang_examples — Enhancement-264

openvaf-r large instance arrays: the module-flatten pass is now **O(N)** (was
O(N²), so a big array looked like a hang), and deep per-node **fan-in no longer
overflows the code-generator's stack**. Neither fix changes generated code.

| File | Property | Before | After |
|---|---|---|---|
| `flatten_array.va` | flatten scaling | `leaf u[0:16000]` on one node — elaboration was O(N²) (2k≈1.8s, 8k≈30s, **16k≈100s**), a large array looked hung | O(N): 16 001 instances compile in **~1 s**, 32 001 in ~2 s |
| `deep_fanin.va` | codegen stack | `leaf u[0:8000]`, distinct `R` per instance, all on one node → an 8 001-deep contribution chain → recursive OSDI codegen **overflowed the rayon worker stack** (SIGABRT) | compiles cleanly (~38 s) on a codegen pool with a generous worker stack |

The two `.va` files are deliberately different: `flatten_array.va` uses identical
contributions (which collapse, so it isolates the *flatten* cost), while
`deep_fanin.va` uses a distinct parameter per instance (so the contributions do
**not** collapse and it isolates the *codegen recursion depth*).

## What changed

* `openvaf/hir/src/elaborate.rs` — hierarchical-name resolution uses a
  precomputed ancestor set (O(1) prefix test) with a dot-free early-out, and the
  E-86 absolute-reference map is shared by reference (`Rc`) instead of deep-cloned
  into every per-instance scope.
* `openvaf/osdi/src/lib.rs` — OSDI code generation runs on a dedicated `rayon`
  pool built with a 256 MiB worker stack, so deep recursion completes instead of
  overflowing the small default stack. A thread's stack size cannot affect the
  emitted code.

## Verify

```
python3 verify_vafhang.py            # check A: flatten O(N) (fast, ~3 s)
python3 verify_vafhang.py --slow     # + check B: deep-fan-in stack guard (~40 s)
```

Check A runs in the routine regression sweep; check B is gated behind `--slow`
(or `NG_RUN_ALL=1`) because thousands of live contributions is genuinely a lot of
IR to compile. Passes iff every enabled check compiles cleanly within its time
bound — no hang, no crash.
