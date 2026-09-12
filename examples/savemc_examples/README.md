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

Since Enhancement-612 the file name keeps its case and its bytes, and a quoted
name its spaces: `savemc=MixedCase/Draws.csv`, `savemc="dir with space/My
Draws.csv"`, `savemc=Résumé_MC.csv` write exactly those (checks 11–13). Since
Enhancement-613 the directories of a name are made (`savemc=NewDir/Sub/Rows.csv`
creates both levels), a name that cannot be opened is reported with the reason
and the rows go to the dated default beside the deck, and a later open that
fails is said once with the rows kept for the next try (checks 14–16).

Run: `python3 verify_savemc.py` (30 checks per solver, both solvers).
