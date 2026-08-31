# lrmdisc — natures, disciplines & branches vs. the LRM (Enhancement-519)

An LRM-2023 conformance audit of clauses **3.6–3.13** and Annex D found
three bugs. This suite pins the fixes end-to-end:

- **Discipline compatibility implements all of 3.11.1**: a branch between a
  conservative net and a signal-flow net of the same potential nature is
  legal (the LRM's own example: `electrical` and `sig_flow_v` *are*
  compatible), natureless disciplines match their whole domain — and the
  mixed branch takes the discipline that has the natures, so `I(br)` across
  `electrical`/`voltage` works, verified as a live 1 kΩ element.
  `electrical` vs `rotational` stays rejected.
- **Nature-attribute validation is alive again** (3.6.1.2): the checks
  existed but iterated the wrong accessor and never ran. `access = "SA"`,
  `access = 3.0`, and non-name `ddt_nature`/`idt_nature` values are located
  errors; a derived nature declaring `units` warns that the value is ignored;
  an unrelated `idt_nature` override warns.
- **VAMS-2023 `constants.vams`** (Annex D.2): `PHYSICAL_CONSTANTS_NIST2018`
  selects the exact 2019-SI values (`P_Q` = 1.602176634e-19, …); the default
  stays NIST1998, exactly as the 2023 LRM specifies.
- **OSDI nature descriptors exact**: every nature's `num_attr` claimed one
  attribute more than it owns; pinned by dlopen-dumping `OSDI_NATURES` with
  the committed `dump_nda.c` harness (ranges contiguous and in-bounds).

Run `python3 verify_lrmdisc.py` — 21 checks, both solvers.
