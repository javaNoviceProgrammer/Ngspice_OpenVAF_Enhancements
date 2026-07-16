# Enhancement-212 — crash hardening: seven user-triggerable crashes

A static-analysis pass (clang's analyzer over the ngspice tree) combined with
**argument fuzzing** of every frontend command and malformed/degenerate netlists
surfaced **seven reproducible, user-triggerable crashes** (SIGSEGV / SIGABRT) in
stock ngspice code. Every one is in **user-input handling** — command parsers, the
`.op` output path, and netlist recursion — never in the numerical core (the device
models, the OSDI loader, Sparse 1.3, KLU, and the analysis drivers were all audited
and found clean). All seven are fixed here.

The common thread is a missing guard on an edge of the input: a trailing flag, an
empty argument list, a missing operand, an empty circuit, a `bsearch` miss, or an
unbounded self-reference.

## Command-parser NULL dereferences

**1. `iplot -w` / `iplot -d` with the flag as the trailing token**
([`breakp.c`](../ngspice-46/src/frontend/breakp.c), `com_iplot`). The flag handler
consumes the next word (`wl = wl->wl_next`) and guards it with `if (wl) {…}` — which
proves `wl` can be NULL — then at the loop bottom does `wl = wl->wl_next`
**unconditionally**, dereferencing the NULL. Repro: `iplot -w` with no window value.
Fix: guard the advance (`if (wl) wl = wl->wl_next;`).

**2. bare `altermod`** ([`device.c`](../ngspice-46/src/frontend/device.c),
`com_altermod` → `com_alter_common`). `com_alter` guards `if (!wl)`, but its sibling
`com_altermod` does not, passing an empty list straight into `com_alter_common`,
which sets `wlin = wl_head` (NULL), calls `wl_nthelem(100, NULL)` → NULL, then
`eq(wlin->wl_word, "]")` derefs NULL. Repro: `altermod` with no arguments. Fix: guard
the empty `wl_head` with a clean error.

**3. `meas … FIND` / `WHEN` with a missing operand**
([`vectors.c`](../ngspice-46/src/frontend/vectors.c), `vec_get`). A malformed measure
statement (`meas tran x FIND`, `… WHEN`, `FIND v(1)` with no `WHEN`/`AT`, across
tran/dc/ac/sp) leaves `meas->m_vec` NULL, which flows into `com_measure_when` →
`vec_get(NULL)` → `copy(NULL)` = NULL → `strchr(NULL, '.')`. Fix: make `vec_get`
NULL-safe (`if (!vec_name) return NULL;`) — the common sink, so every trigger reports
"no such vector" instead of crashing. Every caller already handles a NULL return.

## Output-path abort

**4. empty / all-commented deck + `.op`**
([`dotcards.c`](../ngspice-46/src/frontend/dotcards.c), `ft_cktcoms`). A circuit with
no non-ground nodes — e.g. a deck whose every component is commented out — produces an
`op` plot with no data vectors, so `pl_dvecs` is NULL. The former
`assert(pl_dvecs != NULL)` aborted (**SIGABRT**; ngspice's autotools build defines no
`NDEBUG`, so asserts are live), and with `-DNDEBUG` the next line would dereference
NULL. Fix: guard with `if (plot_cur && plot_cur->pl_dvecs)` and skip the (empty) op
printout. The solver had already handled the empty matrix correctly — this was purely
in output formatting.

## Solver-glue latent guard

**5. KLU pole-zero setup** ([`cktpzset.c`](../ngspice-46/src/spicelib/analysis/cktpzset.c)).
A `bsearch` miss for the drive pointer was reported with a `printf` and then
**dereferenced anyway** (`job->PZdrive_pptr = matched->CSC_Complex`). This is latent —
`SMPmakeElt` creates the element just above, so it is always in the bind table and the
miss cannot occur today — but the guard was objectively broken. Fixed by adding the
missing `else`/NULL path, matching the correct idiom already in `cktsetup.c`.

## Netlist-recursion stack overflows

**6. `.include` recursion** ([`inpcom.c`](../ngspice-46/src/frontend/inpcom.c),
`inp_read`). `inp_read` tracked a `call_depth` but **never limited it**, so a file
that `.include`s itself — directly, via an `A → B → A` cycle, or via a `.lib` section
that `.include`s its own file — recursed until the C stack overflowed (**SIGSEGV**).
(`.lib` *files* are de-duplicated by `find_lib` and read once; the crash is always via
`.include`.) Fix: cap the depth at `INP_MAX_INCLUDE_DEPTH = 50`; a cycle now reports an
error. No legitimate netlist nests includes anywhere near this deep — a 49-level chain
still reads fine.

**7. `.func` recursion** ([`inpcom.c`](../ngspice-46/src/frontend/inpcom.c),
`inp_expand_macro_in_str`). The expander re-expands a substituted function body with no
depth guard, so `.func f(x)={f(x)}` (or a mutual `f ↔ g`) expanded forever and
overflowed the stack — each recursion frame also holds a `params[FCN_PARAMS]` array
(~8 KB), so it fails near ~1000 deep. Fix: a `macro_depth` counter capped at
`INP_MAX_MACRO_DEPTH = 100`, reset on every error path. Legitimate nested and mutual
functions still expand to the correct values.

## Verification

New suite [`examples/crashfix_examples/verify_crashfix.py`](../examples/crashfix_examples/verify_crashfix.py)
(17 checks × both solvers) drives every repro and asserts it now exits gracefully — no
signal — instead of crashing, while every valid form still works (`iplot -w 3 v(1)`,
`altermod nm vto=0.7`, `meas tran vmax MAX v(1)` → 1.0, a normal `.op`, KLU `.pz`, a
legitimate nested `.include`, and `.func sq(x)={x*x}` → `sq(4) = 16`). Crashes are
detected from the child's signal exit code (SIGSEGV/SIGABRT), which the pre-fix binary
returned. Full regression: 172/172, both solvers.

## Scope

ngspice-only, six files (`breakp.c`, `device.c`, `vectors.c`, `dotcards.c`,
`inpcom.c`, `cktpzset.c`). No functional change to correct decks — the fixes turn
crashes on malformed or degenerate input into graceful errors. The netlist-recursion
caps mirror the include/expression-depth hardening OpenVAF-r received in
[Enhancement-148](Enhancement-148.md); ngspice's netlist reader had lacked the
equivalent guards.
