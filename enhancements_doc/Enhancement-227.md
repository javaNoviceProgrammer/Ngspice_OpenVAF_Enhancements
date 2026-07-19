# Enhancement-227 — Touchstone `.sNp` parser crash hardening (fuzzing)

Continuing the fuzzing campaign onto the **Touchstone S-parameter parsers** —
external network-data files that are routinely produced by other tools (VNAs,
EM solvers, other simulators), so their parsers must survive malformed input.
ngspice has two:

- **`rdsnp`** — the Touchstone-v1 reader ([E-72](Enhancement-72.md)) that loads
  `.sNp` data into plot vectors;
- **`pre_snp`** — the convert-to-Verilog-A path ([E-200](Enhancement-200.md) /
  [E-201](Enhancement-201.md)) in `frontend/snp2va.c` that vector-fits the data,
  emits a `laplace_nd` Verilog-A model, and compiles it through openvaf-r.

Mutating valid `.s1p` / `.s2p` / `.s3p` files — corrupting the `#` option line,
the data values (NaN/Inf/overflow tokens, added/removed columns), duplicating
and deleting rows, truncating, flipping bytes — **and** mismatching the port
count encoded in the `.sNp` filename extension, then running each through both
readers, found:

- **`rdsnp`: clean** — 4,500 iterations, 0 crashes.
- **`pre_snp`: a heap-corruption crash** (SIGSEGV) — 103 crashes, **all** on a
  filename whose extension carried an absurd port count, e.g. `.s2147483647p`.

## Root cause

`snp2va.c` infers the port count `N` from the file extension `.sNp`:

```c
N = atoi(dot+2);      /* ".s2147483647p" -> N = INT_MAX */
```

with no upper bound. A huge `N` slips past the parse itself because the record
stride `rec = 1 + 2*N*N` and the per-record inner-loop bound `N*N` both use the
same wrapped `int` (`N*N` overflows to a small or zero value, so the token
layout stays self-consistent and no obvious error is raised). But `N` is then
stored in `out->N` and used **downstream** to size the vector-fit work:

```c
out->S  = malloc(nf * N*N * sizeof(cplx));   /* N*N overflows */
cplx *pv = malloc(N*N * sizeof(cplx));
```

The overflowing / mismatched allocation and the writes that follow corrupt the
heap. The failure is heap-layout dependent — the program typically aborts later,
on an unrelated `malloc`, which is why it presents as flaky.

The brute-force fallback (used when the filename gives no usable count) already
caps inference at **512 ports**:

```c
for (c = 1; c <= 512; c++) if (nn % (1 + 2*c*c) == 0) { N = c; break; }
```

so 512 is the parser's own established sanity bound — the filename path simply
wasn't held to it.

## The fix

Hold the filename-derived count to the same 512-port limit; above it, fall back
to inferring `N` from the data (one line, `frontend/snp2va.c`):

```c
N = atoi(dot+2);
/* Enhancement-227: reject an implausible port count from the filename
 * (e.g. `.s2147483647p`). N is stored in out->N and used to size the
 * downstream N x N vector fit; a huge N over-allocates / overflows and
 * corrupts the heap. Real Touchstone files have few ports -- above the
 * brute-force limit, drop back to inferring N from the data. */
if (N > 512)
    N = 0;
```

A valid file is unaffected: its extension (`.s2p`, …) is far below the cap, and
a genuinely mis-extensioned file now recovers the port count from the data
layout instead of trusting an absurd filename.

## Verification (`examples/snpfuzz_examples`)

`verify_snpfuzz.py` writes a valid `.s2p`, copies it to a `.s2147483647p` name,
and runs `pre_snp` on it several times (the pre-fix corruption was heap-layout
dependent), asserting a clean, bounded outcome rather than the previous SIGSEGV.
A regression check confirms a valid `.s2p` still converts through the full
pipeline (`pre_snp` → `.va` → openvaf-r → `.osdi`).

## Scope

ngspice frontend only, one file (`frontend/snp2va.c`); no device, solver, or
OSDI change. Full regression: 186/186.
