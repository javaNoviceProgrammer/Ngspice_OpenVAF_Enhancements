# Malformed differential-token NULL-deref fix (Enhancement-238)

A third find from the same memory-safety deep dive (after [E-236](../../enhancements_doc/Enhancement-236.md)
and [E-237](../../enhancements_doc/Enhancement-237.md)), surfaced by fuzzing
degenerate output tokens.

`gettoks()` ([dotcards.c](../../ngspice-46/src/frontend/dotcards.c)) parses the
output tokens of `.save`/`.print`/`.plot`/`.four` (and `.measure` variables). For
a differential form like `v(a,b)` it locates the comma `c` and the close paren
`r`, then splits the second operand off at `r`:

```c
r = strchr(t, ')');
c = strchr(t, ',');
...
if (c != r) {        /* a comma distinct from ')' -> differential */
    *r = '\0';       /* <-- r is NULL for a malformed "v(1," */
    ...
}
```

A **malformed** token such as `v(1,` has a comma but **no** `)`, so `r` is `NULL`
while `c` is not; `c != r` is then true and `*r = '\0'` dereferences NULL →
**SIGSEGV**. It is reachable from `.save`/`.print`/`.plot`/`.four`/`.measure` — a
one-line typo in a netlist crashes the simulator.

The fix guards the split with `if (r && c != r)`, so a malformed token degrades
to a harmless parse (the well-formed differential path is unchanged).

## Verify

```sh
python3 verify_malftoken.py
```

Three checks: `.print tran v(1,` no longer crashes; the same malformed shape
across `.save`/`.plot`/`.four`/`.meas` and other prefixes (`i(1,`, `vdb(1,`,
`vm(1,`) no longer crashes; and a well-formed `v(1,2)` still rewrites to
`v(1)-v(2)` and computes the correct value (1.5 V).
