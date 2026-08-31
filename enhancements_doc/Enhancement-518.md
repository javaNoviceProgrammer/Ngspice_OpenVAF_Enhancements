# Enhancement-518: expressions and math, audited against the LRM

**Scope:** Accellera VAMS-2023 clauses 4.1–4.4 (operators, precedence,
built-in functions, signal access), from the full LRM conformance audit.
Two bugs, one undefined-behavior hazard closed, one internal
inconsistency resolved, one operator pair taught to lex, and one operator
pair flagged as the extension it is.

**Suite:** [`examples/lrmexpr_examples/`](../examples/lrmexpr_examples/) —
22 checks, both solvers. `operator`, `precedence`, `casexz`, `concat`,
`stringcmp`, `domainrt` and `lrm` (both solvers) all still pass.

## Same-node branch access compiled silently (LRM 4.4, Table 4-16)

Table 4-16 lists `V(n1,n1)` and `I(n1,n1)` as **Error** — "the operands
of an expression shall be unique to define a valid branch". `V(a,a)`
compiled with *no* diagnostic at all and silently evaluated to 0; a
one-character slip produced a device term that contributed nothing.
Both potential and flow access over the same net are located errors now.

Two boundaries were deliberately drawn. A **named** degenerate branch
declaration (`branch (a,a) b;`) keeps its E-414 warning — declaring one
is survivable, accessing it is not. And inside an **elaboration buffer**
the check does not fire: a flattened instantiation legally ties two
formal terminals to one node — a diode-connected transistor; the LRM's
own ECP-oscillator example does it — and the flattener then renders
`V(s,c)` as `V(out,out)`. Those accesses keep the pre-elaboration
semantics (read 0, contribute a net nothing). This carve-out was not
theoretical: the first build broke the `lrm_examples` suite on exactly
that oscillator. Recognition reuses the diagnostics sink's
elaboration-buffer name test, now exported from `basedb`. A latent
copy-paste bug found next door was fixed in passing: the nature-access
validator read `args[0]` twice, so its incompatible-discipline arm could
never fire.

## Modulus by a deck-supplied zero (LRM 4.2.4)

"It shall be an error to pass zero (0) as the second argument to the
modulus operator." A *literal* zero was already a compile error (E-333);
a zero arriving through a model card reached `Irem`/`Frem` unguarded —
NaN on the real path, target-specific garbage on the integer path, and
the analysis died with a generic "Transient op failed" naming neither
the operator nor the value. The `%` divisor now gets the E-509
three-route treatment: parameter-derived zero aborts with
`OSDI(fatal) … %: the second operand (the modulus divisor) is zero,
which LRM 4.2.4 makes an error`. (The first cut printed garbage — the
message's leading `%` was eaten by the printf-style formatter; escaped.)
A genuinely runtime divisor is deliberately left unguarded, consistent
with the documented probe-argument policy.

## Integer division UB closed at the LLVM layer

That runtime case used to be genuinely dangerous: `Idiv`/`Irem` lowered
to raw LLVM `sdiv`/`srem`, which are **undefined behaviour** on a zero
divisor and on `INT_MIN / -1` — poison for the optimizer and a SIGFPE
trap on the x86 builds this project ships. Following the E-335 shift
precedent, both are now pinned at the lowering: `x/0` → 0,
`INT_MIN/-1` → `INT_MIN` (the two's-complement wrap the rest of the
integer surface already uses), `x%0` → 0, `INT_MIN%-1` → 0. The MIR
constant folder folds to the same values, so a folded chain and the
compiled model always agree. Verified live: `INT_MIN/-1` reads
−2147483648, runtime `/0` and `%0` read 0.

## Shift distances: the error that contradicted the runtime (LRM 4.2.11)

The shift distance is "always treated as an unsigned number" with no
upper bound — `1<<32` is legal Verilog-A and equals 0, which is exactly
what the *runtime* path computed (E-335 guards). But the same expression
with a **literal** distance was a hard error (E-333, to keep LLVM poison
out of the IR). Rejecting a legal constant the runtime handled correctly
was an internal inconsistency: the diagnostic is a warning now, and the
value is the LRM's — `1<<32` folds to 0, `-8>>>34` to the sign fill —
identical on the compile-time and runtime paths.

## `===`/`!==` lex; `<<<`/`>>>` flagged (LRM 4.2.6, 4.2.11)

Table 4-1 lists the case-equality operators and 4.2.6 grants them
"limited support in the analog block"; the lexer did not know them, so
`(i === j)` died as `==` then a stray `=` with a baffling message. They
lex now (new `EQ3`/`NEQ2` tokens through the sourcegen pipeline), parse
at the `==` precedence level, and evaluate as `==`/`!=` — *exact* in a
2-state analog world, which has no x/z bits for them to distinguish.

The arithmetic shifts go the other way: 4.2.11 says they "can not be
used in an analog block", but `>>>` is Verilog's only spelling of a
sign-extending shift, so they stay — as a **flagged extension**, one
warning per use naming the clause. All thirteen big CMC models compile
with zero warnings, so the flag costs real models nothing.

## Documented

The runtime-probe domain policy (a probe argument outside a math
builtin's domain is deliberately not refused mid-Newton) is now
explicitly marked as a deviation from 4.3.2's unqualified "shall report
an error", and the domain-refusal claim is scoped to exclude `0**0`
(= 1.0 by near-universal convention, IEEE 1364's integer table
included).
