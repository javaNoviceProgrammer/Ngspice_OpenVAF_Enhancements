# rawparam_examples — Enhancement-607

The raw-file writers spelled a current-typed `@dev[param]` vector `i(@r1[i])`,
a name nothing reads back after `load` (`@r1[i]` asks the absent device,
`i(@r1[i])` is the parser's i() of a non-source) — every OSDI terminal current
`.option savecurrents` records was affected, in `write` and batch `-r` alike.
Both writers keep a `@` name verbatim, and the reader puts an old file's
`i(@...)`/`v(@...)` back.

Run: `python3 verify_rawparam.py` (7 checks per solver, both solvers).
