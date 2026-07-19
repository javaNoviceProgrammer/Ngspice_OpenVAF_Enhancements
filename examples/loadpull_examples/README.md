# Load-pull / source-pull analysis (Enhancement-234)

**Load-pull** is a staple of power-amplifier design: sweep the load impedance the
device output sees over the Smith chart and contour output power, gain, PAE, and
drain efficiency to find the optimum load. ngspice had no such command;
open-source load-pull is genuinely scarce. This adds one, riding the existing
`.tran` engine and `alter` mechanism (as `optimize`/`sweep` do), with contours
rendered by `pyplot -contour` (E-218).

## Usage

```
loadpull -load <R> <L> <C> -out <node> -drive <Vsrc> -f <freq>
         [-supply <Vsrc>] [-z0 50] [-n 15] [-gmax 0.85] [-nper 20] [-npts 50]
loadpull -source <Rs> <Ls> <Cs> -out <node> -drive <Vsrc> -f <freq> ...   (source-pull)
```

* `-load R L C` — three series elements (out → ground) that present the swept
  load. For each Γ the target `Z = z0·(1+Γ)/(1−Γ) = R + jX` is synthesized: the
  resistor is set to `R`, and the inductor/capacitor give `+X`/`−X` (the unused
  reactor parked near a short, so the branch is an AC-coupled `R+jX` at `f0`).
* `-out` — the output node; the fundamental power delivered to the load is
  measured here.
* `-drive` — the input drive source (for Pin → gain).
* `-supply` — the DC supply source (for PAE and drain efficiency). Optional; omit
  for a passive/linear load-pull (just Pout / gain).
* `-source Rs Ls Cs` — sweep the **source** impedance instead (source-pull).
* `-n` grid points per axis, `-gmax` max |Γ|, `-nper` periods integrated,
  `-npts` timepoints/period, `-z0` reference impedance.

Each Γ point runs a large-signal `.tran`, extracts the fundamental by a direct
DFT over the last `nper` periods, and computes **Pout, gain, PAE = (Pout−Pin)/Pdc,
drain efficiency = Pout/Pdc**. Results are stored as `gamma_re`, `gamma_im`,
`pout_dbm`, `gain_db`[, `pae`, `eff`] in a `loadpull` plot; the optimum (max Pout)
load and its impedance are reported.

```
loadpull -load RL LL CL -out out -drive Vdr -supply Vdd -f 1e9 -n 21
pyplot -contour gamma_re gamma_im pout_dbm      ; power contours on the Smith grid
pyplot -contour gamma_re gamma_im pae
```

## Verify

```sh
python3 verify_loadpull.py
```

Four checks: (1) a **linear Thévenin source** (Vs, Zs = 50+j30) peaks Pout at
`Γ_L = conj(Γ_s)` with the analytic `Pmax = |Vs|²/(8·Rs) = 3.979 dBm`; (2) a
behavioral PA yields **physical** gain/PAE/efficiency (`0 < PAE < eff < 100%`);
(3) source-pull runs. Check (2) also guards the E-234 fix — a use-after-free in
the source-name lookup was silently corrupting the branch-current metrics.
