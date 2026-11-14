// Microbenchmark: cuDF-style single_pass_shmem_aggs_kernel inner loop vs. a fixed-unroll version.
//
// Models the aggregation half of TPC-H Q1's hash group-by on Sirius/cuDF (RTX 5070 profile):
//   * input = the filtered lineitem rows (SF1: 3,153,518) with a precomputed group slot per row
//     (what groupby::mapping_indices_kernel produces), group sizes taken from the real Q1 output;
//   * C value columns, runtime-described (kind + width), summed per group into a shared-memory table;
//   * 240 CTAs x 128 threads (the launch ncu recorded), table flushed to global with atomics.
//
// baseline : grid-stride, ONE row per iteration; runtime column loop; per row+column type switch;
//            load -> generic system-scope atomicAdd into shared memory (ncu SASS showed
//            LD.E.64 -> ATOM.E.ADD.64.STRONG.SYS). The atomic waits on its own load.
// unroll<U>: same runtime column loop, same atomic flavour, but each thread takes U rows per
//            batch (warp-striped, coalesced): load U slot ids, then per column issue U loads,
//            one wait, U atomics. Type switch once per U rows per column.
// unroll<U>+atoms : extra variant, as unroll<U> but with native shared atomics (address space known).
//
// Build: nvcc -O3 -std=c++17 -arch=sm_120 -lineinfo groupby_unroll_bench.cu -o groupby_unroll_bench
// Usage: ./groupby_unroll_bench [col_spec=LLLL] [rows=3153518] [reps=50] [group_id_file]
//        group_id_file: real Q1 row->group ids in table order (q1_groups.csv, made by make_q1_groups.sh)
//        col_spec chars: L = SUM int64, I = SUM int32 (int64 accumulator), C = COUNT (no load)
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <vector>
#include <string>
#include <random>
#include <algorithm>
#include <cuda_runtime.h>

#define CK(x) do { cudaError_t e_ = (x); if (e_ != cudaSuccess) { \
  fprintf(stderr, "CUDA error %s at %s:%d\n", cudaGetErrorString(e_), __FILE__, __LINE__); exit(1); } } while (0)

constexpr int MAXC = 8;
constexpr int G = 4;               // Q1: (A,F) (N,F) (N,O) (R,F)
enum Kind : int { SUM_I64 = 0, SUM_I32 = 1, COUNT = 2 };

struct Cols { const void* data[MAXC]; int kind[MAXC]; int n; };

// Hide the address space so the atomic is emitted as a generic ATOM (as in cuDF's kernel),
// not ATOMS. Also prevents the compiler from proving the table doesn't alias the inputs.
__device__ __forceinline__ unsigned long long* generic_ptr(long long* p) {
  asm volatile("" : "+l"(p));
  return reinterpret_cast<unsigned long long*>(p);
}

template <bool NATIVE_SHARED>
__device__ __forceinline__ void agg_add(long long* slot, long long v) {
  if constexpr (NATIVE_SHARED) atomicAdd(reinterpret_cast<unsigned long long*>(slot), (unsigned long long)v);
  else                          atomicAdd_system(generic_ptr(slot), (unsigned long long)v);
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

// ---------------------------------------------------------------- baseline (cuDF-like)
__global__ void __launch_bounds__(128) baseline_kernel(int n, const int* __restrict__ map, Cols cols, long long* out) {
  extern __shared__ long long tab[];
  const int C = cols.n;
  init(tab, C);
  for (int row = blockIdx.x * blockDim.x + threadIdx.x; row < n; row += gridDim.x * blockDim.x) {
    const int slot = map[row];
    for (int c = 0; c < C; ++c) {
      long long* dst = &tab[slot * C + c];
      switch (cols.kind[c]) {                                   // dispatch per row per column
        case SUM_I64: agg_add<false>(dst, static_cast<const long long*>(cols.data[c])[row]); break;
        case SUM_I32: agg_add<false>(dst, static_cast<const int*>(cols.data[c])[row]); break;
        case COUNT:   agg_add<false>(dst, 1); break;
      }
    }
  }
  flush(tab, out, C);
}

// ---------------------------------------------------------------- fixed unroll U
template <int U, bool NATIVE_SHARED>
__global__ void __launch_bounds__(128) unroll_kernel(int n, const int* __restrict__ map, Cols cols, long long* out) {
  extern __shared__ long long tab[];
  const int C = cols.n;
  init(tab, C);
  const int tile = blockDim.x * U;
  for (int base = blockIdx.x * tile; base < n; base += gridDim.x * tile) {
    int g[U]; bool ok[U];
#pragma unroll
    for (int r = 0; r < U; ++r) {                               // U slot loads in flight
      const int row = base + r * blockDim.x + threadIdx.x;     // warp-striped -> coalesced
      ok[r] = row < n;
      g[r] = ok[r] ? map[row] : 0;
    }
    for (int c = 0; c < C; ++c) {                               // runtime column loop
      switch (cols.kind[c]) {                                   // dispatch once per U rows
        case SUM_I64: {
          const long long* d = static_cast<const long long*>(cols.data[c]);
          long long v[U];
#pragma unroll
          for (int r = 0; r < U; ++r) v[r] = ok[r] ? d[base + r * blockDim.x + threadIdx.x] : 0;  // U loads
#pragma unroll
          for (int r = 0; r < U; ++r) if (ok[r]) agg_add<NATIVE_SHARED>(&tab[g[r] * C + c], v[r]);
        } break;
        case SUM_I32: {
          const int* d = static_cast<const int*>(cols.data[c]);
          int v[U];
#pragma unroll
          for (int r = 0; r < U; ++r) v[r] = ok[r] ? d[base + r * blockDim.x + threadIdx.x] : 0;
#pragma unroll
          for (int r = 0; r < U; ++r) if (ok[r]) agg_add<NATIVE_SHARED>(&tab[g[r] * C + c], v[r]);
        } break;
        case COUNT: {
#pragma unroll
          for (int r = 0; r < U; ++r) if (ok[r]) agg_add<NATIVE_SHARED>(&tab[g[r] * C + c], 1);
        } break;
      }
    }
  }
  flush(tab, out, C);
}

// ---------------------------------------------------------------- cuDF-style dispatch
// cuDF's kernel reads each column's 64-byte column_device_view from global memory and runs
// type_dispatcher (a binary-search switch over cudf::type_id) for every row x column; ncu SASS
// shows this as LDG.E type_id (stride 0x40) + ISETP.GT chains against 0xe/0x15/0x18/0x1a.
struct ColDesc { int type_id; int pad0; const void* data; char pad[48]; };   // 64 B, like column_device_view
static_assert(sizeof(ColDesc) == 64, "64B descriptor");
enum TypeId : int { INT8 = 1, INT16, INT32, INT64, UINT8, UINT16, UINT32, UINT64, FLOAT32, FLOAT64, BOOL8,
                    TS_D, TS_S, TS_MS, TS_US, TS_NS, DUR_D, DUR_S, DUR_MS, DUR_US, DUR_NS,
                    DICT32, STRING, LIST, DEC32, DEC64, DEC128, STRUCT };

#define CUDF_TYPE_SWITCH(tid, F)                                                                   \
  switch (tid) {                                                                                   \
    case INT8: F(int8_t); break;     case INT16: F(int16_t); break;   case INT32: F(int32_t); break; \
    case INT64: F(long long); break; case UINT8: F(uint8_t); break;   case UINT16: F(uint16_t); break; \
    case UINT32: F(uint32_t); break; case UINT64: F(unsigned long long); break;                    \
    case FLOAT32: F(float); break;   case FLOAT64: F(double); break;  case BOOL8: F(bool); break;  \
    case TS_D: F(int32_t); break;    case TS_S: F(long long); break;  case TS_MS: F(long long); break; \
    case TS_US: F(long long); break; case TS_NS: F(long long); break; case DUR_D: F(int32_t); break; \
    case DUR_S: F(long long); break; case DUR_MS: F(long long); break; case DUR_US: F(long long); break; \
    case DUR_NS: F(long long); break; case DEC32: F(int32_t); break;  case DEC64: F(long long); break; \
    default: break;                                                                                \
  }

__global__ void __launch_bounds__(128) cudf_dispatch_baseline(int n, const int* __restrict__ map,
                                                              const ColDesc* descs, int C, long long* out) {
  extern __shared__ long long tab[];
  init(tab, C);
  for (int row = blockIdx.x * blockDim.x + threadIdx.x; row < n; row += gridDim.x * blockDim.x) {
    const int slot = map[row];
    for (int c = 0; c < C; ++c) {
      const ColDesc* cd = &descs[c];                           // descriptor load per row x column
      long long* dst = &tab[slot * C + c];
#define ADD1(T) agg_add<false>(dst, (long long)static_cast<const T*>(cd->data)[row])
      CUDF_TYPE_SWITCH(cd->type_id, ADD1)                     // dispatch per row x column
#undef ADD1
    }
  }
  flush(tab, out, C);
}

template <int U>
__global__ void __launch_bounds__(128) cudf_dispatch_unroll(int n, const int* __restrict__ map,
                                                            const ColDesc* descs, int C, long long* out) {
  extern __shared__ long long tab[];
  init(tab, C);
  const int tile = blockDim.x * U;
  for (int base = blockIdx.x * tile; base < n; base += gridDim.x * tile) {
    int g[U]; bool ok[U];
#pragma unroll
    for (int r = 0; r < U; ++r) {
      const int row = base + r * blockDim.x + threadIdx.x;
      ok[r] = row < n;
      g[r] = ok[r] ? map[row] : 0;
    }
    for (int c = 0; c < C; ++c) {
      const ColDesc* cd = &descs[c];                           // descriptor load once per U rows
#define ADDU(T) {                                                                                  \
        const T* p = static_cast<const T*>(cd->data); T v[U];                                      \
        _Pragma("unroll") for (int r = 0; r < U; ++r) v[r] = ok[r] ? p[base + r * blockDim.x + threadIdx.x] : (T)0; \
        _Pragma("unroll") for (int r = 0; r < U; ++r) if (ok[r]) agg_add<false>(&tab[g[r] * C + c], (long long)v[r]); }
      CUDF_TYPE_SWITCH(cd->type_id, ADDU)                     // dispatch once per U rows x column
#undef ADDU
    }
  }
  flush(tab, out, C);
}

// ---------------------------------------------------------------- host
#include <functional>
typedef void (*KernelFn)(int, const int*, Cols, long long*);
typedef void (*DispFn)(int, const int*, const ColDesc*, int, long long*);
struct Variant { std::string name; const void* fn; std::function<void(dim3, dim3, size_t)> launch; };

int main(int argc, char** argv) {
  const std::string spec = argc > 1 ? argv[1] : "LLLL";
  const int n    = argc > 2 ? atoi(argv[2]) : 3153518;
  const int reps = argc > 3 ? atoi(argv[3]) : 50;
  const int C = (int)spec.size();
  if (C < 1 || C > MAXC) { fprintf(stderr, "1..%d columns\n", MAXC); return 1; }

  // Group slots with the real Q1 SF1 group sizes (shipdate <= 1995-08-19).
  const double cnt[G] = {1478493, 38854, 157301, 1478870};
  const double tot = cnt[0] + cnt[1] + cnt[2] + cnt[3];
  std::mt19937_64 rng(254);
  std::uniform_real_distribution<double> U01(0, 1);
  std::vector<int> h_map(n);
  const char* map_file = argc > 4 ? argv[4] : nullptr;   // optional: real per-row group ids, one per line
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
  for (int c = 0; c < C; ++c) {
    const char k = spec[c];
    if (k == 'L') {
      std::vector<long long> h(n);
      std::uniform_int_distribution<long long> d(90000, 10494950);       // l_extendedprice in cents
      for (int i = 0; i < n; ++i) { h[i] = d(rng); ref[h_map[i] * C + c] += h[i]; }
      void* p; CK(cudaMalloc(&p, n * 8)); CK(cudaMemcpy(p, h.data(), n * 8, cudaMemcpyHostToDevice));
      cols.data[c] = p; cols.kind[c] = SUM_I64; d_bufs.push_back(p); bytes_per_row += 8;
    } else if (k == 'I') {
      std::vector<int> h(n);
      std::uniform_int_distribution<int> d(100, 5000);                    // l_quantity * 100
      for (int i = 0; i < n; ++i) { h[i] = d(rng); ref[h_map[i] * C + c] += h[i]; }
      void* p; CK(cudaMalloc(&p, n * 4)); CK(cudaMemcpy(p, h.data(), n * 4, cudaMemcpyHostToDevice));
      cols.data[c] = p; cols.kind[c] = SUM_I32; d_bufs.push_back(p); bytes_per_row += 4;
    } else if (k == 'C') {
      for (int i = 0; i < n; ++i) ref[h_map[i] * C + c] += 1;
      cols.data[c] = nullptr; cols.kind[c] = COUNT;
    } else { fprintf(stderr, "bad col spec char '%c'\n", k); return 1; }
  }
  int* d_map; CK(cudaMalloc(&d_map, n * 4)); CK(cudaMemcpy(d_map, h_map.data(), n * 4, cudaMemcpyHostToDevice));
  long long* d_out; CK(cudaMalloc(&d_out, G * C * 8));
  // L2 flush buffer (2x the 5070's 48 MB L2) so every rep reads from DRAM.
  const size_t flush_bytes = 96u << 20; void* d_flush; CK(cudaMalloc(&d_flush, flush_bytes));

  // cuDF-style descriptors (COUNT columns have no data and are not part of this path)
  std::vector<ColDesc> h_desc;
  for (int c = 0; c < C; ++c)
    if (cols.kind[c] != COUNT) { ColDesc d{}; d.type_id = cols.kind[c] == SUM_I64 ? INT64 : INT32; d.data = cols.data[c]; h_desc.push_back(d); }
  const bool disp_ok = (int)h_desc.size() == C;
  ColDesc* d_desc; CK(cudaMalloc(&d_desc, sizeof(ColDesc) * MAXC));
  if (!h_desc.empty()) CK(cudaMemcpy(d_desc, h_desc.data(), sizeof(ColDesc) * h_desc.size(), cudaMemcpyHostToDevice));

  std::vector<Variant> vars;
  auto addK = [&](const char* nm, KernelFn f) {
    vars.push_back({nm, (const void*)f, [=](dim3 g, dim3 b, size_t s) { f<<<g, b, s>>>(n, d_map, cols, d_out); }});
  };
  auto addD = [&](const char* nm, DispFn f) {
    vars.push_back({nm, (const void*)f, [=](dim3 g, dim3 b, size_t s) { f<<<g, b, s>>>(n, d_map, d_desc, C, d_out); }});
  };
  addK("baseline (simple sw)", baseline_kernel);
  addK("unroll U=1",           unroll_kernel<1,  false>);
  addK("unroll U=2",           unroll_kernel<2,  false>);
  addK("unroll U=4",           unroll_kernel<4,  false>);
  addK("unroll U=8",           unroll_kernel<8,  false>);
  addK("unroll U=16",          unroll_kernel<16, false>);
  addK("unroll U=8 +ATOMS",    unroll_kernel<8,  true>);
  if (disp_ok) {
    addD("cudf-disp baseline", cudf_dispatch_baseline);
    addD("cudf-disp U=4",      cudf_dispatch_unroll<4>);
    addD("cudf-disp U=8",      cudf_dispatch_unroll<8>);
  }

  const dim3 grid(240), block(128);
  const size_t smem = G * C * sizeof(long long);
  const double bytes = double(n) * bytes_per_row;
  cudaDeviceProp prop; CK(cudaGetDeviceProperties(&prop, 0));
  printf("# %s | rows=%d cols=%s bytes/row=%zu input=%.1f MB | grid=%u x %u | reps=%d (median, L2 flushed)\n",
         prop.name, n, spec.c_str(), bytes_per_row, bytes / 1e6, grid.x, block.x, reps);
  printf("# floor @672 GB/s = %.1f us\n", bytes / 672e3);
  printf("%-22s %6s %10s %10s %8s %8s %s\n", "variant", "regs", "median_us", "min_us", "GB/s", "speedup", "check");

  cudaEvent_t e0, e1; CK(cudaEventCreate(&e0)); CK(cudaEventCreate(&e1));
  double base_us = 0;
  for (auto& v : vars) {
    cudaFuncAttributes fa; CK(cudaFuncGetAttributes(&fa, v.fn));
    std::vector<float> ts;
    bool ok = true;
    for (int it = 0; it < reps + 5; ++it) {
      CK(cudaMemsetAsync(d_flush, it & 0xff, flush_bytes));
      CK(cudaMemsetAsync(d_out, 0, G * C * 8));
      CK(cudaEventRecord(e0));
      v.launch(grid, block, smem);
      CK(cudaEventRecord(e1));
      CK(cudaEventSynchronize(e1));
      CK(cudaGetLastError());
      float ms; CK(cudaEventElapsedTime(&ms, e0, e1));
      if (it >= 5) ts.push_back(ms * 1000.f);
      if (it == 0) {
        std::vector<long long> h_out(G * C);
        CK(cudaMemcpy(h_out.data(), d_out, G * C * 8, cudaMemcpyDeviceToHost));
        ok = (h_out == ref);
      }
    }
    std::sort(ts.begin(), ts.end());
    const double med = ts[ts.size() / 2], mn = ts[0];
    if (base_us == 0) base_us = med;
    printf("%-22s %6d %10.1f %10.1f %8.1f %7.2fx %s\n", v.name.c_str(), fa.numRegs, med, mn,
           bytes / med / 1e3, base_us / med, ok ? "OK" : "MISMATCH");
  }
  for (void* p : d_bufs) cudaFree(p);
  cudaFree(d_map); cudaFree(d_out); cudaFree(d_flush); cudaFree(d_desc);
  return 0;
}
