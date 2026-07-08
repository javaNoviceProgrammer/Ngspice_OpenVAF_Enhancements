# Enhancement-105 — `$sscanf` / `$fscanf` honour the format conversion base

Gap-hunt round 3 extended the runtime-value batteries into string and file I/O.
A `$sscanf` value battery — parsing known strings and checking the parsed
results — turned up a real bug: the scanf functions **ignore the format
string's conversion base**.

## The bug

`$sscanf` / `$fscanf` parse each field by the destination variable's *type*
(integer via `strtol`, real via `strtod`, string as the next token) and never
look at the format string. For integers the runtime used `strtol(p, &end, 0)`
— base **0**, which auto-detects the base from the *input's* own prefix. So the
conversion character had no effect:

| call | expected | got (before) |
|---|---|---|
| `$sscanf("ff", "%h", x)` | 255 | 0 (needs `"0xff"`) |
| `$sscanf("17", "%o", x)` | 15 | 17 (parsed as decimal) |
| `$sscanf("1010", "%b", x)` | 10 | 1010 (parsed as decimal) |
| `$sscanf("42", "%d", x)` | 42 | 42 ✓ |

Only the default (decimal / real / string) cases happened to work.

## The fix

The lowering now reads the format string (a compile-time literal in practice)
and picks the integer base **per field** from its conversion character, then
dispatches to a base-specific runtime scanner:

- **`hir_lower`** (`expr.rs`): `lower_scanf` receives the format expression,
  extracts the ordered conversion characters (`scanf_conversion_chars`), and
  maps each integer field to `ScanKind::IntHex` (`%h`/`%H`/`%x`/`%X`),
  `IntOct` (`%o`/`%O`), `IntBin` (`%b`/`%B`), or the default `Int`. A
  non-literal format falls back to the previous type-driven behavior.
- **`hir_lower`** (`callbacks.rs`) + **`osdi`** (`compilation_unit.rs`): the new
  `ScanKind` variants map to new runtime symbols
  `osdi_scan_hex`/`_oct`/`_bin`.
- **`osdi/stdlib.c`**: the three new scanners call `strtol` with base 16 / 8 /
  2, so the format's base is honoured (e.g. `"ff"` → 255 without a `0x`
  prefix). `osdi_scan_int` keeps its base-0 auto-detect for `%d` and untyped
  fields, so existing behavior is unchanged. The C spelling `%x` is accepted as
  an alias for the Verilog `%h`.

## Verification

`sscanf_examples` (7/7): a device parses fixed input strings and exposes the
parsed values as operating-point variables. It checks `%h ff→255`,
`%o 17→15`, `%b 1010→10`, `%d 42→42` (each wrong under the old base-0
behavior), a repeated conversion (`%h %h → 160, 255`), and a mixed
integer/real parse (`%d %g → 7, 8.5`) with the correct match count. The wider
gap-hunt batteries behind this (string/file-function compile probes, and a
`$sscanf` value battery over `%d`/`%g`/`%e`/`%h`/`%o`/multi-field) otherwise
matched their expected results. Full regression: all verify suites plus the
OpenVAF integration tests remain green.
