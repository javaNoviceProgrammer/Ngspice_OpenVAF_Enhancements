/* Enhancement-200: Touchstone (.sNp) -> Verilog-A converter + `pre_snp` command. */
#ifndef SNP2VA_H
#define SNP2VA_H
#include "ngspice/wordlist.h"
/* Convert a Touchstone file to a Verilog-A n-port model. Returns 0 on success;
 * msg gets a one-line status/error. (No ngspice deps in the converter core.) */
int snp2va_convert(const char *snpfile, const char *vafile, const char *module,
                   char *msg, int msglen);
/* Enhancement-242: same parse+vector-fit, emitted as a native `.nport` fit file
 * (for the built-in n-port device) instead of Verilog-A. */
int snp2nport_convert(const char *snpfile, const char *nportfile,
                      char *msg, int msglen);
/* Enhancement-745: the fit's acceptance limit (rms relative error of the worst
 * element); x < 0 restores the default, 0 removes the limit. */
void snp2va_set_maxerr(double x);
double snp2va_maxerr_default(void);
double snp2va_last_err(void);       /* the last fit's error, after a conversion */
void com_pre_snp(wordlist *wl);
#endif
