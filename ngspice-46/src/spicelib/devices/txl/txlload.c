/**********
Copyright 1992 Regents of the University of California.	 All rights
reserved.
Author:	1992 Charles Hough
**********/


#include "ngspice/ngspice.h"
#include "txldefs.h"
#include "ngspice/sperror.h"
#include "ngspice/suffix.h"


static double ratio[MAX_CP_TX_LINES];
static int update_cnv_txl(TXLine*, double);
static VI_list_txl *new_vi_txl(void);
static void free_vi_txl(VI_list_txl*);
static int add_new_vi_txl(TXLinstance*,	CKTcircuit*, long long);
static int get_pvs_vi_txl(long long, long long, TXLine*, double*, double*, double*,	double*, double*, 
			  double*, double*, double*);
static int right_consts_txl(TXLine*, long long, long long, double, double, int, int, CKTcircuit*);
static int update_delayed_cnv_txl(TXLine*, double);
static int expC(double,	double,	double, double*,	double*);
static void copy_tx(TXLine *, TXLine *);

/* Enhancement-906: the exact weights of one step of a convolution with the
 * kernel c*exp(x*tau), its input linear over the step h from vold to vnew:
 * the step adds (c/x)*(vnew*wn + vold*wo), with z = x*h,
 * wn = (e^z - 1 - z)/z and wo = (e^z - 1) - wn. update_cnv_txl advances the
 * characteristic admittance's history with exactly this integral once a
 * point is accepted, while the load formed the same step, and the delayed
 * h2/h3 steps, by the trapezoid rule. The two disagree by (x h)^2/12 a step,
 * and on a lossy line driven in its RC regime the disagreement fed back: a
 * 200 m line with R*length = 1.2 Zc, at a tenth of R/(2 pi L), grew from
 * 0.19 V to -2.6 V on a 1 V source in 3 ms where the exact line is 0.25 V. */
static void
txl_w(double x, double h, double *wn, double *wo)
{
   double z = x * h, em1 = expm1(z), w;

   if (fabs(z) < 1e-3)
      w = z * (0.5 + z * (1.0/6.0 + z * (1.0/24.0 + z / 120.0)));
   else
      w = (em1 - z) / z;
   *wn = w;
   *wo = em1 - w;
}

/* the same for a complex pole pair, x = xr + j xi */
static void
txl_wc(double xr, double xi, double h, double *wnr, double *wni, double *wor, double *woi)
{
   double zr = xr * h, zi = xi * h, sh = sin(0.5 * zi);
   double emr = expm1(zr) * cos(zi) - 2.0 * sh * sh;
   double emi = exp(zr) * sin(zi);
   double wr, wi;

   if (hypot(zr, zi) < 1e-3) {
      static const double coef[3] = {1.0/24.0, 1.0/6.0, 0.5};
      double pr = 1.0/120.0, pi = 0.0, t;
      int k;
      for (k = 0; k < 3; k++) {
         t = pr * zr - pi * zi; pi = pr * zi + pi * zr; pr = t + coef[k];
      }
      wr = pr * zr - pi * zi;
      wi = pr * zi + pi * zr;
   } else {
      double nr = emr - zr, ni = emi - zi, d = zr * zr + zi * zi;
      wr = (nr * zr + ni * zi) / d;
      wi = (ni * zr - nr * zi) / d;
   }
   *wnr = wr; *wni = wi;
   *wor = emr - wr; *woi = emi - wi;
}

/* one exact step of a complex term: cnv = cnv*e + (c/x)*(vnew*wn + vold*wo) */
static void
txl_cstep(double *cr, double *ci, double c_r, double c_i, double x_r, double x_i,
          double h, double vnew, double vold)
{
   double er, ei, wnr, wni, wor, woi, d, tr, ti, ur, ui, a, b;

   expC(x_r, x_i, h, &er, &ei);
   txl_wc(x_r, x_i, h, &wnr, &wni, &wor, &woi);
   d = x_r * x_r + x_i * x_i;
   tr = (c_r * x_r + c_i * x_i) / d;
   ti = (c_i * x_r - c_r * x_i) / d;
   ur = vnew * wnr + vold * wor;
   ui = vnew * wni + vold * woi;
   a = *cr * er - *ci * ei;
   b = *cr * ei + *ci * er;
   *cr = a + tr * ur - ti * ui;
   *ci = b + tr * ui + ti * ur;
}

/*ARGSUSED*/
int
TXLload(GENmodel *inModel, CKTcircuit *ckt)
{
	TXLmodel *model = (TXLmodel *)inModel;
	TXLinstance *here;
	TXLine *tx, *tx2;
	int k, l;
	long long time, time2;   /* Enhancement-907: picoseconds; an int froze the line at 2.147 ms */
	double h, h1, f;
	long long hint;
	double hf;
	NODE *nd;
	double v, v1, g;
	int cond1;
	CKTnode	*node;
	VI_list_txl *vi, *vi_before;
	int i;
	long long before, delta;

	double gmin;	 /* dc solution	*/

	/* debug 
	printf("before txlload\n");
	SMPprint(ckt->CKTmatrix, NULL);
	*/

	h = ckt->CKTdelta;
	h1 = 0.5 * h;
	time2 =	(long long) (ckt->CKTtime * 1e12);
	hint = (long long)(h * 1e12);
	hf = h * 1e12;
	time = (long long) ((ckt->CKTtime - ckt->CKTdelta) * 1e12);

	cond1= ckt->CKTmode & MODEDC;

	gmin = 0.1 * ckt->CKTgmin;     /* dc solution */

	for( ; model !=	NULL; model = TXLnextModel(model)) {
		for (here = TXLinstances(model); here != NULL ; 
			here=TXLnextInstance(here)) { 

			tx = here->txline;

			*here->TXLposPosPtr += gmin; /* dc solution */
			*here->TXLnegNegPtr += gmin;
			*here->TXLnegPosPtr += gmin;
			*here->TXLposNegPtr += gmin;

			if (cond1 || tx->vi_head == NULL) continue;

			if (time < tx->vi_tail->time) {
				time = tx->vi_tail->time;
				hint = time2 - time;
			}

			vi_before = tx->vi_tail;
			before = tx->vi_tail->time;

			if (time > tx->vi_tail->time) {

				copy_tx(tx, here->txline2);
				add_new_vi_txl(here, ckt, time);

				delta =	time - before;

				nd = tx->in_node;
				v = vi_before->v_i;
				nd->V =	tx->vi_tail->v_i;
				v1 = nd->V;
				nd->dv = (v1 - v) / (double) delta;

				nd = tx->out_node;
				v = vi_before->v_o;
				v1 = nd->V = tx->vi_tail->v_o;
				nd->dv = (v1 - v) / (double) delta;

				if (tx->lsl) continue;
				update_cnv_txl(tx, (double) delta);
				if (tx->ext) update_delayed_cnv_txl(tx,	(double) delta);
			}
		}
	}

    model = (TXLmodel *)inModel;
    for( ; model != NULL; model	= TXLnextModel(model))	{
	for (here = TXLinstances(model); here != NULL ;	
			here=TXLnextInstance(here)) { 

			tx = here->txline;
			tx2 = here->txline2;

			if (!tx->lsl &&	hf > tx->taul) {

				fprintf(stderr, "your time step is too large for TXL tau.\n");
/*				fprintf(stderr, "please decrease max time	step in	.tran card.\n");
				fprintf(stderr, ".tran tstep tstop tstart	tmax.\n");
				fprintf(stderr, "make tmax smaller than %e and try again.\n",
				tx->taul * 1e-12);
				return (1111);
*/
				fprintf(stderr,	"tmax is now set to	%e.\n", 0.9 * tx->taul * 1e-12);
				ckt->CKTmaxStep = 0.9 * tx->taul * 1e-12;

			}

			if (cond1) {
				if (here->TXLlengthgiven) 
					g = model->R * here->TXLlength;
				else g = model->R * TXLmodPtr(here)->length;
				*(here->TXLposIbr1Ptr) += 1.0;
				*(here->TXLnegIbr2Ptr) += 1.0;
				*(here->TXLibr1Ibr1Ptr)	+= 1.0;
				*(here->TXLibr1Ibr2Ptr)	+= 1.0;
				*(here->TXLibr2PosPtr) += 1.0;
				*(here->TXLibr2NegPtr) -= 1.0;
				*(here->TXLibr2Ibr1Ptr)	-= g;

				continue;

			}

			/* dc setup */
			if (here->TXLdcGiven ==	0 && !cond1) {
				nd = tx->in_node;
				for (node = ckt->CKTnodes;node;	node = node->next) {
					if (strcmp(nd->name->id, node->name) ==	0) {
						tx->dc1	= tx2->dc1 = ckt->CKTrhsOld[node->number]; 
						nd->V =	tx->dc1;
						break;
					}
				}
				nd = tx->out_node;
				for (node = ckt->CKTnodes;node;	node = node->next) {
					if (strcmp(nd->name->id, node->name) ==	0) {
						tx->dc2	= tx2->dc2 = ckt->CKTrhsOld[node->number]; 
						nd->V =	tx->dc2;
						break;
					}
				}
				here->TXLdcGiven = 1;

				vi = new_vi_txl();
				vi->time = 0;

				vi->i_i	= *(ckt->CKTrhsOld + here->TXLibr1);
				vi->i_o	= *(ckt->CKTrhsOld + here->TXLibr2);

				vi->v_i	= tx->dc1;
				vi->v_o	= tx->dc2;

				for (i = 0; i <	3; i++)	{
					tx->h1_term[i].cnv_i = 
					   - tx->dc1 * tx->h1_term[i].c	/ tx->h1_term[i].x;
					tx->h1_term[i].cnv_o = 
					   - tx->dc2 * tx->h1_term[i].c	/ tx->h1_term[i].x;
				}
				/* Enhancement-904: the currents the operating point
				 * carries. The current history started at 0 while
				 * the voltages started at their dc values, so a line
				 * carrying dc current began its transient by
				 * dropping the far end to a third of its value. */
				tx->idc1 = tx2->idc1 = vi->i_i;
				tx->idc2 = tx2->idc2 = vi->i_o;
				for (i = 0; i <	3; i++)	{
					tx->h2_term[i].cnv_i =
				    - tx->idc1 * tx->h2_term[i].c / tx->h2_term[i].x;
					tx->h2_term[i].cnv_o =
				    - tx->idc2 * tx->h2_term[i].c / tx->h2_term[i].x;
				}
				for (i = 0; i <	6; i++)	{
					tx->h3_term[i].cnv_i = 
				    - tx->dc1 *	tx->h3_term[i].c / tx->h3_term[i].x;
					tx->h3_term[i].cnv_o = 
				    - tx->dc2 *	tx->h3_term[i].c / tx->h3_term[i].x;
				}
				if (tx->ifImg) {
				    /* Enhancement-904: a complex pair's dc state is
				     * -v*c/x in complex arithmetic, its real and
				     * imaginary parts in the two terms */
				    double d, a, b;
				    d = tx->h3_term[4].x * tx->h3_term[4].x + tx->h3_term[5].x * tx->h3_term[5].x;
				    a = (tx->h3_term[4].c * tx->h3_term[4].x + tx->h3_term[5].c * tx->h3_term[5].x) / d;
				    b = (tx->h3_term[5].c * tx->h3_term[4].x - tx->h3_term[4].c * tx->h3_term[5].x) / d;
				    tx->h3_term[4].cnv_i = - tx->dc1 * a;
				    tx->h3_term[5].cnv_i = - tx->dc1 * b;
				    tx->h3_term[4].cnv_o = - tx->dc2 * a;
				    tx->h3_term[5].cnv_o = - tx->dc2 * b;
				    d = tx->h2_term[1].x * tx->h2_term[1].x + tx->h2_term[2].x * tx->h2_term[2].x;
				    a = (tx->h2_term[1].c * tx->h2_term[1].x + tx->h2_term[2].c * tx->h2_term[2].x) / d;
				    b = (tx->h2_term[2].c * tx->h2_term[1].x - tx->h2_term[1].c * tx->h2_term[2].x) / d;
				    tx->h2_term[1].cnv_i = - tx->idc1 * a;
				    tx->h2_term[2].cnv_i = - tx->idc1 * b;
				    tx->h2_term[1].cnv_o = - tx->idc2 * a;
				    tx->h2_term[2].cnv_o = - tx->idc2 * b;
				}
				vi->next = NULL;
				tx->vi_tail = vi;
				tx->vi_head = vi;
				here->txline2->vi_tail = vi;
				here->txline2->vi_head = vi;

			}

			/* change 6,6	 1/18/93 
			*(here->TXLibr1Ibr1Ptr)	-= 1.0;	
			*(here->TXLibr2Ibr2Ptr)	-= 1.0;
	    *(here->TXLposIbr1Ptr) += 1.0;
	    *(here->TXLnegIbr2Ptr) += 1.0;
	    *(here->TXLibr1PosPtr) += tx->sqtCdL + h1 *	tx->h1C;
			*(here->TXLibr2NegPtr) += tx->sqtCdL + h1 * tx->h1C;
			*/
			*(here->TXLibr1Ibr1Ptr)	= -1.0;	
			*(here->TXLibr2Ibr2Ptr)	= -1.0;
	    *(here->TXLposIbr1Ptr) = 1.0;
	    *(here->TXLnegIbr2Ptr) = 1.0;
	    {
		double yn = 0.0, wn, wo;
		if (!tx->lsl)
		    for (i = 0; i < 3; i++) {
			txl_w(tx->h1_term[i].x, h, &wn, &wo);
			yn += tx->h1_term[i].c / tx->h1_term[i].x * wn;
		    }
		*(here->TXLibr1PosPtr) = tx->sqtCdL + yn;
		*(here->TXLibr2NegPtr) = tx->sqtCdL + yn;
	    }

			k = here->TXLibr1;
			l = here->TXLibr2;

			copy_tx(tx2, tx);

			if (right_consts_txl(tx2, time,	time2, h, h1, k, l, ckt)) {
				if (tx->lsl) {
					f = ratio[0] * tx->h3_aten;
					*(here->TXLibr1NegPtr) = -f;
					*(here->TXLibr2PosPtr) = -f;
					f = ratio[0] * tx->h2_aten;
					*(here->TXLibr1Ibr2Ptr)	= -f;
					*(here->TXLibr2Ibr1Ptr)	= -f;
				}
				else {
					tx->ext	= 1;
					tx->ratio = ratio[0];
					if (ratio[0] > 0.0) {
						f = ratio[0] * (h1 * (tx->h3_term[0].c 
							+ tx->h3_term[1].c + tx->h3_term[2].c 
							+ tx->h3_term[3].c + tx->h3_term[4].c
							+ tx->h3_term[5].c ) + tx->h3_aten);
						*(here->TXLibr1NegPtr) = -f;
						*(here->TXLibr2PosPtr) = -f;
						f = ratio[0] * (h1 * ( tx->h2_term[0].c	
							+ tx->h2_term[1].c + tx->h2_term[2].c )	
							+ tx->h2_aten);
						*(here->TXLibr1Ibr2Ptr)	= -f;
						*(here->TXLibr2Ibr1Ptr)	= -f;
					}
				}
			} 
			else tx->ext = 0;
	}
    }

	if (cond1) return (OK);

	/* debug 
	printf("after txlload\n");
	SMPprint(ckt->CKTmatrix, NULL);
	*/

    return(OK);
}

static void 
copy_tx(TXLine *new, TXLine *old)
{
	int i;
	VI_list_txl *temp;

	new->lsl = old->lsl;
	new->ext = old->ext;
	new->ratio = old->ratio;
	new->taul = old->taul;
	new->sqtCdL = old->sqtCdL;
	new->h2_aten = old->h2_aten;
	new->h3_aten = old->h3_aten;
	new->h1C = old->h1C;
	for (i=	0; i < 3; i++) {
		new->h1e[i] = old->h1e[i];

		new->h1_term[i].c = old->h1_term[i].c;
		new->h1_term[i].x = old->h1_term[i].x;
		new->h1_term[i].cnv_i =	old->h1_term[i].cnv_i;
		new->h1_term[i].cnv_o =	old->h1_term[i].cnv_o;

		new->h2_term[i].c = old->h2_term[i].c;
		new->h2_term[i].x = old->h2_term[i].x;
		new->h2_term[i].cnv_i =	old->h2_term[i].cnv_i;
		new->h2_term[i].cnv_o =	old->h2_term[i].cnv_o;
	}
	for (i=	0; i < 6; i++) {
		new->h3_term[i].c = old->h3_term[i].c;
		new->h3_term[i].x = old->h3_term[i].x;
		new->h3_term[i].cnv_i =	old->h3_term[i].cnv_i;
		new->h3_term[i].cnv_o =	old->h3_term[i].cnv_o;
	}

	new->ifImg = old->ifImg;
	new->hstep = old->hstep;        /* Enhancement-905 */
	if (new->vi_tail != old->vi_tail) {
		/* someting wrong */
		fprintf(stderr, "Error during evaluating TXL line\n");
		controlled_exit(0);
	}

	while (new->vi_head->time < old->vi_head->time)	{
		temp = new->vi_head;
		new->vi_head = new->vi_head->next;
		free_vi_txl(temp);
	}
		
}


static int 
update_cnv_txl(TXLine *tx, double h)
{
   int i;

   double ai, bi, ao, bo;
   double e, t;

   ai =	tx->in_node->V;
   ao =	tx->out_node->V;
   bi =	tx->in_node->dv;
   bo =	tx->out_node->dv;

   for (i = 0; i < 3; i++) {
      TERM *tm;
      tm = &(tx->h1_term[i]);

      e	= tx->h1e[i];
    
      t	= tm->c	/ tm->x;
      /* Enhancement-905: each term's own slope, in the weights the load used
       * for this step. `bi *= t` multiplied the running product into the next
       * term: the second and third terms took dv*t0*t1 and dv*t0*t1*t2. The
       * slope term was also a difference of two near-equal quantities when
       * the step is short against the pole, and lost digits at high
       * frequency. h is the step in picoseconds, dv in volts per picosecond. */
      {
	 double wn, wo;
	 txl_w(tm->x, tx->hstep, &wn, &wo);
	 tm->cnv_i = tm->cnv_i * e + t * (ai * wn + (ai - bi * h) * wo);
	 tm->cnv_o = tm->cnv_o * e + t * (ao * wn + (ao - bo * h) * wo);
      }
   }
   return (1);
}


static VI_list_txl
*new_vi_txl(void)
{
   VI_list_txl *q;

   if (pool_vi_txl) {
      q	= pool_vi_txl;
      pool_vi_txl = pool_vi_txl->pool;
      return(q);
   } else 
      return(TMALLOC(VI_list_txl, 1));
}

static void 
free_vi_txl(VI_list_txl	*q)
{
   q->pool = pool_vi_txl;
   pool_vi_txl = q;
}


static int 
add_new_vi_txl(TXLinstance *here, CKTcircuit *ckt, long long time)
{
   VI_list_txl *vi;
   TXLine *tx, *tx2;

   tx =	here->txline;
   tx2 = here->txline2;

   vi =	new_vi_txl();
   vi->time = time;
   tx->vi_tail->next = vi;
   tx2->vi_tail->next =	vi;
   vi->next = NULL;
   tx->vi_tail = vi;
   tx2->vi_tail	= vi;
   
   vi->v_i = *(ckt->CKTrhsOld +	here->TXLposNode);
   vi->v_o = *(ckt->CKTrhsOld +	here->TXLnegNode);
   vi->i_i = *(ckt->CKTrhsOld +	here->TXLibr1);
   vi->i_o = *(ckt->CKTrhsOld +	here->TXLibr2);
   return(1);
}


static int 
get_pvs_vi_txl(long long t1, long long t2, TXLine *tx, double *v1_i, double	*v2_i, double *i1_i, double *i2_i, 
	       double *v1_o, double *v2_o, double *i1_o, double	*i2_o)
{
   double ta, tb; 
   VI_list_txl *vi, *vi1;
   double f;
   int ext = 0;

   ta =	(double) t1 - tx->taul;
   tb =	(double) t2 - tx->taul;
   if (tb <= 0)	{
      *v1_i = *v2_i = tx->dc1; 
      *v2_o = *v1_o = tx->dc2;
      *i1_i = *i2_i = tx->idc1;      /* Enhancement-904: were 0 */
      *i1_o = *i2_o = tx->idc2;
      return(ext);
   }

   if (ta <= 0)	{
      *i1_i = tx->idc1;              /* Enhancement-904: were 0 */
      *i1_o = tx->idc2;
      *v1_i = tx->dc1;
      *v1_o = tx->dc2; 
      vi1 = tx->vi_head;
      vi = vi1->next;
   } else {
      vi1 = tx->vi_head;
      for (vi =	vi1->next; (double) vi->time < ta; vi = vi->next) {
	 /* free_vi_txl(vi1); */
	 vi1 = vi;
      }
      f	= (ta -	(double) vi1->time) / (double) (vi->time - vi1->time);
      *v1_i = vi1->v_i + f * (vi->v_i -	vi1->v_i);
      *v1_o = vi1->v_o + f * (vi->v_o -	vi1->v_o);
      *i1_i = vi1->i_i + f * (vi->i_i -	vi1->i_i);
      *i1_o = vi1->i_o + f * (vi->i_o -	vi1->i_o);
      tx->vi_head = vi1;
   }

   if (tb > (double) t1)	{
     
      /* fprintf(stderr, "pvs: time = %d\n", t2); */
      ext = 1;
      /*     
      f	= tb - t1;
      *v2_i = tx->in_node->V + tx->in_node->dv * f;
      *v2_o = tx->out_node->V +	tx->out_node->dv * f;
      
      if (vi) {
	 for (;	vi->time != t1;	vi = vi->next) 
	    vi1	= vi;

	 f /= (double) (t1 - vi1->time);
	 *i2_i = vi->i_i + f * (vi->i_i	- vi1->i_i);
	 *i2_o = vi->i_o + f * (vi->i_o	- vi1->i_o);
      }	else {
	 *i2_i = vi1->i_i;
	 *i2_o = vi1->i_o;
      }
       */
      ratio[0] = f = (tb - (double) t1) / (double) (t2 - t1);
      if (vi)
	 for (;	vi->time != t1;	vi = vi->next)
	    ;
      else 
	 vi = vi1;
      f	= 1 - f;
      *v2_i = vi->v_i *	f;
      *v2_o = vi->v_o *	f;
      *i2_i = vi->i_i *	f;
      *i2_o = vi->i_o *	f;
   } else {
      for (; (double) vi->time <	tb; vi = vi->next) 
	 vi1 = vi;
      
      f	= (tb -	(double) vi1->time) / (double) (vi->time - vi1->time);
      *v2_i = vi1->v_i + f * (vi->v_i -	vi1->v_i);
      *v2_o = vi1->v_o + f * (vi->v_o -	vi1->v_o);
      *i2_i = vi1->i_i + f * (vi->i_i -	vi1->i_i);
      *i2_o = vi1->i_o + f * (vi->i_o -	vi1->i_o);
   }

   return(ext);
}


static int
right_consts_txl(TXLine	*tx, long long t, long long time, double h,	double h1, int l1, int l2, CKTcircuit *ckt)
/***  h1 = 0.5 * h  ***/
{
   int i;
   double ff=0.0, gg=0.0, e;
   double v1_i,	v2_i, i1_i, i2_i;
   double v1_o,	v2_o, i1_o, i2_o;
   int ext;

   NG_IGNORE(h1);    /* Enhancement-906: the exact weights replaced h/2 */
   tx->hstep = h;    /* Enhancement-905: for the history update once accepted */

   if (! tx->lsl) {
   for (i = 0; i < 3; i++) {
      double wn, wo, t = tx->h1_term[i].c / tx->h1_term[i].x;
      tx->h1e[i] = e = exp(tx->h1_term[i].x * h);
      txl_w(tx->h1_term[i].x, h, &wn, &wo);
      ff  -= tx->h1_term[i].cnv_i * e + t * wo * tx->in_node->V;
      gg  -= tx->h1_term[i].cnv_o * e + t * wo * tx->out_node->V;
   }
   }

   ext = get_pvs_vi_txl(t, time, tx, &v1_i, &v2_i, &i1_i, &i2_i, &v1_o,	&v2_o, &i1_o, &i2_o);

   if (tx->lsl)	{
	   ff =	tx->h3_aten * v2_o + tx->h2_aten * i2_o;
	   gg =	tx->h3_aten * v2_i + tx->h2_aten * i2_i;
  } else {
   if (tx->ifImg) {
      for (i = 0; i < 4; i++) {
     TERM *tm;
     double wn, wo, t;
     tm	= &(tx->h3_term[i]);
     e =  exp(tm->x * h);
     txl_w(tm->x, h, &wn, &wo);
     t = tm->c / tm->x;
     tm->cnv_i = tm->cnv_i * e + t * (v2_i * wn + v1_i * wo);
     tm->cnv_o = tm->cnv_o * e + t * (v2_o * wn + v1_o * wo);
      }
      txl_cstep(&tx->h3_term[4].cnv_i, &tx->h3_term[5].cnv_i, tx->h3_term[4].c, tx->h3_term[5].c,
                tx->h3_term[4].x, tx->h3_term[5].x, h, v2_i, v1_i);
      txl_cstep(&tx->h3_term[4].cnv_o, &tx->h3_term[5].cnv_o, tx->h3_term[4].c, tx->h3_term[5].c,
                tx->h3_term[4].x, tx->h3_term[5].x, h, v2_o, v1_o);

      ff += tx->h3_aten	* v2_o;
      gg += tx->h3_aten	* v2_i;

      for (i = 0; i < 5; i++) {
     ff	+= tx->h3_term[i].cnv_o;
     gg	+= tx->h3_term[i].cnv_i;
      }
      ff += tx->h3_term[4].cnv_o;
      gg += tx->h3_term[4].cnv_i;

      {
     TERM *tm;
     double wn, wo, t;
     tm	= &(tx->h2_term[0]);

     e =  exp(tm->x * h);
     txl_w(tm->x, h, &wn, &wo);
     t = tm->c / tm->x;
     tm->cnv_i = tm->cnv_i * e + t * (i2_i * wn + i1_i * wo);
     tm->cnv_o = tm->cnv_o * e + t * (i2_o * wn + i1_o * wo);
      }
      txl_cstep(&tx->h2_term[1].cnv_i, &tx->h2_term[2].cnv_i, tx->h2_term[1].c, tx->h2_term[2].c,
                tx->h2_term[1].x, tx->h2_term[2].x, h, i2_i, i1_i);
      txl_cstep(&tx->h2_term[1].cnv_o, &tx->h2_term[2].cnv_o, tx->h2_term[1].c, tx->h2_term[2].c,
                tx->h2_term[1].x, tx->h2_term[2].x, h, i2_o, i1_o);

      ff += tx->h2_aten	* i2_o + tx->h2_term[0].cnv_o +
	  2.0 *	tx->h2_term[1].cnv_o;
      gg += tx->h2_aten	* i2_i + tx->h2_term[0].cnv_i +
	  2.0 *	tx->h2_term[1].cnv_i;
   } else {
      for (i = 0; i < 6; i++) {
     TERM *tm;
     double wn, wo, t;
     tm	= &(tx->h3_term[i]);

     e =  exp(tm->x * h);
     txl_w(tm->x, h, &wn, &wo);
     t = tm->c / tm->x;
     tm->cnv_i = tm->cnv_i * e + t * (v2_i * wn + v1_i * wo);
     tm->cnv_o = tm->cnv_o * e + t * (v2_o * wn + v1_o * wo);
      }

      ff += tx->h3_aten	* v2_o;
      gg += tx->h3_aten	* v2_i;

      for (i = 0; i < 6; i++) {
     ff	+= tx->h3_term[i].cnv_o;
     gg	+= tx->h3_term[i].cnv_i;
      }

      for (i = 0; i < 3; i++) {
     TERM *tm;
     double wn, wo, t;
     tm	= &(tx->h2_term[i]);

     e =  exp(tm->x * h);
     txl_w(tm->x, h, &wn, &wo);
     t = tm->c / tm->x;
     tm->cnv_i = tm->cnv_i * e + t * (i2_i * wn + i1_i * wo);
     tm->cnv_o = tm->cnv_o * e + t * (i2_o * wn + i1_o * wo);
      }

      ff += tx->h2_aten	* i2_o;
      gg += tx->h2_aten	* i2_i;

      for (i = 0; i < 3; i++) {
     ff	+= tx->h2_term[i].cnv_o;
     gg	+= tx->h2_term[i].cnv_i;
      }
   }
   }

	*(ckt->CKTrhs +	l1) = ff;
	*(ckt->CKTrhs +	l2) = gg;

   return(ext);
}


static int update_delayed_cnv_txl(TXLine *tx, double h)
{
   double ratio1;
   double f;
   VI_list_txl *vi;
   TERM	*tms;

   h *=	0.5e-12;
   ratio1 = tx->ratio;
   vi =	tx->vi_tail;

   if (ratio1 > 0.0) {
      tms = tx->h3_term;
      f	= h * ratio1 * vi->v_i;
      tms[0].cnv_i += f	*  tms[0].c;
      tms[1].cnv_i += f	*  tms[1].c;
      tms[2].cnv_i += f	*  tms[2].c;
      tms[3].cnv_i += f	*  tms[3].c;
      tms[4].cnv_i += f	*  tms[4].c;
      tms[5].cnv_i += f	*  tms[5].c;

      f	= h * ratio1 * vi->v_o;
      tms[0].cnv_o += f	*  tms[0].c;
      tms[1].cnv_o += f	*  tms[1].c;
      tms[2].cnv_o += f	*  tms[2].c;
      tms[3].cnv_o += f	*  tms[3].c;
      tms[4].cnv_o += f	*  tms[4].c;
      tms[5].cnv_o += f	*  tms[5].c;

      tms = tx->h2_term;
      f	= h * ratio1 * vi->i_i;
      tms[0].cnv_i += f	*  tms[0].c;
      tms[1].cnv_i += f	*  tms[1].c;
      tms[2].cnv_i += f	*  tms[2].c;

      f	= h * ratio1 * vi->i_o;
      tms[0].cnv_o += f	*  tms[0].c;
      tms[1].cnv_o += f	*  tms[1].c;
      tms[2].cnv_o += f	*  tms[2].c;
   }

   return(1);
}

static int 
expC(double ar,	double ai, double h, double *cr, double *ci)
{
   double e, cs, si;

   e = exp(ar * h);
   cs =	cos(ai	* h);
   si =	sin(ai	* h);
   *cr = e * cs;
   *ci = e * si;

   return(1);
}

