/*************
 * Header file for pyplot.c (Enhancement-94)
 ************/

#ifndef ngspice_PYPLOT_H
#define ngspice_PYPLOT_H

void ft_pyplot(double *xlims, double *ylims,
        double xdel, double ydel,
        const char *filename, const char *title,
        const char *xlabel, const char *ylabel,
        GRIDTYPE gridtype, PLOTTYPE plottype,
        struct dvec *vecs, bool hist);

/* Enhancement-208: render the folded eye (eye_wave/eye_t + scalar metrics left
   in the current plot by the `eye` command) as a persistence-style 2-D-histogram
   eye diagram via matplotlib, honouring the same pyplot_* settings as ft_pyplot. */
void ft_pyplot_eye(const char *filename, const char *expr);

#endif
