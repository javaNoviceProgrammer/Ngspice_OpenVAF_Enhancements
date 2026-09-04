# Bug hunt — the Monte Carlo commands

**Date:** 2026-09-04 · **Commit under test:** `547e0c92` · **Binaries:** locally
built `OpenVAF-master-20260610/target/opt/openvaf-r` and
`ngspice-46/build/src/ngspice`.

A pass over `montecarlo`, `highsigma`, `wcd`, `mcsample`, `setseed`,
`mccorr`/`mvnorm` and `.option osdimc`, aimed at what the ten Monte Carlo
suites (145 checks, all green at the start) do not pin. Method: wherever a
statistic has a closed form, measure against it — the yield at a *k*σ
threshold is Φ(*k*), FORM is exact for a linear metric, a correlation matrix
produces its own coefficient — and wherever a knob has an edge, push it.

**Result: three findings that produce a confident wrong number, two silent
degradations, and a set of measurements that hold.** The numerical core of
every command is right: yields, tail probabilities, worst-case distances and
correlations all land on their analytic values, and the model-declared
statistics of `.option osdimc` sample exactly under `montecarlo` and
`highsigma`. What breaks is at the edges of the *inputs*: a spec written in
quotes, a run replicated without a seed, and `wcd` asked about statistics it
cannot see.

| # | finding | severity |
|---|---|---|
| [F1](#f1--a-quoted--spec-or--metric-is-scored-as-0-and-reported-with-confidence) | a `-spec`/`-metric` written in double quotes — or naming a vector that does not exist — is evaluated as 0 and reported as a definite 0 % or 100 % yield / P(fail); the evaluator's validity flag is discarded | medium — wrong answer, run completes. **Fixed** |
| [F2](#f2--un-seeded-runs-are-identical-replications) | `montecarlo` and `highsigma` without `-seed` re-seed from the constant `1` on every invocation, so "run it again" returns the same samples; the report never states the seed | medium — a replication that is not one |
| [F3](#f3--wcd-cannot-see-model-declared-statistics-and-says-the-wrong-thing) | `wcd` walks netlist `.param` dimensions only: with osdimc-only statistics it says *"the deck draws no Gaussian .params — use agauss"*; with one netlist dimension added it reports P(fail) = 0 for a 4σ event that `highsigma` and `montecarlo` both see | medium — wrong answer, wrong advice |
| [F4](#f4--mvnormi-outside-the-registered-matrix-is-an-independent-draw) | `mvnorm(i)` with *i* outside 1..*k*, or with no `mccorr` registered, silently returns an independent standard normal — the requested correlation is simply not applied | low — silent |
| [F5](#f5--a-contradictory-spec-yields-0--in-silence) | `-spec x -max 1.1m -min 0.9m` (max below min) is accepted and yields 0 % without a word | low — diagnostic |

---

## F1 — a quoted `-spec` or `-metric` is scored as 0, and reported with confidence

The help text writes `-spec <metric>`; a metric with parentheses invites
quotes. Under a transient analysis:

| spec, as written | what happened |
|---|---|
| `-spec vecmax(v(2)) -min 0.4` | 20 / 20 pass — correct |
| `-spec "vecmax(v(2))" -min 0.4` | `Warning from checkvalid: vector vecmax(v(2)) is not available` ×20, then **0 / 20 pass** |
| `-spec "v(2)*2" -min 0.2` (op) | the same warning, **0 %** |
| `-spec v(nosuch) -max 1` | the same warning, then **100 % yield, 0 violations** |

The quoted form arrives with its quotes attached, so the expression parser
takes it as one *vector name* and the lookup fails. The result is then scored:
`sw_eval_expr_ok` (`frontend/com_sweep.c:163`) returns `f = 0.0` for a
missing vector and reports the failure through its `ok` argument — and every
caller passes `NULL` for `ok` (`sw_eval_expr(metric[s])` at `:4567`). A 0
compared against the limits is a definite pass or a definite fail, so the
report is a confident yield either way. `montecarlo`'s only hint is a note
that *"every sample gave the SAME value … nothing in this deck varied"*,
which is about invariance, not existence; `highsigma` at least adds *"check
the metric resolves"*; `wcd` refuses correctly (*"the metric does not respond
to any statistical parameter"*).

This is the class Enhancement-433 already fixed for the same commands' other
arguments: `-analysis` goes through `cp_unquote` in all three (`:4382`,
`:4066`, `:4780`), `-spec` and `-metric` are `strncpy`'d raw (`:4405`,
`:4090`, `:4759`). Two lines close it — unquote the metric, and honour `ok`
by refusing the run when a sample's metric does not resolve — and the
undefined-vector case closes with the same line.

**Scope.** Unquoted expressions work in all three commands (`vecmax(v(2))`,
`v(2)*2`, `2*v(2)`, `@mm[r]`), and the evaluator takes the **last** element of
a multi-point vector (`v_realdata[v_length-1]`), so a transient spec reads the
final time point — worth knowing, since a pulse deck whose `tran` ends in the
low phase reads 0 legitimately. Non-finite metric values are also mapped to
0 (`if (!finite(f)) f = 0.0`) with the same silence.

**Resolved (2026-09-04, after the hunt).** `-spec` and `-metric` now pass
through the same `cp_unquote` as `-analysis` in all three commands, and every
evaluation honours the validity flag. `montecarlo` and `highsigma` stop at the
first sample whose metric resolves to nothing — the expression is the same for
every sample, so one is enough to know — and refuse to report: *"montecarlo:
spec 1 (v(nosuch)) did not resolve to a value on sample 1 -- it names no
vector this analysis produces (check the spelling, and that the metric exists
in the 'op' plot). No yield is reported: a spec that resolves to nothing would
have scored 0 against its limits."* The refusal runs after the loop's normal
cleanup (warm start, loop bar, seed offset, fast path, LHS), and the result
variables stay unset as a refused run's must (the E-537 hunt's H). `wcd`
says *"the metric (v(nosuch)) did not resolve to a value at the nominal
point"* instead of blaming the operating point, and a sample whose metric
does not resolve inside its importance-sampling loop is excluded like a run
that did not solve. The quoted transient spec in the table reads 20 / 20.
Pinned: `montecarlo_examples` 10 → 12, `highsigma_examples` 10 → 12,
`wcd_examples` 19 → 21; `mcpolicy_examples`' hunt-L check, which had reached
the no-variance note only because a mis-typed node's constant 0 never varied,
now uses a metric that resolves and never varies, and the mis-typed node is a
check of its own (33 → 34). Still as described: a non-finite metric value is
mapped to 0 in silence.

---

## F2 — un-seeded runs are identical replications

```
montecarlo 300 -spec i(v1) -max -0.95m      ->  yield 68.667%  (206 / 300)
montecarlo 300 -spec i(v1) -max -0.95m      ->  yield 68.667%  (206 / 300)
montecarlo 300 -spec i(v1) -max -0.95m      ->  yield 68.667%  (206 / 300)
montecarlo 300 -seed 1 -spec ...            ->  yield 68.667%  (206 / 300)
montecarlo 300 -seed 2 -spec ...            ->  yield 72.000%  (216 / 300)
highsigma 300 -scale 2 -metric ... (twice)  ->  P(fail) 4.2742e-03 both times
```

All three sampling commands initialise `unsigned seed = 1` (`:3988`, `:4340`,
`:4741`) and re-seed the generator from it at every invocation unless `-seed`
is given. The intent is reproducibility, and it delivers it — but the natural
way to check an estimate is to run it again, and here that returns the same
206 samples, so the check proves nothing; the report line (`montecarlo: 300
random samples, analysis 'op', 1 spec`) never says which seed was used.
Enhancement-537 records the *seeded* half of this problem ("every
'independent' run returned the same points") and fixed `-seed`; the default
path still has it. Either advance the default per invocation or print the
seed in the report — printing it is the smaller change and makes the
determinism a stated fact rather than a trap.

---

## F3 — `wcd` cannot see model-declared statistics, and says the wrong thing

Model `smcres` declares `r ~ N(1000, 25)` and a per-instance `dr ~ N(0, 10)`
through attributes, so `R = r + dr ~ N(1000, 26.93)`. Under `.option osdimc`:

| command, threshold at 4σ (`i(v1) > -0.902769m`) | result | analytic |
|---|---|---|
| `montecarlo 3000` at the 1σ threshold | yield 84.133 % | 84.13 % |
| `highsigma 3000 -scale 2` | P(fail) 4.81e-05 ± 1.23e-05 | 3.17e-05 (z = +1.3) |
| `wcd -metric i(v1) -max -0.902769m` | *"wcd: the deck draws no Gaussian .params — nothing to search over (use agauss/gauss in a .param)"* | β = 4 |
| the same deck plus one 1 Ω series resistor with `agauss(1, 1, 1)` | *"1 statistical dimension"*, **β = 106.7 σ, P(fail) = 0** | β ≈ 4, P = 3.17e-05 |

`wcd` counts its dimensions with `mc_wcd_ndim()`, which sees netlist `.param`
draws only, and Enhancement-535 deliberately holds **one** osdimc sample for
the whole search (`OSDImcHoldTrial(TRUE)`, `:4859`) — a worst-case walk over
a frozen draw. That is a defensible design limit; the defect is that neither
message admits it. The first tells a user whose statistics are entirely
model-declared to add `agauss` to a `.param` — advice that would double-count
if followed. The second says nothing at all and produces a P(fail) that is
wrong by the whole event: the σ = 26.9 Ω the model declares is invisible to
the walk, so the 1 Ω netlist dimension is the only one, and 106 σ of it is
"needed" to fail. A one-line note when osdimc statistics are present — *"the
model's declared statistics are held at one sample and not walked"* — would
make both outcomes honest.

---

## F4 — `mvnorm(i)` outside the registered matrix is an independent draw

`mccorr 2 1 0.9 0.9 1` then `.param a = 10 + 2*mvnorm(3)` — index 3 against a
2×2 matrix — runs without a word and draws a value. `mc_corr_component`
(`maths/misc/randnumb.c`):

```c
if (corr_k <= 0 || idx < 1 || idx > corr_k)
    return mc_sample_gauss();
```

so an index past *k*, an index of 0, or any `mvnorm` used with **no `mccorr`
registered at all** quietly becomes an uncorrelated standard normal. Nothing
crashes and the draw is well-formed; the correlation the deck asked for is
just absent. The `mccorr` command itself already says *"use mvnorm(1..2) in
.param expressions"* — the same range check, applied at the draw with a
message, would close this.

Measured in range, the machinery is exact: ρ = 0.9 gives +0.909, ρ = −0.9
gives −0.877, ρ = 0.5 gives +0.505, and `mccorr off` gives −0.027, over 400
resets each.

---

## F5 — a contradictory spec yields 0 % in silence

`montecarlo 20 -spec i(v1) -max -1.1m -min -0.9m` — an upper limit below the
lower one, unsatisfiable by construction — reports `yield 0.000% (0 / 20
pass)` and a per-spec violation count, exactly as a real 0 % yield would.
Diagnostic only; a check at parse time is a line.

---

## What was measured and holds

**Yields and tails against closed forms.** `montecarlo 4000` at a 1σ
threshold: 84.850 % (Φ(1) = 84.13 %, n = 4000, within 1.3 SE). `wcd` on the
netlist dimension: β = 2.5000 and 4.0000 exactly, P(fail) = Φ(−β) to seven
digits; the 2-D symmetric case and the negative-β case are the suite's.
`highsigma` at a 4σ threshold, λ = 2: 2.70e-05 ± 4.7e-06; λ = 3: 2.89e-05 ±
3.4e-06 (analytic 3.17e-05). Across eight seeds at λ = 8, seven estimates are
covered by their reported ± and one is a 3σ outlier; at λ = 3, eight of
eight — the reported error is honest. `-scale 1` is refused (*"must be >
1"*). Its effective-sample-size guard is `(Σw)²/Σw² < 10 % of the valid
samples`, computed over all samples rather than the failing ones, so an
over-inflated run can pass it while the tail estimate is poor — an
observation, not a defect, given the coverage above.

**Edges of `montecarlo`.** N is checked to [2, 100000] with the offending
token named; no `-spec` is refused; an always-passing and an always-failing
spec give 100 % / 0 % with the correct Wilson intervals ([88.65, 100] and
[0, 11.35] for n = 30); a spec on the drawn *model* parameter itself
(`-spec @mm[r] -max 1030`) yields 88.550 % against Φ(1.2) = 88.49 %.

**`mcsample` and `setseed`.** `lhs 0` and `lhs -3` are refused (*"must be
>= 2"*); `lhs 4` followed by eight `reset`s keeps producing fresh draws after
the four announced strata (5–8 differ from 1–4; whether they are a new
stratified round or plain draws is unstated); `mcsample off` restores
independent draws; `setseed 21` makes an un-seeded `montecarlo` reproducible
(and see F2 for what happens without it).

**`.option osdimc` structure.** Trial 1 is the exact nominal baseline. The
mismatch parameter `dr` draws independently per instance — including two
instances inside two copies of one subcircuit, and an instance with `m=4`,
which draws once. The process parameter `r` moves in lockstep across every
instance of the card, subcircuit copies included (derived per instance as
`1/i − dr`: 1003.202 / 1003.207 / 1003.202 / 1003.203 Ω on one trial). `-lhs`
under osdimc says exactly what it covers: *"stratifies the netlist's own
random .params; it does NOT cover .option osdimc draws"*.

**Expression specs, unquoted.** `vecmax(v(2))` under `tran`, `v(2)*2` and
`2*v(2)` under `op`, and `@mm[r]` all evaluate correctly in `montecarlo`;
`highsigma -metric v(2)*2 -max 0.5` gives P(fail) = 1 and `wcd` gives β = −20
(the nominal already fails) — both right.

## Coverage, honestly

Not reached: `optimize`/`sweep` interplay with osdimc beyond what
`mcpolicy_examples` pins (34 checks), `highsigma -inflate` on a subset of
parameters, `wcd -is` refinement under osdimc, the `-warm` flag, Ctrl-C
behaviour (batch mode cannot interrupt), and the `yield`/`pareto` commands'
own edges. Two probe decks failed on my side before they failed on ngspice's
— `printf '%s'` left `\n` literal, folding a control block onto one line —
and one "hang" was a `sed` waiting on stdin; all three are recorded so the
next hunt does not repeat them.
