#pragma once

#ifndef NO_STD
#include <stdint.h>
#endif

/* Companion to osdi_0_4.h and osdi_0_4_enhancement{1,2,3}.h -- assumes
 * OSDI_NUM_DESCRIPTORS / OsdiDescriptor from osdi_0_4.h are in scope. */

/*
 * OSDI 0.4 -- Enhancement 4:  transition() and slew() stamped by the simulator
 * ==========================================================================
 *
 * This header documents an ADDITIVE, backward-compatible extension to the
 * OSDI 0.4 ABI (see osdi_0_4.h), sitting alongside Enhancement 1 (absdelay())
 * and Enhancement 2 (last_crossing()). It is emitted by OpenVAF-reloaded and
 * consumed by ngspice-46 to implement the Verilog-A `transition()` and
 * `slew()` operators (project Enhancement-698, hunt F1/F2 of 2026-09-21).
 *
 * Nothing in the earlier headers changes:
 *   - The `OsdiDescriptor` struct layout is UNCHANGED.
 *   - This extension adds TWO struct types (OsdiTransitionInfo, OsdiSlewInfo)
 *     and FOUR optional global symbols (OSDI_TRANSITION_COUNTS/INFOS,
 *     OSDI_SLEW_COUNTS/INFOS).
 *
 * Pairing: a simulator that does not know this extension leaves the output
 * rows described below EMPTY, so a model compiled with it needs a simulator
 * that has it (the matrix is singular otherwise). A model compiled before it
 * carries the operators as a tracking loop inside its own residuals and runs
 * on a new simulator unchanged.
 *
 *
 * 1. Why the simulator
 * --------------------
 * Both operators used to be one loop in the compiled model,
 * dy/dt = clamp(K (x - y), -neg, +pos). A loop has no memory of the swing it
 * is asked to make, so `transition` ran at the fixed RATE 1/rise_time -- a
 * 5 V step took 5 * rise_time where LRM 4.5.8 says every transition takes
 * rise_time -- and its stiff tail rang under the trapezoidal rule whenever
 * the input stepped between timepoints. LRM 4.5.8 defines transition on
 * EVENTS of the input on the simulator's timeline ("A transition is created
 * when the input expression changes, and at this point it uses the value of
 * td, rise_time, fall_time and time_tol to determine the new pending
 * transition"; corners are timepoints; an interrupted ramp is readjusted;
 * transitions queue behind the delay), and 4.5.9's slew is an ideal rate
 * limiter, which needs the ACCEPTED output. Only the simulator has either.
 *
 *
 * 2. Model of the operators
 * -------------------------
 * Each call is lowered to TWO synthetic implicit-node equations, the same
 * pattern as absdelay's (y_synth, z) pair:
 *
 *     eq_y (input node y_synth): V(y_synth) = expr
 *                                -> the MODEL stamps this row (a normal
 *                                   resistive residual emitted by OpenVAF),
 *                                   so the simulator reads the converged
 *                                   input at each accepted timepoint.
 *
 *     eq_z (output node z):      -> the SIMULATOR stamps this row:
 *          transition            V(z) = ramp(t), the piecewise-linear
 *                                function scheduled from the changes of the
 *                                accepted V(y_synth) -- a function of time
 *                                alone, so J[z,z] = -1 and rhs[z] = -ramp(t);
 *          slew                  V(z) = clamp(V(y_synth), y_last - neg h,
 *                                y_last + pos h) with y_last the output it
 *                                accepted at the previous point and h the
 *                                time since -- J[z,y] = 1 while tracking, 0
 *                                while limiting, J[z,z] = -1.
 *
 * The operator's arguments are recomputed by the compiled model at every
 * evaluation and written into instance data (like absdelay's td), so the
 * simulator reads td, rise_time and fall_time "at this point" when the input
 * changes, and the rate bounds at every stamp. The value of the operator in
 * the model body is V(z).
 *
 *
 * 3. Per-slot descriptors
 * -----------------------
 */
typedef struct OsdiTransitionInfo {   /* 24 bytes, six uint32_t, no padding */
  uint32_t y_node;        /* OSDI node index of the synthetic input node      */
  uint32_t z_node;        /* OSDI node index of the output node               */
  uint32_t td_offset;     /* byte offsets, within the per-instance OSDI data  */
  uint32_t trise_offset;  /* block, of the `double` delay, rise time and fall */
  uint32_t tfall_offset;  /* time (each already projected onto its domain)    */
  uint32_t flags;         /* reserved, 0                                      */
} OsdiTransitionInfo;

typedef struct OsdiSlewInfo {         /* 16 bytes, four uint32_t, no padding */
  uint32_t y_node;
  uint32_t z_node;
  uint32_t pos_offset;    /* byte offsets of the `double` positive and        */
  uint32_t neg_offset;    /* negative rate bounds, both MAGNITUDES; +inf for  */
                          /* "no limit on that side"                          */
} OsdiSlewInfo;

/*
 * 4. Global symbols (exported from the .osdi object, optional)
 * -----------------------------------------------------------
 * Each pair is present ONLY when at least one module in the object uses the
 * operator. Same shape and indexing convention as OSDI_ABSDELAY_COUNTS/INFOS:
 *
 *   const uint32_t OSDI_TRANSITION_COUNTS[OSDI_NUM_DESCRIPTORS];
 *   const OsdiTransitionInfo OSDI_TRANSITION_INFOS[ sum(counts) ];
 *   const uint32_t OSDI_SLEW_COUNTS[OSDI_NUM_DESCRIPTORS];
 *   const OsdiSlewInfo OSDI_SLEW_INFOS[ sum(counts) ];
 *
 *
 * 5. What the simulator must do for each slot k of an instance
 * ------------------------------------------------------------
 *   setup   : create the matrix entries J[z_node, y_node] and J[z_node,
 *             z_node] (the same two as an absdelay slot) and allocate the
 *             slot's state; mark both nodes as coupled, since no descriptor
 *             Jacobian entry names the output node.
 *   DC / OP : J[z,y] += 1 ; J[z,z] += -1  (the identity: LRM 4.5.8/4.5.9,
 *             both operators pass expr in DC). The first transient
 *             evaluation stamps the identity too and seeds the state from
 *             the converged operating point.
 *   TRAN    : transition -- at each ACCEPTED point: advance the active ramp;
 *             start a pending transition whose due time has come; if the
 *             accepted input differs from the last accepted one, create a
 *             transition with the stored td / rise / fall: td = 0 starts it
 *             now (the queue is dropped; an active ramp is readjusted by
 *             4.5.8's slope rule -- from the interrupted ramp's origin when
 *             the new destination continues its direction, from its
 *             destination when it reverses, over the new time, applied from
 *             the point of interruption), td > 0 queues it for t + td and
 *             cancels queued transitions due at or after that. Corners are
 *             breakpoints (the leading one, when it is the current point,
 *             makes the integrator restart at order one there); a zero time
 *             is a negligible non-zero ramp with no trailing breakpoint; an
 *             input that changes at consecutive points places no
 *             breakpoints at all. Stamp J[z,z] += -1, rhs[z] += -ramp(t).
 *             slew -- remember the accepted output and its time; stamp the
 *             linearised clamp above; keep the next step from growing past
 *             the corner where the ramp meets the input.
 *   AC      : unity -- J[z,y] += e^{-j w td} for transition (the delay's
 *             phase, as the absdelay stage it replaced), += 1 for slew;
 *             J[z,z] += -1.  PZ: the zero-delay wire.
 *
 * The reference consumer implementation lives in ngspice-46/src/osdi:
 *   osdiregistry.c (read symbols), osdisetup.c (allocate + KLU bind),
 *   osdiload.c (transition_stamp, slew_stamp), osdiaccept.c
 *   (transition_accept, slew_accept), osditrunc.c, osdiacld.c, osdipzld.c.
 * The matching emitter is OpenVAF openvaf/osdi/src/lib.rs (export) +
 * inst_data.rs (argument storage) + hir_lower/src/expr.rs (lowering).
 */
