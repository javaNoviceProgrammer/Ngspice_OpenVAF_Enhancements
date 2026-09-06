# Enhancement-566: solver core — a floating node names itself instead of corrupting the solve, the matrix spans every node, and KLU's complex refactor is guarded (bug hunt F1–F5, F7, F8)

**Scope:** the seven solver-core defects of the
[2026-09-06 KLU/Sparse bug hunt](../docs/bug_hunts/2026-09-06_klu-sparse-solver-cores.md)
that belong to the solvers: the KLU glue (`src/maths/KLU/klusmp.c`, `src/include/ngspice/klu.h`),
the Sparse builder (`src/maths/sparse/spbuild.c`, `src/include/ngspice/spmatrix.h`), the
determinant normalisation in both (`src/maths/sparse/sputils.c`, `klusmp.c`), the
Newton/AC iterators (`src/maths/ni/{nireinit,niaciter}.c`), and the setup, ic, AC-load and
job paths that hold matrix pointers (`src/spicelib/analysis/{cktsetup,cktic,cktpzset,acan,cktdojob}.c`,
`src/include/ngspice/smpdefs.h`). **ngspice only.** F6 of the hunt, an XSPICE batch-exit
double free, is not a solver defect and stays open.

**Suites:** new [`solvercore_examples`](../examples/solvercore_examples/) (17 checks per
solver, both solvers, also clean under guard-malloc); `solverfix`, `klupz`, `klu_tuning`,
`noisejw`, `linesearch`, `checkpoint`, `analyses`, `groundcontrib`, `hierbranch`,
`ctrlnode`, `pzhb`, `portconnected`, `paramsetlrm` pass; full sweep 465 of 465 on both
solvers. The bug-hunt write-up carries a "status after the fixes" section.

## What was wrong

Six user-visible defects and one latent hang, all found by reading the glue and running
small decks under both solvers:

* **F1 (KLU, high).** A node that owns no matrix entry — fed only by a current source, the
  output of a controlled current source, a behavioural current monitor whose load resistor
  was forgotten — made `SMPconvertCOOtoCSC` "collapse" its column. The new→old node map was
  built 0-based and consumed 1-based, rows were merged with their neighbours whether or not
  they were empty, a trailing node was dropped, and the RHS vectors were sized from the
  collapsed count. Every other node's voltage came out wrong with no message: a 1 V source
  read 0 V and sourced 1 A, in op, dc, tran, ac and sens; with two such nodes the device
  loads wrote past the RHS vectors. E-232 and E-233 had touched this path and called it
  unreachable.
* **F8 (both solvers, medium).** The matrix is created with size 0 (`NIinit`) and grows to
  the highest node index that carries an entry, so the same node numbered after every
  connected one was outside the matrix altogether: Sparse allocated the RHS vectors one
  short and `ISRCload` wrote past them (guard-malloc SIGSEGV), and both solvers printed the
  injected current as the node's voltage, accumulating across a `dc` sweep.
* **F2 (KLU, medium-high).** `.ic` or `.nodeset` on a node without a diagonal element — the
  tap between two stacked voltage sources, a node between two inductors, a source feeding an
  inductor — aborted every analysis in the deck as "out of memory": `CKTic` looked the
  diagonal up with `SMPfindElt`, which cannot create, and returned `E_NOMEM`.
* **F3 (KLU, medium).** `.option rshunt` was bound to the real value array only;
  `CKTacLoad` added it there while the complex array was factored, so ac, noise, `sp` and
  disto ran without the shunt (a 55× error in output noise, |S11| = 1 for a shunted port).
* **F4 (KLU, medium).** AC, noise, `sp` and disto bound every device to the complex arrays
  and back only on their success path. A breakpoint or error in between left the binding
  complex; under E-471's setup reuse the next `sweep` point's operating point loaded the
  complex array while the real one was factored — singular, NaN recorded.
* **F7 (KLU, medium).** Every AC point after the first was a `klu_z_refactor` with the pivot
  order frozen at the first frequency and no numerical check. On a ten-section RC ladder
  spanning nine decades of resistance the response at 1 THz was 26 dB off a 70-digit
  reference, 613 dB off with `pivrel=1`, the phase 90° off, S-parameters with it; Sparse was
  exact at every point.
* **F5 (both, latent).** The determinant normalisation `while (Norm >= 1e12) Norm *= 1e-12`
  never terminates for an infinite pivot.

## What changed

* **The matrix agrees with the node numbering.** After the device setups, `CKTsetup` asks
  the solver which unknowns own a column (`SMPmarkOccupied`), gives every node that owns none
  a zero diagonal element and says so once — *node 'nx' is connected to nothing that
  conducts; it is held only by gmin* — gives every `.nodeset`/`.ic` node its diagonal, and
  tells the solver the true unknown count (`SMPsizeHint`). A circuit with no matrix at all
  keeps Enhancement-492's single note. The floating node is then a real, singular column
  that gmin stepping holds up: both solvers print `singular matrix: check node nx`, the
  other nodes are exact, and the node reads I/gmin — the same thing Sparse already did once
  a `.nodeset` had created the diagonal.
* **KLU's conversion no longer collapses anything.** `SMPconvertCOOtoCSC` sizes the matrix
  from the hint and the largest row or column index seen, keeps empty columns as empty
  columns, and the three solves use the identity map (node i is RHS entry i+1). The
  empty-matrix branch initialises `Ap[0]` and keeps the RHS span; `SMPfindElt` refuses a
  column beyond N instead of reading past `Ap`. Sparse gains `spEnsureNode`, a `Translate`
  without an element, so the hint maps every node; `NIreinit` never sizes the vectors below
  `CKTmaxEqNum-1`. The pole-zero setup is deliberately left without the hint: PZ builds a
  reduced matrix in which the sources have no branch equations.
* **`CKTic`** names the node and returns `E_NOTFOUND` in the case that should no longer
  occur.
* **`CKTacLoad`** adds the shunt through `SMPfindElt`, which returns the live slot for the
  matrix's current kind — the complex one during an AC-family analysis under KLU, the same
  element as before under Sparse.
* **`CKTdoJob`** rebinds the devices to the real arrays after any analysis returns while the
  matrix is flagged complex, whatever it returned.
* **`SMPcLUfac`** runs `klu_z_rcond` after every successful complex refactor and returns
  `E_SINGULAR` on a zero or on a collapse by more than 1e-6 relative to the last full complex
  factorization, which `SMPcReorder` and the E-499 full-factor branch now record; `NIacIter`
  answers with a fresh, silently re-pivoted factorization and warns only if that one is
  singular too (`NIdIter` already did). One extra full factorization on the 31-point ladder
  sweep, two on a buffered chain, none on an ordinary common-emitter AC.
* **`isfinite`** guards the four normalisation loops.

## Verification

| check | result |
|---|---|
| deck A (`i1 0 nx 1m` beside two dividers), CCCS output, two floating nodes, a monitor inside a subcircuit | 1 V / 0.5 V / 0.5 V on both solvers (KLU gave 0 / 0 / 0, i(v1) = 1 A; two nodes gave 9.2e81); `check node nx` and the setup warning name the node; v(nx) = I/gmin |
| the trailing node (`i2 0 nx 2m` last, no branch rows), op and `dc i2 0 4m 1m` | 2/3 V, 1/3 V, v(nx) = 2e9 on both (was 2e-3, the current read as volts); the sweep scales 2:1 instead of summing; guard-malloc clean on both (Sparse faulted in `ISRCload`) |
| `.nodeset` on the tap of stacked supplies; `.ic` between two inductors with `tran` then `op`; `.ic` on a VCVS output | 1 V / 2 V, 1 V / 1 V, 2 V / 2 V under KLU (every one was `doAnalyses: out of memory`) |
| `.option rshunt=1k` in ac, noise, sp | |v(out)| = 6.283e-3, onoise = 7.365e-9, |S11| = 0.814 under KLU, equal to Sparse (were 1.0, 4.05e-7, 1.000) |
| `stop when frequency > 500` inside `sweep -analysis ac` and `sp`, device and `.param` knobs | all three points recorded under KLU (point 2 was NaN) |
| the wide-range ladder, `ac dec 2 1m 1t`, default `pivrel` and `pivrel=1`; the buffered chain; S21 through two ports | within 0.05 dB of the 70-digit reference at 1 GHz and 1 THz (were −26 dB and +613 dB off; the chain 109 dB); Sparse unchanged |
| controls: common-emitter noise and poles, a VCVS chain, HiCUM and BSIM4 stages over fifteen decades, line search, trust region, continuation, a switched network, a one-node matrix | unchanged and identical across solvers |
| `solvercore_examples`; thirteen suites; full sweep; the new suite under guard-malloc | 17 / 17 both solvers; all pass; 465 of 465; clean on both |
