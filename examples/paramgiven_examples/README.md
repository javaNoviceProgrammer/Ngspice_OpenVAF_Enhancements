# paramgiven_examples — givenness survives machine writes; a default is judged against a moved bound (Enhancement-555)

```
python3 verify_paramgiven.py
```

16 checks, both solvers; compiles its own models, the bundled BSIM4 among
them, with `openvaf-r` (and one with the prebuilt compiler, for the
old-object case).

## The need

F1 and F2 of the bug hunt of 2026-09-05.

The descriptor's `access()` marks a parameter **given** on every write. An
`.option osdimc` draw, and the restore after a `.dc` or `sweep` of the
parameter, went through it, so a parameter the deck never gave came out
given — and a model that picks a default with `$param_given` (BSIM4:
`toxp = toxe − dtox` when `toxp` is not given) ran its "given" branch at the
declared default from trial 2 on, and after any sweep. A 0.003 % sigma on
`toxp` cost 32 % of the drain current, and every member of the recorded
ensemble sat 32 % from the design point. The built-in BSIM4 was unchanged
under the same sweep: it puts its given flags back, OSDI had no way to.

And the compiled setup judged a parameter's range only when the parameter
was given: `l = 1.2 from [lmin:inf)` with `lmin` altered, swept or drawn to
1.5 ran with `l` below its bound, silently.

## What changed

| where | what |
|---|---|
| compiler | the OSDI side-table flags a statistical parameter the module tests with `$param_given` (`OSDI_DIST_GATED`), and every object exports a per-descriptor given-flag entry point, `OSDI_PARAM_GIVEN_FNS` (read, set, clear); the descriptor ABI is unchanged, an older object simply lacks the symbol |
| compiler | a default whose `from`/`exclude` bounds read another parameter is judged at setup, given or not; a constant default outside a constant range keeps the E-56 exemption (lint L027 at compile time) |
| ngspice | `osdimc` draws a gated parameter only when the deck gave it, and says so once: *`mm:toxp` is not given by the deck and the model tests `$param_given(toxp)`: a draw would switch the model … not drawn. Give it on the card, or altermod it, to vary it.* A gated, not-given parameter is no dimension of the `wcd` walk and no factor of the `highsigma` weight |
| ngspice | the restore after a `.dc` (instance and model targets), after the `sweep` command, and after `unset osdimc` clears the given flag of a parameter the deck never gave |

Where it lives: `param_given_tests` in `openvaf/hir/src/body.rs`,
`module_given_tests` and `dynamic_bounds` in
`openvaf/sim_back/src/module_info.rs`, the `check_default` list in
`openvaf/hir_lower/src/parameters.rs`, the entry point in
`openvaf/osdi/src/given.rs`; `OSDIparamGiven` / `OSDIparamGivenByName` and
the gated skip in `ngspice-46/src/osdi/osdisetup.c`, the restores in
`spicelib/analysis/dctrcurv.c` and `frontend/com_sweep.c`.
