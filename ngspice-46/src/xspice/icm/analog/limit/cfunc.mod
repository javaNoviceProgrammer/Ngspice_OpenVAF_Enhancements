/*.......1.........2.........3.........4.........5.........6.........7.........8
================================================================================

FILE limit/cfunc.mod

Public Domain

Georgia Tech Research Corporation
Atlanta, Georgia 30332
PROJECT A-8503-405
               

AUTHORS                      

    6 Jun 1991     Jeffrey P. Murray


MODIFICATIONS   

     2 Oct 1991    Jeffrey P. Murray
                                   

SUMMARY

    This file contains the model-specific routines used to
    functionally describe the limit code model.


INTERFACES       

    FILE                 ROUTINE CALLED     

    CMutil.c             void cm_smooth_corner(); 


REFERENCED FILES

    Inputs from and outputs to ARGS structure.
                     

NON-STANDARD FEATURES

    NONE

===============================================================================*/

/*=== INCLUDE FILES ====================*/


                                      

/*=== CONSTANTS ========================*/




/*=== MACROS ===========================*/



  
/*=== LOCAL VARIABLES & TYPEDEFS =======*/                         


    
           
/*=== FUNCTION PROTOTYPE DEFINITIONS ===*/




                   
/*==============================================================================

FUNCTION void cm_limit()

AUTHORS                      

     2 Oct 1991     Jeffrey P. Murray

MODIFICATIONS   

    NONE

SUMMARY

    This function implements the limit code model.

INTERFACES       

    FILE                 ROUTINE CALLED     

    CMutil.c             void cm_smooth_corner(); 


RETURNED VALUE
    
    Returns inputs and outputs via ARGS structure.

GLOBAL VARIABLES
    
    NONE

NON-STANDARD FEATURES

    NONE

==============================================================================*/

/*=== CM_LIMIT ROUTINE ===*/

void cm_limit(ARGS)  /* structure holding parms, 
                                       inputs, outputs, etc.     */
{
    double out_lower_limit;   /* output lower limit */
	double out_upper_limit;   /* output upper limit */
	double limit_range;       /* upper and lower limit smoothing range */
    /* Enhancement-468 */
    static char *limit_negative_error =
        "\n**** ERROR ****\n* LIMIT limit_range is negative: it would widen the linear\n"
        "* region past the limits and stop limiting. Clamped to zero. *\n";
    static char *limit_order_error =
        "\n**** ERROR ****\n* LIMIT out_upper_limit is below out_lower_limit. *\n";
    /* Enhancement-485 */
    static char *limit_range_error =
        "\n**** ERROR ****\n* LIMIT limit_range leaves no linear region between the\n"
        "* limits; clamped to half the limit span. *\n";
	double gain;              /* gain */
    double threshold_upper;   /* value above which smoothing takes place */
	double threshold_lower;   /* value below which smoothing takes place */
	double out;               /* output */
	double limited_out;       /* limited output value */
    double out_partial;       /* partial of the output wrt input */
    
    Mif_Complex_t ac_gain;



    /* Retrieve frequently used parameters... */

    out_lower_limit = PARAM(out_lower_limit);
    out_upper_limit = PARAM(out_upper_limit);
    limit_range = PARAM(limit_range);
    gain = PARAM(gain);


    if (PARAM(fraction) == MIF_TRUE)     /* Set range to absolute value */
        limit_range = limit_range * 
              (out_upper_limit - out_lower_limit);



    /* Enhancement-468: check the range, as the CLIMIT sibling already does.
     *
     * A NEGATIVE limit_range widens the linear region instead of narrowing it:
     * with out_lower_limit=-1, out_upper_limit=1 and limit_range=-5 the
     * thresholds became -6 and +6, so an input of 1.5 passed straight through
     * and the block STOPPED LIMITING -- silently, while still declaring an
     * upper limit of 1. Ranges of 0.01, 0.1, 0 and -0.01 all clamp correctly,
     * so it was silent on everything except a value large enough to swallow
     * the limits. An INVERTED pair (lower above upper) was accepted too.
     *
     * CLIMIT tests its linear range and refuses; LIMIT tested nothing. A
     * negative range is clamped to zero -- hard limiting at the bounds the
     * deck asked for, the only reading that still honours them -- and both
     * faults are reported with CLIMIT's message convention, whose INIT/TIME
     * guard keeps it quiet on the first pass when every input is still zero. */
    /* Enhancement-480: report these ONCE, at INIT, in every analysis.
     *
     * Both faults are properties of the model card and cannot change during a
     * run, but the guard they carried -- borrowed from CLIMIT, where it keeps a
     * SIGNAL-dependent message quiet while the inputs are still zero -- tests
     * `TIME != 0`, which is never true in an `op` or a `dc` sweep. So a limiter
     * whose limits were written the wrong way round said nothing at all in
     * those analyses (`out_lower_limit=5 out_upper_limit=-5` produced the
     * transfer curve 5, 5, 5, 5, -5 in silence), and said it 214 times in a
     * transient -- once per timestep. Firing at INIT gives one message per
     * instance, wherever the instance is used. */
    if (limit_range < 0.0) {
        if (INIT == 1)
            cm_message_send(limit_negative_error);
        limit_range = 0.0;
    }
    if (out_upper_limit < out_lower_limit) {
        if (INIT == 1)
            cm_message_send(limit_order_error);
    }

    /* Enhancement-485: a limit_range wider than HALF the limit span crosses the
     * two thresholds below, and the parabolic smoothing then runs over an
     * inverted region and carries the output straight past the limits this block
     * exists to enforce: with out_lower_limit=-1, out_upper_limit=1 and an input
     * of 0.5, limit_range=5 gave 1.1125, limit_range=99 gave 24.5057 and
     * limit_range=1e6 gave 249999.75 -- unbounded, and silent.
     *
     * E-468 added the negative-range and inverted-limits checks above, modelled
     * on CLIMIT ("as the CLIMIT sibling already does"). It did not port CLIMIT's
     * OWN guard, which is exactly this one: CLIMIT computes
     * `linear_range = threshold_upper - threshold_lower` and refuses when it goes
     * negative. `limit` never computed linear_range at all, and neither do `int`
     * or `d_dt`, which carry the same parameter pair.
     *
     * Clamp rather than refuse: at half the span the thresholds coincide, which
     * is hard limiting exactly at the bounds the deck asked for -- the only
     * reading that still honours them. Reported at INIT, once per instance,
     * following E-480. */
    {
        double half_span = 0.5 * (out_upper_limit - out_lower_limit);
        if (half_span > 0.0 && limit_range > half_span) {
            if (INIT == 1)
                cm_message_send(limit_range_error);
            limit_range = half_span;
        }
    }

    threshold_upper = out_upper_limit -   /* Set Upper Threshold */
                         limit_range;

    threshold_lower = out_lower_limit +   /* Set Lower Threshold */
                         limit_range;
                              


    /* Compute Un-Limited Output */

    out = gain * (PARAM(in_offset) + INPUT(in)); 



    if (out < threshold_lower) {       /* Limit Out @ Lower Bound */

        if (out > (out_lower_limit - limit_range)) { /* Parabolic */
            cm_smooth_corner(out,out_lower_limit,out_lower_limit,
                        limit_range,0.0,1.0,&limited_out,
                        &out_partial);               
            out_partial = gain * out_partial;   
        }
        else {                             /* Hard-Limited Region */
            limited_out = out_lower_limit;
            out_partial = 0.0;
        }    
    }
    else {
        if (out > threshold_upper) {       /* Limit Out @ Upper Bound */

            if (out < (out_upper_limit + limit_range)) { /* Parabolic */
                cm_smooth_corner(out,out_upper_limit,out_upper_limit,
                            limit_range,1.0,0.0,&limited_out,
                            &out_partial);               
                out_partial = gain * out_partial; 
            }
            else {                             /* Hard-Limited Region */
                limited_out = out_upper_limit;
                out_partial = 0.0;
            }
        }
        else {               /* No Limiting Needed */
            limited_out = out;
            out_partial = gain;
        }
    }

    if (ANALYSIS != MIF_AC) {     /* DC & Transient Analyses */

        OUTPUT(out) = limited_out;
        PARTIAL(out,in) = out_partial;

    }
    else {                        /* AC Analysis */
        ac_gain.real = out_partial;
        ac_gain.imag= 0.0;
        AC_GAIN(out,in) = ac_gain;

    }
}
