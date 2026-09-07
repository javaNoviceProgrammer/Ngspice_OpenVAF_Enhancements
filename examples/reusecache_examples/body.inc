// the body of inc.va lives here, so an edit to THIS file must rebuild inc.osdi
module rinc(p, n);
  inout p, n; electrical p, n;
  analog I(p,n) <+ V(p,n) / 1000.0;
endmodule
