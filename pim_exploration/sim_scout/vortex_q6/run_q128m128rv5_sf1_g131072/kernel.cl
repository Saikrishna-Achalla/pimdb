// TPC-H Q6: revenue = sum(l_extendedprice * l_discount) over rows that pass three filters.
// Columns are exact fixed-point integers: price in cents, discount and quantity times 100,
// ship date as days since 1970-01-01. The sum is in cents * discount-percent (scale 10^4).

// Each thread keeps one running sum in a register. Each work-group then adds its threads'
// sums in local memory, and work-item 0 writes one result per work-group.

// UNROLL rows per step: a thread issues the loads for all UNROLL rows before using any of them,
// so up to 4 * UNROLL of its loads are in flight at once. Set with the build option -DUNROLL=n.
#ifndef UNROLL
#define UNROLL 1
#endif

__kernel void q6_sum(__global const short* quantity,
                     __global const int* extendedprice,
                     __global const char* discount,
                     __global const short* shipdate,
                     int num_rows,
                     int date_lo, int date_hi,
                     int disc_lo, int disc_hi,
                     int qty_lt,
                     __local long* scratch,
                     __global long* group_sums) {
  int gid = get_global_id(0);
  int stride = get_global_size(0);

  long sum = 0;
  int i = gid;
#if UNROLL > 1
  for (; i + (UNROLL - 1) * stride < num_rows; i += UNROLL * stride) {
    int d[UNROLL], disc[UNROLL], qty[UNROLL], price[UNROLL];
#pragma unroll
    for (int u = 0; u < UNROLL; ++u) {
      d[u] = shipdate[i + u * stride];
      disc[u] = discount[i + u * stride];
      qty[u] = quantity[i + u * stride];
      price[u] = extendedprice[i + u * stride];
    }
#pragma unroll
    for (int u = 0; u < UNROLL; ++u) {
      bool pass = (d[u] >= date_lo) & (d[u] < date_hi) &
                  (disc[u] >= disc_lo) & (disc[u] <= disc_hi) &
                  (qty[u] < qty_lt);
      long revenue = (long)price[u] * disc[u];
      sum += pass ? revenue : 0;
    }
  }
#endif
  // With UNROLL = 1 this is the whole loop; otherwise it handles the last few rows.
  for (; i < num_rows; i += stride) {
    int d = shipdate[i];
    int disc = discount[i];
    bool pass = (d >= date_lo) & (d < date_hi) &
                (disc >= disc_lo) & (disc <= disc_hi) &
                (quantity[i] < qty_lt);
    long revenue = (long)extendedprice[i] * disc;
    sum += pass ? revenue : 0;
  }

  // Tree reduction in local memory: halve the number of active threads each step.
  int lid = get_local_id(0);
  scratch[lid] = sum;
  barrier(CLK_LOCAL_MEM_FENCE);
  for (int s = get_local_size(0) / 2; s > 0; s >>= 1) {
    if (lid < s)
      scratch[lid] += scratch[lid + s];
    barrier(CLK_LOCAL_MEM_FENCE);
  }
  if (lid == 0)
    group_sums[get_group_id(0)] = scratch[0];
}
