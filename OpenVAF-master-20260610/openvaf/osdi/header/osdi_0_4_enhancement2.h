#pragma once

#ifndef NO_STD
#include <stdint.h>
#endif

/* Companion to osdi_0_4.h and osdi_0_4_enhancement1.h — assumes
 * OSDI_NUM_DESCRIPTORS / OsdiDescriptor from osdi_0_4.h are in scope. */

/*
 * OSDI 0.4 — Enhancement 2:  last_crossing() support
 * ====================================================
 *
 * This header documents an ADDITIVE, backward-compatible extension to the
 * OSDI 0.4 ABI (see osdi_0_4.h), sitting alongside Enhancement 1
 * (osdi_0_4_enhancement1.h, absdelay()). It is emitted by OpenVAF-reloaded
 * (version7) and consumed by ngspice-46 (version7) to implement the
 * Verilog-A `last_crossing()` operator.
 *
 * Nothing in osdi_0_4.h or osdi_0_4_enhancement1.h changes:
 *   - The `OsdiDescriptor` struct layout is UNCHANGED.
 *   - This extension adds ONE new struct type (OsdiLastCrossingInfo) and TWO
 *     new optional global symbols (OSDI_LAST_CROSSING_COUNTS,
 *     OSDI_LAST_CROSSING_INFOS).
 *
 * A simulator that does not know about this extension simply ignores the two
 * symbols; a model that uses no `last_crossing()` does not export them at
 * all. Therefore old simulators run new models (minus last_crossing) and new
 * simulators run old models unchanged.
 *
 *
 * 1. Model of `last_crossing()`
 * ------------------------------
 * `last_crossing(expr [, dir])` is lowered to TWO synthetic implicit-node
 * equations per call ("crossing slot"), following the exact same pattern as
 * absdelay()'s (y_synth, z) pair:
 *
 *     eq_y (input node  y_synth): V(y_synth) = expr
 *                                 -> the MODEL stamps this row (a normal
 *                                    resistive residual emitted by OpenVAF),
 *                                    so the simulator can read the converged
 *                                    value of `expr` at each accepted
 *                                    timepoint via the OSDI node mapping.
 *
 *     eq_z (output node z):       V(z) = time of the most recent point where
 *                                 V(y_synth)'s ACCEPTED history crossed zero
 *                                 in the requested direction (dir<0: falling,
 *                                 dir>0: rising, dir==0: either).
 *                                 -> the SIMULATOR stamps this row using the
 *                                    same waveform-history mechanism
 *                                    absdelay uses.
 *
 * Unlike absdelay's output, `V(z)` has ZERO Jacobian sensitivity to
 * `V(y_synth)` almost everywhere: the crossing time is a locally-constant
 * function of simulation time between crossings (it only jumps
 * discontinuously exactly at a new crossing, a measure-zero event for Newton
 * iteration purposes). So, unlike absdelay, the simulator never needs a
 * `J[z, y]` coupling term — only `J[z, z] = -1` and the crossing-time RHS.
 * This is a meaningful simplification relative to absdelay's stamping.
 *
 * The value of the `last_crossing()` expression in the model body is V(z).
 *
 *
 * 2. Per-slot descriptor
 * -----------------------
 * One OsdiLastCrossingInfo describes one crossing slot. It is 12 bytes:
 * three uint32_t fields, no padding — byte-identical layout to
 * OsdiAbsDelayInfo, just different field semantics.
 */
typedef struct OsdiLastCrossingInfo {
  uint32_t y_node;      /* OSDI node index of the synthetic input node
                         * y_synth (the watched expression). Index into the
                         * descriptor's node table / per-instance
                         * node_mapping (same space as OsdiJacobianEntry.nodes
                         * and OsdiNode).                                    */
  uint32_t z_node;      /* OSDI node index of the crossing-time output node z. */
  uint32_t dir_offset;  /* Byte offset, within the per-instance OSDI data
                         * block, of the `double dir` value for this slot
                         * (dir<0: falling only, dir>0: rising only, dir==0:
                         * either direction). Recomputed every evaluation and
                         * written into instance data by the compiled model,
                         * exactly like absdelay's td_offset.                */
} OsdiLastCrossingInfo;


/*
 * 3. Global symbols (exported from the .osdi object, optional)
 * -----------------------------------------------------------
 * Present ONLY when at least one module in the object uses last_crossing().
 * Same shape/indexing convention as OSDI_ABSDELAY_COUNTS/INFOS:
 *
 *   const uint32_t OSDI_LAST_CROSSING_COUNTS[OSDI_NUM_DESCRIPTORS];
 *   const OsdiLastCrossingInfo OSDI_LAST_CROSSING_INFOS[ sum(counts) ];
 *
 *
 * 4. What the simulator must do for each slot k of an instance
 * --------------------------------------------------------------
 *   setup   : create ONE matrix entry, J[z_node, z_node] (no y-coupling
 *             entry is needed — see rationale above), and allocate a
 *             per-slot waveform history of V(y_synth) (same mechanism as
 *             absdelay's delay_hist).
 *   DC / OP : J[z,z] += -1 ; RHS[z] += 0        (z = 0 before any history
 *             exists — matches "no crossing observed yet")
 *   TRAN    : at each accepted timepoint, scan the history for the most
 *             recent bracketing pair of samples whose sign change matches
 *             the requested direction; linearly interpolate the zero-
 *             crossing time within that bracket; cache it. Stamp
 *             J[z,z] += -1 ; RHS[z] += cached_crossing_time. Commit the
 *             converged V(y_synth) into history at each accepted timepoint,
 *             exactly like absdelay.
 *   AC      : pass through the last computed (real-valued) crossing time as
 *             a constant contribution; J[z,z] += -1, no frequency-dependent
 *             term (last_crossing has no well-defined small-signal AC
 *             sensitivity).
 *
 * The reference consumer implementation lives in ngspice-46/src/osdi:
 *   osdiregistry.c (read symbols), osdisetup.c (allocate + KLU bind),
 *   osdiload.c (DC/TRAN stamp), osdiaccept.c (history commit). The matching
 *   emitter is OpenVAF openvaf/osdi/src/lib.rs (export) + inst_data.rs (dir
 *   storage).
 */
