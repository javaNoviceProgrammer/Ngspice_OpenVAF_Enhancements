# initfile_examples — an initialisation file must not crash ngspice at start-up

Finding F6 of the 2026-09-06 solver-core hunt
([`docs/bug_hunts/2026-09-06_klu-sparse-solver-cores.md`](../../docs/bug_hunts/2026-09-06_klu-sparse-solver-cores.md))
first looked like an XSPICE teardown fault. It was not: since Enhancement-558 made
`com_source` unquote every word by freeing it and installing the unquoted copy,
`inp_source()`'s *borrowed* word — the caller's own pointer — was freed inside the call
and again by the caller. Any `.spiceinit` or `spice.rc` found in the deck's directory,
in the current directory or in `$HOME` ended the run before the first line of output
(`pointer being freed was not allocated`, exit 134). `inp_source()` now hands
`com_source()` a heap copy and frees whatever comes back.

The suite runs a trivial deck with an init file in each of the three places, and the
F6 deck itself (two code models, op then ac) with the analog library loaded from a
`.spiceinit` beside the deck.

## Run

```
python3 verify_initfile.py
```

5 checks per solver, all PASS.
