# Enhancement-238 — `gettoks`: fix a NULL-deref crash on a malformed differential token

A third find from the same memory-safety deep dive (after [E-236](Enhancement-236.md)
and [E-237](Enhancement-237.md)), surfaced by fuzzing degenerate output tokens
and reproducible on the shipped binary.

## The bug

`gettoks()` (`frontend/dotcards.c`) parses the output tokens of
`.save`/`.print`/`.plot`/`.four` (via `ft_savedotargs`) and `.measure` variables
(via `com_measure2`). For a differential form like `v(a,b)` it finds the comma
`c` and the close paren `r`, then splits the second operand off at `r`:

```c
r = strchr(t, ')');
c = strchr(t, ',');
if (!c)
    c = r;
if (c)
    *c = '\0';
...
if (c != r) {        /* a comma distinct from ')' -> it's a differential */
    *r = '\0';       /* <-- r is NULL for a malformed "v(1," */
    wl = wl_cons(copy(c + 1), NULL);
    ...
}
```

A **malformed** token such as `v(1,` has a comma but **no** `)`, so
`r = strchr(t, ')')` is `NULL` while `c` (the comma) is not. `c != r` is then
true, and `*r = '\0'` dereferences NULL → **SIGSEGV** (`EXC_BAD_ACCESS` at
address 0x0, confirmed via lldb: `gettoks` ← `ft_savedotargs`).

Reproduce on the stock binary:

```
v1 1 0 dc 1
r1 1 2 1k
r2 2 0 1k
.tran 1u 1m
.print tran v(1,
.end
```

→ `ngspice -b` segfaults. The token is a one-character typo (missing `)`), and it
crashes the simulator across `.save`/`.print`/`.plot`/`.four`/`.measure`.

## The fix

Require `r` to be non-NULL before splitting on it:

```c
if (r && c != r) {
    *r = '\0';
    ...
}
```

When the token has a comma but no close paren, `r` is NULL and the
second-operand split is skipped, so the malformed token degrades to a harmless
parse instead of crashing. Every well-formed case is unchanged:

* `v(a,b)` — `c` = comma, `r` = `)`, both non-NULL, `c != r` → split (as before);
* `v(a)` — no comma, `c = r = )` → `c == r`, skipped (as before);
* `i(x)` — the branch sets `c = r = NULL` → skipped (as before).

## Verification (`examples/malftoken_examples`)

`verify_malftoken.py` (3 checks): `.print tran v(1,` no longer crashes; the same
malformed shape across `.save`/`.plot`/`.four`/`.meas` and other prefixes
(`i(1,`, `vdb(1,`, `vm(1,`) no longer crashes; and a well-formed `v(1,2)` still
rewrites to `v(1)-v(2)` and computes the correct value (1.5 V). A broad
malformed-token sweep (prefixes × bodies × cards, hundreds of combinations) is
crash-free after the fix.

## Scope

ngspice frontend only — one guard in `dotcards.c` (`gettoks`). No solver,
analysis, device, or compiler change; well-formed parsing is unchanged. Full
regression: 196/196.
