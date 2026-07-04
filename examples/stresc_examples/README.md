# stresc_examples — string literal escape sequences (Enhancement-48)

Demonstrates the complete **LRM 2.7.1 string escape set** — `\n`, `\t`, `\\`,
`\"`, and `\ddd` (one to three octal digits) — using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

- **Octal escapes were unsupported**: `"\101\102\103"` printed literally as
  `\101\102\103` instead of `ABC`.
- **Overlapping sequences were corrupted**: the unescaper was a chain of
  sequential `str::replace` calls with `\n` handled *before* `\\`, so
  `"a\\nb"` — a literal backslash followed by `n` — came out as a backslash
  plus a **real newline**.

Enhancement-48 replaces the chain with a single left-to-right pass covering
the full LRM set. A backslash before a (possibly CRLF) newline keeps the
newline (line-continuation extension, unchanged behavior), and unknown
escapes are preserved verbatim. Every string consumer — `$strobe`/`$display`
format strings, string values and comparisons, attribute strings, lint names —
already routed through the one function, so the fix applies everywhere at
once.

## Run

```
python3 verify_stresc.py
```

Checks (ALL PASS): the `$strobe` rendering matrix (tab, newline, backslash,
quote, the previously-corrupted `\\n` round-trip, octal `ABC` and digit
forms) and compile-time string consistency (`"\101\102" == "AB"`,
overlap-safe self-equality, unknown escapes comparing consistently — module
output 7 exactly).
