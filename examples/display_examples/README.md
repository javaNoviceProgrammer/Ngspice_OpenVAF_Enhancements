# display_examples — display tasks + format specifiers (Enhancement-71)

Validates the display tasks (`$strobe`, `$display`, `$write`, `$monitor`,
`$debug`) and the **full format-specifier surface** using the committed
`openvaf-r` and `ngspice-46`. The Enhancement-71 audit found two defects,
both fixed:

1. **Flags and width were rejected for every non-real conversion** —
   `%5d`, `%-8d`, `%+d`, `%08d`, `% d`, `%#o` all failed with
   "unexpected character": the format parser only terminated on real
   conversions, in both the type-checking and code-generation layers.
   The general `[flags][width][.precision][conversion]` form now works
   for every conversion, including dynamic `%*d` widths.
2. **`%b` crashed the simulator** (pre-existing, latent): the print
   codegen built the binary string and remembered it for `free()` but
   **never passed it to `snprintf`** — the matching `%s` read a garbage
   pointer. Any model printing `%b` segfaulted ngspice.

Pinned printf-exact: all flags (`- + 0 # space`), fixed and dynamic
widths, precision, all conversions (`%d %h %H %o %b %c %s %e %f %g`),
`%%`, `%m` (module path), escape sequences, bare-argument defaults, and
all five display kinds.

Enhancement-660 (hunt F16 of 2026-09-18) adds `display_setup.va`: a display
or severity task whose arguments are solution-independent runs in the
model's setup code, which ngspice runs twice per analysis, and printed
twice -- the first copy before the draws and the corner were applied. The
setup pass's copies are now held and superseded by the temperature pass's;
six checks (once per analysis, the corner and the draw banners, a `.dc temp`
sweep, an `altermod`, a failed setup).

## Run

```bash
python3 verify_display.py    # 30 checks
```
