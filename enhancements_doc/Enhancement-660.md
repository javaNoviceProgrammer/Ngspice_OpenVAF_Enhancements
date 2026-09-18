# Enhancement-660: a hoisted display or severity task prints once per analysis, after the draws and the corner — the setup pass's output is superseded by the temperature pass's

**Scope:** F16 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/osdi/osdicallbacks.c` (the setup pass's messages held and
superseded; `osdi_display_setup_failed`), `src/osdi/osdidefs.h`,
`src/osdi/osdisetup.c` (the release on a failed setup). `examples/display_examples/`
(`display_setup.va` and six checks, 30 in all). Handbook
[§2.11](../docs/handbook/02-verilog-a-language.md) row. **ngspice only**; the
compiler is untouched, deliberately (below).

**Suites:** [`display_examples`](../examples/display_examples/) 30 of 30 per
solver, both solvers (five of the six new checks fail on the E-659 binaries);
`lrmsysio`, `lrmvoice`, `carddefault`, `dropguard`, `mcpolicy`, `scanbody`,
`simctrl`, `osdimc` unchanged; full sweep 529 of 529.

## What was wrong

```
analog begin $strobe("S"); I(p,n) <+ V(p,n)*1e-3; end      -> op: 2 lines; tran of 79 points: 2 lines
analog begin $strobe("S v=%g", V(p,n)); ... end            -> op: 1 line;  tran: 79 lines
```

A display or severity task whose arguments depend on nothing the solver
computes — a constant, a variable computed from constants, a parameter,
`$temperature`, `$mfactor` — is hoisted by the compiler into the model's setup
code, with everything else that is solution-independent. ngspice runs that code
twice per analysis: once in `OSDIsetup`'s own setup loops and once in
`OSDItemp`, which `CKTdoJob` runs after `CKTsetup` in every job (OSDI has one
entry point for setup and temperature). So every such `$strobe`, `$info`,
`$warning` and `$error` printed twice per analysis. Worse, the first copy was
stale: [E-535](Enhancement-535.md)'s draws and [E-654](Enhancement-654.md)'s
corner are applied at the end of `OSDIsetup`, after its setup loops, so under
`.option corner=ss` a banner printed `rsh=100` and then `rsh=115` for one
operating point, and under `.option osdimc` the nominal and then the draw.

## What changed

The setup pass's messages are **held** in `osdi_log` (`OSDIsetup` marks the
pass through `osdi_display_setup_phase`, once per device type; the earlier
types' messages stay held) and **dropped when the temperature pass re-enters**
(`osdi_display_reenter_setup`, from `OSDItemp`): its copies, evaluated on the
values the analysis runs with, are the ones that print. They are released to
the output instead when the setup **failed** for a card (`osdi_display_setup_failed`,
from the two failure branches and the corner refusal — what the code said before
the failure must show, and no temperature pass will repeat it), or at the first
Newton iteration if no temperature pass came. `$fatal` and event-gated or
`analog initial` output (`LOG_FLAG_IMMEDIATE`) are never held. A temperature
pass on its own — a `.dc temp` point, an `altermod`, a `reset` — prints as
before, once, with the new values.

## Why the hoisting stays

The hunt read LRM 9.4 as asking for a constant `$strobe` at every time step it
is reached in. The compiler's partition is the other reading, and the one
every Verilog-A compiler applies: code that depends only on parameters and
temperature is *initialization*, evaluated when those change, and a display
task in it reports at that evaluation. The model corpus is written to it —
BSIM4 has 338 `$strobe` parameter checks in its analog block, BSIMSOI 203,
bsimbulk 25 with 27 `$error`, HiSIM2 186, r3_cmc 11 `$warning` and 7
`$error`, PSP-HV 7 `$error`, and none of them under `@(initial_step)`; a
per-point evaluation would print BSIM4's *gamma1 is ignored because k1 or k2 is
given* at every accepted point of every instance. A task that reads the
solution, a state variable, `$abstime` or a branch a solution-dependent
condition controls stays per point, as before.

## Verification

`display_setup.va`: a constant, a constant-variable and a parameter banner
`$strobe`, a `$info` and a `$warning`, a solution-dependent `$strobe`, an
`@(initial_step)` control, a `$fatal` on a negative `rsh`.

| check | result |
|---|---|
| `op` + `tran 1u 70u` | the hoisted `$strobe`s, `$info`, `$warning` 2 lines each (was 4); `@(initial_step)` 2; the per-point `$strobe` 1 + 79 |
| `.option corner=ss`, `op` | one banner, `rsh=115` (was `rsh=100` then `rsh=115`) |
| `.option osdimc`, `op op op` | one banner per run: 100, then the draws |
| `dc temp 27 47 10` | the banner at 310.15 and 320.15 once each |
| `op`; `altermod mm rsh=50`; `op` | `rsh=100` once, `rsh=50` once |
| `rsh=-1` on the card | the banner once (was twice), then the `$fatal` |
| the E-659 binaries on the same suite | five of the six fail |

Full sweep 529 of 529 on both solvers.

## What this does not do

- A hoisted task still does not print per point; see above.
- `$fatal` from setup code is reported twice on a failed setup: two setup
  attempts, each immediate. Pre-existing and untouched.
- A `.dc temp` sweep prints the job's own setup line and then the first
  point's, both at the deck temperature. Pre-existing ([E-535](Enhancement-535.md)
  hunt bug 3 made the per-point lines appear at all).
