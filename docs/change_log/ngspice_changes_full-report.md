# ngspice-46 — Full Change Report

**Every modification applied to ngspice-46 in this project, with its
reason.** The baseline is the pristine ngspice-46 source tree (as vendored
in the project's `original/` snapshot, which already contains
OpenVAF-Reloaded's stock OSDI support); the current state is the tree
committed in this repository under `ngspice-46/`. Each entry links the
enhancement write-up in [`enhancements_doc/`](../../enhancements_doc/) that
carries the full engineering detail and the verifying example suite. The
companion document
[openvaf_changes_full-report.md](openvaf_changes_full-report.md) covers
the compiler side.

> **Maintenance note:** this report is updated whenever an enhancement
> touches ngspice sources. If you are reading it alongside a newer tree,
> the per-enhancement index at the end tells you the last change it
> covers.

**Scope summary.** One new source file and 41 modified ones carry all the
functional changes (~2,000 substantive diff lines). A further ~100
`Makefile.in` files and `config.h.in` differ only because the autotools
were regenerated with a current libtool
([E-77](../../enhancements_doc/Enhancement-77.md)); they contain no
hand-written changes and are not listed individually. Everything below is
behavior, interface, or diagnostics.

---

## 1. The OSDI ABI, version 0.4 → 0.7

`src/osdi/osdi.h` is the authoritative C contract between ngspice and the
`.osdi` objects `openvaf-r` produces. The project extended it four times —
twice additively (new exported symbols old loaders simply never look up),
twice with genuine version bumps (layout changes):

| Change | Kind | Enhancement | Why |
|---|---|---|---|
| `OSDI_ABSDELAY_COUNTS` / `OSDI_ABSDELAY_INFOS` exports | additive symbols | [E-1](../../enhancements_doc/Enhancement-1.md) | `absdelay()` needs simulator-side waveform history and synthetic delay-equation rows; the descriptors tell ngspice which nodes/offsets each delay slot uses |
| `OSDI_LAST_CROSSING_COUNTS` / `OSDI_LAST_CROSSING_INFOS` exports | additive symbols | [E-6](../../enhancements_doc/Enhancement-6.md) | `last_crossing()` needs waveform history and crossing interpolation — same additive pattern as absdelay |
| `OsdiNode.nodeset` field | **ABI 0.5** (node stride change) | [E-45](../../enhancements_doc/Enhancement-45.md) | Verilog-A net initializers (`electrical a = 5.0;`) become solver initial-guess nodesets; every node record carries the hint |
| `num_ac_stim_src` / `ac_stim_sources` / `load_ac_stim` descriptor tail | **ABI 0.6** (descriptor grows) | [E-51](../../enhancements_doc/Enhancement-51.md) | full `ac_stim()` support: a Verilog-A module can *be* the AC stimulus, so the descriptor must enumerate its AC right-hand-side sources |
| `load_noise` destination stride 1 → 2 (signed `(flat, react)` power pairs) | **ABI 0.7** | [E-54](../../enhancements_doc/Enhancement-54.md) | correct noise physics: operating-point-dependent factors and `ddt()`-shaped (jω) noise need a complex amplitude per source, `re + jω·im`, so coherent same-named sources (LRM 4.6.4) sum with correct sign and frequency shape |

Two **additive flag conventions** ride on the existing `eval()` interface
(not version bumps):

- `EVAL_FLAG_IS_FINAL_STEP` (bit 1≪21) in the eval *input* flags —
  `@(final_step)` firing ([E-53](../../enhancements_doc/Enhancement-53.md));
- eval *return* flags for `$finish`/`$stop` requests and
  `$discontinuity`-driven step rejection
  ([E-55](../../enhancements_doc/Enhancement-55.md)).

**Pairing consequence:** this ngspice requires OSDI ≥ 0.7 and rejects
older objects with a clear version message; `.osdi` files from older
compilers must be recompiled ([E-54](../../enhancements_doc/Enhancement-54.md)).

---

## 2. The OSDI runtime — `src/osdi/`

### `osdiaccept.c` — new file ([E-55](../../enhancements_doc/Enhancement-55.md), [E-1](../../enhancements_doc/Enhancement-1.md), [E-6](../../enhancements_doc/Enhancement-6.md))

The accepted-timepoint hook (`DEVaccept`) OSDI previously lacked. It
advances the `absdelay`/`last_crossing` waveform histories only at
*accepted* points (so rejected timesteps don't corrupt the delay lines)
and reads the per-attempt latched `$finish`/`$stop` request flags at the
one boundary where honoring them is safe. **Why:** acting on `$stop`
mid-Newton-iteration was treated as a step failure and ground the
timestep into a rejection loop; `$finish` was ignored outright.

### `osdidefs.h` (104 diff lines)

- `OsdiExtraInstData` grows the per-instance fields behind every runtime
  feature: `dt`/`temp` offsets with given-flags (instance temperature),
  `eval_flags`, absdelay waveform-history rows and pre-allocated
  KLU/SPARSE matrix-pointer sets for the delay-equation rows (re-pointed
  on every DC↔AC transition, mirroring the regular Jacobian handling),
  and the last_crossing history
  ([E-1](../../enhancements_doc/Enhancement-1.md), [E-6](../../enhancements_doc/Enhancement-6.md), [E-55](../../enhancements_doc/Enhancement-55.md)).
- `ALIGN` macro renamed `OSDI_ALIGN`: the macOS SDK's `<sys/param.h>`
  defines an unrelated `ALIGN`, producing a redefinition warning in every
  OSDI translation unit ([E-77](../../enhancements_doc/Enhancement-77.md)).

### `osdiitf.h` / `osdiext.h`

The registry-entry structure gains the absdelay/last_crossing descriptor
pointers, and `OSDIpendingRequests()` is exported so the analyses can ask
"did any device request `$finish`/`$stop` at this accepted point?"
([E-1](../../enhancements_doc/Enhancement-1.md), [E-6](../../enhancements_doc/Enhancement-6.md), [E-55](../../enhancements_doc/Enhancement-55.md)).

### `osdiregistry.c` (68 diff lines)

- Loads the absdelay/last_crossing descriptor arrays from each `.osdi`
  and threads them into the registry entries
  ([E-1](../../enhancements_doc/Enhancement-1.md), [E-6](../../enhancements_doc/Enhancement-6.md)).
- Requires OSDI ≥ 0.7 ([E-54](../../enhancements_doc/Enhancement-54.md)).

### `osdiinit.c` (8 diff lines)

- Registers the `DEVaccept` hook ([E-55](../../enhancements_doc/Enhancement-55.md)).
- Publishes the synthetic instance-temperature parameter under **both**
  spellings, `dt` and the conventional `dtemp` every built-in device
  uses; `n1 a b mod dtemp=10` used to fail with *"unknown parameter"*
  while the underlying plumbing was exact
  ([E-80](../../enhancements_doc/Enhancement-80.md)).

### `osdiload.c` (441 diff lines — the largest OSDI change)

- Stamps the absdelay synthetic rows (`y_synth`, `z`) for DC, AC and
  transient, driving the delay from the recorded history
  ([E-1](../../enhancements_doc/Enhancement-1.md)).
- Evaluates `last_crossing` from the recorded waveform with linear
  interpolation between the bracketing timepoints
  ([E-6](../../enhancements_doc/Enhancement-6.md)).
- Passes the final-step flag through to `eval()`
  ([E-53](../../enhancements_doc/Enhancement-53.md)).
- Latches eval-return flags per timepoint attempt (`point_eval_flags`,
  OR-ed across Newton iterations, reset per attempt) so
  `$finish`/`$stop` under solution-dependent conditions survive to the
  accepted-point boundary ([E-55](../../enhancements_doc/Enhancement-55.md)).
- Folds the stride-2 signed noise-power pairs (`fac·|fac|` semantics)
  when transferring `load_noise` results
  ([E-54](../../enhancements_doc/Enhancement-54.md), [E-42](../../enhancements_doc/Enhancement-42.md)).

### `osdisetup.c` (178 diff lines)

- Creates the synthetic delay-equation unknowns and matrix entries for
  absdelay ([E-1](../../enhancements_doc/Enhancement-1.md)).
- Applies the OSDI nodesets (`OsdiNode.nodeset`) as solver initial
  guesses ([E-45](../../enhancements_doc/Enhancement-45.md)).
- A `$fatal`/`$finish` raised **during setup** (models rejecting their
  configuration by design — HiSIM's `$port_connected` guards) used to
  surface as ngspice's baffling *"impossible error — can't occur"*; it
  now reads *"a Verilog-A device rejected its configuration during
  setup"* ([E-56](../../enhancements_doc/Enhancement-56.md)).
- An internal OSDI node that appears in **no Jacobian entry** — a net
  structurally decoupled from the matrix, e.g. an explicit `ground gnd`
  reference whose branch contribution `V(p,gnd) <+ …` drops the `gnd`
  column — used to be allocated its own solver row. That all-zero
  row/column is benign under Sparse (it decouples to `V=0`) but makes
  the **KLU** matrix structurally singular, so KLU returned a wrong DC
  answer (`groundcontrib`: `v(p)=0` not `1.5`; `hierbranch`: branch
  currents `0`). Such nodes are now tied to ground (node 0) at setup,
  matching how OpenVAF already treats them and fixing both solvers
  ([E-116](../../enhancements_doc/Enhancement-116.md)).

### `osdiacld.c` (89 diff lines)

- AC loading gains the `ac_stim` right-hand-side injection: the
  partitioned AC-stimulus source array is loaded through `load_ac_stim`
  and added to the AC RHS with exact magnitude and phase, `$mfactor`
  applied linearly (deterministic signals scale with multiplicity)
  ([E-51](../../enhancements_doc/Enhancement-51.md), [E-26](../../enhancements_doc/Enhancement-26.md)).
- Complex (jω-shaped) noise coupling entries participate in the AC
  matrix ([E-54](../../enhancements_doc/Enhancement-54.md)).

### `osdinoise.c` (93 diff lines)

- **Per-instance grouping of same-named noise sources**: coherent
  summation of complex amplitudes `(a + jω·b)·T` before squaring, per
  LRM 4.6.4 — same-named sources correlate (including exact anti-phase
  cancellation), differently-named ones stay independent
  ([E-42](../../enhancements_doc/Enhancement-42.md)).
- Reads the stride-2 signed pairs of ABI 0.7
  ([E-54](../../enhancements_doc/Enhancement-54.md)).

### `osditrunc.c` (34 diff lines)

- Honors `$discontinuity(n)`'s **next-step clamp**: a negative
  `bound_step` sentinel from the model limits the step after the event
  ([E-24](../../enhancements_doc/Enhancement-24.md)).
- Honors the **step-rejection** return flag: when an event fired inside
  the step, `OSDItrunc` requests `delta/8` (with a `20·CKTdelmin`
  termination floor) so the integrator bisects onto the discontinuity
  instead of extrapolating across it
  ([E-55](../../enhancements_doc/Enhancement-55.md)).

### `osdi/Makefile.am`

Adds `osdiaccept.c` to the build ([E-55](../../enhancements_doc/Enhancement-55.md)).

---

## 3. Analyses — `src/spicelib/analysis/`

### `dctran.c` (46 diff lines)

- Advances OSDI delay/crossing histories via the accept path and skips
  history corruption on rejected steps
  ([E-1](../../enhancements_doc/Enhancement-1.md), [E-6](../../enhancements_doc/Enhancement-6.md)).
- Issues the dedicated `@(final_step)` evaluation at the converged end
  of a successful transient ([E-53](../../enhancements_doc/Enhancement-53.md)).
- Honors accepted-point `$finish` (ends the analysis cleanly, firing
  `final_step` at the requesting point), `$stop` (pauses resumably), and
  aborts with a clear error on `$fatal`'s `E_PANIC` instead of retrying
  it as nonconvergence ([E-55](../../enhancements_doc/Enhancement-55.md)).

### `dcop.c` (9) and `acan.c` (10)

- Fire `@(final_step)` at their successful end (an operating point fires
  both step events — a single point is first *and* last)
  ([E-53](../../enhancements_doc/Enhancement-53.md)).
- An AC job's operating-point phase carries the analysis **name** bit
  (only the name — adding the reactive `CALC_*` bits would wrongly
  enable integration at an op), so `analysis("ac")` holds through the
  whole AC run per LRM 4.6.1 and `@(initial_step("ac"))` fires in AC
  ([E-53](../../enhancements_doc/Enhancement-53.md)).

### `dctrcurv.c` (150) + `include/ngspice/trcvdefs.h` (13)

- **Generic `.dc @inst[param]` sweeps** (a new sweep code): the DC sweep
  previously hardcoded Vsource/Isource/Resistor/temperature, so sweeping
  any other device parameter was a fatal error. The generic sweep
  resolves `@inst[param]` through the device's own parameter tables,
  refreshes per point via `DEVtemperature` (for OSDI exactly the `alter`
  path), nests with other sweep variables, and restores the original
  value afterwards ([E-62](../../enhancements_doc/Enhancement-62.md)).
- Fires `final_step` at the last sweep point; honors a `$finish` raised
  mid-sweep ([E-53](../../enhancements_doc/Enhancement-53.md), [E-55](../../enhancements_doc/Enhancement-55.md)).

### `noisean.c` (37)

- A singular AC matrix during noise analysis **crashed ngspice with a
  SIGABRT**: the code ignored `NIacIter`'s return and the adjoint solve
  asserted on the unfactored matrix. It now aborts cleanly ("AC solution
  failed at … Hz") ([E-56](../../enhancements_doc/Enhancement-56.md)).
- Honors deferred `$finish`/`$stop` raised at the noise operating point
  and fires `final_step` on success
  ([E-55](../../enhancements_doc/Enhancement-55.md), [E-53](../../enhancements_doc/Enhancement-53.md)).

### `span.c` (31) + `cktspdum.c` (14)

- **1-port S-parameter analyses enabled**: the "we need at least two
  ports" error was over-strict (a 1-port is a plain reflection
  measurement; the matrix machinery is N-general) — and it was hiding
  the `cadjoint` crash fixed in `dense.c`
  ([E-64](../../enhancements_doc/Enhancement-64.md)).
- **`Rbase` published into the sp plot** from port 1's `z0`, making the
  Touchstone writers work with no manual `let Rbase = 50` incantation
  ([E-64](../../enhancements_doc/Enhancement-64.md)).
- **Stock NaN fixed in `donoise` noise-parameter extraction**: the
  uncorrelated noise conductance `Gu` is analytically zero for
  fully-correlated single-source topologies, and floating-point rounding
  could land `sqrt(Ycor² + Gu/Rn)`'s argument at −10⁻¹⁸ → NaN for the
  noise figure. Clamped to the physical range ≥ 0 — found by parity
  testing against an OSDI resistor that produced the exact textbook NF
  where the built-in returned NaN
  ([E-63](../../enhancements_doc/Enhancement-63.md)).

### `cktdisto.c` (16)

- `.disto` **silently reported zero distortion** for OSDI devices — the
  distortion kernel needs higher-order Taylor coefficients the OSDI ABI
  cannot provide (first derivatives only), and such devices were skipped
  without a word. A prominent warning now names each affected OSDI
  device type ([E-62](../../enhancements_doc/Enhancement-62.md)).

---

## 4. Frontend — `src/frontend/`

### `plotting/pyplot.c` (new) + `com_pyplot.c` (new) + `plotit.c`, `commands.c` (E-94)

A new interactive command, **`pyplot`**, plots simulated vectors with
**matplotlib** — a Python counterpart to `gnuplot`. `ft_pyplot()`
(`plotting/pyplot.c`) mirrors `ft_gnuplot()`: it writes a `<file>.data`
table and a `<file>.py` matplotlib script and `system()`s `python3`
(synchronously for a PNG, backgrounded for an interactive window). A new
`"pyplot"` device arm in `plotit()` routes to it, so it accepts the same
plot expressions as `plot`/`gnuplot`; the `com_pyplot()` wrapper mirrors
`com_gnuplot()`, and `pyplot` is registered in both command tables. Two
`set` variables tune it: `pyplot_terminal=png` renders headless (Agg) to a
PNG, and `pyplot_python` picks the interpreter (default `python3`). Purely
additive ([E-94](../../enhancements_doc/Enhancement-94.md)). The output file
base name is **optional** ([E-95](../../enhancements_doc/Enhancement-95.md)):
`com_pyplot()` treats the first word as a file name only when it is not a plot
expression (no `(`, and not a vector by `vec_get()`), otherwise it defaults to
`pyplot` — so `pyplot v(out)` plots directly (the command's minimum argument
count was lowered from 2 to 1). `ft_pyplot()` also grew **stacked subplots**
(`set pyplot_subplots=N` → `plt.subplots(nrows, 1, sharex=True)`, `N` traces
per panel; `vs` stays the x-axis, so it is not a panel separator) and
**matplotlib style sheets** (`set pyplot_style=<name>`, `dark` →
`dark_background`, guarded) ([E-98](../../enhancements_doc/Enhancement-98.md)).
The headless `pyplot_terminal` was extended from PNG-only to the **vector
export formats** `svg` and `pdf` (`set pyplot_terminal=svg`/`pdf` →
`fig.savefig(<file>.<fmt>)`, matplotlib picking the writer from the extension),
and a **figure size** control was added (`set pyplot_figsize="W,H"` →
`plt.subplots(..., figsize=(W, H))`; quote the value so ngspice keeps the
comma) ([E-99](../../enhancements_doc/Enhancement-99.md)).

### `postcoms.c` (414 diff lines) + `postcoms.h` + `commands.c` (16)

The Touchstone I/O subsystem
([E-64](../../enhancements_doc/Enhancement-64.md), [E-72](../../enhancements_doc/Enhancement-72.md)):

- **`wrsnp`** (with `wrs2p` dispatching to the same handler): Touchstone
  v1 for **any port count** — the classic 2-port `S11 S21 S12 S22`
  column order preserved byte-identically, N ≥ 3 in the spec's row-major
  layout with at most four complex pairs per line;
- **writer options** `wrsnp <file> [ri|ma|db] [s|y|z] [hz|khz|mhz|ghz]`,
  any combination in any order: MA/DB formats, Y/Z parameters
  (normalized to Rbase, `Y·R` / `Z/R`, per the v1 spec), frequency
  units — the option line reflects every choice;
- **`rdsnp`**: reads any Touchstone v1 file into a **new plot** with a
  Hz `frequency` scale and complex vectors matching the `.sp` plot's
  conventions (MA/DB converted back, Y/Z de-normalized, the 2-port
  column order handled, `Rbase` published so imports round-trip) —
  measured data diffs against simulation in one `let` expression.

**Why:** E-63 showed the S-parameter *analysis* was exact but its results
could not leave ngspice in the industry-standard format (`wrs2p` demanded
a never-created `Rbase` vector), and nothing could bring VNA data in.

### `outitf.c` (16)

- **Integer operating-point variables recorded per point**: `getSpecial`
  masked with `IF_REAL` only, so an integer opvar saved with
  `.save @n1[flag]` produced garbage in transient vectors
  ([E-32](../../enhancements_doc/Enhancement-32.md)).
- The plot-memory guard's message printed `%Id` — a Windows-only printf
  length modifier that is undefined behavior elsewhere and rendered the
  message as the numberless `"memory required (Id Bytes)"`. Now `%zu`:
  real byte counts on every platform
  ([E-77](../../enhancements_doc/Enhancement-77.md)).

### `resource.c` (27)

`ft_ckspace()` — the *"approaching max data size"* warning (RSS > 95% of
RSS + free RAM) — now honors **`set no_mem_check`** (the same opt-out the
fatal output-size estimate in `outitf.c` respects; one variable governs
both memory guards) and warns **once per excursion** above the threshold,
re-arming below 90%, instead of repeating on every check through a long
analysis ([E-81](../../enhancements_doc/Enhancement-81.md)).

### `display.c` (1)

`#undef NODEV` before the local macro definition — the macOS SDK's
`<sys/param.h>` defines an unrelated `NODEV`
([E-77](../../enhancements_doc/Enhancement-77.md)).

---

## 5. Parser and device registry — `src/spicelib/`

### `parser/inpgtok.c` (10)

**A `.model` card override silently dropped its first parameter** when
the type name and the opening parenthesis had no space between them
(`modname devtype(p1=v1 …)`): `INPgetNetTok`'s scan did not treat `(` as
a token boundary, so the type token swallowed the paren and the first
parameter name. Found while verifying event-function counters whose
model-card overrides mysteriously kept defaults
([E-8](../../enhancements_doc/Enhancement-8.md)).

### `parser/inpgmod.c` (5)

`find_model_parameter()` dereferenced `*(device->numModelParms)`, which
is **NULL** for built-ins that take no model cards (VCVS, CCCS, …) — any
*referenced* `.model m vcvs()` card segfaulted, with **no OSDI involved
at all** (an ordinary MOS instance sufficed). This was the true root of
the long-documented "module named like a built-in crashes" gotcha. One
NULL guard; both shapes now produce clean, located errors
([E-76](../../enhancements_doc/Enhancement-76.md)).

### `devices/dev.c` (51)

- **Duplicate device-type registration warned and skipped**:
  `osdi_add_device()` appended every descriptor unconditionally, and the
  model-card lookup scans front-to-back — so a module name duplicated
  across two loaded libraries silently resolved to the *first*
  registration (loading an updated model library gave the stale device
  with no hint), and a module named like a built-in corrupted model
  creation. Registration now checks the table case-insensitively and
  skips duplicates loudly ([E-76](../../enhancements_doc/Enhancement-76.md)).
- **`pre_osdi` path dedup**: loading an already-loaded file notes it and
  skips — with the remedy stated: *"restart ngspice to load a recompiled
  file"* ([E-76](../../enhancements_doc/Enhancement-76.md), [E-81](../../enhancements_doc/Enhancement-81.md)).

### `osdi/osdiparam.c` (E-93)

Setting a **fixed (`localparam`) OSDI parameter** from the netlist used to
be swallowed silently: openvaf exports every `localparam` as a parameter,
its "given" flag is forced false, and the written value is overwritten by
the parameter-init default — so `.model … N=8` on a frozen structural width
parameter changed nothing, with no feedback. `OSDIparam`/`OSDImParam` now
test the new `PARA_FLAG_FIXED` descriptor flag (set by openvaf, a free bit
of the parameter `flags` field) and emit *"parameter 'N' is a fixed
(localparam) value and cannot be set from the netlist; ignored"* instead of
silently dropping it ([E-93](../../enhancements_doc/Enhancement-93.md)).

---

## 6. Maths — `src/maths/`

### `dense/dense.c` (11 substantive lines; the file also carries a whitespace/line-ending normalization from editing)

**`cadjoint()` had no 1×1 base case**: its cofactor loop allocated 0×0
and then negative-sized minors, killing ngspice with
`malloc: can't allocate -8 bytes` — the crash that had been hiding behind
the "at least two ports" guard in `span.c`. The adjugate of `[a]` is
`[1]` (the empty minor's determinant is 1 by convention), making
`cinverse` of a 1×1 equal `1/a`; a 100 Ω load on a 50 Ω port now writes a
proper `.s1p` with S11 = 1/3 exactly
([E-64](../../enhancements_doc/Enhancement-64.md)).

### `sparse/spfactor.c` (6)

The Markowitz-product overflow guards compare a `double` against
`LARGEST_LONG_INTEGER` (= `LONG_MAX`), which is not exactly representable
as a double; the conversion is now explicit — identical semantics,
intentional and warning-free
([E-77](../../enhancements_doc/Enhancement-77.md)).

### `KLU/klu_multiply.c` (16)

`SMPmultiply`'s KLU path passed `NULL` internal↔external ordering maps to
`KLU_matrix_vector_multiply`, which dereferenced them unconditionally
(`&NULL[n]` = `0x14` for `n = 5`) and **segfaulted** — so `.option linesearch`
crashed under `.option klu`. The line search is the only caller of
`SMPmultiply` under KLU, so this path had never been exercised. A NULL map now
means the **identity** ordering (`ext = i + 1`, since the KLU CSR is 0-based and
the RHS/Solution vectors are 1-based), making the KLU matrix-vector product —
and hence the [E-111](../../enhancements_doc/Enhancement-111.md) line-search
residual merit — correct under KLU, with a merit sequence numerically identical
to Sparse 1.3 ([E-112](../../enhancements_doc/Enhancement-112.md)).

### `KLU/klusmp.c` (SMPcaSolve)

`SMPcaSolve` is the complex **adjoint** (transposed) solve used by noise and
S-parameters. Its Sparse branch calls `spSolveTransposed`, but the KLU branch
called the *non-transposed* `klu_z_solve` — silently wrong for any asymmetric
matrix (every circuit with a transistor or controlled source), which is why
`.noise` was disabled under KLU. It now calls `klu_z_tsolve` (transposed), so KLU
noise matches Sparse exactly (including OSDI device models). This is the core of
[E-113](../../enhancements_doc/Enhancement-113.md), which also removes the KLU
refusal guards in `noisean.c` / `pzan.c` (single-ended pole-zero runs under KLU;
balanced-output pole-zero keeps a targeted guard).

### `spicelib/analysis/cktsens.c`

Sensitivity builds an auxiliary perturbation matrix `delta_Y` (holding `∂Y/∂p`)
via `SMPnewMatrix`, which allocates a plain **Sparse 1.3** matrix
(`delta_Y->CKTkluMODE = 0`, no `SMPkluMatrix`). It is only *multiplied* against
the solution (`SMPmultiply` → `spMultiply`), never factored, and `DEVbindCSC`
always binds into `ckt->CKTmatrix`, not `delta_Y` — so it is correctly Sparse in
every case. But two KLU-only setup blocks were gated on the **main** matrix's
`CKTkluMODE`, so under `.option klu` they ran and dereferenced the NULL
`delta_Y->SMPkluMatrix` — a **segfault** on every DC/AC `.sens` deck. The blocks
now gate on `delta_Y->CKTkluMODE` (its own flag, `0`), keeping `delta_Y` Sparse
under KLU exactly as it already is under the default solver, while the main `Y`
matrix stays KLU. DC and AC sensitivity now match Sparse exactly
([E-114](../../enhancements_doc/Enhancement-114.md)).

### `spicelib/analysis/distoan.c`

Distortion is a **complex** analysis (Volterra series solved at the harmonic /
intermodulation frequencies via `NIdIter` → `SMPcSolve`), but `distoan.c` had
**no KLU code at all**: under `.option klu` the KLU matrix stayed in *real* mode,
the complex solves ran against an unconverted matrix, and every harmonic came
back **zero** — a silent wrong answer. The fix mirrors `acan.c`: before the
solve loop it converts the matrix to complex (`DEVbindCSCComplex` per device +
`KLUmatrixIsComplex`), and on exit converts back to real
(`DEVbindCSCComplexToReal`) so a later real analysis in the same session is
unaffected. KLU distortion now matches Sparse bit-for-bit (single-tone, two-tone
intermodulation, and OSDI models) ([E-115](../../enhancements_doc/Enhancement-115.md)).

---

## 7. Build system

### `xspice/icm/makedefs.in` (4)

The XSPICE codemodel (`.cm`) link rule hardcoded the pre-macOS-10.3 idiom
`-bundle -flat_namespace -undefined suppress`, deprecated loudly by the
modern linker on all 14 codemodel links (CI macOS builds included). Now
`-bundle -undefined dynamic_lookup` — the modern spelling for plugins
whose host symbols resolve at load time
([E-77](../../enhancements_doc/Enhancement-77.md)).

### Autotools regeneration (the ~100 `Makefile.in` files + `config.h.in`)

Regenerated by `./autogen.sh` with libtool 2.5.4 during the zero-warning
work — a build tree whose `configure` predates libtool 2.4.7 selects the
deprecated darwin `-undefined suppress` flag whenever
`MACOSX_DEPLOYMENT_TARGET` is unset. No hand-written content
([E-77](../../enhancements_doc/Enhancement-77.md)).

---

## 8. Per-enhancement index

Every enhancement that touched ngspice, oldest first:

| Enhancement | ngspice files | One line |
|---|---|---|
| [E-1](../../enhancements_doc/Enhancement-1.md) | osdi.h, osdidefs.h, osdiitf.h, osdiregistry.c, osdiload.c, osdisetup.c, dctran.c (+accept path) | `absdelay()`: synthetic delay rows + waveform history |
| [E-6](../../enhancements_doc/Enhancement-6.md) | osdi.h, osdidefs.h, osdiitf.h, osdiregistry.c, osdiload.c | `last_crossing()`: history + interpolated crossings |
| [E-8](../../enhancements_doc/Enhancement-8.md) | parser/inpgtok.c | `.model` card first-parameter drop fix |
| [E-24](../../enhancements_doc/Enhancement-24.md) | osditrunc.c | `$discontinuity` next-step clamp |
| [E-25](../../enhancements_doc/Enhancement-25.md) | osdi callbacks (get_simparams) | expose `analysis_name` + `simulator` simparams |
| [E-32](../../enhancements_doc/Enhancement-32.md) | outitf.c | integer opvars recorded per point |
| [E-42](../../enhancements_doc/Enhancement-42.md) | osdinoise.c | coherent same-named noise grouping (LRM 4.6.4) |
| [E-45](../../enhancements_doc/Enhancement-45.md) | osdi.h (ABI 0.5), osdisetup.c | Verilog-A nodesets applied to the solver |
| [E-51](../../enhancements_doc/Enhancement-51.md) | osdi.h (ABI 0.6), osdiacld.c | full `ac_stim` AC-RHS injection |
| [E-53](../../enhancements_doc/Enhancement-53.md) | dctran.c, dcop.c, dctrcurv.c, acan.c, noisean.c, osdiload.c | `@(final_step)` + analysis-name phase bits |
| [E-54](../../enhancements_doc/Enhancement-54.md) | osdi.h (ABI 0.7), osdinoise.c, osdiload.c, osdiacld.c, osdiregistry.c | node-free complex noise factors, stride-2 pairs |
| [E-55](../../enhancements_doc/Enhancement-55.md) | osdiaccept.c (new), osdiload.c, osditrunc.c, osdiinit.c, dctran.c, dctrcurv.c, osdiitf.h, Makefile.am | `$finish`/`$stop`/`$fatal` honored; `$discontinuity` step rejection |
| [E-56](../../enhancements_doc/Enhancement-56.md) | noisean.c, osdisetup.c | noise SIGABRT fix; setup-rejection diagnostics |
| [E-62](../../enhancements_doc/Enhancement-62.md) | dctrcurv.c, trcvdefs.h, cktdisto.c | generic `.dc @inst[param]` sweeps; `.disto` warning |
| [E-63](../../enhancements_doc/Enhancement-63.md) | span.c | `donoise` NaN clamp (stock defect, found by parity) |
| [E-64](../../enhancements_doc/Enhancement-64.md) | span.c, cktspdum.c, dense.c, postcoms.c/.h, commands.c | Touchstone export, auto-`Rbase`, 1-port `.sp`, `cadjoint` 1×1 |
| [E-72](../../enhancements_doc/Enhancement-72.md) | postcoms.c/.h, commands.c | Touchstone round 2: MA/DB/Y/Z/units + `rdsnp` reader |
| [E-76](../../enhancements_doc/Enhancement-76.md) | dev.c, inpgmod.c | duplicate-registration warning, load dedup, stock `.model` segfault fix |
| [E-77](../../enhancements_doc/Enhancement-77.md) | osdidefs.h, display.c, outitf.c, spfactor.c, makedefs.in (+autotools regen) | zero-warning build, 33 → 0 |
| [E-80](../../enhancements_doc/Enhancement-80.md) | osdiinit.c | `dtemp` instance-parameter alias |
| [E-81](../../enhancements_doc/Enhancement-81.md) | resource.c, dev.c | memory-warning opt-out + once-per-excursion; reload-note hint |
| [E-93](../../enhancements_doc/Enhancement-93.md) | osdi.h, osdiparam.c | warn (not silently ignore) when a netlist sets a `PARA_FLAG_FIXED` (`localparam`) OSDI parameter |
| [E-94](../../enhancements_doc/Enhancement-94.md) | plotting/pyplot.c (new), com_pyplot.c (new), plotit.c, commands.c | new `pyplot` command — plot vectors with matplotlib (a Python `gnuplot`) |
| [E-95](../../enhancements_doc/Enhancement-95.md) | com_pyplot.c, commands.c | make the `pyplot` output file name optional (defaults to `pyplot`) |
| [E-98](../../enhancements_doc/Enhancement-98.md) | plotting/pyplot.c | `pyplot` stacked subplots (`pyplot_subplots=N`) + matplotlib style sheets (`pyplot_style`) |
| [E-99](../../enhancements_doc/Enhancement-99.md) | plotting/pyplot.c | `pyplot` vector export formats (`pyplot_terminal=svg`/`pdf`) + figure size (`pyplot_figsize`) |
| [E-110](../../enhancements_doc/Enhancement-110.md) | optdefs.h, tskdefs.h, cktsopt.c, cktntask.c | `.option errpreset=conservative\|moderate\|liberal` — one knob for a coordinated tolerance/robustness set; explicit options override regardless of order (`moderate` = historical defaults) |
| [E-111](../../enhancements_doc/Enhancement-111.md) | optdefs.h, tskdefs.h, cktdefs.h, cktsopt.c, cktdojob.c, cktntask.c, cktdest.c, niiter.c | `.option linesearch` — globalized (damped) Newton via Armijo backtracking on a new KCL-residual merit `‖F‖=‖G·x−b‖`; result-neutral, off by default |
| [E-112](../../enhancements_doc/Enhancement-112.md) | maths/KLU/klu_multiply.c | KLU support for `.option linesearch` — `SMPmultiply`'s KLU path passed NULL ordering maps that `klu_matrix_vector_multiply` dereferenced (SIGSEGV); NULL now means identity ordering. Line search verified merit-identical KLU vs Sparse |
| [E-113](../../enhancements_doc/Enhancement-113.md) | maths/KLU/klusmp.c, spicelib/analysis/noisean.c, pzan.c | KLU support for noise + single-ended pole-zero — `SMPcaSolve`'s adjoint KLU branch used the non-transposed solve (silently wrong noise on asymmetric matrices); now `klu_z_tsolve`. Guards removed; balanced-output pz keeps a targeted guard |
| [E-114](../../enhancements_doc/Enhancement-114.md) | spicelib/analysis/cktsens.c | KLU support for sensitivity — the auxiliary perturbation matrix `delta_Y` is Sparse, but two KLU setup blocks gated on the *main* matrix's flag dereferenced its NULL `SMPkluMatrix` (segfault on every DC/AC `.sens`); now gated on `delta_Y`'s own flag. DC/AC `.sens` match Sparse exactly |
| [E-115](../../enhancements_doc/Enhancement-115.md) | spicelib/analysis/distoan.c | KLU support for distortion — `.disto` is a complex analysis but `distoan.c` had no KLU code, so under KLU the matrix stayed real and every harmonic came back zero (silent wrong answer); now converts real↔complex around the solve loop like `acan.c`. Matches Sparse bit-for-bit |
| [E-116](../../enhancements_doc/Enhancement-116.md) | osdi/osdisetup.c | KLU wrong-DC fix — an OSDI internal node with no Jacobian entry (a decoupled `ground` reference) was given an all-zero solver row that made the KLU matrix structurally singular; now tied to ground. Fixes the `groundcontrib` and `hierbranch` KLU_XFAILs |
| [E-117](../../enhancements_doc/Enhancement-117.md) | configure.ac (+`configure`), spicelib/analysis/dcpss.c | Periodic steady state (PSS) productionized — built by default (was experimental `--enable-pss`, so `.pss` was unimplemented in shipped builds); ~230 lines of shooting-loop trace routed through `set ngdebug` (232 → 31 lines by default); fail-fast KLU guard (PSS hangs under KLU) directing `.pss` to `.option sparse` |
| [E-118](../../enhancements_doc/Enhancement-118.md) | spicelib/analysis/dcpss.c | PSS runs under KLU — the shooting loop hung under KLU (`klu_refactor`'s reused pivots inflated the truncation error into a ~20M-step timestep explosion); forcing a full re-factor (`NISHOULDREORDER`) each PSS step makes KLU converge to the same result as Sparse. E-117's Sparse-only guard removed |
| [E-119](../../enhancements_doc/Enhancement-119.md) | pssdefs.h, spicelib/analysis/dcpss.c | Retain the PSS periodic operating point — PSS sampled the node voltages per period for its DFT then freed them, and never captured device states; now the voltages **and** `CKTstate0` states are captured per sample and retained on the `PSSan` job (with frequency + dims) as the substrate for the periodic small-signal suite (PAC/pnoise/PXF). Self-checks that the retained samples reproduce the fundamental |
| [E-120](../../enhancements_doc/Enhancement-120.md) | spicelib/analysis/dcpss.c | Periodic small-signal Jacobian harmonics — walk the retained operating point, re-linearize each sample (`CKTload` MODEINITSMSIG) and stamp `G+jC` (`CKTacLoad` ω=1), read the osc-node diagonal → `g(t)`, `c(t)`, DFT to harmonics. The blocks the PAC conversion matrix is built from. (Fixed a complex-mode-not-set bug where `C(t)` accumulated across samples.) Verified: RC gives `G=1/R1`, `C=C1`, no harmonics |
| [E-121](../../enhancements_doc/Enhancement-121.md) | spicelib/analysis/dcpss.c | PAC conversion-matrix engine — extend E-120 from the osc diagonal to every matrix nonzero, complex-DFT to harmonics `G_k`, `C_k`, assemble the `(2M+1)N` harmonic conversion matrix `H_{nm}=G_{n−m}+jω_m·C_{n−m}`, inject a unit current at the osc node in sideband 0 and solve by dense complex LU (`pss_csolve`), report the sideband conversion gains. The numerical heart of PAC/pnoise/PXF. Verified: linear RC gives sideband-0 = AC driving-point `|Z|(f0/2)` = 303.3 Ω with the ±1 sidebands at floating-point zero (no spurious conversion) |
| [E-122](../../enhancements_doc/Enhancement-122.md) | include/ngspice/pssdefs.h, spicelib/analysis/psssetp.c, spicelib/parser/inp2dot.c, spicelib/analysis/dcpss.c | `.pac` command (periodic AC) — the user-facing analysis on the E-121 engine. `.pac Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff <dec\|oct\|lin> Npts Fstart Fstop` runs PSS then sweeps the input frequency, solving the conversion matrix at each point and emitting the 0-th-sideband node responses as a complex `PAC Analysis` plot (`print`/`plot`/`wrdata`). Reuses the PSS analysis via a `PSSdoPAC` flag; engine factored into `pac_extract_harmonics` (once) + `pac_solve_at` (per freq). Verified: swept sideband-0 `\|b(f)\|` == analytic AC driving-point `\|Z(f)\|` to 1.6e−7 across 10 kHz–1 MHz |
| [E-123](../../enhancements_doc/Enhancement-123.md) | include/ngspice/pssdefs.h, spicelib/analysis/psssetp.c, spicelib/parser/inp2dot.c, spicelib/analysis/dcpss.c | finish `.pac` — (1) **source-referenced stimulus**: capture the netlist `AC`-source RHS from `CKTacLoad` as the sideband-0 stimulus `B_0` (a periodic-AC transfer/conversion gain), unit-current-at-osc-node fallback; (2) **multi-sideband output**: optional trailing `maxsideband Ksb` emits every conversion sideband `f_in+k·f0` (`k=−Ksb..Ksb`) as its own vector — sideband 0 keeps the node name, others `<node>_usb<k>`/`<node>_lsb<k>` via `IFnewUid`. Verified: RC with `V1 AC 1` gives sideband-0 = low-pass transfer `1/√(1+(2πfRC)²)` (0.998→0.157) with `b_usb1`/`b_lsb1` ~0 (no conversion) |
| [E-124](../../enhancements_doc/Enhancement-124.md) | include/ngspice/pssdefs.h, spicelib/analysis/psssetp.c, spicelib/parser/inp2dot.c, spicelib/analysis/dcpss.c | `.pnoise` command (periodic noise) — fold each device's noise through the conversion matrix. `pac_solve_adjoint` solves `Hᵀ Ψ = e_{out,0}`; `pnoise_sweep` loads the sideband-`k` adjoint into `CKTrhs`/`CKTirhs` and calls the existing device noise routines (`NevalSrc`, OSDI `load_noise`) once per sideband, accumulating `Σ_k S·\|ΔΨ_k\|²` — reuses every device noise model via a minimal local `NOISEAN` context. `.pnoise <pss> OutNode InSrc <dec\|oct\|lin> Np Fstart Fstop`; emits `onoise_spectrum`/`inoise_spectrum`. Verified: linear RC reduces exactly to `.noise` (`4kTR/(1+(2πfRC)²)`, matches the `.noise` reference to every digit) |
| [E-125](../../enhancements_doc/Enhancement-125.md) | include/ngspice/pssdefs.h, spicelib/analysis/psssetp.c, spicelib/parser/inp2dot.c, spicelib/analysis/dcpss.c | `.pxf` command (periodic transfer function) — the adjoint of PAC, completing the PSS→PAC→Pnoise→PXF suite. `pxf_sweep` solves `Hᵀ Ψ = e_{out,0}` per frequency and dots each sideband block with the AC-source pattern `B0` → `xf_k=Σ_j Ψ_k(j)·B0(j)`, the input→output transfer at each sideband. `.pxf <pss> OutNode <dec\|oct\|lin> Np Fstart Fstop [maxsb]`; emits `xf` + `xf_usb<k>`/`xf_lsb<k>`. Verified: by the identity `(H⁻¹B)_out=(H⁻ᵀe_out)ᵀB` the sideband-0 transfer is **bit-identical** to the PAC response (0.998→0.157 low-pass), conversion sidebands ~2e−16 |
| [E-126](../../enhancements_doc/Enhancement-126.md) | include/ngspice/pssdefs.h, spicelib/analysis/psssetp.c, spicelib/parser/inp2dot.c, spicelib/analysis/dcpss.c | cyclostationary noise — `.pnoise ... cyclo` evaluates each device's noise PSD `S(t)` at **every** PSS sample's bias (`CKTload` per sample) and folds it through the **time-domain** adjoint transfer `A_s(j)=Σ_k Ψ_k(j)e^{j2πks/P}`, averaging: `onoise(f)=(1/P)Σ_s S(t_s)·\|ΔA_s\|²`. Reuses the device noise routines. Verified: (1) reduces **exactly** to `.noise` on the linear RC (bias-independent thermal → Parseval); (2) a flicker resistor carrying the RC current gives `onoise·f = R1²·KF·⟨I²⟩ = 4.88e−10` (uses the period-average `⟨I²⟩`, matched to 5 digits) |
| [E-127](../../enhancements_doc/Enhancement-127.md) | include/ngspice/{optdefs,tskdefs,cktdefs}.h, spicelib/analysis/{cktsopt,cktntask,cktdojob,cktop,cktdest}.c, maths/ni/niiter.c | pseudo-transient continuation — `.option ptcont` embeds `f(x)=0` in a backward-Euler pseudo-transient `f(x)+Gps·(x−x_prev)=0` and marches `dτ` small→large (`Gps→0`). `Gps` diagonal via the gmin path; the `Gps·x_prev` RHS coupling (added in `NIiter`) makes each step a stable-trajectory move, not a static gmin step. New `pseudo_transient` in the `CKTop` cascade, off by default. Verified under KLU+Sparse: result-neutral on normal circuits; on a stiff no-limiting exp, reaches the correct DC `0.837922 V` where plain Newton lands on a spurious `70.5 V` (21/21) |
| [E-128](../../enhancements_doc/Enhancement-128.md) | include/ngspice/{optdefs,tskdefs,cktdefs}.h, spicelib/analysis/{cktsopt,cktntask,cktdojob}.c, spicelib/analysis/dctran.c | LTE-based dynamic integration-order control — `.option dynorder` selects the Gear order per step from the local-truncation-error limit instead of the stock 1↔2 toggle, so orders 3–6 (already coded in `NIcomCof` but never used) are actually exercised. The selector compares the **raw** LTE-limited step (uncapped `CKTtrunc`) at the current order and its `±1` neighbours and moves with hysteresis (1.2×), a settling **hold** after each change (let the BDF divided differences rebuild), and an order-dependent step-growth cap (2× at order ≤3 → 1.3× at 6). Off by default; bounded by `maxord`; inert at the default `maxord=2`. Stiff-transient guards (post-breakpoint order hold + leaky-bucket rejection-rate order drop) keep it from collapsing the step on a violent slew. Verified under KLU+Sparse: RC decay 3–5× fewer steps at matched accuracy with monotone error; smooth RLC ringdown **8.9× fewer steps AND more accurate** (0.13 % vs 0.34 %); nonlinear rectifier matches stock to 5 sig figs; the transistor-level µA741 ±5 V slew completes under dynorder and matches fixed Gear-2 |
| [E-129](../../enhancements_doc/Enhancement-129.md) | frontend/outitf.c | sweep progress bar — the throttled `Reference value` status line (redrawn in place every 0.25 s during a sweep) now carries a live progress bar + percentage, e.g. `Reference value : 5.91926e-04  [==================      ] 74%`. `outp_progress_frac()` computes the 0–1 fraction per analysis: **transient** from `(CKTtime−TSTART)/(TSTOP−TSTART)`, **AC**/**noise** from the frequency's linear/log position in the band, **DC** from the accepted-point count over the nested step-count product; analyses with no span (op, …) keep the plain line. Fixed-width (no stale chars), stdout status-line only (never in the rawfile/`wrdata`), same `!ft_norefprint && !cp_background` gating. Verified 22/22: printed % matches the analytic sweep fraction to 0.5 % across tran/AC/DC/noise; op shows no bar |
| [E-130](../../enhancements_doc/Enhancement-130.md) | frontend/com_optimize.{c,h}, commands.c, options.c, include/ngspice/fteext.h, spicelib/analysis/cktdojob.c, frontend/outitf.c | built-in Nelder-Mead **optimizer** — `optimize -param <name> <init> <lo> <hi> [-param ...] -analysis <cmd> -minimize <expr> [-maxiter N] [-tol T] [-verbose]` varies device/`alter` parameters, re-runs an analysis, and minimizes a scalar objective expression via a derivative-free downhill simplex in normalized [0,1] space (scale-invariant across orders-of-magnitude params). Sub-commands dispatched synchronously through `cp_coms` (not the deferring re-entrant `cp_evloop`); the hundreds of inner analyses are silenced via a new `ft_optimizing` flag gating the banner/row-count/E-129 progress bar at source (`-verbose` to show). Verified 9/9 against analytic optima: DC divider R1→2333.3 Ω, AC low-pass R1→2756.6 Ω, 2-D compound objective R1=3k/R2=2k exactly |
| [E-131](../../enhancements_doc/Enhancement-131.md) | frontend/com_checkpoint.{c,h}, commands.c, com_commands.h, Makefile.am, spicelib/analysis/dctran.c, include/ngspice/cktdefs.h | transient **checkpoint / restart** — new `savestate <file>` / `loadstate <file>` commands serialize the full transient integration state (solution vector `CKTrhsOld`, device state history `CKTstates[]`, time/step/order/mode, pending breakpoints) to a binary file and resume it, **including in a fresh process** — so a long run survives a crash, splits across sessions, or moves between machines (stock ngspice could only `resume` in memory). `DCtran()` gains a `CKTcheckpoint`-gated branch that opens a **fresh** output plot (no live plot to `666`-relink across a reload), initializes the XSPICE breakpoint markers, and fixes up the breakpoint list before jumping into the stepping loop; the rhs length is keyed off `SMPmatSize+1` (not `CKTmaxEqNum`). A stored signature rejects a mismatched circuit; **Sparse-solver only** (KLU rejected with a clear message). Verified 19/19: resumed waveform **bit-identical** to an uninterrupted run for RC-step/pulse/diode built-ins and ~2e-7 for a compiled OSDI diode, across a separate process |
| [E-132](../../enhancements_doc/Enhancement-132.md) | spicelib/analysis/dcpss.c, spicelib/parser/inp2dot.c, spicelib/analysis/psssetp.c, include/ngspice/pssdefs.h | **periodic S-parameters** (`.psp`) — small-signal scattering parameters around a PSS operating point, including conversion between the input frequency and its sidebands `f_in+k·f0` (mixers / switched circuits, where a static-DC `.sp` cannot see the conversion). Sits on the PSS→conversion-matrix suite (E-117–126): after PSS, `psp_sweep` excites each RF port (`portnum`/`z0`, the `.sp` framework) by driving its branch source (V=1, like `.sp`'s `VSRCspupdate`) through the shared `(2M+1)N` conversion matrix, reads per-sideband port waves in the same Kurosawa power-wave convention, and forms `S^(k)=B^(k)·A^-1` (dense-complex `cinverse`/`cmultiply`). `pac_solve_at`'s matrix assembly factored into a reusable `pac_build_matrix`; `PSSdoPSP` flag + `psp` PSS param + `dot_psp` card. Because `S=B·A^-1` is excitation-basis-invariant, sideband 0 reduces **exactly** to `.sp` for a time-invariant network. **Sparse-only** (PSS suite). Verified 8/8: sideband-0 matches `.sp` to ~1e-16 for 1/2/3-port resistive + reactive networks (magnitude and phase) incl. **OSDI Verilog-A** devices (G + reactive `ddt` stamps), conversion sidebands correctly ~0 |

*(E-25's simparam exposure lives in the OSDI callback table populated at
load time; its diff rides inside the `osdiload.c`/callbacks changes.)*

*Build-warning cleanup (post-E-127): a full rebuild under the repo's
`-Wconversion` flags surfaced latent warnings. `configure.ac` had `-s` (a strip
flag) in the compile `CFLAGS`, so clang warned "argument unused during
compilation: '-s'" on **every** source file (~1526 warnings) — removed (binaries
are stripped separately by the fold and CI). `-Wconversion` also flagged a real
latent bug in `maths/ni/nipzmeth.c` (`b = 0.0` was an assignment where `b == 0.0`
was intended) — fixed — and benign `double`→`bool` conversions in
`maths/cmaths/cmath4.c` — made explicit. Full-build warnings dropped 1903 → 394;
the remainder are `-Wconversion` warnings in third-party SuiteSparse (KLU) and CMC
device models (HiSIM), which are left to their upstream sources.*

Every entry above is guarded by a verify script under
[`examples/`](../../examples/) and was regression-checked against the full
example arsenal, the compiler's integration suite, and the VA_TEST
industry-model corpus at the time it landed.
