// Loop-unrolling study for the cuDF-style group-by aggregation kernel (single_pass_shmem_aggs_kernel model).
// ONLY unrolling is varied; atomic flavour (generic ATOM.E.ADD.64.STRONG.SYS into shared memory), launch
// (240 x 128), shared-memory layout and per-kernel work are identical to groupby_unroll_bench.cu's baseline.
//
// Build (same toolchain/flags as build.sh):
//   P=/home/sai/cs254_project/sirius/.pixi/envs/default
//   PATH=$P/bin:$PATH $P/bin/nvcc -ccbin $P/bin/x86_64-conda-linux-gnu-g++ -O3 -std=c++17 -arch=sm_120 -lineinfo \
//       unroll_study.cu -o unroll_study
// Usage: ./unroll_study [col_spec=LLLLL] [rows=3153518] [reps=30] [group_id_file|-] [name_filter_substr]
//        col_spec chars: L = SUM int64, I = SUM int32 (int64 accumulator), C = COUNT (no value load)
//        env NCU=1 : launch every selected variant exactly once (for ncu -k regex:us_)
//
// Unroll axes / knobs (template parameters of us_kernel):
//   U    rows per batch                       MAP  row mapping inside a batch (WARP / THREAD / GRID / THREADV)
//   CU   columns per batch (1 = runtime column loop, one column at a time; >1 = CU columns' loads issued
//        before any of their atomics, remainder columns handled one at a time)
//   TAIL 0 = every load/atomic predicated on row<n ; 1 = unpredicated main loop + one-row remainder loop
//   SLOT 0 = U slot (group-id) loads issued up front with the batch ; 1 = slot loaded lazily right before
//        the first column's atomic (value loads unrolled, slot loads effectively not) ; 2 = slot loads up
//        front but their first USE deferred to the atomics (so slot + first value loads overlap)
//   CU   0 = ALL columns (unrolled to MAXC, predicated)
//   MINB __launch_bounds__(128, MINB) (0 = unspecified)
//   SUB  0 = none ; else int64 columns are processed in sub-batches of SUB rows inside the U-row batch
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <vector>
#include <string>
#include <random>
#include <algorithm>
#include <functional>
#include <cuda_runtime.h>

#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) { \
  fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e_), __FILE__, __LINE__); exit(1); } } while (0)

constexpr int MAXC = 8;
constexpr int G = 4;
enum Kind : int { SUM_I64 = 0, SUM_I32 = 1, COUNT = 2 };
enum Map : int { WARP = 0, THREAD = 1, GRID = 2, THREADV = 3 };

struct Cols { const void* data[MAXC]; int kind[MAXC]; int n; };

// Column-descriptor access. PASS 0: Cols by value (kernel parameter; with a runtime column index the compiler
// spills it to the thread's local stack -> LDL per access). PASS 1 ("gdesc"): descriptors in global memory,
// re-read per access like cuDF's column_device_view (LDG per row x column in the baseline).
struct ByVal { const Cols& c; int n;
  __device__ __forceinline__ int kind(int i) const { return c.kind[i]; }
  __device__ __forceinline__ const void* data(int i) const { return c.data[i]; } };
struct ByPtr { const Cols* p; int n;
  __device__ __forceinline__ int kind(int i) const { return p->kind[i]; }
  __device__ __forceinline__ const void* data(int i) const { return p->data[i]; } };
template <int PASS> __device__ __forceinline__ auto acc(const Cols& c, const Cols* g) {
  if constexpr (PASS == 1) return ByPtr{g, g->n}; else return ByVal{c, c.n};
}

// Hide the address space so the atomic is the generic ATOM (as in cuDF's SASS), and so the compiler
// cannot prove the table does not alias the inputs.
__device__ __forceinline__ unsigned long long* generic_ptr(long long* p) {
  asm volatile("" : "+l"(p));
  return reinterpret_cast<unsigned long long*>(p);
}
__device__ __forceinline__ void agg_add(long long* slot, long long v) {
  atomicAdd_system(generic_ptr(slot), (unsigned long long)v);
}
__device__ __forceinline__ void flush(long long* tab, long long* out, int C) {
  __syncthreads();
  for (int i = threadIdx.x; i < G * C; i += blockDim.x)
    if (tab[i]) atomicAdd(reinterpret_cast<unsigned long long*>(&out[i]), (unsigned long long)tab[i]);
}
__device__ __forceinline__ void init(long long* tab, int C) {
  for (int i = threadIdx.x; i < G * C; i += blockDim.x) tab[i] = 0;
  __syncthreads();
}

// One row, all columns: exactly the baseline body (load -> atomic per column).
template <class CT>
__device__ __forceinline__ void one_row(int row, const int* map, const CT& cols, long long* tab) {
  const int C = cols.n;
  const int slot = map[row];
  for (int c = 0; c < C; ++c) {
    long long* dst = &tab[slot * C + c];
    switch (cols.kind(c)) {
      case SUM_I64: agg_add(dst, static_cast<const long long*>(cols.data(c))[row]); break;
      case SUM_I32: agg_add(dst, static_cast<const int*>(cols.data(c))[row]); break;
      case COUNT:   agg_add(dst, 1); break;
    }
  }
}

// ---------------------------------------------------------------- baseline (cuDF-like), as in groupby_unroll_bench.cu
template <int PASSV>
__global__ void __launch_bounds__(128) us_baseline(int n, const int* __restrict__ map, Cols cols_v, const Cols* cols_g, long long* out) {
  const auto cols = acc<PASSV>(cols_v, cols_g);
  extern __shared__ long long tab[];
  const int C = cols.n;
  init(tab, C);
  for (int row = blockIdx.x * blockDim.x + threadIdx.x; row < n; row += gridDim.x * blockDim.x) {
    const int slot = map[row];
    for (int c = 0; c < C; ++c) {
      long long* dst = &tab[slot * C + c];
      switch (cols.kind(c)) {
        case SUM_I64: agg_add(dst, static_cast<const long long*>(cols.data(c))[row]); break;
        case SUM_I32: agg_add(dst, static_cast<const int*>(cols.data(c))[row]); break;
        case COUNT:   agg_add(dst, 1); break;
      }
    }
  }
  flush(tab, out, C);
}

// ---------------------------------------------------------------- pragma-only ("naive") unrolling: no restructuring
// rows: U copies of the baseline body per iteration (warp-striped rows); loads stay next to their atomics
// in source order -- can the compiler hoist them over the generic atomics?
template <int U, int PASSV = 0>
__global__ void __launch_bounds__(128) us_naive_rows(int n, const int* __restrict__ map, Cols cols_v, const Cols* cols_g, long long* out) {
  const auto cols = acc<PASSV>(cols_v, cols_g);
  extern __shared__ long long tab[];
  init(tab, cols.n);
  const int tile = blockDim.x * U;
  for (int base = blockIdx.x * tile; base < n; base += gridDim.x * tile) {
#pragma unroll
    for (int r = 0; r < U; ++r) {
      const int row = base + r * blockDim.x + threadIdx.x;
      if (row < n) one_row(row, map, cols, tab);
    }
  }
  flush(tab, out, cols.n);
}
// grid: #pragma unroll U on the baseline's grid-stride loop itself.
template <int U, int PASSV = 0>
__global__ void __launch_bounds__(128) us_naive_grid(int n, const int* __restrict__ map, Cols cols_v, const Cols* cols_g, long long* out) {
  const auto cols = acc<PASSV>(cols_v, cols_g);
  extern __shared__ long long tab[];
  init(tab, cols.n);
#pragma unroll U
  for (int row = blockIdx.x * blockDim.x + threadIdx.x; row < n; row += gridDim.x * blockDim.x)
    one_row(row, map, cols, tab);
  flush(tab, out, cols.n);
}
// cols: #pragma unroll N on the runtime column loop (compiler generates N-way body + remainder).
template <int N, int PASSV = 0>
__global__ void __launch_bounds__(128) us_naive_cols(int n, const int* __restrict__ map, Cols cols_v, const Cols* cols_g, long long* out) {
  const auto cols = acc<PASSV>(cols_v, cols_g);
  extern __shared__ long long tab[];
  const int C = cols.n;
  init(tab, C);
  for (int row = blockIdx.x * blockDim.x + threadIdx.x; row < n; row += gridDim.x * blockDim.x) {
    const int slot = map[row];
#pragma unroll N
    for (int c = 0; c < C; ++c) {
      long long* dst = &tab[slot * C + c];
      switch (cols.kind(c)) {
        case SUM_I64: agg_add(dst, static_cast<const long long*>(cols.data(c))[row]); break;
        case SUM_I32: agg_add(dst, static_cast<const int*>(cols.data(c))[row]); break;
        case COUNT:   agg_add(dst, 1); break;
      }
    }
  }
  flush(tab, out, C);
}

// ---------------------------------------------------------------- restructured unrolling
// Issue N loads of column d for rows row0 + (r0+i)*step.
template <typename T, int N, int MAP, bool PRED>
__device__ __forceinline__ void load_rows(T* v, const T* d, int row0, int step, const bool* ok) {
  if constexpr (MAP == THREADV) {
    // thread-contiguous rows, explicit wide loads (up to 128 bit per LDG)
    constexpr int W0 = 16 / (int)sizeof(T);
    constexpr int W = W0 < N ? W0 : N;
    struct alignas(W * sizeof(T)) Vec { T x[W]; };
#pragma unroll
    for (int i = 0; i < N; i += W) {
      const Vec t = *reinterpret_cast<const Vec*>(d + row0 + i);
#pragma unroll
      for (int j = 0; j < W; ++j) v[i + j] = t.x[j];
    }
  } else {
#pragma unroll
    for (int i = 0; i < N; ++i) {
      if constexpr (PRED) v[i] = ok[i] ? d[row0 + i * step] : (T)0;
      else                v[i] = d[row0 + i * step];
    }
  }
}

// SLOT==2: hide the slot value until the atomic that needs it, so the compiler cannot hoist the
// loop-invariant g*C above the value loads (which would make the thread wait on the slot loads first).
template <int SM> __device__ __forceinline__ int use_slot(int g) {
  if constexpr (SM == 2) asm volatile("" : "+r"(g));
  return g;
}

// One column, U rows: N loads then N atomics (sub-batched by SUB for int64 if SUB > 0).
template <int U, int MAP, bool PRED, int SUB, int SM, class CT>
__device__ __forceinline__ void col_rows(int c, int row0, int step, const int* map, const CT& cols,
                                         long long* tab, int* g, const bool* ok) {
  const int C = cols.n;
  switch (cols.kind(c)) {                                       // dispatch once per U rows
    case SUM_I64: {
      const long long* d = static_cast<const long long*>(cols.data(c));
      constexpr int S = (SUB > 0 && SUB < U) ? SUB : U;
#pragma unroll
      for (int s = 0; s < U; s += S) {
        long long v[S];
        load_rows<long long, S, MAP, PRED>(v, d, row0 + s * step, step, ok + s);
#pragma unroll
        for (int r = 0; r < S; ++r) {
          if constexpr (SM == 1) g[s + r] = ok[s + r] ? map[row0 + (s + r) * step] : 0;
          if (ok[s + r]) agg_add(&tab[use_slot<SM>(g[s + r]) * C + c], v[r]);
        }
      }
    } break;
    case SUM_I32: {
      const int* d = static_cast<const int*>(cols.data(c));
      int v[U];
      load_rows<int, U, MAP, PRED>(v, d, row0, step, ok);
#pragma unroll
      for (int r = 0; r < U; ++r) {
        if constexpr (SM == 1) g[r] = ok[r] ? map[row0 + r * step] : 0;
        if (ok[r]) agg_add(&tab[use_slot<SM>(g[r]) * C + c], v[r]);
      }
    } break;
    case COUNT: {
#pragma unroll
      for (int r = 0; r < U; ++r) {
        if constexpr (SM == 1) g[r] = ok[r] ? map[row0 + r * step] : 0;
        if (ok[r]) agg_add(&tab[use_slot<SM>(g[r]) * C + c], 1);
      }
    } break;
  }
}

template <int U, int MAP, int CU, bool PRED, int SLOT, int SUB, class CT>
__device__ __forceinline__ void do_batch(int row0, int step, int n, const int* map, const CT& cols, long long* tab) {
  const int C = cols.n;
  int g[U]; bool ok[U];
#pragma unroll
  for (int r = 0; r < U; ++r) {
    const int row = row0 + r * step;
    ok[r] = PRED ? (row < n) : true;
    if constexpr (SLOT != 1) g[r] = ok[r] ? map[row] : 0;       // U slot loads in flight
    else g[r] = 0;
  }
  int c = 0;
  if constexpr (SLOT == 1) { col_rows<U, MAP, PRED, SUB, 1>(0, row0, step, map, cols, tab, g, ok); c = 1; }
  if constexpr (CU > 1) {
    for (; c + CU <= C; c += CU) {                              // CU columns x U rows per batch
      long long v64[CU][U]; int v32[CU][U];
#pragma unroll
      for (int j = 0; j < CU; ++j) {                            // phase 1: dispatch -> issue loads only
        switch (cols.kind(c + j)) {
          case SUM_I64: load_rows<long long, U, MAP, PRED>(v64[j], static_cast<const long long*>(cols.data(c + j)), row0, step, ok); break;
          case SUM_I32: load_rows<int, U, MAP, PRED>(v32[j], static_cast<const int*>(cols.data(c + j)), row0, step, ok); break;
          default: break;
        }
      }
#pragma unroll
      for (int j = 0; j < CU; ++j) {                            // phase 2: dispatch again -> atomics
        switch (cols.kind(c + j)) {
          case SUM_I64:
#pragma unroll
            for (int r = 0; r < U; ++r) if (ok[r]) agg_add(&tab[use_slot<SLOT>(g[r]) * C + c + j], v64[j][r]);
            break;
          case SUM_I32:
#pragma unroll
            for (int r = 0; r < U; ++r) if (ok[r]) agg_add(&tab[use_slot<SLOT>(g[r]) * C + c + j], v32[j][r]);
            break;
          case COUNT:
#pragma unroll
            for (int r = 0; r < U; ++r) if (ok[r]) agg_add(&tab[use_slot<SLOT>(g[r]) * C + c + j], 1);
            break;
        }
      }
    }
  }
  if constexpr (CU == 0) {                                      // ALL columns (up to MAXC, predicated on j < C) x U rows
    long long v64[MAXC][U]; int v32[MAXC][U];
#pragma unroll
    for (int j = 0; j < MAXC; ++j) {
      if (j < C) switch (cols.kind(j)) {
        case SUM_I64: load_rows<long long, U, MAP, PRED>(v64[j], static_cast<const long long*>(cols.data(j)), row0, step, ok); break;
        case SUM_I32: load_rows<int, U, MAP, PRED>(v32[j], static_cast<const int*>(cols.data(j)), row0, step, ok); break;
        default: break;
      }
    }
#pragma unroll
    for (int j = 0; j < MAXC; ++j) {
      if (j < C) switch (cols.kind(j)) {
        case SUM_I64:
#pragma unroll
          for (int r = 0; r < U; ++r) if (ok[r]) agg_add(&tab[use_slot<SLOT>(g[r]) * C + j], v64[j][r]);
          break;
        case SUM_I32:
#pragma unroll
          for (int r = 0; r < U; ++r) if (ok[r]) agg_add(&tab[use_slot<SLOT>(g[r]) * C + j], v32[j][r]);
          break;
        case COUNT:
#pragma unroll
          for (int r = 0; r < U; ++r) if (ok[r]) agg_add(&tab[use_slot<SLOT>(g[r]) * C + j], 1);
          break;
      }
    }
    c = C;
  }
  for (; c < C; ++c) col_rows<U, MAP, PRED, SUB, SLOT == 2 ? 2 : 0>(c, row0, step, map, cols, tab, g, ok);
}

template <int U, int MAP, int CU, int TAIL, int SLOT, int MINB, int SUB, int PASSV = 0>
__global__ void __launch_bounds__(128, MINB) us_kernel(int n, const int* __restrict__ map, Cols cols_v, const Cols* cols_g, long long* out) {
  const auto cols = acc<PASSV>(cols_v, cols_g);
  extern __shared__ long long tab[];
  init(tab, cols.n);
  const int B = blockDim.x, NB = gridDim.x, tid = threadIdx.x, bi = blockIdx.x;
  const int stride = NB * B * U;                                 // rows consumed by the whole grid per batch
  int row0, step;
  if constexpr (MAP == WARP)        { row0 = bi * B * U + tid;   step = B; }       // row = tile + r*B + tid
  else if constexpr (MAP == GRID)   { row0 = bi * B + tid;       step = NB * B; }  // baseline rows, U at a time
  else                              { row0 = (bi * B + tid) * U; step = 1; }       // U contiguous rows per thread
  if constexpr (TAIL == 0) {
    for (; row0 < n; row0 += stride) do_batch<U, MAP, CU, true, SLOT, SUB>(row0, step, n, map, cols, tab);
  } else {
    for (; row0 + (U - 1) * step < n; row0 += stride) do_batch<U, MAP, CU, false, SLOT, SUB>(row0, step, n, map, cols, tab);
    for (int r = 0; r < U; ++r) {                                // remainder: baseline body, not unrolled
      const int row = row0 + r * step;
      if (row < n) one_row(row, map, cols, tab);
    }
  }
  flush(tab, out, cols.n);
}

// ---------------------------------------------------------------- host
typedef void (*KernelFn)(int, const int*, Cols, const Cols*, long long*);
struct Variant { std::string name; KernelFn fn; };

int main(int argc, char** argv) {
  const std::string spec = argc > 1 ? argv[1] : "LLLLL";
  const int n    = argc > 2 ? atoi(argv[2]) : 3153518;
  int reps       = argc > 3 ? atoi(argv[3]) : 30;
  const char* map_file = (argc > 4 && strcmp(argv[4], "-")) ? argv[4] : nullptr;
  const char* filter = argc > 5 ? argv[5] : nullptr;
  const bool ncu_mode = getenv("NCU") != nullptr;
  int warm = 5;
  if (ncu_mode) { reps = 1; warm = 0; }
  const int C = (int)spec.size();
  if (C < 1 || C > MAXC) { fprintf(stderr, "1..%d columns\n", MAXC); return 1; }

  const double cnt[G] = {1478493, 38854, 157301, 1478870};
  const double tot = cnt[0] + cnt[1] + cnt[2] + cnt[3];
  std::mt19937_64 rng(254);
  std::uniform_real_distribution<double> U01(0, 1);
  std::vector<int> h_map(n);
  if (map_file) {
    FILE* f = fopen(map_file, "r"); if (!f) { perror(map_file); return 1; }
    for (int i = 0; i < n; ++i) if (fscanf(f, "%d", &h_map[i]) != 1) { fprintf(stderr, "map file short\n"); return 1; }
    fclose(f);
  } else {
    for (int i = 0; i < n; ++i) {
      double u = U01(rng) * tot; int g = 0;
      while (g < G - 1 && u >= cnt[g]) { u -= cnt[g]; ++g; }
      h_map[i] = g;
    }
  }

  Cols cols{}; cols.n = C;
  std::vector<long long> ref(G * C, 0);
  std::vector<void*> d_bufs;
  size_t bytes_per_row = sizeof(int);
  const size_t pad = 64;                                         // slack rows (never read by any variant; safety only)
  for (int c = 0; c < C; ++c) {
    const char k = spec[c];
    if (k == 'L') {
      std::vector<long long> h(n);
      std::uniform_int_distribution<long long> d(90000, 10494950);
      for (int i = 0; i < n; ++i) { h[i] = d(rng); ref[h_map[i] * C + c] += h[i]; }
      void* p; CK(cudaMalloc(&p, (n + pad) * 8)); CK(cudaMemcpy(p, h.data(), (size_t)n * 8, cudaMemcpyHostToDevice));
      cols.data[c] = p; cols.kind[c] = SUM_I64; d_bufs.push_back(p); bytes_per_row += 8;
    } else if (k == 'I') {
      std::vector<int> h(n);
      std::uniform_int_distribution<int> d(100, 5000);
      for (int i = 0; i < n; ++i) { h[i] = d(rng); ref[h_map[i] * C + c] += h[i]; }
      void* p; CK(cudaMalloc(&p, (n + pad) * 4)); CK(cudaMemcpy(p, h.data(), (size_t)n * 4, cudaMemcpyHostToDevice));
      cols.data[c] = p; cols.kind[c] = SUM_I32; d_bufs.push_back(p); bytes_per_row += 4;
    } else if (k == 'C') {
      for (int i = 0; i < n; ++i) ref[h_map[i] * C + c] += 1;
      cols.data[c] = nullptr; cols.kind[c] = COUNT;
    } else { fprintf(stderr, "bad col spec char '%c'\n", k); return 1; }
  }
  int* d_map; CK(cudaMalloc(&d_map, (n + pad) * 4)); CK(cudaMemcpy(d_map, h_map.data(), (size_t)n * 4, cudaMemcpyHostToDevice));
  long long* d_out; CK(cudaMalloc(&d_out, G * C * 8));
  const size_t flush_bytes = 96u << 20; void* d_flush; CK(cudaMalloc(&d_flush, flush_bytes));

  Cols* d_cols; CK(cudaMalloc(&d_cols, sizeof(Cols))); CK(cudaMemcpy(d_cols, &cols, sizeof(Cols), cudaMemcpyHostToDevice));
  std::vector<Variant> vars;
  auto add = [&](const char* nm, KernelFn f) { vars.push_back({nm, f}); };
  //                                    U  MAP     CU TAIL SLOT MINB SUB
  add("baseline",                 us_baseline<0>);
  add("naive pragma rows U=4",    us_naive_rows<4>);
  add("naive pragma grid U=4",    us_naive_grid<4>);
  add("naive pragma cols N=4",    us_naive_cols<4>);
  add("rows U=1 warp",            us_kernel<1,  WARP,   1, 0, 0, 0, 0>);
  add("rows U=2 warp",            us_kernel<2,  WARP,   1, 0, 0, 0, 0>);
  add("rows U=3 warp",            us_kernel<3,  WARP,   1, 0, 0, 0, 0>);
  add("rows U=4 warp",            us_kernel<4,  WARP,   1, 0, 0, 0, 0>);
  add("rows U=6 warp",            us_kernel<6,  WARP,   1, 0, 0, 0, 0>);
  add("rows U=8 warp",            us_kernel<8,  WARP,   1, 0, 0, 0, 0>);
  add("rows U=12 warp",           us_kernel<12, WARP,   1, 0, 0, 0, 0>);
  add("rows U=16 warp",           us_kernel<16, WARP,   1, 0, 0, 0, 0>);
  add("rows U=24 warp",           us_kernel<24, WARP,   1, 0, 0, 0, 0>);
  add("rows U=32 warp",           us_kernel<32, WARP,   1, 0, 0, 0, 0>);
  add("rows U=8 warp minb5",      us_kernel<8,  WARP,   1, 0, 0, 5, 0>);
  add("rows U=16 warp minb5",     us_kernel<16, WARP,   1, 0, 0, 5, 0>);
  add("rows U=24 warp minb5",     us_kernel<24, WARP,   1, 0, 0, 5, 0>);
  add("rows U=32 warp minb5",     us_kernel<32, WARP,   1, 0, 0, 5, 0>);
  add("rows U=2 thread",          us_kernel<2,  THREAD, 1, 0, 0, 0, 0>);
  add("rows U=4 thread",          us_kernel<4,  THREAD, 1, 0, 0, 0, 0>);
  add("rows U=8 thread",          us_kernel<8,  THREAD, 1, 0, 0, 0, 0>);
  add("rows U=16 thread",         us_kernel<16, THREAD, 1, 0, 0, 0, 0>);
  add("rows U=2 threadvec rem",   us_kernel<2,  THREADV, 1, 1, 0, 0, 0>);
  add("rows U=4 threadvec rem",   us_kernel<4,  THREADV, 1, 1, 0, 0, 0>);
  add("rows U=8 threadvec rem",   us_kernel<8,  THREADV, 1, 1, 0, 0, 0>);
  add("rows U=16 threadvec rem",  us_kernel<16, THREADV, 1, 1, 0, 0, 0>);
  add("rows U=2 grid",            us_kernel<2,  GRID,   1, 0, 0, 0, 0>);
  add("rows U=4 grid",            us_kernel<4,  GRID,   1, 0, 0, 0, 0>);
  add("rows U=8 grid",            us_kernel<8,  GRID,   1, 0, 0, 0, 0>);
  add("rows U=4 warp rem",        us_kernel<4,  WARP,   1, 1, 0, 0, 0>);
  add("rows U=8 warp rem",        us_kernel<8,  WARP,   1, 1, 0, 0, 0>);
  add("rows U=4 warp lazyslot",   us_kernel<4,  WARP,   1, 0, 1, 0, 0>);
  add("rows U=8 warp lazyslot",   us_kernel<8,  WARP,   1, 0, 1, 0, 0>);
  add("cols CU=2 (U=1)",          us_kernel<1,  WARP,   2, 0, 0, 0, 0>);
  add("cols CU=4 (U=1)",          us_kernel<1,  WARP,   4, 0, 0, 0, 0>);
  add("cols CU=8 (U=1)",          us_kernel<1,  WARP,   8, 0, 0, 0, 0>);
  add("both U=2 x CU=2",          us_kernel<2,  WARP,   2, 0, 0, 0, 0>);
  add("both U=2 x CU=4",          us_kernel<2,  WARP,   4, 0, 0, 0, 0>);
  add("both U=4 x CU=2",          us_kernel<4,  WARP,   2, 0, 0, 0, 0>);
  add("both U=4 x CU=4",          us_kernel<4,  WARP,   4, 0, 0, 0, 0>);
  add("both U=8 x CU=2",          us_kernel<8,  WARP,   2, 0, 0, 0, 0>);
  add("rows U=2 warp defslot",    us_kernel<2,  WARP,   1, 0, 2, 0, 0>);
  add("rows U=4 warp defslot",    us_kernel<4,  WARP,   1, 0, 2, 0, 0>);
  add("rows U=8 warp defslot",    us_kernel<8,  WARP,   1, 0, 2, 0, 0>);
  add("cols CU=4 (U=1) defslot",  us_kernel<1,  WARP,   4, 0, 2, 0, 0>);
  add("cols ALL (U=1)",           us_kernel<1,  WARP,   0, 0, 0, 0, 0>);
  add("cols ALL (U=1) defslot",   us_kernel<1,  WARP,   0, 0, 2, 0, 0>);
  add("both U=2 x ALL",           us_kernel<2,  WARP,   0, 0, 0, 0, 0>);
  add("both U=2 x ALL defslot",   us_kernel<2,  WARP,   0, 0, 2, 0, 0>);
  add("both U=4 x ALL defslot",   us_kernel<4,  WARP,   0, 0, 2, 0, 0>);
  add("rows U=8 warp sub64=4",    us_kernel<8,  WARP,   1, 0, 0, 0, 4>);
  add("rows U=16 warp sub64=4",   us_kernel<16, WARP,   1, 0, 0, 0, 4>);
  add("rows U=16 warp sub64=8",   us_kernel<16, WARP,   1, 0, 0, 0, 8>);
  // "gdesc": column descriptors read from global memory per access (cuDF-like), no stack frame
  add("gdesc baseline",           us_baseline<1>);
  add("gdesc naive rows U=4",     us_naive_rows<4, 1>);
  add("gdesc rows U=1 warp",      us_kernel<1,  WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=2 warp",      us_kernel<2,  WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=3 warp",      us_kernel<3,  WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=4 warp",      us_kernel<4,  WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=6 warp",      us_kernel<6,  WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=8 warp",      us_kernel<8,  WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=12 warp",     us_kernel<12, WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=16 warp",     us_kernel<16, WARP,   1, 0, 0, 0, 0, 1>);
  add("gdesc rows U=4 warp rem",  us_kernel<4,  WARP,   1, 1, 0, 0, 0, 1>);
  add("gdesc rows U=4 threadvec", us_kernel<4,  THREADV,1, 1, 0, 0, 0, 1>);
  add("gdesc rows U=8 threadvec", us_kernel<8,  THREADV,1, 1, 0, 0, 0, 1>);
  add("gdesc cols CU=2 (U=1)",    us_kernel<1,  WARP,   2, 0, 0, 0, 0, 1>);
  add("gdesc cols CU=4 (U=1)",    us_kernel<1,  WARP,   4, 0, 0, 0, 0, 1>);
  add("gdesc cols ALL (U=1)",     us_kernel<1,  WARP,   0, 0, 0, 0, 0, 1>);
  add("gdesc both U=2 x ALL",     us_kernel<2,  WARP,   0, 0, 0, 0, 0, 1>);
  add("gdesc both U=4 x CU=2",    us_kernel<4,  WARP,   2, 0, 0, 0, 0, 1>);

  const dim3 grid(240), block(128);
  const size_t smem = G * C * sizeof(long long);
  const double bytes = double(n) * bytes_per_row;
  cudaDeviceProp prop; CK(cudaGetDeviceProperties(&prop, 0));
  printf("# %s | rows=%d cols=%s bytes/row=%zu input=%.1f MB | grid=%u x %u | reps=%d (median, L2 flushed)%s\n",
         prop.name, n, spec.c_str(), bytes_per_row, bytes / 1e6, grid.x, block.x, reps, map_file ? " | real q1 groups" : "");
  printf("# floor @672 GB/s = %.1f us\n", bytes / 672e3);
  printf("%-26s %5s %10s %10s %7s %8s %7s %s\n", "variant", "regs", "median_us", "min_us", "GB/s", "speedup", "%floor", "check");

  cudaEvent_t e0, e1; CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1));
  double base_us = 0;
  for (auto& v : vars) {
    if (filter && v.name.find(filter) == std::string::npos && v.name != "baseline") continue;
    if (filter && ncu_mode && v.name == "baseline" && std::string("baseline").find(filter) == std::string::npos) continue;
    cudaFuncAttributes fa; CK(cudaFuncGetAttributes(&fa, (const void*)v.fn));
    std::vector<float> ts;
    bool ok = true;
    for (int it = 0; it < reps + warm; ++it) {
      CK(cudaMemsetAsync(d_flush, it & 0xff, flush_bytes));
      CK(cudaMemsetAsync(d_out, 0, G * C * 8));
      CK(cudaEventRecord(e0));
      v.fn<<<grid, block, smem>>>(n, d_map, cols, d_cols, d_out);
      CK(cudaEventRecord(e1));
      CK(cudaEventSynchronize(e1));
      CK(cudaGetLastError());
      float ms; CK(cudaEventElapsedTime(&ms, e0, e1));
      if (it >= warm) ts.push_back(ms * 1000.f);
      if (it == 0 || it == reps + warm - 1) {
        std::vector<long long> h_out(G * C);
        CK(cudaMemcpy(h_out.data(), d_out, G * C * 8, cudaMemcpyDeviceToHost));
        ok = ok && (h_out == ref);
      }
    }
    std::sort(ts.begin(), ts.end());
    const double med = ts[ts.size() / 2], mn = ts[0];
    if (base_us == 0) base_us = med;
    printf("%-26s %5d %10.1f %10.1f %7.1f %7.2fx %6.1f%% %s\n", v.name.c_str(), fa.numRegs, med, mn,
           bytes / med / 1e3, base_us / med, 100.0 * (bytes / med / 1e3) / 672.0, ok ? "OK" : "MISMATCH");
    fflush(stdout);
  }
  for (void* p : d_bufs) cudaFree(p);
  cudaFree(d_cols); cudaFree(d_map); cudaFree(d_out); cudaFree(d_flush);
  return 0;
}
