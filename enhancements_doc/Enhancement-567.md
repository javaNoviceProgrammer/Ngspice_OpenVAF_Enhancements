# Enhancement-567: an initialisation file no longer kills the run at start-up — `inp_source` hands `com_source` a copy it may free (bug hunt F6)

**Scope:** finding F6 of the
[2026-09-06 KLU/Sparse bug hunt](../docs/bug_hunts/2026-09-06_klu-sparse-solver-cores.md),
the one that was not a solver defect: `inp_source()` in `src/frontend/inp.c`. **ngspice
only.**

**Suites:** new [`initfile_examples`](../examples/initfile_examples/) (5 checks per solver,
both solvers); Enhancement-558's `rawfstring` and `paramgiven` pass; `solvercore`,
`ctrlnode` pass; full sweep 466 of 466 on both solvers. The bug-hunt write-up's F6
section is rewritten with the real cause.

## What was wrong

Every `.spiceinit` or `spice.rc` that ngspice found — in the deck's directory, in the
current directory, or in `$HOME` — ended the run before the first line of output:

```
ngspice(...) malloc: *** error for object 0x...: pointer being freed was not allocated
```

exit 134, under either solver, whatever the file contained (a single `set foo=1` was
enough) and whatever the deck was. The hunt met it as an XSPICE deck that "aborted on
exit", because the failing decks happened to live in a scratch directory holding a
`.spiceinit` written to load the code models, and the variants that "worked" had been
written elsewhere; guard-malloc placed nothing, and under `MallocStackLogging` the double
free went unnoticed and the deck ran. Rebuilding `main.o` with line information put the
bad free at `read_initialisation_file()` in `main.c`, called at start-up.

The mechanism is a one-day-old regression. `inp_source(file)` builds a stack wordlist
whose single word is *borrowed* from its caller — its own comment says "nothing in it
should be freed" — and calls `com_source()`. Enhancement-558 (2026-09-05, hunt F10) made
`com_source()` unquote every word it is given by freeing the word and installing the
unquoted copy. `read_initialisation_file()` passes its `tprintf`'d path, `com_source()`
frees it, the caller frees it again. The other callers of `inp_source()` — `tclspice`,
`sharedspice`, `cpitf`'s `SPICE_SCRIPTS` handling — pass string literals or their own
buffers and were freed underneath them the same way.

## What changed

`inp_source()` copies the file name onto the heap before calling `com_source()` and
frees whatever word `com_source()` leaves in the list afterwards — the original if
unquoting left it alone, the unquoted copy if not. Nothing else moves: `com_source()`
still unquotes (E-558's behaviour is kept, its suites pass), the borrowed-word
convention is simply no longer relied upon. Nutmeg's `nutinp_source()`/`nutcom_source()`
pair does not unquote and needed nothing.

## Verification

| check | result |
|---|---|
| `.spiceinit` with `set foo=1` beside a trivial RC deck; in the current directory; in `$HOME` (`HOME=` override) | exit 134 before (the version12 binary), exit 0 and v(out) = 1 after, all three, both solvers |
| the F6 deck (two XSPICE code models, op then ac) with the analog library loaded from a `.spiceinit` beside it | exit 0, v(mid) = 0.5, |v(out)| = 39.788 (before: exit 134, no output) |
| the F6 deck under guard-malloc | clean |
| `rawfstring_examples`, `paramgiven_examples` (Enhancement-558) | pass on both solvers |
| `initfile_examples`; full sweep | 5 / 5 both solvers; 466 of 466 |
