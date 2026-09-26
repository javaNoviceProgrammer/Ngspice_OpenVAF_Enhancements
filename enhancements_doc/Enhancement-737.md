# Enhancement-737: the pole-zero search holds at the determinant's rounding floor — the same common-emitter stage gave two, three or five poles depending on the solver, its knobs and the deck's line order, because the Muller driver lost its sign-change bracket where the determinant is noise, went hunting a conjugate pair that is not there and burnt its iteration budget; a bracket now keeps its crossing, Muller starts beside its complex start, the outward march stops when the deflated determinant is flat, a minimum at the floor is taken at once, and the stage's five poles, a twelve-decade ladder's six roots and a bandpass's pair come out under every solver and knob without a warning

**Scope:** F4 of the
[second KLU/Sparse solver-core hunt of 2026-09-25](../docs/bug_hunts/2026-09-25_klu-sparse-solver-cores-second-hunt.md)
and the six-element RLC of its smaller notes. **ngspice only, both solvers, the Muller
driver only.** `src/spicelib/analysis/cktpzstr.c` (`CKTpzUpdateSet`, `CKTpzStrat`,
`PZeval`'s `COMPLEX_INIT` and `COMPLEX_GUESS`, `CKTpzFindZeros`' loop and its warnings).
[`examples/klupz_examples/`](../examples/klupz_examples/) (checks [10]–[16], 12 checks,
21 in all); [`examples/pzeig_examples/`](../examples/pzeig_examples/) (checks [3] and [8]
re-anchored, the README's far-root limitation). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page; the solver notes.

**Suites:** `klupz` 21 of 21 (10 of 21 on the E-736 binary: the twelve new checks, all but
the linear twin under KLU); `pzeig` 13 of 13 (12 of 13 on the E-736 binary: check [8]);
`pzklu` 4 of 4; no new build warnings; full sweep, run alone. Beyond the suites: the 56
pole-zero decks of the hunt's harnesses and of the suites, run on the E-736 binary and this
one — 20 report more roots or lose their warning, 33 are the same, 3 move a root by at most
2.8e-9 relative, none reports fewer; 40 random R/L/C/G networks (3 to 6 nodes, values over
up to fifteen decades, floating capacitors, series inductors) against the exact roots of
their characteristic polynomials — 77 of 80 solver runs complete against 70, one warning
against eight, none worse (see Verification).

## What was wrong

```spice
* ce
Vcc vcc 0 12
Vin in 0 dc 0.7 ac 1
Rs in b 1k
Rb1 vcc b 100k
Rb2 b 0 22k
Q1 c b e qm
.model qm npn(bf=150 is=1e-15 cje=2p cjc=1p tf=0.3n rb=50)
Rc vcc c 4.7k
Re e 0 1k
Ce e 0 100u
Cc c out 10u
Rl out 0 100k
Cs out 0 1p
Lp c c2 1n
Rp c2 0 1e9
.control
pz in 0 out 0 vol pz
print all
.endc
.end
```

| run | poles reported (E-736) |
|---|---|
| Sparse | −1e18, −5.9265e8, −5.7693e7, −53.963, −0.95511 |
| KLU, default | **−53.963, −0.95511** — "iteration limit reached; giving up after 218 trials" |
| KLU, `klu_btf=off` or `klu_scale=none` | −5.7693e7, −53.963, −0.95511 — gives up after 239 / 245 |
| KLU, `klu_scale=sum` or `klu_ordering=colamd` | the five |
| KLU default, `Lp`, `Rp`, `Cs` moved to the top of the deck | the five |

The five are real (−Rp/Lp is −1e18; the exact roots of the stage's linear twin agree). The
determinant is not at fault — `pzeig` and E-171/E-172 had made it right under KLU — but its
rounding near a far root is the trigger, and the driver could not take it. A trace of the KLU
run (`PZDEBUG`) shows the third pole bracketed at once by a sign change between −1e8 and
−1e7, and then, at −5.77e7, the deflated determinant at its floor: 2⁻⁸⁸ against 2⁻⁵⁷ a decade
away, the sign flipping at random between trials 0.03 apart. The bracket was (−.0387 −,
−.0153 +, −868.97 +) and the next point, −.0207 (+), fell between the two ends of the
crossing with `set[1]`'s sign; `CKTpzUpdateSet` chooses which point of the set a new point
replaces by *magnitude* —

```c
        if (!CKTpzTrapped || new->mag_def < set[1]->mag_def ...) {
            /* Really should check signs, not just compare fabs( ) */
            set[2] = set[1]; set[1] = new;        /* MID_LEFT */
        } else {
            set[0] = new;                         /* NEAR_LEFT */
        }
```

— and at the floor the magnitudes are noise, so it took the new point as the left end and
dropped the only point of the other sign. Three same-sign points with the smallest in the
middle are, to `CKTpzStrat`, "minima in magnitude above the x axis": the search left the
real axis for a conjugate pair, and Muller iterated on noise around −57692869.03 ± j0.0025
for 170 trials until `NITER_LIM`. Under Sparse the same root's determinant happened to
cancel 2⁻⁵⁰ deeper (the pivot order absorbs the cancellation differently) and the search
converged in six steps; `klu_scale=sum`, `colamd` and the moved lines change KLU's order and
scaling the same way. Which rounding came first was the solver's only part.

Three more of the same family, in the same driver, found on the way:

* **The companions to a complex start.** When a real-axis magnitude minimum is found the
  driver starts Muller at (σ, jω) with ω from the quadratic through the three real points
  (`NIpzK`), then needs two more points and put them at j1e8 and j1e12, whatever the
  circuit's scale. On the six-element RLC of the hunt's notes (twelve decades, exact roots
  at −0.999, −1001, −1.001e9, −5e11 ± j3.16e13 and −1e15) the start landed almost on the
  pair — the determinant 2⁻²³⁹ against 2⁻⁹⁹ around it — and Muller, from a triple with two
  points 40 and 100 times too low, wandered to the limit: "giving up after 236 trials" with
  three roots, under both solvers.
* **The far field.** After the last finite root the outward march (guesses ×10, alternating
  sides) went on to ±1e21 before the loop's own span test stopped it, and beyond about 1e19
  the rounding of the s·C entries against G makes the deflated determinant's variation
  noise (6e-3 relative at 1e21 on the bandpass, 1.6e-7 at 1e16). A chance minimum there
  trapped the hunt for 45 trials and a complex hunt on nothing took the rest: the RLC
  bandpass under Sparse gave up after 231 trials *with both of its roots found*.
* **The minimum at the floor.** The hunt for a magnitude minimum on the real axis refined
  it until two trials coincided to 1e-12 — on a quadratic minimum whose three values already
  agree to 1e-13 that is a random walk: 24 trials on the RLC, 45 on a pair at
  −4e-5 ± j1.2e9 under Sparse and never under KLU. The driver's own comment says the ω the
  complex start uses is taken from the first quadratic in any case.

## What changed

Four changes in `cktpzstr.c`, all solvers:

* **A bracket keeps its crossing.** With the sign change between `set[0]` and `set[1]`, a
  new point between them of `set[1]`'s sign goes to the middle (the crossing is now between
  `set[0]` and it) and a point to the right of `set[1]` becomes the right end; the mirror
  image for a crossing between `set[1]` and `set[2]`. The magnitude rule still decides where
  it is harmless (a point of the far end's sign, or an untrapped set). A third repeated move
  splits inside the crossing (`SPLIT_LEFT` for trap 1, `SPLIT_RIGHT` for trap 2) — the old
  rule sent a third `NEAR_LEFT` to the far side of `set[1]`, outside it.
* **The companions sit beside the start.** When the start's imaginary part came from the
  real-axis quadratic, the two companions are at twice and half of it, so the triple spans
  the pair; the blind start (imaginary part 10000, when no quadratic was available) keeps
  j1e8 and j1e12.
* **The march stops when the deflated determinant is flat.** With the roots found so far
  divided out, f(s) = c · Π(1 − s/r) over the roots r that remain, so three points spanning
  S at which f agrees to 2⁻²⁰ put every remaining root beyond S · 2²⁰; at S = 1e16 that is
  1e22, the span at which the loop gave up anyway (`PZ_FLAT_BITS`, `PZ_FLAT_SPAN`; a new
  `QUIT` strategy ends the search without a warning). A root at 1e18 (the stage's −Rp/Lp)
  leaves a 1 % variation at 1e16 and the march goes on to find it, as before.
* **A minimum at the floor is taken.** In the trapped minimum hunt, three magnitudes that
  agree to 2⁻³³ (`PZ_MIN_FLAT_BITS`) cannot be refined by more trials: the middle point is
  flagged as the minimum and the complex search starts from it, as the coincidence test
  would have decided had two trials happened to agree — the same path, entered at once.

The "giving up" warnings say how many roots the search has and that `.option pzeig`
does not iterate.

| deck | E-736 | now |
|---|---|---|
| CE stage, KLU default | 2 poles, 208 trials, warning | 5 poles, 61 trials |
| CE stage, KLU `klu_btf=off` | 3 poles, 219 trials, warning | 5 poles, 45 trials |
| CE stage, Sparse | 5 poles, 57 trials | 5 poles, 48 trials |
| linear twin, Sparse | 3 poles, 214 trials, warning | 5 poles, 42 trials |
| six-element RLC, both | 3 poles, 220 trials, warning | 6 poles, 42 trials |
| RLC bandpass, Sparse | 2 poles, 215 trials, warning | 2 poles, 39 trials |
| RLC bandpass, KLU | 2 poles, 51 trials | 2 poles, 39 trials |

(Trials are `NTrials` of the pole search in a `PZDEBUG` build.)

## Verification

* **The stage.** Five poles, identical to 1e-6 across KLU's default, `klu_btf=off`,
  `klu_scale=none`, `klu_scale=sum`, `klu_ordering=colamd` and Sparse, with the three lines
  moved or not, no warning (`klupz` [10]–[13]). Its linear twin: the five exact roots of its
  characteristic polynomial under both solvers ([16]).
* **The ladder and the bandpass.** The six-element RLC gives all six exact roots under both
  solvers ([14]) — `pzeig` reports three of them, because its infinity threshold
  (|μ| ≤ 64·n·ε·‖M‖) discards eigenvalues more than about 1e13 times farther out than the
  nearest one, now said in its README; the bandpass under Sparse gives its pair and origin
  zero without a warning ([15]); `pzeig`'s check [8], which keyed on that warning to show
  the default is still the Muller method, now keys on the ladder's far roots.
* **The random battery.** 40 networks (a ladder spine of R or L with shunt R and C, up to
  three extra R/L/C between random nodes, a VCCS in a third of them), the exact roots of
  det(G + sC) from the characteristic polynomial over the rationals; every root matched to
  1e-6 and none extra counts as complete. E-736: 70 of 80 solver runs complete, 8 warnings;
  now 77, one warning, no run worse. The two "extras" both binaries report are a double pole
  at 0 that the reference's root finder places at 1e-181. What remains: a pair at
  −4.1e-5 ± j1.2e9 (the real part 3e-14 of the magnitude) that KLU's rounding still leaves
  at 2 of 4 — see below.
* **The hunt's and the suites' decks.** All 56 with a `pz` line, on both binaries: 20 better
  (more roots, or the warning gone), 33 the same, 3 with a root moved by 1.0e-9 to 2.8e-9
  relative (a reconverged far root), none fewer, no new warning.

## What this does not do

* It does not change the coincidence test that accepts a root — two trials agreeing to
  1e-12 of the real part, with the same imaginary part. A pair whose real part is far below
  its magnitude (−4.1e-5 ± j1.2e9) can sit on the root with the determinant at 2⁻¹⁵⁹ and
  never pass it under one solver's rounding: KLU still reports 2 of that network's 4
  poles. Judging the distance against the magnitude instead was tried and not kept — it
  accepted Muller iterates that were still creeping (the bandstop's zeros came out at
  1 + j1e6 instead of ±j1e6, and the battery gained six spurious roots).
* It does not touch the determinant path (`spDeterminant`, `spDeterminant_KLU`), the
  deflation, `NITER_LIM` (200), or the `pzeig` method; the far-field noise beyond |s| ≈ 1e19
  is still there for a circuit whose roots are not exhausted before it.
* It does not retry under another ordering or fall through to `pzeig` when the search gives
  up, the hunt page's other suggestions: the search now converges on every deck where those
  would have been tried, and `pzeig` drops the far roots the Muller search finds.
