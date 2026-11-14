// TPC-H Q1 over fixed-point columns: decimals are scaled by 100, dates are days since 1970-01-01.
// Groups are (l_returnflag, l_linestatus) with returnflag in {A,N,R} and linestatus in {F,O}.

#define NUM_GROUPS 6
#define NUM_FIELDS 6  // sum_qty, sum_base_price, sum_disc_price, sum_charge, sum_disc, count

__kernel void q1_partial(__global const long* quantity,
                         __global const long* extendedprice,
                         __global const long* discount,
                         __global const long* tax,
                         __global const int* shipdate,
                         __global const uchar* returnflag,
                         __global const uchar* linestatus,
                         int num_rows,
                         int cutoff,
                         __global long* partials) {
  int gid = get_global_id(0);
  int stride = get_global_size(0);

  long acc[NUM_GROUPS * NUM_FIELDS];
  for (int i = 0; i < NUM_GROUPS * NUM_FIELDS; ++i)
    acc[i] = 0;

  for (int i = gid; i < num_rows; i += stride) {
    if (shipdate[i] > cutoff)
      continue;
    uchar rf = returnflag[i];
    int g = ((rf == 'N') ? 1 : (rf == 'R') ? 2 : 0) * 2 + ((linestatus[i] == 'O') ? 1 : 0);
    long price = extendedprice[i];
    long disc = discount[i];
    long disc_price = price * (100 - disc);         // scale 4
    long charge = disc_price * (100 + tax[i]);       // scale 6
    __private long* a = acc + g * NUM_FIELDS;
    a[0] += quantity[i];
    a[1] += price;
    a[2] += disc_price;
    a[3] += charge;
    a[4] += disc;
    a[5] += 1;
  }

  __global long* out = partials + (long)gid * NUM_GROUPS * NUM_FIELDS;
  for (int i = 0; i < NUM_GROUPS * NUM_FIELDS; ++i)
    out[i] = acc[i];
}

__kernel void q1_reduce(__global const long* partials, int num_partials, __global long* result) {
  int slot = get_global_id(0);
  if (slot >= NUM_GROUPS * NUM_FIELDS)
    return;
  long sum = 0;
  for (int p = 0; p < num_partials; ++p)
    sum += partials[(long)p * NUM_GROUPS * NUM_FIELDS + slot];
  result[slot] = sum;
}
