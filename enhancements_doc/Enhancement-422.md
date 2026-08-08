# Enhancement-422 — one reference, three different outcomes

A `nature` declaration makes up to three references to other natures — `parent`,
`ddt_nature`, `idt_nature` — and a `discipline` makes two more, `potential` and
`flow`. They are the same kind of reference, resolved by the same function.
Before this release a name that failed to resolve produced **three different
outcomes** depending on which one you wrote:

| reference | a name that does not resolve |
|---|---|
| `parent` | **crashes the compiler** |
| `ddt_nature`, `idt_nature` | silently discarded, nothing said |
| `potential`, `flow` | reported much later, against the **model body** |

Now all five say the same thing, at the declaration.

## The crash

```verilog
nature Vd : Vbaze;      // meant Vbase
  access = V1;
endnature
```

```
OpenVAF encountered a problem and has crashed!
A log file has been generated at ".../openvaf-crash-1786218907.log"
Panic occurred in file 'openvaf/osdi/src/ndatable.rs' at line 79
called `Option::unwrap()` on a `None` value
```

Nothing validated the name. `hir_ty::lower` resolves it with
`lookup_nature(..).ok()` — **which throws the error away** — and OSDI codegen
then unwrapped the missing name-map entry. Six spellings reached it: a
one-character typo, an undeclared name, a **discipline** name, an **access
function** name, the **module** name, and a discipline-qualified parent whose
discipline does not exist.

**And it did not have to be used.** A stray `nature Stray : nosuch;` that no
discipline and no module ever mentions crashed the build all the same — so one
bad declaration in an included header killed every model that included it.

### The tell was five lines below the panic

`resolve_nature_ref` (parent) `.unwrap()`ed. `resolve_nature_index` — added by
Enhancement-39 for `ddt_nature`/`idt_nature`, immediately below it in the same
file — was already written as `unwrap_or(u32::MAX)`. The sibling was hardened
and this one was not, which is why one crashed and the other went quiet.

Both halves are fixed: the names are now diagnosed in `hir_ty`, so a bad
reference never reaches codegen, and `resolve_nature_ref` returns `NATREF_NONE`
instead of panicking if one ever does again.

## Cycles

`nature A : A;` and two- and three-nature cycles all compiled. Salsa recovers
from the query cycle by re-resolving with the parent dropped — so nothing
crashes, nothing is said, and the nature **silently becomes its own base
nature**. It then inherits no units, and since discipline compatibility falls
back to the same-base-nature rule when units are absent (Enhancement-399), *the
cycle changes which disciplines the nature is compatible with*.

Parameter cycles, `aliasparam` cycles (Enhancement-414) and analog-function
recursion are all rejected by name. Nature cycles were the family member nobody
checked. The walk deliberately uses `nature_data` + `lookup_nature` rather than
`nature_info`, so it sees the cycle instead of salsa's recovery, and reports only
from the member the walk returns to — an N-cycle gives N reports, not N².

## `abstol`, which was unvalidated in two different ways

`abstol` is the size below which the solver stops distinguishing two values.

* `abstol = 0`, a negative abstol, and a literal that overflows to infinity
  (`1e400`) all compiled and reached the OSDI nature descriptor.
* Separately, an abstol whose value is **not a folded real constant** —
  `1.0/0.0`, `0.0/0.0`, `1e-6+0.0`, even `"abc"` — was **silently discarded**,
  leaving the nature with no abstol at all, which is not what the declaration
  says. The lowering only stores `abstol` when `as_constexprval().as_real()`
  succeeds; everything else fell on the floor.

Both halves are checked. A nature with **no** `abstol` attribute remains
perfectly legal — the LRM makes it optional, and Enhancement-399 already decided
how an absent attribute behaves.

## Scope: the cascade is recorded, not hidden

A discipline whose `potential` names a missing nature now reports at the
declaration, naming the discipline and the missing nature — but the old
body-level complaint (`illegal access of branch '(p, p)'`) **still follows it**.
What changed is which comes first.

Suppressing the cascade means teaching the body walk that the discipline is
already known-broken, which is a wider change than the evidence asks for. So the
example suite pins the *ordering* — the declaration error must lead — and the
cascade is stated here rather than quietly left for someone to rediscover.

## The harness lesson, which is the reason this took three rounds to find

**openvaf installs a panic hook.** A hard compiler crash exits **101** with a
polite banner:

```
OpenVAF encountered a problem and has crashed!
```

containing **neither the word "panicked" nor a backtrace**. A crash detector
keyed on signals (a negative return code) or on `"panicked"` in the output scores
it as an ordinary rejection — which is exactly why the round-26 and round-27
hunts both reported "no crashes found". Round 27's batches were re-run with the
corrected detector and stayed clean, so that round's claim survives; round 26 ran
in another session and was not re-verified.

The example suite asserts the **banner is gone and no crash log was written**,
not merely that the return code is non-zero — because the defect's signature was
a non-zero return code with a plausible-looking message.

## Verification

* **`examples/natureref_examples` — 51/51.** Roughly half is the accept half:
  correctly spelled parents, discipline-qualified references that resolve,
  three- and four-deep acyclic chains, real `ddt_nature`/`idt_nature`, four legal
  abstol values, a nature with no abstol at all, and a model on **custom natures
  that still simulates** (−1 mA, measured).
* **The standard library is pinned explicitly**: a stock `electrical` model, a
  two-discipline `electrical` + `thermal` model, and a user nature derived from
  the stock `Voltage` all compile clean. That is the check that matters, since
  `disciplines.vams` is a dense set of parent/`ddt_nature`/`idt_nature`
  references and an over-eager check would break every model in existence.
* **124-model VA_TEST industry corpus and 40-model `integration_tests` corpus**,
  compiled with the previous shipped binary and this one: **the only difference
  is Enhancement-421's typo fix**, which the shipped binary predates. Not one
  nature or discipline diagnostic fires across 164 real models.
* `cargo test --features llvm18` **210/210**, no snapshot moved.
* **Full regression 339/339**, both solvers.

## Found by

A round-28 hunt over openvaf-r. It also verified a large surface clean, and one
result is worth recording because it closes the vein that produced
Enhancement-405: **eleven equivalent spellings of a resistor** — unnamed and
named branches, mixed node/branch probes, `V(p)-V(n)`, double negation, both
endpoints reversed, via a variable, via an analog function, the potential form
`V <+ I/g`, and an indirect contribution — **agree exactly at DC and AC**, as do
five spellings of a capacitor.

One of the hunt's observations was withdrawn on evidence: nature-attribute access
(`Vbase.abstol`) is rejected in a module body but works where the LRM puts it,
inside a nature declaration, so it is not a defect.
