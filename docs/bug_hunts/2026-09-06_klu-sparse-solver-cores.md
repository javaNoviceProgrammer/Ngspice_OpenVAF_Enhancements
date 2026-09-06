# KLU and Sparse solver cores — a one-hour hunt

**Date:** 2026-09-06, 11:17–12:17 · **Commit under test:** `5c81fedd` ·
**Binary:** locally built `ngspice-46/build/src/ngspice` (2026-09-06 08:29; KLU and
XSPICE compiled in, CIDER not) · **Solver selection:** `.option sparse` / `.option klu`
(this build defaults to Sparse) · **Method:** read the solver glue and the custom KLU
helpers line by line, then wrote small decks for every suspicion and ran each under both
solvers. No fixes were applied; every deck below is inline so the run can be repeated.

The brief was the *core* of the two solvers. In this build there is only one glue file
for both: `src/maths/sparse/spsmp.c` is compiled only when KLU is not wanted
(`sparse/Makefile.am`), so every Sparse call in the shipped binary goes through the
`else` branches of `src/maths/KLU/klusmp.c`. That file, the repo's own additions to KLU
(`klu_multiply.c`, `klu_utils.c`, `klu_extract.c`, the rcond guards) and the analyses
that flip the matrix between real and complex got the closest reading; the upstream
SuiteSparse kernels and Sparse 1.3's ordering were skimmed, not audited.

**Result: six defects confirmed with plain decks — five on the KLU side and one,
found at the very end, that Sparse and KLU share; one latent hang shared by both
solvers; one side finding in XSPICE's batch teardown; and a handful of smaller
notes.** The first finding is a wrong-answer bug that two earlier
audits had declared unreachable; the fifth, found in the second hour, is an AC accuracy
loss that grows across a wide frequency sweep.

| # | finding | severity |
|---|---|---|
| [F1](#f1--a-node-with-no-matrix-entries-makes-klu-return-wrong-voltages-for-the-rest-of-the-circuit-silently) | a node that owns no matrix entry (connected only to a current source, or only as the output of a controlled current source) makes KLU return wrong voltages for **every other node**, with no warning, in op, dc, tran, ac and sens; Sparse solves the deck or reports a singular matrix. With two such nodes the RHS vectors are allocated short and every device load writes past them. The structural-zero-column collapse in `SMPconvertCOOtoCSC` is wrong end to end, and E-232/E-233's claim that it is dead code is false | **high** — wrong answers, silent; heap overflow with two floating nodes |
| [F2](#f2--ic-or-nodeset-on-a-node-without-a-diagonal-element-aborts-every-analysis-under-klu-as-out-of-memory) | `.ic` or `.nodeset` on a node that has no diagonal element (the tap between two stacked voltage sources, a node between two inductors, or between an inductor and a voltage source) aborts **every** analysis in the deck under KLU with `doAnalyses: out of memory`; Sparse creates the element and runs | **medium-high** — legal deck, fatal and misleading |
| [F3](#f3--option-rshunt-is-silently-absent-from-ac-noise-sp-and-disto-under-klu) | `.option rshunt` reaches the operating point under KLU but is silently absent from AC, noise, `sp` and distortion — all four confirmed with decks: the shunt pointers are bound to the real array only and `CKTacLoad` adds through them while the factorization reads the complex array | **medium** — wrong small-signal answers, silent |
| [F4](#f4--an-ac-family-analysis-that-returns-early-leaves-the-devices-bound-to-the-complex-arrays) | AC, noise, `sp` and `disto` switch every device's pointers to the complex arrays and switch back only on their success path; an early return leaves the binding complex. Harmless when the next job rebuilds the matrix; under E-471's setup reuse (`sweep`/`optimize -analysis ac|noise|sp`) the next point's operating point is factored from an empty real matrix. Reproduced: a `stop when` breakpoint inside `sweep -analysis ac` makes the following point singular (`out = nan`) under KLU while Sparse completes all points | **medium** — wrong sweep results after any interrupted point |
| [F7](#f7--klus-ac-loses-accuracy-across-a-wide-sweep-because-every-point-reuses-the-first-frequencys-pivot-order) | every AC point after the first is a `klu_z_refactor` with the pivot order chosen at the first frequency and no numerical check (the E-439 guard is real-only). On a ten-section RC ladder spanning nine decades of resistance and twelve of capacitance, `ac dec 2 1m 1t` is 26 dB off a 70-digit reference at 1 THz, and 613 dB off with `pivrel=1`; Sparse is exact at every point. Starting the sweep at 1 GHz, or `klu_btf=off`, or `klu_scale=none`, or `colamd` all give the exact value — it is the reused order, not KLU | **medium** — wrong AC answers, silent, needs wide dynamic range |
| [F8](#f8--both-solvers-a-floating-node-numbered-after-every-connected-one-is-outside-the-matrix-sparse-writes-past-its-vectors-and-both-report-the-injected-current-as-its-voltage) | `NIinit` creates the matrix with size 0 and lets it grow to the highest node index that carries an element, so a node with no element numbered after all connected ones is simply outside the matrix. Sparse then allocates the RHS vectors one short, the device load writes past them (guard-malloc: **SIGSEGV**; KLU's one spare entry hides it for the operating point but not for `sens`), and both solvers print the injected current as the node's voltage — accumulating across a `dc` sweep — with no warning | **medium** — shared; heap overflow, silent phantom voltage under both |
| [F5](#f5--an-infinite-pivot-hangs-the-determinant-normalisation-in-both-solvers) | the determinant used by pole-zero normalises with `while (Norm >= 1e12) Norm *= 1e-12` in both `spDeterminant` and `spDeterminant_KLU`; an infinite pivot never leaves that loop. NaN is safe, Inf is not | low — latent hang |

## What was read and run

* `klusmp.c` in full (2 362 lines): the COO→CSC conversion, every factor/refactor/solve
  entry for both kinds, the determinant, `SMPfindElt`, the PZ column helpers, the CSR
  multiply. `klu_multiply.c`, `klu_utils.c` (`Compress`, the CSR conversion),
  `klu_extract.c` (`KLU_extract_Udiag`). Sparse's `spFactor` refactor loops (real and
  complex) and the two determinant normalisations in `sputils.c`.
* The analyses that flip the matrix kind: `acan.c`, `noisean.c`, `span.c`,
  `distoan.c`; `cktsetup.c` (conversion, rshunt binding), `cktic.c`, `cktload.c`,
  `cktdojob.c` (E-471 reuse decision), `cktpzset.c`, `cktsopt.c` (option parsing),
  `niiter.c` (gmin flag, NaN handling).
* Sparse itself is stock: `git log` on `src/maths/sparse` shows only E-77's warning
  cleanup, so anything found there is upstream Sparse 1.3 behaviour.
* Systematic checks that came back clean: every one of the 58 device directories with a
  `bindCSC` has all three binding functions (real, complex, complex-to-real), and so
  does XSPICE's `mifbindCSC.c`; the E-152 options `klu_ordering`/`klu_scale`/`klu_btf`
  are keyword-validated; `klu_extract_Udiag` fills unit scale factors when KLU ran
  unscaled; `klu_memgrow_factor=0.5` is harmless; conductances of 1e-15 S solve on both
  solvers; `halt_if_singular` is never overridden, so a singular full factorization
  returns a NULL Numeric and `E_SINGULAR` as intended; pole-zero setup starts from a
  fresh matrix (`NIdestroy`/`NIinit`), so its second `SMPconvertCOOtoCSC` is safe;
  an OSDI device with an omitted optional terminal keeps its private node's column
  populated (the Jacobian pattern is fixed), so F1 does not reach it — verified with the
  `$port_connected` suite's `netterm` model under both solvers; both solvers recover
  from a singular *refactor* by reordering (`niiter.c:233-278`); Sparse's `spFactor`
  routes an unordered matrix to `spOrderAndFactor` before touching `Diag[1]`; a
  behavioural source refuses `sqrt(-1)` at parse time, so that route into a NaN pivot
  is closed; the E-439 / large-circuit rcond guard on `klu_refactor` did not trip once
  on a 200-stage RC ladder with time constants spread over four decades and a diode
  load (`set ngdebug`, 20 µs transient), so it is not forcing needless full
  factorizations on ordinary stiff decks; an OSDI deck (`netterm`, one terminal omitted)
  runs clean under guard-malloc with KLU; the E-111/E-112 line search (which goes
  through `SMPmultiply`'s CSR rebuild under KLU) gives the same operating point and
  the same four iterations on a stiff diode chain under both solvers, and so do E-153's
  trust region (which reads `KLUmatrixDiag` through `SMPdiagNorm`) and E-127's
  pseudo-transient continuation (which loops to `SMPmatSize`) on a cross-coupled BJT
  latch; a common-emitter stage gives the same integrated output noise (the adjoint
  `klu_z_tsolve` path) and the same two poles (the `spDeterminant_KLU` path) under
  both solvers; and the two ordinary singular-at-DC topologies — a node held only by a
  capacitor and a current source, and two ideal inductors in parallel — produce the
  same `singular matrix: check node …` warnings and the same recovered values under
  both; a node named only as a controlled source's control input is refused up front
  with E-492's message under both. The F1 family is specifically about a node with
  **no** entry at all, which is the one case the collapse machinery exists for.
* Some twenty decks, each under both solvers unless the finding is KLU-only by
  construction, and the F1 family once more under guard-malloc. Decks are in the
  findings.

## F1 — a node with no matrix entries makes KLU return wrong voltages for the rest of the circuit, silently

**Deck A** — a node connected only to a current source, numbered in the middle:

```spice
* floating middle node fed only by a current source
.option klu
v1 n1 0 1
r1 n1 n2 1k
i1 0 nx 1m
r2 n2 0 1k
r3 n1 n3 1k
r4 n3 0 1k
.control
op
print v(n1) v(n2) v(nx) v(n3) i(v1)
.endc
.end
```

| | v(n1) | v(n2) | v(n3) | i(v1) | v(nx) | messages |
|---|---|---|---|---|---|---|
| Sparse | 1.000 | 0.500 | 0.500 | −1.000e-3 | 1e-3 | `Note: Dynamic gmin stepping completed` |
| KLU | **0.000** | **0.000** | **5.0e-4** | **+1.000** | 0.5 | none |

The voltage source reads 0 V at its own terminal and sources 1 A into two 1 kΩ
dividers. Nothing is printed.

**Deck B** — the same node as the output of a current-controlled current source
(`f1 0 nx v1 1` in place of `i1`): Sparse prints `singular matrix: check node nx` on
every rung and fails the operating point, which is right (the node has no defined
voltage). KLU prints all four voltages as 0 and `i(v1)` as 1 A, and reports success.

**Deck C** — the floating node numbered *last* (`i1 0 nx 1m` as the last element):
KLU gives v(n1) = 1e-3, v(n2) = 0, i(v1) = 64 A, again silently. Numbered *first*,
KLU reports `singular matrix: check node nx` like Sparse — the only position that is
handled.

**Deck D** — deck A plus `.nodeset v(n3)=0.5` (a normal node, numbered after the
floating one): KLU aborts with `doAnalyses: out of memory` and *"The needed element
doesn't exist in the matrix"* — the diagonal of `n3` is looked up in the shifted column
space and missed.

**Deck E** — the same with the nodeset node as the *last* unknown (no voltage source,
so no branch row follows it):

```spice
.option klu
i1 0 n1 1m
r1 n1 0 1k
i2 0 nx 1m
i3 0 n3 1m
r2 n3 0 1k
.nodeset v(n3)=1
.control
op
.endc
```

Plain run: the same abort. Under macOS guard-malloc
(`DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib`) the run dies with **SIGSEGV
(exit 139)**: `SMPfindElt` (`klusmp.c:2146`) reads `Ap[Col+1]` with `Col+1 = N+1`, one
`int` past the end of the `Ap` allocation, because the node's number is beyond the
shrunken `N`. Decks A–D run clean under guard-malloc; decks E, F and G are the
hard out-of-bounds accesses in the family, and the rest is silent mis-addressing
inside bounds.

**Deck F** — two floating nodes (deck A plus `i2 0 ny 1m` after `r2`), the multi-gap
case whose map E-233 chained: KLU gives v(n1) = 1e-3, v(n2) = 0, **v(n3) = 9.2e81**,
i(v1) = 0. Sparse gives 1 / 0.5 / 0.5 / −1 mA. Under guard-malloc this deck
**crashes (exit 139)**: the map is initialised only at indices that carry a column
(`klusmp.c:245-249`), the second collapse chains through an index that never was
one, and the garbage becomes an RHS subscript in the gather — and, per root cause 3
below, the RHS vectors themselves are two entries short, so the device loads write
past them. Two *adjacent* floating nodes (a gap two columns wide) behave identically:
the same 9.2e81 and the same crash.

**Deck G** — the empty-matrix path (E-492) with a nodeset: `i1 0 a 1m` and
`.nodeset v(a)=1` alone. The conversion leaves `KLUmatrixAp` as one uninitialised
`int` (`klusmp.c:186`); `CKTic`'s `SMPfindElt` reads `Ap[0]` and `Ap[1]` from it, which
guard-malloc turns into a **SIGSEGV** (exit 139); the plain run says `out of memory`.
Sparse says `singular matrix: check node a` and fails the operating point, which is the
right diagnosis for a node held up by nothing.

**Deck H** — the way a user actually meets this: a behavioural current monitor whose
load resistor was forgotten.

```spice
v1 in 0 dc 1
r1 in out 1k
r2 out 0 1k
bmon 0 imon i = i(v1)*1000
r3 in x 2k
r4 x 0 2k
.op
```

Sparse: `Warning: singular matrix: check nodes imon and in`, repeated through gmin
stepping, and the operating point fails — the user finds `imon`. KLU: v(in) = 0,
v(out) = 0, v(x) = 0, v(imon) = 0, no message, and the run continues with a 1 V source
reading zero. Inside a subcircuit it is the same story: Sparse names `x1.imon`, KLU
prints zeros for every top-level node.

Transient and AC inherit all of it: deck A with `ac lin 1 1k 1k` gives vm(n1) = 0
under KLU against 1.0 under Sparse (the complex gather has the same shifted map), and
its transient settles at v(n1) = 1e-3 against 1.0; a `dc v1 0 1 0.5` sweep reports
v(n2) = 0 at every point against 0, 0.25, 0.5; `sens v(n2)` reports zero sensitivity to
`r1` and `r2` against ∓2.5e-4. The result does not depend on the ordering: `klu_btf=off` and
`klu_ordering=colamd` give the same 0 V / 0 V. A trailing CCCS output (deck B's `f1`
as the last element) is wrong the same way, because the voltage source's branch is
numbered after it and the gap is in the middle again. When the floating node really is
the last unknown and its row is not empty (`i1 0 a 1m`, `r1 a 0 1k`, `g1 0 nx a 0 1m`),
the row index lands beyond the shrunken `N`, `klu_analyze` rejects the pattern, and the
user reads `doAnalyses: impossible error - can't occur` where Sparse says
`singular matrix: check node nx`.

**Workaround that exists today, for op and tran only:** `.option rshunt=1e12`
(XSPICE build) makes `CKTsetup` create a diagonal for every node before the conversion,
so no column is empty; deck A then gives 1 V / 0.5 V / 0.5 V under KLU with
v(nx) = 1e9 V, the shunt's honest answer for a floating node. It does not carry into
AC, because of F3: the same deck's `ac` aborts with `doAnalyses: matrix is singular`
under KLU while Sparse gives vm(n1) = 1, vm(n2) = 0.5.

**Root cause.** `SMPconvertCOOtoCSC` (`klusmp.c:241-306`) sizes the matrix from the
largest column index that carries an entry, not from the `size` that `SMPnewMatrix`
was given, and "collapses" any gap between occupied columns. Five things are wrong
with that at once:

1. The node map is built 0-based new→0-based old
   (`NewToOld[MatrixCOO[i].col - col_diff + 1] = NewToOld[MatrixCOO[i].col]`,
   line 280) but consumed as if it were 1-based:
   `Intermediate[i] = RHS[NewToOld[i+1]]` (`SMPsolve`, line 1215; the complex twins at
   1119 and 1169). For columns {0,1,3} with column 2 empty, row 1 is gathered from
   `RHS[3]` and row 2 from `RHS[3]` too — that is the 0 V / 1 A in deck A. The correct
   access would have been `RHS[NewToOld[i] + 1]`.
2. Rows are shifted with the columns (lines 283-285) whether or not the removed node's
   **row** was empty. A CCCS/VCCS output node has an empty column and a non-empty
   row; its KCL row is silently added into the previous node's row (deck B).
3. A trailing floating node is never seen as a gap; `N` is just one smaller than the
   number of unknowns and `KLUmatrixNrhs = N+1` (line 305) makes the RHS zeroing and
   scatter stop short, so the dropped node's stale RHS entry survives (deck C). Worse,
   `NIreinit` (`maths/ni/nireinit.c:31-42`) sizes **every RHS vector** from
   `KLUmatrixNrhs` under KLU — `N+2` doubles — while the devices keep stamping
   `RHS[node]` with the original node numbers. One floating node still fits (the
   `+1` absorbs it); with two, every `CKTload` writes past the end of `CKTrhs`,
   `CKTrhsOld` and their siblings. That heap overflow is what guard-malloc catches in
   deck F and its wide-gap variant, and `snload` (`spiceif.c:2896`) re-sizes the same
   vectors to `SMPmatSize+1`, one shorter again, so a restored snapshot overflows with a
   single floating node.
4. `SMPfindElt`, `SMPcZeroCol`, `SMPcAddCol`, `SMPmultiply`, `SMPmatSize` and the E-127
   pseudo-transient loop in `niiter.c:103-107` all work in the collapsed index space
   while node numbers, RHS and nodesets live in the original one (decks D and E);
   `checkpoint` stores the solution vectors with that collapsed size too
   (`com_checkpoint.c:106`), so a checkpoint of such a deck drops the last unknown.
5. The map is initialised only at indices that carry a column (lines 245-249), so a
   second gap chains through an uninitialised entry and the gather indexes the RHS
   with garbage (decks F and the wide-gap variant); the empty-matrix branch leaves
   `Ap` uninitialised altogether (line 186, deck G).

E-232 (fix B) and E-233 (fix 2) touched exactly this path, made the complex solves
"consistent" with the real one and chained the map for multiple gaps, and both wrote
that the path is unreachable because "an empty MNA column is structurally singular and
does not solve at all". It is reachable by an ordinary netlist mistake — a current
injected into a node nothing else touches — and instead of Sparse's `singular matrix:
check node nx` the user gets a converged, wrong operating point.

**Fix direction.** The collapse buys nothing: KLU handles an empty column itself
(`klu_analyze` records a structural rank deficit and `klu_factor` reports
`KLU_SINGULAR` with the column, which `SMPgetError` already turns into `check node
nx`, as the numbered-first case shows). Take `N` from the size given to
`SMPnewMatrix`, drop the gap search and the map, and the three decks above become the
same diagnosis Sparse gives. If the map is kept for some reason it has to be built and
consumed in one index base, rows must only move when the row is empty too, and
`Nrhs` must stay at the true node count. F8 shows the sizing decision underneath is
shared with Sparse: `NIinit` creates the matrix with size 0, so the fix belongs there.

## F2 — `.ic` or `.nodeset` on a node without a diagonal element aborts every analysis under KLU as "out of memory"

```spice
* .ic on a node that has no diagonal element (between two inductors)
v1 in 0 dc 1 pulse(0 1 0 1n 1n 10u 20u)
l1 in mid 1u
l2 mid out 1u
r1 out 0 1k
c1 out 0 1n
.ic v(mid)=0.5
.nodeset v(out)=0.2
.control
tran 10n 1u
op
print v(mid) v(out)
.endc
.end
```

Sparse runs both analyses (`v(mid) = 1`, `v(out) = 1` at the operating point). KLU:

```
doAnalyses: out of memory
tran simulation(s) aborted
doAnalyses: out of memory
op simulation(s) aborted
Warning: The needed element doesn't exist in the matrix, but KLU mode cannot create a
new element. Please specify an existing element for .ic
```

`.nodeset v(mid)=...` behaves the same, and so does `tran … uic`. A node whose only connections are inductor
branches or voltage sources has no (node,node) entry — the branch equations stamp
(node,branch) and (branch,node) only — and `CKTic` (`cktic.c:38-54`) under KLU does
`SMPfindElt(node,node)` and returns `E_NOMEM` when it is missing. `CKTdoJob` runs
`CKTic` for every job that has `do_ic` (`cktdojob.c:445`), so **every** analysis in the
deck dies, and the message names memory rather than the nodeset. Under Sparse the same
code calls `SMPmakeElt`, which creates the element (`cktic.c:48`).

The same abort happens for the far more ordinary node between a voltage source and
an inductor — `v1 in 0 dc 1`, `l1 in out 1u`, `r1 out 0 1k` with `.nodeset v(in)=1`
gives `doAnalyses: out of memory` / `op simulation(s) aborted` under KLU and runs under
Sparse — and for the tap of two stacked supplies, the most everyday case of all:
`v1 a 0 1`, `v2 b a 1`, `r1 b 0 1k`, `.nodeset v(a)=1` aborts under KLU and gives
1 V / 2 V under Sparse. Inside a `sweep` with setup reuse every point aborts the same
way under KLU while Sparse runs all of them. `.option rshunt=1e12` is again a workaround — every node gets a diagonal at
setup and the deck runs under KLU.

**Fix direction.** The diagonal can be reserved before the conversion: `CKTsetup`
already walks the nodes for the rshunt diagonals (`cktsetup.c:163-170`); doing the same
`SMPmakeElt(node,node)` for every node with `nsGiven` or `icGiven` before
`SMPconvertCOOtoCSC` costs one zero entry per such node and makes `CKTic` find what it
needs. Failing that, the return value should be a named error, not `E_NOMEM`.

## F3 — `.option rshunt` is silently absent from AC, noise, `sp` and disto under KLU

```spice
* .option rshunt in AC: a node loaded only by the shunt
.option rshunt=1k
v1 in 0 dc 0 ac 1
c1 in out 1n
r0 in 0 1k
.control
op
print v(out)
ac lin 1 1k 1k
print vm(out) vp(out)
.endc
.end
```

| | v(out) at op | vm(out) at 1 kHz | vp(out) |
|---|---|---|---|
| Sparse | 0 | 6.283e-3 | 1.5645 rad |
| KLU | 0 | **1.000** | **0** |

With the shunt, `out` is a 1 nF / 1 kΩ high-pass at 1 kHz: |H| = ωRC = 6.28e-3. KLU
reports the unloaded capacitor (|H| = 1). The operating point is right under both, so
the shunt exists in the real matrix.

Noise goes with it. The same topology fed through a noisy 1 kΩ source resistor
(`v1 s 0 ac 1`, `rs s in 1k`, `c1 in out 1n`, `noise v(out) v1 dec 10 100 10k`):

| | onoise_total | onoise_spectrum at 1 kHz |
|---|---|---|
| Sparse | 7.36e-9 | 1.28e-11 |
| KLU | **4.05e-7** | **4.07e-9** |

a factor of 55 in the integrated output noise, no message. Distortion analysis loses
it too: a common-emitter stage whose collector is loaded only by the shunt
(`ic vdd c 1m`, `cl c 0 1n`, `disto dec 3 1k 100k`) reports |v(c)| = 2.27e-4 under
Sparse and 9.62e-2 under KLU at the first frequency. S-parameters as well: a port
terminated only through the shunt (`vp in 0 ac 1 portnum 1 z0 50`, `c1 in x 1n`)
reads |S11| = 0.814 under Sparse and 1.000 — an open — under KLU. And where the shunt
is the only thing holding a node up (deck A of F1 with `rshunt=1e12`), the complex matrix has
a numerically empty column and the AC aborts as singular under KLU while Sparse solves
it.

**Root cause.** `cktsetup.c:190-204` rebinds the rshunt diagonal pointers after the
conversion to `matched->CSC` — the real array — and never to `CSC_Complex`.
`CKTacLoad` (`acan.c:474-478`) then adds `gshunt` through those pointers on every
frequency while the devices are bound to `KLUmatrixAxComplex` and `SMPcReorder`/
`SMPcLUfac` factor that array. Noise, `sp` and distortion share `CKTacLoad`, so they
lose the shunt the same way — the decks above show all four. XSPICE is compiled into
this build, so the option is live.

**Fix direction.** Keep a second pointer set bound to `matched->CSC_Complex` and let
`CKTacLoad` add through it, or add the shunt in `CKTacLoad` via `SMPfindElt`, which
already returns the complex slot while the matrix is flagged complex.

## F4 — an AC-family analysis that returns early leaves the devices bound to the complex arrays

`acan.c:319-327` binds every device to the complex arrays and sets
`KLUmatrixIsComplex`; the switch back is at `acan.c:424-433`, on the success path only.
Between them the sweep returns on an `NIacIter` error (line 337), a sensitivity error
(357), a dump error (367) and an internal error (408) without rebinding. `noisean.c`
(set 477, reset never on the error returns at 501-607), `span.c` (765 → 1020, with
E_NOMEM/E_NOMOD/error returns between) and `distoan.c` (319 → 789, a dozen returns
between) have the same shape. The restart block at `acan.c:255` guards its own bind
with `if (!IsComplex)`, so a `resume` is fine.

When the next job rebuilds the circuit (`cktdojob.c:379-391`: `CKTunsetup`/`CKTsetup`
unless reuse was requested) the stale binding is discarded — confirmed: an AC stopped
by a `stop when frequency > 500` breakpoint followed by an `op` under KLU gives the
right operating point. Under E-471's reuse —
`sweep`/`optimize -analysis ac|noise|sp` — the decision at `cktdojob.c:382` does not
look at the previous job's error, so a point whose small-signal analysis failed hands
the next point's operating point a circuit whose devices load into the complex arrays
while `SMPluFac` factors the real ones. E-499 fixed the sibling mismatch (a real
Numeric refactored as complex) but not this binding one.

**Reproduced through the pause return** (`acan.c:268-271`, `E_PAUSE`, which sits after
the bind at 261 in the restart block and after 327 in the loop):

```spice
v1 in 0 dc 1 ac 1
r1 in out 1k
r2 out 0 1k
c1 out 0 1n
.control
stop when frequency > 500
sweep @r1[resistance] lin 3 1k 3k -analysis ac dec 5 100 10k -output g=mag(v(out))
print g
.endc
```

Sparse: the breakpoint interrupts the AC at each of the three points, `g` is recorded
as 0.500 / 0.333 / 0.250, no warnings. KLU: the first point's AC is interrupted with
the devices bound complex; the second point's operating point then reports
`singular matrix: check node v1#branch` six times through gmin stepping, `out = nan`,
and the sweep says `1 of 3 point did not converge; those points are recorded as NaN`.
The real array the operating point factors was never loaded — every device wrote into
the complex one. The error returns at 337/357/367/408 leave the same state; the
routes I checked for a non-interactive trigger were less convenient (`span.c:808`'s
`E_NOMOD` needs a circuit with no voltage source at all, and an LC resonance is never
*exactly* singular at a sampled frequency, so KLU's exact-zero halt does not fire).

A `.param` knob (`sweep rr lin 3 1k 3k …` with `r1 in out {rr}`) fails the same way
— point 2 is `nan` — so both of E-471's reuse paths carry it.
`sweep -analysis sp` behaves like AC: with the breakpoint, point 1 gives |S11| =
0.951, point 2 is `nan` after `The operating point could not be simulated
successfully`, point 3 recovers at 0.975. The same breakpoint inside
`sweep -analysis noise` and `sweep -analysis disto` pauses the points without a
singular operating point, so their pause returns are not harmful in the same way —
`noisean.c:422` returns `E_PAUSE` after the same bind at 407-410, so the reason lies
elsewhere and was not established in the hour; the error returns at
`noisean.c:501-607` were not exercised.

**Workaround that exists today:** `set noreusesetup` before the `sweep` (E-471's
escape hatch) rebuilds the circuit for every point; the same deck, with either knob
kind, then records 0.500 / 0.333 / 0.250 under KLU with no warning.

**Fix direction.** Rebind to real in `CKTdoJob` when a job returns (error or pause)
while `KLUmatrixIsComplex` is set, or refuse reuse after a job that did not complete;
either is a few lines next to the reuse decision at `cktdojob.c:382`.

## F7 — KLU's AC loses accuracy across a wide sweep because every point reuses the first frequency's pivot order

```spice
* wide dynamic range RC ladder: fixed pivot order across 15 decades of frequency
v1 in 0 dc 0 ac 1
r1 in n1 1
c1 n1 0 1e-06
r2 n1 n2 1000.0
c2 n2 0 1e-09
r3 n2 n3 1000000.0
c3 n3 0 1e-12
r4 n3 n4 1000000000.0
c4 n4 0 1e-15
r5 n4 n5 10
c5 n5 0 1e-18
r6 n5 n6 10000.0
c6 n6 0 1e-07
r7 n6 n7 10000000.0
c7 n7 0 1e-10
r8 n7 n8 100
c8 n8 0 1e-13
r9 n8 n9 100000.0
c9 n9 0 1e-16
r10 n9 n10 100000000.0
c10 n10 0 1e-08
rl n10 0 1e12
.control
ac dec 2 1m 1t
let m = vdb(n10)
print m
.endc
.end
```

A 70-digit tridiagonal solve (Python `decimal`, Thomas algorithm) is the reference.
Sparse reproduces it to the printed digits at every one of the 31 points, with the
default `pivrel` and with `pivrel=1`. KLU:

| index | f (Hz) | reference vdb(n10) | KLU, default `pivrel=1e-3` | KLU, `pivrel=1` |
|---|---|---|---|---|
| 18 | 1e6 | −436.13 | +0.00 | +0.01 |
| 21 | 3.2e7 | −615.80 | +0.00 | **+42.48** |
| 24 | 1e9 | −795.85 | −0.00 | **+175.48** |
| 27 | 3.2e10 | −996.63 | +0.11 | **+375.33** |
| 30 | 1e12 | −1263.69 | **−26.17** | **+613.26** |

(errors in dB against the reference). The phase goes with it: at 1 THz Sparse reports
−1.523 rad and KLU +0.032 rad. The same deck swept from 1 GHz (`ac dec 2 1g
1t`) gives −1263.69 at 1 THz under KLU; so do `klu_btf=off`, `klu_scale=none` and
`klu_ordering=colamd` over the full sweep — and each of the three also makes the
milder ladder exact with `pivrel=1`, so it is the default AMD + BTF + max-scaling
combination whose first-frequency order goes bad, not KLU as such. What differs is only *which* pivot order was
frozen at the first frequency: with `pivrel=1` the first factorization pivots purely by
magnitude at 1 mHz, which is the worst possible order once `jωC` dominates, and the
error begins at 30 MHz. S-parameters inherit it: with 50 Ω ports at `in` and `n10`,
`sp dec 2 1m 1t` puts |S21| at 1 THz at −1291.8 dB under Sparse, −1276.4 dB under KLU,
and −674.5 dB under KLU with `pivrel=1` (already −656.5 against −824.0 at 1 GHz). A
milder ladder — the same ten sections with resistances spread over six decades
(1 Ω to 1 MΩ) and capacitances over eight — is exact under KLU's default `pivrel` but
already 81 dB off at 1 GHz and 539 dB off at 1 THz with `pivrel=1`, and 3.4 dB off at
1 THz with the moderate `pivrel=0.1` or `0.01` that a user might try for accuracy; a
ladder of ten
equal 1 kΩ resistors with capacitances spread over nine decades is exact under every
setting, so the resistance spread is what makes the first frequency's order unusable
later. Putting a unity VCVS buffer in the middle of the wide-range ladder makes it worse, not
better: **109 dB** off at 1 THz with the default `pivrel` (−1372.8 against −1263.7)
and 113 dB off already at 1 GHz with `pivrel=1`. A three-section ladder and a
three-stage VCVS amplifier show no error, and the noise spectra of these ladders, output- and input-referred, agree between the
solvers even where the AC gain is 109 dB apart (noise takes its transfers from the
adjoint solve and from the output node's own sources; why that path is immune was not
established); the defect needs a deep, wide-range network — the sort a
transmission-line or package model produces.

What a user would see: on the buffered chain, `meas ac f1200 when vdb(n10)=-1200`
with `ac dec 20 1m 1t` returns 443 GHz under Sparse and 361 GHz under KLU, and with
`pivrel=1` the measurement fails because KLU's curve never reaches the level.

The real path does not share the outcome: a pulse transient on the same ladder
(`tran 1n 10m`, step sizes spanning ten decades) agrees between the solvers at every
probe under both `pivrel` settings, because the E-439 guards force a fresh pivot order
whenever the reused one degrades.

**Workaround that exists today:** split the sweep. `ac dec 2 1meg 1g` followed by
`ac dec 2 1g 1t` gives −795.85 and −1263.69 under KLU, with the default `pivrel` and
with `pivrel=1`, because each segment starts with a fresh factorization; three decades
per segment was enough here. How bad the frozen order is depends on how resistive the matrix was when it was
chosen: with the default `pivrel`, starting the same sweep at 1 Hz instead of 1 mHz
already gives the exact 1 THz value, while with `pivrel=1` starts at 1 Hz and 1 kHz
are still 264 dB off (−999.6) and only a start at 1 MHz is exact. A second, odder
confirmation: add any `hertz`-dependent
source to the deck (`bh dummy 0 v = 0*hertz` with a resistor to ground) and ngspice
recomputes the operating point at every frequency (`CKTvarHertz`, `acan.c:276-330`),
which flips the binding real→complex each time and so performs a full complex
factorization per point — the ladder is then exact under KLU with either `pivrel`.
Inside `sweep -analysis ac` with setup reuse the error is the same at every sweep
point (−1289.86 three times against −1263.69) and does not compound, because the
operating point between points flips the Numeric back to real and the next AC starts
with a fresh complex factorization at its first frequency.

**Root cause.** `NIacIter` factors the first point with `SMPcReorder` (`klu_z_factor`,
partial pivoting with the *current* values) and every later point with `SMPcLUfac` →
`klu_z_refactor` (`klusmp.c:603`), which refills the frozen `L`/`U` pattern and pivot
order with no pivoting and no test. The real path has had E-439's `klu_rcond` check
and the large-circuit relative-rcond drop test since 2026-09-04 (`klusmp.c:762-806`);
the complex path (`klusmp.c:607-632`) has neither, so nothing ever asks `NIacIter` to
reorder (it does so only on `E_SINGULAR`, `maths/ni/niaciter.c:63-80`); with `set ngdebug` the sweep prints nothing. Sparse's `spFactor` also reuses
its order across the sweep; its Markowitz/diagonal ordering happens to stay stable on
this network, so the mechanism is shared and only KLU's outcome is visible here.

**Fix direction.** Mirror E-439 in `SMPcLUfac`: after a successful `klu_z_refactor`
call `klu_z_rcond` (compiled in `libKLU_complex`, currently unreferenced) and return
`E_SINGULAR` when rcond collapses relative to the last full complex factorization, so
`NIacIter` re-pivots at the current frequency; record that reference in `SMPcReorder`
the way `klu_note_factor_rcond` does for the real path. That test will also trip when
the matrix's own conditioning moves with frequency, which is exactly when a fresh order
is wanted, at the price of a few extra full factorizations across a wide sweep. A
cheaper complement is to reorder whenever the sweep has moved a decade since the last
full factorization. Distortion's `NIdIter` (`maths/ni/niditer.c:44-62`) has the same
reorder-only-on-`E_SINGULAR` shape and would take the same guard.

## F8 (both solvers) — a floating node numbered after every connected one is outside the matrix: Sparse writes past its vectors, and both report the injected current as its voltage

```spice
* trailing floating node in a circuit without branch rows
i1 0 n1 1m
r1 n1 0 1k
r2 n1 n2 1k
r3 n2 0 1k
i2 0 nx 2m
.control
op
print v(n1) v(n2) v(nx)
.endc
.end
```

Both solvers print v(n1) = 0.6667, v(n2) = 0.3333 and **v(nx) = 2.000e-3** — the
2 mA of `i2` read back as volts — with no warning of any kind. Under guard-malloc the
Sparse run dies with **SIGSEGV (exit 139)** — lldb puts the fault in `ISRCload`, the
current source stamping `CKTrhs[node]` one entry past the vector (a source with
`dc 0` faults the same way — it is the write, not the value — and so does every other
analysis on the deck, `sens` included, because the operating-point load comes first);
the KLU run survives only because
`NIreinit` gives KLU one spare RHS entry (`KLUmatrixNrhs = N+1`, then `size+1`) —
and only for the plain operating point: `sens v(n2)` on the same deck crashes under
guard-malloc with KLU as well, its sensitivity matrix and vectors being sized from
`SMPmatSize` without that spare.
A `dc` sweep of that source (`dc i2 0 4m 1m`) makes the symptom unmistakable under
both solvers: v(nx) reads 0, 1e-3, 3e-3, 6e-3, 1e-2 — the running sum of the swept
currents, because the entry past the solver's idea of the vector is never zeroed
between points. With two trailing floating nodes
Sparse prints v(nx) = 2e-3 and v(ny) = 0 (the
second stamp lands two entries past the vector) and still crashes under guard-malloc.
AC and transient do the same under both solvers: with
`i2 0 nx dc 2m ac 3 pulse(0 4m …)` the node reads vm(nx) = 3.006 at 1 kHz and
v(nx) = 1.24e-3 mid-pulse — whatever current the source stamps at that moment. The all-empty deck (`i1 0 a ac 1 dc 1m`
alone) is the same under Sparse: v(a) = 1e-3,
vm(a) = 1.003 at any frequency, gmin and gshunt irrelevant, SIGSEGV under
guard-malloc; KLU refuses it with E-492's note. Put a `.nodeset` on the trailing node
and the picture changes under Sparse — `CKTic` creates its diagonal, the matrix grows
to include it, and the run says `singular matrix: check node nx` six times before gmin
stepping settles at the honest 2e9 V (2 mA into 1 pS) — while KLU aborts with F2. A
node can only be trailing in a deck without voltage sources or inductors, because
their branch rows are numbered after all nodes; with any branch present the same node
becomes an interior gap, which is F1 under KLU and the silent gmin pass-through under
Sparse.

**Workaround that exists today:** `.option rshunt=1e12` (XSPICE build) gives every
node a diagonal at setup, so the matrix reaches the last node; both solvers then report
v(nx) = 2e9 V (2 mA into the shunt), the other nodes are unchanged, and guard-malloc is
clean.

**Root cause.** `NIinit` (`maths/ni/niinit.c:43`) calls `SMPnewMatrix(matrix, 0)`:
the matrix is created with size 0 and grows as `spGetElement`/`SMPmakeElt` see
indices (`spbuild.c:435-444` for Sparse, the COO maximum for KLU). Its size is
therefore the highest node index that carries an element, not `CKTmaxEqNum`.
`NIreinit` (`nireinit.c:29-42`) sizes `CKTrhs`, `CKTrhsOld` and their siblings from
that number, every device keeps stamping `RHS[node]` with the original node numbers,
and `spSolve` never touches an entry beyond `Size` — so the current source's stamp is
returned as the voltage. An interior floating node (deck A of F1) does land inside the
matrix as an empty column: under Sparse the first Newton attempt fails without a
message, gmin stepping starts, every rung from 1e-8 down to 1e-12 reports "one
successful gmin step" (`set ngdebug`), and the node still comes out at v = I. The
likely route: Sparse's row/column exchange creates a missing diagonal element on the
fly (`spcFindElementInCol(…, YES)` in `ExchangeRowsAndCols`, `spfactor.c:2068-2077`),
gmin is then added to that zero, and the column factors; why the final value is the
current itself rather than I/gmin was not traced in the hour. Sparse names a node as
singular only when its row is not empty too (deck B). A
trailing one is invisible to both.
F1's trailing case (deck C) and its empty-matrix case (deck G) are the KLU face of the
same sizing decision.

**Fix direction.** `NIinit` runs before the device setups that create branch
equations (`cktsetup.c:104` against `:136`), so the count is not known there; the place
is `CKTsetup` after the setups, before `SMPconvertCOOtoCSC`/`SMPpreOrder` at `:182` —
grow the matrix to `CKTmaxEqNum` — together with `NIreinit` (`:229`) sizing the RHS
vectors from `CKTmaxEqNum` rather than from `SMPmatSize`. Every node then owns a
column; the trailing node
behaves like an interior empty column under both solvers, the RHS vectors are sized
from the node count, and the out-of-bounds write is gone. Whether an empty column
should be a hard "singular matrix: check node" instead of a gmin-stepped v = I is a
second, smaller decision — Sparse's `MatrixIsSingular` already names the column, so
letting that verdict through instead of retrying under gmin would give the user the
diagnosis. This is one line in `NIinit` plus the F1 removal of KLU's collapse.

## F5 — an infinite pivot hangs the determinant normalisation in both solvers

`klusmp.c:1841-1854` (complex) and `1914-1923` (real), copied from `sputils.c:914-924`
and `968-975`:

```c
while (Norm >= 1.0e12) { cDeterminant.Real *= 1.0e-12; ... Norm = NORM(cDeterminant); }
```

`Inf * 1e-12` is `Inf`, so a single infinite pivot (an `Inf` matrix entry from a device
or an overflowed `s·C` product in a pole-zero trial) never leaves the loop and
`*pExponent` overflows. A NaN pivot is safe (both comparisons are false). Only
pole-zero calls the determinant, so the exposure is small, but the guard is one line.

## Second hour (12:15–13:15): what was added

* **Guard-malloc sweep of the repo's own suites under KLU.** With the harness's
  `NGSPICE_BIN` pointed at a wrapper that inserts `libgmalloc`, the solver-centric
  suites `solverfix`, `klupz`, `klu_tuning`, `noisejw`, `linesearch`, `groundcontrib`,
  `hierbranch`, `checkpoint`, `analyses` and the OSDI-heavy `paramsetlrm`,
  `portconnected`, `genhier` all pass with no crash: the glue is memory-clean on
  well-formed circuits; the F1 family is what it takes to reach the bad accesses.
* **Block-triangular parity.** A unilateral VCVS chain (three BTF blocks with
  off-diagonal blocks) gives identical AC, noise (`klu_z_tsolve` through the
  off-diagonal `F` blocks) and pole-zero results under both solvers.
* **Pivot thresholds.** `pivrel=1`, `pivtol=1e-3`, `pivrel=1e-9 pivtol=0` change nothing
  on a stiff diode chain under either solver; KLU's ignoring of `pivtol` has no visible
  effect there.
* **Compact models do not show F7 at these ranges.** An OSDI HiCUM L2 common-emitter
  stage and an OSDI BSIM4 common-source stage swept 1 mHz–1 THz agree between the
  solvers at every printed point, with the default `pivrel` and with `pivrel=1`; Sparse
  stays exact on the wide-range ladder even with `pivrel=1e-9 pivtol=0`.
* **More guard-malloc coverage.** The F4 sweep decks (device knob and `.param` knob,
  with and without the breakpoint), deck A inside a `sweep` with setup reuse, and a
  balanced pole-zero on deck A all run without an out-of-bounds access; the balanced
  pole-zero even agrees between the solvers, because `CKTpzSetup` rebuilds its own
  matrix and the floating node's RHS never enters the determinant.
* **Tuning options and the determinant.** `klu_scale=none`, `klu_btf=off` and
  `klu_ordering=colamd` leave the common-emitter stage's poles and output noise
  unchanged, so `spDeterminant_KLU`'s handling of the scale factors and of the block
  structure is sound.
* **Pivot reuse on the real path holds.** The wide-range ladder's pulse transient, a
  stiff network with a switch toggling eighteen decades of conductance, the ladder's
  ten poles (`pz`, which re-pivots every trial), and its input-referred noise all agree
  between the solvers; only the complex refactor path shows F7.
* **F7 and F8.** The wide-dynamic-range ladder swept over fifteen decades, checked
  against a 70-digit reference, gave the hour's KLU finding (F7, after F4); a one-line
  edge-case deck at the very end gave the shared one (F8, after F7): the matrix is
  created with size 0 in `NIinit` and grows only to the highest node that carries an
  element, which is the root under F1's trailing case as well.
* **XSPICE code models** (loaded through the build's `_spicelib/scripts/spinit`): a
  `gain` stage and an `int` stage give the same op and AC under both solvers, so the
  MIF complex binding works. Which surfaced F6 below.

## F6 (side finding, not solver core) — a batch run with two XSPICE code models and an AC aborts on exit

```spice
v1 in 0 dc 0.2 ac 1
a1 %v(in) %v(mid) xg
.model xg gain(gain=2.5)
r1 mid x 1k
c1 x 0 1n
a2 %v(x) %v(out) xint
.model xint int(gain=1e5 out_lower_limit=-10 out_upper_limit=10)
r2 out 0 1k
.control
op
ac lin 1 1k 1k
print vm(out)
.endc
.end
```

`ngspice -b` exits with **134 (SIGABRT)** under both solvers and the buffered `print`
output is lost; lldb shows `malloc: pointer being freed was not allocated` raised from
`main` on the normal end-of-batch path, after the simulation completed. Add `quit` to
the control block and the run exits 0 with the right numbers; drop the `op`, use an
`.ac` card instead of the control-block `ac`, run `tran` instead, or remove either code
model or the capacitor between them, and it does not happen. So it is a teardown
double-free in the frontend/XSPICE path after op + AC on this topology, not a wrong
answer, and it belongs to an XSPICE hunt; noted here because a CI script sees a
failed exit code and no output.

## Status after the fixes (2026-09-06, build of 13:25)

Seven of the eight are fixed in the tree; the regression suite
[`examples/solvercore_examples/`](../../examples/solvercore_examples/) pins them on both
solvers (17 checks per solver).

| # | fix | where |
|---|---|---|
| F1, F8 | `CKTsetup` gives every node that owns no matrix entry a zero diagonal (with a warning naming it) and every `.nodeset`/`.ic` node its diagonal, then tells the solver the true unknown count; KLU's `SMPconvertCOOtoCSC` no longer collapses columns and sizes itself from the hint and the largest index seen, the solves use the identity map, `SMPfindElt` is bounded; Sparse gains `spEnsureNode` (a `Translate` without an element); `NIreinit` never sizes the vectors below the node numbering; the pole-zero setup is deliberately left without the hint (its reduced matrix has no source branches, and the hint made every PZ run "shorted") | `cktsetup.c`, `klusmp.c`, `spbuild.c`, `spmatrix.h`, `smpdefs.h`, `nireinit.c`, `cktpzset.c` |
| F2 | covered by the diagonals above; `CKTic`'s message names the node and returns `E_NOTFOUND` instead of `E_NOMEM` | `cktic.c` |
| F3 | `CKTacLoad` adds the shunt through `SMPfindElt`, which returns the live slot for the matrix's current kind | `acan.c` |
| F4 | `CKTdoJob` rebinds the devices to the real arrays after any analysis returns while the matrix is flagged complex | `cktdojob.c` |
| F5 | `isfinite` on the four normalisation loops | `sputils.c`, `klusmp.c` |
| F7 | `SMPcLUfac` runs `klu_z_rcond` after every successful complex refactor and returns `E_SINGULAR` on a zero or a collapse relative to the last full complex factorization (recorded by `SMPcReorder` and the E-499 full-factor branch); `NIacIter` re-pivots silently on that code and warns only if the fresh factorization is singular too | `klusmp.c`, `niaciter.c`, `klu.h` |
| F6 | **open** — the XSPICE batch-exit double free is outside the solver core; the file-name ownership path was ruled out and the writer was not found in the time box | — |

After the fixes every deck in this report gives the same numbers under KLU and Sparse:
the floating node reads I/gmin (2 mA into 1 pS is 2e9 V) with `singular matrix: check
node` naming it, the nodeset decks run, the shunt is present in ac/noise/sp/disto, the
paused sweep records all its points, the wide-range ladder is within 0.05 dB of the
70-digit reference with either `pivrel`, and guard-malloc is clean on all of them. The
F7 guard forced one extra full factorization on the 31-point ladder sweep, two on the
buffered chain and none on an ordinary common-emitter AC. The control decks, eleven
solver-centric and OSDI suites are unchanged, and the full regression sweep is 464 of 464 (the first pass caught two things the fixes had to respect: E-492's single note for a circuit with no matrix at all, and pole-zero's reduced matrix).

## Smaller notes (not pursued)

* `SMPsolve` (`klusmp.c:1222-1250`) prints when `klu_solve` fails and then scatters
  the untouched intermediate vector into the RHS as if it were a solution; the `FIXME`
  at line 1233 says as much. `SMPcSolve`/`SMPcaSolve` assign `ret` and never look at it.
* `SMPconvertCOOtoCSC` frees the COO linked list (line 214) but leaves
  `KLUmatrixLinkedListNZ` and `KLUmatrixLinkedListCOO` pointing at it; a second
  conversion of the same matrix, or the PZ union reservation (`cktpzset.c:114-117`)
  on a converted matrix, would walk freed memory. Today every caller starts from a
  fresh `SMPnewMatrix`, so it is fragility, not a bug.
* `SMPdestroy` frees the CSC arrays but not an unconverted COO list, so a setup that
  errors out between `SMPnewMatrix` and the conversion leaks it.
* `SMPzeroRow` has no KLU branch (it would dereference `SPmatrix`, NULL under KLU)
  and translates a *row* through `ExtToIntColMap`. It has no callers.
* `SMPcProdDiag` returns `spError(SPmatrix)` under KLU, i.e. `spNO_MEMORY`. No callers.
* `SMPluFacKLUforCIDER` (`klusmp.c:854-864`) reads `Common->status` before its
  `Common == NULL` check — the E-232/E-233 class in the one function they skipped.
  CIDER is not in this build.
* The complex refactor (`SMPcLUfac`) has no E-439 rcond guard: a NaN pivot produced
  by `klu_z_refactor` passes as success exactly as the real one did before E-439.
  Sparse's refactor tests `== 0.0` and lets NaN through too (`spfactor.c:404,428,521`).
* KLU ignores `.option pivtol`; only `pivrel` reaches `Common->tol`
  (`NG_IGNORE(PivTol)` in `SMPluFac`/`SMPcLUfac`, and `SMPreorder` never uses it).
  Sparse applies it as `AbsThreshold`. Not wrong, but undocumented as far as I looked.
* `SMPmultiply` under KLU rebuilds a CSR copy of the whole matrix (two `qsort`s and
  three `malloc`s) on every call; the E-112 line search calls it per merit evaluation.
  Performance only.

## Coverage, honestly

Read closely: the glue, the repo's KLU additions, the flag-switching analyses, the
setup/ic/load paths that hold raw matrix pointers, Sparse's refactor loops and
determinant. Skimmed or not read: `klu_kernel.c`, `klu_factor.c`, `klu_analyze.c`,
`btf_*.c`, `amd_*.c`, `colamd.c` (upstream SuiteSparse), `spfactor.c`'s ordering and
Markowitz search, `spbuild.c`, `spalloc.c`; `spsolve.c` only for its gather/scatter
index handling. Not exercised: F4's non-interactive triggers and CIDER. The second hour added the
guard-malloc sweep of twelve suites, XSPICE code models in AC (through the build's own
`spinit`), the checkpoint suite under guard-malloc, some forty more decks around F7,
and the trailing-node family behind F8 (op, dc, ac, tran, sens, noise, with and
without nodeset, rshunt, one and two floating nodes); the KLU and Sparse kernels
themselves are still read only where a finding led into them. Every number above came from the build named in the header on this
machine and is reproducible from the inline decks.
