# Enhancement-107 — the `$fgetc` file-input function

Gap-hunt round 5 pushed the runtime-value batteries into 2-D `$table_model`
bilinear interpolation, `white_noise` output spectra, file write/read
round-trips, and file positioning (`$ftell`/`$fseek`/`$rewind`) — **all of which
matched their analytic expectations exactly**. The compiler is robust across
that surface. The one clear in-scope gap it confirmed is a missing member of the
file I/O family.

## The gap

Enhancement-11 gave openvaf-r a full file I/O family — `$fopen`, `$fclose`,
`$fgets`, `$fscanf`, `$fdisplay`/`$fwrite`, `$feof`, `$ferror`, `$rewind`,
`$fseek`, `$ftell`, `$fflush` — but **not `$fgetc`**, the standard IEEE-1364
single-character read:

```
error: '$fgetc' was not found in the current scope
```

`$fgetc(fd)` reads one character and returns its integer code, or `-1` (EOF) at
end of file or on a bad descriptor.

## The implementation

`$fgetc` is another `fd → int` file operation, so it slots straight into the
existing `FileOp` machinery — no new callback shape:

- **`syntax`/`hir_def`**: the interned name, the `BuiltIn::fgetc` enum entry
  (`= 115`), and its scope registration.
- **`hir_ty`**: the signature is `BASIC_IO` (`integer → integer`, impure — like
  `$ftell`/`$feof`), added to the builtin table.
- **`hir_lower`**: `BuiltIn::fgetc` lowers to `FileOp::Getc`, whose runtime
  symbol is `osdi_fgetc`; the OSDI backend already binds `FileOp` variants
  generically by name.
- **`osdi/stdlib.c`**: `osdi_fgetc` looks up the descriptor and returns
  `fgetc(f)` (`-1` for a NULL descriptor).

## Verification

`fgetc_examples` (6/6): a device reads a fixed text file character by character
— the first two characters come back as their ASCII codes, and a `while` loop
over `$fgetc` counts and sums the remaining characters, terminating on the `-1`
EOF sentinel. The wider gap-hunt batteries behind this enhancement — 2-D
bilinear `$table_model` (exact on a linear surface), `white_noise` output
spectrum (matching `√S·R` to the loading), `$fdisplay`/`$fscanf` round-trips
across `%d`/`%g`/`%h`/`%o`/`%b`, and `$ftell`/`$fseek`/`$rewind` positioning —
all matched their expected values. Full regression: all verify suites plus the
OpenVAF integration tests remain green.
