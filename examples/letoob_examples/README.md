# letoob_examples — Enhancement-271

The `let` command used to read **one byte before its buffer** on an empty or
all-whitespace left-hand side. `com_let` flattens its arguments into a heap string
`p`, splits the RHS off at `=`, and NUL-terminates the vector name at the first `[`.
It then trims trailing whitespace:

```c
for (q = p + strlen(p) - 1; *q <= ' ' && p <= q; q--) ...
```

When the LHS is a bare bracket — `let [[ = ...`, so `p` becomes `""` — or is all
whitespace, `q` starts at `p - 1` and `*q` is dereferenced **before** the `p <= q`
guard short-circuits: a one-byte read before the allocation, caught by
AddressSanitizer (`heap-buffer-overflow READ`) on `let [[ = ...`.

Fix (`src/frontend/com_let.c`): test the bound first (`p <= q && *q <= ' '`). An
empty name then falls through to the existing `"bad variable name"` error. No valid
`let` is affected.

## Verify

```
python3 verify_letoob.py
```

Five checks: `let [[ = ...`, `let [ = 5`, and an all-whitespace LHS each error
quickly with `bad variable name` (no crash, no hang); a plain `let a = 5` and an
indexed `let a[1] = 7` still assign correctly.
