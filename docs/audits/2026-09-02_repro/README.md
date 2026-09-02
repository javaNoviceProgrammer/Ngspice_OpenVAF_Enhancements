# Reproduction decks — 2026-09-02 LRM audit (round 2)

Each finding in [`../2026-09-02_LRM-audit-round2.html`](../2026-09-02_LRM-audit-round2.html)
is reproduced here. Build the model with the committed `openvaf-r`, then run the deck with
the committed `ngspice`:

    openvaf-r <model>.va -o <model>.osdi
    ngspice -b <deck>.cir

| Finding | Files | What to look for |
|---|---|---|
| `%m` prints the module, not the instance | `fmt.va`, `m2.cir` | four distinct instances all print `m=fmt` |
| multichannel descriptors are not bit masks | `fio.va`, `fio.cir`, `fio2.va` | `$fdisplay(mA|mB,…)` lands in `fc.txt`; the first mcd is 1 |
| RNG seed never advances | `seed.va`/`seed.cir`, `loop.va`/`loop.cir` | `s` stays 1234; five loop draws give one value |
| `$fscanf` consumes the whole line | `rd2.va`, `rd2.cir`, `data.txt` | `$fgets` after `$fscanf` returns line 2, not `" alpha"` |
| `$fclose`+`$fopen` does not rewind | `rd4.va`, `rd4.cir`, `data.txt` | the second open reads line 2 |
| nature `abstol` discarded | `nat.va` | compiles; no tolerance reaches the OSDI descriptor (code read) |
