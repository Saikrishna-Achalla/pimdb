// Read bandwidth probe: every work-item sums every global_size-th element of buf, iters times.
// Four independent loads per step keep several requests in flight per warp, so the probe is
// limited by the memory level being measured rather than by one load's latency.
// An 8-lane warp reads 8 consecutive longs = one 64-byte line per load instruction.
__kernel void rd(__global const long* buf, int n, int iters, __global long* out) {
  int gid = get_global_id(0), gs = get_global_size(0);
  long a0 = 0, a1 = 0, a2 = 0, a3 = 0;
  for (int it = 0; it < iters; ++it) {
    int i = gid;
    for (; i + 3 * gs < n; i += 4 * gs) {
      a0 += buf[i];
      a1 += buf[i + gs];
      a2 += buf[i + 2 * gs];
      a3 += buf[i + 3 * gs];
    }
    for (; i < n; i += gs)
      a0 += buf[i];
  }
  out[gid] = a0 + a1 + a2 + a3;
}
