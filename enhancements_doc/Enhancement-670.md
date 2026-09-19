# Enhancement-670: the later spelling of an option pair wins — `noautocorner` turns `autocorner` off, `noosdimc` turns `osdimc` off, on one card, across cards and from the control block

**Scope:** F17 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/frontend/variable.c` (`cp_off_pairs`, `cp_off_partners`, the
rule in `cp_vset`), `src/frontend/inp.c` (`inp_opt_pair_prune`, the option
cards in card order), `src/include/ngspice/cpextern.h`.
`examples/autoopts_examples/` (eight checks added, 35 per solver);
`examples/savemc_examples/` (one check reordered). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). **ngspice only.**

**Suites:** [`autoopts_examples`](../examples/autoopts_examples/) 35 of 35
per solver, both solvers (6 of the 8 new checks fail on the E-666 binaries);
`saveused`, `osdimc`, `autoadapt`, `autobus`, `dcpath`, `reusesetup`,
`savemc`, `autocorner`, `vacorner`, `cornerscmd`, `mcyield` unchanged; full
sweep 530 of 530.

## What was wrong

[E-572](Enhancement-572.md) registered the documented `no` spellings of the
front-end options so they draw no *unknown option* warning, on the rule that
a setting the run honours must not be flagged. Some readers judge the option
cards themselves, later card winning ([E-454](Enhancement-454.md)'s
`saveused`, `autobus`, `autoadapt`); the others read the positive alone
through `cp_getvar`. For those the `no` spelling was known and turned
nothing off — accepted and ignored, the failure E-445's note describes:

| deck | before |
|---|---|
| `.option autocorner noautocorner` | both set, the loop runs |
| `.option autocorner` then `set noautocorner` in the control block | the loop runs |
| `.option osdimc noosdimc`; `.option osdimc` then `set noosdimc` | trial 2 draws |

`.option noautocorner` alone was quiet because nothing was on; only `unset
autocorner` turned the option off.

## What changed

**The later spelling of an option pair wins.** A table in `variable.c` holds
the registered pairs — `autocorner`/`noautocorner`; `osdimc`, `automc` /
`noosdimc`, `noautomc`; `saveused`/`nosaveused`; `autobus`/`noautobus`;
`autoadapt`/`noautoadapt`; `osdicache`/`noosdicache`; `dcpath`, `dcpathall` /
`nodcpath`; `savemc`, `automc_save`, `osdimc_save` / `nosavemc`;
`reusesetup`/`noreusesetup` — and `cp_off_partners(name)` answers the other
side. Setting one spelling removes the other:

- in the control block, `cp_vset` removes the partners first (`cp_remvar`
  searches the circuit's own list too, where a deck's option cards put
  theirs), so `set noautocorner` takes `autocorner` away and `set autocorner`
  takes `noautocorner` back;
- on the option cards, `inp.c` builds the circuit's variables card by card
  and prunes, for each word, the partners further down the card (its earlier
  words — the parsed list runs last word first) and every partner an earlier
  card set. One card, two cards, either order: the later spelling stands.

The readers are untouched: a reader of the positive finds it gone. The
readers that judge the cards themselves already followed the same rule, so
the two agree. `unset` still works; a `no` spelling alone is quiet as before.
The `savemc` suite's four-spelling card is reordered so its `nosavemc` is
last, which is now what turning the recorder off on that card means.

## Verification

| check | result |
|---|---|
| `.option autocorner noautocorner`; `op` | no loop, `$?autocorner` 0, `$?noautocorner` 1 |
| `.option noautocorner autocorner` | the loop runs, `$?autocorner` 1 |
| `.option autocorner` + `.option noautocorner`, and the reverse | off; on |
| `.option autocorner`; `set noautocorner`; `op`; `set autocorner`; `op` | the first `op` plain, the second loops |
| `.option autocorner`; `unset autocorner`; `op` | plain |
| `.option automc noosdimc mcseed=7`; two `op`; and `.option osdimc` with `set noosdimc` | `@rm[r]` 1000 on trial 2, `$?osdimc` and `$?automc` 0 |
| `.option osdimc savemc=file nosavemc` | `$?savemc` 0, no file |
| the E-666 binaries on the suite | 6 of the 8 new checks fail (the compile and the `unset` checks pass there) |

Full sweep 530 of 530 on both solvers.

## What this does not do

- A value spelling (`osdimc=0`, `automc=no`, `saveused=off`) is its reader's
  business, as before; it is a positive for the pair rule and removes a `no`
  spelling that came earlier.
- Options outside the table (`noloopbar`, `noosdilim`, `nobreak`, …) are
  variables of their own with no positive counterpart, and are left alone.
