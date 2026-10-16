#include "polyeval.h"

double
ft_peval(double x, double *coeffs, int degree)
{
	double	y;
	int	i;

	if (!coeffs)
		return 0.0;	/* XXX Should not happen */

	y = coeffs[degree];	/* there are (degree+1) coeffs */

	for (i = degree - 1; i >= 0; i--) {
		y *= x;
		y += coeffs[i];
	}

	return y;
}


/* Enhancement-890: evaluate a polynomial ft_polyfit fitted, whose
 * coefficients are those of u = (x - frame[0]) / frame[1], at x */
double
ft_pevalf(double x, const double *frame, double *coeffs, int degree)
{
	return ft_peval((x - frame[0]) / frame[1], coeffs, degree);
}
