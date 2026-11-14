// General database sub-operator kernels for the Vortex baseline (OpenCL C 1.2, PoCL-Vortex).
// Structured the way libcudf launches them: one kernel per sub-operator and per column; compaction is
// count -> scan -> scatter with the selected count read back by the host; predicates write a 1-byte
// mask (cuDF BOOL8). No kernel knows which query it serves (project rule: no query-specific fusion).
//
// Two launch shapes (set by the host):
//  * grid-stride kernels (element-wise, gathers, casts, binary ops, reduce tiles, group-by): the host
//    launches one work-item per resident hardware thread (cores x warps x 32) and each work-item walks
//    i = gid, gid + gsize, ... -- consecutive lanes touch consecutive elements (coalesced);
//  * tile kernels (compaction, scan): one work-group of WG work-items per TILE = WG * IPT rows, items in
//    a blocked arrangement (8 consecutive bytes / ints per work-item), as cub's select/scan agents do.
// 64-bit atomic add: PoCL's kernel library has no ATOM_ADD64(long); the clang builtin lowers to RISC-V
// amoadd.d (A extension), which simx executes in local memory and at the LLC.
#define ATOM_ADD64(p, v) __atomic_fetch_add((p), (v), __ATOMIC_RELAXED)

#define WG 256
#define IPT 8
#define TILE (WG * IPT)

// ---------------------------------------------------------------- empty kernel (launch cost probe)
__kernel void empty_kernel(void) {}

// ---------------------------------------------------------------- 1. predicate: column <op> constant -> mask
// Mask kernels handle two consecutive rows per work-item, so one warp store covers 64 mask bytes = one
// whole 64 B sector (the GPU equivalent: one 32 B sector per warp store of 32 bools).
// op: 0 ==, 1 !=, 2 <, 3 <=, 4 >, 5 >=
#define PAIR_LOOP(T, EXPR)                                                        \
  for (int p = get_global_id(0); 2 * p < n; p += get_global_size(0)) {           \
    int i = 2 * p;                                                                \
    if (i + 1 < n) {                                                              \
      T v0 = col[i], v1 = col[i + 1];                                             \
      uchar2 r;                                                                   \
      { T v = v0; r.x = (uchar)(EXPR); }                                          \
      { T v = v1; r.y = (uchar)(EXPR); }                                          \
      vstore2(r, p, mask);                                                        \
    } else {                                                                      \
      T v = col[i];                                                               \
      mask[i] = (uchar)(EXPR);                                                    \
    }                                                                             \
  }
#define DEF_CMP(T, NAME)                                                                   \
  __kernel void cmp_##NAME(__global const T* col, long c, int op, __global uchar* mask, int n) { \
    T k = (T)c;                                                                            \
    switch (op) {                                                                          \
      case 0: PAIR_LOOP(T, v == k) break;                                                  \
      case 1: PAIR_LOOP(T, v != k) break;                                                  \
      case 2: PAIR_LOOP(T, v < k) break;                                                   \
      case 3: PAIR_LOOP(T, v <= k) break;                                                  \
      case 4: PAIR_LOOP(T, v > k) break;                                                   \
      default: PAIR_LOOP(T, v >= k) break;                                                 \
    }                                                                                      \
  }
DEF_CMP(short, i16)
DEF_CMP(int, i32)
DEF_CMP(long, i64)

// ---------------------------------------------------------------- 2. range predicate (two compares), mask AND
#define DEF_RANGE(T, NAME)                                                                          \
  __kernel void range_##NAME(__global const T* col, long lo, long hi, __global uchar* mask, int n) { \
    T a = (T)lo, b = (T)hi;                                                                         \
    PAIR_LOOP(T, (v >= a) & (v <= b))                                                               \
  }
DEF_RANGE(short, i16)
DEF_RANGE(int, i32)
DEF_RANGE(long, i64)

__kernel void mask_and(__global const uchar* a, __global const uchar* b, __global uchar* mask, int n) {
  for (int p = get_global_id(0); 2 * p < n; p += get_global_size(0)) {
    int i = 2 * p;
    if (i + 1 < n) vstore2(vload2(p, a) & vload2(p, b), p, mask);
    else mask[i] = a[i] & b[i];
  }
}

// Conjunction of up to four inclusive range terms over columns of any integer width, evaluated in one
// pass (the general counterpart of cuDF's AST compute_column_kernel for "c0 in [lo0,hi0] AND ...").
// t*: element width code 0 = 1 B, 1 = 2 B, 2 = 4 B, 3 = 8 B.
static inline long ld_any(__global const void* p, int t, int i) {
  switch (t) {
    case 0: return ((__global const char*)p)[i];
    case 1: return ((__global const short*)p)[i];
    case 2: return ((__global const int*)p)[i];
    default: return ((__global const long*)p)[i];
  }
}
static inline uchar conj_row(__global const void* c0, __global const void* c1, __global const void* c2,
                             __global const void* c3, int t0, int t1, int t2, int t3, long lo0, long hi0,
                             long lo1, long hi1, long lo2, long hi2, long lo3, long hi3, int nterms, int i) {
  long v0 = ld_any(c0, t0, i);
  int r = (v0 >= lo0) & (v0 <= hi0);
  if (nterms > 1) { long v = ld_any(c1, t1, i); r &= (v >= lo1) & (v <= hi1); }
  if (nterms > 2) { long v = ld_any(c2, t2, i); r &= (v >= lo2) & (v <= hi2); }
  if (nterms > 3) { long v = ld_any(c3, t3, i); r &= (v >= lo3) & (v <= hi3); }
  return (uchar)r;
}
__kernel void filter_conj(__global const void* c0, __global const void* c1, __global const void* c2,
                          __global const void* c3, int t0, int t1, int t2, int t3, long lo0, long hi0,
                          long lo1, long hi1, long lo2, long hi2, long lo3, long hi3, int nterms,
                          __global uchar* mask, int n) {
  for (int p = get_global_id(0); 2 * p < n; p += get_global_size(0)) {
    int i = 2 * p;
    uchar r0 = conj_row(c0, c1, c2, c3, t0, t1, t2, t3, lo0, hi0, lo1, hi1, lo2, hi2, lo3, hi3, nterms, i);
    if (i + 1 < n) {
      uchar r1 = conj_row(c0, c1, c2, c3, t0, t1, t2, t3, lo0, hi0, lo1, hi1, lo2, hi2, lo3, hi3, nterms, i + 1);
      vstore2((uchar2)(r0, r1), p, mask);
    } else {
      mask[i] = r0;
    }
  }
}

// ---------------------------------------------------------------- work-group scan / reduce helpers
// Barriers are expensive in this model (PoCL lowers one to ~18 warp instructions; ~570 cycles per
// barrier with 4 work-groups resident, runs/test/xp_bar64), so the helpers use 3 barriers instead of a
// log2(WG)-step tree: the 32 lanes of warp 0 each scan 8 consecutive slots, lane 0 scans the 32 chunk
// totals (lanes of one warp execute in lockstep, so no barrier is needed inside warp 0).
// s must hold WG + 33 ints.
static int wg_exclusive_scan(int x, __local int* s, int* total) {
  int l = get_local_id(0);
  s[l] = x;
  barrier(CLK_LOCAL_MEM_FENCE);
  if (l < 32) {
    volatile __local int* v = s;
    int b = l * 8, run = 0;
    for (int k = 0; k < 8; ++k) { int t = v[b + k]; v[b + k] = run; run += t; }
    v[WG + l] = run;
    if (l == 0) {
      int r = 0;
      for (int c = 0; c < 32; ++c) { int t = v[WG + c]; v[WG + c] = r; r += t; }
      v[WG + 32] = r;
    }
  }
  barrier(CLK_LOCAL_MEM_FENCE);
  int ex = s[l] + s[WG + (l >> 3)];
  *total = s[WG + 32];
  barrier(CLK_LOCAL_MEM_FENCE);
  return ex;
}
// work-group sum (2 barriers); s must hold WG + 1 ints
static int wg_sum_int(int x, __local int* s) {
  int l = get_local_id(0);
  s[l] = x;
  barrier(CLK_LOCAL_MEM_FENCE);
  if (l < 32) {
    volatile __local int* v = s;
    int r = 0;
    for (int k = 0; k < 8; ++k) r += v[l * 8 + k];
    v[l * 8] = r;
    if (l == 0) { int t = 0; for (int c = 0; c < 32; ++c) t += v[c * 8]; v[WG] = t; }
  }
  barrier(CLK_LOCAL_MEM_FENCE);
  return s[WG];
}

static inline int nz8(uchar8 m) {
  return (m.s0 != 0) + (m.s1 != 0) + (m.s2 != 0) + (m.s3 != 0) + (m.s4 != 0) + (m.s5 != 0) + (m.s6 != 0) + (m.s7 != 0);
}

// ---------------------------------------------------------------- 3. compaction: count -> scan -> scatter
// pass 1: selected rows per tile (one work-group per TILE rows, 8 consecutive mask bytes per work-item)
__kernel void mask_count(__global const uchar* mask, int n, __global int* tile_counts) {
  __local int s[WG + 1];
  int g = get_group_id(0), l = get_local_id(0);
  int i0 = g * TILE + l * IPT;
  int c = 0;
  if (i0 + IPT <= n) {
    c = nz8(vload8(0, mask + i0));
  } else {
    for (int i = i0; i < n; ++i) c += mask[i] != 0;
  }
  int tot = wg_sum_int(c, s);
  if (l == 0) tile_counts[g] = tot;
}

// pass 2 (one work-group): exclusive scan of the per-tile values; total -> *total (the host reads it back)
__kernel void scan_tiles(__global const int* tile_vals, int ntiles, __global int* tile_offsets, __global int* total) {
  __local int s[WG + 33];
  int l = get_local_id(0);
  int per = (ntiles + WG - 1) / WG;
  int b = l * per, e = min(b + per, ntiles);
  int sum = 0;
  for (int t = b; t < e; ++t) sum += tile_vals[t];
  int tot;
  int run = wg_exclusive_scan(sum, s, &tot);
  for (int t = b; t < e; ++t) { tile_offsets[t] = run; run += tile_vals[t]; }
  if (l == 0) *total = tot;
}

// pass 3: stable scatter of the selected row indices. Two-phase like cub: the tile's selected indices
// are first compacted into local memory, then written to global memory with consecutive work-items
// writing consecutive words (coalesced).
__kernel void mask_scatter(__global const uchar* mask, int n, __global const int* tile_offsets, __global int* out_idx) {
  __local int s[WG + 33];
  __local int buf[TILE];
  int g = get_group_id(0), l = get_local_id(0);
  int i0 = g * TILE + l * IPT;
  uchar8 v = (uchar8)(0);
  if (i0 + IPT <= n) {
    v = vload8(0, mask + i0);
  } else {
    if (i0 + 0 < n) v.s0 = mask[i0 + 0];
    if (i0 + 1 < n) v.s1 = mask[i0 + 1];
    if (i0 + 2 < n) v.s2 = mask[i0 + 2];
    if (i0 + 3 < n) v.s3 = mask[i0 + 3];
    if (i0 + 4 < n) v.s4 = mask[i0 + 4];
    if (i0 + 5 < n) v.s5 = mask[i0 + 5];
    if (i0 + 6 < n) v.s6 = mask[i0 + 6];
  }
  int tot;
  int pos = wg_exclusive_scan(nz8(v), s, &tot);
  if (v.s0) buf[pos++] = i0 + 0;
  if (v.s1) buf[pos++] = i0 + 1;
  if (v.s2) buf[pos++] = i0 + 2;
  if (v.s3) buf[pos++] = i0 + 3;
  if (v.s4) buf[pos++] = i0 + 4;
  if (v.s5) buf[pos++] = i0 + 5;
  if (v.s6) buf[pos++] = i0 + 6;
  if (v.s7) buf[pos++] = i0 + 7;
  barrier(CLK_LOCAL_MEM_FENCE);
  int base = tile_offsets[g];
  for (int k = l; k < tot; k += WG) out_idx[base + k] = buf[k];
}

// ---------------------------------------------------------------- general int scan (string offsets)
// tile sums of an int column
__kernel void tile_sum_i32(__global const int* in, int n, __global int* tile_sums) {
  __local int s[WG + 1];
  int g = get_group_id(0), l = get_local_id(0);
  int i0 = g * TILE + l * IPT, c = 0;
  for (int k = 0; k < IPT; ++k) if (i0 + k < n) c += in[i0 + k];
  int tot = wg_sum_int(c, s);
  if (l == 0) tile_sums[g] = tot;
}
// exclusive scan within the tile plus the tile offset; out has n+1 entries (out[n] = *total)
__kernel void tile_scan_apply_i32(__global const int* in, int n, __global const int* tile_offsets,
                                  __global const int* total, __global int* out) {
  __local int s[WG + 33];
  int g = get_group_id(0), l = get_local_id(0);
  int i0 = g * TILE + l * IPT, c = 0;
  for (int k = 0; k < IPT; ++k) c += (i0 + k < n) ? in[i0 + k] : 0;
  int tot;
  int run = tile_offsets[g] + wg_exclusive_scan(c, s, &tot);
  // second read of the work-item's 8 values hits in L1 (no private array: it would live on the stack)
  for (int k = 0; k < IPT; ++k) if (i0 + k < n) { int t = in[i0 + k]; out[i0 + k] = run; run += t; }
  if (get_global_id(0) == 0) out[n] = *total;
}

// ---------------------------------------------------------------- 4. gather (fixed width)
#define DEF_GATHER(T, NAME)                                                                          \
  __kernel void gather_##NAME(__global const T* src, __global const int* idx, __global T* out, int m) { \
    for (int j = get_global_id(0); j < m; j += get_global_size(0)) out[j] = src[idx[j]];             \
  }
DEF_GATHER(char, i8)
DEF_GATHER(short, i16)
DEF_GATHER(int, i32)
DEF_GATHER(long, i64)

// strings gather (cuDF: offsets from a scan of the gathered lengths, then the characters)
__kernel void str_gather_len(__global const int* off, __global const int* idx, __global int* len, int m) {
  for (int j = get_global_id(0); j < m; j += get_global_size(0)) {
    int r = idx[j];
    len[j] = off[r + 1] - off[r];
  }
}
__kernel void str_gather_chars(__global const int* off, __global const uchar* chars, __global const int* idx,
                               __global const int* out_off, __global uchar* out_chars, int m) {
  for (int j = get_global_id(0); j < m; j += get_global_size(0)) {
    int r = idx[j], b = off[r], e = off[r + 1], o = out_off[j];
    for (int k = b; k < e; ++k) out_chars[o + (k - b)] = chars[k];
  }
}

// ---------------------------------------------------------------- 5. element-wise: cast / binary ops
__kernel void cast_i32_i64(__global const int* in, __global long* out, int n) {
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) out[i] = (long)in[i];
}
__kernel void cast_i16_i64(__global const short* in, __global long* out, int n) {
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) out[i] = (long)in[i];
}
// op: 0 add, 1 sub, 2 mul
#define BIN_LOOP(EXPR) for (int i = get_global_id(0); i < n; i += get_global_size(0)) { long x = a[i], y = b[i]; out[i] = (EXPR); }
__kernel void binop_i64(__global const long* a, __global const long* b, __global long* out, int n, int op) {
  switch (op) {
    case 0: BIN_LOOP(x + y) break;
    case 1: BIN_LOOP(x - y) break;
    default: BIN_LOOP(x * y) break;
  }
}
// scalar <op> column (cuDF binary_operation(scalar, column))
#define BINS_LOOP(EXPR) for (int i = get_global_id(0); i < n; i += get_global_size(0)) { long y = b[i]; out[i] = (EXPR); }
__kernel void binop_s_i64(long x, __global const long* b, __global long* out, int n, int op) {
  switch (op) {
    case 0: BINS_LOOP(x + y) break;
    case 1: BINS_LOOP(x - y) break;
    default: BINS_LOOP(x * y) break;
  }
}

// ---------------------------------------------------------------- 6. reduce (cub DeviceReduceKernel + SingleTile)
// work-group reductions with 2 barriers (see the scan helpers); s must hold WG + 1 longs
static long wg_sum_long(long x, __local long* s) {
  int l = get_local_id(0);
  s[l] = x;
  barrier(CLK_LOCAL_MEM_FENCE);
  if (l < 32) {
    volatile __local long* v = s;
    long r = 0;
    for (int k = 0; k < 8; ++k) r += v[l * 8 + k];
    v[l * 8] = r;
    if (l == 0) { long t = 0; for (int c = 0; c < 32; ++c) t += v[c * 8]; v[WG] = t; }
  }
  barrier(CLK_LOCAL_MEM_FENCE);
  return s[WG];
}
// min and max together; a, b must hold WG + 1 longs each
static void wg_minmax_long(long mn, long mx, __local long* a, __local long* b, long* omn, long* omx) {
  int l = get_local_id(0);
  a[l] = mn;
  b[l] = mx;
  barrier(CLK_LOCAL_MEM_FENCE);
  if (l < 32) {
    volatile __local long* va = a;
    volatile __local long* vb = b;
    long r = LONG_MAX, q = LONG_MIN;
    for (int k = 0; k < 8; ++k) { r = min(r, va[l * 8 + k]); q = max(q, vb[l * 8 + k]); }
    va[l * 8] = r;
    vb[l * 8] = q;
    if (l == 0) {
      long t = LONG_MAX, u = LONG_MIN;
      for (int c = 0; c < 32; ++c) { t = min(t, va[c * 8]); u = max(u, vb[c * 8]); }
      va[WG] = t;
      vb[WG] = u;
    }
  }
  barrier(CLK_LOCAL_MEM_FENCE);
  *omn = a[WG];
  *omx = b[WG];
}
__kernel void reduce_sum_i64(__global const long* in, int n, __global long* partials) {
  __local long s[WG + 1];
  long acc = 0;
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) acc += in[i];
  long r = wg_sum_long(acc, s);
  if (get_local_id(0) == 0) partials[get_group_id(0)] = r;
}
__kernel void reduce_sum_i32(__global const int* in, int n, __global long* partials) {
  __local long s[WG + 1];
  long acc = 0;
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) acc += in[i];
  long r = wg_sum_long(acc, s);
  if (get_local_id(0) == 0) partials[get_group_id(0)] = r;
}
__kernel void reduce_sum_final(__global const long* partials, int np, __global long* out) {
  __local long s[WG + 1];
  long acc = 0;
  for (int i = get_local_id(0); i < np; i += WG) acc += partials[i];
  long r = wg_sum_long(acc, s);
  if (get_local_id(0) == 0) out[0] = r;
}
__kernel void reduce_minmax_i64(__global const long* in, int n, __global long* partials) {
  __local long s[WG + 1], s2[WG + 1];
  long mn = LONG_MAX, mx = LONG_MIN;
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) { long v = in[i]; mn = min(mn, v); mx = max(mx, v); }
  long a, b;
  wg_minmax_long(mn, mx, s, s2, &a, &b);
  if (get_local_id(0) == 0) { partials[2 * get_group_id(0)] = a; partials[2 * get_group_id(0) + 1] = b; }
}
__kernel void reduce_minmax_final(__global const long* partials, int np, __global long* out) {
  __local long s[WG + 1], s2[WG + 1];
  long mn = LONG_MAX, mx = LONG_MIN;
  for (int i = get_local_id(0); i < np; i += WG) { mn = min(mn, partials[2 * i]); mx = max(mx, partials[2 * i + 1]); }
  long a, b;
  wg_minmax_long(mn, mx, s, s2, &a, &b);
  if (get_local_id(0) == 0) { out[0] = a; out[1] = b; }
}

// ---------------------------------------------------------------- 7. small-group hash aggregation
// cuDF hash group-by (cuco static_set + shared-memory aggregation), for string or integer keys.
// (a) fill: hash-table slots := -1 (cuco initialize)
__kernel void fill_i32(__global int* p, int v, int n) {
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) p[i] = v;
}
__kernel void fill_i64(__global long* p, long v, int n) {
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) p[i] = v;
}
// (b) insert-or-find every row's key in an open-addressing table (linear probing, CAS on the slot that
// stores the first row holding the key); writes the slot per row (cuDF mapping_indices_kernel).
// Keys: up to two string columns (offsets + chars); nkeys = 1 or 2.
static inline uint str_hash(__global const int* off, __global const uchar* ch, int r, uint h) {
  for (int k = off[r]; k < off[r + 1]; ++k) h = (h ^ ch[k]) * 16777619u;   // FNV-1a
  return h * 2654435761u;
}
static inline int str_eq(__global const int* off, __global const uchar* ch, int a, int b) {
  int la = off[a + 1] - off[a], lb = off[b + 1] - off[b];
  if (la != lb) return 0;
  for (int k = 0; k < la; ++k) if (ch[off[a] + k] != ch[off[b] + k]) return 0;
  return 1;
}
__kernel void gb_map_str(__global const int* off0, __global const uchar* ch0, __global const int* off1,
                         __global const uchar* ch1, int nkeys, int n, __global int* table, int tsize,
                         __global int* slot_of_row) {
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) {
    uint h = str_hash(off0, ch0, i, 2166136261u);
    if (nkeys > 1) h = str_hash(off1, ch1, i, h);
    int s = (int)(h & (uint)(tsize - 1));
    for (;;) {
      int cur = table[s];
      if (cur < 0) {
        cur = atomic_cmpxchg(&table[s], -1, i);
        if (cur < 0) break;               // inserted
      }
      if (str_eq(off0, ch0, cur, i) && (nkeys < 2 || str_eq(off1, ch1, cur, i))) break;   // found
      s = (s + 1) & (tsize - 1);
    }
    slot_of_row[i] = s;
  }
}
// (c) per-work-group shared-memory accumulators (local 64-bit atomics), flushed with global atomics
// (cuDF single_pass_shmem_aggs_kernel). Up to 6 SUM(int64) value columns + COUNT(*) per slot.
// acc layout: acc[slot * (nv + 1) + v], v = nv is the count.
#define GB_MAX_T 64
#define GB_MAX_V 7
__kernel void gb_agg_sum(__global const int* slot_of_row, int n, int tsize, int nv,
                         __global const long* v0, __global const long* v1, __global const long* v2,
                         __global const long* v3, __global const long* v4, __global const long* v5,
                         __global long* acc) {
  __local long sacc[GB_MAX_T * GB_MAX_V];
  int l = get_local_id(0), w = nv + 1;
  for (int k = l; k < tsize * w; k += WG) sacc[k] = 0;
  barrier(CLK_LOCAL_MEM_FENCE);
  for (int i = get_global_id(0); i < n; i += get_global_size(0)) {
    __local long* a = sacc + slot_of_row[i] * w;
    if (nv > 0) ATOM_ADD64(a + 0, v0[i]);
    if (nv > 1) ATOM_ADD64(a + 1, v1[i]);
    if (nv > 2) ATOM_ADD64(a + 2, v2[i]);
    if (nv > 3) ATOM_ADD64(a + 3, v3[i]);
    if (nv > 4) ATOM_ADD64(a + 4, v4[i]);
    if (nv > 5) ATOM_ADD64(a + 5, v5[i]);
    ATOM_ADD64(a + nv, 1L);
  }
  barrier(CLK_LOCAL_MEM_FENCE);
  for (int k = l; k < tsize * w; k += WG)
    if (sacc[k] != 0) ATOM_ADD64(acc + k, sacc[k]);
}

// ---------------------------------------------------------------- 8. membership probe (dynamic filter)
// mask[i] = col[i] is in the sorted key set keys[0..k) (binary search; small sets stay in L1)
__kernel void probe_sorted_i32(__global const int* col, int n, __global const int* keys, int k, __global uchar* mask) {
  for (int p = get_global_id(0); 2 * p < n; p += get_global_size(0)) {
    uchar r[2] = {0, 0};
    for (int q = 0; q < 2; ++q) {
      int i = 2 * p + q;
      if (i >= n) break;
      int v = col[i], lo = 0, hi = k;
      while (lo < hi) { int mid = (lo + hi) >> 1; if (keys[mid] < v) lo = mid + 1; else hi = mid; }
      r[q] = (uchar)(lo < k && keys[lo] == v);
    }
    if (2 * p + 1 < n) vstore2((uchar2)(r[0], r[1]), p, mask);
    else mask[2 * p] = r[0];
  }
}

// ---------------------------------------------------------------- experiments (launch-shape probes)
__kernel void xp_count_atomic(__global const uchar* mask, int n, __global int* tile_counts) {
  __local int s;
  int g = get_group_id(0), l = get_local_id(0);
  if (l == 0) s = 0;
  barrier(CLK_LOCAL_MEM_FENCE);
  int i0 = g * TILE + l * IPT, c = 0;
  if (i0 + IPT <= n) c = nz8(vload8(0, mask + i0)); else for (int i = i0; i < n; ++i) c += mask[i] != 0;
  atomic_add(&s, c);
  barrier(CLK_LOCAL_MEM_FENCE);
  if (l == 0) tile_counts[g] = s;
}
__kernel void xp_count_nobar(__global const uchar* mask, int n, __global int* tile_counts) {
  int g = get_group_id(0), l = get_local_id(0);
  int i0 = g * TILE + l * IPT, c = 0;
  if (i0 + IPT <= n) c = nz8(vload8(0, mask + i0)); else for (int i = i0; i < n; ++i) c += mask[i] != 0;
  if (c < 0) tile_counts[g] = c;
}
__kernel void xp_noop(__global const uchar* mask, int n, __global int* tile_counts) {
  if (n < 0) tile_counts[0] = mask[0];
}
__kernel void xp_bar64(__global const uchar* mask, int n, __global int* tile_counts) {
  __local int s[WG];
  int l = get_local_id(0);
  s[l] = l;
  for (int k = 0; k < 64; ++k) barrier(CLK_LOCAL_MEM_FENCE);
  if (n < 0) tile_counts[0] = mask[0] + s[(l + 1) % WG];
}
