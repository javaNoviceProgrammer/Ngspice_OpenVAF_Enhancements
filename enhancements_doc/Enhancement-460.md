# Enhancement-460 — a crash, a silent table, and two dropped statements

Five defects from a one-hour hunt at openvaf-r: one compiler crash, one silent
wrong answer, two constructs the compiler accepted and then silently discarded,
and one command line accepted and ignored. Two further findings from the same
hunt were implemented and then withdrawn, and two more were deliberately left
alone — all four with the reason recorded.

## 1. `a.potential.access` crashed the compiler

```verilog
analog begin y = a.potential.access; I(a,b) <+ 1e-3; end
```

```
OpenVAF encountered a problem and has crashed!
Panic occurred in file 'openvaf/hir/src/body.rs' at line 389
invalid HIR: path Path { path: a.potential.access } was not resolved Val(Err)
```

LRM Syntax 5-4 names this case exactly: *"This syntax shall not be used for the
`access`, `ddt_nature`, or `idt_nature` attributes of a nature, nor any other
attribute whose value is not a constant expression."* Those attributes hold an
**identifier** — an access-function name, a nature name — so `nature_attr_ty`
found no value type and returned `None`. That pushed no diagnostic, left the
expression typed `Err`, and the lowering panicked on it.

Four spellings crashed: `a.potential.access`, `a.potential.idt_nature`,
`a.flow.access`, and the branch form `br.potential.access`. **Which ones
depended on whether the nature happened to define the attribute** —
`electrical`'s Voltage defines `idt_nature` (Flux), so that crashed, while
`ddt_nature` is undefined there and collected a clean "not found". The attribute
that resolves is the one that kills the compiler.

This is Enhancement-455's shape again: a type that fails to resolve without
anyone saying so, reaching a lowering that assumes resolution succeeded. It now
reports which attribute cannot be read and why, and `.abstol`, `.units` and
user-defined attributes are untouched.

## 2. A multi-dimensional table file was interpolated to garbage

`interp_1d_values` states its precondition one function below the reader —
*"`grid` is ascending"*. Every 1-D form establishes it: the inline
`'{x0,y0,…}` pairs and the two-column data file both `sort_by` and `dedup_by`
their breakpoints. The multi-dimensional reader was the one path that did not.

With `f(x,y) = x² + y` sampled on `x = [0,1,2]`, writing that axis as `2 1 0`
returned **0.5, 4.5, 4.5** across x = 0, 0.5, 1 — with no diagnostic. That is
not the function the file describes under *any* reading:

| reading | x=0 | x=0.5 | x=1 |
|---|---|---|---|
| the file at its word (row *k* belongs to axis[*k*]) | 4.5 | 3.0 | 1.5 |
| the ascending function | 0.5 | 1.0 | 1.5 |
| **what it returned** | 0.5 | 4.5 | 4.5 |

The interpolation simply clamped. Out-of-order and repeated coordinates were
equally wrong, on any axis and in 3-D as well.

Each axis is now sorted and de-duplicated with the value tensor permuted to
match, so the grid means exactly what the file says whatever order it is written
in — and the repeated-coordinate rule matches 1-D's `dedup_by`, keeping the
first. The NaN/Inf, size and value-count checks were already in place; only
**order** went unchecked.

## 3 & 4. Event control statements where the LRM forbids them

LRM 5.2.1 lists three things an `analog initial` block *"shall not contain"*:
statements with access functions or analog operators, contribution statements,
and **event control statements**. LRM 4.7.1 forbids the same three in an analog
function.

The first two were enforced in both places. The third was accepted in both, with
no diagnostic even under `-E all`, and the statement it guarded never ran:

```verilog
analog initial begin @(timer(1e-6)) q = 5.0; end    // q stays 0.0
analog function real f; … @(timer(1e-6)) f = 5.0;   // f returns x, not 5.0
```

`@(cross)` and `@(final_step)` behaved the same; `@(initial_step)` happened to
run, so the construct was not even consistently dead. This is Enhancement-456's
defect one level down — an initialisation that looks careful and quietly does
nothing.

The check is on the **statement**, not on what it guards, because the guarded
body is exactly what used to disappear without a word. Events in the analog
block are untouched.

## 5. `-D =1` named no macro

It was accepted and silently dropped, so the build failed later against the
*source* — `macro `GAIN` has not been declared` — rather than against the
command line that was wrong. Now refused with the offending argument quoted.

## Written, then withdrawn: LRM 3.6.1.2's nature rules

The hunt also found that a base nature may omit `abstol` or `access` — of each
the LRM says *"This attribute is required for all base natures"* — and that a
derived nature may redefine `access`, which 3.6.1.2 calls *"illegal"*. Both
checks were implemented here, and **both were withdrawn when the regression
sweep failed two suites within one run**:

- `derivednature_examples` — Enhancement-39 supports a derived nature declaring
  its own access function **on purpose**. Its shipped example derives `Current2`
  with a fresh one, and Enhancement-422's suite builds every derived nature that
  way.
- `natureref_examples` — Enhancement-422 pins *"a nature with NO abstol
  attribute at all stays legal"* as a deliberate decision.

E-422's stated reason — *"the LRM makes it optional"* — does not survive reading
3.6.1.2, which is quoted above. But the **decision** stands on its own, neither
omission produces a wrong answer, and reversing a documented project decision is
a call for the project rather than a side effect of a bug hunt. The same standard
that left `5.` alone applies here: spec-conformance nits with no wrong answer are
not worth breaking working models over.

Both rules are recorded in place, in `verify_nature`, so the next reader finds
the decision rather than the idea — and the suite pins the accepted spellings so
reversing it later has to be deliberate. A **bad** abstol (zero, negative) is
still rejected: that is Enhancement-422's own guard, untouched.

## Deliberately not changed

**`5.` as a real literal.** LRM A.8.7 requires digits on both sides of the dot
in every `real_number` alternative, so `5.` is malformed — but its value is
always correct (5.0), no corpus model writes one, and making a *lexer* rule
stricter is exactly what broke eight shipping models earlier the same day:
Enhancement-458 reserved `expm1`, which HiSIM-SOI and HiSIM-SOTB each declare as
their own analog function. A syntax break with no wrong answer to prevent is not
worth that risk. Pinned as accepted so the decision is recorded rather than
rediscovered.

**Named blocks inside an analog function.** LRM 4.7.1 forbids them; openvaf
supports them and they work correctly, so rejecting them would break working
models to gain nothing.

## Verification

`examples/ctxguard_examples/verify_ctxguard.py` — **33/33**, both solvers. The
table half is checked by value against all three readings above, in 1-D, 2-D and
3-D, with the 1-D forms pinned unchanged; the crash half pins all four spellings
as refused-and-not-crashing while `.abstol`, `.flow.abstol` and user-defined
attributes keep working; the event half pins both forbidden contexts as refused
and the analog block as untouched; and every deliberate
non-change -- `5.`, named blocks in functions, and both withdrawn nature rules --
is pinned as accepted.

**Corpus: 107 compiled by both, 17 rejected by both, 0 rc differences, 0 byte
differences** against the Enhancement-459 binary. That check passed even with the
two withdrawn rules in place — no industry model declares such a nature — which
is precisely why it was the project's OWN suites, not the corpus, that caught
them. `cargo test` passes across 44 test binaries. Full regression **374/374**,
both solvers.

## What the hunt withdrew

Four candidates did not survive checking, and are recorded so they are not
re-reported: a `gain`/`GAIN` parameter collision (ngspice *does* warn — it prints
after the simulation results); `-8>>1` returning 2147483644 (correct — Verilog's
`>>` is logical, and `>>>` exists and gives −4); analog-function locals
persisting across calls (already a known deferred item, now characterised more
sharply: they persist across *evaluations*, so a single call reads a value
written later in the same block); and `0 && (1/0)` being rejected at compile time
(only when both operands are literals — a parameter-guarded division compiles and
behaves correctly).
