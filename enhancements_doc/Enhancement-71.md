# Enhancement-71 — display-task audit: format flags/width for every conversion + the `%b` segfault

This document describes Enhancement-71: a systematic audit of the display
tasks (`$strobe`, `$display`, `$write`, `$monitor`, `$debug`) and the full
format-specifier surface. Front-end + OSDI codegen — no ngspice change.

## The audit

**Two defects found and fixed; everything else verified against exact
printf output.**

### Defect 1: flags and width rejected for every non-real conversion

`%5d`, `%-8d`, `%+d`, `%08d`, `% d`, `%#o` — all standard display syntax —
failed to compile with *"failed to parse format specifier; unexpected
character d"*. Only real conversions (`%10.3e`, `%.2f`) accepted a
`[flags][width][.precision]` prefix: the inference-side parser
(`hir_ty/inference/fmt_parser.rs`) only *terminated* on `e/f/g/r`, and
the lowering-side translator (`hir_lower/fmt.rs`) had the same
real-only assumption baked into its catch-all branch.

**Fix, both layers:** the parser now terminates on every conversion
character and reports it (`ParseResult::conversion`), so inference types
the argument from the conversion (`d/h/o/b/c` → integer, `s` → string,
`e/f/g/r` → real) with flags/width/precision legal everywhere; the
lowering translator collects the general prefix verbatim (consuming one
extra integer argument per dynamic `*`) and re-emits it in the generated
C format with the conversion translated (`%h`→`%x`, `%b`→`%s` over a
pre-formatted binary string, `%r`→engineering-notation `f%c` pair).

### Defect 2: `%b` crashed the simulator (pre-existing)

The OSDI print codegen (`osdi/src/compilation_unit.rs`) called
`fmt_binary(val)` to build the binary string and remembered the result
**for `free()` — but never passed it to `snprintf`**. The matching `%s`
consumed a garbage pointer: any model printing `%b` segfaulted ngspice.
Latent since the print machinery was built (the in-tree users never
exercised `%b` at runtime). One line: push the formatted string as an
argument before remembering it for free.

## Verified printf-exact (18 checks)

`%5d` → `[   42]`, `%-5d` → `[42   ]`, `%05d` → `[00042]`, `%+d` →
`[+42]`, `%8s`/`%-8s`, `%4h` → `[  ff]`, `%8b` → `[     101]`, dynamic
`%*d`, `%10.3e` → `[ 1.235e+03]`, `%#o` → `[010]`, all base conversions
(`hex=ff HEX=FF oct=10 bin=101 chr=A`), `%%`, `%m` (module path),
escape sequences, bare-argument defaults (`%g`/`%d`/`%s` inferred), and
all five display kinds print (`$write` joins lines; `$monitor`/`$debug`
fire — their values reflect the evaluation they run in, per LRM).

## Examples (`display_examples/`, 18 checks, ALL PASS)

`verify_display.py` + `display_fmt.va` (the format tour) +
`display_kinds.va` (kinds, `%m`, escapes).

## Regression

All 65 example verify suites pass; the integration suite 28/28; crate
tests pass; the VA_TEST corpus compiles 92/92; zero-warning build
maintained.
