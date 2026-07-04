# Enhancement-48 — string literal escape sequences (version11)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to complete **string literal escape handling** per LRM 2.7.1.
One function in `syntax`; no OSDI/ngspice change.

## The defects

The LRM escape set for string literals is `\n`, `\t`, `\\`, `\"`, and `\ddd`
(a character given by one to three octal digits). The probe found:

| escape | before |
|---|---|
| `\n`, `\t`, `\\`, `\"` | worked |
| `\ddd` octal | **unsupported** — printed literally |
| `\\n` (literal backslash, then `n`) | **corrupted** — printed backslash + real newline |

Root cause: `StrLit::unescaped_value` chained sequential `str::replace`
calls, with `\n` replaced *before* `\\` — the classic overlapping-escape bug
(the `\n` inside `\\n` was consumed first, orphaning the leading backslash) —
and simply had no `\ddd` handling.

## The fix

`unescaped_value` is now a single left-to-right pass:

- `\n`, `\t`, `\\`, `\"` — the LRM basics;
- `\ddd` — one to three octal digits, greedy, out-of-range values degrade to
  the replacement character;
- backslash before a (possibly CRLF) newline keeps the newline — the
  pre-existing line-continuation extension, behavior unchanged;
- any other escape (and a trailing backslash) is preserved verbatim.

The audit confirmed every string consumer already routes through this one
function — `$strobe`/`$display`/`$swrite` format strings, string literal
values and comparisons, `(* desc= *)`/`units` attribute strings,
`@(initial_step("phase"))` phase names, and lint-attribute names — so the fix
applies uniformly with no second unescape path to drift.

## What now works (`stresc_examples/`, all verified)

| case | result |
|---|---|
| `"\101\102\103"` in `$strobe` | prints `ABC` |
| `"\060\61"` (3- and 2-digit forms) | prints `01` |
| `"a\\nb"` | prints `a\nb` — literal backslash + n (the old bug printed a newline) |
| `"\101\102" == "AB"` | true — octal and plain spellings are the same string |
| `"x\\ny" == "x\\ny"`, `"a\qb" == "a\qb"` | overlap-safe, unknown escapes consistent |
| `\n`/`\t`/`\\`/`\"` rendering | unchanged, exact |

`verify_stresc.py`: 8/8 PASS. Regression: all 44 example verify suites ALL
PASS; `syntax`/`hir_def`/`basedb`/`hir_lower`/`sim_back` crate tests 52/52.

## Notes

- `%%` in format strings is printf-level, not a string escape — untouched.
- Multi-line strings remain tolerated with the backslash-newline continuation
  keeping the newline, exactly as before this change.
