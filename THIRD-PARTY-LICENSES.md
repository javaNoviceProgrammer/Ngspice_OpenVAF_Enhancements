# Third-party components and their licenses

This repository is a **combined work**. Most of the code in it is not original to
this project: it bundles the ngspice circuit simulator and the OpenVAF Verilog-A
compiler, both modified here, together with the enhancements, documentation,
examples and test harnesses written for this project.

**The combined work is distributed under GPL-3.0** — see [LICENSE](LICENSE).
That is not a choice so much as a consequence: OpenVAF is GPL-3.0, this project
modifies and redistributes it, and GPL-3.0 is the strongest copyleft among the
components. Every other component's license is compatible with it.

**Each component keeps its own license.** GPL-3.0 governs the combination; it
does not relicense anything listed below. The BSD, MIT and MPL-2.0 components in
particular carry attribution and notice requirements that survive redistribution,
which is what this file exists to satisfy.

---

## 1. ngspice — `ngspice-46/`

Default license: **Modified BSD** (3-clause).
Copyright 1985–2018, Regents of the University of California and others;
`COPYING` is © 2025 by the ngspice team.

The authoritative statement is [`ngspice-46/COPYING`](ngspice-46/COPYING). It
records these exceptions to the Modified BSD default:

| Path | License |
|---|---|
| `src/osdi` | **MPL-2.0** |
| `src/maths/KLU` | LGPL (see the note below) |
| `src/maths/sparse` | unnamed MIT license, compatible with New BSD |
| `src/frontend/numparam` | LGPLv2 or newer |
| `src/tclspice.c` | LGPLv2 |
| `src/xspice/icm/table` | **GPLv2 or newer** |
| `src/xspice` (everything else) | public domain (Georgia Tech Research Corporation) |
| `src/spicelib/devices/ndev` | public domain |
| `m4/` | unnamed, compatible with DFSG |
| the ngspice manual | CC-BY-SA v4.0 |

**A note on KLU.** `COPYING` summarises it as "LGPLv2". Read literally that would
be a problem, because LGPL-2.0 without an "or later" clause is not GPL-3.0
compatible. The sources themselves are more specific — they say *"version 2.1 of
the License, or (at your option) any later version"* — i.e. **LGPL-2.1-or-later**,
which is GPL-3.0 compatible. The summary is imprecise; the headers govern.

The GPLv2-or-newer XSPICE table code model is likewise compatible through its
"or newer" clause.

## 2. OpenVAF (OpenVAF-Reloaded) — `OpenVAF-master-20260610/`

License: **GPL-3.0**, declared per crate; the full text is in
[`OpenVAF-master-20260610/LICENSE`](OpenVAF-master-20260610/LICENSE).
34 of the 36 crates that declare a license use `license = "GPL-3.0"`.

Two internal utility crates are more permissive:

| Crate | License |
|---|---|
| `lib/base_n` | MIT OR Apache-2.0 |
| `lib/mini_harness` | MIT OR Apache-2.0 |

Vendored third-party license texts are kept in
[`OpenVAF-master-20260610/copyright/`](OpenVAF-master-20260610/copyright/):
`LICENSE_APACHE`, `LICENSE_MIT`, and `LICENSE_BSD3_INSTANT`
(© 2019 Sébastien Crozet, for the `instant` crate).

## 3. The OSDI interface — MPL-2.0 on the ngspice side

Worth calling out separately because it is easy to get wrong: the OSDI ABI that
the compiler and the simulator meet across is, **on the ngspice side**, neither
GPL nor BSD. `ngspice-46/src/osdi/` is **MPL-2.0**, © 2022 SemiMod GmbH, and its
headers carry that notice explicitly; ngspice's `COPYING` lists it as an
exception to the Modified BSD default.

MPL-2.0 is file-level copyleft: modifications to MPL-2.0 files remain MPL-2.0,
and it is explicitly GPL-compatible. This project has modified files in that
directory, so those files keep their MPL-2.0 terms.

The **OpenVAF side of the same interface is not MPL-2.0.** The `openvaf/osdi`
crate declares `license = "GPL-3.0"` like the rest of the compiler, and its
headers under `openvaf/osdi/header/` carry no separate licence notice. The two
sides of one ABI are therefore under different terms — MPL-2.0 in ngspice,
GPL-3.0 in OpenVAF — which is legitimate (an interface definition is not itself
a shared work) but is the sort of thing to state rather than assume.

## 4. Prebuilt binaries — `bin/`

This repository ships **prebuilt binaries** for six platform targets — Linux
(ARM, Intel), macOS (Apple silicon, Intel) and Windows (ARM, Intel) — comprising
`ngspice`, `openvaf-r` and the XSPICE `*.cm` code models.

These are compiled from the sources in this same repository, and are therefore
themselves covered by GPL-3.0. The corresponding source required by GPL-3.0
§6 is the content of this repository at the commit the binaries were built
from; no separate written offer is needed, because source and binary are
distributed together.

## 5. This project's own contributions

**Modifications to the bundled sources — no separate copyright asserted.**
The changes this project makes to ngspice and to OpenVAF are contributed under
the terms of the works they modify: ngspice changes under ngspice's own licences
(Modified BSD, or the relevant exception for files such as `src/osdi/`), OpenVAF
changes under GPL-3.0. No copyright separate from the upstream projects' is
claimed over them, and they are not to be read as a new work laid on top of the
originals.

*(Copyright arises automatically in most jurisdictions and cannot simply be
switched off; what is stated here is that none is **asserted** over these
modifications, and that they carry no terms beyond those of the code they
change.)*

**Files original to this project** — the documentation under `docs/` and
`enhancements_doc/`, the examples and verification harnesses under `examples/`,
the change reports, and the build and CI tooling written for this repository —
are © 2026 javaNoviceProgrammer and are released under GPL-3.0 along with the
rest of the combined work.

---

*This file is a summary for orientation, compiled from the license texts present
in this repository. Where it and an upstream license text disagree, the upstream
text governs. It is not legal advice.*
