# KLU pole-zero: complex determinant, pivot tolerance, balanced output (E-171 + E-172)

A deep audit of the two linear-solver stacks (Sparse 1.3 and KLU) found that
**pole-zero analysis under `.option klu` silently produced garbage for any
circuit with complex poles or zeros** — a series RLC reported *four bogus real
poles* (−100, −10, −0.89, 0) instead of its conjugate pair −5000 ± j·999 987.5.
Real-axis poles/zeros came out right, which is exactly why the existing
regression (a single-real-pole RC) never caught it.

![klu pole-zero fixed](klupz.png)

## The two defects (both in `maths/KLU/klusmp.c`)

1. **Complex determinant formula.** `spDeterminant_KLU` built each pivot as the
   mixed quantity `(1/(Ux·Rs), Uz·Rs)` and took its complex reciprocal. KLU's
   `Udiag` holds the *actual* pivots (its solve divides by them), so the correct
   contribution is simply `Udiag·Rs` — the mixed form is right **only when the
   pivot is real** (`Uz = 0`) and garbage everywhere else. Since pole-zero's
   Muller iteration evaluates `det(G + sC)` at complex trial points `s`, every
   complex-plane evaluation was wrong. The real branch was worse still: its
   product loop never ran (the loop index was left at N by the preceding scan),
   it divided instead of multiplying (copied from Sparse, whose `Diag` stores
   *reciprocal* pivots), and it never wrote the imaginary part, so the caller
   consumed an uninitialized value. Both branches also computed the permutation
   sign as `#non-fixed-points/2`, which is wrong for any cycle longer than 2 —
   now an exact cycle-decomposition parity.

2. **Unsanitized pivot tolerance.** Pole-zero calls `SMPcReorder` with
   `PivRel = 0.0`. Sparse's `spOrderAndFactor` **sanitizes** a non-positive
   threshold to its default; the KLU branch passed it straight to
   `Common->tol`, making KLU accept an *exactly-zero* diagonal as a pivot. At
   the `s = 0` trial an inductor branch has a `0.0` diagonal, so the
   factorization came back `KLU_SINGULAR` and PZ recorded a **spurious root at
   the origin** — and the poisoned search never expanded past |s| ≈ 10.

With both fixed, the KLU determinant matches Sparse to ~14 digits at every
trial point, and the E-113-era guard ("finite-zero computation is not supported
with KLU") is removed from `pzan.c` — its root cause was defect 2. (The
balanced/differential-output guard remains: `SMPcAddCol` genuinely has no KLU
branch.)

## Enhancement-172: balanced output + full partial pivoting

Two follow-up fixes complete KLU pole-zero support:

- **Balanced / differential output** (`pz n1 n2 n3 n4 vol` with a non-ground
  output reference) was guarded off as unsupported: the output fold
  `col(out−) += col(out+)` runs through `SMPcAddCol`, which had no KLU branch —
  and KLU's CSC sparsity pattern is fixed at conversion time, so the fold's
  fill-in cannot be created on the fly the way Sparse does. Fixed by reserving
  the **union pattern** in `CKTpzSetup` (every row of the solution column is
  added to the balance column before the COO→CSC conversion; duplicates fold
  into one slot) plus a merge-walk KLU branch in `SMPcAddCol`.
- **Full partial pivoting for PZ factorizations.** KLU's ordering is fixed at
  `klu_analyze` time (pattern-only); Sparse re-runs *value-aware* Markowitz
  ordering every trial. PZ sweeps |s| across ~20 decades, and with the relaxed
  default `tol = 0.001` the fixed ordering picked catastrophically-cancelling
  pivots at extreme |s| — the determinant came back with the **wrong sign and
  magnitude** (verified against an exact rational determinant of the same
  loaded matrix), minting spurious far-field "roots" at |s| ~ 1e19–1e21. The
  out-of-range-PivRel fallback is now `tol = 1.0` (full partial pivoting, KLU's
  only value-adaptive lever), which keeps the determinant accurate across the
  whole sweep — and also cured the twin-T conjugate-pair stall noted in E-171's
  scope: **all root sets now match Sparse**, including the twin-T (6/6 roots).

![balanced pole-zero](klupz_balanced.png)

## Enhancement-737: the search itself holds at the determinant's rounding floor

F4 of the [second solver-core hunt](../../docs/bug_hunts/2026-09-25_klu-sparse-solver-cores-second-hunt.md)
(2026-09-25): the same common-emitter stage gave **2** poles under KLU's
default ordering ("iteration limit reached; giving up after 218 trials"),
**3** with `klu_btf=off` or `klu_scale=none`, **5** with `klu_scale=sum`,
`colamd` or Sparse — and 5 under KLU too once three deck lines were moved.
The determinant was not at fault, its rounding was the trigger: near the
third pole (−5.77·10⁷) the deflated determinant is at its floor (2⁻⁸⁸
against 2⁻⁵⁷ a decade away), its sign flips at random, and the Muller
driver (`cktpzstr.c`) lost its sign-change bracket there — `CKTpzUpdateSet`
replaced an endpoint by magnitude ("really should check signs, not just
compare fabs()", says its own comment), dropped the one point of the other
sign, read the three same-sign points as a magnitude minimum and went hunting
a conjugate pair that is not there until its iteration limit. Which
ordering's rounding did this first was the solver's and the knobs' only part.
Four changes in the driver, both solvers:

- a bracket with a sign change **keeps its crossing** (a point of the far
  endpoint's sign goes to the middle), and a repeated move splits inside it;
- Muller's two companions to a complex start sit at **half and twice its
  imaginary part** when that came from the real-axis quadratic, instead of
  the fixed j10⁸ and j10¹² — on the six-element RLC ladder the start was
  almost on the pair at ±j3.16·10¹³ and the fixed companions sent Muller
  wandering;
- the outward march **stops when the deflated determinant is flat** to 2⁻²⁰
  over a span of 10¹⁶: every remaining root is then beyond 10²², where the
  search gave up anyway, and the march no longer walks into the zone
  (|s| ≳ 10¹⁹) where the rounding of the s·C entries against G makes the
  determinant's variation noise and a chance minimum trapped it (the
  bandpass under Sparse, "giving up after 231 trials" with both roots found);
- a real-axis magnitude minimum whose three values **agree to 2⁻³³ is taken at
  once** — refining it further is a random walk until two trials happen to
  coincide to 1e-12 (24 trials on the ladder, 45 on a pair at −4·10⁻⁵ ± j1.2·10⁹
  under Sparse, never under KLU), and the imaginary part the complex start
  uses was taken from the first quadratic in any case.

The stage gives its five poles under every solver and knob (61 trials where
the old search spent 208 on two); the RLC ladder gives all six exact roots of
its characteristic polynomial; the "giving up" warning now says how many
roots it has and that `.option pzeig` does not iterate. Checks [10]–[16].

## Files

- **`verify_klupz.py`** — compares the **full pole/zero root set** between the
  two solvers on nine circuits, each also anchored to its analytic answer:
  series RLC (conjugate pole pair — the smoking gun), RC lowpass (the old-good
  case, no regression), lead network (finite real zero), RC highpass (origin
  zero), RLC bandstop (**purely imaginary zeros** — the hardest case), RLC
  bandpass (the finite-zero search that used to be guarded off under KLU);
  plus the E-172 additions — differential RC bridge and differential
  complex-pole pair (**balanced output**, formerly "not supported with 'option
  KLU'"), and the twin-T notch (formerly stalling on its conjugate zero pair);
  plus the E-737 section — the common-emitter stage under KLU's default,
  `klu_btf=off`, `klu_scale=none`, `klu_scale=sum`, `klu_ordering=colamd` and
  Sparse and with its lines reordered (five poles every time, no warning), the
  six-element RLC ladder over twelve decades (all six exact roots of its
  characteristic polynomial, both solvers), the bandpass under Sparse (no
  "giving up"), and the stage's linear twin (five exact poles, both solvers).
- **`make_klupz_fig.py`** → **`klupz.png`** — s-plane root maps: Sparse ✕ vs
  fixed-KLU ○ coinciding, with the recorded pre-fix garbage in red.
- **`klupz_demo.cir`** — the series RLC under `.option klu`, printing the
  conjugate pair.

## Running

```sh
python3 verify_klupz.py       # 21 checks (drives both solvers itself)
python3 make_klupz_fig.py     # figure
ngspice -b klupz_demo.cir     # demo
```

## Scope note

The vintage spice3 PZ driver (Muller iteration on determinants) is delicate
near its noise floor *independent of solver*; E-737 above made it hold there
(the RLC bandpass, on which Sparse used to hit its iteration limit after
finding both roots, is clean under both). With the E-172 full-partial-pivoting
fallback, every circuit in this battery produces root sets identical between
the two solvers to float precision (the twin-T stall noted during E-171 is
resolved). What remains beyond the floor: a pair whose real part is below the
determinant's resolution (10⁻¹⁴ of its magnitude) can still be missed by one
solver's rounding and found by the other's.
