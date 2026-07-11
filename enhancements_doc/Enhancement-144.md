# Enhancement-144 — optimizing symbolic `.param` values (`-dparam`)

The built-in `optimize` command ([Enhancement-130](Enhancement-130.md),
[Enhancement-143](Enhancement-143.md)) could only turn knobs reachable by
`alter`: device instances (`R1`) and device/model parameters (`@m1[w]`). But
netlists are usually written in terms of **symbolic `.param` values** —
`.param w=1u`, `R1 in out {500*k}` — and those are *not* `alter` targets: a
`.param` is expanded at **parse time**, so changing it means editing the deck and
re-parsing, not poking the live circuit. This was the last open follow-up from
Enhancement-143.

Enhancement-144 adds a second knob kind, **`-dparam`**, for exactly this. A
`-dparam` name is a symbolic `.param`; the optimizer changes it with
`alterparam <name>=<value>` (which rewrites the stored deck) followed by a quiet
`reset` that re-sources the deck — re-evaluating every `.param` expression and
re-stamping device values — before running the analysis.

## Usage

```
optimize (-param|-dparam) <name> <init> <lo> <hi>  [...]
         -analysis <command ...>
         ( -minimize <expr> | -target <expr> <value> [<weight>] ... )
         [-method nm|lm] [-maxiter <N>] [-tol <T>] [-verbose]
```

- **`-param name init lo hi`** — as before: an `alter` target (device instance or
  `@inst[param]`), changed **in place** (fast, no re-parse).
- **`-dparam name init lo hi`** — a symbolic netlist `.param` (e.g. the `w` in
  `.param w=1u`), changed with `alterparam` + a `reset` re-source.

Everything else — `-analysis`, `-minimize`, `-target`, `-method`, `-maxiter`,
`-tol`, `-verbose`, normalized `[0,1]` search, Nelder-Mead / Levenberg-Marquardt —
is unchanged. The two knob kinds **mix freely** in one run.

### Example

```spice
.param rtop=1k
V1 in 0 dc 1
R1 in out {rtop}
R2 out 0 1k
.control
optimize -dparam rtop 1k 100 10k -analysis op -minimize (v(out)-0.3)^2
.endc
```

tunes the `.param rtop` (used as `R1`'s value) until `v(out) = 0.3`, giving
`rtop = 2333.3 Ω`.

## Implementation notes

- Changes are in `frontend/com_optimize.c` (parameter *kind* tracking + the
  re-source step) and `frontend/inp.c` (gate two re-source banners); plus the
  one-line help string in `commands.c`. No new files, no ABI change.
- Each parameter carries a `kind`: `OPT_ALTER` (device/instance, in place) or
  `OPT_DECKPARAM` (`.param`, via `alterparam` + `reset`). If any `-dparam` is
  present, `opt_eval` **applies all deck params first, re-sources once, then
  applies the in-place `alter` params** — because `reset` rebuilds the circuit
  from the deck and would otherwise wipe an earlier in-place `alter`. This
  ordering is what makes the two kinds mix correctly (verified: a `.param` and an
  altered device fitted together land on the unique joint solution).
- Circuits with **no** `-dparam` skip the re-source entirely — the Enhancement-130
  / -143 fast path is untouched, no performance regression.
- The per-iteration `reset` is silenced by the existing `ft_optimizing` flag: the
  two banners it prints (`Reset re-loads circuit …` in `inp_spsource`, and
  `Circuit: …`) are now gated, so hundreds of inner re-sources are quiet; only the
  final "leave the circuit at the optimum" run is shown. `ft_optimizing` is
  re-asserted after each `reset` in case re-sourcing cleared it.
- A `reset` is heavier than an `alter` (it tears down and rebuilds the whole
  circuit and re-reads the deck), so `-dparam` costs more per evaluation than
  `-param` — inherent to changing a parse-time `.param`. Use `-param` when a knob
  is `alter`-reachable; use `-dparam` only for genuine `.param`s.

## Verification

`examples/optimize_examples/verify_optimize.py` (31/31; solver-independent, run
once) — checks [1]–[10] are Enhancement-130/-143; [11]–[15] are new:

- **[11]** scalar `.param` fit: `-dparam rtop` (used as a device value) → `rtop =
  2333.3` for `v(out) = 0.3`.
- **[12]** **mixed** `-dparam rtop` + `-param R2` fitted together → `rtop = 3 k`,
  `R2 = 2 k` (the unique joint solution) — proves the deck param is re-sourced
  first and the in-place `alter` re-applied after.
- **[13]** `.param` inside an arithmetic device expression (`R1 = {500*k}`) → `k = 6`.
- **[14]** least-squares `-dparam` fit (`-target`, Levenberg-Marquardt) → `rtop =
  2333.3`.
- **[15]** the inner re-sources are quiet — the `Reset re-loads` banner appears at
  most once (the final run), not once per evaluation.

Also verified manually with an AC analysis and with a `.param` scaling an
**OSDI/Verilog-A** device value across the re-source. `examples/optimize_examples/
optimize_dparam_demo.cir` is a runnable demo. The Enhancement-130/-143 suite is
unchanged (23/23 within the 31).

## Scope and follow-ups

Optimizing symbolic `.param` values, mixing freely with `alter`-reachable device
parameters, in scalar or least-squares mode. Remaining optimizer follow-up:
analytic (adjoint) sensitivities in place of the finite-difference Jacobian.
