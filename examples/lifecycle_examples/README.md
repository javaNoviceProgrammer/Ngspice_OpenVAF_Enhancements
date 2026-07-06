# Enhancement-81 — session-lifecycle + memory audit

Interactive ngspice workflows with OSDI devices, probed for correctness
and bounded memory — plus the two resource fixes this enhancement ships.

## What the audit found (all healthy)

- **Re-sourcing** the same deck is idempotent; `remcirc` + a new deck
  resolves cleanly to the new circuit.
- **The E-66 Monte-Carlo `reset` idiom is leak-free in practice**: 100
  reset+op iterations grow the ngspice program size by ~6 kB/iteration
  (bounded < 20 kB in the check) with the solution exact throughout.
- **Plots accumulate one per analysis** (the documented E-66 trap for
  big loops) and `destroy all` genuinely frees them — the numbering
  restarts at `tran1`.

## The two fixes

1. **`ft_ckspace` (the "approaching max data size" warning)** now honors
   the same `set no_mem_check` opt-out as the output-size estimate in
   `outitf.c`, and warns **once per excursion** above the 95% threshold
   (re-arming below 90%) instead of repeating on every check.
2. **The `pre_osdi` already-loaded note** (E-76) now tells you what to
   do about it: *"restart ngspice to load a recompiled file"*. The
   stale-model behavior it warns about is pinned by the suite:
   overwriting a loaded `.osdi` and re-loading the same path keeps the
   old model for the rest of the session — same effective behavior as
   the pre-E-76 silent shadowing, now with instructions.

## Files

`verify_lifecycle.py` (9 checks, self-contained decks), `lres.va` (the
minimal OSDI resistor the probes instantiate).
