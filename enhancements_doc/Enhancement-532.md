# Enhancement-532: the openvaf-r hunt round — a short that fell open, a default off its own range

**Scope:** a 30-minute adversarial hunt over openvaf-r produced five
findings; this enhancement resolves all five — two code fixes (one HIGH
silent-wrong-answer in the simulator's collapse machinery, one new
compile-time lint), one diagnostic improvement, one documentation
correction, and one **retraction**: the hunt's own LRM reading was wrong,
the ledger records it, and the audited semantics are now pinned by suite
so they cannot regress in either direction. Twenty-plus probe families
(autodiff, reactive Jacobians, transient operators, noise spectra,
`$mfactor`, temperature plumbing, port flows, parser edges) came back
clean against analytic ground truth and are recorded in the hunt ledger.

**Suites:** [`examples/huntfix2_examples/`](../examples/huntfix2_examples/)
(new, 21 checks, both solvers). Three fixtures of
[`examples/rangeguard_examples/`](../examples/rangeguard_examples/) turned
out to carry defaults that genuinely violate their own ranges (they were
probing the exclude-cover checker with arbitrary defaults); one got a
legal default and two — shapes with **no legal value at all** — now assert
that the new lint speaks exactly where the cover checker deliberately
stays silent (75/75). Full sweep **446/446** ALL OK; cargo fast+slow green
with zero snapshot churn; all 26 bundled industry models compile with zero
warnings.

## The headline: a chained terminal short was silently an open circuit (ngspice)

`V(a,m) <+ 0.0; V(m,b) <+ 0.0;` with `m` internal is physically the same
circuit as `V(a,b) <+ 0.0` — and the direct spelling shorts correctly
(E-401 turns a terminal-terminal 0 V contribution into a real 0 V source).
The chained spelling conducted **nothing**: 0 A and the full source
voltage across the device, zero diagnostics from either tool. The first
collapse merged `m` onto one terminal; the second then faced a
terminal-terminal merge, which node collapsing cannot perform (ngspice
allocates terminal nodes), and the old loop silently `continue`d — the
V = 0 *equation itself* vanished from the system. Chains of any depth
failed identically; a chain landing on an internal node was fine, which is
exactly why the hole survived: BSIM4-class gate ladders chain collapses
like this, saved only by their conditions rarely all firing.

The fix stamps what the hint expressed: when `collapse_nodes` refuses a
terminal-terminal (or terminal-ground) merge, it records the pair and
`OSDIsetup` builds a **synthetic ideal 0 V source** between the two global
nodes — a branch equation `V(n1) − V(n2) = 0` plus the ±1 current entries,
the vsrc stamp at dc 0. The implementation follows the absdelay
extra-entry pattern end to end: `SMPmakeElt` at setup, KLU COO→CSC rebind
and real/complex pointer switching on every DC↔AC transition, stamps in
the DC/tran, AC and PZ loads (OpenMP branch included), branch-equation
reuse across `sens`'s double-setup (which forbids node allocation), and
deletion in `OSDIunsetup`. Netlist-tied endpoints and duplicate pairs
(two hints reaching the same terminals through different chains) are
dropped as redundant.

Rewriting the merge loop as proper group operations also fixed **two
latent corruptions** in the old code, both reachable through hint chains:

* a group already collapsed to **ground**, merged again, had its members
  re-mapped onto the other group — quietly *un-grounding* them — while the
  node count was decremented for a row that never disappeared;
* a redundant hint between two nodes **already in one group** (a collapse
  triangle) renumbered every node above the group representative and
  corrupted the count the same way.

The suite pins the direct/one-internal/two-internal spellings identical in
op, AC and transient, across `reset`, through `sens`, under both solvers —
plus the ground-chain, un-ground and triangle shapes with closed-form
currents.

## A parameter default off its own range now speaks (openvaf-r)

`parameter real r = -1.0 from (0:inf);` compiled silently and simulated
with r = −1 — a negative resistance from a declaration whose entire
purpose is to forbid it — while the very same value in `.model` is refused
at setup ("out of bounds"). The range machinery only ever judged **given**
values; the author's own default was exempt, per the CMC convention the
handbook documents (an out-of-range default as the "feature disabled" /
must-give state) — but the exemption was *silent*.

The new `param_default_out_of_range` lint (L027, warn by default) judges a
**constant** default against **constant** `from`/`exclude` constraints at
compile time, mirroring the generated `check_param` exactly: a `from` list
is a union (any match accepts), `exclude` is absolute (one foldable hit
reports regardless of the rest), and any non-constant `from` member makes
the union unjudgeable, so nothing is said. The `inf` bound literal now
const-folds — without it `from (0:inf)`, the single most common spelling,
was unjudgeable. The deliberate idiom keeps its silence per declaration
via `(* openvaf_allow="param_default_out_of_range" *)`; a default that
references an overridable parameter is left alone; all 26 bundled industry
models produce zero hits.

## The discarded-contribution report learned to say "noise-only" (openvaf-r)

The hunt logged "opposite-kind noise on a classified branch is silently
dropped" — and was wrong about the *silently*: E-400's
`discarded_contribution` warning already fired, and the hunt's own probe
had swallowed the compiler's stderr (recorded in the ledger; a hunt that
cannot retract its own mistakes cannot be trusted about the rest). The
real gap was the message. Since E-531 a noise-only contribution never
decides a branch's kind — so the report's "the last contribution decides"
was exactly wrong for the very site it pointed at. Contribution sites now
carry a `noise_only` classification (the HIR mirror of the lowering's
detector), and the report states it in as many words: the noise-only
contribution never decides the branch kind, but its **noise vanishes with
the losing kind** — express it in the branch's own kind or give it a
branch of its own.

## The retraction, pinned: noise correlation follows the call, not the label

The hunt claimed two same-named `white_noise` calls should sum coherently
(4S) and measured openvaf-r summing them as independent (2S). The claim
was **wrong**: the project's own LRM-conformance audit (4.6.4.6, p.92)
established that *labels group reporting; sources stay uncorrelated*, and
E-528 implemented exactly that after the original coherent-by-label
behavior produced impossible cancellations. Correlation is expressed by
reusing one call's **output** — and that idiom measures exact: contributed
twice, 4S to every printed digit; anti-series, exact cancellation to the
thermal floor; `2.0*white_noise(S)`, power ×4. "Fixing" the finding would
have regressed an audited fix. Three suite checks now pin all three shapes
against closed-form spectra, so the semantics cannot drift silently in
*either* direction — toward the bug or toward the retracted "fix".

## limexp's knee, written down

`limexp` is exp up to the overflow cutoff `ln(1e30)` ≈ 69.08 and the
tangent line `1e30·(1 + x − ln 1e30)` above it — stateless by documented
design (E-13). But the handbook called it "exact in every analysis", and
above the knee that is false: a junction forced to x ≈ 193 converges
quietly to the linearisation, tens of decades below true exp. No silicon
operates there and every production simulator makes the same trade — but
the trade is real, so [§4.4](../docs/handbook/04-limitations-and-gotchas.md)
now states the knee, the tangent form, and the divergence, and two suite
checks measure the knee so the documentation cannot drift from the
implementation.
