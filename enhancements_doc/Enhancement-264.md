# Enhancement-264 — openvaf-r large instance arrays: O(N) flatten + codegen stack headroom

Two scalability/robustness defects on the same path — compiling a module that
instantiates a large array of a sub-module — surfaced by the continuing
robustness campaign (Enhancement-213/-220/-230/-263). A design with thousands of
instances either *looked like a hang* (super-linear elaboration) or *crashed*
(codegen stack overflow). Both are fixed; neither changes the code generated for
any existing model.

## 1. Hierarchy flattening was O(N²) in the instance count

`openvaf-r` flattens module instantiation before lowering: the Enhancement-5/-49/
-86 pass in `hir/src/elaborate.rs` renders one textual copy of a sub-module per
instance, each with a per-instance name prefix, and rewrites hierarchical name
references (`u.x`, cross-instance `$root…` paths) to the flattened names. For an
instance array `leaf u[0:N]` this runs N times.

Three steps inside that per-instance work were themselves O(N), making the whole
pass **O(N²)** — doubling the instance count *quadrupled* elaboration time
(≈2 k → 1.8 s, 8 k → 30 s, 16 k → 100 s), so a large array was indistinguishable
from a hang:

1. **Hierarchical-name resolution re-scanned every prefix per token.**
   `find_instance_path_holes` walked the instance-prefix map with
   `.keys().any(|k| …)` for *every* dotted chain it examined — O(number of
   instances) per token.
2. **…and it was called per port binding, per instance.** Port-binding
   substitution invoked the resolver on each connection of each rendered
   instance, multiplying step 1 by N again.
3. **Each per-instance scope deep-cloned the absolute-reference map.** The E-86
   cross-instance reference map (`abs_prefixes`, O(N) entries) was `clone()`d
   into every per-instance scope.

**Fix (all in `elaborate.rs`, behaviour-preserving):**

* Precompute an **ancestor set** once, giving O(1) "is this chain a hierarchical
  prefix?" tests instead of an O(N) scan.
* A **dot-free early-out**: every hierarchical reference contains a `.`, so a
  token with no dot (the overwhelmingly common case) skips resolution entirely.
* Share the absolute-reference map by reference — a small `Rc<AbsPrefixes>`
  (map + its precomputed ancestor set) is `Rc::clone`d (O(1)) into each scope
  instead of deep-copied.

The pass is now **O(N)**: a 16 001-instance array elaborates + compiles in ~1 s
(was ~100 s), 32 001 in ~2 s. Output is unchanged — the elaborated text and every
resulting `.osdi` are identical to before (only faster).

## 2. Deep per-node fan-in overflowed the codegen worker stack

When many instances contribute to the *same* node — e.g. `leaf u[0:8000]` where
every `leaf` drives the one node pair `(a,b)` and each has a distinct parameter
so the contributions do **not** collapse — the module's residual becomes a chain
of thousands of accumulated contributions. OpenVAF's OSDI code generator and its
automatic differentiation walk that chain **recursively**, and that recursion ran
on a `rayon` codegen worker whose default stack is only a few MB. Past ~8 000
contributions the worker overflowed its stack and the process aborted with
`thread … has overflowed its stack` / SIGABRT — a crash on large-but-valid input.

**Fix (`osdi/src/lib.rs`):** run OSDI codegen on a dedicated `rayon` thread pool
built with a generous worker stack (256 MiB) instead of the default global pool.
A thread's stack size is a property of the *thread*, not of the work — it cannot
change the emitted code — so the generated `.osdi` is byte-for-byte equivalent
(modulo the linker's already-nondeterministic build id); it only lets the deep
recursion complete. The 8 001-contribution design now compiles cleanly.

## Verification

`examples/vafhang_examples/verify_vafhang.py`:

* **Check A (always):** a 16 001- and a 32 001-instance array compile in ~1 s and
  ~2 s. The generous absolute time bounds (30 s / 45 s) would be blown by any
  re-introduced O(N²) behaviour (~100 s / ~400 s), so this is a standing guard
  against regression.
* **Check B (`--slow` / `NG_RUN_ALL=1`):** the 8 001-contribution deep-fan-in
  design compiles cleanly (rc 0, ~38 s), where the pre-fix binary aborted with a
  stack-overflow SIGABRT.

Behaviour-preserving for every existing model: the full dual-solver example
regression passes, and openvaf-r's own `cargo test` is unchanged — no MIR/OSDI
snapshot moved (the flatten fix only reorders/accelerates identical work; the
stack fix is a thread property with no effect on output).

## Scope

Two source files: `openvaf/hir/src/elaborate.rs` (the O(N) flatten) and
`openvaf/osdi/src/lib.rs` (the codegen stack pool). No public interface, no OSDI
ABI, and no generated-code change. Extreme instance counts remain bounded by the
existing 1 M instance-array / generate-loop caps and by downstream compile cost.
