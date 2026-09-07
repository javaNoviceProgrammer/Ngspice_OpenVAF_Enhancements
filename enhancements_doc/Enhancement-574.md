# Enhancement-574: openvaf-r colours a diagnostic only when it writes to a terminal — five suites that a colour terminal failed and a harness with `TERM` unset passed

**Scope:** `openvaf/basedb/src/diagnostics/sink.rs` (the colour choice, shared),
`openvaf/basedb/src/diagnostics.rs`, `openvaf/openvaf/src/lib.rs` (the `Finished`
line), `openvaf/openvaf-driver/src/{main,cli_process,crash_report}.rs` and its
`Cargo.toml`; on the harness side `examples/_setup.py`, `examples/run_regression.py`,
`examples/constname_examples/verify_constname.py` (resolves its binaries through
`_setup.py`), `examples/syntaxhl_examples/verify_syntaxhl.py`; and, from the second sweep,
`src/frontend/com_dl.c` (the cache's compiler check finds a bare name on `PATH`) with
`examples/vacompile_examples/verify_vacompile.py` and the `$OPENVAF` hand-over in
`examples/_setup.py`. **Compiler, harness and one ngspice
file; no codegen change.**

**Suites:** new [`vafcolor_examples`](../examples/vafcolor_examples/) (10 checks);
[`reusecache_examples`](../examples/reusecache_examples/) grows to 25 checks per
solver; `lrmdisc`, `lrmfuncs`, `natureref`, `vafdeterminism`, `vafice`, `syntaxhl`,
`constname`, `vacompile` pass under `TERM=xterm-256color`; full sweep 474 of 474 on
both solvers, run under `TERM=xterm-256color` with no `openvaf-r` on `PATH`.

## What happened

A regression sweep run from an ordinary shell reported five failures — `lrmdisc` and
`lrmfuncs` under both solvers, `natureref`, `vafdeterminism` and `vafice` with
`rc=1` — that the same tree had just passed, 473 of 473, from the harness this work is
done in. Nothing about the tree differed. The one failing `natureref` check, run by
hand, showed the cause in its own detail column:

```
FAIL  ...and that error comes FIRST, naming the discipline and the missing nature
PASS  the diagnostic prints the cycle  [['\x1b[0m\x1b[1m\x1b[38;5;12m=\x1b[0m info: cycle: nA -> nA']]
```

The compiler's diagnostics carried ANSI escape codes although they were being read
through a pipe. The line that reads `error: …` on the screen began with
`\x1b[0m\x1b[1m\x1b[38;5;9m` in the captured text, so a check written as
`startswith("error:")` was false, an ordering check found no `error:` line at all, and
`vafdeterminism`, which hashes the compiler's output line by line, saw a different text
than the harness had.

The harness runs with `TERM` unset. The shell had `TERM=xterm-256color`. Setting that
one variable reproduced all five failures on the harness; `TERM=dumb` cleared them.

## Why

The compiler picked its colours with termcolor's `ColorChoice::Auto`, at seven sites:
the diagnostic sink, the `Finished building` line (twice), the top-level error, the
crash report, `--lints` and `--supported-targets`. termcolor's `Auto` is documented as
"try very hard to emit colors": it consults `TERM` and `NO_COLOR` and never asks
whether the stream is a terminal — that check is the caller's. None of the seven made
it. So from any colour terminal, every diagnostic written into a pipe was coloured: a
build log, a CI capture, a test harness, and ngspice's own `pre_osdi -va`, which reads
the compiler's diagnostics to show them.

## What changed

**Compiler.** `basedb::diagnostics` gains `stderr_color_choice()` and
`stdout_color_choice()`: `ColorChoice::Auto` when the stream is a terminal
(`std::io::IsTerminal`), `Never` otherwise. All seven sites use them. The terminal case
keeps termcolor's own policy, so `NO_COLOR` and a dumb `TERM` still turn colour off on a
real terminal. The driver crate now depends on `basedb` directly for the helper; it had
reached it only through `openvaf` before.

**Harness.** A prebuilt or older compiler may not carry the fix, and a sweep may be run
on Linux from any shell, so the harness settles the terminal for every child it spawns:
`_setup.py`, which every verify script imports, sets `TERM=dumb` and `NO_COLOR=1` at
import, and `run_regression.py` hands the same to every suite. These are the two
switches termcolor honours on every version. `syntaxhl_examples`, which is *about*
colour on a real terminal, asks for a colour terminal in its pty children and lets a
check's own `NO_COLOR=1` override it, as it did before. `constname` was the one script
that did not import `_setup.py`: it found ngspice by its own path and the compiler by
the bare name `openvaf-r`, and on a machine with no `openvaf-r` on `PATH` it was the
one suite to fail the Linux-condition sweep; it now resolves both binaries through
`_setup.py` like every other suite.

## The second sweep: one more, and it was not the colour

The user's re-run under the fix came back 473 of 474, with `vacompile` failing under
both solvers — and passing here, under every terminal type. The difference was how
the compiler is *named*. `osdi_find_openvaf()` tries the `openvaf` variable, then
`$OPENVAF`, then `$SPICE_LIB_DIR/openvaf-r`, and otherwise returns the bare name
`openvaf-r` for the shell to find on `PATH`. [E-573](Enhancement-573.md) had just made
the cache reject an object older than the compiler, and could only do so when the
compiler's path could be stat'ed — a bare name cannot be, so the rule was silently
inert for exactly the setup this harness runs in, and live in a shell that names the
compiler by path. Three `vacompile` checks backdate the object to 2023 to make it
"look up to date"; under the new rule an object from 2023 is older than any compiler
and is rebuilt, so `[11]`, `[16]` and `[18]` failed wherever the rule was live.

Three changes. `com_dl.c` locates a bare compiler name on `PATH` the way `system()`
will, so the timestamp rule holds however the compiler was named, and the rebuild
message prints the path it found. `vacompile` stamps its "up to date" objects *now* —
newer than the source and newer than the compiler, which is what up to date has meant
since E-573 — instead of at a fixed instant in 2023. `reusecache_examples` gains the
check that a compiler found by bare name on `PATH` is located and rebuilt against.

And one more, found by asking what the harness would do on a machine with no
`openvaf-r` on `PATH` at all: `vacompile` failed from its first compile. Its decks
"pin" the compiler with `set openvaf=…` in the control block, and that `set` runs
after the `pre_` commands it would have to precede, so the pin had never reached a
compile — the suite had been using `PATH` all along. `_setup.py` now exports
`$OPENVAF`, the lookup's second step, as the compiler it resolved, so every
`pre_osdi -va` and `pre_snp` that ngspice runs under the harness uses the same binary
the scripts do, on any machine; the three `pre_snp` suites already did this for
themselves, and `reusecache` removes it per call where it tests the lookup.

## Verification

[`vafcolor_examples`](../examples/vafcolor_examples/) — 10 checks, compiler only:

| section | checks |
|---|---|
| [1] into a pipe, `TERM=xterm-256color` | a diagnostic, the `Finished` line, `--lints` and `--supported-targets` are plain text; the first diagnostic line begins with `error:` at column 0; `TERM=dumb` is plain as before |
| [2] on a pseudo-terminal | the diagnostic and `Finished` ARE coloured; `NO_COLOR=1` and `TERM=dumb` still turn it off |

The harness layer was proved on its own against the previous compiler binary, which
still colours a pipe: `natureref` and `vafice` pass through the hardened harness with
`OPENVAF_BIN` pointing at it and `TERM=xterm-256color` in the shell. The full sweep was
run under `TERM=xterm-256color` with `PATH` stripped of every `openvaf-r`: 474 of 474
on both solvers.
