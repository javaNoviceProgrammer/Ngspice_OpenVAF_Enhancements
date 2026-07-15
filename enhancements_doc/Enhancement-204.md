# Enhancement-204 — auto-triggering DC convergence aids

A convergence-robustness enhancement: `.option convhelp` turns ngspice's
operating-point solver into an **automatic escalation ladder** that reaches for the
strong convergence aids *without the user asking*, and reports which aid produced the
point.

## Background

ngspice's `CKTop` cascade already escalates automatically through **gmin stepping**
and **source stepping**. But the two strongest aids —

- the globalized damped-Newton **line search** ([E-111](Enhancement-111.md)), and
- **pseudo-transient continuation** ([E-127](Enhancement-127.md)) —

only fired when the user hand-set `.option linesearch` / `.option ptcont`, and nothing
told the user which aid rescued a hard operating point. The ngspice-vs-Spectre gap
analysis flagged exactly this: *"what remains is mostly auto-triggering heuristics
(reaching for these aids without the user asking) and folding them into the
robustness presets."*

## The ladder

`.option convhelp` makes the whole cascade one automatic ladder:

```
Newton (+ line search) → gmin step → source step → pseudo-transient → optran
```

- **Line search** is enabled for the operating-point Newton (and, since they call
  `NIiter` internally, its fallback homotopies). E-111's line search reduces to a
  plain full Newton step whenever the full step already reduces the weighted residual
  norm, so points that converge easily take the same iterates and are unaffected.
- **Pseudo-transient continuation** is tried automatically as a fallback — the E-127
  gate becomes `if (ckt->CKTptcont || ckt->CKTconvhelp)`, so no `.option ptcont` is
  needed.
- When a non-trivial aid produces the operating point, `CKTop` prints a one-line note,
  e.g. `Note: DC operating point reached via pseudo-transient continuation.`

`CKTop` saves the caller's line-search flag on entry and restores it on every exit
(the routine was refactored to a single `done:` exit), so the setting never leaks
into the transient analysis that follows.

It is **off by default** — the default (`convhelp` unset) path is byte-for-byte the
historical behavior, no new output — and it is turned on by
`.option errpreset=conservative`. The E-110 `TSKtolGiven` given-flag mechanism means
an explicit `.option convhelp=0` still overrides the preset, regardless of `.options`
line order.

## Verification

The same deliberately stiff behavioral exponential E-127 used — no junction
limiting, `1e-14·(exp(V/0.026) − 1) = (100 − V)/100`, physical root
`V(1) = 0.837922 V` — where plain Newton overshoots the huge `exp()` derivative to a
**spurious ~70.5 V** root (and here even the transient-op fallback lands on it).

With gmin/source stepping disabled so pseudo-transient continuation is the rung that
must fire:

- `.option convhelp` reaches the **correct 0.837922 V** and reports
  *via pseudo-transient continuation* — **without** `.option ptcont`;
- a plain run lands on the spurious root, so convhelp demonstrably changes the
  outcome;
- `.option errpreset=conservative` enables the same ladder, and an explicit
  `.option convhelp=0` overrides it.

On a battery of normal circuits (diode, BJT, two-diode, resistor network) convhelp is
**result-neutral** (converged node voltages identical to a plain run) and **silent**
(no aid note — the plain Newton solve already converges). All checked under **both**
linear solvers (KLU + Sparse 1.3): `examples/convhelp_examples/verify_convhelp.py`,
35/35.

## Files changed

Seven files, additive, mirroring the E-127 option plumbing:

- `optdefs.h` — `OPT_CONVHELP` enum + `ERRP_CONVHELP` given-flag bit.
- `tskdefs.h` — `TSKconvhelp:1`; `cktdefs.h` — `CKTconvhelp:1`.
- `cktsopt.c` — `OPT_CONVHELP` setter (+ given-flag), `convhelp` in the errpreset
  value table (conservative = on), and the `"convhelp"` `OPTtbl` keyword.
- `cktntask.c` — copy + default off; `cktdojob.c` — `CKTconvhelp = TSKconvhelp`.
- `cktop.c` — the auto-escalation: enable line search under convhelp, auto-fire
  pseudo-transient continuation, track and report the winning aid, single-exit
  restore of the line-search flag.

## Scope

`convhelp` orchestrates the *existing* aids automatically; it adds no new numerical
method. The default path is unchanged, so it is fully backward compatible.
