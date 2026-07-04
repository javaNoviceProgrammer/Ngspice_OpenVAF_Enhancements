# Enhancement-46 — escaped identifiers + integer literal bases (version11)

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory to implement **integer literal bases** (LRM A.8.7) and complete
**escaped identifiers** (LRM A.9.3). Front-end only; no OSDI/ngspice change.

## Integer literal bases (were entirely missing, plus a crash)

`'h1F`, `'o17`, `'b1010`, `'d42`, sized `8'hFF`, signed `8'shFF` — every based
form was "encountered unexpected token": the lexer contained only a
commented-out sketch of based-number tokenization. And the LRM-legal
underscore separator (`1_000_00`) **crashed the compiler**: `eat_decimal_digits`
accepted `_` into the token, but `IntNumber::value_as_f64` parsed the raw text
(`"IntNumber token must be valid float syntax too: ParseFloatError"`).

**Fix** (`lexer`, `syntax/ast/expr_ext.rs`):

- The lexer tokenizes `[size]'[s]<base><digits>` — the unsized form from the
  `'` dispatch (alongside the `'{` aggregate arm), the sized form as a
  continuation of `number()`. Digits are validated **per base while lexing**
  (`'b12` ends the token at the `2` → ordinary parse error), a digit is
  required after the base (a bare `'h` never becomes a silently-zero literal),
  and `x`/`z` digits — not meaningful in the analog subset — are not consumed.
- Value parsing (`parse_based_int`): strip `_`, radix-parse, mask to the
  declared size (clamped 1..=32), sign-extend from the size's MSB under `s`,
  wrap to the 32-bit `integer` type (`'hFFFFFFFF` = −1). `_` separators are
  stripped in **all** number forms (plain ints, `1_234.5` reals, SI-scaled).

## Escaped identifiers (half-wired)

The lexer already emitted `EscapedIdent` tokens (backslash through the last
non-whitespace character) and mapped them to `IDENT` — but two defects made
the feature unusable:

1. **`Name::resolve` stripped the last character** along with the backslash
   (`raw[1..len-1]`, written for a token shape that included the terminating
   whitespace). `\foo` resolved to `"fo"`, so the escaped and plain spellings
   of a name never matched — and the compiler's own `std.va` def-map snapshot
   had baked in `logi` for the escaped `\logic` discipline, hiding the bug.
   Fixed to strip only the backslash; the stale snapshots were refreshed.
2. **The E-5 elaboration re-rendered substituted names unescaped.** An escaped
   net inside a flattened submodule (`\n-1` → instance-prefixed `u1_n-1`)
   was emitted raw into the synthesized text, which no longer lexed
   ("unexpected token '-'"). A `render_name` helper now re-escapes any
   substitution value that isn't a plain identifier (`\u1_n-1 `), applied in
   `render_with_holes` (which also gained the `EscapedIdent` substitution arm
   — escaped *uses* keyed by their resolved name) and the net-declarator
   re-render path.

Keyword spellings (`\module`) work as names — `EscapedIdent` never goes
through keyword mapping.

## What now works (`escid_examples/`, all exact)

| case | result |
|---|---|
| `'h1F + 'o17 + 'b1010 + 'd42` | 31+15+10+42 |
| `8'hFF` / `8'shFF` / `4'sb1000` | 255 / −1 / −8 (size mask + sign extension) |
| `'hFFFFFFFF` | −1 (32-bit wrap) |
| `1_000_00`, `16'hAB_CD`, `1_234.5` | separators stripped everywhere |
| whole-module sum | **0.1443252345 V exactly** |
| `\2wire`, `\value#`, `\r+val` | nets/vars/params with specials |
| `\mid` ≡ `mid` | one net (LRM equivalence) |
| escaped net in flattened submodule | re-escaped, 2k series exact |
| `\module` | keyword spelling as a name |
| `'h`, `'sh`, `'b12`, `8'squark` | clean parse errors, no crash, no silent 0 |

`verify_escid.py`: 12/12 PASS. Regression: all 42 example verify suites ALL
PASS; 65/65 crate tests (`lexer`/`tokens`/`syntax`/`parser`/`hir_def`/`hir`/
`hir_ty`/`hir_lower`/`sim_back`) after refreshing the snapshots that had
encoded the `\logic`→`logi` bug.

## Notes

- Sized literals wider than 32 bits clamp to the 32-bit `integer` type.
- The `'d` form takes decimal digits only; `x`/`z` digits are rejected by
  construction (analog subset).
