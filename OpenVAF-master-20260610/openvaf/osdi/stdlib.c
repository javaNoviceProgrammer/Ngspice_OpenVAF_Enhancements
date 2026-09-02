#ifdef NO_STD
// This was used before. Seems wrong. AB
// typedef int int32_t;
// Maybe this is better... AB
typedef unsigned int uint32_t;
typedef int int32_t;
// End of change AB
typedef unsigned char bool;
typedef __SIZE_TYPE__ size_t;
extern size_t strlen (const char *__s);
extern void *memcpy (void *__restrict __dest, const void *__restrict __src,
		     size_t __n);
extern void *malloc (size_t __size);
extern void *realloc (void *__ptr, size_t __size);
extern void free (void *__ptr);
extern double log(double);
extern double exp(double);
extern double sqrt(double);
extern double cos(double);
extern int strcmp(const char*, const char*);
// Enhancement-11 file I/O: FILE* is treated opaquely as void*; these resolve
// against the host libc at OSDI load, exactly like `log` above.
extern void *fopen(const char *, const char *);
extern int fclose(void *);
extern int fputs(const char *, void *);
extern int fflush(void *);
extern int fseek(void *, long, int);
extern long ftell(void *);
extern void rewind(void *);
extern int feof(void *);
extern int ferror(void *);
extern int fgetc(void *);
extern int ungetc(int, void *);
extern char *fgets(char *, int, void *);
extern long strtol(const char *, char **, int);
extern double strtod(const char *, char **);
extern char *strchr(const char *, int);
extern void *freopen(const char *, const char *, void *);
extern double fabs(double);
extern double floor(double);
extern double log10(double);
#define NULL ((void*)0)
#define SEEK_SET 0
/* The C standard streams are macros over platform-specific symbols; name the
 * real symbol per target (the bitcode is compiled once per target triple, so
 * the right branch is baked in). Needed for the LRM 9.5.1 pre-opened
 * descriptors. */
#if defined(__APPLE__)
extern void *__stdinp, *__stdoutp, *__stderrp;
#define OSDI_STDIN __stdinp
#define OSDI_STDOUT __stdoutp
#define OSDI_STDERR __stderrp
#elif defined(_WIN32)
extern void *__acrt_iob_func(unsigned);
#define OSDI_STDIN (__acrt_iob_func(0))
#define OSDI_STDOUT (__acrt_iob_func(1))
#define OSDI_STDERR (__acrt_iob_func(2))
#else
extern void *stdin, *stdout, *stderr;
#define OSDI_STDIN stdin
#define OSDI_STDOUT stdout
#define OSDI_STDERR stderr
#endif
#else
#include <math.h>
#include <stdio.h>
#include "stdlib.h"
#include "string.h"
#define OSDI_STDIN stdin
#define OSDI_STDOUT stdout
#define OSDI_STDERR stderr
#endif

#ifndef OSDI_0_4
#include "header/osdi_0_4.h"
#endif

// no header was included explicitly so just use the newest version
#ifndef OSDI_VERSION_MAJOR_CURR
#include "header/osdi_0_4.h"
#endif


char *concat(const char *s1, const char *s2) {
  const size_t len1 = strlen(s1);
  const size_t len2 = strlen(s2);
  char *result = malloc(len1 + len2 + 1);
  if (result == NULL) {
    return NULL;
  }
  memcpy(result, s1, len1);
  memcpy(result + len1, s2, len2 + 1);
  return result;
}

typedef void (*osdi_log_ptr)(void *handle, char *msg, uint32_t lvl);
extern osdi_log_ptr osdi_log;

/* `%m` (LRM 9.4.4) must print the hierarchical name of the module INSTANCE
 * that invoked the display task -- the clause's whole point is that "when
 * there are many instances ... %m pinpoints the module instance responsible".
 * It used to expand at compile time to the MODULE's name, so every instance
 * printed the same string.
 *
 * The instance name only exists at run time, in the simulator, so it takes a
 * callback slot the simulator fills in at load (exactly like osdi_log above).
 * That is what made this awkward to fix before: a model built by a NEW
 * compiler and loaded by an OLD simulator would find the slot unset. Hence
 * `osdi_inst_name` rather than a direct call -- the NULL check lives here, in
 * the model, so an old simulator silently yields the old module-name
 * behaviour instead of jumping through a null pointer. */
typedef char *(*osdi_instance_name_ptr)(void *handle);
extern osdi_instance_name_ptr osdi_instance_name;

__attribute__((noinline))
char *osdi_inst_name(void *handle, char *fallback) {
  osdi_instance_name_ptr f = osdi_instance_name;
  if (f == NULL || handle == NULL) {
    return fallback;
  }
  char *n = f(handle);
  return (n != NULL && n[0] != '\0') ? n : fallback;
}

#define SCMP(p1, p2, s1, s2, eq) for(p1=s1, p2=s2;*p1 && *p2 && *p1==*p2;p1++, p2++); eq = (*p1==*p2);

/* Enhancement-377: report an unknown $simparam / $simparam$str name.
 *
 * The two call sites used to build the message with `concat(prefix, name)`, which
 * has NO SEPARATOR -- `$simparam$str("analysis")` reported
 *
 *     unknown $simparam_stranalysis
 *
 * where the function name and the argument run together, so the reader cannot see
 * where one ends and the other begins. Three further problems came with it:
 * the name was spelled `$simparam_str` rather than `$simparam$str` as it is
 * written in Verilog-A; there was no trailing newline, so consecutive reports
 * concatenated into one unreadable line; and the malloc'd message was never
 * freed, which leaks once per evaluation (a failing operating point retries, so
 * that is hundreds of allocations, not one).
 *
 * Produces:  unknown $simparam$str "analysis"\n
 */
static void log_unknown_simparam(void *handle, const char *what, const char *name) {
  const size_t lw = strlen(what);
  const size_t ln = strlen(name);
  /* what + '"' + name + '"' + '\n' + NUL */
  char *msg = malloc(lw + ln + 4);
  if (msg == NULL) {
    /* out of memory: fall back to the bare prefix rather than saying nothing */
    osdi_log(handle, (char *)what, LOG_LVL_FATAL | LOG_FMT_ERR);
    return;
  }
  memcpy(msg, what, lw);
  msg[lw] = '"';
  memcpy(msg + lw + 1, name, ln);
  msg[lw + 1 + ln] = '"';
  msg[lw + 2 + ln] = '\n';
  msg[lw + 3 + ln] = '\0';
  osdi_log(handle, msg, LOG_LVL_FATAL);
  free(msg);
}

double simparam(void *params_, void *handle, uint32_t *flags, char *name) {
  OsdiSimParas *params = params_;
  for (int i = 0; params->names[i]; i++) {
    char *p1, *p2;
    int eq;
    SCMP(p1, p2, params->names[i], name, eq);
    // if (strcmp(params->names[i], name) == 0) {
    if (eq) {
      return params->vals[i];
    }
  }
  *flags |= EVAL_RET_FLAG_FATAL;
  log_unknown_simparam(handle, "unknown $simparam ", name);
  return 0.0;
}

double simparam_opt(void *params_, char *name, double default_val) {
  OsdiSimParas *params = params_;
  for (int i = 0; params->names[i]; i++) {
    char *p1, *p2;
    int eq;
    SCMP(p1, p2, params->names[i], name, eq);
    // if (strcmp(params->names[i], name) == 0) {
    if (eq) {
      return params->vals[i];
    }
  }
  return default_val;
}

extern int strcmp(const char *__s1, const char *__s2);

char *simparam_str(void *params_, void *handle, uint32_t *flags, char *name) {
  OsdiSimParas *params = params_;
  // Enhancement-25: walk the *string* parameter list (`names_str`, NULL-terminated)
  // and return the matching *value* (`vals_str`). Previously this loop was bugged --
  // it iterated the numeric `names` array and returned the name instead of the value,
  // so `$simparam$str` never worked (and read out of bounds once the string list is
  // shorter than the numeric one).
  if (params->names_str) {
    for (int i = 0; params->names_str[i]; i++) {
      char *p1, *p2;
      int eq;
      SCMP(p1, p2, params->names_str[i], name, eq);
      if (eq) {
        return params->vals_str[i];
      }
    }
  }
  *flags |= EVAL_RET_FLAG_FATAL;

  log_unknown_simparam(handle, "unknown $simparam$str ", name);

  return "�";
}

/* Enhancement-215: a NON-FATAL string simparam lookup -- like simparam_str, but
 * returns default_val instead of raising a fatal error when the name is absent.
 * `$value$plusargs` needs to ask "is a plusarg present, and what is its string
 * value?" without aborting when it is not: the fatal simparam_str cannot express
 * that. Mirrors the numeric simparam_opt (state is just the params pointer; no
 * handle/flags because it never logs or faults). */
char *simparam_str_opt(void *params_, char *name, char *default_val) {
  OsdiSimParas *params = params_;
  if (params->names_str) {
    for (int i = 0; params->names_str[i]; i++) {
      char *p1, *p2;
      int eq;
      SCMP(p1, p2, params->names_str[i], name, eq);
      if (eq) {
        // Never hand back a NULL string: it flows straight into the scan buffer
        // of `$value$plusargs` (osdi_scan_*), which dereferences it unchecked.
        return params->vals_str[i] ? params->vals_str[i] : "";
      }
    }
  }
  return default_val ? default_val : "";
}

void push_error(OsdiInitError **dst, uint32_t *len, uint32_t *cap,
                OsdiInitError err) {
  if (*dst == NULL) {
    *cap = 8;
    *dst = malloc(8 * sizeof(OsdiInitError));
  } else if (*cap <= *len) {
    *cap = 2 * (*len);
    *dst = realloc(*dst, *cap * sizeof(OsdiInitError));
  }

  (*dst)[*len] = err;
  *len += 1;
}

void push_invalid_param_err(void **dst, uint32_t *len, uint32_t *cap,
                            uint32_t param) {
  OsdiInitError err = (OsdiInitError){
      .code = INIT_ERR_OUT_OF_BOUNDS,
      .payload =
          (OsdiInitErrorPayload){
              .parameter_id = param,
          },
  };

  push_error((OsdiInitError **)dst, len, cap, err);
}

void bound_step(double *dst, double val) { *dst = val; }

#define FMT_OFF 6
#define NUM_FMT 11
const char FMT_CHARS[NUM_FMT] = {'a', 'f', 'p', 'n', 'u', 'm',
                                 ' ', 'k', 'M', 'G', 'T'};
const double EXP[NUM_FMT] = {1e18, 1e15, 1e12, 1e9,  1e6,  1e3,
                             1,    1e-3, 1e-6, 1e-9, 1e-12};
/* %r/%R engineering notation (LRM 9.4.3): pick the SI scale character so the
 * printed mantissa is val * EXP[idx]. Index FMT_OFF (' ') is the unit scale;
 * each step of 3 decades moves one entry ('k' at 1e3 is FMT_OFF+1 with
 * multiplier 1e-3, 'n' at 1e-9 is FMT_OFF-3 with multiplier 1e9).
 *
 * The original computed `((int)log(val))/3` -- the NATURAL log, truncated
 * toward zero, never offset by FMT_OFF -- so every value picked a wrong (or
 * out-of-range) scale and %r printed garbage for all inputs. */
int fmt_char_idx(double val) {
  double a = fabs(val);
  if (a == 0.0 || a != a || a > 1.7e308) {
    return FMT_OFF; /* 0, NaN, inf: print as-is with the unit scale */
  }
  double e = floor(log10(a) / 3.0);
  int pos = FMT_OFF + (int)e;

  if (pos < 0) {
    return 0;
  }
  if (pos >= NUM_FMT) {
    return NUM_FMT - 1;
  }
  return pos;
}

char *fmt_binary(int val) {
  int len = 32 - __builtin_clz(val);
  char *res = malloc(len + 1);
  res[len] = '\0';
  if (len == 0) {
    return res;
  }
  for (int i = 1; i < len + 1; i++) {
    if (val & 1) {
      res[len - i] = '1';
    } else {
      res[len - i] = '0';
    }
    val >>= 1;
  }

  return res;
}

void lim_discontinuity(int *flags) { *flags |= EVAL_RET_FLAG_LIM; }

void set_ret_flag_fatal(int *flags) { *flags |= EVAL_RET_FLAG_FATAL; }

void set_ret_flag_finish(int *flags) { *flags |= EVAL_RET_FLAG_FINISH; }

void set_ret_flag_stop(int *flags) { *flags |= EVAL_RET_FLAG_STOP; }

/* Enhancement-55: $discontinuity(n >= 0) -- see EVAL_RET_FLAG_DISCONT */
void set_ret_flag_discont(int *flags) { *flags |= EVAL_RET_FLAG_DISCONT; }

double store_lim(void *sim_info_, int idx, double val) {
  OsdiSimInfo *sim_info = (OsdiSimInfo *)sim_info_;
  sim_info->next_state[idx] = val;
  return val;
}

int analysis(void *sim_info_, char *name) {
  OsdiSimInfo *sim_info = (OsdiSimInfo *)sim_info_;
  uint32_t flags = sim_info->flags;
  // AB: fixed bug, missing ! in front of strcmp()
  return ((flags & ANALYSIS_AC) && !strcmp(name, "ac")) ||
         ((flags & ANALYSIS_DC) && !strcmp(name, "dc")) ||
         ((flags & ANALYSIS_NOISE) && !strcmp(name, "noise")) ||
         ((flags & ANALYSIS_TRAN) && !strcmp(name, "tran")) ||
         ((flags & ANALYSIS_IC) && !strcmp(name, "ic")) ||
         ((flags & ANALYSIS_STATIC) && !strcmp(name, "static")) ||
         ((flags & ANALYSIS_NODESET) && !strcmp(name, "nodeset"));
}

double store_delay(void *sim_info_, double *dst, double val) {
  OsdiSimInfo *sim_info = (OsdiSimInfo *)sim_info_;
  if (sim_info->flags & ANALYSIS_IC) {
    *dst = val;
    return val;
  }

  return *dst;
}

// ---------------------------------------------------------------------------
// Enhancement-10: statistical / random-number system functions.
//
// These back the Verilog-AMS `$random`, `$arandom`, `$dist_*` and `$rdist_*`
// system functions. Each is a *pure*, deterministic function of `(seed, salt)`
// plus the distribution parameters -- there is no persistent RNG state. `salt`
// is a per-call-site constant supplied by the compiler (the call's ExprId) so
// that independent draws (distinct call sites) use independent streams, while a
// given `(seed, salt)` is perfectly reproducible and, crucially, stable across
// the nonlinear solver's Newton iterations (an in-place-advancing seed, as the
// LRM nominally prescribes, would change every evaluation and break DC/tran
// convergence). See Enhancement-10.md for the full rationale.
//
// The core generator is splitmix64 seeded by a hash of (seed, salt); every
// uniform variate advances a *local* 64-bit state, so multi-uniform
// distributions (normal, chi-square, student-t, erlang, ...) draw independent
// underlying uniforms within a single call.
// ---------------------------------------------------------------------------

typedef unsigned long long u64;

// 2 * pi, for the Box-Muller transform.
#define OSDI_TWO_PI 6.28318530717958647692528676655900577

// Derive the initial 64-bit generator state from (seed, salt). The avalanche
// mixing ensures small / adjacent (seed, salt) pairs diverge immediately.
static u64 osdi_rng_state(int32_t seed, int32_t salt) {
  u64 s = ((u64)(uint32_t)seed << 32) | (u64)(uint32_t)salt;
  s ^= 0x9E3779B97F4A7C15ULL;
  s = (s ^ (s >> 30)) * 0xBF58476D1CE4E5B9ULL;
  s = (s ^ (s >> 27)) * 0x94D049BB133111EBULL;
  return s ^ (s >> 31);
}

// One splitmix64 step -> uniform double in [0, 1) with 53 bits of entropy.
static double osdi_rng_unit(u64 *state) {
  u64 z = (*state += 0x9E3779B97F4A7C15ULL);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  z = z ^ (z >> 31);
  return (double)(z >> 11) * (1.0 / 9007199254740992.0); // * 2^-53
}

// A standard normal deviate via the Box-Muller transform (two uniforms).
static double osdi_rng_std_normal(u64 *state) {
  double u1 = osdi_rng_unit(state);
  double u2 = osdi_rng_unit(state);
  if (u1 < 1e-300) {
    u1 = 1e-300; // guard log(0)
  }
  return sqrt(-2.0 * log(u1)) * cos(OSDI_TWO_PI * u2);
}

// $random / $arandom: uniform signed 32-bit integer (returned as a double; the
// caller casts back to int). The exact sign convention is implementation-
// defined in the LRM.
double osdi_rng_random(int32_t seed, int32_t salt) {
  u64 s = osdi_rng_state(seed, salt);
  return (double)(int32_t)(uint32_t)(s >> 21);
}

// $rdist_uniform: real uniform in [start, end).
double osdi_rng_uniform(int32_t seed, int32_t salt, double start, double end) {
  u64 s = osdi_rng_state(seed, salt);
  double u = osdi_rng_unit(&s);
  if (end < start) {
    double t = start;
    start = end;
    end = t;
  }
  return start + (end - start) * u;
}

// $dist_uniform: integer uniform, inclusive on [start, end].
double osdi_rng_uniform_int(int32_t seed, int32_t salt, double start,
                            double end) {
  u64 s = osdi_rng_state(seed, salt);
  double u = osdi_rng_unit(&s);
  long lo = (long)start;
  long hi = (long)end;
  if (hi < lo) {
    long t = lo;
    lo = hi;
    hi = t;
  }
  long span = hi - lo + 1;
  long r = lo + (long)(u * (double)span);
  if (r > hi) {
    r = hi; // u < 1 makes this all but unreachable; clamp defensively
  }
  return (double)r;
}

// $rdist_normal / $dist_normal: gaussian with the given mean and std deviation.
double osdi_rng_normal(int32_t seed, int32_t salt, double mean,
                       double std_dev) {
  u64 s = osdi_rng_state(seed, salt);
  return mean + std_dev * osdi_rng_std_normal(&s);
}

// $rdist_exponential / $dist_exponential: exponential with the given mean.
double osdi_rng_exponential(int32_t seed, int32_t salt, double mean) {
  u64 s = osdi_rng_state(seed, salt);
  double u = osdi_rng_unit(&s);
  if (u < 1e-300) {
    u = 1e-300;
  }
  return -mean * log(u);
}

// $rdist_poisson / $dist_poisson: poisson count with the given mean, via
// Knuth's multiplicative algorithm (adequate for the modest means used in
// device models).
double osdi_rng_poisson(int32_t seed, int32_t salt, double mean) {
  if (mean <= 0.0) {
    return 0.0;
  }
  u64 s = osdi_rng_state(seed, salt);
  double L = exp(-mean);
  double p = 1.0;
  long k = 0;
  do {
    k++;
    p *= osdi_rng_unit(&s);
  } while (p > L);
  return (double)(k - 1);
}

// $rdist_chi_square / $dist_chi_square: sum of `dof` squared standard normals.
double osdi_rng_chi_square(int32_t seed, int32_t salt, double dof) {
  u64 s = osdi_rng_state(seed, salt);
  long k = (long)dof;
  if (k < 1) {
    k = 1;
  }
  double acc = 0.0;
  for (long i = 0; i < k; i++) {
    double z = osdi_rng_std_normal(&s);
    acc += z * z;
  }
  return acc;
}

// $rdist_t / $dist_t: student-t with `dof` degrees of freedom,
// z / sqrt(chi_square(dof) / dof).
double osdi_rng_t(int32_t seed, int32_t salt, double dof) {
  u64 s = osdi_rng_state(seed, salt);
  long k = (long)dof;
  if (k < 1) {
    k = 1;
  }
  double z = osdi_rng_std_normal(&s);
  double chi = 0.0;
  for (long i = 0; i < k; i++) {
    double n = osdi_rng_std_normal(&s);
    chi += n * n;
  }
  return z / sqrt(chi / (double)k);
}

// $rdist_erlang / $dist_erlang: erlang with shape `k` and the given total mean
// (sum of k exponentials, each with mean `mean/k`).
double osdi_rng_erlang(int32_t seed, int32_t salt, double k_in, double mean) {
  u64 s = osdi_rng_state(seed, salt);
  long k = (long)k_in;
  if (k < 1) {
    k = 1;
  }
  double per = mean / (double)k;
  double acc = 0.0;
  for (long i = 0; i < k; i++) {
    double u = osdi_rng_unit(&s);
    if (u < 1e-300) {
      u = 1e-300;
    }
    acc += -per * log(u);
  }
  return acc;
}

// ---------------------------------------------------------------------------
// Enhancement-11: file I/O system functions.
//
// Verilog-AMS $fopen returns an *integer* descriptor, but a host FILE* is a
// 64-bit pointer, so we keep a small module-global table of open FILE*s and
// hand out 1-based indices into it. Index 0 is reserved so that a returned 0
// means "open failed", matching the LRM. All the $f* descriptor functions look
// the FILE* back up through this table.
//
// The table is per-loaded-OSDI-module state (all instances of a model share it,
// which is correct -- file descriptors are global). It is not guarded against
// concurrent access, so file I/O should be confined to the usual setup / event
// contexts (e.g. @(initial_step)); see Enhancement-11.md.
// ---------------------------------------------------------------------------

#define OSDI_MAX_FILES 64
// `volatile` is load-bearing: the descriptor table is `internal` module state
// and the `osdi_f*` functions are `internal` too, so LLVM's aggressive
// interprocedural passes (IPSCCP / GlobalOpt) will otherwise "prove" the table
// contents at compile time -- e.g. fold `$fopen`'s returned slot index to a
// constant and specialise `osdi_fputs` down to `table[0]` (always NULL), so no
// write ever reaches the file. Marking the slots volatile forces every access
// to be a real runtime load/store and defeats that mis-specialisation. The
// `noinline` on the entry points keeps them from being inlined and re-analysed
// at each call site.
#define OSDI_SHARED __attribute__((weak))
OSDI_SHARED void *volatile osdi_file_table[OSDI_MAX_FILES];
// Name each slot was opened under (for the same-name dedup below).
OSDI_SHARED char *volatile osdi_file_names[OSDI_MAX_FILES];
// Opened with a readable mode ('r' or '+'): only these streams take part in
// the read-position rewind below -- rewinding a write-only stream would make
// later writes overwrite what an accepted iteration already wrote.
OSDI_SHARED char volatile osdi_file_readable[OSDI_MAX_FILES];
// $fclose seen while the deferral is not yet managed (i.e. during instance
// setup, where the compiler hoists parameter-only file code): the close is
// postponed so the descriptor stays valid for the eval function's deferred
// writes (the open-write-close idiom, LRM 9.5) and executed at the next
// accepted-iteration flush.
OSDI_SHARED char volatile osdi_file_close_req[OSDI_MAX_FILES];
// Read-position baseline per slot: `osdi_io_iter_begin` rewinds every stream
// here, and `osdi_io_flush` (accepted iteration) advances it -- so the reads
// of a rejected/superseded Newton iteration are replayed and the accepted
// iteration's reads stick (LRM 9.5.9).
OSDI_SHARED long volatile osdi_file_basepos[OSDI_MAX_FILES];

/* LRM 9.5.1 distinguishes TWO kinds of descriptor, and the difference is not
 * cosmetic:
 *
 *   - `$fopen(name, mode)` yields a FILE DESCRIPTOR, "a 32-bit value ... with
 *     the most significant bit set", naming exactly one stream.
 *   - `$fopen(name)` yields a MULTICHANNEL DESCRIPTOR, "a 32-bit integer in
 *     which a single bit is set". Bit 0 ALWAYS refers to the standard output,
 *     and output goes to several files at once "by bitwise OR-ing together
 *     their multichannel descriptors".
 *
 * Both used to be drawn from one namespace of consecutive small integers, so
 * `$fopen("a")` and `$fopen("b")` returned 1 and 2 and the LRM's own idiom
 * `$fdisplay(mA|mB, ...)` computed 3 -- the descriptor of an unrelated third
 * file, which silently received the text. Descriptor 1, which the LRM reserves
 * for stdout, was handed to the first user file instead.
 *
 * So: a file descriptor is the slot index with OSDI_FD_BIT set (slots 0..2 are
 * the pre-opened standard streams, which is why user slots start at 3), and a
 * multichannel descriptor is a one-hot bit that indexes osdi_mcd_table. The
 * two are told apart by OSDI_FD_BIT, exactly as the LRM's wording implies. */
#define OSDI_FD_BIT 0x80000000u
#define OSDI_FD_FIRST 3
#define OSDI_MCD_BITS 32
OSDI_SHARED void *volatile osdi_mcd_table[OSDI_MCD_BITS];
OSDI_SHARED char *volatile osdi_mcd_names[OSDI_MCD_BITS];

// Slot behind a file descriptor, or -1 if this is not a file descriptor.
static int osdi_fd_slot(int fd) {
  unsigned u = (unsigned)fd;
  if (!(u & OSDI_FD_BIT)) {
    return -1;
  }
  unsigned i = u & ~OSDI_FD_BIT;
  if (i >= OSDI_MAX_FILES) {
    return -1;
  }
  return (int)i;
}

// File names written earlier in this simulator process: a "w"-mode reopen of
// such a name APPENDS instead of truncating, so a later analysis in the same
// process extends the earlier one's output (LRM 9.5.1.1).
#define OSDI_MAX_WRITTEN 128
OSDI_SHARED char *volatile osdi_written_names[OSDI_MAX_WRITTEN];

// Writes of the current Newton iteration, buffered until the iteration is
// accepted (LRM 9.5.9; the $fdebug/event-gated paths bypass this with
// immediate=1). The simulator drives the lifecycle through the exported
// osdi_io_iter_begin / osdi_io_flush below; a simulator that never calls them
// (an older ngspice) still gets every write, at flush-by-next-iteration
// granularity... except it never clears -- so writes fall through immediately
// when the buffer is unmanaged (osdi_io_managed stays 0).
typedef struct {
  int fd;
  char *s;
} OsdiPendingWrite;
OSDI_SHARED OsdiPendingWrite *volatile osdi_pending_writes;
OSDI_SHARED int volatile osdi_pending_len;
OSDI_SHARED int volatile osdi_pending_cap;
OSDI_SHARED int volatile osdi_io_managed;

#define OSDI_NOINLINE __attribute__((noinline))
#define OSDI_EXPORT __attribute__((visibility("default")))

static void *osdi_file_lookup(int fd) {
  int slot = osdi_fd_slot(fd);
  // LRM 9.5.1: pre-opened descriptors for the standard streams.
  if (slot == 0) {
    return OSDI_STDIN;
  }
  if (slot == 1) {
    return OSDI_STDOUT;
  }
  if (slot == 2) {
    return OSDI_STDERR;
  }
  if (slot < 0) {
    // A multichannel descriptor. Only the write path understands one -- it
    // fans out over the set bits -- so every other file operation, which the
    // LRM defines on a file descriptor, correctly finds nothing here.
    return NULL;
  }
  return osdi_file_table[slot];
}

// The single stream behind a one-hot multichannel bit (bit 0 is stdout).
static void *osdi_mcd_lookup(int bit) {
  if (bit == 0) {
    return OSDI_STDOUT;
  }
  if (bit < 0 || bit >= OSDI_MCD_BITS) {
    return NULL;
  }
  return osdi_mcd_table[bit];
}

static int osdi_name_was_written(const char *name) {
  for (int i = 0; i < OSDI_MAX_WRITTEN; i++) {
    if (osdi_written_names[i] && strcmp(osdi_written_names[i], name) == 0) {
      return 1;
    }
  }
  return 0;
}

static void osdi_record_written(const char *name) {
  if (osdi_name_was_written(name)) {
    return;
  }
  for (int i = 0; i < OSDI_MAX_WRITTEN; i++) {
    if (osdi_written_names[i] == NULL) {
      size_t n = strlen(name) + 1;
      char *copy = malloc(n);
      if (copy) {
        memcpy(copy, name, n);
        osdi_written_names[i] = copy;
      }
      return;
    }
  }
}

// Is a deferred $fclose (LRM 9.5.9: s == NULL is the close marker) queued for
// this slot? Under managed I/O that queue, not osdi_file_close_req, is where a
// close waits, so a reopen has to consult it to see that the model closed the
// file. `drop` removes the markers as well as reporting them: a reopen makes
// the stream live again, so the queued close must not fire at the next flush
// and shut the file under the reader that just opened it.
static int osdi_close_deferred(int fd, int drop) {
  int found = 0;
  int w = 0;
  for (int i = 0; i < osdi_pending_len; i++) {
    if (osdi_pending_writes[i].fd == fd && osdi_pending_writes[i].s == NULL) {
      found = 1;
      if (drop) {
        continue;
      }
    }
    if (drop) {
      osdi_pending_writes[w++] = osdi_pending_writes[i];
    }
  }
  if (drop) {
    osdi_pending_len = w;
  }
  return found;
}

// $fopen(name, mode) -> descriptor (0 on failure). An EMPTY mode is how the
// lowering spells the LRM's one-argument `$fopen(name)`, which returns a
// multichannel descriptor rather than a file descriptor.
OSDI_NOINLINE int osdi_fopen(const char *name, const char *mode) {
  if (mode[0] == '\0') {
    // Multichannel: one bit per file, bit 0 reserved for stdout. Same-name
    // dedup as below, so reopening a channel returns the bit it already has.
    for (int b = 1; b < OSDI_MCD_BITS; b++) {
      if (osdi_mcd_table[b] != NULL && osdi_mcd_names[b] != NULL &&
          strcmp((const char *)osdi_mcd_names[b], name) == 0) {
        // Reopening cancels a deferred $fclose of this channel, for the same
        // reason it does on the file-descriptor path above: otherwise the
        // queued close fires at the next flush and shuts the channel under a
        // model that believes it just reopened it, and later writes to the
        // bit vanish with no error.
        osdi_close_deferred(1 << b, 1);
        return 1 << b;
      }
    }
    for (int b = 1; b < OSDI_MCD_BITS; b++) {
      if (osdi_mcd_table[b] == NULL) {
        // LRM 9.5.1.1's append-on-rewrite rule applies here too.
        const char *m = osdi_name_was_written(name) ? "a" : "w";
        void *f = fopen(name, m);
        if (f == NULL) {
          return 0;
        }
        osdi_mcd_table[b] = f;
        size_t n = strlen(name) + 1;
        char *copy = malloc(n);
        if (copy) {
          memcpy(copy, name, n);
        }
        osdi_mcd_names[b] = copy;
        osdi_record_written(name);
        return 1 << b;
      }
    }
    return 0; // all 31 channels in use
  }
  // Same-name dedup: an $fopen of a file that is already open returns the
  // existing descriptor instead of burning a new slot. This keeps the
  // per-evaluation open-write-close idiom (LRM statements execute per
  // evaluation) from exhausting the table when the model omits the $fclose.
  for (int i = OSDI_FD_FIRST; i < OSDI_MAX_FILES; i++) {
    if (osdi_file_table[i] != NULL && osdi_file_names[i] != NULL &&
        strcmp((const char *)osdi_file_names[i], name) == 0) {
      // A close-then-open of the same name must hand back a stream positioned
      // at byte 0, not one that carries the closed stream's read offset. The
      // dedup above is what makes that non-automatic, and the reopen branch
      // below only ever ran for unmanaged I/O -- so under the simulator (which
      // is always managed) `$fclose` + `$fopen` + `$fgets` returned the LINE
      // AFTER the one the first read consumed. Rewinding is enough for the
      // read path and leaves the write deferral untouched: a write-mode
      // reopen keeps the existing append-and-close-at-flush behaviour, whose
      // pending writes must still land in queue order.
      int readable = (mode[0] == 'r' || strchr(mode, '+') != NULL);
      int enc = (int)(OSDI_FD_BIT | (unsigned)i);
      // Only when the stream is ALREADY readable: reopening a write-mode
      // stream for reading is a MODE CHANGE and needs the freopen below --
      // seeking a "w" handle back to 0 leaves it just as unreadable as it was.
      if (readable && osdi_file_readable[i] &&
          (osdi_file_close_req[i] || osdi_close_deferred(enc, 0))) {
        osdi_close_deferred(enc, 1);
        fseek(osdi_file_table[i], 0, SEEK_SET);
        osdi_file_readable[i] = 1;
        osdi_file_basepos[i] = 0;
        osdi_file_close_req[i] = 0;
        return enc;
      }
      if (!osdi_io_managed && osdi_file_close_req[i]) {
        // The instance initialization re-ran (ngspice executes it for both
        // setup and temperature): the previous run already open-...-closed
        // this file, so behave like the first run's fresh open -- honoring
        // the requested mode (truncating for "w") -- instead of continuing
        // at the previous run's position.
        void *nf = freopen(name, mode, osdi_file_table[i]);
        if (nf == NULL) {
          osdi_file_table[i] = NULL;
          if (osdi_file_names[i]) {
            free(osdi_file_names[i]);
            osdi_file_names[i] = NULL;
          }
          osdi_file_close_req[i] = 0;
          continue;
        }
        osdi_file_table[i] = nf;
        osdi_file_readable[i] = (mode[0] == 'r' || strchr(mode, '+') != NULL);
        osdi_file_basepos[i] = ftell(nf);
      }
      osdi_file_close_req[i] = 0;
      return enc;
    }
  }
  // LRM 9.5.1.1: a "w"-mode reopen of a file already written in this
  // simulator process appends rather than truncating.
  char mode_buf[8];
  if (mode[0] == 'w' && osdi_name_was_written(name)) {
    size_t n = strlen(mode);
    if (n >= sizeof(mode_buf)) {
      n = sizeof(mode_buf) - 1;
    }
    memcpy(mode_buf, mode, n);
    mode_buf[n] = '\0';
    mode_buf[0] = 'a';
    mode = mode_buf;
  }
  for (int i = OSDI_FD_FIRST; i < OSDI_MAX_FILES; i++) {
    if (osdi_file_table[i] == NULL) {
      void *f = fopen(name, mode);
      if (f == NULL) {
        return 0;
      }
      osdi_file_table[i] = f;
      size_t n = strlen(name) + 1;
      char *copy = malloc(n);
      if (copy) {
        memcpy(copy, name, n);
      }
      osdi_file_names[i] = copy;
      osdi_file_readable[i] = (mode[0] == 'r' || strchr(mode, '+') != NULL);
      osdi_file_close_req[i] = 0;
      osdi_file_basepos[i] = ftell(f);
      if (mode[0] == 'w' || mode[0] == 'a' || strchr(mode, '+')) {
        osdi_record_written(name);
      }
      return (int)(OSDI_FD_BIT | (unsigned)i);
    }
  }
  return 0; // table full
}

static void osdi_fputs_now(int fd, const char *s) {
  if (osdi_fd_slot(fd) < 0) {
    // A multichannel descriptor: LRM 9.5.1 says output goes to every file
    // whose bit is set, which is what makes `$fdisplay(mA|mB, ...)` write to
    // both. Bit 0 is stdout.
    unsigned mask = (unsigned)fd;
    for (int b = 0; b < OSDI_MCD_BITS && mask; b++) {
      if (mask & (1u << b)) {
        void *f = osdi_mcd_lookup(b);
        if (f != NULL) {
          fputs(s, f);
        }
        mask &= ~(1u << b);
      }
    }
    return;
  }
  void *f = osdi_file_lookup(fd);
  if (f != NULL) {
    fputs(s, f);
  }
}

static int osdi_fclose_now(int fd);

// Sink for the $fdisplay/$fwrite/... formatted string (see print_callback).
// `immediate` is set for $fdebug and for writes inside event-controlled
// blocks; everything else is deferred until the iteration is accepted
// (LRM 9.5.9) -- when the simulator manages the buffer.
OSDI_NOINLINE void osdi_fputs(int fd, const char *s, int immediate) {
  if (immediate || !osdi_io_managed) {
    osdi_fputs_now(fd, s);
    return;
  }
  if (osdi_pending_len >= osdi_pending_cap) {
    int cap = osdi_pending_cap ? 2 * osdi_pending_cap : 16;
    OsdiPendingWrite *grown =
        realloc(osdi_pending_writes, (size_t)cap * sizeof(OsdiPendingWrite));
    if (grown == NULL) {
      osdi_fputs_now(fd, s); // out of memory: write through
      return;
    }
    osdi_pending_writes = grown;
    osdi_pending_cap = cap;
  }
  size_t n = strlen(s) + 1;
  char *copy = malloc(n);
  if (copy == NULL) {
    osdi_fputs_now(fd, s);
    return;
  }
  memcpy(copy, s, n);
  osdi_pending_writes[osdi_pending_len].fd = fd;
  osdi_pending_writes[osdi_pending_len].s = copy;
  osdi_pending_len++;
}

// Exported to the simulator (looked up with dlsym, optional): a new Newton
// iteration starts -- drop the previous iteration's deferred writes and
// rewind every stream's read position to its accepted baseline (LRM 9.5.9).
OSDI_EXPORT void osdi_io_iter_begin(void) {
  osdi_io_managed = 1;
  for (int i = 0; i < osdi_pending_len; i++) {
    if (osdi_pending_writes[i].s != NULL) {
      free(osdi_pending_writes[i].s);
    }
  }
  osdi_pending_len = 0;
  for (int i = 1; i < OSDI_MAX_FILES; i++) {
    void *f = osdi_file_table[i];
    if (f != NULL && osdi_file_readable[i]) {
      fseek(f, osdi_file_basepos[i], SEEK_SET);
    }
  }
}

// Exported to the simulator: the iteration was accepted -- perform its
// deferred writes and advance the read baselines.
OSDI_EXPORT void osdi_io_flush(void) {
  for (int i = 0; i < osdi_pending_len; i++) {
    if (osdi_pending_writes[i].s != NULL) {
      osdi_fputs_now(osdi_pending_writes[i].fd, osdi_pending_writes[i].s);
      free(osdi_pending_writes[i].s);
    } else {
      osdi_fclose_now(osdi_pending_writes[i].fd); // deferred $fclose
    }
  }
  osdi_pending_len = 0;
  for (int i = 1; i < OSDI_MAX_FILES; i++) {
    void *f = osdi_file_table[i];
    if (f != NULL && osdi_file_readable[i]) {
      osdi_file_basepos[i] = ftell(f);
    }
    if (f != NULL && osdi_file_close_req[i]) {
      osdi_file_close_req[i] = 0;
      osdi_fclose_now((int)(OSDI_FD_BIT | (unsigned)i));
    }
  }
}

static int osdi_fclose_now(int fd) {
  int slot = osdi_fd_slot(fd);
  if (slot < 0) {
    // $fclose of a multichannel descriptor closes every channel in the mask
    // (LRM 9.5.2). Bit 0 is stdout and is never closed.
    unsigned mask = (unsigned)fd;
    int r = -1;
    for (int b = 1; b < OSDI_MCD_BITS; b++) {
      if ((mask & (1u << b)) && osdi_mcd_table[b] != NULL) {
        r = fclose(osdi_mcd_table[b]);
        osdi_mcd_table[b] = NULL;
        if (osdi_mcd_names[b]) {
          free(osdi_mcd_names[b]);
          osdi_mcd_names[b] = NULL;
        }
      }
    }
    return r;
  }
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  int r = fclose(f);
  osdi_file_table[slot] = NULL;
  if (osdi_file_names[slot]) {
    free(osdi_file_names[slot]);
    osdi_file_names[slot] = NULL;
  }
  return r;
}

// $fclose(fd). Under the simulator-managed deferral (LRM 9.5.9) the close
// itself is deferred as a pending entry with s == NULL: the accepted
// iteration's flush performs the writes and then the close, while a
// superseded iteration's close is simply dropped (the file stays open and the
// next iteration's $fopen returns the same descriptor via the name dedup).
OSDI_NOINLINE int osdi_fclose(int fd) {
  // Closing a pre-opened standard stream is a no-op.
  unsigned u = (unsigned)fd;
  if (u == 0x80000000u || u == 0x80000001u || u == 0x80000002u) {
    return 0;
  }
  int slot = osdi_fd_slot(fd);
  // A multichannel descriptor names one or more channels, none of which the
  // file-descriptor lookup can see; it is live if any of its bits is open.
  int live = (slot >= 0) ? (osdi_file_lookup(fd) != NULL) : 0;
  if (slot < 0) {
    unsigned mask = (unsigned)fd;
    for (int b = 1; b < OSDI_MCD_BITS; b++) {
      if ((mask & (1u << b)) && osdi_mcd_table[b] != NULL) {
        live = 1;
        break;
      }
    }
  }
  if (!osdi_io_managed) {
    // Instance-setup close: keep the stream open for eval's deferred writes
    // and close it at the first accepted-iteration flush instead.
    if (!live) {
      return -1;
    }
    if (slot >= OSDI_FD_FIRST && slot < OSDI_MAX_FILES) {
      osdi_file_close_req[slot] = 1;
      return 0;
    }
    // Multichannel descriptors have no deferral slot; close them outright.
    return osdi_fclose_now(fd);
  }
  if (!live) {
    return -1;
  }
  if (osdi_pending_len >= osdi_pending_cap) {
    int cap = osdi_pending_cap ? 2 * osdi_pending_cap : 16;
    OsdiPendingWrite *grown =
        realloc(osdi_pending_writes, (size_t)cap * sizeof(OsdiPendingWrite));
    if (grown == NULL) {
      return osdi_fclose_now(fd);
    }
    osdi_pending_writes = grown;
    osdi_pending_cap = cap;
  }
  osdi_pending_writes[osdi_pending_len].fd = fd;
  osdi_pending_writes[osdi_pending_len].s = NULL; // close marker
  osdi_pending_len++;
  return 0;
}

// $fflush(fd)
OSDI_NOINLINE int osdi_fflush(int fd) {
  if (osdi_fd_slot(fd) < 0) {
    // A multichannel descriptor flushes every channel in its mask, the same
    // way a write to it reaches every channel.
    unsigned mask = (unsigned)fd;
    int r = -1;
    for (int b = 0; b < OSDI_MCD_BITS; b++) {
      if (mask & (1u << b)) {
        void *ch = osdi_mcd_lookup(b);
        if (ch != NULL) {
          r = fflush(ch);
        }
      }
    }
    return r;
  }
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  return fflush(f);
}

// $fflush()  -- flush every open stream
OSDI_NOINLINE int osdi_fflush_all(void) {
  return fflush(NULL);
}

// $feof(fd)
OSDI_NOINLINE int osdi_feof(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return 0;
  }
  return feof(f);
}

// $ftell(fd)
OSDI_NOINLINE int osdi_ftell(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  return (int)ftell(f);
}

// Enhancement-107: $fgetc(fd) -- read one character; returns its code, or -1
// (EOF) at end-of-file or on a bad descriptor.
OSDI_NOINLINE int osdi_fgetc(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  return fgetc(f);
}

// Enhancement-108: $ungetc(c, fd) -- push character c back onto the stream so
// the next $fgetc(fd) returns it. Returns c on success, or -1 on failure / a
// bad descriptor. Argument order matches the Verilog `$ungetc(c, fd)` call.
OSDI_NOINLINE int osdi_ungetc(int c, int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  return ungetc(c, f);
}

// $fseek(fd, offset, whence)  -- whence 0/1/2 = SET/CUR/END
OSDI_NOINLINE int osdi_fseek(int fd, int offset, int whence) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  return fseek(f, (long)offset, whence);
}

// $rewind(fd)
OSDI_NOINLINE int osdi_frewind(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  rewind(f);
  return 0;
}

// ---------------------------------------------------------------------------
// Enhancement-11: string-formatting and file-reading system functions.
//
//   $swrite/$sformat -> handled by the print_callback "String" sink (returns a
//                       formatted char*), no runtime function needed here.
//   $fgets           -> osdi_fgets + osdi_strlen
//   $ferror          -> osdi_ferror_msg + osdi_ferror_code
//   $sscanf/$fscanf  -> osdi_scanf_begin + osdi_scan_int/real/str + osdi_scanf_count
//
// The scanner is a simple whitespace-delimited tokenizer over a module-global
// cursor. It does not interpret the C format string: each field is parsed by
// the type of its destination variable (int via strtol, real via strtod, string
// as the next token) -- adequate for the usual `%d %g %s`-over-whitespace input.
// As with the descriptor table, the cursor/counter are `volatile` so LLVM's IPO
// can't specialise them away (see Enhancement-11.md).
// ---------------------------------------------------------------------------

extern size_t strlen(const char *);
extern int strcmp(const char *, const char *);

OSDI_NOINLINE
int osdi_strlen(const char *s) { return s ? (int)strlen(s) : 0; }

// Enhancement-106: lexicographic string comparison backing the relational
// operators (`<`, `<=`, `>`, `>=`). Returns the sign of the difference; a NULL
// string is treated as empty.
OSDI_NOINLINE
int osdi_strcmp(const char *a, const char *b) {
  return strcmp(a ? a : "", b ? b : "");
}

OSDI_NOINLINE
char *osdi_fgets(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return "";
  }
  char *buf = malloc(4096);
  if (buf == NULL) {
    return "";
  }
  if (fgets(buf, 4096, f) == NULL) {
    buf[0] = '\0'; // EOF / error -> empty string
  }
  return buf;
}

// $fscanf's line read. $fscanf is lowered as "read a line, then scan it like
// $sscanf", which by itself consumes the WHOLE line however little the format
// matches -- so the ordinary "scan the numbers, take the trailing text" idiom
// lost everything after the last conversion, and a following $fgets returned
// the line after next. The scan must put back what it did not consume, so the
// line read records where the line began; the scanners below then keep the
// descriptor sitting exactly at the last converted character.
OSDI_SHARED int volatile osdi_scan_src_fd;
OSDI_SHARED long volatile osdi_scan_src_pos;
OSDI_SHARED const char *volatile osdi_scan_src_base;

OSDI_NOINLINE
char *osdi_fgets_scan(int fd) {
  void *f = osdi_file_lookup(fd);
  long pos = f ? ftell(f) : -1;
  char *buf = osdi_fgets(fd);
  // Arm the pushback only for a seekable stream: on a pipe or terminal ftell
  // fails and the bytes are simply gone, which is the same limitation C's own
  // fscanf has there.
  if (f != NULL && pos >= 0 && buf != NULL && buf[0] != '\0') {
    osdi_scan_src_fd = fd;
    osdi_scan_src_pos = pos;
    osdi_scan_src_base = buf;
  } else {
    osdi_scan_src_fd = 0;
  }
  return buf;
}

OSDI_NOINLINE
int osdi_ferror_code(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  return ferror(f);
}

OSDI_NOINLINE
char *osdi_ferror_msg(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return "invalid descriptor";
  }
  return ferror(f) ? "I/O error" : "";
}

OSDI_SHARED const char *volatile osdi_scan_cursor;
OSDI_SHARED int volatile osdi_scan_matches;
/* Enhancement-507: a field that does not convert must leave its destination
 * ALONE.
 *
 * Each scanner used to return 0 / 0.0 / "" when nothing parsed and the lowering
 * stored that unconditionally, so a failed conversion DESTROYED the value the
 * variable already held -- `$sscanf("abc", "%d", x)` set x to 0, and a partial
 * parse zeroed every destination past the last match. C leaves an unmatched
 * argument untouched and IEEE 1364 follows it, which is what makes the ordinary
 * idiom work:
 *
 *     x = fallback;
 *     if ($sscanf(line, "%d", x) < 1)  // x is still fallback
 *
 * The destination's CURRENT value is passed in and handed straight back when the
 * field does not convert. Passing it as an argument rather than branching in the
 * generated code keeps the callers branch-free: an earlier version selected on a
 * separate "did it match" callback and the extra blocks produced a module that
 * segfaulted in the simulator. */

static int osdi_is_ws(char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}

static const char *osdi_skip_ws(const char *p) {
  while (*p && osdi_is_ws(*p)) {
    p++;
  }
  return p;
}

// Put the descriptor back to the first byte the format did not consume. Called
// after every field so the position is right however early the scan stops.
static void osdi_scan_sync(void) {
  if (osdi_scan_src_fd == 0 || osdi_scan_src_base == NULL) {
    return;
  }
  void *f = osdi_file_lookup(osdi_scan_src_fd);
  if (f == NULL) {
    osdi_scan_src_fd = 0;
    return;
  }
  long used = (long)(osdi_scan_cursor - osdi_scan_src_base);
  if (used >= 0) {
    fseek(f, osdi_scan_src_pos + used, SEEK_SET);
  }
}

OSDI_NOINLINE
void osdi_scanf_begin(const char *input) {
  osdi_scan_cursor = input ? input : "";
  osdi_scan_matches = 0;
  // Only a line read by osdi_fgets_scan (i.e. $fscanf) may reposition a file.
  // A $sscanf over a plain string -- including one the model got from its own
  // $fgets, which is specified to have consumed the whole line -- must not.
  if (input == NULL || input != osdi_scan_src_base) {
    osdi_scan_src_fd = 0;
  }
}

OSDI_NOINLINE
int osdi_scan_int(int fallback) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 0);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_sync();
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  osdi_scan_sync();
  return fallback;
}

// Enhancement-105: base-specific integer scanners for the `%h`/`%o`/`%b`
// conversions. Unlike osdi_scan_int (strtol base 0, which infers the base from
// the input's own prefix), these force the base named by the format specifier,
// so `$sscanf("ff", "%h", x)` yields 255 and `$sscanf("17", "%o", x)` yields 15.
OSDI_NOINLINE
int osdi_scan_hex(int fallback) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 16);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_sync();
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  osdi_scan_sync();
  return fallback;
}

OSDI_NOINLINE
int osdi_scan_oct(int fallback) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 8);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_sync();
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  osdi_scan_sync();
  return fallback;
}

OSDI_NOINLINE
int osdi_scan_bin(int fallback) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 2);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_sync();
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  osdi_scan_sync();
  return fallback;
}

OSDI_NOINLINE
double osdi_scan_real(double fallback) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  double v = strtod(p, &end);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_sync();
    osdi_scan_matches++;
    return v;
  }
  osdi_scan_cursor = p;
  osdi_scan_sync();
  return fallback;
}

OSDI_NOINLINE
char *osdi_scan_str(char *fallback) {
  const char *start = osdi_skip_ws(osdi_scan_cursor);
  const char *p = start;
  while (*p && !osdi_is_ws(*p)) {
    p++;
  }
  size_t len = (size_t)(p - start);
  char *res = malloc(len + 1);
  if (res == NULL) {
    return "";
  }
  memcpy(res, start, len);
  res[len] = '\0';
  if (len == 0) {
    return fallback ? fallback : "";
  }
  osdi_scan_cursor = p;
  osdi_scan_sync();
  osdi_scan_matches++;
  return res;
}

OSDI_NOINLINE
int osdi_scanf_count(void) { return osdi_scan_matches; }

