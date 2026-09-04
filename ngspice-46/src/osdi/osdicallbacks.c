#include "ngspice/devdefs.h"
#include "ngspice/memory.h"
#include "osdidefs.h"

#include <string.h>

/* ------------------------------------------------------------------------
 * LRM 9.4.6: "All the display tasks, except $debug, shall not display output
 * unless an iteration has been accepted."
 *
 * Every display task of every loaded OSDI model funnels through osdi_log, so
 * the deferral lives here: DISPLAY/MONITOR-class messages are buffered,
 * OSDIload drops the buffer when a new Newton iteration starts (its output
 * supersedes the previous, unaccepted iteration's), and OSDIaccept /
 * OSDIfinalStep / the sweep analyses flush the buffer of the iteration that
 * was actually accepted. Messages tagged LOG_FLAG_IMMEDIATE by the compiler
 * (statements inside event-controlled blocks, which fire on the event's own
 * iteration) and every other level ($debug per the LRM's exemption; info/
 * warn/err/fatal are diagnostics) print right away, exactly as before.
 *
 * $monitor (LOG_LVL_MONITOR, LRM 9.4.1) prints "if a variable or expression
 * in the argument list changes value compared with the last accepted step":
 * at flush time the k-th monitor message of the point is compared against the
 * k-th monitor message of the previously flushed point and skipped when the
 * text is unchanged. (A $abstime/$realtime argument defeats this text
 * comparison -- documented deviation.)
 * ------------------------------------------------------------------------ */

typedef struct {
  char *text;    /* "OSDI<kind> <inst>: <message>", context NOT yet appended */
  int head_len;  /* bytes of the "OSDI <inst>: " head at the front of `text` */
  uint32_t sev;  /* nonzero for a severity task: its `lvl`, for the 9.7.3
                    context, which is computed at OUTPUT time (see below) */
  bool to_err;   /* stream selection at flush time */
  bool monitor;  /* LOG_LVL_MONITOR: change-detected at flush */
} OsdiPendingMsg;

/* ROUND-3 AUDIT (2026-09-02) / LRM 9.4.1: "The $write task provides the same
 * capabilities as $strobe, but with no newline." Suppressing the newline has
 * exactly one purpose -- assembling one output line from several calls -- and
 * the per-message "OSDI <inst>: " head defeated it:
 *
 *     $write("[A]"); $write("[B]"); $write("[C]\n");
 *       was:  OSDI n1: [A]OSDI n1: [B]OSDI n1: [C]
 *       now:  OSDI n1: [A][B][C]
 *
 * So the head is written only at the START of a line. Every other display task
 * ends its text with a newline, so each of those still carries its own head
 * and nothing else changes. Tracked per stream, since stdout and stderr keep
 * independent write positions. */
static bool at_line_start[2] = {true, true}; /* [0] stdout, [1] stderr */

static void osdi_severity_when(char *buf, size_t n, uint32_t lvl);

/* `sev` is a severity task's `lvl`, or 0 for every other task. The LRM 9.7.3
 * context is resolved HERE rather than when the message was formatted, because
 * a deferred message is emitted at the accepted point and that is when the
 * simulator's own bookkeeping holds the right answer: during a .dc sweep
 * `CKTtime` only takes the point's swept value after the solve that produced
 * the message, so a context baked in at format time reported the PREVIOUS
 * point's value. */
static void osdi_emit(const char *text, int head_len, bool to_err,
                      uint32_t sev) {
  int stream = to_err ? 1 : 0;
  FILE *dst = to_err ? stderr : stdout;
  const char *out;
  size_t n;
  if (text == NULL) {
    return;
  }
  out = at_line_start[stream] ? text : text + head_len;
  n = strlen(out);
  if (sev != 0) {
    char when[64];
    osdi_severity_when(when, sizeof(when), sev);
    if (when[0] != '\0') {
      /* before the message's own newline, so the head and the message text
         stay contiguous for every reader that matches on them */
      if (n > 0 && out[n - 1] == '\n') {
        fprintf(dst, "%.*s%s\n", (int)(n - 1), out, when);
      } else {
        fprintf(dst, "%s%s", out, when);
      }
      if (n > 0) {
        at_line_start[stream] = (out[n - 1] == '\n');
      }
      return;
    }
  }
  fputs(out, dst);
  if (n > 0) {
    at_line_start[stream] = (out[n - 1] == '\n');
  }
}

/* The circuit whose evaluation is producing log output, published by the load
 * and setup paths below. Only the LRM 9.7.3 severity context reads it. */
static const CKTcircuit *osdi_log_ckt;

void osdi_display_note_circuit(const CKTcircuit *ckt) { osdi_log_ckt = ckt; }

/* ROUND-3 AUDIT / LRM 9.7.3: "these tasks shall also report the simulation run
 * time at which the severity system task is called. If any of these tasks is
 * called from an analog context during a dc sweep, the simulator shall report
 * the current value of the swept variable in place of the simulation run time.
 * If the task is called from an analog initial block, the simulator shall
 * report that the call was made during initialization."
 *
 * None of it was reported: a $warning carried the instance name and nothing
 * else, in every analysis. Written as a trailing parenthetical rather than
 * inside the head so that the head stays the stable "OSDI(warn) <inst>: "
 * every reader (and every suite) already matches on.
 *
 * `CKTtime` carries the swept value during a .dc, which is why the two cases
 * differ only in wording -- the same field E-55's $finish note reports as
 * "sweep value". */
static void osdi_severity_when(char *buf, size_t n, uint32_t lvl) {
  const CKTcircuit *ckt = osdi_log_ckt;
  buf[0] = '\0';
  if (lvl & LOG_FLAG_INIT) {
    snprintf(buf, n, " (during initialization)");
    return;
  }
  if (ckt == NULL) {
    return;
  }
  if (ckt->CKTmode & MODEDCTRANCURVE) {
    snprintf(buf, n, " (at sweep value %g)", ckt->CKTtime);
  } else if (ckt->CKTmode & MODETRAN) {
    snprintf(buf, n, " (at t = %g)", ckt->CKTtime);
  } else {
    snprintf(buf, n, " (at the operating point)");
  }
}

static OsdiPendingMsg *pending;
static int pending_len, pending_cap;
/* Deferral engages with the first Newton iteration (OSDIload). Display calls
 * made before that -- instance setup evaluating init-resident statements --
 * print through immediately, as they always did. */
static bool display_managed;

/* previous flushed text of the k-th $monitor message, for change detection */
static char **monitor_prev;
static int monitor_prev_cap;

void osdi_display_iter_begin(void) {
  display_managed = true;
  for (int i = 0; i < pending_len; i++) {
    tfree(pending[i].text);
  }
  pending_len = 0;
}

/* Enhancement-535 (hunt N5): a (re-)setup is about to run init-resident code
 * -- the temperature/parameter-dependent statements the compiler hoists,
 * which may $strobe/$display. That code is NOT part of any Newton iteration,
 * so its output must print immediately (as it did on the very first setup of
 * the session, before display_managed first latched true). Without this the
 * flag stayed true across the whole session: every setup after the first
 * DEFERRED the hoisted display into `pending`, and the next iter_begin then
 * dropped it as a superseded iteration -- a model's temperature $strobe
 * printed once per session and never again, though the code demonstrably
 * re-ran (an opvar it assigned updated correctly). Clearing the flag (and any
 * stale pending from a prior analysis) makes every setup behave like the
 * first; the first load iteration re-arms deferral via iter_begin. */
void osdi_display_reenter_setup(void) {
  display_managed = false;
  /* Round-3 audit: a model whose last `$write` never terminated its line would
   * otherwise keep every later message's head suppressed for the rest of the
   * session. Within one evaluation that is exactly what $write asks for; a new
   * setup is a new line. */
  at_line_start[0] = true;
  at_line_start[1] = true;
  for (int i = 0; i < pending_len; i++) {
    tfree(pending[i].text);
  }
  pending_len = 0;
}

/* A fresh analysis is starting (OSDIsetup). Do everything reenter_setup does,
 * AND (hunt N5, bug 4) drop the $monitor change-detection history: it compares
 * the k-th monitor line of this point against the k-th of the PREVIOUS flushed
 * point, and across a run boundary the "previous" belongs to a different
 * analysis -- so the first accepted point of a new run was silently suppressed
 * when its text happened to match the last flushed line of the prior run, and
 * the k-indexing misaligned after a deck change. Reset per ANALYSIS (here),
 * never per temperature point -- a `.dc temp` sweep runs OSDItemp (hence
 * reenter_setup) per point and must keep its cross-point history intact. */
void osdi_display_setup_phase(void) {
  osdi_display_reenter_setup();
  for (int i = 0; i < monitor_prev_cap; i++) {
    if (monitor_prev[i]) {
      tfree(monitor_prev[i]);
      monitor_prev[i] = NULL;
    }
  }
}

void osdi_display_flush(void) {
  int mon_seq = 0;
  for (int i = 0; i < pending_len; i++) {
    OsdiPendingMsg *m = &pending[i];
    if (m->monitor) {
      int k = mon_seq++;
      if (k < monitor_prev_cap && monitor_prev[k] != NULL &&
          strcmp(monitor_prev[k], m->text) == 0) {
        tfree(m->text);
        continue; /* unchanged since the last accepted step: no output */
      }
      if (k >= monitor_prev_cap) {
        int cap = monitor_prev_cap ? 2 * monitor_prev_cap : 8;
        while (cap <= k) {
          cap *= 2;
        }
        monitor_prev = TREALLOC(char *, monitor_prev, cap);
        for (int j = monitor_prev_cap; j < cap; j++) {
          monitor_prev[j] = NULL;
        }
        monitor_prev_cap = cap;
      }
      if (monitor_prev[k]) {
        tfree(monitor_prev[k]);
      }
      monitor_prev[k] = m->text; /* keep for the next comparison */
      osdi_emit(m->text, m->head_len, m->to_err, m->sev);
      continue;
    }
    osdi_emit(m->text, m->head_len, m->to_err, m->sev);
    tfree(m->text);
  }
  pending_len = 0;
}

/* Build "<prefix><name>: <msg>", reporting how many bytes of head that put in
 * front of the message so a `$write` continuation can skip them, and appending
 * the LRM 9.7.3 context (`when`, empty for every non-severity task) before the
 * message's own trailing newline. Caller owns the returned buffer. */
static char *osdi_log_format(const char *prefix, const char *name,
                             const char *msg, bool fmt_err, int *head_len) {
  size_t n = strlen(prefix) + strlen(name) + strlen(msg) + 32;
  char *text = TMALLOC(char, n);
  int head = snprintf(text, n, "%s%s: ", prefix, name);
  if (head < 0) {
    head = 0;
  }
  if (fmt_err) {
    snprintf(text + head, n - (size_t)head, "failed to format\"%s\"\n", msg);
  } else {
    snprintf(text + head, n - (size_t)head, "%s", msg);
  }
  *head_len = head;
  return text;
}

static void osdi_log_defer(char *text, int head_len, uint32_t sev, bool to_err,
                           bool monitor) {
  if (pending_len >= pending_cap) {
    pending_cap = pending_cap ? 2 * pending_cap : 16;
    pending = TREALLOC(OsdiPendingMsg, pending, pending_cap);
  }
  pending[pending_len].text = text;
  pending[pending_len].head_len = head_len;
  pending[pending_len].sev = sev;
  pending[pending_len].to_err = to_err;
  pending[pending_len].monitor = monitor;
  pending_len++;
}

/* LRM 3.6.1: a nature's `abstol` is "the absolute tolerance ... used to
 * determine convergence" for a signal of that nature. The compiler writes it
 * into the .osdi nature tables, but nothing here ever read them, so a model
 * declaring `abstol = 1p` was still judged by the circuit-wide `abstol` --
 * a tolerance three orders too loose converges early on a wrong answer, and a
 * tolerance too tight refuses to converge at all. Neither said anything.
 *
 * Resolves node `node_idx`'s POTENTIAL nature (that is the unknown the
 * convergence test compares) to its declared abstol, or 0.0 when the model
 * names none -- in which case the caller keeps the circuit-wide value. */
/* Does this attribute range declare `abstol`? Round-4 audit: split out of the
 * walk below so the same search can be run over a DISCIPLINE's override
 * attributes as over a nature's own. Reports the declared value even when it
 * is not positive, so a nonsense declaration stops the walk exactly as it did
 * before rather than silently inheriting a parent's. */
static bool osdi_attr_abstol(const OsdiAttribute *attrs, uint32_t num_attributes,
                             uint32_t start, uint32_t count, double *out) {
  uint32_t k;
  for (k = 0; k < count; k++) {
    uint32_t a = start + k;
    if (a >= num_attributes) {
      break;
    }
    if (attrs[a].name && strcmp(attrs[a].name, "abstol") == 0 &&
        attrs[a].value_type == ATTR_TYPE_REAL) {
      *out = attrs[a].value.real;
      return true;
    }
  }
  return false;
}

/* LRM 3.6.2.5: a discipline may override an attribute of the nature it binds
 * (`discipline ttl; flow ttl_curr; flow.abstol = 10u; enddiscipline`), and
 * 3.6.2.6 makes a nature derived from `ttl.flow` inherit the attributes "as
 * modified in" that discipline. So wherever a nature is reached THROUGH a
 * discipline -- a node's own binding, or a derived nature's parent link -- the
 * discipline's override of that side is what the LRM says applies, and it is
 * consulted before the nature underneath.
 *
 * Round-4 audit: this whole path was missing. The walk resolved a discipline
 * straight to its nature index and broke out of the loop the moment a parent
 * was not a plain nature, so an override never reached the convergence test
 * and a nature derived from a discipline's flow reported nothing at all.
 *
 * Writes the underlying nature index to `*nature` so the caller can carry on
 * there, and returns true when the discipline itself declares `abstol`. */
static bool osdi_discipline_abstol(const OsdiRegistryEntry *entry,
                                   uint32_t disc_idx, bool potential,
                                   uint32_t *nature, double *out) {
  const OsdiDiscipline *disc = (const OsdiDiscipline *)entry->disciplines;
  const OsdiAttribute *attrs = (const OsdiAttribute *)entry->attributes;
  uint32_t start, count;

  *nature = UINT32_MAX;
  if (!disc || !attrs || disc_idx >= entry->num_disciplines) {
    return false;
  }
  disc += disc_idx;
  *nature = potential ? disc->potential : disc->flow;
  /* the table lays a discipline's attributes out as [flow][potential][user],
   * all counted from `attr_start` */
  if (potential) {
    start = disc->attr_start + disc->num_flow_attr;
    count = disc->num_potential_attr;
  } else {
    start = disc->attr_start;
    count = disc->num_flow_attr;
  }
  return osdi_attr_abstol(attrs, entry->num_attributes, start, count, out);
}

double osdi_node_abstol(const OsdiRegistryEntry *entry, uint32_t node_idx) {
  const OsdiDescriptor *descr;
  const OsdiNature *natures;
  const OsdiAttribute *attrs;
  const OsdiNatureRef *ref;
  uint32_t nat_idx;

  if (!entry || !entry->natures || !entry->attributes) {
    return 0.0;
  }
  descr = (const OsdiDescriptor *)entry->descriptor;
  if (!descr || !descr->unknown_nature || node_idx >= descr->num_nodes) {
    return 0.0;
  }
  natures = (const OsdiNature *)entry->natures;
  attrs = (const OsdiAttribute *)entry->attributes;
  ref = &descr->unknown_nature[node_idx];

  /* A node's unknown is reached either directly as a nature or through its
   * discipline's potential/flow nature -- and in the second case the
   * discipline's own override of that attribute comes first (3.6.2.5). */
  if (ref->ref_type == NATREF_NATURE) {
    nat_idx = ref->index;
  } else if (ref->ref_type == NATREF_DISCIPLINE_POTENTIAL ||
             ref->ref_type == NATREF_DISCIPLINE_FLOW) {
    double overridden;
    if (osdi_discipline_abstol(entry, ref->index,
                               ref->ref_type == NATREF_DISCIPLINE_POTENTIAL,
                               &nat_idx, &overridden)) {
      return (overridden > 0.0) ? overridden : 0.0;
    }
  } else {
    return 0.0;
  }
  if (nat_idx >= entry->num_natures) {
    return 0.0;
  }

  {
    const OsdiNature *nat = &natures[nat_idx];
    /* A derived nature inherits its parent's abstol unless it overrides it
     * (LRM 3.6.1.1), so walk up the parent chain. The bound on the walk is
     * the table size: a corrupt table must not spin here. */
    uint32_t hops = 0;
    while (hops++ <= entry->num_natures) {
      double v;
      if (osdi_attr_abstol(attrs, entry->num_attributes, nat->attr_start,
                           nat->num_attr, &v)) {
        return (v > 0.0) ? v : 0.0;
      }
      if (nat->parent_type == NATREF_NATURE) {
        if (nat->parent >= entry->num_natures) {
          break;
        }
        nat = &natures[nat->parent];
      } else if (nat->parent_type == NATREF_DISCIPLINE_POTENTIAL ||
                 nat->parent_type == NATREF_DISCIPLINE_FLOW) {
        /* 3.6.2.6: `nature n : ttl.flow;` inherits ttl's override of the
         * flow's attributes, and only then the bound nature's own. */
        uint32_t next;
        if (osdi_discipline_abstol(entry, nat->parent,
                                   nat->parent_type == NATREF_DISCIPLINE_POTENTIAL,
                                   &next, &v)) {
          return (v > 0.0) ? v : 0.0;
        }
        if (next >= entry->num_natures) {
          break;
        }
        nat = &natures[next];
      } else {
        break;
      }
    }
  }
  return 0.0;
}

/* `%m`: the instance name behind an OSDI handle (LRM 9.4.4). This is the same
 * string osdi_log prefixes its output with, which is exactly the name the
 * clause asks %m to print -- it was simply never offered to the model. */
char *osdi_instance_name(void *handle_) {
  OsdiNgspiceHandle *handle = handle_;
  return handle ? handle->name : NULL;
}

void osdi_log(void *handle_, char *msg, uint32_t lvl) {
  OsdiNgspiceHandle *handle = handle_;
  uint32_t level = lvl & LOG_LVL_MASK;
  const char *prefix;
  bool to_err = false;
  bool severity = false;
  /* Does this level wait for an accepted iteration?
   *
   * ROUND-3 AUDIT (2026-09-02): the three non-fatal SEVERITY levels belong
   * here and were missing, so `$error`/`$warning`/`$info` ran on every Newton
   * iteration. LRM 9.7.3 states the rule for this family in its own words --
   * "Non-fatal system severity tasks ($error, $warning, $info) called during a
   * rejected iteration shall have no effect" -- which is why reading 9.4.6
   * alone (it names only "the display tasks") missed them. Measured on one
   * diode .op: $strobe printed 1 line at the converged point and $warning
   * printed 21, walking the whole unconverged Newton sequence.
   *
   * The other two levels stay immediate, each for its own clause:
   *   LOG_LVL_DEBUG -- 9.4.6's sole exemption, "except $debug".
   *   LOG_LVL_FATAL -- 9.7.3: "$fatal terminates the simulation without
   *                    checking whether the iteration would be rejected." */
  bool defers = false;

  switch (level) {
  case LOG_LVL_DEBUG:
    prefix = "OSDI(debug) ";
    break;
  case LOG_LVL_DISPLAY:
  case LOG_LVL_MONITOR:
    prefix = "OSDI ";
    defers = true;
    break;
  case LOG_LVL_INFO:
    prefix = "OSDI(info) ";
    defers = true;
    severity = true;
    break;
  case LOG_LVL_WARN:
    prefix = "OSDI(warn) ";
    to_err = true;
    defers = true;
    severity = true;
    break;
  case LOG_LVL_ERR:
    prefix = "OSDI(err) ";
    to_err = true;
    defers = true;
    severity = true;
    break;
  case LOG_LVL_FATAL:
    prefix = "OSDI(fatal) ";
    to_err = true;
    severity = true;
    break;
  default:
    prefix = "OSDI(unknown) ";
    to_err = true;
    break;
  }

  {
    int head_len = 0;
    /* The severity levels are all nonzero (INFO=2 .. FATAL=5), so the raw
       `lvl` doubles as the "this is a severity task" marker and carries
       LOG_FLAG_INIT along to the context. */
    uint32_t sev = severity ? lvl : 0u;
    char *text = osdi_log_format(prefix, handle->name, msg,
                                 (lvl & LOG_FMT_ERR) != 0, &head_len);

    /* LRM 9.4.6/9.5.9/9.7.3 deferral: output waits for the accepted iteration
     * unless the compiler tagged it immediate (event-gated, or an `analog
     * initial` block, which fires on the initial-step iteration). */
    if (display_managed && defers && !(lvl & LOG_FLAG_IMMEDIATE)) {
      osdi_log_defer(text, head_len, sev, to_err, level == LOG_LVL_MONITOR);
      return;
    }
    osdi_emit(text, head_len, to_err, sev);
    tfree(text);
  }
}

/* ------------------------------------------------------------------------
 * File-write deferral hooks (LRM 9.5.9): each loaded .osdi buffers its own
 * un-gated file writes; osdiregistry.c resolves the optional lifecycle
 * symbols at load time and registers them here (once per object file).
 * ------------------------------------------------------------------------ */

typedef void (*OsdiIoHook)(void);
#define OSDI_MAX_IO_HOOKS 128
static OsdiIoHook io_begin_hooks[OSDI_MAX_IO_HOOKS];
static OsdiIoHook io_flush_hooks[OSDI_MAX_IO_HOOKS];
static int num_io_hooks;

void osdi_register_io_hooks(void *lib_handle,
                            void *(*get_sym)(void *, const char *)) {
  OsdiIoHook begin = (OsdiIoHook)get_sym(lib_handle, "osdi_io_iter_begin");
  OsdiIoHook flush = (OsdiIoHook)get_sym(lib_handle, "osdi_io_flush");
  if (begin == NULL && flush == NULL) {
    return; /* an older .osdi without the deferred-I/O runtime */
  }
  if (num_io_hooks >= OSDI_MAX_IO_HOOKS) {
    return;
  }
  io_begin_hooks[num_io_hooks] = begin;
  io_flush_hooks[num_io_hooks] = flush;
  num_io_hooks++;
}

void osdi_io_hooks_iter_begin(void) {
  for (int i = 0; i < num_io_hooks; i++) {
    if (io_begin_hooks[i]) {
      io_begin_hooks[i]();
    }
  }
}

void osdi_io_hooks_flush(void) {
  for (int i = 0; i < num_io_hooks; i++) {
    if (io_flush_hooks[i]) {
      io_flush_hooks[i]();
    }
  }
}

double osdi_pnjlim(bool init, bool *check, double vnew, double vold, double vt,
                   double vcrit) {
  if (init) {
    *check = true;
    return vcrit;
  }
  int icheck = 0;
  double res = DEVpnjlim(vnew, vold, vt, vcrit, &icheck);
  *check = icheck != 0;
  return res;
}

double osdi_limvds(bool init, bool *check, double vnew, double vold) {
  if (init) {
    *check = true;
    return 0.1;
  }
  double res = DEVlimvds(vnew, vold);
  if (res != vnew) {
    *check = true;
  }
  return res;
}

/* LRM 9.17.3 fallback: "If the string refers to an unknown or unsupported
 * function, the simulator is responsible for determining the appropriate
 * limiting algorithm, just as if no string had been supplied." Bound (with a
 * load-time warning) when $limit names a function this table does not
 * provide; it applies no limiting -- the access-function value passes
 * through. Any extra arguments the model passes are simply never read, which
 * the C calling convention permits, so one adapter serves every arity. */
double osdi_limit_unknown(bool init, bool *check, double vnew, double vold) {
  (void)vold;
  if (init) {
    *check = true;
    return vnew;
  }
  *check = false;
  return vnew;
}

double osdi_fetlim(bool init, bool *check, double vnew, double vold,
                   double vto) {
  if (init) {
    *check = true;
    return vto + 0.1;
  }
  double res = DEVfetlim(vnew, vold, vto);
  if (res != vnew) {
    *check = true;
  }
  return res;
}

double osdi_limitlog(bool init, bool *check, double vnew, double vold,
                     double LIM_TOL) {
  if (init) {
    *check = true;
    return 0.0;
  }
  int icheck = 0;
  double res = DEVlimitlog(vnew, vold, LIM_TOL, &icheck);
  *check = icheck != 0;
  return res;
}
