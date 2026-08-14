# Enhancement-452 — an unusable `-o` destroyed the source, or crashed

Three ways a `-o` destination went wrong. None was checked by the driver; each
reached the backend and failed there.

## `-o` naming the input file

The compiled module was written straight over the source, and the run reported
success:

```
$ openvaf-r m.va -o m.va
Finished building m.va in 0.08s          # exit 0

m.va:  111 bytes of Verilog-A   ->   36888 bytes of Mach-O
```

The source is gone. There is no warning, no non-zero exit, and nothing in the
output to suggest anything unusual happened. It is reachable from a shell loop
whose output variable is accidentally the input one, or from a mis-completed
file name.

## An empty `-o`, and an unwritable directory — both panicked

```
$ openvaf-r m.va -o ""
OpenVAF encountered a problem and has crashed!
A log file has been generated at "/var/folders/.../openvaf-crash-1786705998.log".
To help us fix the problem, please open an issue at https://github.com/...
```

Exit **101**, a crash banner, a crash-log file and a request to file a bug —
for a typo. The same for a directory that cannot be written.

Both are an ordinary I/O failure meeting an assertion:

| site | code | reached by |
|---|---|---|
| `osdi/src/lib.rs:107` | `dst.file_stem().expect("destination is a file")` | an empty `-o` |
| `osdi/src/lib.rs:579` | `assert_eq!(llmod.emit_object(..), Ok(()))` | an unwritable directory |

`emit_object` already returns a `Result`; the caller asserts on it rather than
propagating it.

## The fix

The destination is validated in the driver, in `matches_to_opts`, before any
parsing. That is the last point which still knows **both** the input and the
requested output, and it runs before any work is done:

```
-o naming the input   ->  error: the output path 'm.va' is the input file
                          help: the compiled module would be written over the source
                                and the source would be lost; choose a different -o
-o ""                 ->  error: the output path '' does not name a file
                          help: give -o a file name, for example -o model.osdi
-o /unwritable.osdi   ->  error: cannot write to the output directory '/':
                                 Read-only file system (os error 30)
-o nodir/x.osdi       ->  error: the output directory 'nodir' does not exist
```

Exit 65, one line each, and the source file untouched.

Two decisions worth stating:

**Overwriting a previous *output* stays legal.** Rebuilding onto an existing
`.osdi` is the normal workflow, so only the input is protected. A check pins
that.

**Writability is tested by creating and removing a probe file**, not by
inspecting permission bits. The backend writes one object file per module
*beside* the target, so the real question is whether that directory can be
written — which only an actual write answers, and which is exactly what
`emit_object` was failing to do at line 579.

## Verification

**`examples/optpath_examples` — 16/16**, and **9/16 on the previous compiler**:
the seven checks that fail there are exactly the defect-specific ones, while
every control passes on both.

* `-o` naming the input is refused, **the source file is still there**, and the
  message says why
* an empty `-o` is refused, does **not** exit 101, and names the problem
* an unwritable directory is refused, does not exit 101, and names the directory
* a non-existent output directory is refused without panicking
* a plain `-o`, no `-o` at all, and `-o` into an existing subdirectory all still
  compile; overwriting a previous output is still allowed; and the `.osdi`
  produced is still a real module

**Full regression 365/365**, both solvers — the whole model corpus recompiled
with the new driver.
