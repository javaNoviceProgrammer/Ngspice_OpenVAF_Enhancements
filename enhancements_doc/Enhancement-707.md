# Enhancement-707: the linker reads its arguments from a response file above 16 KiB, an `exec` failure names the program and the cause, and a failed link removes its object files — a file of 1 800 modules failed after 12 s with "linker not found: Argument list too long"

**Scope:** F8 of the
[robustness campaign of 2026-09-23](../docs/bug_hunts/2026-09-23_openvaf-r-robustness-campaign.md).
**Compiler only.** `linker/src/lib.rs` (`link`: `RESPONSE_FILE_THRESHOLD`,
`response_file_contents`, the two `exec` error arms; two unit tests for the quoting),
`openvaf/src/lib.rs` (the object files are removed before the link result is examined).
[`examples/multimod_examples/`](../examples/multimod_examples/) (4 checks, 28 in all).
The hunt page.

**Suites:** `multimod` 28 of 28 (27 of 28 on the E-704 binaries), `vacompile`,
`powguard` 37 of 37, `diagslips` 46 of 46, `langguard` 132 of 132 and `lrmlex`
unchanged; the linker crate's two unit tests; the compiler workspace tests green apart
from the three pre-existing sourcegen drift failures (221 passed), no build
warnings; full sweep 532 of 532, run alone.

## What was wrong

A file of `n` one-line resistor modules:

| modules | before | now |
|---|---|---|
| 200 / 500 / 1 000 / 1 500 | 1.4 / 3.4 / 6.8 / 10.3 s | unchanged |
| 1 700 | 11.9 s, 1.7 GB | unchanged |
| 1 800 | after 12 s: `error: linker not found: Argument list too long (os error 7)` | 12.8 s, 1.7 GB, an 8.0 MB library |
| 2 000 | the same | 14.4 s, 1.8 GB, 8.9 MB |

**Where.** Every module is compiled to four object files, and each path is added to the
linker's argument vector (`openvaf/src/lib.rs`, `linker.add_object(path)`). The paths
sit next to the output and run to about a hundred bytes, so 1 800 modules — 7 200 paths —
exceed macOS's 256 KB `ARG_MAX` and `exec` fails with `E2BIG`; on Linux the 2 MB limit
moves the wall to about 15 000 modules, on Windows the 32 767-character command line
brings it down to a few hundred. `link` mapped every `exec` error to "linker not
found", so the message sent the user looking for `clang`. And a link that fails for any
reason returned before the loop that removes the object files, leaving four `.oN` files
per module next to the output.

## What changed

1. **A response file above 16 KiB of arguments.** `link` sums the bytes of the
   arguments it has built; above `RESPONSE_FILE_THRESHOLD` (16 KiB — about 150–190
   object paths, so a file of forty-odd modules) it writes them to `<output>.rsp`, one
   per line, and runs the linker as `<linker> @<output>.rsp`. clang, gcc, GNU ld and
   link.exe all read `@file`. The quoting follows the reader: for the GNU-style readers
   every argument is double-quoted with `\` and `"` escaped by a backslash; for link.exe
   a backslash is the path separator and is written as it is, and only an argument
   holding white space or a quote is quoted. The file is removed after the link, and the
   threshold sits well below the tightest host limit (Windows's 32 767 characters).
2. **The `exec` failure says what it is.** `NotFound` is "linker not found: 'clang' is
   not installed or not on PATH (No such file or directory (os error 2))"; any other
   spawn error is "failed to run the linker 'clang': <the error>", with the program that
   was run in both.
3. **The object files go whether the link succeeded or not.** The driver removes them
   first and examines the link result second.

## Verification

`multimod_examples` (Enhancement-76's multi-module suite) gains [14] a generated file of
400 one-line modules — 1 600 object files, about 130 KB of paths, eight times the
threshold — that compiles, leaves no `.rsp` behind, and whose last module loads in
ngspice and conducts 0.5 mA through `r=2k`; and [15] a compile with no linker on `PATH`
that fails with "linker not found: '…' is not installed or not on PATH". The second
fails on the E-704 binaries (27 of 28); the first passes there too, since 400 modules
were always under the wall — the response file is exercised, the wall itself is pinned
by hand: 1 800 modules link in 12.8 s and 2 000 in 14.4 s (1.7 and 1.8 GB resident, 8.0 and 8.9 MB libraries), where 1 800 failed after 12 s before. Two unit tests in the linker crate pin the two quotings (a path with
a space, a backslash and a quote in each style).

## What this does not do

- The threshold is a constant, not an option, and there is no retry on `E2BIG` — the
  response file is taken deterministically by size, so `E2BIG` cannot arise from the
  object list.
- Memory: about a megabyte of resident memory per module is still spent before the
  link (1 800 modules, 1.7 GB); that is codegen, not the linker, and is untouched.
- One object per file instead of four per module would shorten the list further; the
  four-way split is what lets the modules' functions compile in parallel and is kept.
