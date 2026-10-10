# Bug hunt — ngspice and openvaf-r: a robustness and correctness campaign

**When:** 2026-10-10.
**Binaries:** the repo's `ngspice-46/build/src/ngspice` (built 2026-10-10 08:35) and
`OpenVAF-master-20260610/target/opt/openvaf-r` (2026-10-10 08:22), both at E-835. Tree at `8681f4b8`.

**Method:** five families of generated checks, run one compile or simulation at a time under a
12 GB RSS cap, through throwaway harnesses in the session scratchpad (`rc/*.py`). Each family
checks against a reference that does not share code with the thing under test:

- **A. The loaded Jacobian against finite differences.** For every compact model in the
  `VA_TEST` corpus (92 standalone modules), the conductance matrix ngspice solves in an `ac`
  analysis at 1 Hz, internal nodes eliminated by the solve, is compared with central finite
  differences of the dc terminal currents. Each terminal is driven in turn by
  `alter @vk[acmag] = 1`, and the comparison column is the terminal currents from a three-point `dc`
  sweep of the same source. The bias is chosen by terminal names, so the device conducts:
  d, g, s, b at 1, 1, 0, 0; c, b, e, s at 1.5, 0.8, 0, 0; a, c at 0.7, 0. Tight tolerances
  (`reltol=1e-9`) are used. The noise floor is `10*(reltol*Imax + abstol)/h`, and the
  threshold is 1e-3 of the column's largest entry.
- **B. Random linear networks against a dense solve.** 600 networks of 3 to 30 nodes with R, C,
  L, V, I, G, E, F and H elements, spanning-tree connected, are stamped into MNA by a separate
  numpy script. Each is solved by `op` and by `ac` at 1 Hz, 1 kHz, 1 MHz and 1 GHz, under Sparse
  and under KLU, for 1 200 runs in all.
- **C. Compiler mutation fuzz.** 1 500 mutants of the examples' 709 tracked `.va` files. The
  mutator works on tokens and keeps each gap's whitespace and comments: it deletes, duplicates,
  swaps or truncates tokens, inserts one of 101 Verilog-A snippets or 18 keywords, sets a
  number to one of 8 extremes, and replaces identifiers. An unchanged round trip reproduces all 709 files byte for
  byte. A compile is flagged on a panic (exit 101), a signal, an LLVM error, a timeout (60 s)
  or the memory cap.
- **D. Deck mutation fuzz under Guard Malloc.** 3 000 mutants of the examples' tracked `.cir`
  decks, skipping those that use `shell` or `cd`. Each mutant gets one to three line or token
  mutations: an extreme value, an injected card or control command from a list of 75, a
  deleted or duplicated line, or a node replaced by 0. Each runs under macOS Guard Malloc
  (`DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib`), and every flag is re-run without it
  before it counts.
- **E. A Verilog-A twin against a built-in device.** The SPICE level-1 diode, written in
  Verilog-A with is, n, rs, cjo, vj, m, fc, tt, kf and af, is compared with the built-in `d`
  on the same card. The analyses are `op`, `dc`, `ac`, `tran` and `noise`, under both solvers.

Two regressions turned up, and each was bisected to the enhancement that introduced it. A
sparse git worktree held one tree, ngspice or OpenVAF, and was rebuilt at each step: 9 steps
for ngspice, 8 for the compiler.

Nothing was fixed; this is the list.

| | Finding | Severity |
|---|---|---|
| [F1](#f1) | *(fixed in [E-836](../../enhancements_doc/Enhancement-836.md), [E-837](../../enhancements_doc/Enhancement-837.md) and [E-838](../../enhancements_doc/Enhancement-838.md); E-734 exposed it rather than caused it -- 13 of the 14 are back, VBIC 4T-et is open at its defaults)* 14 of the corpus's 92 compact models no longer reach an operating point (bsimbulk ×3, bsimcmg ×2, bsimimg, HICUM L0 ×2, HICUM L2 ×3, HiSIM-SOI ×2, VBIC 4T-et): a regression from E-734 | high |
| [F2](#f2) | *(fixed in [E-839](../../enhancements_doc/Enhancement-839.md): the `sqrt`, `pow`, `hypot` and `atan2` guards replace only the singular point; HiSIM-HV and HiSIM-SOTB were F2 too)* openvaf-r loads a wrong Jacobian wherever a `sqrt` argument is small: E-261's regularisation `2*sqrt(x + 1e-18)` changes the derivative by `5e-19/x`, which is 8 % on HiSIM-SOI's gm | high |
| [F3](#f3) | *(fixed in [E-840](../../enhancements_doc/Enhancement-840.md): any refused analysis command did it, and the freed job was the previous command's; `CKTdelTask` clears the pointer)* **memory:** `op`, then a refused `sens`, then `reset` reads the freed `sens` job through `CKTcurJob` in `DCtran_step_quit` | medium |
| [F4](#f4) | a second `sens` job in one run fails its operating point on a resistor divider; under Guard Malloc the device load reads freed memory | medium |
| [F5](#f5) | **crash:** `envelope` after a device refused at setup copies from a NULL `CKTrhsOld`; E-502's guard only asks for `CKTmatrix` | medium |
| [F6](#f6) | **crash:** a deck that `source`s itself, or two that source each other, recurse until the stack overflows; `.include` stops at 50 levels | low |
| [F7](#f7) | **compiler panic:** `parameter p p = 1;` reports its parse error, then panics on a salsa query cycle | low |

<a id="f1"></a>
## F1 — 14 corpus models no longer reach an operating point

*Fixed in [E-836](../../enhancements_doc/Enhancement-836.md),
[E-837](../../enhancements_doc/Enhancement-837.md) and
[E-838](../../enhancements_doc/Enhancement-838.md). The dig corrected the lead below. E-734 only
took away the leaked gmin that had hidden three different things, and the "check node" names
that pointed into the models' source networks were wrong themselves:*
- *The names were wrong because OSDI internal rows were named after the wrong descriptor node
  once anything collapsed (E-836). `n1#si` was BSIM-BULK's thermal branch.*
- *11 models (bsimbulk, bsimcmg, bsimimg, HICUM) were a loop of voltage sources. Each ties its
  thermal terminal to ground with self-heating off (`Temp(t) <+ 0`), and the harness held the
  same terminal with a 0 V source. That loop is now named, a model short duplicated across
  instances is dropped, and the harness grounds such a terminal (E-837).*
- *HiSIM-SOI's `db` and `sb` are written only in the 5-terminal mode, so in the 4-terminal mode
  their rows are all zero. They are now held at the reorder (E-838).*
- *`vbic_4T_et_cf` opens every series resistor at its defaults, so its internal nodes float
  together. It is refused honestly; in July it read exactly 0 A.*

*The corpus campaign is at 90 of 92 (EPFL-HEMT's compile refusal is intended).*

`VA_TEST/correctness_campaign.py` biased all 92 standalone models at a plain bias and got an
operating point for every one on 2026-07-19 (`cdc6faf4`). Today it reports
`{'OK': 77, 'COMPILE-FAIL': 1, 'DC-NOCONV': 14}`. The one that no longer compiles is EPFL-HEMT,
refused by the LRM 4.4 same-net branch diagnostic, which is an intended change.

The 14 that no longer converge:

| family | files |
|---|---|
| BSIM-BULK | `bsimbulk.va`, `bsimbulk106.va`, `bsimbulk107.va` |
| BSIM-CMG | `vacode/bsimcmg.va`, `vacode111/bsimcmg.va` |
| BSIM-IMG | `bsimimg.va` |
| HICUM L0 | `hicumL0_v2p0p0.va`, `hicumL0_v2p1p0.va` |
| HICUM L2 | `hicumL2V2p4p0.va`, `hicumL2V3p0p0.va`, `hicumL2_v310.va` |
| HiSIM-SOI | `vacode/hisimsoi_n4.va`, `vacode/hisimsoi_n5.va` |
| VBIC | `vbic_4T_et_cf.va` |

The smallest deck that shows it uses BSIM-BULK with every parameter at its default:

```spice
.control
pre_osdi bsimbulk.osdi
.endc
vd d 0 1
vg g 0 1
vs s 0 0
vb b 0 0
n1 d g s b t nch
vt t 0 0
.model nch bsimbulk
.control
op
print i(vd)
.endc
.end
```

Today's build fails it. It prints `singular matrix: check node n1#si`, and then dynamic gmin,
true gmin, source stepping, the transient op and damped Newton all fail (exit 1). The
version11 build gives `i(vd) = -6.58515e-07`. HICUM's message names `n1#xf1`, and E-833's
warning names `n1#di1` and `n1#bi` as having no DC path. The other compiler gives the same
result: the failure follows the ngspice binary, not the `.osdi`.

**Bisect:** the first bad ngspice commit is `6ceb890d`,
[E-734](../../enhancements_doc/Enhancement-734.md) (source stepping puts the diagonal gmin back
when it is done). Before it, source stepping left `CKTdiagGmin` at gmin, and every later Newton
call factored with a 1e-12 S shunt on every node. That leak was what held these models'
internal nodes. At the good commit (`cdc6faf4`) the op converged only after about 280
iterations, with singular warnings on the way. Their rows are numerically zero at this bias,
so the factorisation finds no pivot without the shunt. E-575's dc-path walk does not hold them
because it reads the sparsity pattern, which shows them connected.

| option | effect on the op |
|---|---|
| `.option gshunt=1e-12` | converges (`i(vd) = -6.58516e-07`), but the `ac` that follows is still singular |
| `noosdilim`, `klu`, `dcpath=off`, `noreusesetup`, `sparsediaggmin` | none |

**Lead:** E-734 was right to stop the leak. The models need a deliberate hold in its place:
a gmin to ground on an OSDI internal node whose row is numerically empty at the bias, decided
by value rather than by pattern, and kept through `ac`, `noise` and `pz`.

<a id="f2"></a>
## F2 — openvaf-r's `sqrt` derivative is wrong for small arguments

*Fixed in [E-839](../../enhancements_doc/Enhancement-839.md). Each guard now replaces only the
singular value, with a select, so every derivative away from it is the unguarded one, bit for
bit. The dig found the same shift in three more guards: E-262's `pow`, for every exponent
(`pow(x, 2)` at x = 1e-17 was 10 % high), and E-580's `hypot` and `atan2`. Re-run with the
fixed compiler, the Jacobian family's 9 HiSIM-HV and 2 HiSIM-SOTB mismatches, which this page
had put down to finite-difference truncation, agree too: they were this finding.*

Family A found one model whose loaded Jacobian disagrees with its own currents: HiSIM-SOI
(`vacode140/hisimsoi_n4.va` and `_n5.va`, at d, g, s, b = 1, 1, 0, 0). The dc currents are
identical with either compiler; the Jacobian is not:

| | gm (A/V) | relative |
|---|---|---|
| finite difference, h = 1e-3, 1e-4, 1e-5 | −2.384236e-4 | — |
| `ac` at 1 Hz and at 1e-9 Hz, today's openvaf-r | −2.197346e-4 | 7.8e-2 |
| `ac`, version11's openvaf-r or the `cdc6faf4` compiler | −2.384236e-4 | 2.5e-10 |

gds is off by about 10 %. Neither the step nor the frequency moves the gap, so it is not
truncation or a capacitive term.

**Bisect:** the first bad compiler commit is `69de4a6f`,
[E-261](../../enhancements_doc/Enhancement-261.md) (guard the `sqrt()` derivative singularity).
The `sqrt` derivative cache in `mir_autodiff/src/builder.rs` became `2*sqrt(x + a)` with
`a = 1e-18`, which is finite at x = 0. The commit message says the change is below the ULP for
any x > 0. It is not: the relative change to the derivative is `a/(2x) = 5e-19/x`. That is
below 1 ULP only above x of a few times 1e-3; it is 0.05 % at 1e-15 and 5 % at 1e-17.

Compact models written in SI units take square roots of quantities that small all the time:
squared charges, products of doping and permittivity, areas. A ten-line module shows it:

```verilog
module sq(a, c);
inout a, c; electrical a, c;
parameter real s = 1e-17;
analog I(a, c) <+ 1e6*sqrt(s*V(a, c));
endmodule
```

At V = 1 the `ac` conductance is 1.507557e-3 against the exact 1.581139e-3, a 4.7 % error,
while the op current, 3.162278e-3, is exact.

Every quantity built from the Jacobian inherits the error: `ac`, `noise`, `pz`, `tf`, `sens`,
and the small-signal capacitances, which are derivatives too. The op and transient values
are only slowed, because Newton converges to the right residual with a wrong slope. E-580's
`hypot` cache, `hypot(h, 1e-18)`, has the same shape, but its error `a²/(2h²)` matters only
below h ≈ 1e-17.

**Lead:** make the guard relative, or apply it only where the plain cache `2*sqrt(x)` is zero,
for example with a select. A derivative at x > 0 must then be bit-identical to the unguarded
one.

<a id="f3"></a>
## F3 — a refused `sens` leaves `CKTcurJob` pointing at freed memory

*Fixed in [E-840](../../enhancements_doc/Enhancement-840.md). The lead below was wrong about
which job was freed:*
- *`if_run` deletes the previous interactive command's task, and with it the `op` job
  `CKTcurJob` still named, before it parses the new card.*
- *A card refused there never re-points `CKTcurJob`: `sens v(nosuch)`, `ac dec 0 1 1`,
  `tran 1u`, `tf v(nosuch) v1` and `noise v(nosuch) …` all do it.*

*`CKTdelTask` now clears the pointer when it frees the job it names, closing a stepped
transient's plot first, and `remcirc` deletes the tasks before it frees the circuit. F4, the
second `sens` job, is a different path and stays open.*

```spice
v1 a 0 1
r1 a 0 1k
.control
op
sens v(nosuch)
reset
echo survived
.endc
.end
```

The `sens` is refused (no such node). Without Guard Malloc the deck prints `survived` with exit
status 1, so the use-after-free goes unnoticed. Under Guard Malloc it is SIGSEGV every time:

```
DCtran_step_quit+24 <- com_remcirc <- com_rset <- doblock <- cp_evloop
```

`reset` calls `DCtran_step_quit(ft_curckt->ci_ckt)` (`frontend/runcoms2.c:247`), which reads
`ckt->CKTcurJob->JOBtype` (`dctran.c:1452`). `CKTcurJob` still points at the `sens` job, which
was freed on the error path. An `op` between the `sens` and the `reset` re-points `CKTcurJob`
and hides it. A `tran` before the `sens` crashes the same way, and so does `mcsample` before
the `reset`. Fuzz mutant t1193 found it, from `lhs_examples/lhs_demo.cir` with a `sens v(1)`
inserted into its `reset`/`op` loop.

**Lead (not confirmed):** `CKTdoJob` runs a sens job with `ckt->CKTsenInfo` pointing at the job
itself and frees it through `CKTsenInfo` on error, while the task's job list and `CKTcurJob`
still hold it.

<a id="f4"></a>
## F4 — a second `sens` job reads what the first freed

```spice
v1 in 0 dc 1
r1 in mid 1k
r2 mid 0 3k
.sens v(mid)
.sens v(mid)
.control
run
.endc
.end
```

The first `sens` runs and reports (`r1 = -1.875e-04`, `r2 = 6.25e-05`). The second fails its
operating point on the same divider: `singular matrix: check node in`, then every homotopy
fails, `SENS: Timestep too small`, and the run aborts with exit 1. One `.sens` alone is fine.
Under Guard Malloc the second job faults in a device load, `RESload` or `VSRCload` depending
on the layout:

```
RESload+64 <- CKTload <- NIiter <- CKTop <- sens_sens <- CKTdoJob
```

| cards | plain | Guard Malloc |
|---|---|---|
| `.sens v(mid)` + `.op` / `.tran` / `.dc` | ok | ok |
| `.op` + `.sens v(mid)` | ok | ok |
| `.sens v(mid)` + `.sens v(in)` | exit 1, singular | SIGSEGV |
| `.sens … ac dec 1 1 1k` + `.sens v(mid)` | exit 1, singular | SIGSEGV |

Only a second `sens` is hit. That points to the `CKTsenInfo` ownership in F3: the first job
frees sensitivity state that the second reuses. Fuzz mutant t2184 found it, from
`analyses_examples/sens_dc.cir` with its `.sens` line duplicated.

<a id="f5"></a>
## F5 — `envelope` after a setup refusal copies from NULL

```spice
v1 1 0 dc 1 sin(0 1 1meg)
r1 1 2 1k
c1 2 0 1n
t1 2 0 3 0 z0=0 td=1n
r2 3 0 50
.control
envelope 2 1meg 10u
.endc
.end
```

The settling transient is refused at setup: `TRAsetup` reports that `z0 = 0` is not a usable
characteristic impedance. `envelope` carries on and crashes deterministically, with or without
Guard Malloc:

```
_platform_memmove (address 0x0) <- EFanalysis+332 <- com_envelope <- doblock
```

`com_envelope.c` already checks that the transient ran (E-502), but its test is
`ft_curckt->ci_ckt->CKTmatrix != NULL`. The matrix is created before the device setups run,
while `CKTrhsOld` is allocated only after they all succeed. So a setup-stage refusal passes the
guard, and `EFanalysis` does `memcpy(x, ckt->CKTrhsOld, …)` (`envelope.c:267`).

The same refusal followed by each of 27 other analysis and output commands was refused cleanly
with exit 1, under Guard Malloc too: `op`, `dc`, `ac`, `tran`, `noise`, `pz`, `sens` (dc and ac),
`tf`, `disto`, `pss`, `hb`, `sp`, `linearize`, `fourier`, `meas`, `write`, `run`, `resume`,
`alter`, `reset`, and `show`/`print all`. `envelope` is the only command that reads the state
of its own internal run. Fuzz mutant t5869 found it: the line `tran 0 0`, injected into
`envelope_demo.cir`, reads as a lossless line named `tran`.

<a id="f6"></a>
## F6 — `source` recursion overflows the stack

```spice
* s.cir
r1 1 0 1k
v1 1 0 1
.control
source s.cir
.endc
.end
```

`ngspice -b s.cir` recurses `com_source → inp_spsource → cp_evloop → doblock → com_source`
until the stack overflows: SIGSEGV (exit 139) after 1.3 s. Two
decks that source each other do the same. The netlist equivalent is refused at once:
`.include i.cir` inside `i.cir` stops with "`.include nesting too deep (> 50 levels), likely
a circular include`". Fuzz mutant t6027 found it, from `slew_examples/dc_sim.cir` with
`source fz.cir` injected. It was first flagged as a 30 s timeout under Guard Malloc.

<a id="f7"></a>
## F7 — a parameter named as its own type panics the compiler

```verilog
module m(a); inout a; electrical a;
parameter p p = 1;
analog V(a) <+ p;
endmodule
```

openvaf-r prints the right error (`unexpected token identifier; expected '='`) and then
panics. It exits 101 with the "please open an issue" banner and a crash log:

```
salsa::Cycle <- SyncMap::claim <- HirTyDB::inference_result <- hir_ty::db::param_ty
  <- Ctx::infere_expr <- … <- hir::diagnostics::collect_body_diagnostcs
```

After error recovery the parameter's default expression refers back to the parameter, and
`param_ty` asks for its own inference. The well-formed spellings are diagnosed properly, with
exit 65: `parameter real p = p;` gets "definition of 'p' references itself", and a forward
reference gets "references parameter 'r' defined afterwards". Fuzz mutant t1382 found it,
from `vafintub_examples/intub.va`, with `parameter integer ione` mutated to
`parameter ione ione`. It was the only flag in the 1 500 compiles.

## Verified clean

- **A, the Jacobian:**
  - 63 modules agree within 1e-3 of the column scale after the noise floor, and the 14 of F1
    cannot be tested.
  - The 9 HiSIM-HV mismatches (2.1e-3 to 2.4e-3) and the 2 HiSIM-SOTB ones (1.0e-2 and
    1.7e-2) were put down here to finite-difference truncation, since they agreed at
    h = 1e-4. That was wrong: they are F2's guard error. The smaller step only lifted the
    noise floor above it, and with E-839's compiler they agree at h = 1e-3.
  - bsimsoi's 124 % at 1 Hz is its floating body, whose time constant puts 1 Hz above the dc
    limit. It drops to 3.7 % at 1e-9 Hz, where the FD of a 8e-8 A device is itself noisy;
    inconclusive, not counted.
- **B, linear networks:** 1 200 runs; 7 exceeded 1e-6 relative against numpy (worst 2e-5).
  Every one is an ill-conditioned network: the ngspice solution's backward error is about
  1e-17, the same as numpy's, or the exact solution is near zero.
- **C, the compiler fuzz:** 1 500 compiles, with 1 455 refused by diagnostics (exit 65), 44
  compiled and 1 panic (F7). There were no signals, no LLVM errors, no timeouts and no
  memory-cap hits.
- **D, the deck fuzz:** 3 000 mutants, with 18 flags under Guard Malloc. 4 are real (F3, F4,
  F5, F6). The other 14 are Guard Malloc artefacts:
  - 10 memory-cap hits, all on the progress-bar deck: its mutants run up to a million rows,
    113 MB without Guard Malloc;
  - 4 timeouts of 30 s (`rc_pxf`, `zi` `ac_sim`, `opt100` twice);
  - re-run without it, each ends normally.
- **E, the diode twin:** with default tolerances it agrees to 1.4e-6 (op) and 6e-4 (tran). At
  `reltol=1e-9` the twin's `$vt` (CODATA 2018) is the only difference: written with ngspice's
  constants instead, the comparison gives
  - op 7.9e-15, dc 2.7e-11, ac 2.0e-14;
  - tran 1.5e-7, noise 6.4e-7, from `` `P_K `` and `` `P_Q `` in the noise sources;
  - the same under Sparse and KLU.

  The CODATA gap is documented in `docs/internals/ngspice_internals/ngspice_temperature.md`.
