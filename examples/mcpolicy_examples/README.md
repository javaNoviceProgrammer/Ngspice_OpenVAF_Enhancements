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

`verify_mcpolicy.py` (12 checks, both solvers) pins each behavior with
closed-form expectations computed from the same run's parameter readbacks —
`v(2) = 1k/(r+dr+1k)` against `@mm[r]`/`@n1[dr]` — plus the two
deterministic mcseed-7 montecarlo discriminators for the init-resident and
preserve legs. Two fixture models: `mcres.va` (statistics used directly in
eval) and `mchoist.va` (a statistic feeding only a hoisted assignment — the
model that exposed the ordering bug).
