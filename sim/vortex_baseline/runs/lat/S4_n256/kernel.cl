// Pointer-chase latency probe: one work-item follows a chain, so each load waits for the last.
__kernel void chase(__global const ulong* next, int steps, __global ulong* out) {
  ulong p = 0;
  for (int i = 0; i < steps; ++i)
    p = next[p];
  out[0] = p;
}
