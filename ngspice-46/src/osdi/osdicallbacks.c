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
  char *text;    /* fully formatted, prefix included */
  bool to_err;   /* stream selection at flush time */
  bool monitor;  /* LOG_LVL_MONITOR: change-detected at flush */
} OsdiPendingMsg;

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
      fputs(m->text, m->to_err ? stderr : stdout);
      continue;
    }
    fputs(m->text, m->to_err ? stderr : stdout);
    tfree(m->text);
  }
  pending_len = 0;
}

static void osdi_log_defer(const char *prefix, const char *name,
                           const char *msg, bool fmt_err, bool to_err,
                           bool monitor) {
  if (pending_len >= pending_cap) {
    pending_cap = pending_cap ? 2 * pending_cap : 16;
    pending = TREALLOC(OsdiPendingMsg, pending, pending_cap);
  }
  size_t n = strlen(prefix) + strlen(name) + strlen(msg) + 32;
  char *text = TMALLOC(char, n);
  if (fmt_err) {
    snprintf(text, n, "%s%s: failed to format\"%s\"\n", prefix, name, msg);
  } else {
    snprintf(text, n, "%s%s: %s", prefix, name, msg);
  }
  pending[pending_len].text = text;
  pending[pending_len].to_err = to_err;
  pending[pending_len].monitor = monitor;
  pending_len++;
}

void osdi_log(void *handle_, char *msg, uint32_t lvl) {
  OsdiNgspiceHandle *handle = handle_;
  FILE *dst = stdout;
  uint32_t level = lvl & LOG_LVL_MASK;

  /* LRM 9.4.6 deferral: display-class output waits for the accepted
   * iteration, unless the compiler tagged it immediate (event-gated). */
  if (display_managed &&
      (level == LOG_LVL_DISPLAY || level == LOG_LVL_MONITOR) &&
      !(lvl & LOG_FLAG_IMMEDIATE)) {
    osdi_log_defer("OSDI ", handle->name, msg, (lvl & LOG_FMT_ERR) != 0,
                   false, level == LOG_LVL_MONITOR);
    return;
  }

  switch (level) {
  case LOG_LVL_DEBUG:
    printf("OSDI(debug) %s: ", handle->name);
    break;
  case LOG_LVL_DISPLAY:
  case LOG_LVL_MONITOR:
    printf("OSDI %s: ", handle->name);
    break;
  case LOG_LVL_INFO:
    printf("OSDI(info) %s: ", handle->name);
    break;
  case LOG_LVL_WARN:
    fprintf(stderr, "OSDI(warn) %s: ", handle->name);
    dst = stderr;
    break;
  case LOG_LVL_ERR:
    fprintf(stderr, "OSDI(err) %s: ", handle->name);
    dst = stderr;
    break;
  case LOG_LVL_FATAL:
    fprintf(stderr, "OSDI(fatal) %s: ", handle->name);
    dst = stderr;
    break;
  default:
    fprintf(stderr, "OSDI(unknown) %s", handle->name);
    break;
  }

  if (lvl & LOG_FMT_ERR) {
    fprintf(dst, "failed to format\"%s\"\n", msg);
  } else {
    fprintf(dst, "%s", msg);
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
