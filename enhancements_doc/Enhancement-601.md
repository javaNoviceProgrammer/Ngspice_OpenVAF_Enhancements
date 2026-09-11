# Enhancement-601: an operating-point quantity is named as one, and an integer or string out of range shows its value

**Scope:** `src/frontend/spiceif.c` (`say_instance_level`, the instance-side write branch
of `if_setparam`), `src/osdi/osdisetup.c` (the range refusal's value for an integer and
a string), `examples/opvarmsg_examples/` (new, 10 checks per solver). **ngspice only.**
Findings D3 and D4 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)).

**Suites:** [`opvarmsg_examples`](../examples/opvarmsg_examples/) 10 of 10 per solver,
both solvers; `hunt2diag` [3] re-pinned to the integer's value; `instdep`, `showwidth`,
`paramrange` unchanged; full sweep 495 of 495.

## D3 — an operating-point variable called an instance parameter

Reading an operating-point variable through the model name — `@km[lvo]`, `lvo` being a
`(* desc *)` variable the model computes — answered with E-560's message for an instance
**parameter**: "'lvo' is an INSTANCE parameter of model 'km' (declared (* type="instance"
*), or resolved per instance because its default reads an instance parameter, lint
L028)". The reader is sent looking for a declaration that does not exist. `say_instance_level`
found the name in the instance table and did not ask what kind of entry it was. A write
was no better: `alter @km[lvo]=1` and `altermod km lvo=1` said "has no parameter lvo",
and `alter @n1[lvo]=1` "no such parameter lvo", for a name that plainly exists.

**What changed.** A read-only entry of the instance table — an opvar, a terminal current
(`i_p`), a built-in's `i` — is named as what it is:

- read through the model: "'lvo' is an operating-point quantity of the instances of
  model 'km' -- a value each instance computes (an operating-point variable, or a
  terminal current), not a parameter -- so the model has none. Read it from an instance:
  @<instance>[lvo]";
- written through the model or the instance: "... read-only -- so nothing can set it".

An instance parameter through the model keeps E-560's text; an unknown name keeps "no
such parameter".

## D4 — the value missing from an integer or string range refusal

The OSDI range refusal (bug-hunt F6, E-558) printed the value for a scalar real —
"Parameter x of 'rm' is out of bounds (value 5; range from (0:10] exclude {5})!" — and
omitted it for everything else, so an integer given as `k=0.4`, rounded to 0 with a
warning, was refused as "out of bounds; range from [1:3]" with the rounded value, the
whole question, unsaid. An integer and a string scalar now show their value the same
way: "(value 0; range from [1:3])", "(value "oxide"; range from {...})".

The second half of D4 — `w=2 w=3 width=4` on one line getting the generic "parameter
value out of range or the wrong type" instead of the alias error — no longer reproduces:
Enhancement-597's rework of the parameter loop reaches the LRM 3.4.7 refusal, and the
suite pins it.

## Verification

| check | result |
|---|---|
| `print @km[kk]`, `print @km[i_p]` | the operating-point-quantity message, no "type="instance"" text |
| `print @km[area]` | E-560's instance-parameter message, unchanged |
| `alter @km[kk]=1`, `altermod km kk=1` | read-only, "on the model or on an instance" |
| `alter @n1[kk]=1`, `alter n1 kk=2` | read-only, on the instance |
| `alter @r1[i]=1`; `alter @n1[nosuch]=1` | the read-only message for the built-in's `i`; "no such parameter nosuch" |
| `.model km om k=0.4` against `[1:3]` | "(value 0; range from [1:3])" after the rounding warning |
| `kind="oxide"` against `{"poly", "metal"}` | "(value "oxide"; range from {...})" |
| `x=5` against `(0:10] exclude 5` | unchanged |
| `n1 a 0 km w=2 w=3 width=4` | the duplicate warning, then the alias error |

Full sweep 495 of 495 on both solvers.
