# autocorner_examples — Enhancement-656

`.option autocorner`: every run-class command (`op`, `tran`, `ac`, `dc`,
the batch-mode `run`, the shared library's) runs at the nominal `tt` and
then at every process corner the loaded Verilog-A models declare
(`(* corner=... *)`, E-654). The per-corner plots are kept, named with
their corner, so batch `.print` cards print each corner; and a combined
`autocorner<n>` plot is made current with the nominal's vectors under their
names and each corner's as `<name>_<corner>` (`v(out_ss)`), resampled onto
the nominal's scale — the form a schematic host reads. The option is inert
inside loop commands and without a declared corner; the `corner` variable
is put back afterwards.

Run: `python3 verify_autocorner.py` (15 checks per solver, both solvers).
