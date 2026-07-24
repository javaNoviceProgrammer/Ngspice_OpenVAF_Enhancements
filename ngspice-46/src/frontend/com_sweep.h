/* Enhancement-146: the universal `sweep` command. */
#ifndef COM_SWEEP_H
#define COM_SWEEP_H
void com_sweep(wordlist *wl);

/* Enhancement-320/321/322: the `.param` fast-sweep engine, shared with the
 * optimizer (com_optimize.c). sw_fp_build captures the swept `.param` names'
 * dependent device/model values (top-level and subckt-internal) and returns 1
 * if every use is safely in-place-able (armed); sw_fp_apply overrides the params
 * in the numparam table and pushes the re-evaluated values into the live circuit
 * without a reset; sw_fp_free drops the capture. */
int  sw_fp_build(char *const *names, int n);
void sw_fp_apply(char *const *names, const double *vals, int n);
void sw_fp_free(void);
#endif
