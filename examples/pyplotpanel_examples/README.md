# pyplotpanel_examples — pyplot multi-panel + style (Enhancement-98)

Two additions to the `pyplot` command (E-94/95): `set pyplot_subplots=N` lays
the traces out as stacked subplots sharing the x-axis (N traces per panel;
0/unset = one axis), and `set pyplot_style=<name>` applies a matplotlib style
sheet (`dark` aliases `dark_background`). `vs` still means the x-axis vector
(ngspice semantics), so multi-panel is chosen with `pyplot_subplots`, not `vs`.

The verify renders a multi-RC transient with `pyplot_subplots=1` (three stacked
panels), `pyplot_subplots=2` (two panels for four traces), the default single
axis, and `pyplot_style=dark`; it checks the generated scripts for the right
`plt.subplots(n, 1, …)` / `plt.style.use('dark_background')` and that each
renders a valid PNG. Requires matplotlib. Run: `python3 verify_pyplotpanel.py`
(5 checks).
