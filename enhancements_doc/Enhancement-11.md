# Enhancement-11 — Verilog-A file I/O and string-formatting system functions (version11)

This document describes the source-code changes made to **OpenVAF-r** in the
`version11/` directory, implementing the Verilog-AMS **file I/O, file-descriptor,
string-formatting and file-reading system functions** on top of Enhancement-10
(random / statistical functions, same folder):

- Output: `$fopen`, `$fclose`, `$fdisplay`, `$fwrite`, `$fstrobe`, `$fmonitor`,
  `$fdebug`, `$fflush`, `$ftell`, `$fseek`, `$rewind`, `$feof`
- String / reading: `$swrite`, `$sformat`, `$sscanf`, `$fgets`, `$fscanf`,
  `$ferror`

All work is in `version11/` only; verification uses `version11/ngspice-46`'s own
binary and `version11/OpenVAF-master`'s own `openvaf-r`.

The only file/string system functions still unsupported are connectivity
aliasing (`$simprobe`, `$analog_node_alias`, `$analog_port_alias`) and the
plusarg functions (`$test_plusargs`, `$value_plusargs`).

> This document was originally written for the output-only set (§1–§5 below);
> §6 covers the string-formatting and reading functions added afterward.

## 0. Starting point

Like the random functions in Enhancement-10, the front-end already type-checked
all of these (full signatures in `hir_ty/src/builtin.rs`), but they were gated
in `hir_def/src/builtin.rs`'s `is_unsupported()` and rejected before codegen.
The console `$display` family, by contrast, was fully working -- and since
`$fdisplay`/`$fwrite`/... are exactly `$display`/`$write`/... aimed at a file,
the implementation is mostly *reuse* of the existing formatting machinery plus a
small runtime file-descriptor table.

## 1. Design

### 1.1 Descriptor table (`osdi/stdlib.c`)

`$fopen` must return an *integer* descriptor, but a host `FILE*` is 64-bit, so
the runtime keeps a small module-global table of open `FILE*`s and hands out
1-based indices into it (index 0 reserved, so a returned 0 means "failed", per
the LRM). Every `$f*` descriptor function looks the `FILE*` back up by index.
`FILE*` is treated opaquely as `void*`; `fopen`/`fputs`/`fclose`/`fflush`/
`fseek`/`ftell`/`rewind`/`feof` are declared `extern` and resolve against the
host libc at OSDI load -- exactly like the pre-existing `log`, so **ngspice
needs no changes**.

### 1.2 Output path reuses `$display`

`$fdisplay`/`$fwrite`/`$fstrobe`/`$fmonitor`/`$fdebug` share the entire
`snprintf`-based formatting path with `$display` (`fmt::ins_display` +
`osdi::print_callback`, handling `%g`/`%d`/`%h`/`%s`/`%b`/engineering `%r`,
etc.). The only differences: the file variant takes the descriptor as an extra
leading call argument, and the backend routes the formatted string to
`osdi_fputs(fd, s)` instead of the console `osdi_log`. `$fwrite` omits the
trailing newline; `$fstrobe`/`$fmonitor` are treated as `$fdisplay` (one write
per evaluation).

### 1.3 Execution context (important semantic note)

File-I/O writes that depend only on **parameters/constants** are placed by
`sim_back` in the model's initialization code and run **once per instance** --
ideal for exporting model parameters and characterization tables. Writes that
depend on **node voltages / the operating point** are a different matter:
`sim_back` splits node-dependent code into the per-iteration `eval` path, which
(a) would run on every Newton iteration and (b) separates such writes from the
`$fopen`/`$fclose` pair (which are parameter-level and stay in init), so the
descriptor is already closed by the time they run. Enhancement-11 therefore
targets the sound use case -- **parameter/setup-derived export** -- and the
example writes only parameter-derived data. (The descriptor table itself is not
guarded against concurrent access, so I/O should stay in these setup contexts.)

## 2. Implementation

| Layer | Change |
|---|---|
| Ungate | `hir_def/src/builtin.rs`: removed the implemented functions from `is_unsupported()`; the reading/string ones stay gated (§0). |
| Callbacks | `hir_lower/src/callbacks.rs`: added `to_file: bool` to `CallBackKind::Print`; new `CallBackKind::Fopen` and `CallBackKind::FileOp(FileOp)` (Close/Flush/FlushAll/Eof/Tell/Rewind/Seek), all side-effecting. |
| Lowering | `hir_lower/src/fmt.rs`: `ins_display` takes an optional descriptor, passed as the second call arg and flagged `to_file`. `hir_lower/src/expr.rs`: arms for every file builtin (`$fopen` synthesises a default `"w"` mode; `lower_file_op` for the descriptor ops). |
| Backend | `osdi/src/compilation_unit.rs`: `general_callbacks` resolves `Fopen`/`FileOp` to the `osdi_*` runtime functions; `print_callback` gained a `to_file` path that routes to `osdi_fputs`. |
| Runtime | `osdi/stdlib.c`: the descriptor table + `osdi_fopen`/`osdi_fputs`/`osdi_fclose`/`osdi_fflush`/`osdi_fflush_all`/`osdi_feof`/`osdi_ftell`/`osdi_fseek`/`osdi_frewind`, plus the `extern` libc declarations. |

## 3. Two bugs found and fixed during bring-up

1. **`fun` shadowing in `print_callback`.** The formatted-text sink extracted the
   file descriptor with `LLVMGetParam(fun, 2)` at the *end* of the hand-built
   callback -- but `fun` had already been rebound to the `snprintf` intrinsic
   earlier in the function, so it was reading snprintf's parameter, not the
   callback's descriptor. Every write went to garbage/`fd 0` and silently
   produced an empty file. Fixed by capturing the descriptor param up front
   (`file_fd`), while `fun` still refers to the callback.

2. **IPO mis-specialisation of the descriptor table.** The `osdi_f*` functions
   and the descriptor table are all `internal` after linking, so LLVM's
   aggressive interprocedural passes "proved" the table contents at compile time
   -- folding `$fopen`'s returned index to a constant and rewriting `osdi_fputs`
   down to a fixed `table[0]` (always NULL), so no write reached the file.
   Fixed by marking the table `volatile` (forcing real runtime loads/stores) and
   the entry points `noinline`.

## 4. Verification (`examples/fileio_examples/`)

`fileio_demo.va` is a resistor that also exports a characterization report --
its parameters and a computed `I = V/R` table -- to `fileio_out.txt` at
initialization. `verify_fileio.py` runs a `.op` and checks every line against
the closed-form values, exercising `%g`/`%d`/`%h`/`%s`, the newline-less
`$fwrite` (fragment join), and `$ftell` (byte offset). `fileio_seek.va`
separately checks `$rewind` and `$fseek` by overwriting a file in place
(`0123456789` -> `XY234**789`).

```
$ python3 verify_fileio.py
...
ALL PASS (9/9)
```

Regression: console `$display`/`$strobe` still format and print correctly
(shared `print_callback`); Enhancement-10's `verify_rng.py` still passes 24/24;
`sim_back` unit tests 24/24; `hir_*` data-tests unchanged.

## 6. String-formatting and file-reading functions

Added afterward: `$swrite`, `$sformat`, `$sscanf`, `$fgets`, `$fscanf`,
`$ferror`. These all involve writing back into a *string/variable argument*, so
the enabler is a small helper -- `hir::into_variable(expr)` (via a new
`Ty::unwrap_var`) -- that recovers the destination `Variable` from a `Var(..)`
argument, after which a normal `def_place(PlaceKind::Var(..), value)` stores the
result.

### 6.1 String formatting (`$swrite` / `$sformat`)

These are `$write`/`$display` that format into a string variable instead of a
sink. The `Print` callback's `to_file: bool` was generalised to a `PrintDst`
enum (`Console` / `File` / `String`); for `String`, `print_callback` returns the
freshly `snprintf`-ed `char*` (rather than calling `osdi_log`/`osdi_fputs`), and
the lowering stores it into the destination string variable. `$swrite` and
`$sformat` lower identically (both format `args[1..]` -- `ins_display` already
treats a leading format-string literal as the format and otherwise auto-formats,
which is exactly the `$sformat` vs `$swrite` distinction).

### 6.2 Reading (`$fgets`, `$fscanf`, `$sscanf`, `$ferror`)

Small `osdi_*` runtime helpers back these:
- `$fgets(str, fd)` -> `osdi_fgets(fd)` reads one line (returned as a `char*`,
  stored into `str`); the return count is `osdi_strlen` of it.
- `$ferror(fd, str)` -> `osdi_ferror_msg`/`osdi_ferror_code`.
- `$sscanf`/`$fscanf` share `lower_scanf`: `osdi_scanf_begin(input)` resets a
  module-global cursor (`$fscanf` first reads a line via `osdi_fgets`), then one
  `osdi_scan_int`/`_real`/`_str` per target variable pulls the next
  whitespace-delimited token (parsed by the **variable's type**, not by
  interpreting the C format string -- adequate for the usual whitespace-separated
  input), each stored via `def_place`; `osdi_scanf_count` returns the match
  count. The cursor/counter are `volatile` for the same IPO reason as §3.2.

An upstream **signature bug** had to be fixed: `$sscanf` and `$fscanf` were both
mapped to `FDISPLAY_FUN` (leading `Val(Integer)`, return `Void`) -- wrong for
`$sscanf` (whose first argument is the input *string*) and for the return type
(both return the Integer match count). Split into `SSCANF_FUN`
(`Val(String)` + `Integer` return) and `FSCANF_FUN` (`Val(Integer)` + `Integer`
return).

### 6.3 Verification (`examples/stringio_examples/`)

`stringio_demo.va` formats strings (`$sformat`/`$swrite`), parses a literal
(`$sscanf`), round-trips a file read (`$fgets` and `$fscanf` over a file the
model itself wrote) and queries `$ferror`, writing a report checked by
`verify_stringio.py`: **6/6 PASS**. Same setup-context caveat as the output
functions (§1.3) applies.

## 5. Diff summary

| File | Kind of change |
|---|---|
| `openvaf/hir_def/src/builtin.rs` | Removed the implemented file functions from `is_unsupported()`; kept the reading/string ones gated, with a note (§0) |
| `openvaf/hir_lower/src/callbacks.rs` | `Print{ to_file }`; new `Fopen`, `FileOp(FileOp)` callbacks + `FileOp` enum and their signatures (§2) |
| `openvaf/hir_lower/src/lib.rs` | Re-export `FileOp` |
| `openvaf/hir_lower/src/fmt.rs` | `ins_display` gained an optional descriptor argument and emits `Print{to_file}` (§1.2) |
| `openvaf/hir_lower/src/expr.rs` | Lowering for `$fopen`/`$fclose`/`$fdisplay`/`$fwrite`/`$fstrobe`/`$fmonitor`/`$fdebug`/`$fflush`/`$ftell`/`$fseek`/`$rewind`/`$feof`; `lower_file_op` helper (§2) |
| `openvaf/osdi/src/compilation_unit.rs` | `print_callback` file-routing path (`to_file`, descriptor captured up front) + `general_callbacks` arms for `Fopen`/`FileOp` (§2, §3) |
| `openvaf/osdi/stdlib.c` | Runtime descriptor table + `osdi_f*` functions + `extern` libc decls; `volatile` table + `noinline` to defeat IPO mis-specialisation (§1.1, §3) |
| `examples/fileio_examples/` | New verified example suite (`fileio_demo.va`, `fileio_seek.va`, `verify_fileio.py`, `README.md`) (§4) |
| **§6 additions:** | **string-formatting / reading functions** |
| `openvaf/hir_ty/src/types.rs` | `Ty::unwrap_var()` accessor (§6) |
| `openvaf/hir/src/body.rs` | `into_variable(expr)` -- recover a `Variable` from a `Var(..)` argument (§6) |
| `openvaf/hir_ty/src/builtin.rs` | Fixed `$sscanf`/`$fscanf` signatures: new `SSCANF_FUN` (`Val(String)`→`Integer`) / `FSCANF_FUN` (`Val(Integer)`→`Integer`), replacing the wrong shared `FDISPLAY_FUN` (§6.2) |
| `openvaf/hir_lower/src/callbacks.rs` | Generalised `Print{ to_file }` → `Print{ dst: PrintDst }` (Console/File/String); new `ScanBegin`/`Scan(ScanKind)`/`ScanCount`/`Fgets`/`StrLen`/`FerrorMsg`/`FerrorCode` callbacks (§6) |
| `openvaf/hir_lower/src/lib.rs` | Re-export `PrintDst`, `ScanKind` |
| `openvaf/hir_lower/src/fmt.rs` | `ins_display` takes a `PrintDst`; returns the formatted string for `String` (§6.1) |
| `openvaf/hir_lower/src/expr.rs` | Lowering for `$swrite`/`$sformat`/`$fgets`/`$ferror`/`$sscanf`/`$fscanf`; `lower_scanf` helper (§6) |
| `openvaf/hir_def/src/builtin.rs` | Ungated the 6 string/reading functions (only `$simprobe`/`$*_alias`/plusargs remain) |
| `openvaf/osdi/src/compilation_unit.rs` | `print_callback` `PrintDst::String` return path; `general_callbacks` arms for the scan/read helpers (§6) |
| `openvaf/osdi/stdlib.c` | `osdi_fgets`/`osdi_strlen`/`osdi_ferror_*` + the `volatile`-cursor scanner (`osdi_scanf_begin`/`osdi_scan_*`/`osdi_scanf_count`) + `extern` libc decls (§6.2) |
| `examples/stringio_examples/` | New verified example suite (`stringio_demo.va`, `verify_stringio.py`, `README.md`) (§6.3) |
