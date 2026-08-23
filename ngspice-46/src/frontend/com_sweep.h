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
/* Enhancement-472: ask CKTdoJob to keep the circuit standing for the next
 * analysis instead of tearing it down and building it again (Enhancement-471).
 * Only ever a REQUEST -- CKTdoJob re-decides node collapse and rebuilds for
 * real if the topology moved, and declines outright for any device type whose
 * collapse it cannot re-check. The caller's job is only to ask when nothing has
 * re-sourced the deck since the last analysis, and not after one that failed.
 * Shared with the optimizer, which has its own no-reset evaluation paths. */
void sw_request_reuse(void);
int  sw_reuse_report(int *kept, int *rebuilt);

int  sw_fp_build(char *const *names, int n);
void sw_fp_apply(char *const *names, const double *vals, int n);
void sw_fp_free(void);
#endif
