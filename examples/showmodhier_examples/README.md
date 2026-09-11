# showmodhier_examples — Enhancement-606

`showmod x1.rm` and `showmod x1:rm` found nothing while `altermod` accepts both
spellings of a subcircuit's flattened model name (`x1:rm`, nested `x1.x2:rm`).
The device generator's grammar could express neither; a whole-word match — the
query, with or without the `#` model marker, equal to the model's name with
`.` standing for `:` — is consulted alongside it, as E-410 did for instances.

Run: `python3 verify_showmodhier.py` (8 checks per solver, both solvers).
