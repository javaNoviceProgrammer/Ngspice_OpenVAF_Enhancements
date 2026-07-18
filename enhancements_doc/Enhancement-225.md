# Enhancement-225 — ngspice command/expression-evaluator crash hardening (fuzzing)

The netlist parser is now heavily hardened ([E-212](Enhancement-212.md),
[E-222](Enhancement-222.md), [E-223](Enhancement-223.md)). This pass turns the
fuzzer on a different, previously-unfuzzed surface: the **interactive `.control`
command interpreter and the vector-expression evaluator** — `print` / `let` /
`plot` / `meas` / `fft` / `fourier` and the operators (`?:`, indexing `[ ]`,
ranges `[[ ]]`, arithmetic) that post-process simulation vectors.

Mutating command lines and expressions over a running circuit and executing each
under `ngspice -b` turned up memory-safety crashes (SIGSEGV / SIGABRT — ngspice
is C, so these are real). The first run found **62 crashes in 2,500 iterations**.
Iterating fix → re-fuzz across two fuzzer configurations and many seeds drove the
crash rate to **0** and surfaced **five distinct bugs** in three groups.

## Group A — degenerate-input heap overflows in the math transforms

`fft`, `deriv` and `fourier` each crashed on a **too-short (< 2-point) or
synthetic** vector — e.g. `fft(1)`, `deriv(vecmin(v(1)))` (a plot-derived scalar),
`fourier 1k deriv(vecmin(v(1)))`. The crashes were heap-layout dependent (the
`malloc` abort fires on a *later* allocation, not at the overflow), which is why
they looked non-deterministic and resisted reduction.

1. **`cx_fft`** (`maths/cmaths/cmath4.c`) — the Green's real/complex FFT `rffts`
   dereferences bit-reversal tables `BRLowArray[(M-1)/2]` that `fftInit()` only
   allocates for `M > 2`, so an input of ≤ 4 points read unallocated memory; and
   `time`/`xscale` were sized by the data `length` while the scale loops fill
   `pl_scale->v_length` entries and the scale vector uses `fpts` points, so a
   vector shorter than the plot's scale overran both. Fixed: pad to `N ≥ 8`, size
   the buffers for the largest fill, reject `length < 2` / scale-too-short.
2. **`cx_deriv`** (`maths/cmaths/cmath4.c`) — the polynomial-fit derivative reads
   `degree+1` points per fit; a length-1 input ran the fit / edge loops over too
   few points and overran the heap. Fixed: for `length < 2` return a zero vector
   (the derivative of a single point is undefined).
3. **`fourier`** (`frontend/fourier.c`) — a degenerate input gives a zero time
   span and overran the interpolation grid. Fixed: require ≥ 2 data points.

## Group B — `ft_ternary` NULL dereference

`frontend/evaluate.c` `ft_ternary()` evaluated the `?:` operator's condition and
its selected branch with **no NULL check**. When either fails to evaluate — e.g.
`1?0[3]:9`, where `0[3]` ("indexing a scalar") returns NULL — the code hit
`vec_copy(NULL)` (branch) or `cond->v_link2` (condition) and crashed. This was the
dominant crash: almost every fuzz hit contained a `?:`. Fixed with NULL guards on
both. An audit of the other `ft_evaluate()` call sites (`op_ind`, `op_range`, the
binary-op and `apply_func` paths) confirmed they already guard NULL — `ft_ternary`
was the sole gap.

## Group C — `meas` fixed-buffer overflow on a long expression

`frontend/com_measure2.c` formatted measure error messages into a **`char
errbuf[100]`** shared by the `measure_parse_*` helpers (passed by pointer). When a
measure expression fails to resolve, its *entire string* is written as the vector
name — `sprintf(errbuf, "no such vector as '%s'\n", meas->m_vec)` — so a measure
expression longer than ~80 characters (trivial: `meas tran m MAX (v(1)+v(1)+…)`)
overran the buffer and smashed the stack/heap → `SIGABRT`. The content was
irrelevant, only the length, which is why it resisted reduction. Fixed: a
file-scope `MEAS_ERRBUF_SIZE` and a bounded `snprintf` at every write (28 sites).

*Not a bug:* `dowhile 1 … end` (a true constant condition with no `break`) is an
intentional infinite loop — the fuzzer flags it as a HANG, but it is correct
behaviour.

## Method

The fuzzer runs a valid `.tran` circuit, then appends a mutated `.control` block
(recursively-generated expressions plus commands like `print`/`let`/`plot`/`meas`/
`fft`/`fourier`/`compose`/`reshape`/`define`), classifies each run `OK` / `CRASH`
(killed by a signal) / `HANG` (timeout), and saves every crashing input. Because
the heap corruption aborted on a *later* `malloc`, crashes were confirmed
deterministic by repeated runs and each read at the source; fixes were applied one
at a time and the fuzzer re-run to convergence.

## Verification (`examples/cmdfuzz_examples`)

`verify_cmdfuzz.py` (13 checks) pins every fix with a minimal repro per root
cause — `fft(1)`/`fft(vector(3))`/`fft(vector(5))`, `deriv(vecmin(v(1)))`,
`fourier 1k deriv(vecmin(v(1)))`, the three ternary NULL forms
(`0[3]?9:9`, `1?0[3]:9`, `0[3]?0[3]:0[3]`), and a long `meas … MAX (v(1)+…)` — each
now a clean, bounded outcome (the crash-guard ones run several times, since the
pre-fix corruption only crashed on some heap layouts). Regression checks confirm
normal post-processing is unchanged: `fft(v(1))` and `deriv(v(1))` still transform,
a valid `?:` still selects the right branch, and ordinary indexing `unitvec(5)[2]`
still works.

## Scope

ngspice frontend / math only, four files (`frontend/evaluate.c`,
`frontend/com_measure2.c`, `frontend/fourier.c`, `maths/cmaths/cmath4.c`); no
device, solver, or OSDI change. Full regression: 184/184.
