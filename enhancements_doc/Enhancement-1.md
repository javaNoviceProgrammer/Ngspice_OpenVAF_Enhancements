# Enhancement-1 changes — `absdelay` support for OSDI/Verilog-A in OpenVAF + ngspice

This document describes, step by step, every source change made to turn the
**original** OpenVAF and ngspice-46 sources into **version 2**. It was produced
by diffing `original/` against `version2/`.

The single goal of version 2 is to make the Verilog-A **`absdelay()`** operator
work end-to-end through the OSDI flow — compile a model that uses `absdelay`
with `openvaf-r`, and simulate it in ngspice for **DC**, **AC**, and
**transient** analysis.

Nothing outside the OSDI subsystem of ngspice is touched, and on the OpenVAF
side only the absdelay lowering + OSDI code-gen path is changed.

---

## 1. The idea (how `absdelay` is modeled)

`absdelay(V(in), td)` returns the input delayed by `td` seconds. A delay is not
expressible as a local algebraic/reactive stamp, so version 2 splits each
`absdelay` call into **two synthetic implicit equations** that the compiler
emits and the simulator closes:

```
 eq_y  (AbsDelayInput) :  V(y_synth) = y_expr          ← stamped by the model
 eq_z  (AbsDelayOutput):  V(z)       = delayed(V(y_synth), td)   ← stamped by ngspice
```

- The **model** (OpenVAF output) owns `eq_y`: it forces a synthetic node
  `y_synth` to equal the input expression, and it stores the current `td`.
- The **simulator** (ngspice) owns `eq_z`: it keeps a waveform history of
  `V(y_synth)` and stamps the row that ties output node `z` to the delayed
  value (interpolated from history in transient, `e^{-jωτ}` in AC, pass-through
  in DC).

To connect the two, OpenVAF exports a small descriptor per delay slot and
ngspice reads it at `.osdi` load time:

```
OsdiAbsDelayInfo { uint32 y_node; uint32 z_node; uint32 td_offset; }
```

plus two module-level arrays: `OSDI_ABSDELAY_COUNTS[i]` (number of delay slots
in descriptor `i`) and `OSDI_ABSDELAY_INFOS[]` (the flattened slot descriptors).
This contract is the heart of version 2.

---

## 2. OpenVAF compiler changes

8 source files. The job: lower `absdelay` to the two-equation form, carry the
`td` value into instance data, and export the slot descriptors in the `.osdi`.

### 2.1 `openvaf/hir_lower/src/lib.rs` — new IR vocabulary
- New `PlaceKind::AbsDelayTime(u32)` — a real-typed place that holds the current
  `td` for slot *i* (so it can be written into instance data and read back by
  the simulator).
- New `ImplicitEquationKind::AbsDelayInput(u32)` and `AbsDelayOutput(u32)` — the
  `eq_y` / `eq_z` synthetic-node equations.
- New field on `HirInterner`: `absdelay_equations: Vec<(ImplicitEquation,
  ImplicitEquation)>` — records the `(eq_y, eq_z)` pair for every slot, in order.

### 2.2 `openvaf/hir_lower/src/ctx.rs`
- `PlaceKind::AbsDelayTime(_)` initializes to `F_ZERO` (default value before the
  model body assigns it).

### 2.3 `openvaf/hir_lower/src/expr.rs` — the actual lowering (core change)
The original code for `absdelay` was a disabled `/* TODO */` block that tried to
approximate the delay with a reactive (`ddt`-style, `res/3`) term and then fell
through to an "unsupported" arm. Version 2 replaces it with the two-node form:
1. lower `y_expr = args[0]` and `td = args[1]` (clamp to `tdmax` if a third arg
   is present);
2. allocate `eq_y = AbsDelayInput(idx)` and `eq_z = AbsDelayOutput(idx)` and push
   `(eq_y, eq_z)` onto `absdelay_equations`;
3. emit the resistive residual `y_expr − V(y_synth) = 0` on `eq_y`;
4. store `td` into the `AbsDelayTime(idx)` place;
5. **return `V(z)`** as the value of the `absdelay` expression — `eq_z`'s row is
   left for the simulator to stamp.

### 2.4 `openvaf/sim_back/src/topology.rs` — keep equation indices aligned
The DAE builder used to `filter_map` away equations with dead/collapsed
unknowns. That would renumber equations and break the slot→node mapping. Version
2 changes it to `map` so **every** implicit equation keeps a slot in the
`unknowns` vector; dead/collapsed ones get a `Contribution::default()`
(zero-contribution) placeholder. The absdelay output rows are exactly these
"empty" rows — ngspice fills them in. This guarantees `ImplicitEquation` indices
stay valid as node indices.

### 2.5 `openvaf/sim_back/src/context.rs`
- Treat `PlaceKind::AbsDelayTime(_)` as a real output place (so it participates
  in output/eval-slot handling like other stored quantities).

### 2.6 `openvaf/osdi/src/inst_data.rs` — carry `td` into instance data
- New `delay_times: Vec<EvalOutputSlot>` on the instance-data layout, one slot
  per absdelay, populated from the `AbsDelayTime(i)` outputs.
- New `store_delay_times(...)` — writes each `td` slot during `eval`.
- New `delay_time_offset(i, target_data)` — returns the byte offset of slot *i*'s
  `td` inside the instance struct (this becomes `td_offset` in the descriptor).

### 2.7 `openvaf/osdi/src/eval.rs`
- Call `inst_data.store_delay_times(instance, &builder)` inside the generated
  `eval` so `td` is live in instance memory whenever the simulator reads it.

### 2.8 `openvaf/osdi/src/lib.rs` — export the descriptors
- Define the `OsdiAbsDelayInfo { y_node, z_node, td_offset }` LLVM struct type.
- For each module, for each `(eq_y, eq_z)` slot, resolve `y_node`/`z_node` from
  the DAE `unknowns` (`SimUnknownKind::Implicit(eq)` → node index) and
  `td_offset` from `delay_time_offset(i)`, and build a const struct.
- If any module uses absdelay, export the global arrays
  **`OSDI_ABSDELAY_COUNTS`** (per-descriptor slot count) and
  **`OSDI_ABSDELAY_INFOS`** (flattened slot descriptors).

---

## 3. ngspice simulator changes

9 OSDI files (8 edited + 1 new). The job: read the descriptors, allocate the
delay-row matrix entries and waveform history, and stamp `eq_z` for DC, AC,
and transient. The core analysis engine (`dctran.c`, `acan.c`, `optran.c`, …) is
**unchanged** — all support lives in the OSDI device layer.

### 3.1 `src/include/ngspice/osdiitf.h` — registry entry
- Added `uint32_t num_absdelays` and `const void *absdelay_infos` to
  `OsdiRegistryEntry`, filled at load time from the exported symbols.

### 3.2 `src/osdi/osdidefs.h` — data structures
- New `OsdiAbsDelayInfo { y_node, z_node, td_offset }` (mirrors the OpenVAF
  export).
- Extended `OsdiExtraInstData` with:
  - `delay_hist[][]` + `delay_hist_cap` — per-slot waveform history of
    `V(y_synth)`, indexed by accepted timepoint;
  - `delay_jac_y[]`, `delay_jac_z[]` — active matrix-entry pointers for the
    `(z,y_synth)` and `(z,z)` stamps;
  - `delay_jac_{y,z}_csc[]`, `delay_jac_{y,z}_cx[]` — KLU-only saved real and
    complex pointers (used by the AC fix in §3.8).

### 3.3 `src/osdi/osdiregistry.c` — read the descriptors
- At `.osdi` load, look up `OSDI_ABSDELAY_COUNTS` and `OSDI_ABSDELAY_INFOS`;
  for each descriptor compute its slice into the flattened infos array
  (`12` bytes/slot) and store `num_absdelays` + `absdelay_infos` on the entry.

### 3.4 `src/osdi/osdiext.h` and `src/osdi/osdiinit.c` — register accept hook
- Declare `OSDIaccept` and wire it as `OSDIinfo->DEVaccept = OSDIaccept;` so
  ngspice calls it after each accepted transient timepoint.

### 3.5 `src/osdi/osdisetup.c` — allocate entries + KLU binding
- In `OSDIsetup`: when `num_absdelays > 0`, allocate the history/pointer arrays
  and create the two matrix entries per slot with
  `SMPmakeElt(matrix, z_row, y_col)` and `SMPmakeElt(matrix, z_row, z_row)`.
- In `OSDIbindCSC` (KLU): rebind each delay pointer from the temporary COO
  buffer to the live KLU matrix, saving **both** the real (`CSC`) and complex
  (`CSC_Complex`) addresses (`delay_jac_*_csc` / `delay_jac_*_cx`).
- In `OSDIupdateCSC` (KLU real↔complex switch): repoint the active
  `delay_jac_*` pointers to the complex array for AC and back to real for
  DC/tran — see §3.8.

### 3.6 `src/osdi/osdiload.c` — DC and transient stamping (largest change)
New static helpers + hooks in `OSDIload`:
- `absdelay_ensure_timepoints` / `absdelay_grow_hist` — lazily allocate and grow
  `CKTtimePoints` and the per-slot history (ngspice only allocates
  `CKTtimePoints` for LTRA otherwise).
- `absdelay_lookup` — interpolate the delayed `V(y_synth)` at `t − td` from the
  accepted history (binary search), returning the value and a Jacobian `alpha`.
- `absdelay_stamp_dc` — steady state: a delay is an ideal wire, so stamp
  `jac[z,y]+=1`, `jac[z,z]+=−1` (`V(z)=V(y_synth)`), keeping the matrix
  non-singular.
- `absdelay_stamp_tran` — transient: initialize history on the first step, then
  stamp the interpolated delayed value into `eq_z`. **Sub-femtosecond delays
  (`td < 1e-15`) are treated as DC pass-through** so the epsilon delays that
  appear in photonic S11/S22 terms don't collapse the timestep.
- `OSDIload` calls `absdelay_stamp_tran` (transient) or `absdelay_stamp_dc`
  (DC) after the normal device load.

### 3.7 `src/osdi/osdiaccept.c` — **new file**, commit history
- `OSDIaccept` runs after each accepted transient timepoint and writes the
  converged `V(y_synth)` into `delay_hist[k][CKTtimeIndex]`, growing the history
  if `CKTtimePoints` grew. This is the data `absdelay_lookup` reads next step.

### 3.8 `src/osdi/osdiacld.c` — AC stamping
- For each slot, stamp the complex delay row: `(z,y_synth) += e^{-jωτ} =
  cos(ωτ) − j·sin(ωτ)` and `(z,z) += −1`. Magnitude is 1 (lossless delay); only
  the phase rotates with frequency, which is the physical group delay.

---

## 4. Bug fixes made while bringing the three analyses up

Two defects were found and fixed during development; both are folded into the
files above.

### 4.1 Transient "timestep too small" from epsilon delays
Some models emit `absdelay` terms with ~`1e-20 s` delays (S11/S22 phase
derivatives). Feeding those into the integrator drove the timestep toward zero.
Fix: in `absdelay_stamp_tran`, any `td < 1e-15` is stamped as a DC
pass-through (`V(z)=V(y_synth)`) instead of a true delay (`osdiload.c §3.6`).

### 4.2 AC singular matrix under KLU
KLU keeps **two** arrays per matrix entry — real (`CSC`) for DC/tran and complex
(`CSC_Complex`) for AC — and swaps the active pointer on every DC↔AC
transition. The absdelay delay-row pointers were only ever bound to the real
array, so during the AC complex solve the delay rows were stamped into the
unused real array → empty complex rows → singular matrix. (The legacy SPARSE
solver was unaffected because it stores `[real,imag]` adjacently in one
element.)

Fix (`osdidefs.h` + `osdisetup.c`): save both `CSC` and `CSC_Complex` for each
delay entry in `OSDIbindCSC`, and in `OSDIupdateCSC` switch the active
`delay_jac_*` pointer to the complex array for AC and back to real for DC/tran —
mirroring exactly how ngspice already handles the regular device Jacobian.
After the fix, KLU and SPARSE AC results are bit-identical.

---

## 5. Summary of changed files

### OpenVAF (`version2/OpenVAF-master`)
| file | lines | what |
|---|---:|---|
| `openvaf/hir_lower/src/lib.rs` | 12 | IR kinds: `AbsDelayTime`, `AbsDelayInput/Output`, `absdelay_equations` |
| `openvaf/hir_lower/src/ctx.rs` | 1 | default `td` place to 0 |
| `openvaf/hir_lower/src/expr.rs` | 58 | **lower `absdelay` to the two-node DAE form** |
| `openvaf/sim_back/src/topology.rs` | 20 | keep equation indices aligned (placeholder rows) |
| `openvaf/sim_back/src/context.rs` | 5 | `AbsDelayTime` is an output place |
| `openvaf/osdi/src/inst_data.rs` | 31 | store `td` in instance data; offset accessor |
| `openvaf/osdi/src/eval.rs` | 1 | call `store_delay_times` in `eval` |
| `openvaf/osdi/src/lib.rs` | 62 | **export `OSDI_ABSDELAY_COUNTS` / `OSDI_ABSDELAY_INFOS`** |

### ngspice (`version2/ngspice-46/src`)
| file | lines | what |
|---|---:|---|
| `include/ngspice/osdiitf.h` | 4 | `num_absdelays`, `absdelay_infos` on registry entry |
| `osdi/osdidefs.h` | 29 | `OsdiAbsDelayInfo`, history + matrix-pointer fields |
| `osdi/osdiregistry.c` | 29 | read the exported symbols at load time |
| `osdi/osdiext.h` | 1 | declare `OSDIaccept` |
| `osdi/osdiinit.c` | 1 | register `DEVaccept = OSDIaccept` |
| `osdi/osdisetup.c` | 90 | allocate entries/history; KLU bind + real/complex switch |
| `osdi/osdiload.c` | 226 | **DC pass-through + transient history stamping** |
| `osdi/osdiaccept.c` | 86 | **new** — commit converged `V(y_synth)` to history |
| `osdi/osdiacld.c` | 46 | **AC `e^{-jωτ}` stamping** |

The core ngspice analysis files (`acan.c`, `dctran.c`, `optran.c`, `span.c`,
`noisean.c`) are **unchanged**.

---

## 6. Build & verify

```bash
# compiler
cd ./OpenVAF-master && ./configure && ./build.sh --release
#   -> target/release/openvaf-r   (also copied to ./bin/openvaf-r)

# simulator
cd ./ngspice-46/build && make -C src -j4
#   -> src/ngspice                (also copied to ./bin/ngspice)

# end-to-end checks
cd ./absdelay_examples
bash examples/run_examples.sh      # DC/AC/tran, KLU vs SPARSE agree
bash benchmark/run_benchmark.sh    # KLU vs SPARSE timing sweep
```

