# Enhancement-793: `%c` of 0 no longer cuts the line — the NUL ended the formatted text and took the line break with it — and `%b` of 0 prints `0`

**Scope:** D3 of the
[openvaf-r hunt of 2026-10-04](../docs/bug_hunts/2026-10-04_openvaf-r-run-time-domains-filters-and-instances.md),
and `%b` of 0, found beside it. openvaf:
- `hir_lower/src/fmt.rs`: `%c` lowers to `%s` with `FmtArgKind::Char`.
- `osdi/src/compilation_unit.rs`: `print_callback` passes `fmt_char(value)`.
- `osdi/stdlib.c`: `fmt_char` and its constant table `FMT_CHAR_STR`; `fmt_binary` handles 0.

`examples/vafslips_examples/` (section [3], fifteen checks). **openvaf only.**

**Suites:** [`vafslips_examples`](../examples/vafslips_examples/) 67 of 67 per solver (9 of the 15
in [3] fail on the E-790 binaries); `fmtdiag`, `display` and `scanfmt`, within
the full sweep (537 of 537); the workspace tests.

## What was wrong

**`%c` of 0.** `$strobe`, `$display`, `$fdisplay` and `$sformat` build their text with `snprintf`
and hand it on as a C string. `%c` was C's own `%c`, so a 0 argument wrote a NUL into the text.
Everything after it was lost, including the line break:

```
$strobe("[%c|tail %d]", 0, 7);   $strobe("[%c]", 65);
```

printed `[[A]`: the first line cut after `[`, the next glued on. `$sformat(s, "S[%c]after", 0)`
left `S[` in `s`. A value of 256, or any multiple of 256, did the same, since `%c` prints the low
eight bits.

**`%b` of 0.** `%b` printed nothing for 0. `fmt_binary` sized its string with
`32 - __builtin_clz(val)`, and `__builtin_clz(0)` is undefined:
- on AArch64 it gives 32, so the length was 0 and the string empty;
- on x86-64 it compiles to `bsr`, which leaves its result unset for 0, so the length (and the
  `malloc` and the loop that fills it) came from whatever the register held.

## The change

`%c` is rendered as `%s` of a one-character string. `fmt_char(value)` returns an entry of a
constant 256-entry table. Entry 0 is the empty string, which is what a terminal shows for a NUL.
So the rest of the line, and its break, survive. Nothing is allocated, and a width still pads
(`%3c`, `%-3c`). `fmt_binary` takes a length of 1 for 0 and prints `0`.

## The checks

vafslips [3], at an operating point:
- `[%c]` of 0 prints `[]`, and `[%c|tail %d]` of 0, 7 prints `[|tail 7]`, each on its own line;
- `[%c%c%c]` of 72, 0, 73 prints `[HI]`;
- `%c` of 65, 321 and 256 prints `A`, `A` and nothing;
- `%3c` and `%-3c` pad;
- `%b` of 0, 5 and -1 prints `0`, `101` and 32 ones, and `%0b` of 0 prints `0`;
- `$sformat` keeps `S[]after`;
- no output line carries two strobes.

## Limits

- A NUL cannot be printed at all. The line is a C string from the model to the simulator, and
  `%c` of 0 prints nothing.
