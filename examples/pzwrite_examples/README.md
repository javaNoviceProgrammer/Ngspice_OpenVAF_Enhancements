# pzwrite_examples — Enhancement-866

[E-866](../../enhancements_doc/Enhancement-866.md): F11 of the
[third robustness and correctness campaign of 2026-10-10](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

Two naming bugs on pz plots:
- **`write`:** it wrapped a pz plot's roots in `v(...)`, writing `v(zero(1))`, so the file did
  not load back under its own names.
- **`all`:** on a plot holding one vector, `all` renamed that vector: `print all` printed
  `all = …`, and `write` wrote the pole twice, the second time as `v(all)`.

A name of the form `f(...)` is now written as it is, and a lone vector found by `all` keeps its
name.

The checks:
- **[1]** `write` of a plot with a pole and a zero: `pole(1)` and `zero(1)`.
- **[2]** `write` of a plot with one pole: one variable, `pole(1)`.
- **[3]** `print all` on that plot prints `pole(1) = …`.
- **[4]** The written file loads back under its own names.
- **[5]** (control) An op plot still writes `v(...)` and `i(...)` names.
- **[6]** (control) `print all` on a plot with several vectors names each.

Run: `python3 verify_pzwrite.py` (6 checks per solver). On the E-863 binaries [1] to [4] fail.
