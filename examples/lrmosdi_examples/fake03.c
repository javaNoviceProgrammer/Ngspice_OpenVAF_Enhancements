/* Minimal but FUNCTIONAL OSDI 0.3 object, written strictly against the
 * published spec docs/osdi_v0p3.pdf (struct listings pp. 20-21, 29-30).
 * Module "res03": a 3-node resistor chain  a -- mid -- b, 500 ohm + 500 ohm,
 * i.e. 1k total with an internal node "mid".
 * A conforming OSDI 0.3 loader must simulate it as a 1k resistor and give
 * v(mid) = v(a,b)/2. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* ------- OSDI 0.3 structs exactly as published ------- */
typedef struct OsdiNodePair03 { uint32_t node_1, node_2; } OsdiNodePair03;
typedef struct OsdiJacobianEntry03 {
  OsdiNodePair03 nodes;
  uint32_t react_ptr_off;
  uint32_t flags;
} OsdiJacobianEntry03;
typedef struct OsdiNode03 {
  char *name;
  char *units;
  char *residual_units;
  uint32_t resist_residual_off;
  uint32_t react_residual_off;
  uint32_t resist_limit_rhs_off;
  uint32_t react_limit_rhs_off;
  bool is_flow;
} OsdiNode03;
typedef struct OsdiParamOpvar03 {
  char **name; uint32_t num_alias; char *description; char *units;
  uint32_t flags; uint32_t len;
} OsdiParamOpvar03;
typedef struct OsdiSimParas03 {
  char **names; double *vals; char **names_str; char **vals_str;
} OsdiSimParas03;
typedef struct OsdiSimInfo03 {
  OsdiSimParas03 paras; double abstime;
  double *prev_solve, *prev_state, *next_state; uint32_t flags;
} OsdiSimInfo03;
typedef struct OsdiInitInfo03 {
  uint32_t flags; uint32_t num_errors; void *errors;
} OsdiInitInfo03;

typedef struct OsdiDescriptor03 {
  char *name;
  uint32_t num_nodes;
  uint32_t num_terminals;
  OsdiNode03 *nodes;
  uint32_t num_jacobian_entries;
  OsdiJacobianEntry03 *jacobian_entries;
  uint32_t num_collapsible;
  OsdiNodePair03 *collapsible;
  uint32_t collapsed_offset;
  void *noise_sources;
  uint32_t num_noise_src;
  uint32_t num_params;
  uint32_t num_instance_params;
  uint32_t num_opvars;
  OsdiParamOpvar03 *param_opvar;
  uint32_t node_mapping_offset;
  uint32_t jacobian_ptr_resist_offset;
  uint32_t num_states;
  uint32_t state_idx_off;
  uint32_t bound_step_offset;
  uint32_t instance_size;
  uint32_t model_size;
  void *(*access)(void *inst, void *model, uint32_t id, uint32_t flags);
  void (*setup_model)(void *handle, void *model, OsdiSimParas03 *sp, OsdiInitInfo03 *res);
  void (*setup_instance)(void *handle, void *inst, void *model, double temperature,
                         uint32_t num_terminals, OsdiSimParas03 *sp, OsdiInitInfo03 *res);
  uint32_t (*eval)(void *handle, void *inst, void *model, OsdiSimInfo03 *info);
  void (*load_noise)(void *inst, void *model, double freq, double *nd, double *lnnd);
  void (*load_residual_resist)(void *inst, void *model, double *dst);
  void (*load_residual_react)(void *inst, void *model, double *dst);
  void (*load_limit_rhs_resist)(void *inst, void *model, double *dst);
  void (*load_limit_rhs_react)(void *inst, void *model, double *dst);
  void (*load_spice_rhs_dc)(void *inst, void *model, double *dst, double *prev_solve);
  void (*load_spice_rhs_tran)(void *inst, void *model, double *dst, double *prev_solve, double alpha);
  void (*load_jacobian_resist)(void *inst, void *model);
  void (*load_jacobian_react)(void *inst, void *model, double alpha);
  void (*load_jacobian_tran)(void *inst, void *model, double alpha);
} OsdiDescriptor03;

/* ------- instance layout (private to the model) -------
 * 0   : node_mapping  [3 x u32]  (+pad)
 * 16  : jacobian_ptr_resist [8 x double*]  = 64 bytes
 * 80  : collapsed [1 x bool] (+pad)
 * 88  : jacobian values [8 x double]
 * 152 : residual_resist [3 x double]
 * 176 : end */
#define OFF_MAP   0
#define OFF_JPTR  16
#define OFF_COLL  80
#define OFF_JVAL  88
#define OFF_RES   152
#define INST_SIZE 176
#define G2 (1.0/500.0)

static void setup_model03(void *h, void *m, OsdiSimParas03 *sp, OsdiInitInfo03 *res) {
  (void)h; (void)m; (void)sp; res->flags = 0; res->num_errors = 0; res->errors = 0;
}
static void setup_instance03(void *h, void *inst, void *m, double t, uint32_t nt,
                             OsdiSimParas03 *sp, OsdiInitInfo03 *res) {
  (void)h; (void)m; (void)t; (void)nt; (void)sp;
  res->flags = 0; res->num_errors = 0; res->errors = 0;
  *((bool *)((char *)inst + OFF_COLL)) = false;
}
static uint32_t eval03(void *h, void *inst, void *m, OsdiSimInfo03 *info) {
  (void)h; (void)m;
  char *p = (char *)inst;
  uint32_t *map = (uint32_t *)(p + OFF_MAP);
  double *jv = (double *)(p + OFF_JVAL);
  double *rr = (double *)(p + OFF_RES);
  double va = info->prev_solve[map[0]];
  double vb = info->prev_solve[map[1]];
  double vm = info->prev_solve[map[2]];
  /* branch a-mid and mid-b, each 500 ohm */
  rr[0] = (va - vm) * G2;                 /* node a residual */
  rr[1] = (vb - vm) * G2;                 /* node b residual */
  rr[2] = (vm - va) * G2 + (vm - vb) * G2; /* node mid residual */
  /* entries: (a,a) (a,mid) (b,b) (b,mid) (mid,a) (mid,b) (mid,mid) x1 spare */
  jv[0] = G2;  jv[1] = -G2;
  jv[2] = G2;  jv[3] = -G2;
  jv[4] = -G2; jv[5] = -G2; jv[6] = 2.0 * G2;
  jv[7] = 0.0;
  return 0;
}
static void load_noise03(void *i, void *m, double f, double *nd, double *lnnd) {
  (void)i; (void)m; (void)f; (void)nd; (void)lnnd;
}
static void load_residual_resist03(void *inst, void *m, double *dst) {
  (void)m;
  char *p = (char *)inst;
  uint32_t *map = (uint32_t *)(p + OFF_MAP);
  double *rr = (double *)(p + OFF_RES);
  dst[map[0]] += rr[0]; dst[map[1]] += rr[1]; dst[map[2]] += rr[2];
}
static void nop_dst(void *i, void *m, double *d) { (void)i; (void)m; (void)d; }
static void load_spice_rhs_dc03(void *i, void *m, double *d, double *ps) {
  (void)i; (void)m; (void)d; (void)ps; /* linear device: J*V - f == 0 */
}
static void load_spice_rhs_tran03(void *i, void *m, double *d, double *ps, double a) {
  (void)i; (void)m; (void)d; (void)ps; (void)a;
}
static void load_jacobian_resist03(void *inst, void *m) {
  (void)m;
  char *p = (char *)inst;
  double **jp = (double **)(p + OFF_JPTR);
  double *jv = (double *)(p + OFF_JVAL);
  for (int k = 0; k < 7; k++)
    if (jp[k]) *jp[k] += jv[k];
}
static void load_jacobian_react03(void *i, void *m, double a) { (void)i; (void)m; (void)a; }
static void load_jacobian_tran03(void *inst, void *m, double a) {
  (void)a; load_jacobian_resist03(inst, m);
}
static void *access03(void *i, void *m, uint32_t id, uint32_t f) {
  (void)i; (void)m; (void)id; (void)f; return 0;
}

static OsdiNode03 nodes03[3] = {
  {"a",   "V", "A", OFF_RES,      UINT32_MAX, UINT32_MAX, UINT32_MAX, false},
  {"b",   "V", "A", OFF_RES + 8,  UINT32_MAX, UINT32_MAX, UINT32_MAX, false},
  {"mid", "V", "A", OFF_RES + 16, UINT32_MAX, UINT32_MAX, UINT32_MAX, false},
};
static OsdiJacobianEntry03 jac03[7] = {
  {{0, 0}, UINT32_MAX, 4}, {{0, 2}, UINT32_MAX, 4},
  {{1, 1}, UINT32_MAX, 4}, {{1, 2}, UINT32_MAX, 4},
  {{2, 0}, UINT32_MAX, 4}, {{2, 1}, UINT32_MAX, 4}, {{2, 2}, UINT32_MAX, 4},
};

uint32_t OSDI_VERSION_MAJOR = 0;
uint32_t OSDI_VERSION_MINOR = 3;
uint32_t OSDI_NUM_DESCRIPTORS = 1;

OsdiDescriptor03 OSDI_DESCRIPTORS[1] = {{
  .name = "res03",
  .num_nodes = 3,
  .num_terminals = 2,
  .nodes = nodes03,
  .num_jacobian_entries = 7,
  .jacobian_entries = jac03,
  .num_collapsible = 0,
  .collapsible = 0,
  .collapsed_offset = OFF_COLL,
  .noise_sources = 0,
  .num_noise_src = 0,
  .num_params = 0,
  .num_instance_params = 0,
  .num_opvars = 0,
  .param_opvar = 0,
  .node_mapping_offset = OFF_MAP,
  .jacobian_ptr_resist_offset = OFF_JPTR,
  .num_states = 0,
  .state_idx_off = 0,
  .bound_step_offset = UINT32_MAX,
  .instance_size = INST_SIZE,
  .model_size = 8,
  .access = access03,
  .setup_model = setup_model03,
  .setup_instance = setup_instance03,
  .eval = eval03,
  .load_noise = load_noise03,
  .load_residual_resist = load_residual_resist03,
  .load_residual_react = nop_dst,
  .load_limit_rhs_resist = nop_dst,
  .load_limit_rhs_react = nop_dst,
  .load_spice_rhs_dc = load_spice_rhs_dc03,
  .load_spice_rhs_tran = load_spice_rhs_tran03,
  .load_jacobian_resist = load_jacobian_resist03,
  .load_jacobian_react = load_jacobian_react03,
  .load_jacobian_tran = load_jacobian_tran03,
}};
