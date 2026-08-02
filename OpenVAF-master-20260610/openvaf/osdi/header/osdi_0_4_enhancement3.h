#pragma once

/* Companion to osdi_0_4.h, osdi_0_4_enhancement1.h and osdi_0_4_enhancement2.h —
 * assumes OSDI_NUM_DESCRIPTORS / OsdiDescriptor from osdi_0_4.h are in scope. */

/*
 * OSDI 0.4 — Enhancement 3:  terminal shorts
 * ==========================================
 *
 * This header documents an ADDITIVE, backward-compatible extension to the
 * OSDI 0.4 ABI (see osdi_0_4.h), sitting alongside Enhancement 1
 * (absdelay()) and Enhancement 2 (last_crossing()). It is emitted by
 * OpenVAF-reloaded and consumed by ngspice-46 to implement Enhancement-401.
 *
 * Nothing in the earlier headers changes:
 *   - The `OsdiDescriptor` struct layout is UNCHANGED.
 *   - The ABI version (OSDI_VERSION_MINOR_CURR) does NOT move.
 *   - This extension adds ONE new struct type (OsdiTermShortInfo) and TWO new
 *     optional global symbols (OSDI_TERM_SHORT_COUNTS, OSDI_TERM_SHORT_INFOS).
 *
 * A simulator that does not know about this extension simply ignores the two
 * symbols; a model that shorts none of its own terminals does not export them
 * at all. Old simulators therefore run new models (minus the fix) and new
 * simulators run old models unchanged.
 *
 *
 * 1. The problem
 * --------------
 *
 * `V(a,b) <+ 0;` in Verilog-A means "a and b are the same node". OpenVAF
 * lowers it to a CollapseHint callback rather than to a residual contribution,
 * i.e. it asks the simulator to fuse the two solver unknowns.
 *
 * A simulator cannot honour that when a and b are both TERMINALS: their solver
 * unknowns are circuit nodes the simulator allocated and other devices attach
 * to, not unknowns the device owns. ngspice says exactly this in
 * `collapse_nodes()` (src/osdi/osdisetup.c) and skips such a pair.
 *
 * Before this extension nothing replaced the skipped collapse — the DAE build
 * emits no equation for a trivial potential contribution — so the two
 * terminals were left unconnected: an OPEN CIRCUIT where the model wrote a
 * short, silently. The LRM's own page-155 `parares` degenerated to an open
 * instead of a wire.
 *
 *
 * 2. The contract
 * ---------------
 *
 * For every branch whose collapse hint cannot be honoured, the compiler now
 * emits a real 0 V source (an extra flow unknown and its equation
 * `V(node_1) - V(node_2) = 0`) AND lists the branch here.
 *
 * That equation is correct precisely when node_1 and node_2 are two DISTINCT
 * CONNECTED circuit nodes. Otherwise it is redundant, and a redundant 0 V
 * source is a SINGULAR row: its current appears nowhere else in the system.
 * That case is common and legitimate — a self-heating model ties its thermal
 * terminal to ground, and the netlist grounds that terminal too.
 *
 * Only the simulator knows the netlist, so it makes the call:
 *
 *   for each OsdiTermShortInfo ts:
 *       if node_1/node_2 do NOT resolve to two distinct connected circuit
 *       nodes, drop the unknown `ts.flow_node` (collapse it away) exactly as
 *       an ordinary collapse-to-ground would.
 *
 * "Do not resolve to two distinct connected circuit nodes" means any of:
 *   - node_1 >= connected_terminals (not a connected terminal; the ordinary
 *     collapse already applies to it),
 *   - node_2 == UINT32_MAX (short to ground) and terminal node_1 IS ground,
 *   - node_2 >= connected_terminals,
 *   - terminals node_1 and node_2 are the same circuit node.
 *
 * The compiler lists a branch here ONLY when the model never reads that
 * branch's current, which is what makes dropping the unknown safe.
 *
 *
 * 3. The symbols
 * --------------
 *
 *   const uint32_t OSDI_TERM_SHORT_COUNTS[OSDI_NUM_DESCRIPTORS];
 *
 *       How many terminal shorts each descriptor has, in descriptor order.
 *
 *   const OsdiTermShortInfo OSDI_TERM_SHORT_INFOS[/ sum of the counts /];
 *
 *       Flat array, grouped by descriptor in the same order: descriptor i owns
 *       the next OSDI_TERM_SHORT_COUNTS[i] entries after those of descriptors
 *       0..i-1. (Same layout convention as OSDI_ABSDELAY_INFOS.)
 *
 * Both symbols are absent when no module in the object needs them.
 */

#include <stdint.h>

typedef struct OsdiTermShortInfo {
  /* OSDI node index of the first shorted terminal */
  uint32_t node_1;
  /* OSDI node index of the second shorted terminal, or UINT32_MAX when the
   * short is to ground */
  uint32_t node_2;
  /* OSDI node index of the branch-current unknown to drop when node_1/node_2
   * do not resolve to two distinct connected circuit nodes */
  uint32_t flow_node;
} OsdiTermShortInfo;
