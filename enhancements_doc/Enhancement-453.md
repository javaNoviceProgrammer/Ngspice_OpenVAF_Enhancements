# Enhancement-453 — a stale cache artifact, an impossible target, and two crashes

Five defects, all of the same shape: the compiler answered a request it could
not actually satisfy — with the wrong artifact, with a crash, or with a refusal
the LRM does not permit.

## The batch cache answered with the wrong build

Batch mode keys its cache on the source text, the defines, the lints and the
compiler version. The settings that decide what **machine code** comes out were
not in the key, so a request differing only in those settings was answered with
whatever artifact was already there.

```
$ openvaf-r m.va -b --cache-dir C -O 0     # 113424 bytes cached
$ openvaf-r m.va -b --cache-dir C -O 3     # exit 0 -- and the SAME entry
```

One cache entry, not two. The second run reported success and handed back the
`-O 0` build; a real `-O 3` build of that model is 36936 bytes. Debug once and
every later optimized build is silently the debug one.

`--target` was worse, because the answer was not merely unoptimized but for the
wrong operating system:

```
$ openvaf-r m.va -b --cache-dir C --target x86_64-unknown-linux
Finished building m.va                     # exit 0
$ file C/*.osdi
Mach-O 64-bit dynamically linked shared library arm64
```

A Linux build that is a macOS build, reported as success.

`--target-cpu` and `-C` are the same class of input — `--target-cpu native` and
`--target-cpu generic` produce different binaries here — so they are hashed too.

## Cross-compiling then panicked

`initialize_llvm` registers only the **native** LLVM target, so any foreign
architecture fails inside `create_target`. That failure was reached through
`back.new_module(..).unwrap()` on a rayon worker:

```
$ openvaf-r m.va -o x.osdi --target x86_64-unknown-linux
OpenVAF encountered a problem and has crashed!
A log file has been generated at "/var/folders/.../openvaf-crash-1786709027.log".
To help us fix the problem, please open an issue at https://github.com/...
```

Exit **101**, a crash banner and a request to file a bug, for asking a macOS
binary to build for Linux. The panic was at `openvaf/osdi/src/lib.rs:197`:
`called Result::unwrap() on an Err value: "No available targets are compatible
with triple \"x86_64-unknown-linux-gnu\""`.

The two halves are one story. Putting the target in the cache key turns the
wrong-artifact answer into a real compile — which then has to fail *honestly*
rather than abort, or the fix would have converted a silently wrong answer into
a crash. Both are checked together.

The target is now probed once, before any work is spawned, with the same triple,
CPU and features the codegen would use:

```
error: cannot generate code for target 'x86_64-unknown-linux-gnu': No available
       targets are compatible with triple "x86_64-unknown-linux-gnu"
help: this binary has a code generator for aarch64-unknown-linux,
      aarch64-pc-windows, aarch64-apple-darwin
```

The help line is built by probing each target the driver advertises, so it
reports what this binary can really emit rather than what it knows the name of.
Note that `--supported-targets` lists eight; only three can actually be
generated here. Targets that reach the linker and fail there (a cross-linker
problem, not a codegen one) are left alone — that failure was already honest.

## The LRM's null argument was rejected

LRM 4.5.11 (Laplace filters) and 4.5.12 (Z-transform filters) each state:

> The zeros argument may be represented as a null argument. The null argument is
> characterized by two adjacent commas (,,) in the argument list.

and 4.5.11.1 gives a worked example using it:

```verilog
V(out) <+ laplace_zp(white_noise(k), , '{1,0,1,0,-1,0,-1,0});
```

That line did not compile — `error: unexpected token ','`, followed by a bogus
arity complaint ("expected at least 3 arguments but found 1") produced by the
failed parse. It failed for all eight filters.

The capability was never missing: `'{}` expresses "no zeros" and is numerically
exact. Only the LRM's spelling of it was. An empty slot now parses as the same
empty-vector node `'{}` produces, so the two spellings are the *same filter* —
verified numerically, not just by exit code, because a spelling fix that quietly
produced a different filter would be worse than the defect it replaced.

The parser sees token **kinds only, never text**, so it cannot know which
function is being called; legality is therefore decided by type inference, where
the builtin is known. Outside a vector position the empty array is a type error,
which is what a null argument there should be (LRM 4.6: "It is illegal to specify
a null argument in the argument list of an analog operator, except as specified
elsewhere"). Only an **interior or leading** slot is a null argument — a
trailing comma is still the Enhancement-423 error.

## Printing a comparison crashed the compiler

An argument that no `%` conversion consumes is rendered from its own type. Only
real, integer and string had a case, and the fallback was `unreachable!()`:

```verilog
$strobe("x", 1 > 0);          // a Bool  -> exit 101, crash report
$strobe("x", '{1.0, 2.0});    // an array -> exit 101, crash report
```

A *named* array was already caught cleanly ("requires a bit-select"); these were
not. This is the most reachable of the five — `$strobe("flag", v > 0.5)` is an
ordinary thing to write while debugging a model.

`$strobe("%d", 1 > 0)` always worked, because that path casts the Bool to an
integer. So a Bool **is** printable; it simply never reached a cast on the
default path. It gets one now, and prints `1`/`0`. An array has no default
rendering and is reported instead of crashing.

## The fix

| file | change |
|---|---|
| `openvaf/openvaf/src/cache.rs` | hash `opt_lvl`, target triple, `target_cpu` and `codegen_opts` into the cache key |
| `openvaf/mir_llvm/src/lib.rs` | `LLVMBackend::target_available` — probe the triple and dispose the machine |
| `openvaf/osdi/src/lib.rs` | `initialize_llvm` made public so the probe can run before codegen |
| `openvaf/openvaf/src/lib.rs` | refuse an unavailable target, listing the ones that work |
| `openvaf/parser/src/grammar/call.rs` | an interior/leading empty argument slot becomes an empty `ARRAY_EXPR` |
| `openvaf/hir_ty/src/inference.rs` | check display arguments no conversion consumes; cast a Bool, reject an array |
| `openvaf/hir_lower/src/fmt.rs` | comment recording that the `unreachable!()` is now enforced upstream |

## Verification

**`examples/batchkey_examples` — 17/17**, and **9/17 on the previous compiler**.
**`examples/nullarg_examples` — 37/37** under both solvers, and **13/27 on the
previous compiler**. In both suites the failures there are exactly the
defect-specific checks, and every control passes on both.

* `-O 0` and `-O 3` are two different cache entries, of two different sizes, and
  re-running `-O 0` still **hits** the cache rather than adding a third
* a foreign `--target` is not answered from the host cache, does not panic, and
  invents no artifact; the message names the target and says what can be built
* the host target named explicitly still compiles, a plain build still compiles,
  and two identical batch builds still share one entry
* the LRM's own `laplace_zp` example compiles; the null argument is accepted for
  `laplace_nd/np/zd/zp` and `zi_zp/zi_zd`
* the null-argument filter matches `1/(1+s/1e4)` in magnitude and phase and is
  **identical** to the `'{}` spelling
* `max(1,,2)`, `max(1,2,)`, `ddt(,)`, `$strobe("a",,"b")` and a null argument in
  an expression position are all still refused, none of them crashing
* a printed comparison compiles and prints `1`/`0`; a real, integer and string
  still print as before; an array literal is refused without a crash

**Corpus differential.** The parser change touches every call expression and the
inference change every `$display`-family call, so the whole 124-model corpus was
compiled with the old and the new driver and compared: **107 compiled by both,
17 rejected by both, 0 rc differences, 0 byte differences**. Both binaries wrote
to the same output path, since an `.osdi` embeds its own path (Enhancement-389)
and differing paths would have made every comparison differ for no reason.

`cargo test` across the workspace passes with zero failures. Full regression
**367/367**, both solvers.
