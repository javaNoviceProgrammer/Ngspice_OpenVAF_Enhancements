# Enhancement-81 — session-lifecycle + memory audit: two resource fixes

This document describes Enhancement-81: an audit of **interactive ngspice
workflows with OSDI devices** — re-sourcing, circuit removal, long
reset/alter loops, plot management — probed for correctness and bounded
memory, plus two quality-of-life fixes in the resource machinery that the
user's "approaching max data size" question motivated.

## The audit (all healthy)

- **Re-sourcing** the same deck is idempotent (identical currents), and
  `remcirc` + a new deck resolves cleanly to the new circuit — the OSDI
  registry (E-76's loud, deduplicated version) composes with circuit
  reloads.
- **The E-66 Monte-Carlo `reset` idiom is leak-free in practice**: 100
  reset+op iterations grow the ngspice program size by **~6 kB per
  iteration** (pinned < 20 kB) with the solution exact throughout — the
  OSDI setup/teardown cycle does not accumulate instance state.
- **Plot accumulation behaves as documented** (one plot per analysis —
  the E-66 trap for big loops) and `destroy all` genuinely frees the
  memory: the plot numbering restarts at `tran1`.

## Fix 1: the "approaching max data size" warning (`resource.c`)

`ft_ckspace()` warns when the process RSS exceeds 95% of (RSS + free
RAM). Two behaviors improved:

- it now honors **`set no_mem_check`** — the same opt-out the fatal
  output-size estimate in `outitf.c` already respects, so one variable
  governs both memory guards;
- it warns **once per excursion** above the threshold (re-arming only
  after usage drops clearly below 90%) instead of repeating on every
  check through a long analysis.

The warning itself requires ~95% RAM pressure and is deliberately not
triggered by the bounded verify suite; the opt-out path is exercised and
the latch logic is single-page code review.

## Fix 2: the `pre_osdi` reload note gets instructions (`dev.c`)

E-76's already-loaded note now reads: *"already loaded; skipping
(restart ngspice to load a recompiled file)"*. The suite pins the
behavior it warns about: overwriting a loaded `.osdi` and re-issuing
`pre_osdi` on the same path keeps the **old** model for the rest of the
session — the same effective behavior as pre-E-76 (where the duplicate
registration was silently shadowed by the first), but now with the
remedy stated.

## Examples (`lifecycle_examples/`, 9 checks, ALL PASS)

`verify_lifecycle.py` (self-contained decks) + `lres.va`. Checks: the
re-source identity, remcirc/new-deck resolution, the 100-reset exactness
and memory bound, plot accumulation + `destroy all`, the reload note's
hint + the pinned stale-model behavior, and normal simulation under
`no_mem_check`.

## Regression

ngspice rebuilt warning-free (dev.c + resource.c); all 72 example verify
suites pass, the integration suite 28/28, corpus 92/92 (compiler
unchanged).
