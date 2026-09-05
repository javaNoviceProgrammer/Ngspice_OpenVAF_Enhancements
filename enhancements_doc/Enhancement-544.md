# Enhancement-544: the user's `alter`/`altermod` writes survive the loop commands' internal resets

**Scope:** finding F3 of the ngspice + OSDI hunt
([`docs/bug_hunts/2026-09-04_osdi-workflows-and-fresh-code.md`](../docs/bug_hunts/2026-09-04_osdi-workflows-and-fresh-code.md)),
which also records F14 — `set temp` dropped by every reset — as pre-existing
and unfixed. **ngspice only; the compiler is unchanged.**

**Suites:** [`mcpolicy_examples`](../examples/mcpolicy_examples/) 34 → 41
(the `highsigma` fixture now uses `-scale 1.5`, since a scale must exceed 1);
twenty related suites green on both solvers.

## What was wrong

The sampling commands redraw a deck's random `.param` values with an
*internal reset* — a full re-source of the circuit — on `highsigma` and `wcd`
at every evaluation, and on `montecarlo` whenever Enhancement-346's fast path
cannot arm, which is every deck whose only variability is model-declared. The
re-source rebuilt the circuit from the deck, so every `alter` and `altermod`
the user had typed beforehand was discarded, statistical or not:

| what the user did | what the command reported |
|---|---|
| moved a nominal 4 σ with `altermod`, then `wcd` | β = 4.00, as if the nominal had not moved |
| recentred a nominal so that P(fail) is 0.35, then `highsigma` | P(fail) = 2 × 10⁻⁵, the deck's value |
| `alter r1 resistance=2k`, then `montecarlo`, then `op` | the operating point of the un-altered circuit |

The hunt's first claim that plain alters survived was itself wrong — it had
been observed on the fast path, which never re-sources — and the finding was
broadened accordingly.

## What changed

* **A journal of the user's writes.** `alter` and `altermod` are recorded at
  the command dispatcher (`control.c`), so only commands the *user* typed
  are journaled; the optimizer's, `sweep`'s, `temper`'s and `aging`'s own
  writes stay out. Each entry is keyed by target (`i:`/`m:` plus the
  lower-cased left-hand side), so a later write to the same parameter
  replaces the earlier one, and the value is stored as it was *evaluated* —
  `%.17g` for a scalar, `[ … ]` for a vector — so a write that named a
  `.param` or an expression replays exactly.
* **Replayed after every internal reset**, beside Enhancement-501's aging
  replay, in `sweep`, `montecarlo`, `highsigma`, `wcd` and the optimizer,
  under `ft_optimizing` so the replay is not journaled again; a circuit-title
  check keeps a journal from being replayed into a different deck.
* **Forgotten on a user `reset`**, together with the aging writes.
* **The optimizer journals its optimum**: `optimize`'s final `opt_eval` is
  armed so that the parameters it settles on survive the next loop command.
* `ft_set_writes` counts successful `set` calls, for the tests.

## Verification

| check | result |
|---|---|
| `altermod` of a nominal, then `wcd` | β follows the moved nominal |
| recentred nominal, then `highsigma` | P(fail) ≈ 0.35 (was 2 × 10⁻⁵) |
| `alter` + `montecarlo` + `op` | reads the altered value, 2000 Ω |
| a journaled write replaced by a later one to the same target | one entry, the later value |
| `reset` typed by the user | the journal is empty |
| `mcpolicy_examples` | 41 / 41, both solvers |
