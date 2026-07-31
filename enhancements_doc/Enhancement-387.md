# Enhancement-387 — an empty `()` crashed the compiler, and two more

Three defects in `openvaf-r`, found by a compiler bug hunt.

## [1] An empty parenthesised expression crashed the compiler

```verilog
`include "disciplines.vams"
module dut(p,n);
  inout p,n; electrical p,n;
  analog I(p,n) <+ ();
endmodule
```
```
OpenVAF encountered a problem and has crashed!          exit code 101
```

Five lines, no CLI flags, on the **shipped release binary**.

`paren_expr` loops on `while !p.at(EOF) && !p.at(T![')'])`, so for `()` the body
never ran: nothing was parsed, and — the real defect — **no diagnostic was
emitted**. The `PAREN_EXPR` completed with no child, `hir_def` lowered it to
`Expr::Missing`, and `hir/src/body.rs` has arms for nine expression variants but
none for `Missing`, so it fell through to

```rust
_ => panic!("invalid HIR: {:?}", self.body.exprs[expr]),
```

**The hole was exactly one token wide.** Every other malformed expression form —
`{}`, `{1,}`, `a[]`, `? :`, `sqrt()`, `1+` — was already rejected in the parser
and never reached lowering. Only `()`, and its nestings `(())` / `(( ))`, got
through. That is why it survived the assertion-replay campaign
([E-347](Enhancement-347.md)) — this is a `panic!`, not a `debug_assert`, and it
is reachable in a release build.

Reporting the missing expression turns it into an ordinary syntax error, and no
`Expr::Missing` reaches the HIR.

## [2] `-DNAME=VALUE` defined a macro called `NAME=VALUE`

Every `-D` flag became a macro whose name was the **whole flag string**:

```
openvaf-r m.va -DEXT=5.5     ->  error: macro '`EXT' has not been declared
```

`-DEXT=5.5` defined a macro literally named `EXT=5.5`, so no spelling of the flag
could reach it — not `` `EXT ``, and not `` `ifdef EXT `` either. The flag is now
split on its first `=`, which is what the `-D <MACRO[=VALUE]>` help text promises
and what every other toolchain does.

**Half of this is deliberately not fixed, and it is worth being explicit about.**
The *value* is still not substituted. A macro body is a `Vec<ParsedToken>` whose
text is resolved **by span against a real source file**, and a value that arrived
through `argv` has no backing text. Defining the name is the half that can be
done correctly inside the preprocessor; substituting the value requires the `-D`
definitions to be materialised as a source file and run through the normal
`` `define `` path, which is a larger change than this enhancement takes on.

## [3] A bad `TMPDIR` aborted through an uncaught C++ exception

```
libc++abi: terminating due to uncaught exception of type ...filesystem_error:
    in create_directory: No such file or directory ["$TMPDIR/ld-support-9907"]
clang: error: unable to execute command: Abort trap: 6
error: linking failed (see linker output for details)
```

The linker writes scratch files into `TMPDIR`. A nonexistent **or read-only**
`TMPDIR` produced that abort, and the final message blamed *linking* while never
naming the actual cause. CI runners and sandboxes routinely set `TMPDIR`, so a
stale or removed value is an ordinary environment mistake.

`link()` now checks the directory first and says what is wrong:

```
error: temporary directory '/tmp/nonexistent' does not exist (TMPDIR);
       the linker needs it for scratch files
error: temporary directory '/' is not writable (TMPDIR): Read-only file system; ...
```

Existence alone is not enough — a read-only `TMPDIR` fails identically — so the
check creates and removes a probe directory.

## How [1] was found

Not by fuzzing the language: by following [2]. A valueless `-DEXT` defines a
macro with an **empty body**, so `1e-3*(`EXT)` expanded to `1e-3*()` — and that
crashed. Two defects, one reachable only through the other. The parenthesis form
was then reduced to a five-line source file needing no flags at all.

## Also found, not fixed

The parser's expression-depth guard ([E-148](Enhancement-148.md),
`MAX_EXPR_DEPTH = 1000`) reports an over-deep expression through the **generic**
"unexpected token" path — `expr_too_deep()` says so in its own comment. An
operator chain of 999 terms therefore fails with

```
error: unexpected token identifier; expected '(', '{', system function...
```

rather than saying the expression is too deeply nested, which is what the
analogous include guard does (*"nests too deeply (a file that includes itself?)"*).
This is diagnostic wording on a deliberate guard with no correctness impact, and
carrying a new `SyntaxError` variant through both error enums, the tree builder's
irrefutable `let`, and the renderer is a change of its own — so it is recorded
here rather than rushed alongside a crash fix.

## Verification

`examples/vafice_examples` — 11 checks.

```
   fixed:     11/11
   pre-fix:    5/11
```

The six pre-fix failures are the defects: all eight empty-parenthesis forms
crashing, `()` not being reported at all, `-DEXT=5.5` unreachable, `` `ifdef ``
not seeing it, and both `TMPDIR` cases aborting.

The three accept checks pass on **both** binaries. The parser change touches
every parenthesised expression in every model, so they pin nested ordinary
parentheses, an end-to-end numeric result through a parenthesised model
(2 V / 1 kΩ = 2 mA exactly), and an ordinary compile with a valid `TMPDIR` — the
last because the new probe runs on every link.

The compact-model corpus is unaffected: **92/92 compile** and **92/92
correctness** (`VA_TEST`), the same as before. Regression 310/310 → 311/311.
