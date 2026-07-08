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
#define NULL ((void*)0)
#else
#include <math.h>
#include <stdio.h>
#include "stdlib.h"
#include "string.h"
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

#define SCMP(p1, p2, s1, s2, eq) for(p1=s1, p2=s2;*p1 && *p2 && *p1==*p2;p1++, p2++); eq = (*p1==*p2);

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
  char *msg = concat("unknown $simparam", name);
  if (msg == NULL) {
    osdi_log(handle, "unknown $simparam %s", LOG_LVL_FATAL | LOG_FMT_ERR);
  } else {
    osdi_log(handle, msg, LOG_LVL_FATAL);
  }
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

  char *msg = concat("unknown $simparam_str", name);
  if (msg == NULL) {
    osdi_log(handle, "unknown $simparam_str %s", LOG_LVL_FATAL | LOG_FMT_ERR);
  } else {
    osdi_log(handle, msg, LOG_LVL_FATAL);
  }

  return "�";
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
int fmt_char_idx(double val) {
  int exp = ((int)log(val)) / 3;
  int pos = exp + NUM_FMT;

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
static void *volatile osdi_file_table[OSDI_MAX_FILES];

#define OSDI_NOINLINE __attribute__((noinline))

static void *osdi_file_lookup(int fd) {
  if (fd < 1 || fd >= OSDI_MAX_FILES) {
    return NULL;
  }
  return osdi_file_table[fd];
}

// $fopen(name, mode) -> descriptor (0 on failure).
OSDI_NOINLINE int osdi_fopen(const char *name, const char *mode) {
  for (int i = 1; i < OSDI_MAX_FILES; i++) {
    if (osdi_file_table[i] == NULL) {
      void *f = fopen(name, mode);
      if (f == NULL) {
        return 0;
      }
      osdi_file_table[i] = f;
      return i;
    }
  }
  return 0; // table full
}

// Sink for the $fdisplay/$fwrite/... formatted string (see print_callback).
OSDI_NOINLINE void osdi_fputs(int fd, const char *s) {
  void *f = osdi_file_lookup(fd);
  if (f != NULL) {
    fputs(s, f);
  }
}

// $fclose(fd)
OSDI_NOINLINE int osdi_fclose(int fd) {
  void *f = osdi_file_lookup(fd);
  if (f == NULL) {
    return -1;
  }
  int r = fclose(f);
  osdi_file_table[fd] = NULL;
  return r;
}

// $fflush(fd)
OSDI_NOINLINE int osdi_fflush(int fd) {
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

static const char *volatile osdi_scan_cursor;
static int volatile osdi_scan_matches;

static int osdi_is_ws(char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v';
}

static const char *osdi_skip_ws(const char *p) {
  while (*p && osdi_is_ws(*p)) {
    p++;
  }
  return p;
}

OSDI_NOINLINE
void osdi_scanf_begin(const char *input) {
  osdi_scan_cursor = input ? input : "";
  osdi_scan_matches = 0;
}

OSDI_NOINLINE
int osdi_scan_int(void) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 0);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  return 0;
}

// Enhancement-105: base-specific integer scanners for the `%h`/`%o`/`%b`
// conversions. Unlike osdi_scan_int (strtol base 0, which infers the base from
// the input's own prefix), these force the base named by the format specifier,
// so `$sscanf("ff", "%h", x)` yields 255 and `$sscanf("17", "%o", x)` yields 15.
OSDI_NOINLINE
int osdi_scan_hex(void) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 16);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  return 0;
}

OSDI_NOINLINE
int osdi_scan_oct(void) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 8);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  return 0;
}

OSDI_NOINLINE
int osdi_scan_bin(void) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  long v = strtol(p, &end, 2);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_matches++;
    return (int)v;
  }
  osdi_scan_cursor = p;
  return 0;
}

OSDI_NOINLINE
double osdi_scan_real(void) {
  const char *p = osdi_skip_ws(osdi_scan_cursor);
  char *end;
  double v = strtod(p, &end);
  if (end != p) {
    osdi_scan_cursor = end;
    osdi_scan_matches++;
    return v;
  }
  osdi_scan_cursor = p;
  return 0.0;
}

OSDI_NOINLINE
char *osdi_scan_str(void) {
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
  if (len > 0) {
    osdi_scan_cursor = p;
    osdi_scan_matches++;
  }
  return res;
}

OSDI_NOINLINE
int osdi_scanf_count(void) { return osdi_scan_matches; }
