# Enhancement-222 — ngspice netlist-parser hardening (fuzzing)

Fuzzing ngspice's netlist parser — mutating real decks (byte flips, truncation,
line duplication, delimiter/bracket/keyword/directive/number injection, and the
new [E-221](Enhancement-221.md) bus-range tokens) and running each under
`ngspice -b` — found **seven** ways to make the parser **crash** (SIGSEGV /
SIGABRT — real memory-safety bugs, since ngspice is C) or **hang** on malformed
input. Every one is now a clean, bounded error.

Across a 12,000-iteration campaign the crash-plus-hang rate dropped from **26 to
1** (a 96 % reduction; **all hangs eliminated**). The one residual is an XSPICE
code-model bug in a different subsystem (see *Residual*).

## The seven root causes

| # | Site | Trigger → symptom | Fix |
|---|---|---|---|
| 1 | `frontend/inpcom.c` `get_number_terminals` + `misc/string.c` `gettok_instance` | `gettok_instance` returns an empty token **without advancing** on `(`/`)`, and the OSDI (`n`) terminal-count case was the only multi-token case with **no iteration cap** — a line starting with `n` containing `(` (e.g. `nan.func f(x)=…`) spun forever, `tmalloc`-ing each pass | `gettok_instance` always advances (consumes the bracket as a 1-char token); the `n` loop gained the same cap as its siblings |
| 2 | `frontend/inpcom.c` `inp_expand_macro_in_str` | a truncated `.model m` (no model type) runs `nexttok` off the end, leaving the scan pointer **NULL**, then `strchr(NULL)` | NULL guards on the `.model` skip and the scan loop |
| 3 | `frontend/subckt.c` `doit` | `MAXNEST` bounds subcircuit **depth**, but a subckt that instantiates **itself** with branching factor ≥ 2 explodes to 2^MAXNEST instances (an effective hang) before the depth cap trips | a total-instantiation cap catches recursive subcircuits |
| 4 | `frontend/subckt.c` `doit` | a bare `X` invocation (nothing after the refdes) makes the *find-last-token* walk run off the **front** of the line buffer → out-of-bounds read → `strcmp(NULL)` | skip an invocation with no node/name text |
| 5 | `frontend/inpcom.c` `inp_modify_exp` | two copies into a fixed `buf[512]` with **no bound**: an unterminated `v(` and a long identifier token (a run of `[`, which is accepted) overran the stack buffer (**stack smashing**) | both loops bounded by the buffer size |
| 6 | `frontend/subckt.c` `doit` | a malformed `.subckt` can register a **NULL name**; the invoked-name match `eq(su_name, …)` then `strcmp(NULL)` | guard `su_name` before the compare |
| 7 | `frontend/subckt.c` `translate` | `gettok_noparens` returns **NULL** at the end of a malformed controlled-source line, then `strcmp(NULL, "POLY")` | guard `next_name` |

Every fix is on a path that previously crashed or hung the parser on *malformed*
input; no valid deck changes behaviour.

## Method

The fuzzer classifies each run `OK` / clean-error / **CRASH** (killed by a signal
or aborted) / **HANG** (timeout), mutating a set of self-contained seed decks
that exercise the parser surface (devices, `.subckt`, `.param`, `.model`,
`.control`, expressions, continuations, buses). Each crash was triaged to its
faulting instruction with `lldb` — conditional breakpoints (`strchr`/`strcmp`
with a NULL argument), `sample` for the hangs, and Guard Malloc
(`libgmalloc`) to pin the stack-buffer overrun — then the bug read at the source.
Fixes were applied one at a time and verified against the recorded crash corpus,
and a fresh 12,000-iteration run confirmed convergence.

## Verification (`examples/parserfuzz_examples`)

`verify_parserfuzz.py` (10 checks) pins the fixes with a minimal deck per root
cause — `nan.func f(x)=…`, `.model m` inside `.control`, a self-recursive subckt,
a bare `X` line, an unterminated `v(`, a 4000-`[` identifier, and 4000 `{` in a
subckt E-source — asserting each now yields a **clean, bounded** outcome (no
signal/abort, no hang). Three valid decks (a subckt hierarchy with an E-source
and a parameter, a `v(x)*v(x)` B-source expression, and a POLY controlled source
in a subckt) confirm normal parsing/simulation is unchanged (V computed to the
analytic value). The recorded crash corpus (27 fuzz-found inputs) is all clean.
Full regression: 181/181.

## Residual

One fuzz input in 12,000 still crashes, in **XSPICE** (`xspice/mif/mifgetmod.c`
`MIFgetMod`), not the netlist parser: an `a`-device whose model name happens to
match a **non-code-model** (e.g. a diode `.model`) is processed as a code model,
so `device->modelParms[…]` is read as the wrong type. That is a code-model
type-confusion in the XSPICE subsystem and warrants its own fix; it is out of
scope for this netlist-parser pass. **Fixed in [E-223](Enhancement-223.md)**
(`MIFgetMod` now rejects a non-code-model with a clean error).

## Scope

ngspice only, three files (`frontend/inpcom.c`, `frontend/subckt.c`,
`misc/string.c`). No device, solver, or OSDI change.
