/*
 * This file is part of the OSDI component of NGSPICE.
 * Copyright© 2022 SemiMod GmbH.
 * 
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/. 
 *
 * Author: Pascal Kuthe <pascal.kuthe@semimod.de>
 */

#pragma once

#include "ngspice/config.h"
#include "ngspice/devdefs.h"
#include <stdint.h>

typedef struct OsdiRegistryEntry {
  const void *descriptor;
  uint32_t inst_offset;
  uint32_t noise_offset;
  uint32_t dt;
  uint32_t temp;

  bool has_m;

#ifdef KLU
  uint32_t matrix_ptr_offset;
#endif

  /* absdelay support: filled at .osdi load time from OSDI_ABSDELAY_* symbols */
  uint32_t num_absdelays;
  const void *absdelay_infos;  /* points into the loaded .osdi's OSDI_ABSDELAY_INFOS */

  /* last_crossing support: filled at .osdi load time from
   * OSDI_LAST_CROSSING_* symbols */
  uint32_t num_last_crossings;
  const void *last_crossing_infos;  /* points into the loaded .osdi's OSDI_LAST_CROSSING_INFOS */

  /* Enhancement-401: terminal-short support, filled at .osdi load time from
   * OSDI_TERM_SHORT_* symbols. A model that shorts two of its own TERMINALS with
   * `V(a,b) <+ 0` cannot be served by node collapsing (terminals are allocated by
   * ngspice, see collapse_nodes), so the compiler emits a real 0 V source instead
   * and lists the branch here. If the netlist turns out to tie those terminals to
   * ONE circuit node the equation is redundant and the system singular, so setup
   * drops the branch current in that case. */
  uint32_t num_term_shorts;
  const void *term_short_infos;  /* points into the loaded .osdi's OSDI_TERM_SHORT_INFOS */

} OsdiRegistryEntry;

/* Enhancement-401: one entry of OSDI_TERM_SHORT_INFOS. `node_1`/`node_2` are the
 * OSDI node indices of the two shorted terminals (`node_2` is UINT32_MAX when the
 * short is to ground); `flow_node` is the branch-current unknown to drop when the
 * two do not resolve to two distinct connected circuit nodes. */
typedef struct OsdiTermShortInfo {
  uint32_t node_1;
  uint32_t node_2;
  uint32_t flow_node;
} OsdiTermShortInfo;

typedef struct OsdiObjectFile {
  OsdiRegistryEntry *entrys;
  int num_entries;
} OsdiObjectFile;

extern OsdiObjectFile load_object_file(const char *path);
extern SPICEdev *osdi_create_spicedev(const OsdiRegistryEntry *entry);
extern int osdi_devtype_is_osdi(int type);   /* Enhancement-323 */

/* Enhancement-215: register a command-line plusarg (`+name[=value]`, passed
 * without the leading '+') so a compiled Verilog-A model's $test$plusargs /
 * $value$plusargs can read it through the simparam channel. */
extern void ngspice_register_plusarg(const char *arg);

extern char *inputdir;

/* Enhancement-55: deferred $finish/$stop requests. OSDIload latches the
 * eval-return flags per timepoint attempt; the analyses check at the
 * ACCEPTED-point boundary (acting mid-Newton-iteration breaks timestep
 * control) and end the analysis cleanly ($finish, after firing
 * @(final_step)) or pause resumably ($stop). */
#define OSDI_REQ_FINISH 1
#define OSDI_REQ_STOP 2
extern int OSDIpendingRequests(CKTcircuit *ckt);

/* Enhancement-53: fire Verilog-A `@(final_step)` blocks. Called by the
 * analyses (tran/op/dc/ac) once they complete successfully; issues one
 * dedicated eval() per OSDI instance with EVAL_FLAG_IS_FINAL_STEP set at the
 * converged final solution. Results are not loaded into the matrix/RHS.
 * Defined in src/osdi/osdiload.c. */
extern int OSDIfinalStep(CKTcircuit *ckt);

/* Enhancement-413: terminal names of an OSDI instance (0 if it is not one), so
 * `.options savecurrents` can be expanded per terminal once the descriptor is
 * known. Defined in src/osdi/osdiparam.c. */
extern int OSDIterminalNames(CKTcircuit *ckt, const char *name, char ***names,
                             int *count);

/* Enhancement-417: 1 if the last setup_instance re-decided this instance's node
 * collapse away from the one the matrix was built for, else 0 (including for
 * every non-OSDI instance). Reading it clears it. Defined in
 * src/osdi/osdiparam.c. */
extern int OSDIcollapseChanged(GENinstance *instPtr);
extern int OSDIanyCollapseChanged(CKTcircuit *ckt);   /* Enhancement-471 */
