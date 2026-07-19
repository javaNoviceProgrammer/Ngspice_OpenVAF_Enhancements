# Enhancement-237 — long vector/node names overflow fixed buffers in `.print`/`.plot`/`.four`

A follow-up to [E-236](Enhancement-236.md), from the same memory-safety deep
dive. Where E-236 fixed the measurement-name overflow, E-237 fixes the sibling
overflows that a long **vector or node name** triggers in the output path —
reproducible on the shipped binary.

## The bug

The SPICE2-compatibility rewrites for `.print`/`.plot`/`.four` output tokens, and
the vector-name helper they feed, each copy an unbounded user name into a fixed
`BSIZE_SP` (512-byte) stack buffer:

* **`fixem()`** (`frontend/dotcards.c`) rewrites a differential form like
  `v(a,b)` into `v(a)-v(b)` (and the `vm`/`vp`/`vi`/`vr`/`vdb` magnitude/phase/…
  variants) with, e.g., `sprintf(buf, "v(%s)-v(%s)", a, b)` into
  `char buf[BSIZE_SP]` — nineteen such writes.
* **`gettoks()`** (`frontend/dotcards.c`) rewrites `i(x)` into `x#branch` with
  `sprintf(buf, "%s#branch", x)` into `char buf[513]`.
* **`vec_basename()`** (`frontend/vectors.c`) does `strcpy(buf, v->v_name)` into
  `char buf[BSIZE_SP]`; it is reached by `.print`, `fft`, `spec`, `linearize`, …

`a`, `b`, `x`, and `v_name` all come straight from user output tokens with no
length check. A token whose name(s) exceed the buffer overruns the stack. On
macOS the canary fires and the process aborts (`SIGABRT`/`SIGTRAP`); elsewhere it
is plain stack corruption.

Reproduce on the stock binary:

```
* v(a,b) with long node names
v1 1 0 dc 1
r1 1 0 1k
.tran 1n 3n
.print tran v(aaaa…(400)…, bbbb…(400)…)
.end
```

→ `ngspice -b` dies with a signal (shell exit 133).

**Fixing `fixem` alone was not enough.** With *valid* long node names the rewrite
succeeds, and the resulting long `v(a)-v(b)` vector name then flows into
`vec_basename`, which crashes there instead — so the fix has to cover the whole
path.

## The fix

Size each scratch buffer to its input rather than a fixed 512 bytes:

* `fixem()` — allocate `buf` to `strlen(string) + 32` (the wrapper overhead is a
  small bounded constant) and make all nineteen writes bounded
  `snprintf(buf, bufsz, …)`; return the heap buffer directly.
* `gettoks()` — drop the fixed `buf[513]` and build the `"<name>#branch"` string
  with `tprintf("%s#branch", l + 1)` (right-sized allocation).
* `vec_basename()` — replace `char buf[BSIZE_SP]` + `strcpy` with `copy()` of the
  source (which allocates to fit), preserving the exact branch semantics.

Nothing is truncated, so a valid long differential still computes the correct
value. The `vectors.c` recompile also surfaced three pre-existing `-Wconversion`
warnings (`v->v_type`, an `enum simulation_types`, passed to `dvec_alloc`'s `int`
parameter); silenced with explicit `(int)` casts to keep the build warning-free.

## Verification (`examples/nameovf_examples`)

`verify_nameovf.py` (4 checks): a long `v(a,b)` on nonexistent nodes no longer
crashes; a **valid** long differential `v(A,B)` (v(A)=2, v(B)=1) runs and prints
`v(A)-v(B) = 1.0` exactly (proving no truncation); a long `i(x)` via `.four` (the
`gettoks` path) no longer crashes; and the ordinary short `v(1,2)` still rewrites
to `v(1)-v(2)` correctly.

## Scope

ngspice frontend only — `dotcards.c` (`fixem`, `gettoks`) and `vectors.c`
(`vec_basename`, plus three `-Wconversion` casts). No solver, analysis, device,
or compiler change; output values are unchanged. Full regression: 195/195.
