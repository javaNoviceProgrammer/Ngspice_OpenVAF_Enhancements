# lrmosdi — the ngspice OSDI layer, audited (Enhancement-529)

The conformance audit's last area: the loader and its guards. This suite
pins the fixes:

- **Original-OpenVAF v0.3 objects are rejected** with a recompile
  message. The old acceptance path read them through the extended
  in-repo layout — misreading node records (48- vs 56-byte stride),
  reading past the 0.3 descriptor's end, and calling the five-argument
  0.3 `load_noise` with four — wrong DC metadata and a transient SIGSEGV
  with zero diagnostics. `fake03.c` here is a minimal *functional* 0.3
  object written strictly against the published spec; the suite compiles
  it with the host `cc` and asserts the clean rejection.
- **A negative multiplicity is warned and ignored on every route** —
  `alter @n1[m]=-2` included, which used to apply it (a resistor model
  *sourcing* +4 mA; `.noise` printing `nan` through the compiled
  `sqrt(m)` factor). `m=0` stays the silent disable-this-instance idiom
  (E-426) and positive `m` scales exactly.
- **No phantom parameter row**: the synthesized `m`-alias IFparm slot is
  counted only when the descriptor carries `$mfactor`, so devhelp never
  shows a `(null)` keyword row.
- The **`$limit` unknown-name fallback** (E-520, LRM 9.17.3) re-pinned
  from the layer side: the model loads with the no-limiting warning and
  runs.

The OpenMP eval branch's `@(initial_step)` parity fix (a task-local
`OsdiSimInfo`) is compile-checked; the committed binaries are built
without OpenMP.

Run `python3 verify_lrmosdi.py` — 10 checks, both solvers.
