# Enhancement-534: `.dc` learns the rest of the parameter surface — model knobs, wildcards, subcircuits, and lin/dec/oct scales

**Scope:** the sweep variables the `sweep`/`altermod` family established now
have a native dc arm. `.dc` (card and command alike) sweeps **model
parameters** — `@mod[p]`, with the dotted subcircuit spelling `@x1.rmod[p]`
resolved through the same E-433 hierarchy funnel the rest of the tooling
uses — and the **wildcard families**: `@*[p]` (every model with `p`),
`@#*[p]` / `@*[[p]]` (every instance with `p`), `@*:leaf[p]` / `@*.leaf[p]`
(every model named `leaf`, wherever expansion put it). And every knob kind,
old and new, takes the **keyword scales** `lin|dec|oct N start stop`,
generating exactly the point sets the `sweep` command generates — nesting
included, in any combination with the classic triple. The E-533 sweep→dc
handover widens to match: model knobs, wildcards, and log-spaced grids now
hand over too (measured on the 1000-device Monte-Carlo ladder: a 2000-point
model-parameter sweep drops from 3.4 s per-point to 0.6 s).

**Suites:** [`examples/dcxsweep_examples/`](../examples/dcxsweep_examples/)
(new, 20 checks, both solvers) pins every spelling on closed-form circuits;
[`examples/sweepdc_examples/`](../examples/sweepdc_examples/) grows to 17,
its ineligible-spelling pins re-pointed at what still has no dc arm. Full
sweep **448/448** ALL OK.

## One type code, the machine-write path

The new kinds resolve once, into a target list on the sweep job — each entry
a device or model card plus its settable parameter id, captured nominal, and
value type — and every point writes the whole list through the DEV tables
directly (`DEVparam`/`DEVmodParam`), then runs **one `CKTtemp`** however many
targets moved. The frontend's own wildcard setters were deliberately *not*
reused for the per-point writes: they run `doset_user()`, which is `alter`'s
recentering hook for `.option osdimc` statistical parameters — and E-531
established that sweeps are machine writes and must never recenter a
nominal — and they `controlled_exit()` on a `CKTtemp` error, which would turn
one refused sweep point into a dead process. The matching rules are mirrored
instead (the same wildcard grammar, the same model-leaf convention, the same
`if_find_model_hier` funnel), so `.dc` targets exactly what `altermod`
targets. Every knob returns to its captured nominal afterwards, unchecked,
through the same restore path the E-62 instance sweep uses.

The E-495 collapse guard arms on every new kind: a model parameter that
moves an OSDI node collapse refuses the point with the message naming
`sweep` as the correct instrument — and the widened handover falls back to
its per-point loop on exactly that refusal, so `sweep @mm[rd] ...` is fast
when topology holds still and correct when it does not. **Built-in devices
get the complementary static guard**: they decide their topology in
`DEVsetup`, which a running dc cannot re-run, so a swept parameter that
builds internal nodes there — BJT `rc`/`rb`/`re`/`rco`, diode `rs`/`tt`, the
MOS `rd`/`rs`/`rsh`/`nrd`/`nrs` family — is refused at resolution, judged by
the very E-471/E-503 tables the setup-reuse gate reads (exported as
`CKTbuiltinTopologyParamRisk`); a safe parameter of the same device (`bf`)
sweeps freely. The reusesetup suite's own [14b] check is what caught the
hole, one full-sweep round before it could ship.

## The scales

`dc V1 lin 5 0 1`, `dc @dm[is] dec 3 1e-15 1e-12`, `dc temp oct 2 25 100` —
parsed on the card by a per-level reader (the classic triple is untouched
byte-for-byte), stored as a counted walk: `lin` interpolates
`start + span·k/(N−1)` so both endpoints are exact, `dec`/`oct` multiply
iteratively by `10^(1/N)` / `2^(1/N)` up to `stop·(1+1e-9)` — the sweep
command's own generator, bit-for-bit. Counted levels terminate by index, so
a descending `lin` works where the legacy overshoot test would have refused
it, and they compose freely with legacy levels in a nest. Integer parameters
refuse the fractional generators outright (a published abscissa the device
never saw is E-427's lie) and keep the whole-number rule on the classic
triple.

Two repairs fell out of the plumbing. The wildcard spellings could not even
be *tokenized* on a card — the parser's token grammar breaks at `*`, right
for expressions and wrong for these names — so an `@`-led sweep-variable
name is now read verbatim to whitespace, changing no legacy spelling by a
byte. And the parameter-sweep **overshoot slack was absolute**
(`1e3·DBL_EPSILON`): a saturation current swept to 5e-14 sat below the slack
the whole way, so `dc @dm[is] 1e-14 5e-14 1e-14` ran on to 2.7e-13 — five
times past stop, publishing rows nobody asked for — latent in E-62 since
tiny parameters became sweepable. The slack now scales with the sweep's own
magnitudes and is bit-identical to the old constant at classic volt/ohm
scales.

## What deliberately did not change

The classic `start stop step` triple parses and walks exactly as before;
`dc temp` semantics are untouched (including its known-open collapse
limitation, still pinned by `sweeptemp` — the handover still declines
temp+OSDI decks); a concrete `@mod[p]` targets the top-level card only, with
the `@*:leaf[p]` wildcard as the every-copy instrument, matching `altermod`'s
documented behavior; and `.param` symbols still have no dc arm (they need a
re-source, which is `sweep`'s job).
