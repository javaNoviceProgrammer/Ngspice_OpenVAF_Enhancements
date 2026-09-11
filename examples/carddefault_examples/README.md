# carddefault_examples — Enhancement-599

A `.model` card's instance-parameter defaults (`.model am cd width=3`) were
honoured but invisible to `showmod` and immovable by `altermod`, whose refusal
recommended the card it could not change. The parser now remembers which
instances took the card's default and which set their own, so `altermod` moves
the default onto the followers, leaves the rest, records it on the card, and
`showmod` lists the card's instance defaults. Also: a `pre_osdi -f` hoisted from
behind other commands in its block gets a Note naming `osdi -f`, and `pre_osdi`
works at the prompt.

Run: `python3 verify_carddefault.py` (15 checks per solver, both solvers).
