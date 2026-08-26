/*.......1.........2.........3.........4.........5.........6.........7.........8
================================================================================

FILE int/cfunc.mod

Public Domain

Georgia Tech Research Corporation
Atlanta, Georgia 30332
PROJECT A-8503-405
               

AUTHORS                      

    6 Nov 1991     Jeffrey P. Murray


MODIFICATIONS   

     2 Oct 1991    Jeffrey P. Murray
                                   

SUMMARY

    This file contains the model-specific routines used to
    functionally describe the int code model.


INTERFACES       

    FILE                 ROUTINE CALLED     

    CMutil.c             void cm_smooth_corner(); 

    CM.c                 void *cm_analog_alloc()
                         void *cm_analog_get_ptr()
                         int  cm_analog_integrate()


REFERENCED FILES

    Inputs from and outputs to ARGS structure.
                     

NON-STANDARD FEATURES

    NONE

===============================================================================*/

/*=== INCLUDE FILES ====================*/

#include "int.h"   

                                      

/*=== CONSTANTS ========================*/




/*=== MACROS ===========================*/



  
/*=== LOCAL VARIABLES & TYPEDEFS =======*/                         


    
           
/*=== FUNCTION PROTOTYPE DEFINITIONS ===*/




                   
/*==============================================================================

FUNCTION void cm_int()

AUTHORS                      

     2 Oct 1991     Jeffrey P. Murray

MODIFICATIONS   

    NONE

SUMMARY

    This function implements the int code model.

INTERFACES       

    FILE                 ROUTINE CALLED     

    CMutil.c             void cm_smooth_corner(); 

    CM.c                 void *cm_analog_alloc()
                         void *cm_analog_get_ptr()
                         int  cm_analog_integrate()

RETURNED VALUE
    
    Returns inputs and outputs via ARGS structure.

GLOBAL VARIABLES
    
    NONE

NON-STANDARD FEATURES

    NONE

==============================================================================*/

/*=== CM_INT ROUTINE ===*/

void cm_int(ARGS)  /* structure holding parms, 
                                       inputs, outputs, etc.     */
{
    /* Enhancement-485: reported once at INIT when limit_range is wider than
     * half the limit span; see the clamp below. */
    static char *e485_range_error =
        "\n**** ERROR ****\n* limit_range leaves no linear region between the limits;\n"
        "* clamped to half the limit span. *\n";

    double        *out, /* current output   */
                   *in, /* input        */
             in_offset, /* input offset */
                  gain, /* gain parameter   */
       out_lower_limit, /* output lower limit   */
       out_upper_limit, /* output upper limit   */
           limit_range, /* range of output below out_upper_limit
                           and above out_lower_limit within which
                           smoothing will take place    */
                out_ic, /* output initial condition - initial output value  */
              pout_pin, /* partial derivative of output w.r.t. input    */
             pout_gain; /* temporary storage variable for partial
                           value returned by smoothing function
                           (subsequently multiplied by pout_pin)    */

    Mif_Complex_t ac_gain;  /* AC gain  */
                                                   


    /** Retrieve frequently used parameters (used by all analyses)... **/

    gain = PARAM(gain);
                                     


    if (ANALYSIS != MIF_AC) {     /**** DC & Transient Analyses ****/

        /** Retrieve frequently used parameters... **/

        in_offset = PARAM(in_offset);
        out_lower_limit = PARAM(out_lower_limit);
        out_upper_limit = PARAM(out_upper_limit);                         
        limit_range = PARAM(limit_range);

        /* Enhancement-485: the smoothing regions below are
         * [out_lower_limit +/- limit_range] and [out_upper_limit +/- limit_range].
         * Once 2*limit_range exceeds the limit span they OVERLAP and the smoothed
         * output leaves the limits entirely -- with limits of +/-1 and a ramp
         * input, limit_range=99 drove `int` to 95.04 and `d_dt` to 24.25, in
         * silence. Clamp to half the span (regions meeting at the midpoint =
         * hard limiting at the declared bounds) and say so once. Same repair as
         * `limit` and the shared cm_climit_fcn helper. */
        {
            double e485_half = 0.5 * (out_upper_limit - out_lower_limit);
            if (e485_half > 0.0 && limit_range > e485_half) {
                if (INIT == 1)
                    cm_message_send(e485_range_error);
                limit_range = e485_half;
            }
        }
        out_ic = PARAM(out_ic);



        /** Test for INIT; if so, allocate storage, otherwise, retrieve
                                   previous timepoint input value...     **/

        if (INIT==1) {  /* First pass...allocate storage for previous value.   */
    
            cm_analog_alloc(INT1,sizeof(double));   
            cm_analog_alloc(INT2,sizeof(double));   
        }
        /* retrieve previous value */
    
            in = (double *) cm_analog_get_ptr(INT1,0);  /* Set out pointer to input storage location */
            out = (double *) cm_analog_get_ptr(INT2,0);  /* Set out pointer to output storage location */
                                  

        /*** Read input value for current time, and calculate pseudo-input ***/
        /***    which includes input offset and gain....                   ***/

        *in = gain*(INPUT(in)+in_offset);

        /*** Test to see if this is the first timepoint calculation... ***/
        /***   this would imply that TIME equals zero.                 ***/
    
        if ( 0.0 == TIME ) {     /*** Test to see if this is the first ***/
                                 /***    timepoint calculation...if    ***/
            *out = out_ic;       /***    so, return out_ic.            ***/
            pout_pin = 0.0;
        }
        else {               /*** Calculate value of integral.... ***/
            cm_analog_integrate(*in,out,&pout_pin);
        }


        /*** Smooth output if it is within limit_range of 
                 out_lower_limit or out_upper_limit.          ***/
                                                                  
        if (*out < (out_lower_limit - limit_range)) {  /* At lower limit. */ 
            *out = out_lower_limit;
            pout_pin = 0.0;
        }
        else {
            if (*out < (out_lower_limit + limit_range)) {  /* Lower smoothing range */
                cm_smooth_corner(*out,out_lower_limit,out_lower_limit,limit_range,
                            0.0,1.0,out,&pout_gain);
                pout_pin = pout_pin * pout_gain;
            }
            else {
                if (*out > (out_upper_limit + limit_range))  {  /* At upper limit */
                    *out = out_upper_limit;
                    pout_pin = 0.0;
                }
                else { 
                    if (*out > (out_upper_limit - limit_range))  {  /* Upper smoothing region */
                        cm_smooth_corner(*out,out_upper_limit,out_upper_limit,limit_range,
                                    1.0,0.0,out,&pout_gain); 
                        pout_pin = pout_pin * pout_gain;
                    }
                }   
            }
        }




        /** Output values for DC & Transient **/

        OUTPUT(out) = *out;          
        PARTIAL(out,in) = pout_pin; 

    }

    else {                    /**** AC Analysis...output (0.0,gain/s) ****/
        ac_gain.real = 0.0;
        ac_gain.imag = -gain / RAD_FREQ;
        AC_GAIN(out,in) = ac_gain;
    }
}





