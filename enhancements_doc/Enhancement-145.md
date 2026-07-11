# Enhancement-145 — optimizing `.model`-card parameters (`-mparam`)

The `optimize` command could tune two kinds of knob: `alter`-reachable
device/instance parameters ([Enhancement-130](Enhancement-130.md)/`-param`) and
symbolic netlist `.param` values ([Enhancement-144](Enhancement-144.md)/`-dparam`).
The one class left out was **`.model`-card parameters** — the `is`/`n` of a diode
model, the `r` of a Verilog-A resistor model, and so on. A model parameter is
*not* `alter`-reachable (that reaches only device instances), and — as the
companion investigation showed — it is not `.dc`-sweepable either (`.dc` steps
only sources, resistors and instance parameters). ngspice changes a model
parameter with a **different** command, `altermod`, and Enhancement-145 wires that
into the optimizer as a third knob kind.

## Usage

```
optimize (-param|-mparam|-dparam) <name> <init> <lo> <hi>  [...]
         -analysis <command ...>
         ( -minimize <expr> | -target <expr> <value> [<weight>] ... )
         [-method nm|lm] [-maxiter <N>] [-tol <T>] [-verbose]
```

- **`-param name init lo hi`** — an `alter` target: a device instance (`R1`) or an
  instance parameter (`@m1[w]`), changed in place with `alter`.
- **`-mparam name init lo hi`** — a `.model`-card parameter, named
  `@<model>[<param>]` (e.g. `@dmod[is]`, `@rmod[r]`), changed in place with
  `altermod <name>=<value>`. **New in this enhancement.**
- **`-dparam name init lo hi`** — a symbolic `.param`, changed with `alterparam` +
  a `reset` re-source.

Everything else is unchanged. Like `-param`, `-mparam` is an **in-place** knob: a
model parameter takes effect immediately (`altermod` re-stamps the affected
devices), with **no re-source** — so `-mparam` is as cheap per evaluation as
`-param`, unlike the heavier `-dparam`. All three kinds mix freely in one run.

### Example

```spice
Vd a 0 dc 0.65
D1 a 0 dmod
.model dmod d(is=1e-15 n=1)
.control
optimize -mparam @dmod[is] 1e-15 1e-16 1e-12 -analysis op -minimize (abs(i(vd))-1m)^2
.endc
```

fits the diode **model**'s saturation current so it passes 1 mA at 0.65 V
(`is → 1.22e-14`).

## Implementation notes

- Changes are confined to `frontend/com_optimize.c` (a new `kind` value and the
  `altermod` branch) plus the one-line help string in `commands.c`. No new source
  files, no ABI change, no change to `inp.c` or any other file.
- Each parameter's `kind` is now one of `OPT_ALTER` (instance, `alter`),
  `OPT_MODELPARAM` (model, `altermod`) or `OPT_DECKPARAM` (`.param`, `alterparam` +
  `reset`). In `opt_eval`, the deck params are applied and re-sourced first (as in
  Enhancement-144), then the in-place knobs: `alter <name>=<value>` for
  `OPT_ALTER`, `altermod <name>=<value>` for `OPT_MODELPARAM`. Because `altermod`
  is in place, `-mparam` never triggers the re-source path — circuits with only
  `-param`/`-mparam` knobs keep the Enhancement-130/-143 fast path.
- The `@<model>[<param>]` name is passed straight through to `altermod`, which
  accepts that accessor form — so `-mparam @rmod[r]` emits `altermod @rmod[r]=…`,
  exactly mirroring how `-param @m1[w]` emits `alter @m1[w]=…`.

## Verification

`examples/optimize_examples/verify_optimize.py` (39/39; solver-independent, run
once) — checks [1]–[15] are Enhancement-130/-143/-144; [16]–[20] are new:

- **[16]** OSDI model param: `-mparam @rmod[r]` fits a Verilog-A resistor model's
  `r` (via `altermod`) so `v(out) = 0.25` → `r = 3 k`.
- **[17]** built-in model param: `-mparam @dmod[is]` fits a diode model's `is` so
  `I(0.65 V) = 1 mA` → `is = 1.22e-14`.
- **[18]** determined mixed fit: a **model** param (`@rmod[r]`) and an **instance**
  param (`R2`) fitted together → `r = 3 k`, `R2 = 2 k`.
- **[19]** `-mparam` is the in-place fast path — **0** re-sources (no `Reset
  re-loads` banner), unlike `-dparam`.
- **[20]** all **three** knob kinds (`-dparam` + `-mparam` + `-param`) coexist in
  one run and converge.

A new `optresm.va` (a Verilog-A resistor whose `r` is a *model* parameter) is
added; `optimize_mparam_demo.cir` is a runnable demo.

## Scope and follow-ups

Optimizing `.model`-card parameters (built-in and OSDI/Verilog-A) via `altermod`,
mixing freely with instance (`-param`) and symbolic (`-dparam`) knobs, in scalar or
least-squares mode. With this the optimizer covers **every** kind of circuit knob.
Remaining optimizer follow-up: analytic (adjoint) sensitivities in place of the
finite-difference Jacobian.
