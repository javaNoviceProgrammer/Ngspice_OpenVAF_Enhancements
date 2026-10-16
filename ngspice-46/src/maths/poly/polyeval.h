#ifndef ngspice_POLYEVAL_H
#define ngspice_POLYEVAL_H

double ft_peval(double x, double *coeffs, int degree);
double ft_pevalf(double x, const double *frame, double *coeffs, int degree);

#endif
