# Enhancement-183 — pyplot usability: distinct default names, deck-folder output, linewidth & backend

A round of `pyplot` (the matplotlib plotting command, [E-94](Enhancement-94.md)/95/98/99/[182](Enhancement-182.md)) usability improvements driven by real use. Four independent changes, all in the `pyplot` front-end (`com_pyplot.c`, `plotting/pyplot.c`); none affect any other command.

## 1. Distinct default names for successive no-name plots (a real bug)

In *window (interactive)* mode `pyplot` launches the Python viewer in the **background** (`python3 pyplot.py &`) so it doesn't block ngspice. Two plots that both omit the file name shared the same `pyplot.py` / `pyplot.data`: the second call overwrote those files *before* the first viewer had read them, so **both windows ended up showing the second plot** — its data and its title. (In PNG mode this was invisible, because that path runs Python synchronously.)

Fix: successive omitted-name plots now get **distinct** base names — the first stays `pyplot` (unchanged), later ones become `pyplot-2`, `pyplot-3`, … via a per-session counter — so each viewer reads its own files. This was diagnosed from a user's 3-inverter deck where two `pyplot … title 'no. 3'` / `title 'no. 4'` windows both showed "no. 4".

## 2. Artifacts written next to the circuit file

`pyplot` wrote `<name>.py` / `<name>.data` / `<name>.png` into ngspice's *current working directory* — so running `ngspice -b /path/to/deck.cir` from elsewhere scattered the plot files into the cwd rather than the deck's folder. Now, when the base name is bare (no directory of its own), pyplot prepends the directory of the circuit file (`ft_curckt->ci_filename` via `ngdirname`), and the generated script uses that full path in both `np.loadtxt(...)` and `savefig(...)` so Python finds the data from any cwd. A deck given as a bare relative name (its directory is `.`) still lands in the cwd, exactly as before — the change is opt-in by how you invoke ngspice, with no behavior change for the common in-folder case.

## 3. `set pyplot_linewidth=<w>`

Sets the matplotlib line width (in points) for every trace, threaded into the `plot(...)`/`step(...)` calls. Unset or ≤ 0 leaves matplotlib's default. Live setting, changeable between plots.

## 4. `set pyplot_backend=<name>`

Selects the matplotlib backend explicitly (e.g. `TkAgg`, `QtAgg`, `MacOSX`, `WebAgg`, `Agg`) by emitting `matplotlib.use('<name>')` ahead of `import matplotlib.pyplot`. When set it takes precedence over the automatic backend, including the `Agg` otherwise forced by the `png`/`svg`/`pdf` terminals — so a user pairing an interactive backend with a file terminal on a headless host does so deliberately. Unset: unchanged behavior (file terminals use `Agg`, interactive uses matplotlib's default, no `use()` call emitted).

## Verification

[`examples/pyplot_examples/verify_pyplot.py`](../examples/pyplot_examples/verify_pyplot.py) grows to **13 checks × both solvers**, adding: two no-name plots produce distinct `pyplot`/`pyplot-2` scripts with their own `suptitle`s; an absolute-path deck run from a different cwd lands its artifacts next to the `.cir` (and the `.py`'s `loadtxt` carries the deck-dir path); `set pyplot_linewidth=3.5` emits `linewidth=3.5`; `set pyplot_backend=Agg` emits `matplotlib.use('agg')`. Full example regression: 149/149. Packaged as a standalone feature bundle under [`features/`](../features/).
