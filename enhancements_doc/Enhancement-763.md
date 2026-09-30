# Enhancement-763: `optimize` refuses what it cannot mean — a bound that is not a number was taken as 0, an init outside the box was clamped to a bound, a zero or negative weight was accepted, a `-target` expression with spaces fitted to a target of 0, a bare `-method` ran the default, a stray token was skipped, a second scalar objective was dropped and a duplicate knob was altered twice, all in silence; each is refused with a message now, and a raised population says so

**Scope:** F2 and F3 of the 2026-09-29 `optimize` hunt. ngspice only: `frontend/com_optimize.c` (the knob's three numbers, the `-target`
value and weight and the option flags all go through E-499's `opt_strictnum`; an init must
lie in `[lo, hi]`; a knob name may appear once; a bare option flag, an unrecognised token
and a second `-minimize`/`-maximize` under a scalar method refuse the command; a
`-swarmsize` raised to a method's minimum prints a NOTE; the lenient `optnum()` is gone).
The suites' own decks turned up two of the cases: `reuseloops` spelled `-samples` as
`-nsamples` and had run its centering check with the default 100 samples instead of 6,
and `loopguard` used a zero weight to provoke E-499's NOTE.

**Suites:** `optimize` 69 of 69 (47 of 69 on the E-761 binary: the new section [20] and
E-762's [19]), `loopguard` 49 of 49 per solver (its check [11] now expects the refusal),
`reuseloops` 17 of 17 per solver (the deck corrected), `pareto`, `dcenter`, `agestate`,
`autocorner`, `deopt`, `failacct`, `hierdev`, `mcpolicy`, `loopbar`, `opt100`, `psoopt`,
`reusestate`, `sweepanalysis` and `saopt` unchanged; the full sweep 534 of 534.

## What was wrong

E-499 gave the numeric options (`-maxiter`, `-tol`, `-swarmsize`, `-seed`, `-samples`)
a strict parser and left everything else on `optnum()`, an `ft_numparse` with an `atof`
fallback that returns 0 for text. Probed on the current build:

| command fragment | what happened |
|---|---|
| `-param R2 1k abc 10k` | `abc` became `lo = 0`; the fit ran over `[0, 10k]` |
| `-param R2 5k 10 1k` (init above `hi`) | the start was clamped to 1k; the only word was E-499's "finished ON a search bound", printed at the end |
| `-target v(out) 0.9 -1` | accepted; the sign vanished in the square |
| `-target v(out) 0.9 0` | accepted; the residual was identically 0 and E-499's NOTE said "nothing was optimised" afterwards |
| `-target v(out) - v(in) 0.4` | `v(out)` became the expression and `-` the value, 0; `unrecognized token 'v(in)'` was printed and the fit RAN, to a target of 0, ending "ON a search bound" |
| `... -method` (no argument) | Nelder-Mead in silence |
| `-minimize A -minimize B` with a scalar method | B dropped in silence (a second objective is NSGA-II's) |
| `-param R2 ... -param R2 ...` | both altered, the last value winning |
| `-maxiter5` | `unrecognized token`, then the run with the default cap |
| `-method de -swarmsize 3` | "population of 5 vectors": raised without a word |

Every unrecognised token was a message followed by the run, so a typo in an option or a
space in an expression changed the question and the command answered it with the same
"converged" line (E-762 fixed the line, not the question).

## What changed

- **Every number is strict.** `<init>`, `<lo>`, `<hi>`, the `-target` value and weight go
  through `opt_strictnum`: a SPICE suffix (`1k`, `1meg`) and a unit letter (`10o` is
  SPICE's 10, as `10ohm` would be) parse, text and trailing junk refuse the command
  naming the knob and the token: `-param r2: <lo> needs a number, not 'abc'`.
- **The init lies inside the box** or the command is refused: `init 5000 lies outside
  [10, 1000]; the search starts inside its own range`.
- **A weight is positive**: `the weight must be positive (got 0); a zero weight fits
  nothing and a negative one is the positive one squared`.
- **A `-target` value that is not a number** is refused with the one-token hint: `<value>
  needs a number, not '-' (an expression with spaces must be one token: v(out)-v(in),
  not v(out) - v(in))`. This is the half of hunt F3 a spaced target made; a `-minimize`
  that begins with `-` is still F3's.
- **A bare option flag** (`-method`, `-swarmsize`, `-seed`, `-maxiter`, `-tol`,
  `-samples`) refuses the command instead of falling off its end.
- **An unrecognised token refuses the command**, with the two usual causes named. That is
  F3's other half: `-minimize -v(out)` (the natural way to maximise `v(out`)) is read as
  a flag and used to print the usage line, followed in batch mode by ngspice's
  "incomplete or empty netlist"; it now says `an expression or command that begins with
  '-' must be quoted`, and the quoted form `-minimize "-v(out)"` runs (the lexer keeps the
  quotes, so the token is not a flag, and `collect_until_flag` strips them), as does
  `0-v(out)`.
- **Several objectives under a scalar method** refuse the command: `2 objectives were
  given (-minimize/-maximize); a scalar method minimises one -- give one, or -method
  nsga2 for a Pareto front`.
- **A knob named twice** is refused.
- **A raised population is announced**: `NOTE -- -swarmsize 3 raised to 5 (differential
  evolution needs four distinct members besides the target)`; the same for particle
  swarm's five and NSGA-II's even eight.

Nothing that parsed before and meant what it said parses differently: suffixes, a
negative target value (`-0.9` is not a flag), an optional weight after the value.

## What the suites' own decks said

The strict parser refused two commands the suites had been running for months:

- `reuseloops` check [9] wrote `-nsamples 6` for `-samples 6`. The lenient parser skipped
  both tokens and the centering ran its default 100 samples; the check still passed
  because it measures the setup reuse, not the sample count. The deck now says `-samples`.
- `loopguard` check [11] used `-target v(out) 0.4 0` to provoke E-499's "nothing was
  optimised" NOTE. The zero weight is refused up front now, and the check expects that.

## Checks

`optimize` section [20]: each of the ten refusals above prints its message and no run
follows (no "1 parameter" banner, no "converged"); SPICE suffixes on a bound and a weight
still parse and the fit converges; a negative target value is a number; `-swarmsize 3`
under differential evolution is raised to 5 with the NOTE and the fit converges;
`-minimize -v(out)` is refused with the quoting hint and `-minimize "-v(out)"` maximises
`v(out)` to the upper bound.

## Limits

- A `-minimize` or `-analysis` whose first token begins with `-` still has to be quoted;
  the parser cannot tell `-v(out)` from a misspelt flag, and the message says so.
- A unit letter after a number is SPICE's and stays accepted (`10o` = 10), so a typo of
  that shape is not caught.

**Update ([E-764](Enhancement-764.md)).** The raised-population NOTE covers `-method cmaes` (a value below 4 is raised to 4); `-starts` takes its count through the same strict reader (a bare `-starts`, `-starts 0` and `-starts abc` are refused), and `-polish` or `-starts` under `-method nsga2` is refused with a message. The usage line and the unknown-method message list the seven methods.

**Update ([E-765](Enhancement-765.md)).** The method lists in the usage line, the bare-flag message and the unknown-method message name `bayes`; `-swarmsize` under it prints a NOTE and is ignored, and `-maxiter` above 2000 is capped with a NOTE.

**Update ([E-766](Enhancement-766.md)).** `-constrain`'s bounds and `-ctol` go through the same strict readers: a limit that is not a number, `-ctol 0`, a constraint with no `-max`/`-min`, a `-constrain` followed by a flag and a `-max` before any `-spec` or `-constrain` are refused with a message.
