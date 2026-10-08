# Long vector/node-name overflow fix (Enhancement-237)

A follow-up to [E-236](../../enhancements_doc/Enhancement-236.md), from the same
memory-safety deep dive. The SPICE2-compatibility rewrites for `.print`/`.plot`/
`.four` output tokens — and the vector-name helper they feed — copied a
user-controlled, unbounded vector or node name into a fixed **`BSIZE_SP`
(512-byte) stack buffer**:

| function | file | rewrite | buffer |
|----------|------|---------|--------|
| `fixem()` | `dotcards.c` | `v(a,b)` → `v(a)-v(b)` (+ `vm/vp/vi/vr/vdb`) | `char buf[BSIZE_SP]` |
| `gettoks()` | `dotcards.c` | `i(x)` → `x#branch` | `char buf[513]` |
| `vec_basename()` | `vectors.c` | `strcpy(buf, v->v_name)` | `char buf[BSIZE_SP]` |

A `.print`/`.plot`/`.four` output token whose node/branch name(s) exceed the
buffer overran the stack — macOS aborts with a stack-smashing trap
(`SIGABRT`/`SIGTRAP`); elsewhere it is plain stack corruption. `vec_basename` is
reached by `.print`, `fft`, `spec`, `linearize`, and more, so the same crash
lurked behind several commands.

Fixing `fixem` alone was **not** enough — the same long name simply flowed
downstream into `vec_basename` and crashed there — which is why E-237 hardens all
three: each scratch buffer is now sized to its input (`fixem`/`vec_basename`
allocate to fit; `gettoks` builds the string with `tprintf`), and every write in
`fixem` is additionally a bounded `snprintf`. Long names are handled instead of
overflowing, with **no truncation**, so a valid long differential still computes
the right value. (The `vectors.c` recompile also surfaced three pre-existing
`-Wconversion` warnings on `v->v_type`, silenced with explicit casts.)

## Verify

```sh
python3 verify_nameovf.py
```

Four checks: a long `v(a,b)` on nonexistent nodes no longer crashes; a **valid**
long differential `v(A,B)` (v(A)=2, v(B)=1) runs and prints `v(A)-v(B) = 1.0`
exactly (proving no truncation); a long `i(x)` via `.four` (the `gettoks` path)
no longer crashes; and the ordinary short `v(1,2)` still rewrites to `v(1)-v(2)`
correctly.

## The output commands (Enhancements 811 and 812)

F20 and F21 of the
[2026-10-08 ngspice + OSDI hunt](../../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md)
are the same class, in the commands that show vectors:

- **[E-811](../../enhancements_doc/Enhancement-811.md).** `print` copied a vector's name into a
  512-byte heap buffer (`com_print`). A 512-character instance, node or Verilog-A parameter
  name corrupted the heap.
- **[E-812](../../enhancements_doc/Enhancement-812.md).** `display`, `load` and a noise plot's
  listing format each vector into a 512-byte stack buffer (`pvec`). A ~470-character name
  aborted every time.

Eleven more checks run those commands with 600- and 3000-character names, and check that the
whole name and its value are printed. They run under macOS Guard Malloc where it exists, which
faults at the overrunning access, so a regression fails every time and not now and then. The
script now has 15 checks; 10 of the 11 new ones fail on the E-810 binaries.

