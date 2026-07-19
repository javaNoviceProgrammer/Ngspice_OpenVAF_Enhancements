# Enhancement-228 — OSDI `.osdi` loader descriptor-count hardening (fuzzing)

Continuing the fuzzing campaign onto the **OSDI object-file loader**. A `.osdi`
model is an external, compiled shared library that ngspice `dlopen`s and then
reads **descriptor metadata** out of (`load_object_file` in
`osdi/osdiregistry.c`, reached by the `pre_osdi` command). It is external input —
often built by a different toolchain and shipped as a binary — so the loader
should survive a corrupt or mismatched file rather than crash on it.

## The crash class

`load_object_file` strided and indexed the descriptor arrays by the counts the
file itself declares, with no bounds:

- `OSDI_NUM_DESCRIPTORS` sizes the registry and drives the outer loop
  `for (i = 0; i < OSDI_NUM_DESCRIPTORS; i++)`, striding `desc_ptr` by
  `*OSDI_DESCRIPTOR_SIZE`;
- each descriptor's `num_params` drives the inner loop
  `for (param_id = 0; param_id < num_params; param_id++)`, which indexes
  `descr->param_opvar[param_id]` and dereferences each entry's `name[]`
  pointers; `num_opvars`, `num_terminals`, `num_noise_src`,
  `num_jacobian_entries`, … feed offset/size arithmetic.

A `.osdi` that still `dlopen`s but declares a count larger than its real array —
a **truncated file, a byte-corrupted one, or one built by a compiler whose OSDI
descriptor ABI differs** (exactly the drift the loader's own comments warn
about) — made the loop read past the array, dereferencing garbage as `name[]`
pointers → **SIGSEGV** during `pre_osdi`. This is the same "trust an unbounded
count from external data" class as [E-227](Enhancement-227.md), here on a
binary rather than a text surface.

## The fix

Two generous ceilings in `osdiregistry.c`, well above any real compact model
(the biggest ship a few dozen modules and ~1k parameters), so a count above them
means the file is not a well-formed OSDI object:

```c
#define OSDI_MAX_DESCRIPTORS 4096u
#define OSDI_MAX_DESC_COUNT (1u << 20)
```

- After reading `OSDI_NUM_DESCRIPTORS`, reject the file (clean diagnostic,
  `INVALID_OBJECT`) if it exceeds `OSDI_MAX_DESCRIPTORS`, before it is used to
  size the registry or stride the array.
- Inside the descriptor loop, reject the file if any of a descriptor's own count
  fields (`num_nodes`, `num_terminals`, `num_params`, `num_instance_params`,
  `num_opvars`, `num_noise_src`, `num_jacobian_entries`, `num_collapsible`,
  `num_states`) exceeds `OSDI_MAX_DESC_COUNT`, before those fields index or size
  anything. This choke point at load time protects every downstream consumer
  (setup, eval), since a rejected file never registers its devices.

Both convert the crash into a message like *“declares N OSDI descriptors, which
exceeds the … sanity limit; the .osdi file is corrupt or was built with an
incompatible toolchain.”*

## Scope (honest limits)

This targets the **egregious / out-of-range count** — the signature of a
truncated, byte-corrupted, or ABI-drifted object file, which is where real
corruption reliably lands (an ABI mismatch reads a pointer's bits as a count →
a huge value). It is **not** a claim that the loader is now proof against every
malformed `.osdi`: a count that lies within the plausible range (e.g. declaring
7 parameters when the array holds 1) is an internally inconsistent binary that
cannot be distinguished from a valid one without a ground truth the file does
not carry, and a `.osdi` is native code whose mere loading executes it — so a
determinedly hostile object is out of scope by construction. The guard removes
the common accidental-corruption crashes, not the theoretical adversarial ones.

On macOS, byte-corrupting a signed `.osdi` also breaks its code signature, so
`dlopen` rejects it before the loader runs; the remaining exposure is chiefly
Linux (no signing gate) and toolchain/ABI drift.

## Verification (`examples/osdifuzz_examples`)

`verify_osdifuzz.py` builds two malformed `.osdi` files from tiny C stubs
(portable — no binary mutation or re-signing): one declaring an implausible
`OSDI_NUM_DESCRIPTORS` (entry guard), and one with a valid descriptor count but
an implausible per-descriptor `num_params`, built from the real `OsdiDescriptor`
struct in `osdi.h` (loop guard). Each now load-rejects cleanly (both were a
SIGSEGV on the pre-fix binary, confirmed rc=139). A positive control confirms a
real openvaf-r-built `.osdi` still loads and simulates (`v(a) = 1`).

## Scope of change

ngspice only, one file (`osdi/osdiregistry.c`); no device, solver, or compiler
change. Full regression: 187/187.
