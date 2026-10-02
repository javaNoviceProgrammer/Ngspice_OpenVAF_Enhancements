# Enhancement-778: openvaf-r on Windows — two compiles into one directory raced for one fixed import-library name, link.exe left a `.lib` and an `.exp` beside every model, an unknown `--target_cpu` crashed the compiler instead of being refused, and the one-argument `$fopen` still opened in text mode

**Scope:** OpenVAF: `openvaf/linker/src/lib.rs` (`link`: the import-library names and
link.exe's `/IMPLIB`), `openvaf/mir_llvm/src/lib.rs` (`capture_stderr` on Windows),
`openvaf/osdi/stdlib.c` (`osdi_fopen`'s multichannel path). From the Windows CI sweep after
E-775..777 (run 37047779037: 504 of 529), read through E-777's traces.

**Suites:** the full sweep on macOS, 536 of 536; winlink (the cross-compile to
`aarch64-pc-windows` through a stand-in link.exe: `/IMPLIB:m.openvaf_implib.lib` on its
command line, the helper library `m.openvaf_ucrt.lib`, and nothing but `m.osdi` left
afterwards). The Windows branches are compiled and run by the Windows CI job only.

## What was wrong

**1. One import library per directory.** A Windows target links the model against an
embedded import library for the C runtime, written beside the output as
`__openvaf__import.lib` and deleted after the link -- one fixed name per directory. Two
compiles into the same directory at once (a parallel build, a suite whose models are
compiled concurrently, the shared temporary directory) wrote and deleted the same file, and
on Windows the second `File::create` failed while the first still held it: "failed to create
importlib", exit 65. It surfaced as vafhang [A], valguard, and suites whose models simply
never appeared (agestate, altermulti, autoadapt, vacorner all passed when re-run alone). The
library is now named after the output: `<model>.openvaf_ucrt.lib`.

**2. link.exe's import library and export file.** link.exe writes `<model>.lib` and
`<model>.exp` beside every DLL it links; an OSDI model has no use for either, and every
compile left both in the user's directory -- in `pre_osdi -va`'s `osdi/` folder (vacompile
[7]) and in the batch cache (batchkey counted six entries for two builds). link.exe is now
given `/IMPLIB:<model>.openvaf_implib.lib`, and the library and its `.exp` are removed with
the other scratch files.

**3. An unknown `--target_cpu` crashed the build.** E-695 refuses a CPU LLVM does not know
by catching LLVM's own complaint on stderr while a target machine is probed. The capture was
written for Unix only; on Windows it returned nothing, the bogus CPU went on into code
generation, and the compiler died with 0xC0000409. The capture now redirects the C
runtime's descriptor 2 on Windows too (`_pipe`, `_dup`, `_dup2`, `_read`).

**4. `$fopen(name)` in text mode.** E-776 made the two-argument `$fopen` binary on Windows;
the one-argument form, which opens a multichannel descriptor, has its own `fopen` with "w"
or "a" and still wrote `\r\n`: fileio's `$ftell` stayed at 171 for 160 bytes. It opens "wb"
or "ab" on Windows.

## Limits

- The Windows branches are checked by the Windows CI job; this is their first build there.
