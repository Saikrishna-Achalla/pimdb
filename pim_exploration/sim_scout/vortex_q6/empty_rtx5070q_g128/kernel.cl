// Launch-overhead probe: same signature as tpch_q6's q6_sum, but does no work except one store per group.
__kernel void q6_sum(__global const short* quantity, __global const int* extendedprice,
                     __global const char* discount, __global const short* shipdate,
                     int num_rows, int date_lo, int date_hi, int disc_lo, int disc_hi, int qty_lt,
                     __local long* scratch, __global long* group_sums) {
  if (get_local_id(0) == 0) group_sums[get_group_id(0)] = 0;
}
