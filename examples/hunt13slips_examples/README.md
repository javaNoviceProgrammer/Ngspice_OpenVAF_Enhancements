# hunt13slips_examples — Enhancement-640

The diagnostic slips of the 2026-09-14 hunt (F6), each pinned: two messages
without runs of spaces; `--dump-json` implemented (the evaluation MIR as
`<stem>_<module>.json`, JSON only under `--dry-run`); a message-less
`$fatal`/`$error`/`$warning`/`$info` printing its own name with the context;
the `std`/`std_rel` and non-real-parameter wordings; `-C` warned as consumed
by nothing; a real default that folds to infinity refused like the literal
`1e400`; and a statement at module scope reported once, as what it is.

Since E-694 (hunt F4 of 2026-09-21) the dump's strings are escaped: a module
with a `$fatal`/`$error`/`$warning`/`$info` -- whose message ends in a real
newline -- produced a file no JSON parser accepted.

Run: `python3 verify_hunt13slips.py` (8 checks per solver, both solvers).
