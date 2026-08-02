# Enhancement-400 — the contribution that statement order threw away

[Enhancement-399](Enhancement-399.md) left one round-13 finding open. A branch
that receives **both** a potential and a flow contribution, with nothing
conditional between them, keeps only the last one. The other is discarded in
silence:

```verilog
analog begin V(a,b) <+ 0.4; I(a,b) <+ 1e-3; end
analog begin I(a,b) <+ 1e-3; V(a,b) <+ 0.4; end
```

Measured through a 1 V source and a 1 kΩ series resistor, printing `v(a)` and
`i(v1)`:

| model | `v(a)` | `i(v1)` | behaves as |
| --- | --- | --- | --- |
| `V(a,b) <+ 0.4; I(a,b) <+ 1e-3;` | 0.0 | −1.0 mA | **`I` only** |
| `I(a,b) <+ 1e-3; V(a,b) <+ 0.4;` | 0.4 | −0.6 mA | **`V` only** |
| `V(a,b) <+ 0.4;` alone | 0.4 | −0.6 mA | — |
| `I(a,b) <+ 1e-3;` alone | 0.0 | −1.0 mA | — |

Identical physics, a different answer, decided by which statement was written
second — and no diagnostic at compile time or at run time.

The answers themselves are unchanged by this release. What changes is that the
compiler now says so:

```
warning[L022]: branch (a,b) is contributed as both a potential and a flow source
  --> dut.va:7:9
  |
7 |         V(a,b) <+ 0.4;
  |         ^^^^^^^^^^^^^^ this potential contribution is discarded
8 |         I(a,b) <+ 1e-3;
  |         --------------- info: the branch is a flow source here
  |
  = a branch is either a potential source or a flow source; when both are
    contributed with no condition between them the last contribution decides,
    and the other one is dropped -- it reaches neither the residual nor the
    Jacobian
  = to switch between the two, contribute them in mutually exclusive
    conditional paths (a switch branch); that form is unaffected by this check
```

## The detection E-399 predicted does not work

E-399 recorded the mechanism as already available: in `sim_back`'s DAE builder,
`build_branch` matches on `BranchInfo::is_voltage_src`, and when that is a
constant while the *other* kind's contribution is non-trivial, a contribution
was written and discarded.

It is never non-trivial. Instrumenting `build_branch` shows both orderings
arriving with the discarded side already zero, indistinguishable from a model
that never wrote it at all:

| model | `is_voltage_src` | `voltage_src.resist` | `current_src.resist` |
| --- | --- | --- | --- |
| `V; I;` | `FALSE` | **`F_ZERO`** | `v18` |
| `I;` alone | `FALSE` | `F_ZERO` | `v16` |
| `I; V;` | `TRUE` | `v18` | **`F_ZERO`** |
| `V;` alone | `TRUE` | `v16` | `F_ZERO` |

`hir_lower::stmt::contribute_value` is the reason: every contribution resets the
*opposite* place to zero before adding its own value.

```rust
self.ctx.def_place(
    PlaceKind::Contribute { dst: write, reactive: false, voltage_src: !voltage_src },
    F_ZERO,
);
```

That statement **is** the discard. By the time the backend sees `BranchInfo` the
evidence is gone, which is exactly why nothing downstream could report it.

## The test, spelled across the stages that each hold part of it

No single stage can answer it.

* The **DAE build** knows the branch is not a switch. A real switch branch has a
  runtime `is_voltage_src` and takes the third arm of `build_branch`, where both
  kinds stay live. A constant means one kind wins on every path. This half was
  right.
* The **HIR** still holds both statements, their source positions, and their
  lint attributes. `Module::contribution_sites` (new) buckets every contribution
  of a module's analog blocks by branch, normalising node order and ground
  references the way `hir_lower` does, so `I(a,b)` and `V(b,a)`, or `V(a,gnd)`
  and `V(a)`, resolve to one branch.

A report needs both: a branch whose kind is fixed, that the module contributes
the other kind to.

### Constant is not the same as unconditional

There is a third stage in it. `is_voltage_src` can also become constant *after*
lowering, when constant propagation folds an `if` whose condition is a
configuration constant. BSIMSOI writes the switch-branch idiom correctly —

```verilog
if ((B4SOIbodyMod == 0) || (B4SOIbodyMod == 2))
    V(b, p)  <+ 0;
else begin
    I(b, p)  <+ B4SOItype * Ibp;
    I(b, p)  <+ white_noise(fourkt*abs(Ibp)/(abs(vbp)+1.0e-9), "rbp");
end
```

— and `B4SOIbodyMod` is a plain `0` whenever `PORT_CONNECTED` is undefined, so
SCCP proves the `else` dead and `is_voltage_src` folds to `TRUE`. Optimized MIR
cannot tell that apart from a branch the author wrote as a single source with a
stray contribution of the other kind. It is not a discarded contribution; it is
the configuration doing its job.

So the branch's character is read where the question is still answerable —
from the **unoptimized** MIR, in `Context::new`, before any pass runs
(`Context::unconditional_branch_kind`). Lowering has already collapsed a phi
whose arms agree, so a branch that is the same kind on every path the author
wrote still reads constant there, while BSIMSOI's genuinely differing arms stay
a phi.

This was not a hypothetical: **BSIMSOI was flagged before the refinement and is
silent after it**, while every true positive is unaffected.

### A literal zero has nothing to discard

BSIM4 gave the third one. The standard CMC series-resistance idiom is

```verilog
if (BSIM4rdsMod) begin
    I(s,si) <+ Issi;
    I(d,di) <+ Iddi;
end
else begin
    V(s,si) <+ 0.0;
    V(d,di) <+ 0.0;
end
...
I(si, s) <+ white_noise(4 * `P_K * T * gspr, "Rs");   // ~150 lines later
```

and the unconditional noise contribution at the end makes the branch a flow
source on every path, so the `V(s,si) <+ 0.0` is overwritten. But that statement
carries no value to lose. `hir_lower::stmt::contribute` recognises a literal-zero
potential contribution as a **node-collapse request** and delivers it through a
`CollapseHint` callback, not through the branch's residual — which is a
different mechanism, and one this check says nothing about.

So a discarded contribution of literal zero is not reported, using the same
`is_zero` test lowering itself uses to decide a contribution is a collapse. The
claim being made — *you computed a value and it was thrown away* — is simply
vacuous for a zero.

The reverse pairing is still reported: in `I(a,b) <+ 1e-3; V(a,b) <+ 0;` the
**flow** contribution is the one discarded, and 1e-3 is a value.

## The diagnostic channel out of the backend

`sim_back` had no way to report anything raised during the DAE build — but it
was already reporting from *module collection*: `collect_modules` takes a
`ConsoleSink` and `module_info.rs` implements `Diagnostic` for its own findings.
The same channel was extended rather than a new one invented.

One `ConsoleSink` now lives for the whole compilation in `openvaf::compile` and
is threaded `osdi::compile` → `CompiledModule::new` → `DaeSystem::new`, which
reports once the system is built. `sim_back/src/diagnostics.rs` holds the
`Diagnostic` implementation, carrying the spans recovered from the HIR at the
moment of detection because MIR has none to give.

Being a real diagnostic and not an `eprintln!`, it is a real lint:

| | |
| --- | --- |
| `discarded_contribution` (**L022**) | default `warn` |
| `--allow discarded_contribution` | silent |
| `(* openvaf_allow="discarded_contribution" *)` on the statement, block or module | silent |
| `--deny discarded_contribution` | error, `rc=65`, object files removed, **no `.osdi` linked** |

## What is *not* reported

The discrimination is the point of the release, so each case was measured, not
reasoned about:

| written as | reported |
| --- | --- |
| `V(a,b) <+ ..; I(a,b) <+ ..;` (either order) | ✅ |
| named branch `V(br); I(br);` | ✅ |
| reversed nodes `V(a,b); I(b,a);` | ✅ |
| ground `V(a); I(a);` | ✅ |
| `if (sw) V(a,b) <+ ..; else I(a,b) <+ ..;` — a switch branch | ❌ silent |
| `if (V(a,b) > x) V(..); else I(..);` — an op-dependent switch | ❌ silent |
| `I(a,b) <+ ..; if (sw) V(a,b) <+ ..;` — still a runtime switch | ❌ silent |
| `if (sw) V(a,b) <+ ..; I(a,b) <+ ..;` — the `V` can never win | ✅ |
| `V(a,b) <+ ddt(..); I(a,b) <+ ..;` — a discarded *reactive* potential | ✅ |
| `I(a,b) <+ ..; V(a,b) <+ 0;` — the collapse discards the flow | ✅ |
| `V(a,b) <+ 0;` alone — node collapsing | ❌ silent |
| a conditional `V(..) <+ 0` collapse then an unconditional flow (BSIM4 `rdsMod`) | ❌ silent |
| `V(out) : V(a,b) == 0;` then `I(out) <+ ..` — indirect contributes too | ✅ |
| a switch whose selector folds to a constant (BSIMSOI) | ❌ silent |
| any discarded contribution whose value is a literal zero | ❌ silent |

The LRM's own switch-branch examples — the `relay` of page 114 and the
`parares` of page 155, both shipped in `examples/lrm_examples/` — are the
if/else form and stay silent.

## A real model was wrong

Of the 124 `VA_TEST` models, exactly one is reported: **FBH HBT 2.3**, three
times.

```
warning[L022]: branch (niiy) is contributed as both a potential and a flow source
    --> fbh_hbt-2_3.va:705:13
     |
705  |             I(niiy)   <+ Iniix;
     |             ^^^^^^^^^^^^^^^^^^^ this flow contribution is discarded
706  |             V(niiy)   <+ I(niiy);
     |             --------------------- info: the branch is a potential source here
     .
711  |             V(niiy)   <+ Iniix;
     |             ------------------- info: the branch is a potential source here
```

Both arms of the model's `if (Fcorr==0)` leave `niiy` a potential source, so the
branch is one kind on every path and the flow contribution is dead on all of
them — the model's correlated-noise network does not do what those two lines
say. The same shape repeats for `niiiy` and `nivy`. That is the defect this
release exists to make visible, found in a published compact model.

## Verification

* **Full regression 322/322.**
* **`cargo test --workspace --features llvm18` 210/0** — 209 as before plus
  `sim_back::dae::tests::discarded_contribution`, which pins both orderings,
  both single-kind branches, the switch branch, and the `openvaf_allow`
  attribute at the layer that changed.
* **Corpus differential** — all 124 `VA_TEST` models compiled with the shipped
  binary and with this one at the same `-o` path (an `.osdi` embeds its own
  output path): **107 compiled by both, 0 return-code differences, 0 byte
  differences.** The check reports **1** model, and that report is a true one.
* **A second sweep over every model this repository ships** — 515 `.va` files
  under `examples/` and `openvaf/integration_tests/` (BSIM3/4/6, BSIMSOI,
  BSIMBULK, HICUM, HiSIM, PSP, MEXTRAM, ASM-HEMT, DIODE_CMC and the rest):
  **0 trip the check.** Both narrowings above were found there and in the
  corpus, not reasoned out in advance — the first draft flagged BSIMSOI and
  BSIM4, and both are correct code.

Zero byte differences is the load-bearing number: this release changes what the
compiler *says*, never what it emits.
