# Enhancement-776: a Verilog-A file is opened in binary mode on Windows — the C runtime's text mode wrote every newline as two bytes, so `$ftell` counted 171 bytes for 160 written and a `$fseek` to an offset `$ftell` gave landed elsewhere

**Scope:** OpenVAF, the OSDI runtime library: `openvaf/osdi/stdlib.c` (`osdi_fopen`), in
code compiled only for a Windows target (`_WIN32`; the library is compiled per target with
`-target <triple>`). The rest of the Windows CI run's findings are
[E-775](Enhancement-775.md) and [E-777](Enhancement-777.md).

**Suites:** fileio on the Windows CI job is the check (`$ftell offset (171 == 160 bytes
written)` failed there); the full sweep on macOS, 536 of 536.

## What was wrong

`$fopen(name, mode)` passed the Verilog-A mode -- "r", "w", "a", "r+" ... -- to the C
library's `fopen`. The Windows C runtime opens a file in text mode unless the mode says
`b`: every `\n` written becomes `\r\n` and `\r\n` read back becomes `\n`, so the byte
offsets `$ftell` and `$fseek` deal in no longer match the bytes the model wrote and reads.
Every other platform's `fopen` has no text mode.

## What changed

On a Windows target `osdi_fopen` appends `b` to a mode that has none. A file a model writes
is byte for byte what it wrote, and the offsets are the same as on Linux and macOS.

## Limits

- Checked by the Windows CI job only; this commit is the first Windows build with it.
