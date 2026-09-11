# Enhancement-610: `.option savemc` — every parameter with statistics, one row per run, in a file beside the netlist

**Scope:** `src/frontend/mcsave.c` and `mcsave.h` (new: the recorder, the csv/txt writers,
a stored-zip `.xlsx` writer), `src/frontend/numparam/xpressn.c` (a `.param` or subcircuit
value drawn; a device slot whose brace draws or reads a drawn symbol, named by the slot),
`numparam/spicenum.c` (a deck expansion begins), `src/frontend/com_sweep.c` (the fast
path's re-derived slots, by the same names), `src/osdi/osdisetup.c` and
`src/include/ngspice/osdiitf.h` (`OSDImcEnabled`, `OSDImcHasStats`, `OSDImcSnapshot`: the
declared-statistics parameters read off the devices), `src/frontend/spiceif.c` (the row
after each run-class command; the four option names known), `src/frontend/runcoms2.c`,
`src/main.c` (the file completed when the circuit goes or ngspice exits),
`src/frontend/Makefile.am`, `examples/savemc_examples/` (new, 17 checks per solver);
handbook [§3.6](../docs/handbook/03-ngspice-workflows.md). **ngspice only.** Requested by
the user.

**Suites:** [`savemc_examples`](../examples/savemc_examples/) 17 of 17 per solver, both
solvers; `osdimc`, `mcrecord`, `mcpolicy`, `mcarming`, `mcfastpath`, `mctrack`, `mcyield`,
`sweepparam`, `nupafail`, `hunt3diag`, `lhs` unchanged; full sweep 504 of 504.

## What was asked

A run with statistics — `.param`s drawn by `agauss`/`gauss`/`unif`/`aunif`/`limit`/
`mvnorm`, device values drawn in place, a Verilog-A model's `(* std= *)` parameters under
`.option osdimc` — produced results but no record of the draws behind them. Reconstructing
a sample's parameter set meant `print`ing every `@dev[param]` by hand in a loop.

## What changed

**`.option savemc`** records, for every run-class command (`op`, `tran`, `run`, … — what
`if_run` dispatches, `resume` excluded), one row with the value in force of every parameter
with statistics:

- a **device slot whose value draws** — `r1 in out {agauss(1k,50,1)}`, or a random `.param`
  used there: ngspice inlines a random `.param` into each use, so each use is its own draw
  (`.param rv=agauss(...)` with `r1 ... {rv}` and `r2 ... {rv}` gives two draws), named by
  the slot, `r1`, `r2`, or `m1:w` for `w={...}`; a slot that reads a drawn symbol (a
  subcircuit's `r1 a b {p}` under `x1 ... p={gauss(...)}`) is a draw too, `r.x1.r1`;
- a **subcircuit call's own drawn value**, `x1.p`;
- under `.option osdimc`, every **OSDI parameter with declared statistics**, read off the
  devices when the row is made, `@<model>[<param>]` for a process parameter,
  `@<instance>[<param>]` for a mismatch one — so the baseline trial reports the nominal
  and a pinned or pending draw what the device actually ran with.

The numparam draws are recorded as they are evaluated (a source, a `reset`, a sweep's or
montecarlo's in-place re-evaluation); under montecarlo's fast path a subcircuit call's
own value is not re-derived and its column is empty on those rows, while the device slots
it feeds are recorded. The row carries `trial` (1, 2, …), `analysis` and `status` (`ok`,
or `failed` for a run that did not solve — the draw happened). Columns are fixed by the
first row and grow if a later row brings a new name.

**The file** is `mcparams_<YYYYMMDD>_<HHMMSS>.<ext>` in the netlist's directory (the
working directory for a deck not read from a file), made unique within a second
(`_2`, `_3`); `savemc=csv` (the default), `savemc=txt` (tab-separated), `savemc=excel`
(a genuine `.xlsx`: a stored zip with inline strings, readable by Excel, Numbers,
LibreOffice and openpyxl — written in full every 25 rows and when the circuit is freed or
ngspice exits), or `savemc=<name>.<csv|txt|xlsx>` for a file of that name beside the
netlist (an absolute path is taken as is). csv and txt are appended row by row and
flushed. One file per deck: a `reset` continues it — every `montecarlo` sample is one row
— and a different deck sourced in the session starts its own; `nosavemc` turns it off.

**`.option automc_save`** (alias `osdimc_save`, with the same values) records the OSDI
parameters only — the automatic Monte Carlo's own draws, without the deck's `.param`
draws. A deck with nothing to record says so once; OSDI statistics declared with `osdimc`
off are noted as not drawn and not recorded.

```
.option savemc osdimc mcseed=5
.param rv = agauss(1k, 50, 1)
r1 in mid {rv}
x1 mid out sub p={gauss(500, 0.1, 1)}
n1 out 0 sm
.model sm st r=1k                    ; st: (* std=25 *) r, (* type="instance", std=10 *) dr
.control
montecarlo 200 -analysis op -expr vo=v(out)
.endc
```

```
trial,analysis,status,r1,x1.p,r.x1.r1,@n1[dr],@sm[r]
1,op,ok,1022.67410253,,505.914206982,-7.303958302,992.359449651
2,op,ok,1090.41078785,,514.175610022,-20.7636901255,998.434353482
```

## Verification

| check | result |
|---|---|
| `.option savemc`, `op`, `reset`, `op` | one csv beside the deck (the working directory elsewhere), `mcparams_<date>_<time>.csv`; header `trial,analysis,status,r1,r2,x1.p,r.x1.r1`; two rows equal to `@r1[r]`, `@r2[r]`, `@r.x1.r1[r]` of each run |
| `montecarlo 6` on the fast path | six rows; `r1` and `r.x1.r1` equal the `-expr` records; `x1.p` empty there |
| `osdimc`: `op`, then `montecarlo 5` | the baseline row nominal (0, 1000); `@n1[dr]`, `@sm[r]` per sample equal the `-expr` records |
| `savemc=excel`, 30 samples | a valid `.xlsx` (zip test clean, workbook/styles/sheet parts), the header, 31 rows at exit, sample 3 equal to the record; openpyxl reads it with typed numbers |
| `savemc=txt`; `savemc=myrun.txt`; `savemc=csv` | tab-separated; the named file in the deck's directory; as the bare option |
| `automc_save`; `osdimc_save=txt` | the OSDI columns only, equal to the records; the alias with a format |
| nothing statistical; OSDI statistics with `osdimc` off; `automc_save` without OSDI statistics | the note once and no file; the note; the scope named |
| `op`, `tran`, a refused `dc` | three rows, the third `failed`, the same draw on all |
| two runs in one second; a second deck sourced | distinct names (`_2`); the second deck's own file, the first complete |
| `savemc nosavemc automc_save osdimc_save` on a card | no "unknown option"; `nosavemc` off |

Full sweep 504 of 504 on both solvers.
