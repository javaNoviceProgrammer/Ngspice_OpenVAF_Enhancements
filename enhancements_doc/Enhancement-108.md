# Enhancement-108 — the `$ungetc` file-input function

Gap-hunt round 6 pushed the runtime-value batteries into `$random`/`$dist_*`
statistics, module **instance arrays**, and the `idt(ddt(x))` integrator ↔
differentiator round-trip — **all of which behaved correctly**:

- `$dist_uniform`/`$rdist_*` stay in range, are deterministic (same seed → same
  value), and change with the seed; distinct call sites draw from independent
  streams (the Enhancement-10/66 Monte-Carlo design).
- `rsub xarr[0:2] (p, n)` correctly instantiates **three** parallel devices
  (measured `G = 3` vs `G = 1` for a single instance).
- `idt(ddt(V))` reconstructs `V` to machine precision (max error 0.0).

The one clear in-scope gap it surfaced is the companion to Enhancement-107's
`$fgetc`.

## The gap

`$fgetc` (Enhancement-107) reads one character; its natural partner
`$ungetc(c, fd)` — push a character back so the next read returns it — was
missing (`'$ungetc' was not found`). It is the standard IEEE-1364 one-character
look-ahead used by hand-written parsers.

## The implementation

`$ungetc` is a two-argument file operation, so it extends the existing `FileOp`
machinery (the same path as `$fseek`, which already takes three arguments):

- **`syntax`/`hir_def`**: the interned name, `BuiltIn::ungetc` (`= 116`), and
  its scope registration.
- **`hir_ty`**: a two-integer signature `UNGETC(integer, integer) → integer`
  (impure), plus its `BUILTIN_INFO` entry.
- **`hir_lower`**: `BuiltIn::ungetc` lowers to `FileOp::Ungetc` (`num_args = 2`),
  runtime symbol `osdi_ungetc`.
- **`osdi/stdlib.c`**: `osdi_ungetc(c, fd)` looks up the descriptor and calls
  `ungetc(c, f)`; the argument order matches the Verilog `$ungetc(c, fd)` call
  (`c` first).

## Verification

`ungetc_examples` (6/6): a device reads a character, `$ungetc`s it, and confirms
the next `$fgetc` returns the same character (and that `$ungetc` returns the
pushed character). It then performs the classic one-character look-ahead —
accumulating the file's leading decimal digits into an integer (`"4271;…"` →
`4271`) and `$ungetc`-ing the first non-digit (`;`) so it stays in the stream.
The wider gap-hunt batteries behind this enhancement (`$random`/`$dist_*`
statistics, instance arrays, `idt(ddt(x))` round-trip) all behaved correctly.
Full regression: all verify suites plus the OpenVAF integration tests remain
green.
