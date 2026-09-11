# probeblock_examples — Enhancement-605

A `.probe` card in a deck that opens with a `.control` block (every OSDI deck
does, for `pre_osdi`) printed ".save: no such command available in ngspice":
`inp_probe` inserted its `.save all` card right after the deck's first card,
inside the block, where it ran as a command. The card, and the `.save` line the
probes generate, now go after the block's `.endc`.

Run: `python3 verify_probeblock.py` (5 checks per solver, both solvers).
