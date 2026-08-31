# Enhancement-520: jump statements, string functions, and the Annex C/E boundary

**Scope:** the Verilog-A subset boundary itself — Accellera VAMS-2023
Annex C, Annex E (SPICE compatibility), and the 2023 change records the
audit traced through Annex G Table G.7. One compiler crash, one whole
missing 2023 feature, one load refusal against a mandated fallback, two
silent acceptances made audible, and the corrections to this repo's own
documents that the audit's doc-half demanded.

**Suite:** [`examples/lrmjump_examples/`](../examples/lrmjump_examples/) —
22 checks, both solvers. `disable`, `analogloop`, `dowhile`, `funcarray`,
`arrayout`, `arrayret`, `generate`, `legacygen` and `lrm` all still pass;
fast and slow cargo suites green.

## break / continue / return (LRM 5.11)

"Verilog-AMS HDL provides C-like jump statements break, continue, and
return." VAMS-2023 put them in the analog grammar (A.6.4/A.6.5), Annex B
reserves the words, and Annex C does not exclude them — and none of the
three existed: `break;` died as "'break' was not found in the current
scope", `return x;` as a parse error. Worse, the compliance doc claimed
the *language* has no such keywords and that the compiler suggests the
`disable` idiom in a diagnostic that never existed.

They are implemented end to end. The grammar gains one `JumpStmt` node
(sourcegen); the words are **contextual keywords** — a pre-pass keeps
them keywords only in statement shape (statement-boundary token before,
`;` or an expression start after), so pre-2023 source using `break` as an
identifier still compiles, now flagged by the L012 keyword-compat lint
like every other VAMS reserved word. Typing treats `return expr` exactly
like an assignment to the function-name variable, casts included.

Lowering reuses the `disable` machinery's shape — jump to a recorded
block, continue into a fresh unreachable one. Loops carry a
`(continue_target, break_target)` scope: `while`/`do-while` re-test the
condition, `for` gained a dedicated **increment block** so `continue`
still increments (skipping it is an infinite loop), and `repeat` gained a
**latch block** so `continue` still decrements the counter. Loop exit
blocks are now sealed only after the body, since a `break` adds a
predecessor. Every inlined function body gets an exit block; `return`
optionally writes the return place, then jumps. The suite checks all of
it numerically — including a `return` from inside a `for` inside a
function, and `fname = 5.0; return;` keeping the 5.

Position rules per 5.11: `break`/`continue` outside a runtime loop and
`return` outside an analog function are targeted errors. The 5.9.3
exclusion (no jump statements in a genvar `analog_for`) needed **zero
extra code**: those loops unroll at elaboration, so a jump inside one
reaches validation loop-less and draws the outside-a-loop error.

## String analog functions crashed the compiler (LRM 4.7.1, Mantis 7808)

Syntax 4-5 makes `string` a legal analog-function type, and 4.7.2.1/4.7.2.3
give string returns and output arguments empty-string initialization.
Declaring one ICEd openvaf-r: "internal error: entered unreachable code:
invalid function return type String" — two `unreachable!` arms in the
function-inlining lowering. Both arms now initialize with `sconst("")`;
string returns and string output arguments work end to end (`pick(1)`
prints `pos`, an output arg comes back `high`).

## $limit: fallback, not refusal (LRM 9.17.3, Annex E Table E.2)

"If the string refers to an unknown or unsupported function, the
simulator is responsible for determining the appropriate limiting
algorithm, just as if no string had been supplied." E-396 made an
unresolved `$limit` name a hard **load failure** — justified then,
because the alternative was a NULL function pointer and a SIGSEGV. The
mandated fallback exists now: the slot binds a pass-through (no
limiting, one adapter serves every arity since extra C arguments are
simply never read) and a load-time warning names the function, the
arity, and the supported set. The model runs; only its convergence aid
is absent — exactly the no-string behavior. The SIGSEGV stays fixed:
every slot always gets a real function.

And Table E.2's preferred name **vdslim** — which this tree spells
`limvds`, so a model written against the LRM's own table was refused —
is now an alias in both the compiler's L020 lint set and the ngspice
loader, bound to the real implementation.

## Made audible

- **`$realtime` in the analog context** (Table 9-7 says No; the 9.10
  NOTE deprecates it): kept as a backward-compat alias of `$abstime`,
  but each use now warns — with the trap spelled out that VAMS 2.0–2.4
  scaled it to `` `timescale `` units (default 1 ns), so legacy source
  reads values 10⁹ off from what this alias returns.
- **`` `default_discipline ``** (Annex C.4: "not supported in
  Verilog-A"): was silently swallowed — even with a nonexistent
  discipline name — while a VAMS source relying on it would resolve net
  disciplines differently. It warns as an ignored AMS-only directive
  now, with its own preprocessor test.

## The document corrections

The audit's doc-half found the compliance document asserting the
opposite of the LRM in three places, all fixed: the break/continue
claims (above); `casex`/`casez` presented as subset conformance when
Annex C.7 *excludes* them from Verilog-A (now marked as the deliberate
extension it is, likewise the obsolete legacy `generate` per G.2.3);
and the `lrm_examples` headline counts, stale by five fixed limitations
(now 47 compile / 12 limitations / 21 mixed-signal, quoting
`manifest.json` as the executable ground truth). The Annex E boundary
is documented for the first time: SPICE-primitive instantiation from
Verilog-A source (`resistor`, `bjt`, …) is not supported — a clean
error; instantiate SPICE devices at netlist level.
