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

**Scope summary.** One new source file and 33 modified ones carry all the
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
additive ([E-94](../../enhancements_doc/Enhancement-94.md)).

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

*(E-25's simparam exposure lives in the OSDI callback table populated at
load time; its diff rides inside the `osdiload.c`/callbacks changes.)*

Every entry above is guarded by a verify script under
[`examples/`](../../examples/) and was regression-checked against the full
example arsenal, the compiler's integration suite, and the VA_TEST
industry-model corpus at the time it landed.
