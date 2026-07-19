# Enhancement-234 — `loadpull`: power-amplifier load-/source-pull analysis

Load-pull — sweeping the load (and source) impedance a device/PA sees and
contouring output power, gain, PAE, and efficiency on the Smith chart — is a
staple of power-amplifier design that ngspice lacked, and open-source load-pull
is genuinely scarce. This adds a `loadpull` command that rides the existing
`.tran` engine, the `alter` mechanism (as `optimize`/`sweep` do), and the
`pyplot -contour` renderer (E-218), so it is mostly orchestration over machinery
already in the fork.

## What it does

`loadpull -load <R> <L> <C> -out <node> -drive <Vsrc> -f <f0> [-supply <Vsrc>] …`
sweeps Γ over a grid inside `|Γ| ≤ gmax`. At each point it synthesizes the target
impedance `Z = z0·(1+Γ)/(1−Γ) = R + jX` on the three series load elements (the
resistor set to `R`; the inductor/capacitor giving `+X`/`−X`, the unused reactor
parked near a short so the branch is an AC-coupled `R+jX` at `f0`), runs a
large-signal `.tran`, and extracts the fundamental by a direct DFT over the last
`nper` periods. It computes, per point:

* **Pout** = ½·|V_out(f0)|²·R/|Z|² (power delivered to the load),
* **gain** = Pout / Pin (Pin from the drive source's fundamental V·I\*),
* **PAE** = (Pout − Pin) / Pdc, and **drain efficiency** = Pout / Pdc, when a DC
  `-supply` is given (Pdc = V_dd · I_dc).

Results are stored as `gamma_re`, `gamma_im`, `pout_dbm`, `gain_db`[, `pae`,
`eff`] in a `loadpull` plot; `pyplot -contour gamma_re gamma_im pout_dbm` draws
the classic contours. `-source <Rs> <Ls> <Cs>` sweeps the **source** impedance
instead (source-pull). The transient engine means it works under either linear
solver.

Implementation is one new frontend file (`frontend/com_loadpull.c`) modeled on
`com_stb` — a synchronous command runner, expression evaluation via
`ft_getpnames_from_string`/`ft_evaluate`, and result vectors via
`dvec_alloc`/`vec_new`.

## A use-after-free found and fixed along the way

The branch-current metrics (gain, PAE, efficiency) were initially wrong — gain
read as 0 and efficiency exceeded 100%. Root cause: the source-terminal lookup
called `INPretrieve(&name, symtab)`, which **replaces the pointer with the
interned UID string** — the same memory the voltage source's own `VSRCname`
field points at — after which `tfree()` freed the source's live name. It did not
crash; instead the sweep's per-point re-setups re-created the drive source's
branch node from that freed memory (which the allocator had refilled with other
UID strings, e.g. `dr`, then `tran`), so `vdr#branch` silently became
`tran#branch` and the metrics read the wrong source's current. The fix drops
`INPretrieve` (top-level device names need no subcircuit translation) and frees
only the local copy. **`com_stb` (E-198) carries the identical latent
use-after-free** — it never triggers there because `stb` runs once with no
re-setup — and is worth a defensive follow-up.

## Verification (`examples/loadpull_examples`)

`verify_loadpull.py` (4 checks): (1) a **linear Thévenin source** (Vs = 1 V,
Zs = 50 + j30) peaks Pout at `Γ_L = conj(Γ_s)` with the analytic
`Pmax = |Vs|²/(8·Rs) = 3.979 dBm` — measured 3.970 dBm at the nearest grid node;
(2) a behavioral PA yields **physical** gain/PAE/efficiency (`0 < PAE < eff <
100%`: gain 28 dB, eff 96%, PAE 96%), which also guards the use-after-free fix;
(3) source-pull runs and reports an optimum.

## Scope

ngspice frontend only — one new file (`frontend/com_loadpull.c`) plus command
registration (`frontend/commands.c`, `frontend/com_commands.h`,
`frontend/Makefile.am`); no solver, analysis, device, or compiler change. Full
regression: 192/192.
