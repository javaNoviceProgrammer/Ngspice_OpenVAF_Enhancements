# savemc_examples — Enhancement-610

`.option savemc[=csv|excel|txt|<name>.<ext>]` records the value in force of
every parameter with statistics, one row per analysis run, in
`mcparams_<date>_<time>.<ext>` beside the netlist (csv by default): a device
slot whose value draws (`r1 in out {agauss(1k,50,1)}`, or a random `.param`
inlined there — each use its own draw, as ngspice has it), named `<instance>`
or `<instance>:<key>`; a subcircuit call's own drawn value, `x1.p`; and, under
`.option osdimc`, every OSDI parameter declared with `(* std= *)`, read off the
devices as `@<model>[<param>]` / `@<instance>[<param>]`. `.option automc_save`
(alias `osdimc_save`) records the OSDI parameters only. A `reset` continues the
file (every `montecarlo` sample is a row), a different deck starts another; a
failed run is a row marked `failed`; `excel` writes a genuine `.xlsx`.

Run: `python3 verify_savemc.py` (17 checks per solver, both solvers).
