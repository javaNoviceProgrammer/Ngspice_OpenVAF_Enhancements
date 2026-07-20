# Enhancement-244 — crash-hardening round 2: `nport` device + `pyplot` markers

An argument-fuzzing pass over the newer devices and commands turned up two
reproducible, user-triggerable crashes — both in recently-added code, both
reproduce on the shipped binary. Each is fixed and covered by a repro test.

## 1. `nport` device — unbound node → SIGABRT / out-of-bounds

The native n-port device (E-242) reads its port count `N` from the `.nport` model
file, then in `NPORTsetup` reads the instance's terminals from the fixed-size
`GENnode` array (`ports 0..N-1`, reference at `[N]`) and stamps an `N`-port
admittance block. It never checked that the instance line actually **connected**
all `N+1` nodes.

```
V1 a 0 dc 1
N1 a 0 mod          ; 2 nodes, but the model is a 2-port (needs p1 p2 ref)
.model mod nport(file="two.nport")
.op
```

The generic `N` dispatcher leaves unconnected terminals as `-1`, so `setup` passed
a **negative row/column** to the sparse-matrix builder:

```
Assertion failed: (IS_SPARSE(Matrix) && Row >= 0 && Col >= 0), spGetElement, spbuild.c:267
```

(SIGABRT with assertions on; a silent out-of-bounds access without.) The same
root cause fires when the `.nport` declares `nports` beyond the device maximum
(`NPORT_MAXTERMS`), which would index past the `GENnode` array.

**Fix** (`nportsetup.c`): reject a `.nport` whose port count leaves no room for the
reference (`N + 1 > NPORT_MAXTERMS`), and in `setup` verify every `node[0..N] >= 0`
before stamping — a clean `E_BADPARM` with a diagnostic naming the shortfall
instead of a crash.

## 2. `pyplot -hist` / `-contour` first arg — use-after-free → SIGSEGV

`pyplot`'s histogram (E-217) and contour (E-218) render modes are selected by a
`-hist` / `-contour` marker anywhere in the argument list. The marker was stripped
by **unlinking and freeing a node of the command's own argument wordlist** — but
that list is owned and freed by the command loop. When the marker was the **first**
word, `com_pyplot` freed the list **head**; the command loop then freed it again:

```
pyplot -hist v(out)        ; -> use-after-free / double-free -> SIGSEGV
pyplot -contour v(out) x y ; -> same
```

`pyplot v(out) -hist` (marker not first) was unaffected — which is why the
E-217/E-218 examples, which never put the marker first, always passed.

**Fix** (`com_pyplot.c`): detect the marker by scanning the list (no mutation) and,
when found, build a **filtered copy** without it; use the copy for the plot and free
it ourselves at the end. The caller's wordlist is never touched. As a side effect,
`-hist`/`-contour` as the first argument now render correctly — previously the
corruption also made `-hist v(out)` emit a *line* plot instead of a histogram.

## Verification

`examples/crashfix2_examples/verify_crashfix2.py` (9 checks, both solvers): the
under-bound and over-max `nport` decks exit gracefully with the diagnostic (no
signal); a correctly-bound 2-port still simulates; `pyplot -hist`/`-contour` as the
first argument, and `-hist` with no signals, no longer crash; `-hist` first now
generates a real `plt.hist(...)`; and the trailing-marker form still works.

## Scope

ngspice only. `nportsetup.c` (device input validation) and `com_pyplot.c`
(command-argument ownership). No solver, analysis, or numerical change; valid
usage is unaffected. Full regression: 201/201.
