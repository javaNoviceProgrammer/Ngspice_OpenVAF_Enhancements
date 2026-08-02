# Enhancement-399 — thirteen ways to be told nothing

Round 13 of the bug hunt found fifteen defects. Thirteen are fixed here. They
are not one subsystem; they are one **shape**: the tools accepted something a
careful author could plausibly write, said nothing at all, and produced a
different answer.

Nine of the thirteen are silent acceptance. Two are diagnostics that state the
opposite of the truth. Two are values that depend on which door they came
through.

## 1. `{...}` where the LRM requires `'{...}`

A concatenation supplied where an array literal belongs was accepted in silence,
and the builtin then behaved as though handed an **empty** table:

| | `'{...}` (array literal) | `{...}` (concatenation) |
| --- | --- | --- |
| `$table_model(2.0, …{1,10,2,20,3,30})` | **20.0** | **0.0** |
| `noise_table(…{10,1e-12,1000,3e-12})` | 0.0445 | baseline — **no noise at all** |

`white_noise(1e-4)` scales correctly to 1573 in the same position, so the noise
machinery works; the table simply contributed nothing.

Every check in this area was written `if let Expr::Array(..)`, and a
concatenation is a different variant — so the whole check was skipped rather
than failed. The rule already existed elsewhere: initialising a parameter array
from a concatenation was always rejected. These two builtins never applied it.

**Only a concatenation is refused.** A bare array-*variable* reference
([Enhancement-4](Enhancement-4.md)) is legitimate here and still compiles.

**`laplace_*` is deliberately not included.** It lowers `{1.0}` correctly —
measured identical AC response to `'{1.0}` — and `arraycast_examples` depends on
that form. The rule is *reject what is silently wrong*, not *reject everything
that is not an array literal*. An earlier draft of this release did include it,
and the regression suite caught it.

## 2. No analysis-name string was validated anywhere

`analysis("tarn")` is false in every analysis. `@(initial_step("tarn"))` fires
never. A typo therefore turns an entire branch or initialisation block into dead
code, and nothing was reported at compile time or at run time.

```
@(initial_step)                fires        @(initial_step("tarn"))   never fires
@(initial_step("dc"))          fires        analysis("tran")          1.0 in tran
@(initial_step("dc","tran"))   fires        analysis("tarn")          0.0 in every analysis
```

Now reported by a new `unknown_analysis_name` lint (L021) — a warning, not an
error, exactly as [Enhancement-396](Enhancement-396.md) treats `$limit`, because
the name set is simulator-defined. The set is ngspice's own, from
`osdi/stdlib.c`: `ac, dc, ic, nodeset, noise, static, tran`.

## 3. An event `or` list lost everything after its first `)`

Found while testing (2), not in the hunt report.

```
@(initial_step("nonsense") or final_step)   never fired
@(final_step)                               fired
```

`initial_step`/`final_step` are keyword tokens, so a phase list's parentheses
appear in the same token stream as the event list's own, and the collector broke
on the first `)` it saw. A perfectly good `final_step` was discarded because an
**earlier** member of the list happened to take an argument. The collector now
tracks parenthesis depth. Verified by simulation, not by compiling.

## 4. Event arguments that were dropped on the floor

`@(cross)`, `@(above)` and `@(timer)` accepted any number of arguments and never
checked their tolerances — because `event_from_condition` took the arguments it
modelled off an iterator and **abandoned the rest**, and the tolerances were not
represented in the HIR at all. `@(cross(e,0,t,x,1,2))` lowered identically to
`@(cross(e,0))`.

`Event` now carries the tolerances and the surplus. Lowering still ignores them;
`hir_ty` reads them. Negative tolerances and surplus arguments are rejected.

`@(above)` takes **three** arguments (`expr, time_tol, expr_tol`, LRM 5.10.3),
not two — `opargs_examples` uses the three-argument form, and the regression
suite caught the first draft that assumed two.

## 5. `@(cross())` fired unconditionally

Worse than "accepted": a missing first argument made `event_from_condition`
return `None`, which degrades the **whole event control** to an unconditional
body — so the guarded statement ran on every evaluation. It is recorded as
`Expr::Missing` now and rejected in validation.

It must be rejected *there* and not later: lowering panics on a missing
expression, and an earlier draft of this release turned a wrong answer into a
compiler crash.

## 6. An integer parameter's value depended on how it was supplied

`INPgetValue` converted with `floor(0.5 + x)`, which rounds .5 toward
+infinity. Verilog-A's own conversion inside a model rounds half **away from
zero** per the LRM. The same value therefore differed:

| value | in-model `ii = v` | netlist `.model mm dut(n=v)` |
| --- | --- | --- |
| −0.5 | −1 | **0** |
| −1.5 | −2 | **−1** |
| −2.5 | −3 | **−2** |
| −3.5 | −4 | **−3** |

Every negative half-boundary disagreed; positives always agreed. Now `round()`,
which is exactly the LRM rule.

This is a **generic parser path**, shared by every device rather than only OSDI
ones. The two forms differ only at exact negative half-integers, where no
built-in uses a meaningful value and where the old answer was the surprising
one. The full regression confirms nothing depended on the old behaviour.

## 7. A convergence failure was announced as a model abort

A model containing no `$fatal` at all, failing on a singular matrix, was
reported with:

```
Error: a Verilog-A device raised $fatal during the operating point; aborting.
       This is not a convergence failure -- see the OSDI(fatal) message above
```

with no `OSDI(fatal)` line anywhere above to read. Both claims were false, and
the text actively denied the true cause — a singular matrix that had just
defeated gmin stepping, source stepping and optran, each of which printed its
own correct diagnostic immediately above.

The cause was control flow, not diagnosis. CKTop's ordinary "every convergence
aid failed" exit **fell through** into the `fatal:` label.
[Enhancement-378](Enhancement-378.md) added that block for a genuine
device-raised abort; it landed in the fall-through path of the normal failure
route, so every convergence failure inherited its message. The path returns
`converged` now, leaving E-378's own `goto fatal` jumps as the only way in —
which is what it intended.

Verified both directions: a convergence failure no longer claims `$fatal`, and a
deliberate `$fatal` is still reported as one, with its `OSDI(fatal)` line.

## 8. Three more standard `$simparam` names

`iteration` (`STATnumIter`), `abstime` (`CKTtime`) and `simulatorSubversion`
(0) — the ones ngspice can answer truthfully from state it already keeps.

`shrink`, `imax`, `imelt` and `rthresh` stay **out**, keeping
[Enhancement-394](Enhancement-394.md)'s stated reasoning: ngspice has no such
option, and a made-up number is worse than no answer.

What made the absence matter is that an unknown name is not a soft miss.
`$simparam("iteration")` with no default argument aborts the **entire run** with
`OSDI(fatal)`, so a model ported from another simulator did not degrade — it
died.

## 9. Two natures that agreed only in what they left out

`NatureTy::compatible` compared `Option<String>` units directly, and
`None == None` is true. The discrimination was exact:

| | before |
| --- | --- |
| different units (`"V"` vs `"K"`) | correctly rejected |
| one declares, one omits | correctly rejected |
| **both omit** | **accepted** |

So two unrelated natures, neither declaring `units`, and a branch spanning their
two disciplines compiled in silence. `units` is an LRM-required nature attribute
but omitting it is accepted, so this was reachable from ordinary source.

An absent units string is not evidence of anything and can no longer serve as
evidence of compatibility. When either side lacks units the check falls back to
the LRM's actual rule — same base nature — which keeps a nature compatible with
itself and with anything derived from it (`nature Derived : Base`, with no units
of its own, still branches against `Base`).

This is the weakness round 10 recorded as *"compatible compares UNITS STRINGS
ONLY"*, reached through a different door: rather than matching the units, omit
them from both.

## 10. A backtick that was a lookalike of itself

`U+0060` — the ASCII backtick — was listed in the unicode-lookalike table as a
lookalike of itself, so every plain ASCII backtick set the "contains unicode"
flag. A stray `` `endif `` was answered with:

```
help: It looks like you used characters that look similar to ascii:
  ` instead of `
info: replacing these lookalikes with ascii yields: '`endif'
```

— advising the reader to replace a character with itself, quoting text
byte-identical to what they wrote, and never naming the real problem. Removed
from the table. A genuine lookalike is still caught (checked with an en-dash for
a minus).

## 11. A declared range no value can satisfy

`parameter real k = 2.0 from [3:1];` was accepted, as was `from (1:1)`. The
default bypasses range checking by design
([Enhancement-56](Enhancement-56.md)), so the parameter still reads 2.0 — but
every value supplied from a netlist is rejected at run time, including the
default's own value. The parameter was silently unsettable and the declaration
said nothing.

Only literal bounds are folded: a parameter-valued bound is not knowable here,
and `inf` does not fold, so `from (0:inf)` is untouched. `[1:1]` still compiles —
a closed point range is satisfiable by exactly one value.

## Known open — filed as follow-ups

Two findings from round 13 are **not** fixed here, deliberately.

**A branch contributed both `V` and `I` unconditionally: the last one wins,
silently.** `V(a,b) <+ 0.4; I(a,b) <+ 1e-3;` behaves as current-only; the
reverse order behaves as voltage-only. Identical physics, different answer,
decided by statement order. The fix belongs in `sim_back`'s DAE builder, and the
detection is already available there: when `BranchInfo::is_voltage_src` is a
**constant** yet the other kind's contribution is non-trivial, a contribution
was written and discarded. That test excludes the legitimate switch-branch
idiom, where `is_voltage_src` is a runtime value. What it needs is a diagnostic
channel out of the backend, which is more than a local edit.

**Bus elaboration is O(n²)** — 16K bits 1.96 s, 32K 7.56 s, 64K 31.7 s, four
times the work per doubling. Not a hang; no real compact model declares buses at
that scale.

Also open and minor: a typo'd attribute name (`(* dsec= *)` for `(* desc= *)`)
silently produces no operating-point variable, and `alter` on a non-instance
parameter prints `Error:` while ngspice still exits `rc=0`.

## Verification

Full regression **322/322**. `cargo test --workspace` **209/0**.

**Corpus differential** — all 124 `VA_TEST` models compiled with the shipped
binary and with this one, at the same `-o` path because an `.osdi` embeds its
own output path: **107 compiled by both, 0 return-code differences, 0 byte
differences, and 0 corpus models trip any new check.**

That last number is the point of the release rather than a footnote: every fix
here rejects or reports something, and none of it fires on a single real model
in the corpus.

Two over-reaches were caught by the regression suite and not by the corpus
differential — the `laplace_*` inclusion in §1 and the `@(above)` arity in §4.
Both were cases where the evidence for the narrower rule was already in hand.
