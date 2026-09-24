# openvaf-r robustness campaign — hostile input, scale, and the run-time cost of what the compiler admits

**Date:** 2026-09-23, 18:16–20:05 (the last scale probes ran until about 20:00, the
write-up interleaved from 19:05 on), at head `5b0f96ee` (E-704, the cubic spline's end
conditions). **Binaries:** the repo's `OpenVAF-master-20260610/target/opt/openvaf-r`
(built 19:23 on 2026-09-22) and `ngspice-46/build/src/ngspice` (built 17:09 the same
day), both from the E-704 tree. **Method:** about 790 compiles and 160 ngspice runs, written
for the campaign and driven by a throw-away harness in the scratchpad (`hunt4/h4.py`,
`pA.py … pJ2.py`) that records the exit code, the signal, the wall time and the peak
resident size of every compile and greps its output for a panic, an assertion, a
stack overflow or a Rust backtrace. Unlike the LRM hunts, the question here was not
"is the answer right" but "does the compiler stay up, stay bounded and say something
true": every probe is either hostile (bytes, structure, recursion, absurd arguments),
oversized (tokens, modules, ports, nodes, arrays, coefficients, data files), or an
argument the compile-time checks admit whose run-time cost was then measured on
ngspice. Nothing was fixed; this is the list.

The ground: the front end under hostile bytes and structure (empty and whitespace-only
files, a BOM, CR and CRLF endings, NUL bytes, invalid UTF-8, unterminated comments,
strings and modules, a 1 MB line, 100 k-character identifiers, 1 MB string literals,
50 000-entry attribute lists, every compiler directive); the preprocessor (self- and
mutually-recursive macros, a 2²² token blow-up, 10 000 defines, a 1 MB macro body, a
100-argument macro, unbalanced arguments, 10 000-deep `ifdef` nesting, includes of
the file itself, of a directory, of `/dev/null`, of a binary file, of `/etc/hosts`,
300 deep, a 1 MB file 2 000 times); the command line (every hostile path and flag
value); declarations at scale (50 000 parameters, 2 000 ports, 5 000 internal nodes,
arrays to 2³¹ elements, self-referential and mutually-referential parameters, 5 000-deep
parameter chains, alias cycles, `genvar`, constant-bound, `repeat` and `while` loops,
recursive and 5 000-argument and 5 000-deep function chains); constant folding at
the edges (every division, power, logarithm and trigonometric domain, integer
overflow in every operator, every literal form and scale factor, NaN and infinity in
every comparison and control statement, 32 format-string shapes, widths and
precisions to 10²⁰); semantic shapes that could crash the lowering (every misuse of
access functions, branches, `ddx`, `ddt`, `idt`, events, contributions, `$limit`,
`$bound_step`, `$discontinuity`, the filters, the noise functions, the distributions,
`$simparam`, `$port_connected`, `$param_given`, assignment to every non-variable,
indexing of every non-array, 100 000-deep unary and parenthesis nesting, 5 000-deep
calls and concatenations, 5 000-item `case` and `if` chains); data files for
`$table_model` and `noise_table` (missing, a directory, `/dev/null`, empty, one row,
one column, unreadable, binary, NUL, NaN and infinity, hex, 100 000-digit numbers,
10⁶ rows, 100 MB, 1 000 columns, 100 000 isolines, CRLF, tabs and commas, a BOM, a
1 MB file name, a newline in the name, grid headers of 10⁹); code generation at scale
(20 000 contributions, 100 filters of 20 poles, 1 000 table calls, 2 000 `cross`
events, a 150-port full conductance matrix, 200-deep and 10 000-wide hierarchies,
10 000 function calls, 50 000 variables); and the run-time cost, on ngspice, of the
distributions with a large degree and of NaN and infinite arguments the checks let
through.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--a-table-file-of-100000-rows-overflows-the-compilers-stack) | *(fixed in [E-705](../../enhancements_doc/Enhancement-705.md): the interval search is a binary tree over the segment's parameters — branches above 64 knots, branchless selects below — the MIR post-order walk is iterative and the CFG simplifier no longer restarts at every block it removes; 100 000 rows compile in 14 s, 30 000 in 3 s)* a `$table_model` data file of 100 000 rows (1.3 MB) aborts the compiler with "thread 'main' has overflowed its stack" 4 s in, under linear interpolation, in the MIR optimiser (the unoptimised MIR dump completes, `--dry-run` exits 0); the same for a 2-D file of 100 000 isolines; 30 000 rows compile (in 189 s) | **crash** |
| [F2](#f2--the-compile-time-cubic-spline-is-cubic-in-time-and-quadratic-in-memory-in-the-knot-count) | *(fixed in [E-710](../../enhancements_doc/Enhancement-710.md): the moments by the Thomas algorithm, and no SLP vectoriser above 4 096 knots; 10 000 knots compile in 1.5 s, 200 000 in 41 s)* a cubic (`"3L"`) table of 1 000 knots compiles in 6.8 s, 2 000 in 77 s, 4 000 not in 300 s, and 200 000 fill 50 GB: the dense n × n moment matrix of E-22 and its Gauss–Jordan inverse, on data that is constant at compile time | pathological compile time and memory |
| [F3](#f3--a-legal-source-of-about-two-million-tokens-is-cut-off-by-the-parsers-step-guard-and-reported-as-an-unexpected-end-of-file) | *(fixed in [E-711](../../enhancements_doc/Enhancement-711.md): the guard counts steps since the last consumed token; a legal file of any size parses, 400 000 statements in 144 s)* a legal file of about two million tokens (3.5 MB of ordinary statements) exhausts the parser's 10-million-step guard of E-220, which then returns `EOF` in mid-file: the error is "unexpected token EOF" at a line in the middle of the file, and nothing says the file was too big | refusal of legal input, misleading diagnostic |
| [F4](#f4--a-poisson-draw-saturates-at-768-for-any-mean-above-745) | *(fixed in [E-709](../../enhancements_doc/Enhancement-709.md): Hörmann's transformed rejection above a mean of 10; a mean of 1 000 draws 979, 10⁶ draws 999 300)* `$dist_poisson` and `$rdist_poisson` return 768 for every mean above about 745 — mean 100 draws 113, 500 draws 508, 740 draws 763, and 750, 1 000, 10 000 and 10⁶ all draw 768 — in silence | wrong numbers, silent |
| [F5](#f5--the-erlang-chi-square-and-t-generators-run-in-time-linear-in-their-degree) | *(fixed in [E-709](../../enhancements_doc/Enhancement-709.md): a Marsaglia–Tsang gamma variate above 256 degrees; 2³¹ − 1 degrees return in 0.2 s)* `$dist_erlang`, `$dist_chi_square` and `$dist_t` (and the `$rdist_` forms) cost time linear in the degree: 10⁸ takes 3.4, 7.9 and 8.0 s per evaluation, and 2³¹ − 1 — accepted at compile time, where only a degree ≤ 0 is refused — does not return in a minute; a card can set the degree | hang for a large argument |
| [F6](#f6--a-nan-or-infinity-from-the-constant-folder-passes-every-constant-argument-check) | *(fixed in [E-706](../../enhancements_doc/Enhancement-706.md): `0.0/0.0` is a compile error, `1.0/0.0` folds to the infinity it is and the consumer that needs a finite number says so, `exp(1000.0)` and `pow(10.0, 400.0)` are refused as exceeding the largest double)* `0.0/0.0` and `1.0/0.0` fold to NaN and infinity without a word where `ln(0.0)`, `sqrt(-1.0)` and `pow(0.0, -1.0)` are compile errors; the NaN then passes every constant-argument check that refuses −1 (`absdelay`, `transition`, `slew`, `$bound_step`, `$limit`, the distributions, a parameter default or range bound), and at run time a NaN delay is a zero delay, a NaN `maxdelay` holds the output at 0 for the whole run, a NaN transition time is the default, a NaN slew rate is no limit and a NaN Laplace coefficient is refused as "zero" | diagnostic gap with silent wrong outputs |
| [F7](#f7--compile-time-grows-quadratically-with-the-size-of-a-table-array-or-coefficient-list) | compile time is quadratic or worse in the size of an array or list: a `localparam` array of 20 000 values takes 15.5 s and 100 000 does not finish in 300 s; a loop that fills a 20 000-element array takes 107 s (40 000 does not finish in 400 s) and one that only reads a 10 000-element array 27 s; an inline `noise_table` of 5 000 pairs takes 58 s (100 000 pairs, 300 s, unfinished); a `laplace_nd` denominator of 1 000 coefficients 17 s (100 000, unfinished) | pathological compile time at realistic sizes |
| [F8](#f8--a-file-of-1800-or-more-modules-fails-at-the-link-step-as-linker-not-found) | *(fixed in [E-707](../../enhancements_doc/Enhancement-707.md): a response file above 16 KiB of arguments, an `exec` failure names the program and the cause, a failed link removes its object files; 2 000 modules link in 14.4 s)* 1 700 modules in one file compile in 12 s and 1.7 GB; 1 800 fail after the same 12 s with "linker not found: Argument list too long (os error 7)" — one object file per module is passed on the linker's command line, and the message reports the `exec` error as a missing linker | wrong message, hard limit |
| [F9](#f9--compile-memory-grows-quadratically-with-the-number-of-filter-states) | *(fixed in [E-712](../../enhancements_doc/Enhancement-712.md): the root expansion decides the zero-root choice at compile time instead of opening four branch diamonds per root and coefficient, and the OSDI descriptor module is built at -O0 above 256 Jacobian entries; 100 filters compile in 1.6 s and 0.55 GB, 20 in 0.3 s and 134 MB)* 20 `laplace_zp` filters of 20 poles in one module compile in 7 s and 2.6 GB; 100 of them (2 000 filter states) in 113 s and **48 GB** — five times the filters, eighteen times the memory | pathological compile memory |
| [F10](#f10--diagnostic-slips) | *(fixed in [E-708](../../enhancements_doc/Enhancement-708.md): L030 for a based literal wider than its size, an empty `` `include `` name named, a width or precision above 4096 refused and a `*` width clamped, the Laplace coefficient must be a finite non-zero number)* a hex literal that does not fit 32 bits (`'hFFFFFFFFFF`) is truncated to −1 in silence where the decimal `2147483648` draws L030; `` `include "" `` is reported as "is a directory"; `$sformat` honours a width up to 10⁹ (2 GB at run time) and drops a wider one in silence; `laplace_nd` with a NaN coefficient is refused at run time as a "highest-order coefficient [that] must not be zero" | diagnostic slips |

Everything else held. The list of what was thrown at the compiler and answered
correctly is long and is given after the findings, because for a robustness campaign
it is half the result: apart from the two stack overflows of F1 — both from a large
data file, the one input the E-148 depth guard does not see — no probe produced a
panic, a signal, an assertion or a stack overflow; every hostile byte sequence,
recursion, include and command-line value was refused with a located message; every
nesting probe written in the source met the depth guard; every array bound, loop and
function pathology was named; and the numbers at the edges of the arithmetic are the
documented ones (E-286, E-420, E-693, L030).

## F1 — a table file of 100 000 rows overflows the compiler's stack

**Observed.** `I(p,n) <+ $table_model(V(p,n), "h3_100000.dat", "1L");` with a two-column
file of `n` rows (`hunt4/pH3.py`, `pH2.py`):

| rows | result |
|---|---|
| 10 000 | compiles, 18.3 s, 386 MB |
| 30 000 | compiles, 189 s, 841 MB |
| 60 000 | not finished in 420 s (1.5 GB), no crash |
| 100 000 (1.3 MB of text) | after 4.1 s: `thread 'main' (…) has overflowed its stack` / `fatal runtime error: stack overflow, aborting` — SIGABRT, no `.osdi` |

The same abort, 8.3 s in, for a two-input isoline file of 100 000 isolines of two
points under `"1L,1L"` (30 000 isolines compile in 133 s); with `"3L,1L"` the same
file instead runs for 300 s and 49 GB (F2). `--dry-run`, which returns before the
HIR is lowered, exits 0; `--dump-unopt-mir` writes 182 MB of unoptimised MIR and then
aborts; `--dump-mir` aborts before writing anything: the overflow is in the MIR
pipeline between the two dumps — the optimiser and the autodiff — not in the parser,
the lowering or LLVM.

**Where.** The 1-D interpolant is lowered as one select chain over the segments
(`hir_lower/src/expr.rs`, `interp_1d_values` at 1598: `result = make_select(ge, …
result)` once per knot), and the outer axis of an isoline file the same way over the
isolines (`interp_tbl_tree`, 1495). A chain of 100 000 nested selects is a
100 000-deep use-def chain in MIR; the lowering builds it iteratively and survives
(the unoptimised dump completes), and the first pass that walks it recursively — in
the MIR optimiser or the autodiff, which is where `--dump-mir` dies — exhausts the
8 MB main-thread stack.
The E-148 depth guard bounds what the *parser* nests; a data file builds its nesting
after the parser. E-392 capped the run-time array form at 256 knots for a related
reason ("the largest runtime table that is normalised in the emitted code"); the
compile-time file form has no cap and no guard.

**Expected.** Either a bounded structure — a binary search over the sorted knots is
log₂ n deep and is what a 100 000-row table wants anyway (the linear chain is also
why 30 000 rows cost 189 s: every evaluation walks 30 000 selects) — or a named limit
("a data file of more than N rows is not supported") like E-392's. A crash on a data
file that any measurement setup can produce is the campaign's one hard failure.

**Kind.** Compiler crash (SIGABRT) on legal input of realistic size; deterministic;
the row count at which it starts depends on the platform's main-thread stack.

*Fixed in [E-705](../../enhancements_doc/Enhancement-705.md).* The overflow was
`Postorder::dfs`, the recursive post-order walk of the MIR control-flow graph, on the
300 000 blocks the chain of one `make_select` per knot had produced; it is an explicit
stack now. Behind it, the CFG simplifier's cursor ended each pass at the block it had
just removed — one block per pass, 29 995 passes for 10 000 rows — and LLVM's block
placement, scheduler and SLP vectoriser each choked in turn on a chain of 300 000
blocks, one block of 100 000 live values, one block of 100 000 comparisons. The search
is a balanced tree now, branches above 64 knots and branchless selects below, that
picks the segment's parameters and evaluates one polynomial: 10 000 rows 1.25 s (18.3),
30 000 rows 3.1 s (189), 100 000 rows 13.6 s (the abort), 10 000 isolines 1.85 s (15.7),
30 000 isolines 9.4 s (133); the numbers are bit for bit what they were.
`table_model_examples` pins a 100 000-row file and a 30 000-isoline file.

## F2 — the compile-time cubic spline is cubic in time and quadratic in memory in the knot count

**Observed** (`hunt4/pH3.py`, `pH.py`, `pS.py`):

| knots | `"3L"` from a file | `"1L"` from the same file |
|---|---|---|
| 1 000 | 6.8 s | (2.8 s inline) |
| 2 000 | 77.4 s, 1.4 GB | |
| 4 000 | not finished in 300 s | (5 s, the 2026-09-21 hunt) |
| 10 000 | not finished in 300 s | 18.3 s |
| 200 000 | not finished in 300 s, **50 GB** resident | |

Doubling the knots multiplies the time by eleven and the memory grows with n².

**Where.** `hir_lower/src/expr.rs`, `cubic_spline_moment_matrix` (197): E-22 expresses
the spline's moments as a *linear operator* on the data values — an n × n matrix built
by inverting the tridiagonal system with Gauss–Jordan (O(n³) time, O(n²) memory) — so
that a table whose values are run-time expressions still lowers without a run-time
solve. For a data file, an inline literal or a `localparam` array the values are
compile-time constants, and the operator is applied to constants: the moments could be
solved directly by the Thomas algorithm in O(n) (the run-time form of E-390 already
contains that solve), and the n × n matrix never built. E-704 (yesterday) added the
clamped-end rows to the same matrix and inherited its cost.

**Expected.** A 10 000-knot cubic table — a measured I-V or C-V characteristic with a
smooth interpolant is the textbook use of `"3"` — should compile in the time the linear
one takes. Constant data: solve for the moments; run-time data (`interp_1d_spline`'s
`vals` from an N-D slice of a larger table are the only such case): keep the operator.

**Kind.** Pathological compile time and memory, at sizes a model author writes; no
wrong result. Not platform-specific.

*Fixed in [E-710](../../enhancements_doc/Enhancement-710.md).* The moments are solved
by the Thomas algorithm on the factored tridiagonal system — in f64 for constant data,
as straight-line MIR for a run-time slice — and the dense operator is gone; that left
a second wall at 30 000 knots (32 s) and 100 000 (not in 400 s), LLVM's SLP vectoriser
CSE-ing the gathers it made of the cubic leaf's seven parallel select trees, quadratic
in their number, so a file with a table above 4 096 knots is now optimised without the
vectoriser (LLVM's own `-vectorize-slp=false`; the pass-builder option does nothing
here, as E-705 found). Re-run: 1 000 / 2 000 / 4 000 / 10 000 / 30 000 / 100 000 /
200 000 knots in 0.7 / 0.7 / 1.4 / 1.5 / 4.8 / 19.1 / 41.2 s, the last at 3.8 GB;
`cubic_table_examples` pins a 10 000-row file against a Python Thomas solve.

## F3 — a legal source of about two million tokens is cut off by the parser's step guard and reported as an unexpected end of file

**Observed.** One module whose analog block is `n` copies of `s = s + 1.0e-3 * V(p,n);`
(`hunt4/pA2.py`, `pA3.py`):

| statements | size | tokens (no trivia) | result |
|---|---|---|---|
| 100 000 | 2.5 MB | 1.3 M | compiles, 9.6 s |
| 140 000 | 3.5 MB | 1.82 M | compiles, 17.2 s |
| 150 000 | 3.8 MB | 1.95 M | `error: unexpected token EOF; expected 'root' or identifier` at line **147048** |
| 400 000 | 10 MB | 5.2 M | the same error at line 147048 |

With the six-token statement `s=s+1.0;` the cut moves to line 333 301 (300 000
compile, 340 000 do not): the boundary follows the token count, not the byte count.
The two boundaries are 147 047 × 68 = 9 999 196 and 333 300 × 30 = 9 999 000 — ten
million, less the header, at 68 and 30 parser lookahead steps per statement.

**Where.** `parser/src/parser.rs:38`, `PARSER_STEP_LIMIT = 10_000_000`, and
`Parser::nth` (58–74): E-220's guard against a parser spinning in error recovery
counts every `nth()` lookahead call and, once the count reaches ten million, returns
`EOF` for the rest of the parse — "sticky", by design, so the grammar winds down. Its
comment says "a valid file finishes well under this bound; it is a safety net, not a
size limit". A valid file of about five lookahead steps per token reaches it at two
million tokens: three to four megabytes of ordinary Verilog-A. The largest single
compact-model files in circulation are one to two megabytes, so a PDK library that
concatenates a few of them into one file, or a generated model with a large unrolled
body, is within a factor of two of the guard, and what it gets is a syntax error in
the middle of a file that has no syntax error.

**Expected.** A size the parser will not read should be named as such ("the file has
more than N tokens"), or the guard should count error-recovery steps rather than all
lookahead — the condition it was written for is a parser that makes no progress, which
`pos` not advancing detects directly. A legal file of any size must either parse or be
refused as too large; a mid-file EOF is neither.

**Kind.** Refusal of legal input with a misleading diagnostic; hostile-sized today,
within reach of a concatenated library. Deterministic, not platform-specific.

*Fixed in [E-711](../../enhancements_doc/Enhancement-711.md).* `do_bump` resets the
step counter, so the guard counts lookahead steps since the last consumed token — the
no-progress condition it was written for — with E-220's ten million kept as the
limit. Re-run: 150 000 statements compile in 21.8 s, 400 000 (10 MB) in 144 s and
5.6 GB, 340 000 of `s = s + 1.0;` in 1.6 s; `vafcrash2_examples` pins the last and
E-220's keyword-salad stress.

## F4 — a Poisson draw saturates at 768 for any mean above 745

**Observed.** `I(p,n) <+ V(p,n) + $dist_poisson(s, mean);` at the operating point
(`hunt4/pJ.py`; the current is 1 + the draw):

| mean | draw |
|---|---|
| 100 | 113 |
| 500 | 508 |
| 700 | 722 |
| 740 | 763 |
| 750 | **768** |
| 800, 1 000, 10 000, 10⁶, 2³¹ − 1 | **768** |
| `$rdist_poisson` 760, 10 000 | **768** |
| `$rdist_poisson` +∞ | 803 |

No message at compile time or at run time.

**Where.** The Poisson generator of the OSDI standard library (`osdi/stdlib.c`,
`$dist_poisson` / `$rdist_poisson`) is Knuth's multiplicative method: draw uniforms
until their product falls below `exp(−mean)`. `exp(−745.13)` is the smallest positive
double; above that mean the threshold is exactly zero, the product of uniforms reaches
zero after about 768 factors (each uniform has 53 bits, the product underflows after
about 745·ln 2 ≈ 516 … the observed count is the subnormal tail), and the loop count
is returned as the draw. The E-505 domain check bounds the mean below (a negative mean
is projected) but not above.

**Expected.** A Poisson variate with a mean of 1 000 is 1 000 ± 32. For a mean above
a few tens the standard route is the normal approximation (or a rejection method such
as PTRS); at the least the E-651 machinery should name a mean above the method's
range instead of returning a constant.

**Kind.** Wrong numbers, silent, at run time; any model that draws a Poisson count
above 745 (a photon or electron count per step is a natural use). Not
platform-specific.

*Fixed in [E-709](../../enhancements_doc/Enhancement-709.md).* Above a mean of 10
the draw is Hörmann's PTRS (transformed rejection with squeeze): two uniforms per
attempt, exact, O(1) at any mean, the log Γ it needs by Stirling's series inside the
standard library; below 10 Knuth's method stays and every small-mean draw is what it
was. Re-run: a mean of 750 draws 732, 1 000 draws 979, 10 000 draws 9 931, 10⁶ draws
999 300; `rng_examples` pins the moments at 1 000 and 10⁶ and a mean of 10⁹.

## F5 — the Erlang, chi-square and t generators run in time linear in their degree

**Observed.** One operating point, one evaluation per Newton iterate
(`hunt4/pI.py`, `pJ.py`):

| call | degree | time of the `op` |
|---|---|---|
| `$dist_erlang(s, k, 1)` | 10⁶ / 10⁷ / 10⁸ | 0.2 / 0.5 / 3.4 s |
| `$dist_chi_square(s, k)` | 10⁶ / 10⁷ / 10⁸ | 0.3 / 1.0 / 7.9 s |
| `$dist_t(s, k)` | 10⁶ / 10⁷ / 10⁸ | 0.3 / 1.0 / 8.0 s |
| all three | 2 147 483 647 | **no result in 60 s** (killed) |
| `$rdist_erlang(s, 1e9, 1.0)` | 10⁹ | 31.6 s |

The compile-time check refuses `$dist_t(s, 0)`, `$dist_chi_square(s, 0)` and
`$dist_erlang(s, 0, 1)` ("must be greater than zero") and accepts any positive degree;
the degree may also come from a parameter and so from the card, where no compile-time
check sees it.

**Where.** `osdi/stdlib.c`: the Erlang variate is the sum of `k` exponentials, the
chi-square the sum of `k` squared normals, and the t variate divides a normal by a
chi-square of `k` degrees — each a loop of `k` draws, run at every evaluation of the
model. The E-505/E-651 projections bound the arguments below, not above.

**Expected.** A degree above a few hundred should take the closed-form route (a gamma
variate for Erlang and chi-square — Marsaglia–Tsang is O(1) for any shape — and the
normal limit for t), or be named and bounded, as a `$dist_poisson` mean should be. A
model must not be able to stall the simulator with one integer.

**Kind.** Effectively a hang for a large argument; silent for a merely large one
(10⁸ costs seconds per Newton iterate). Not platform-specific.

*Fixed in [E-709](../../enhancements_doc/Enhancement-709.md).* Above 256 degrees the
three take a Gamma variate by Marsaglia and Tsang's method — a normal and a uniform
per attempt, O(1) at any shape: chi-square(k) is 2·Γ(k/2), Erlang(k, mean) is
Γ(k)·mean/k, t(k) is z over √(chi-square(k)/k) — and the term-by-term sums stay below
256, so every draw there is unchanged. Re-run: 10⁶, 10⁷, 10⁸ and 2³¹ − 1 degrees each
0.2 s per operating point, `$rdist_erlang(s, 1e9, 1.0)` 0.2 s (31.6 s). No
compile-time bound was added, since no degree can stall the simulator now;
`rng_examples` pins the moments at 10⁵ degrees and the wall at 2³¹ − 1.

## F6 — a NaN or infinity from the constant folder passes every constant-argument check

**Observed.** At compile time (`hunt4/pC.py`, `pI.py`):

| expression | result |
|---|---|
| `ln(0.0)`, `sqrt(-1.0)`, `pow(0.0, -1.0)`, `pow(-1.0, 0.5)`, `asin(2.0)`, `acosh(0.0)`, `atanh(1.0)` | compile error naming the domain, "the result would be NaN" |
| `1/0`, `1%0` | compile error |
| `0.0/0.0` | **NaN, silent** |
| `1.0/0.0`, `exp(1000.0)`, `pow(10.0, 400.0)` | **+∞, silent** |
| `1e400` | compile error, "too large to represent" |

and the NaN then travels: `absdelay(V(p,n), 0.0/0.0)`, `transition(V(p,n), 0.0/0.0)`,
`slew(V(p,n), 0.0/0.0)`, `$bound_step(0.0/0.0)`, `$limit(V(p,n), "pnjlim", 0.0/0.0,
0.7)`, `$rdist_normal(s, 0.0, 0.0/0.0)`, `$rdist_exponential(s, 0.0/0.0)`,
`flicker_noise(1e-12, 0.0/0.0)`, `white_noise(0.0/0.0)`, `parameter real q = 0.0/0.0
from [0:1]`, `parameter real q = 1 from [0.0/0.0:1]`, `parameter real q = 1 exclude
0.0/0.0` all compile in silence, where the same argument written as `-1` is refused
("the delay must not be negative, but is -1"; "the standard deviation must not be
negative"; "the step bound must be greater than zero"). Only `zi_nd`'s period and the
`$table_model` and `noise_table` data refuse it — the first because its check is
written as `!(T > 0)`, the second because a folded NaN is "not a compile-time
constant". At run time (`hunt4/pJ2.py`, a 1 V pulse from 1 µs, measured on the flat
parts with `meas … at=`):

| call | at 1.0005 µs | at 3 µs | reading |
|---|---|---|---|
| `absdelay(V, 1u)` (control) | 0 | −1 | delayed |
| `absdelay(V, 0.0/0.0)` | −0.5 | −1 | **a zero delay** |
| `absdelay(V, 1u, 0.0/0.0)` | 0 | **0** | the output holds at 0 for the whole run |
| `transition(V, 0, 1u)` (control) | −9.1e-5 | −1 | a 1 µs ramp |
| `transition(V, 0.0/0.0)` | −0.264 | −1 | the default ramp |
| `slew(V, 1e6)` (control) | −5e-4 | −1 | limited |
| `slew(V, 0.0/0.0)` | −0.5 | −1 | **no limit** |
| `laplace_nd(V, '{1}, '{1, 0.0/0.0})` | — | — | `OSDI(fatal) … highest-order coefficient must not be zero` |
| `laplace_nd(V, '{1}, '{1, 1.0/0.0})` | 0 | **0** | a silent 0 |
| `idt(V, 0.0/0.0)`, `$rdist_normal(s, 0.0/0.0, 1)`, a NaN parameter default | — | — | the operating point fails, "timestep too small" |
| `$bound_step(0.0/0.0)`, `$bound_step(1.0/0.0)` | −0.5 | −1 | ignored |

**Where.** The MIR constant folder folds `fdiv` by zero to the IEEE result
(`mir_opt`, the simplifier), while the domain checks of the elementary functions
(`hir_ty/src/validation/body.rs`, E-2xx's "outside the domain" family) and E-651's
`require_positive`/`require_non_negative` on the constant arguments test `x < 0` or
`x <= 0`, which NaN fails on both sides. The run-time projections of E-651/E-696
(`project_or_warn`) test the same way.

**Expected.** Either the folder refuses `0.0/0.0` as it refuses `ln(0.0)` — the result
is the same NaN, and a division of two zero-valued parameter defaults is how a NaN
enters a real model — or every check that refuses a negative also refuses a NaN
(`!(x >= 0)` instead of `x < 0`), at compile time and in the projections. An infinity
deserves the same decision per argument: an infinite delay or transition time is a
legal way to say "never", an infinite Laplace coefficient is not.

**Kind.** Diagnostic gap whose consequences are silent wrong outputs (a `maxdelay` of
NaN turns a delay line into a permanent 0; a NaN rate turns `slew` off). Not
platform-specific.

*Fixed in [E-706](../../enhancements_doc/Enhancement-706.md).* The gap was at compile
time only: `const_num` leaves a zero divisor unfolded so that "the division checks"
report it, and the real `/` had no check — so `0.0/0.0` was "not a constant" to every
argument check and reached the MIR folder, and `1.0/0.0` was not folded at all. The
"Where" paragraph above guessed that the run-time projections test `x < 0`; reading
them, they are written as `fge`/`fgt` ("false for NaN") at every site, and the zero
delay is the silent projection E-651 prescribes for a run-time quantity, reached by a
literal the compile-time check never saw. Now `0.0/0.0` is an error at the division
("the operands are both 0, so the quotient is undefined; the result would be NaN"), a
non-zero constant over a constant zero folds to IEEE's infinity — legal on its own, as
E-333 promised and `vafdivzero_examples` asserts — and the consumer that needs a finite
number refuses it ("absdelay: the delay must be a finite number, but is inf";
`parameter real q = 1.0/0.0` is E-640's "overflows to infinity"), and `exp`, `sinh`,
`cosh`, `pow` and `**` on finite constants whose result is infinite are refused as
exceeding the largest double. `powguard_examples` pins all of it.

## F7 — compile time grows quadratically with the size of a table, array or coefficient list

**Observed** (`hunt4/pB.py`, `pS.py`, `pD.py`; one compile each, some run beside other
probes, so the seconds are ±20 %):

| shape | 1 000 | 5 000 | 10 000 | 20 000 | larger |
|---|---|---|---|---|---|
| `localparam real t[0:n-1] = '{…}` | 0.2 s | 1.3 s | 4.4 s | 15.5 s | 100 000: not finished in 300 s |
| `parameter real t[0:n-1] = '{…}` / `real t[…] = '{…}` | | 1.3 / 0.7 s | | 15.5 / 9.1 s | |
| `for (k=0;k<n;k=k+1) a[k] = k*1.0;` over `real a[0:n-1]` | 0.7 s | 7.4 s | 22.8 s | 107 s | 40 000: not finished in 400 s |
| `for (…) s = s + a[k];` (a read, no indexed write) | | | 26.8 s | | 40 000: not finished in 400 s |
| `noise_table('{f1, p1, …})` of n pairs | 2.4 s | 58.5 s | | 20 000: not finished in 400 s | 100 000: not finished in 300 s |
| `laplace_nd(V, '{1}, '{n coefficients})` | 17.1 s | 3 000: 91.8 s, 4.3 GB | | | 100 000: not finished in 300 s (500: 7.5 s, 100: 0.9 s) |
| `$table_model(V, '{2n values}, "1L")` inline, n points | 2.8 s | 68.8 s | | | (the same 4 000 points from a data file: 5 s, the 2026-09-21 hunt) |
| `$table_model(V, "file", "1L")`, n rows | | | 18.3 s | 30 000: 189 s | 60 000: not finished in 420 s; 100 000: F1 |
| `$table_model` calls on one 10-point table, n calls | 200: 3.1 s | 65.4 s | | | |
| `@(cross(V(p,n) − c))` event blocks, n of them | 500: 118.7 s | | | 2 000: not finished in 400 s | |
| `real v0 … vn;` each assigned and summed | | | | 7.8 s | 50 000: 47.4 s |
| a chain of n modules, each instantiating the previous one | 50: 5.5 s | 200: 208 s, 2 GB | | | 1 000: not finished in 300 s, 6 GB (10 000 leaves flat in one module: 7.8 s) |

Doubling the size multiplies the time by about four in every row (the loop by five),
so the cost is quadratic; a 5 000-pair noise table and a 5 000-point inline table each
cost a minute, and the same table read from a file costs seconds at 4 000 rows and
minutes at 30 000 — the array literal and the select chain, not the interpolant, are
the slow parts. A thousand calls of one ten-point table (65 s), five hundred
`cross` events (two minutes) and a 200-deep instance chain (208 s) are the same
shape: something that is done once per call site, event or level walks the whole
module again.

**Where.** The array forms lower every element to its own SSA value
(`hir_lower/src/expr.rs`, `lower_array_elems_impl` at 4885 and `const_array_values` at
2902; the `noise_table` lowering at 3478 folds `table_vals` element by element), an
indexed access with a run-time index is a select chain over every element, and the
loop body's chain is then rebuilt by the SSA construction for each element across the
loop — each of these is linear per element and so quadratic for the whole; the
`laplace_nd` polynomial goes through `laplace_roots_to_poly`/the coefficient
expansion in the same file. None of it is wrong; it is the cost model of "no memory,
every value a register".

**Expected.** These sizes are not hostile: a 10 000-point measured noise spectrum, a
20 000-entry lookup table filled in an `@(initial_step)` loop, a 1 000-coefficient
filter from a fitting tool are all things a model author writes. A large constant
array should be one constant-data object indexed at run time (which is also what E-392
capped the run-time `$table_model` at 256 knots to avoid), and a loop over an array
with a run-time index should not unroll the array into the loop body.

**Kind.** Pathological compile time; no wrong result. Not platform-specific.

## F8 — a file of 1 800 or more modules fails at the link step as "linker not found"

**Observed.** A file of `n` one-line resistor modules (`hunt4/pG.py`, `pA2.py`):

| modules | result |
|---|---|
| 200 / 500 / 1 000 / 1 500 | compile in 1.4 / 3.4 / 6.8 / 10.3 s; the `.osdi` is 0.9 / 2.2 / 4.4 / 6.7 MB |
| 1 600 / 1 700 | compile in 11.2 / 11.9 s, 1.6 / 1.7 GB resident |
| 1 800 / 1 900 / 2 000 | after the same 11–13 s: `error: linker not found: Argument list too long (os error 7)` |

**Where.** `openvaf/src/lib.rs:443`: every module is compiled to its own object file
and each path is added to the linker's argument list (`linker.add_object(path)`,
`linker/src/lib.rs:314`); the paths are in the scratch directory and about 120 bytes
long, so 1 800 of them exceed macOS's 256 KB `ARG_MAX` for a single argument vector
and `exec` fails with `E2BIG`. `link` (`linker/src/lib.rs:82`) maps every `exec`
error to "linker not found". About one megabyte of resident memory per module is
spent before the failure.

**Expected.** A response file (`@objects.txt`, which every supported linker reads) or
one object per file instead of per module; and an `exec` failure reported as what it
is, with the linker's path and the error, since a missing linker and an oversized
argument vector call for different fixes.

**Kind.** Hard limit with the wrong message; hostile-sized (a library with 1 800
modules in one file is unlikely, but the failure mode is "works for 1 700, dies for
1 800" with a message that sends the user looking for `clang`). macOS-specific number;
Linux's 2 MB `ARG_MAX` moves it to about 15 000.

*Fixed in [E-707](../../enhancements_doc/Enhancement-707.md).* Above 16 KiB of
arguments the linker is run as `<linker> @<output>.rsp`, one argument per line, quoted
for the reader (GNU-style for clang, gcc and GNU ld; link.exe's for MSVC); a `NotFound`
spawn error is "linker not found: 'clang' is not installed or not on PATH (…)" and any
other "failed to run the linker 'clang': …"; and a failed link no longer leaves four
`.oN` files per module beside the output. 1 800 modules link in 12.8 s and 2 000 in
14.4 s; `multimod_examples` pins a 400-module file (1 600 objects, eight times the
threshold) and the message.

## F9 — compile memory grows quadratically with the number of filter states

**Observed.** One module with `n` contributions `I(p,n) <+ laplace_zp(V(p,n), '{},
'{−1,0, −2,0, …, −20,0});` (`hunt4/pD.py`):

| filters | states | time | peak resident |
|---|---|---|---|
| 20 | 400 | 7.0 s | 2.6 GB |
| 100 | 2 000 | 112.6 s | **48.3 GB** |

Five times the filters cost sixteen times the time and eighteen times the memory. The
five-thousand-contribution module of plain resistive terms beside it took 0.4 s and
180 MB; the cost is the filter states, not the contributions.

**Where.** Every pole of a Laplace filter is an implicit state equation
(`hir_lower/src/expr.rs`, `lower_laplace` and the implicit-equation lowering), and the
module's Jacobian is built by `mir_autodiff` over all of them: with `s` states the
derivative sets grow as `s²` (each state's equation is differentiated with respect to
each unknown that reaches it, and the dense per-instruction derivative bookkeeping is
kept for the whole function until the optimiser prunes it). 2 000 states give four
million derivative slots at some hundreds of bytes each.

**Expected.** A filter's state equations touch only their own states and the input; the
sparsity is known when the filter is lowered, so the autodiff could be told which
unknowns can reach each equation instead of discovering that most cannot. A module
with a few hundred filter states — ten twenty-pole macromodels — should compile in a
few hundred megabytes.

**Kind.** Pathological compile memory, superlinear; at 500 states (ten 50-pole
transmission-line macromodels) it is already several gigabytes. Not platform-specific.

*Fixed in [E-712](../../enhancements_doc/Enhancement-712.md).* The "where" above was
wrong: the DAE build, the derivatives and the optimiser took 110 ms of the 20-filter
module's 7 s. The memory was blocks — the root-to-polynomial expansion selected the
LRM's zero-root exception at run time with four branch diamonds per (root, coefficient)
pair, 54 183 blocks for 20 filters, every one folded away a moment later because the
roots are literals, and the SSA construction over them was the 2.6 GB and the 48 GB.
The time was the OSDI descriptor module: its helper functions are straight-line code
with a few memory operations per Jacobian entry, and two LLVM backend passes (the
post-legalisation DAG combine and the machine scheduler) are quadratic in such a
block — 24 s of a 25 s compile at 2 000 entries, with or without filters (400 `idt`
states 25 s, 1 000 of them 139 s, a 1 000-node ladder 18 s). Now the zero-root choice
of a constant root is decided at lowering time (a branchless `select` for a parameter
root), and the descriptor module is built at -O0 above 256 Jacobian entries, where
its code quality does not matter and FastISel is linear: 20 filters 0.3 s and 134 MB,
100 filters 1.6 s and 550 MB, 1 000 `idt` states 1.8 s, the ladder 1.2 s.

## F10 — diagnostic slips

- **A hex literal that does not fit is truncated in silence.** `'hFFFFFFFFFF` (40 bits)
  evaluates to −1 with no message; `'hFFFFFFFF` is −1 too, right for a 32-bit integer.
  The decimal `2147483648` draws `L030: integer literal … does not fit a 32-bit
  integer`, and so does `9223372036854775807`. The based literal takes another path
  (`syntax/src/ast/expr_ext.rs`, the `x_mask`/`z_mask` digit loop) that masks instead
  of reporting.
- **`` `include "" ``** is reported as `failed to read '<the source's directory>': is
  a directory` — the empty name resolves to the including file's directory. The empty
  name deserves its own words.
- **`$sformat` honours a width up to 10⁹ and drops a wider one in silence.**
  `$sformat(s, "%999999999d", 1)` compiles and allocates 2.0 GB at run time (1.2 s, it
  completes); `"%100000000d"` 200 MB; `"%2147483647d"`, `"%4294967295d"` and
  `"%99999999999999999999d"` compile too and are ignored at run time (65 MB, the
  plain value). `$strobe` truncates all of them to its line buffer. A width the
  compiler parses could be bounded at compile time (`hir_lower/src/fmt.rs`); a width
  it accepts should not be silently dropped.
- **`laplace_nd` with a NaN coefficient** (`'{1.0, 0.0/0.0}`) is refused at run time as
  "the denominator's highest-order coefficient must not be zero" — it is NaN, not zero
  (the check is `!(c != 0)`); F6's compile-time refusal would make the message moot.

*Fixed in [E-708](../../enhancements_doc/Enhancement-708.md).* A based literal wider
than its size draws L030 with the bit count and the value it reads as (`'hFFFFFFFFFF`:
"40 significant bits, more than the 32 of an `integer` … it reads as -1"; `8'hFFF`
likewise against its declared size), a 100 000-digit literal measured by digit count and
abbreviated in the message; `` `include "" `` is refused as "names no file"; a
literal format width or precision above 4096 is a compile error with the digits as
written, and a `*` width or precision is clamped to ±4096 at run time; and the Laplace
check is `|a| > 0 && |a| < ∞` with "must be a finite non-zero number, but is nan" (or
inf — an infinite coefficient used to run the filter as a silent 0). The literal NaN
coefficient is E-706's compile error. `diagslips_examples` pins the fourteen shapes.

## Observations that hold, and design choices

Recorded because a robustness campaign is as much about what did not break.

**No crash from the source text.** Across every probe written in Verilog-A the
compiler exited 0, 2 (usage) or 65 (diagnostics), or was killed by the harness's
timeout; no `panicked`, no signal, no assertion, no Rust backtrace, no non-UTF-8
output. The two stack overflows of F1 came from data files. The E-148 depth
guard ("expression nests too deeply") caught: 100 000-deep parentheses, unary minus,
`!` and `~`; 5 000-deep `abs(…)` calls, 2 000-deep function calls, 5 000-deep
`{…}` concatenations, 2 000-deep ternaries, a 5 000-deep parenthesised parameter
default, a 200 000-term flat sum (the F6 of 2026-09-04, still the message for a flat
chain), a 1 MB macro body, a 100 000-line continued macro, a 2²² and a 2¹⁵ macro
blow-up (the 2²² one in 1.4 s and 2.5 GB, then refused). A 500-deep `a[a[a[…]]]`
index chain compiles (0.4 s), as do 5 000 nested `if`s (4.4 s), a 5 000-arm `else if`
chain (2.8 s), a 5 000-item `case` (4.9 s), 1 000 nested named blocks, 500 chained
functions, a 1 000-argument function, 5 000 function definitions.

**Hostile bytes and structure.** Empty and whitespace-only files: "defines no
module", with a help line about unterminated comments and `ifdef`. A NUL byte: named,
located. Invalid UTF-8 and a non-ASCII identifier: "unexpected character(s) … not a
token of Verilog-A", located. A BOM, CR-only and CRLF endings, a NUL inside a comment,
UTF-8 in a comment: compile. Unterminated block comment, string and module; a lone
`endmodule`; a missing module name; a keyword as a module name; a `*/` after a
nested `/*`: each one located syntax error. A 100 000-character identifier and a 1 MB
string literal compile (the identifier reaches the OSDI descriptor unshortened — the
simulator's problem, if any). A 50 000-entry attribute list compiles in 0.15 s. Every
directive (`timescale`, `resetall`, `celldefine`, `default_nettype`, `line`,
`begin_keywords`) is accepted, `line` with L033 and an unknown keyword set with a
warning; an unknown directive is "macro … has not been declared". Escaped identifiers
end at white space exactly as IEEE 1364 says (`\my\module (\p! , n)` compiles; my first
three spellings were wrong, not the compiler). 100 000 comment lines: 0.1 s. A 1 MB
comment-only include pulled in 2 000 times (2 GB of source): compiles in 45 s and 35 GB
resident — about 17 bytes of memory per source byte, which is the token vector; not a
finding at that input, worth knowing.

**Preprocessor.** A self-recursive, a mutually recursive and an argument-recursive
macro: "was called recursively", located. Argument-count mismatch, an unbalanced
argument, an empty `` `define ``: each located. `` `define module 1 `` compiles (a
macro named like a keyword is never expanded unless invoked). A macro name inside a
string is text. 10 000 defines: 0.1 s. `` `undef `` of an undefined macro warns; of
`` `__FILE__ `` warns "no effect"; a `` `define __FILE__ `` warns "reserved". An unclosed
`` `ifdef ``, a stray `` `endif `` and `` `else ``: located. 10 000-deep `` `ifdef ``
(excluding the module: "defines no module"), 10 000-deep `` `ifndef `` and a 10 000-arm
`` `elsif `` chain: 0.1 s. An include of the file itself and a mutual include: "includes
a file that is already being included"; 300 deep: "nests too deeply" at 64; a
directory, a missing file, a file without quotes or in angle brackets, a binary file
(the NUL byte), `/etc/hosts` (a syntax error located in `/etc/hosts:1:1`): each
refused where it stands; `/dev/null` includes nothing.

**Command line.** No arguments: usage. A directory, a missing file, a symlink loop,
`/dev/null`, `/dev/zero`, `/dev/urandom`, `-`: "invalid value … is not a file" / the OS
error, before anything is read (so a device file cannot hang the read). A file with no
extension, a path with spaces and a non-ASCII name: compile. `-o /dev/full`, a
read-only directory, a missing directory, a directory, an empty string: each refused
with a help line; `-o` equal to the input: refused, "the compiled module would be
written over the source and the source would be lost", the source intact. `-I` missing,
a file, empty: refused at the command line. `-D =1`, `-D X==1`, `-D ü=1`: refused
with the rule spelled out; `-D X=` and `-D "X=1 2"` accepted (an empty and a
space-containing value are legal); `-D module=1` accepted (see above); 1 000 `-D`s:
0.1 s; a macro defined twice: L004. `-A`/`-W`/`-E` with an unknown or empty lint: the
possible values listed. `--lints`, `--dump-mir` to stdout, `-W all -E all`: work. Two
inputs, `-o` twice, an unknown flag, `--target bogus`: clap's messages. `--target_cpu
""`: accepted (LLVM's generic). `-b` prints the cache path.

**Declarations at scale.** 50 000 scalar parameters: 31 s, 1.3 GB (0.6 ms each; a
10 000-term sum of them meets the flat-chain depth guard). 2 000 ports: 0.1 s. A chain
of 5 000 internal nodes: 165 s and 4.1 GB (500: 7.6 s, 1 000: 17.5 s, 2 000: 44.7 s —
n^1.3, 33 ms per node; slow, not pathological, and 0.8 MB per node). Arrays of 10⁷,
2³¹ and 2³¹ + 1 elements and a 10⁵ × 10⁵ matrix: "expands to N elements, exceeding the
limit". `[5:0]` compiles (reversed bounds are legal); `a[-1]` with constant −1:
"index out of range". `1e400` as a default or a bound: "too large to represent";
`2147483648`, `1e10`, `9223372036854775808` and a 31-digit integer default: L030.
`from [-inf:inf]`: accepted. `from [2:1]`: "which no value can satisfy". `parameter
real q = q`, `from [0:q]`: "references itself"; `a = b; b = a`: "references parameter
'b' defined afterwards". A 5 000-deep parameter chain: 0.7 s. `aliasparam a = a`:
"never reaches a parameter: its target chain closes on itself"; a 1 000-long alias
chain and an alias of an alias: compile. A 10⁷-iteration `genvar` loop: "expands to
more than 4096 statement copies"; a constant-bound `for` of 10⁹, a `repeat` of 10⁹
and three nested 1 000-loops: compile in 0.1 s (they are run-time loops; the cost is
the model's); `while (1)`: "loop condition is always true"; `while (q > 0)` with `q` a
parameter: "loop condition can never change". A function calling itself, directly or
through another: "cannot call itself: recursion is not allowed".

**Arithmetic at the edges** (all as documented): `1/0` and `1%0` are compile errors,
`INT_MIN / −1` and `INT_MIN % −1` "overflows"; `2**31` is −2 147 483 648 and
`2**1000000` is 0 (E-693's wrapping); shifts by 100, −1 and `INT_MIN` are 0 with the
E-6xx warning; `65536*65536` is 0 and `2147483647+1` wraps; `abs(INT_MIN)` and
`-INT_MIN` are `INT_MIN`; `$rtoi(1e30)` and `$rtoi(+∞)` saturate at 2 147 483 647,
`$rtoi(NaN)` is 0; `floor(+∞)` is +∞, `ceil(NaN)` NaN, `max(NaN, 1)` is 1 and
`min(1, NaN)` NaN (the C `fmax`/`fmin` rule, argument order dependent); `hypot(+∞,
NaN)` is +∞, `atan2(0,0)` 0, `pow(NaN, 0)` and `pow(1, NaN)` are 1 (C99); NaN is true
in `?:`, `if`, `!`, `&&` and `case` (nonzero), `NaN == NaN` is false and `NaN != NaN`
true. `1a` is 1e-18, `1T` 1e12, `1M + 1m` 1 000 000.001; `1y`, `1Y`, `1x`, `1e3k`:
"malformed number literal" (E-665). `8'd300` is 44 (sized, masked); `'o777` 511;
`1_000_000.0` legal. A 1 MB string parameter default compiles.

**Format strings.** `%`, `%5`, `%-`, `%z`, `%n`, `%p`: "failed to parse format
specifier", located; `%*d`, `%s`, `%d` with no argument, `%%%%%d`: "missing an
argument"; `%s` with a real, `%d` with a string, `%x` with a real: type mismatch;
`%c` with 10⁹ and −1, `%m`, `%l`, `%t`, `%b`, `%o` with −1, `%10.99999s`, `%0d`,
`%+d`, `% d`, `%#x`, `%hd`, `%ld`, `%lld`: accepted (the length modifiers are
ignored). Extra arguments after a format with no specifier: accepted. A 32-way
`$sformat`/`$strobe` sweep produced no crash at run time.

**Semantic shapes.** `V(p,p)`, `I(p,p)`: "both arguments … name the same net"; three
or zero access arguments: counted; `branch (p,p)`: L024; a branch contributed as both
potential and flow, and `V(p,n) <+` beside `I(p,n) <+`: L022; a switch branch under a
time condition: compiles. `ddx(ddx(…))`: L011; `ddx` with respect to an expression or a
variable: "invalid unknown". 50-deep `ddt` and `idt`: 0.2 s. `ddt`, a contribution, an
event inside a function: refused by name; a nested event, an event in a loop, a
`cross` in a conditional, a contribution in an event or in `analog initial`: refused
by name. `$limit` with a one-argument user function, with no arguments, nested:
refused; with an unknown simulator function: L020. `$bound_step(0)`, `(-1)`, a
string: refused. `$discontinuity(10⁹)`: accepted (a degree); `(1.5)`: type mismatch.
`absdelay(V, -1)`: refused; `maxdelay = 1e300`: accepted. `transition` with 101 or 0
arguments, `slew` with a string: refused. `laplace_nd(V, '{}, '{})`: refused with the
rule; `zi_nd` with `T = 0` or `T < 0`: refused. `$random("s")`, `$random(1.5)`,
`$rdist_normal` with σ = −1, `$rdist_uniform` with reversed bounds, `noise_table('{})`,
an odd `noise_table`, `white_noise(-1)`, `$dist_t(s, 0)`, `$dist_chi_square(s, 0)`,
`$dist_erlang(s, 0, 1)`: each refused with the rule. `$simparam` with three
arguments, an integer name: refused; `""` and `$simparam$str("bogus")`: L025.
`$port_connected(x)` with a variable, with an internal node, `$param_given(x)`,
`$param_given($param_given(q))`, `$temperature(1)`, `$vt("x")`: refused by type or
count. Assignment to `$abstime`, a parameter, a port, a function, the module: "invalid
destination"; calling the module, a port or a parameter: "expected a function but
found …". Indexing a scalar, a parameter, a port; three indices on a 1-D array; a
string, a real or a solution-dependent index (the last compiles, clamped at run time
per E-4xx); assigning a scalar to an array; an array in an expression or a comparison:
each named. A `case` with no items: refused; duplicate, real and string items,
`casex`/`casez`: compile. 10 000 string array elements, a string doubled 40 times: fine.

**Data files** (`hunt4/pH.py`). For `$table_model` and `noise_table` alike, a missing
file, a directory, `/dev/null`, an empty file, blank lines only, one column, an
unreadable file (mode 000), a binary file, a NUL byte, `nan`/`inf` tokens, a hex
number, `1e400`, tabs and commas, semicolon-separated rows, Unicode digits, a BOM, a
1 MB file name, a 1 000-column file as a noise table, a grid header of 100 000 ×
100 000, of 10⁹, of −1 and of 0: each "cannot use '…' as $table_model data" (or
"noise_table data") with E-700's cause on the lines after. A single row compiles (a
one-knot table). A 100 000-digit number is read (to 2, and the duplicate knot warned).
CRLF line endings are fine. A 1 000-column file with one input compiles (column 1 is
the dependent). A newline inside the file name is "a string literal must be contained
on a single line". Sizes: 10⁶ rows linear did not finish in 300 s (2.5 GB), 100 MB of
rows not in 600 s, `noise_table` from a 10⁶-row file not in 300 s — the scaling of F1,
F2 and F7 — and the 100 000-row and 100 000-isoline files are F1's crash.

**Code generation at scale** (`hunt4/pD.py`, `pD2.py`). 5 000 and 20 000 separate
flow contributions: 0.4 and 3.2 s (linear). A full conductance matrix across 50 ports
(2 450 contributions): 13 s; across 150 ports (22 350): 244 s — the Jacobian is dense
by construction, so this is the honest cost. 1 000 and 10 000 leaf instances in one
module: 0.3 and 7.8 s. 20 000 and 50 000 real variables assigned and summed: 7.8 and
47 s. 2 000 and 10 000 calls of one function summed flat: the flat-chain depth guard
(the 2026-09-04 F6), as expected. Twenty and a hundred 20-pole filters: F9. A chain
of 50 modules each instantiating the previous one twice was my mistake, not a
finding — 2⁵⁰ leaves — and did not finish; the one-instance-per-level chain is
in F7's table: 50 deep 5.5 s, 200 deep 208 s and 2 GB, 1 000 deep not finished in
300 s at 6 GB; a 12-level binary tree of 4 096 leaves (8 190 instances) 198 s, where
the same 10 000 leaves flat in one module take 7.8 s — the flattening's cost grows
with the depth, not only with the instance count.

**Design choices seen, not findings.** `-D X=` and `-D "X=1 2"` are accepted (legal
values). A constant-bound `for` of 10⁹ iterations compiles in 0.1 s and is the model's
run-time problem. `$rtoi` saturates where integer `+`/`*`/`**` wrap (E-693 chose
wrapping for the integer operators; the real-to-integer conversion's saturation is C's
`(int)` behaviour made deterministic). NaN is "true" as a condition (nonzero). An
identifier of 100 000 characters is legal Verilog-A.
