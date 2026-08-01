# Enhancement-396 — a NULL function pointer, a multiplier lost to a name, and eight arguments nobody checked

Ten defects from a one-hour hunt aimed at **openvaf-r**. One is a hard crash,
two are silent wrong answers, and the rest are input that was accepted and then
degraded quietly at run time.

## 1. `$limit` segfaulted the simulator on any unresolvable name or arity

Source that compiled clean killed ngspice with **zero bytes of output**:

| call | before |
| --- | --- |
| `$limit(V, "pnjlim", vt, vcrit)` | ok |
| `$limit(V, "fetlim", vto)` | ok |
| **`$limit(V, "fetlim", vto, vgst)`** — the LRM spelling | **SIGSEGV** |
| `$limit(V, "pnjlim", vt)` — wrong arity | **SIGSEGV** |
| unknown name, empty string, typo | **SIGSEGV** |

ngspice resolves the name against a fixed table at load time — `pnjlim` (2 extra
arguments), `fetlim` (1), `limitlog` (1), `limvds` (0). On a mismatch it printed
`warning(osdi): ... ignoring...` and left `func_ptr` **NULL**. The compiled model
then *called* that pointer.

The warning never reached anyone either. It went to `stdout`, and the crash it
was warning about destroyed the buffer before it was flushed — which is why the
symptom was a silent death rather than a warning followed by a crash.

`fetlim` takes one extra argument here and **two in the LRM** (`vto, vgst`), so
writing the standard spelling was one of the ways to crash.

There is no way to continue safely: the call site is already compiled to an
indirect call, so the choice is between a clean refusal and a jump to address
zero. An unresolvable entry is now a **hard load failure** naming the function,
both arities and the supported set, written to `stderr` where a later abort
cannot swallow it.

The compiler additionally raises the **`unknown_limit_function`** lint at build
time, when the model is still in front of its author rather than in front of
whoever ran the deck. That one is a lint and not an error because the set is
simulator-defined and another OSDI consumer may legitimately provide more.

## 2. A model parameter named `m` silently defeated the subcircuit multiplier

| model | `X1 a 0 sub m=3` gave | should give |
| --- | --- | --- |
| no parameter named `m` | −3.0 mA, `$mfactor` = 3 | ✓ |
| declares its own `m` | **−1.0 mA, `$mfactor` = 1** | −3.0 mA |

[Enhancement-394](Enhancement-394.md) applies a subcircuit multiplier by
appending ` m={m}` to each device line. When the model declares its own instance
parameter `m`, the append lands **there** — so the enclosing multiplier vanishes
and the device contributes 1× instead of 3×. That is precisely the defect E-394
exists to fix, reintroduced through a name collision, with nothing said. A PDK
model that happens to call a parameter `m` under-counts device area exactly as
it did before that release.

`temp` shadows the instance temperature the same way.

The shadowing itself is the only coherent behaviour — the model's own
declaration must win, and it does, cleanly, with no double application. What was
missing was any way to find out, so both now say so.

## 3. The collision warning misattributed its own cause

Declaring `dtemp` **once** produced *"instance parameter 'dtemp' is declared more
than once differing only in case"*. It is declared once, and the collision is
with a built-in of *identical* case — so the message sent the reader looking for
a second declaration that does not exist. A collision with a loader-provided
parameter and a genuine case collision now have separate messages, told apart by
whether the earlier entry lies in the prefix this loader wrote itself.

## 4. `$table_model` data files accepted non-finite values

`abc` was rejected. `nan`, `inf`, `-infinity` and an overflowing exponent such as
`1e400` were not — `f64::from_str` accepts the first three and returns an
infinity rather than an error for the fourth. One such token poisoned the
**whole** table: every query, including points that should interpolate between
perfectly good rows, returned NaN, with no diagnostic anywhere.

A missing-data marker is exactly how a measured data file spells one, which is
precisely the case where the diagnostic is wanted. Both the validator and the
two readers in `hir_lower` apply the same rule now, so they cannot drift apart.

## 5. `@(timer)` with a degenerate period fired on every evaluation

Over a 10 µs transient a 1 µs timer produces 10 events. A period of zero, a
negative period, and a denormal one all produced **120** — one per timestep.
A negative start time did the same. So a period computed as `1/freq` with
`freq = 0` silently turned a sampler into a per-iteration event.

## 6. `$bound_step` was unvalidated

Zero and denormal aborted the analysis with a *"Timestep too small"* that named
neither the model nor the call. **Negative silently forced the minimum timestep
everywhere — 10001 output rows against the control's 108.**

## 7. `noise_table` shape was unvalidated

An empty or single-entry array made the device contribute **no noise at all** — a
spec that looks present and is not. An odd length dropped the unpaired entry.
A **negative noise power** was accepted and produced the same spectrum as its
positive twin, so the sign was quietly discarded.

## 8. Out-of-range array indexing

Every compile-time-constant index — a literal, a negative literal, a write
target, a `localparam` — is rejected.

**Scope boundary, stated rather than hidden:** an index computed at *run time* is
still masked rather than diagnosed. It is memory-**safe**, which the suite proves
with a canary: reads fold to element 0, writes are discarded, and nothing around
the array is disturbed, for indices from −100 to 10⁶. Diagnosing it would mean a
bounds check on every array access in the inner evaluation loop of every compact
model — a real and permanent cost, to catch a mistake the constant-index checks
already catch in the form models actually write.

## 9. A bus port's two ranges could disagree

`inout [0:2] b;` beside `electrical [0:4] b;` was accepted. The direction range
won and the net's other two bits were discarded, so the module ended up with
fewer terminals than its own source said. (The opposite order was already
caught, but only incidentally, as *"no discipline for net 'b[3]'"*.) Each
declaration registers its own `BusDecl`, so the check compares every bus
carrying the port's name against the range the direction stated.

## 10. A family of unvalidated constant arguments

A `@(cross)` direction that is not −1/0/+1; a negative `transition` delay, rise
or fall time; a non-positive `slew` rise rate or non-negative fall rate; a zero
or negative `idtmod` modulus; a negative `absdelay` delay, and a delay exceeding
the declared maximum.

These are checked **only when the argument is written out as a constant**. That
is deliberately narrow: the point is to catch the spelled-out mistake without
pretending to know what a runtime expression will evaluate to. Every check has a
runtime-expression case in the accept half to pin that.

## Verification

`examples/limguard_examples` — **80/80 fixed, 39/80 against the shipped binary**.
Forty-one checks pin real defects.

Every check is paired. The accept half is doing real work here: this release adds
diagnostics across ten unrelated surfaces, so each one is matched against the
legitimate input it must not disturb — the four resolvable limiter spellings and
the no-limiter form, a well-formed table with comments and blank lines, a
runtime-computed timer period and step bound, matching bus ranges, an in-range
literal index, and a scalar-port model that must be entirely unaffected.

The crash check is worth stating precisely: it asserts not merely that the run
fails, but that it fails with a **positive** return code and a message naming the
supported set — because the defect's signature was `rc = -11` with an empty
output stream, which a naive "did it fail?" test would have called a pass.

E-394's subcircuit multiplier is re-pinned end to end (1× and 3×) alongside the
new shadowing warning, since (2) is a regression channel for that fix rather than
a defect in it.

**Corpus differential.** All 124 files of the `VA_TEST` industry corpus compiled
with the shipped binary and with this one: **107 compiled by both, 0 return-code
differences, 0 byte differences, and 0 models trip any of the new diagnostics.**
That last number is the one that matters for a release made almost entirely of
new checks — it is what says they are aimed at mistakes rather than at practice.

Beyond the suite: `cargo test --workspace` **209/0**, full regression **320/320**.
