# mcpolicy — the osdimc trial policy for loop commands, made honest

Regression suite for Enhancement-535. `.option osdimc` (E-530/531) draws a
fresh Monte-Carlo trial for every run-class command — which was right for a
lone `op` and wrong at both ends of the loop-command spectrum: a `sweep`
stitched N different samples into one "curve", `optimize` fit a stochastic
objective, and `montecarlo` — the one command that *wants* a fresh draw per
sample — got none, because its per-sample internal reset restarted the
sequence at the baseline. Three levers repair the policy:

* **HOLD** — a deterministic loop command (`sweep`'s per-point path,
  `optimize`, `wcd`, `loadpull`) brackets its inner analyses; the whole loop
  consumes exactly ONE trial;
* **PRESERVE** — a command's own internal reset keeps the trial sequence
  running, where a USER `reset` (or re-source) still restarts it at the
  baseline;
* **SCALE** — `highsigma -scale` inflates the attribute-declared sigmas along
  with the netlist ones for its sampling window.

The hunt round then proved the first cut wrong in four ways, all fixed and
pinned here:

* **draws must precede init-resident code** — a trial that could not be
  applied at run start (the nominal table is empty right after an internal
  re-source) is applied at the end of `OSDIsetup`, after defaults resolve and
  *before* `OSDItemp` runs the hoisted statements. The first cut applied it
  at the end of `OSDItemp`: a parameter feeding only `geff = 1/rr` was drawn
  in storage but **nominal in the physics** — every `montecarlo` sample
  computed the nominal while logging distinct draws;
* **machine writes pin** — a `sweep` point push, a `.dc` level write or a
  `sens` perturbation of a statistical parameter now wins over the trial's
  draw until the bracket ends. The first cut re-applied nominal+delta over
  them: `.dc @n1[dr]` returned one point three times and `sens` reported
  ~1e-14 where −2.5e-4 was the answer;
* **the baseline never draws, explicitly** — a `trial < 2` guard replaces
  the empty-table accident, which an `unset osdimc`/`set osdimc` toggle (or
  an optimizer's reset flow) defeated;
* **setup display prints per setup, monitor history resets per analysis** —
  a `.dc temp` sweep's init-resident `$strobe` prints at every point instead
  of once-then-dropped, and a new run's first `$monitor` line is never
  suppressed by the previous run's text.

Enhancement-536 then closed the ledger E-535 shipped, and those six repairs
are pinned here too:

* the hold is a **depth**, so a loop command nested as another's `-analysis`
  (an `optimize` over a swept-curve objective) no longer releases the outer
  bracket — it drew one fresh trial *per evaluation* before;
* `optimize`'s own internal resets **preserve** the sequence like `sweep`'s
  (a `-dparam` fit's objective changed mid-search; `-center` saw no osdimc
  variation at all), and `-center` **replays a trial window** per candidate
  so its yield objective samples variation yet stays deterministic;
* `highsigma -scale` **weights** the OSDI draws it inflates
  (`log λ − n²(λ²−1)/2` per gauss dimension) — P(fail) was the raw inflated
  fraction, 0.42 reported against a true 0.354;
* a `.dc` failure at a later nest level **restores** the earlier levels (a
  typo left `v1` parked at the sweep start), the clash guard also catches a
  wildcard covering a source's principal parameter, and the integer-refusal
  paths drop their target list;
* Ctrl-C **stops** a loop command instead of letting it march through every
  remaining point and report success;
* and an interrupt no longer leaks the hold, the sigma inflation, the
  sampling mode, `ft_optimizing` or the progress bar into the next command.

Enhancement-537 came out of a second hunt over that shipped work, and its ten
repairs are pinned here too — the headline being that `highsigma -scale`'s
importance weights **collapse as more statistical dimensions are inflated**
(twenty bystander devices that cannot affect the metric dragged a true
P(fail) of 0.297 to 2.5e-11), so the command now reports an effective sample
size and refuses to present a number it cannot stand behind. Alongside:
`highsigma`, `wcd`, `aging`, `emir` and `loadpull` no longer read results
back from a run that never solved; a mistyped `altermod` value refuses
instead of killing the session; `montecarlo N` draws N samples in every
session state; `-seed` varies the osdimc draws so replications are really
independent; `-lhs` says it does not cover them; a weighted P(fail) is
clamped into [0,1] with `n/a` rather than a misleading `0.000` at the
boundary; a never-varying metric is named instead of blamed on resolution;
aging's dose no longer recentres a statistical nominal; and a refused command
leaves its result variables unset rather than showing the last run's answer.

Enhancement-538 supplies the remedy E-537's guard was pointing at:
**`-inflate <param>`** names which statistical parameters `-scale` may
inflate, so the importance weight counts only the dimensions the failure
actually turns on. On the very deck that collapsed, `-inflate rr` takes the
reported P(fail) from 3.35e-05 to **0.2967** against a true 0.29670536 — and
reproduces bit for bit the answer from a deck that never had the bystander
devices, so they now cost exactly nothing.

Enhancement-544 adds checks 35–41: the **user's `alter`/`altermod` writes
survive the loop commands' internal resets**. Those resets are full
re-sources — `highsigma` and `wcd` on every evaluation, `montecarlo` whenever
the fast path cannot arm, which is this deck (no netlist random binding) —
and they discarded every altered value, statistical or not: `wcd` reported
β = 4.00 for a nominal the user had just moved 4σ, `highsigma` P(fail) =
2e-5 where the recentred nominal made it 0.5, and the `op` after
`montecarlo` read the un-altered circuit. The commands the user types are
now journaled (value already evaluated, one entry per target) and replayed
after each internal reset, as E-501 replays the aging doses; a user-typed
`reset` forgets them; `optimize` journals its final optimum. The checks read
the `osdimc_verbose` nominals across `montecarlo`, the value `unset osdimc`
restores, a plain netlist `alter`, `wcd`'s β against the closed-form 1.03σ
from the recentred (1100, 0), `highsigma`'s P(r > 1100) = 0.5, the
user-`reset` case, and an optimum carried through a `montecarlo`.

The 2026-09-05 hunt's F13 adds checks 42–46: **a loop command's `-seed`
pins the model-declared draws**. E-537 mixed the seed into the draw key but
left the session-wide trial counter in it, so `montecarlo 3 -seed 1` run
twice reproduced the netlist `agauss` values and not the `@mm[r]` draws, a
seeded `highsigma` gave a different estimate before and after a `reset`,
and the published `montecarlo_seed` could not regenerate an ensemble. Inside
`montecarlo`, `highsigma` and `wcd` the key now carries `(-seed, sample
number counted from the command's start)`, the seed defaulting to 1 as the
netlist half's always has — so an unseeded run repeats itself whole and
equals `-seed 1`, the `osdimc_verbose` line shows `[sample 2 of -seed 1]`,
and a never-run deck on `montecarlo`'s fast path draws on its first sample
(the first run's new circuit pointer used to restart the count at the
baseline). The plain run after a loop command is a fresh trial as before.

`verify_mcpolicy.py` (46 checks, both solvers) pins each behavior with
closed-form expectations computed from the same run's parameter readbacks —
`v(2) = 1k/(r+dr+1k)` against `@mm[r]`/`@n1[dr]` — plus the deterministic
mcseed-7 montecarlo discriminators for the init-resident and preserve legs,
trial-number traces from `osdimc_verbose` for the hold/preserve policy, and
a seeded 1000-sample high-sigma run checked against the closed-form
P(fail) = 0.2967 its single statistical dimension implies. Two fixture
models: `mcres.va` (statistics used directly in eval) and `mchoist.va` (a
statistic feeding only a hoisted assignment — the model that exposed the
ordering bug).
