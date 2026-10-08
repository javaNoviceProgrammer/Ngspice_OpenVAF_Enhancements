#include "ngspice/ngspice.h"
#include "ngspice/dvec.h"
#include "ngspice/plot.h"
#include "ngspice/fteext.h"

#include "ngspice/dstring.h"    /* Enhancement-812 */
#include "pvec.h"
#include "dimens.h"


/* Enhancement-812 (hunt 2026-10-08 F21): the line is built in a growing
 * string. It was sprintf'd into a 512-byte stack buffer with the vector's
 * name, and `display` of a vector named by a ~470-character node or device
 * (a noise contribution `onoise_<device>_thermal` included, and `load`,
 * which lists what it reads through here) overran it: a fortified abort
 * every time. The scale's name and the colour went through the same buffer. */
void
pvec(struct dvec *d)
{
    char buf3[BSIZE_SP];
    DS_CREATE(line, 128);

    ds_cat_printf(&line, "    %-20s: %s, %s, %d long",
                  d->v_name,
                  ft_typenames(d->v_type),
                  isreal(d) ? "real" : "complex",
                  d->v_length);

    if (d->v_flags & VF_MINGIVEN)
        ds_cat_printf(&line, ", min = %g", d->v_minsignal);

    if (d->v_flags & VF_MAXGIVEN)
        ds_cat_printf(&line, ", max = %g", d->v_maxsignal);

    switch (d->v_gridtype) {
    case GRID_LOGLOG:
        ds_cat_str(&line, ", grid = loglog");
        break;

    case GRID_XLOG:
        ds_cat_str(&line, ", grid = xlog");
        break;

    case GRID_YLOG:
        ds_cat_str(&line, ", grid = ylog");
        break;

    case GRID_POLAR:
        ds_cat_str(&line, ", grid = polar");
        break;

    case GRID_SMITH:
        ds_cat_str(&line, ", grid = smith (xformed)");
        break;

    case GRID_SMITHGRID:
        ds_cat_str(&line, ", grid = smithgrid (not xformed)");
        break;

    default: /* va: GRID_NONE or GRID_LIN */
        break;
    }

    switch (d->v_plottype) {

    case PLOT_COMB:
        ds_cat_str(&line, ", plot = comb");
        break;

    case PLOT_POINT:
        ds_cat_str(&line, ", plot = point");
        break;

    default:  /* va: PLOT_LIN, */
        break;
    }

    if (d->v_defcolor)
        ds_cat_printf(&line, ", color = %s", d->v_defcolor);

    if (d->v_scale)
        ds_cat_printf(&line, ", scale = %s", d->v_scale->v_name);

    if (d->v_numdims > 1) {
        dimstring(d->v_dims, d->v_numdims, buf3);
        ds_cat_printf(&line, ", dims = [%s]", buf3);
    }

    if (d->v_plot->pl_scale == d)
        ds_cat_str(&line, " [default scale]\n");
    else
        ds_cat_str(&line, "\n");

    out_send(ds_get_buf(&line));
    ds_free(&line);
}
