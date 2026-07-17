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

} OsdiRegistryEntry;

typedef struct OsdiObjectFile {
  OsdiRegistryEntry *entrys;
  int num_entries;
} OsdiObjectFile;

extern OsdiObjectFile load_object_file(const char *path);
extern SPICEdev *osdi_create_spicedev(const OsdiRegistryEntry *entry);

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
