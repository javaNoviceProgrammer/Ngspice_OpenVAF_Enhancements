# Proposal — a `.statistics` block with Spectre's `process` / `mismatch` / `vary`

*Scoped 2026-10-06, after the question "is it possible to add a vary block similar to what
Spectre has for Monte Carlo simulations?" Nothing here is implemented. The tree as it stands
is E-795 (14ab4f3b). Two pieces of the existing tree carry most of the weight:

- the model-declared statistics engine, `.option osdimc`
  ([E-530](../../enhancements_doc/Enhancement-530.md), with the lognormal and truncation of
  [E-554](../../enhancements_doc/Enhancement-554.md), the `$param_given` gate of
  [E-555](../../enhancements_doc/Enhancement-555.md), the loop-command seeding of
  [E-537](../../enhancements_doc/Enhancement-537.md) and the corners of
  [E-654](../../enhancements_doc/Enhancement-654.md));
- the `.param` fast path of [E-320](../../enhancements_doc/Enhancement-320.md) to
  [E-322](../../enhancements_doc/Enhancement-322.md).

The correlation half builds on the unimplemented
[correlated-statistics proposal of 2026-09-06](2026-09-06_correlated-statistics-for-osdimc.md).*

## The question

Spectre decks carry their variability in a netlist block:

```
statistics {
    process {
        vary rsh   dist=gauss std=5 percent=yes
        vary dtox  dist=gauss std=0.1n
    }
    mismatch {
        vary dvth  dist=gauss std=3m
    }
    correlate param=[rsh dtox] cc=0.6
    truncate tr=3
}
```

`process` variations are drawn once per Monte Carlo iteration and shared by the whole
circuit. `mismatch` variations are drawn again for every subcircuit instance that reads the
parameter. A PDK ships its statistics this way, separate from its model cards, and a
designer adds or tightens a `vary` without touching a model.

In Spectre, `vary` names **netlist parameters** (those of a `parameters` statement). The
model cards read those parameters. It does not name a model's or an instance's parameter
directly.

How do we give ngspice the same?

## What exists, and what it lacks

**Statistics in the Verilog-A source** (E-530). `(* std=…, std_rel=…, dist=…, trunc=… *)`
on a parameter declares its distribution. Under `.option osdimc` (alias `automc`) the
simulator draws it at every run:

- a model parameter once per model card per trial, which is process variation;
- an `(* type="instance" *)` parameter once per instance, which is mismatch.

Distributions are gauss, uniform (`std` = half-width), lognormal and truncated gauss.
Draws are pure functions of (seed, trial, owner, parameter id), and they work with:
- `montecarlo`, including `-lhs`;
- `highsigma` (importance weights per parameter);
- `wcd` (one walk coordinate per parameter);
- `savemc` and `writemc`;
- corners in sigma units.

The statistics are read from the compiled object when ngspice loads it:
`osdiregistry.c` builds one `OsdiStatParam` table per module (`stat_param_infos`), and
`osdisetup.c` reads it in:
- `osdimc_capture` (the nominals);
- `osdimc_stat_of` (one parameter's record, which the walk and the importance weight go
  through);
- `OSDImcHasStats` and `OSDImcSnapshot` (what `savemc` records);
- `OSDImcNewRun` and `osdimc_apply_type` (the draws).

**Lacks:**
- The statistics are in the model's source. A CMC model, a foundry's Verilog-A or anything
  the user does not own cannot be given statistics without editing and recompiling it.
- They are per module, not per model card. An `nch` and a `pch` card of one module cannot
  have different sigmas.
- The engine covers OSDI devices only.
- Its draws cannot be correlated; that is the 2026-09-06 proposal.

**Statistics in the netlist** (base ngspice, [E-151](../../enhancements_doc/Enhancement-151.md),
[E-346](../../enhancements_doc/Enhancement-346.md)). `agauss`, `gauss`, `aunif`, `unif` and
`limit` in a `.param`, with `mccorr` and `mvnorm(i)` for correlation, `montecarlo`'s fast
path to push a redraw into the live circuit, and `-lhs`.

**Lacks:**
- The variation has to be written into the expressions. The card must read the `.param`, and
  the nominal and the spread share one expression.
- Mismatch means one hand-written `.param` per device (`vth1`, `vth2`, …), or `agauss`
  inside a subcircuit's own parameters.
- Process and mismatch cannot be told apart at run time: `montecarlo` has no "process only".
- A PDK's Spectre statistics have to be rewritten into expressions by hand.

## The design

### The block

A dot-card block, like `.control` … `.endc`. Its body takes Spectre's statistics syntax
nearly verbatim, so a PDK's `statistics { … }` section can be pasted in:

```spice
.statistics
process {
    vary rsh          dist=gauss std=5 percent=yes   ; a .param
    vary @nch[tox]    dist=gauss std=0.1n            ; a model card's parameter
    vary @nch*[vth0]  dist=gauss std=10m             ; every card matching nch*
}
mismatch {
    vary @nch[dvth]   dist=gauss std=3m              ; an instance parameter, per device
    vary @m7[dvth]    dist=gauss std=6m              ; one device, its own sigma
}
correlate param=[rsh @nch[tox]] cc=0.6
truncate tr=3
.endstatistics
```

- The outer `statistics { }` is optional, so a block copied with it also reads.
- Comments are ngspice's (`;` and `*`) and Spectre's (`//`).
- The block is cut out of the deck before `numparam` sees it, like `.control`, and parsed
  into one table. Diagnostics name the deck line.
- A deck may hold several blocks; they merge, and a target named twice in one scope is an
  error.

Only the statistics subset is read. A whole Spectre PDK file (`simulator lang=spectre`,
`parameters`, `model`, `section`) is not.

### Targets

| written | means | process | mismatch |
|---|---|---|---|
| `name` | a `.param` | one draw per trial for the whole circuit | one draw per subcircuit instance that reads it (Spectre's mismatch) — phase 3 |
| `@card[p]`, `@card*[p]` | parameter `p` of a model card (wildcards as `altermod` takes them) | a **model** parameter: one draw per card per trial, as E-530 | an **instance** parameter of that card's devices: one draw per device, as E-530's `type="instance"`. A *model* parameter here is the open question below |
| `@inst[p]` | parameter `p` of one instance | one draw per trial for that instance | the same (one instance is one owner) |

The `@…[…]` spellings are the ones `alter`, `altermod` and `print` already read.

Going further than Spectre and naming device parameters directly is deliberate: an ngspice
deck seldom routes its cards through `.param`s, and a compiled model's parameters are
exactly where E-530's engine already works.

### Distributions

Each `vary` becomes one `OsdiStatParam`-shaped record, plus the scope:

| Spectre option | the engine |
|---|---|
| `dist=gauss std=s` | gauss, `std` = s |
| `percent=yes` | `std_rel` = s / 100 |
| `dist=lnorm` | E-554's lognormal |
| `dist=unif` | E-530's uniform, with the half-width converted from Spectre's `std` (see below) |
| `truncate tr=n` | `trunc` = n on every Gaussian `vary` that does not set its own |
| a per-`vary` `trunc=n` (an extension) | `trunc` = n |

Two semantics must be confirmed against the Spectre reference before any code:

- **`std` of a uniform.** If Spectre's `std` is the standard deviation (the range then being
  ±√3·std), it differs from E-530's half-width, and the block converts.
- **`lnorm`.** Whether `std` is the sigma of the natural logarithm, and whether `percent`
  applies to it.

Spectre's other `vary` and `truncate` options are refused by name, not ignored.

### Where the entries live, and determinism

The netlist table is an **overlay per model card** on the module's `OsdiStatParam` table:
- `osdimc_card_stats(entry, gen_model)` returns the effective statistics of one card: the
  module's, with the card's `vary` entries replacing or adding records.
- The readers listed above call it instead of reading `entry->stat_param_infos`. All of them
  loop over the cards except `osdimc_stat_of`, which takes the module and a parameter id and
  gains the card as an argument.

A card without a `vary` reads the module table unchanged, so every deck without a
`.statistics` block draws **bit-for-bit what it draws now**. The E-530 to E-658 suites pin
that.

The draw key stays (seed, trial, owner, parameter id). So a parameter given `std=25` in the
Verilog-A source and the same `std=25` in a `vary` draws the same values: where the
statistics were declared does not change the samples.

**Precedence:**
- A `vary` on a parameter the source already declares replaces the whole record
  (distribution, sigma, truncation), and the simulator says so once per parameter.
- Corners stay the model's. A `+3sigma` corner (E-654) is measured with the effective
  sigma, the `vary`'s when there is one, and the corners note says which.

**Activation** is E-530's:
- every run under `.option osdimc`;
- every sample of `montecarlo`, `highsigma` and `wcd`;
- otherwise nothing.

One new `montecarlo` / `highsigma` option, `-variations process|mismatch|all`, matching
Spectre's `variations=`, draws only one scope. `all` is the default. E-538's scope machinery
(`OSDImcScaleScopeAdd`) is the filter it reuses.

`savemc` and `writemc` record a varied parameter as they record one declared in the source.
Its column gets the netlist's name for it.

### `.param` targets

**Process scope** (phase 2). A drawn value is pushed through the E-320/E-321 fast path: it
re-evaluates the device values that depend on the `.param` and writes them into the live
circuit, the path `sweep` and `optimize -dparam` already use. Where the fast path refuses
(a `.param` that changes the topology, a subcircuit count), the trial falls back to
`montecarlo`'s re-source path, as an `agauss` does today.

The nominal is the `.param`'s value as written. A `.param` that already calls `agauss` is
refused as a `vary` target: two spreads on one value is a mistake either way.

**Mismatch scope** (phase 3). This is Spectre's real mismatch: one value per subcircuit
instance that reads the parameter. ngspice fixes a subcircuit's expressions when it expands
the subcircuit, so a `.param` named in `mismatch { }` is **renamed per instance during
expansion**:
- each `X` instance's references to it become a private `.param` (`dvth@x1.x3`);
- the private `.param` has the same nominal and an owner key of that instance path;
- every private copy then draws like a process-scope `.param` with its own key.

Instances outside any subcircuit share the top-level value, as in Spectre.

This is the largest piece. It touches `numparam`'s expansion (`inpcom.c`, `subckt.c`) and
grows the fast path's dependency table by the number of instances.

### Correlation

`correlate param=[a b …] cc=r` is the 2026-09-06 proposal's latent-factor model, declared
from the netlist instead of the source:
- each `correlate` becomes a model-scoped factor (or a `global.` one, when its members
  belong to different cards or are `.param`s), with loadings from a Cholesky of the declared
  matrix;
- a matrix that is not positive definite is refused, naming the pair.

`highsigma` then weights per latent, and `wcd` walks the latents, exactly as that proposal
specifies. Until it lands, a `correlate` in the block is refused with a pointer to `mccorr`.
It is not ignored.

Spectre's `correlate dev=[…]` (instance-to-instance mismatch correlation) maps to an
instance-scoped factor, and comes with the same step.

### Built-in devices

A `vary` on a built-in device's parameter (`@r1[r]`, a card of ngspice's own BSIM4) needs
the engine to capture, draw and restore through the generic `IFparam` setters, the path
`alter` and `altermod` use, rather than through the OSDI `access()` function. Phase 4.

Until then such a target is refused, with the reason and the `agauss` spelling that does
the same.

### Diagnostics

- Errors:
  - a target that does not exist: no such `.param`, card, instance or parameter, with a
    near-miss suggestion;
  - a parameter that is not real;
  - `std` negative;
  - an option the block does not take;
  - a target named twice in one scope;
  - a model parameter in `mismatch { }` (until the open question below is settled).
- Warnings: `std` = 0, and `percent=yes` on a nominal of 0 (the E-620 rules).
- E-555 applies unchanged: a `$param_given`-tested parameter the deck never gave is not
  drawn, said once.
- A draw outside the parameter's `from` range fails the trial with the device's own range
  error, as today.

## Phases

| phase | scope | where | size |
|---|---|---|---|
| 1 | the block, its parser and diagnostics; OSDI model and instance parameters by card and by instance; the per-card overlay; precedence; `-variations` | `frontend/inpcom.c` (cut the block out), a new `frontend/statistics.c` (parse, resolve, the table), `osdi/osdisetup.c` (`osdimc_card_stats` and the table's readers), `frontend/com_sweep.c` (`-variations`), `frontend/mcsave.c` (column names) | one enhancement; the compiler is not touched |
| 2 | `.param` targets, process scope, through the fast path | `frontend/statistics.c`, the E-320 fast-path engine | one enhancement |
| 3 | `.param` targets, mismatch scope (per-instance renaming at expansion) | `frontend/inpcom.c`, `frontend/subckt.c`, the fast path | one enhancement, the largest |
| 4 | built-in device parameters | the capture, draw and restore via `IFparam` | one enhancement |
| — | `correlate` (both forms) | with the 2026-09-06 correlation proposal: compiler side tables for the source spelling, the netlist block for this one, one sampler | one or two enhancements |

Phase 1 alone answers the question for compiled models, which is where this tree's users
live. Each later phase is independent of the next.

## Verification to pin (a new suite)

- **Statistics of the draws.** Over a couple of thousand trials, the sample mean and sigma
  of each target match the `vary`: gauss, `percent`, lognormal (never negative), uniform
  (bounds per the confirmed semantics), and `truncate` (none beyond n·σ).
- **Scopes.**
  - Process draws are identical for all devices of a card; mismatch draws differ per
    device.
  - An `@inst` override takes its own sigma.
  - `-variations process` leaves mismatch at nominal, and the reverse.
- **Determinism.**
  - A deck without the block draws byte-identical values before and after (the E-530 to
    E-658 suites unchanged).
  - A `vary` equal to a source attribute draws the same values as the attribute.
  - Seed reproducibility.
- **Precedence.** A `vary` replaces a source declaration, and the note is printed once.
- **Integration.** `montecarlo` (with `-lhs`), `highsigma` (weights; a failure probability
  agreeing with plain Monte Carlo), `wcd` (β for a single varied parameter equal to the
  analytic value), `savemc` columns, a sigma corner using the `vary`'s sigma.
- **Refusals.** Each diagnostic above, with its deck line.
- **Phase 3.** Two instances of a subcircuit reading a mismatch `.param` get different
  values, and a top-level reader keeps the shared one.

## Decisions for you

1. **Mismatch on a model parameter.** All devices on a card share its model parameters.
   Two options:
   - **refuse** it, and point to an instance parameter (most compiled models have
     `(* type="instance" *)` deltas, and CMC models expose per-device mismatch that way);
   - **split the card** per device, with a private copy of the model per instance, so each
     draws its own. That costs memory and setup time per device, and is what Spectre
     effectively does for a card inside a subcircuit.

   Suggested: refuse in phase 1, and revisit if a model needs it.
2. **Syntax.** Spectre's braces inside `.statistics` (copy-paste from a PDK), or an
   ngspice-style card form (`.vary @nch[tox] process gauss 0.1n`)? Suggested: the Spectre
   body, with no second spelling.
3. **Naming device parameters directly** (`@card[p]`, `@inst[p]`) as well as `.param`s:
   Spectre names only the latter. Suggested: both.
4. **When the block is in force.** Exactly as `(* std *)` statistics: under
   `.option osdimc` and inside the loop commands. The alternative is a block that turns
   `osdimc` on by itself. Suggested: as `(* std *)`, so a deck with a `.statistics` block
   still runs its nominal unless asked.
5. **Order.** Phase 1, then 2. Phase 3 (Spectre's real mismatch on `.param`s) when a PDK
   needs it. Correlation with the 2026-09-06 proposal, either before phase 2 or after it.
