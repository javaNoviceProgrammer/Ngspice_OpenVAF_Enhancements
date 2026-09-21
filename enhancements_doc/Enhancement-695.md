# Enhancement-695: an unknown `--target_cpu` is refused once, in the compiler's words — it compiled with exit 0 behind 33 garbled copies of LLVM's warning

**Scope:** F5 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_openvaf-r-cli-integers-transition-and-json.md).
openvaf: `mir_llvm/src/lib.rs` (`LLVMBackend::probe`, the E-453 probe with
stderr captured; `capture_stderr`; `target_available` kept as its wrapper),
`openvaf/src/lib.rs` (the refusal), `openvaf-driver/tests/cli.rs` (the smoke
list names a processor of the host's architecture — `skylake` is x86 and was
only ever "accepted" on Apple Silicon because LLVM ignored it — and a Unix-only
negative test of the refusal). `examples/batchkey_examples/` (five checks
added, 22). **openvaf only.**

**Suites:** [`batchkey_examples`](../examples/batchkey_examples/) 22 of 22
(4 fail on the E-694 binaries); `vacompile`, `scanfmt`, `nullarg` both solvers,
unchanged; the compiler workspace tests green apart from the three
pre-existing sourcegen drift failures; full sweep 531 of 531.

## What was wrong

```
$ openvaf-r cli.va --target_cpu bogus_cpu
'bogus_cpu' is not a recognized processor for this target (ignoring processor)
''bogus_cpubogus_cpu' is not a recognized processor for this target' is not a recognized processor for this target (ignoring processor)
 (ignoring processor)
… (33 lines)
$ echo $?
0
```

Every other bad flag value — `-O 5`, `-A L999`, a missing `-I` directory, a
`--target` this binary has no code generator for
([E-453](Enhancement-453.md)) — is refused before any work, in the compiler's
own words, with the valid values. `--target_cpu` was passed straight to LLVM,
whose C API validates nothing: `LLVMCreateTargetMachine` accepts any string,
and `MCSubtargetInfo` writes "'bogus_cpu' is not a recognized processor for
this target (ignoring processor)" to its own unbuffered stderr stream, twice
per target machine. A target machine is created once per codegen unit per
worker thread, so the line came out 33 times, interleaved by the threads into
fragments, while the build went on with exit 0 and generated code for LLVM's
generic CPU — the opposite of what `--target_cpu skylake` asked for, with
nothing in the compiler's output to say so.

## What changed

**The E-453 probe answers the CPU question too.** There is no C API that lists
or checks processor names (rustc needs a C++ wrapper for the same question), so
the answer is taken from the message itself. `LLVMBackend::probe` creates the one
probe target machine that `target_available` already created before any work is
spawned, with fd 2 redirected into a pipe (`capture_stderr`: `pipe`, `dup2`,
restore, read — LLVM's `errs()` is an unbuffered stream on fd 2, which is why the
redirection sees it), and returns `Ok(Some(line))` when LLVM complained,
`Ok(None)` when it did not, `Err` when there is no code generator for the target
at all. The driver refuses an unknown CPU where it refuses an impossible target:

```
error: --target_cpu 'bogus_cpu' is not a processor LLVM knows for arm64-apple-macosx11.0.0 ('bogus_cpu' is not a recognized processor for this target)
help: 'native' (this machine: apple-m1) and 'generic' are always accepted; LLVM lists the target's processors with `llc -mtriple=arm64-apple-macosx11.0.0 -mcpu=help`
error: failed to compile cli.va
```

Exit 65, no output file, and not one line from LLVM: the only target machine
created before the refusal is the captured one. `native` and `generic` are
resolved before the probe (to the host's name and the target's default), so
they can never be refused; a valid name (`apple-m1` here) builds as before.

The capture is Unix only (`pipe`/`dup2` through `libc`); where it is not
available `probe` reports `Ok(None)` and the question is left to LLVM, exactly
as before.

## Verification

| check | result |
|---|---|
| `--target_cpu bogus_cpu` | exit 65, one `error:` naming the flag, the value and the target, one `help:` with `'native'`, `'generic'` and the `llc -mcpu=help` spelling, no output file (was exit 0, 33 LLVM lines, an output for a generic CPU) |
| `--target_cpu skylake` on this aarch64 binary | refused the same way (skylake is an x86 processor) |
| `--target_cpu apple-m1`, `native`, `generic` | build, one "Finished" line, nothing from LLVM |
| `--target x86_64-unknown-linux` | E-453's refusal unchanged ("cannot generate code for target … help: this binary has a code generator for …") |
| the E-694 binaries on the suite | 4 of the 5 new checks fail (`generic` built there too) |
| the driver's CLI tests | 27 of 27 (`--target_cpu native`, `cortex-a72` on this host, the negative `bogus_cpu` case) |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- It does not list the valid processors itself; the help line names LLVM's
  own listing (`llc -mtriple=<triple> -mcpu=help`), which is the authority for
  the LLVM this compiler was built against.
- On a non-Unix build the capture is not attempted and LLVM's lines come out
  as before; the refusal needs the capture.
- A CPU LLVM knows but that this machine cannot run (`--target_cpu apple-m4`
  on an M1) is accepted, as it should be: that is what `--target_cpu` is for.
