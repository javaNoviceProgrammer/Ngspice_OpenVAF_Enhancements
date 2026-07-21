# Enhancement-271 — ngspice: `let` no longer reads before its buffer on an empty LHS

The same ASan/UBSan command-parser fuzz that produced Enhancement-270 also flagged a
one-byte out-of-bounds read in the `let` command (`com_let`, `src/frontend/com_let.c`).

## The bug

`com_let` flattens everything after `let` into a heap string `p`, splits the RHS off
at the first `=`, and then NUL-terminates the destination vector name at the first
`[`. It next trims trailing whitespace from the name:

```c
for (q = p + strlen(p) - 1; *q <= ' ' && p <= q; q--)
    ;
*++q = '\0';
```

When the left-hand side is a bare bracket — `let [[ = …`, where the leading `[` has
just been turned into `'\0'`, leaving `p` an empty string — or is entirely
whitespace, `strlen(p)` is `0`, so `q` starts at `p - 1`. The loop test evaluates
`*q` **before** the `p <= q` guard can short-circuit, so it dereferences `p[-1]`:
a read one byte before the allocation. AddressSanitizer reported a
`heap-buffer-overflow READ of size 1` at `com_let.c` on the input
`let [[ = @#*[r] v1 -o i(v1)`.

The stray byte does not fault deterministically on the shipped build (it is almost
always valid heap metadata), but it is a genuine out-of-bounds read on malformed
input and could fault if `p` were allocated at the start of a page.

## Fix

`src/frontend/com_let.c`: test the bound **before** dereferencing, so `&&`
short-circuits and `q` is never read while it points below `p`:

```c
for (q = p + strlen(p) - 1; p <= q && *q <= ' '; q--)
    ;
*++q = '\0';
```

An empty or all-whitespace name then falls through unchanged to the existing
`"bad variable name"` check, which rejects it cleanly. No valid `let` is affected.

## Verification

`examples/letoob_examples/verify_letoob.py` (5 checks): the fuzz-found `let [[ = …`,
a single-bracket `let [ = 5`, and an all-whitespace LHS each error quickly with
`bad variable name` and no crash or hang; and a plain `let a = 5` and an indexed
`let a[1] = 7` still assign correctly. Re-running the original input under an
ASan-instrumented build no longer reports the overflow. Full dual-solver example
regression passes.

## Scope

One source file (`src/frontend/com_let.c`), a one-line reordering of a loop
condition. No change to any valid `let`.
