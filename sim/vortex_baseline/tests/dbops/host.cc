// Host driver for the general database sub-operator kernels (kernel.cl) on Vortex simx via PoCL.
//
//   dbops -d <data dir> -o <out dir> -c <cores> -w <warps> <op> [op params]
//
// Ops (micro-suite, one operator alone; inputs uploaded functionally, i.e. untimed, as resident columns):
//   empty <k>            k launches of an empty kernel with one work-group, then k with all resident threads
//   pred_i16 | pred_i32  l_shipdate <= 10471 (2 B) | l_quantity < 2400 (4 B) -> 1 B mask
//   range_i16            l_shipdate in [8766, 9130] -> mask (two compares)
//   mask_and             AND of two 1 B masks
//   filter_conj          3-term conjunctive range filter (Q6 predicate shape) -> mask, one pass
//   compact <q>          mask (l_quantity <= q*100) -> count -> scan -> scatter -> int32 row indices
//   gather_i32 <q> | gather_i64 <q>   rows selected by l_quantity <= q*100: gather l_extendedprice (4 B / 8 B)
//   cast                 l_extendedprice int32 -> int64
//   mul                  int64 x int64 -> int64 (l_extendedprice * l_discount, both widened on the host)
//   reduce_i32 | reduce_i64 | minmax_i64   sum / min-max of one column (block partials + final)
//   groupby              keys (l_returnflag, l_linestatus) strings; SUM of 3 int64 columns + COUNT
//   probe <k>            l_quantity IN (k sorted constants) -> mask
// Chains (sub-operator sequence derived from the Sirius traces; one batch = the whole table):
//   chain_q6, chain_q1
//
// For every kernel launch the program prints, in launch order,
//   LAUNCH <i> <kernel> <tag> items=<n> lbytes=<logical bytes read+written>
// and for every host step "HOST <what> bytes=<n>". The simulator writes one RUN/FLUSH record per launch
// to $VX_LAUNCH_LOG in the same order. Results go to <out dir> for verification (verify.py).
#include <CL/opencl.h>
#include <unistd.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#define CL_CHECK(_expr)                                                    \
  do {                                                                     \
    cl_int _err = _expr;                                                   \
    if (_err != CL_SUCCESS) {                                              \
      printf("OpenCL Error: '%s' returned %d!\n", #_expr, (int)_err);     \
      exit(-1);                                                            \
    }                                                                      \
  } while (0)

static const int WG = 256, IPT = 8, TILE = WG * IPT;

struct Buf {
  cl_mem m = nullptr;
  size_t bytes = 0;
};

static cl_context g_ctx;
static cl_command_queue g_q;
static cl_program g_prog;
static std::map<std::string, cl_kernel> g_k;
static int g_launch = 0;
static size_t g_threads = 1024;   // resident hardware threads = cores * warps * 32
static std::string g_data, g_out;

static std::vector<cl_mem> g_all;   // released at exit so the runtime prints its MPM report
static Buf mk(size_t bytes, const void* host = nullptr) {
  Buf b;
  b.bytes = bytes ? bytes : 8;
  cl_int err;
  b.m = clCreateBuffer(g_ctx, CL_MEM_READ_WRITE, b.bytes, nullptr, &err);
  CL_CHECK(err);
  g_all.push_back(b.m);
  if (host) CL_CHECK(clEnqueueWriteBuffer(g_q, b.m, CL_TRUE, 0, bytes, host, 0, nullptr, nullptr));
  return b;
}
template <typename T>
static void rd(const Buf& b, std::vector<T>& v, size_t count, const char* what) {
  v.resize(count);
  if (count) CL_CHECK(clEnqueueReadBuffer(g_q, b.m, CL_TRUE, 0, count * sizeof(T), v.data(), 0, nullptr, nullptr));
  printf("HOST %s bytes=%zu\n", what, count * sizeof(T));
}

template <typename T>
static std::vector<T> load(const std::string& name) {
  std::ifstream f(g_data + "/" + name, std::ios::binary);
  if (!f) { printf("cannot open %s\n", name.c_str()); exit(2); }
  std::vector<char> raw((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
  std::vector<T> v(raw.size() / sizeof(T));
  memcpy(v.data(), raw.data(), v.size() * sizeof(T));
  return v;
}
template <typename T>
static void save(const std::string& name, const std::vector<T>& v) {
  std::ofstream f(g_out + "/" + name, std::ios::binary);
  f.write((const char*)v.data(), v.size() * sizeof(T));
}

// kernel args
static void setargs(cl_kernel, int) {}
template <typename T, typename... R>
static void setargs(cl_kernel k, int i, const T& a, const R&... r) {
  CL_CHECK(clSetKernelArg(k, i, sizeof(T), &a));
  setargs(k, i + 1, r...);
}
static cl_kernel kern(const char* name) {
  auto it = g_k.find(name);
  if (it != g_k.end()) return it->second;
  cl_int err;
  cl_kernel k = clCreateKernel(g_prog, name, &err);
  CL_CHECK(err);
  g_k[name] = k;
  return k;
}
static size_t grid_stride(size_t n) {   // one work-item per resident thread, never more than needed
  size_t need = ((n + WG - 1) / WG) * WG;
  return std::max<size_t>(WG, std::min(g_threads, need));
}
template <typename... A>
static void launch(const char* name, const char* tag, size_t gsize, size_t items, size_t lbytes, const A&... a) {
  cl_kernel k = kern(name);
  setargs(k, 0, a...);
  size_t l = WG;
  CL_CHECK(clEnqueueNDRangeKernel(g_q, k, 1, nullptr, &gsize, &l, 0, nullptr, nullptr));
  CL_CHECK(clFinish(g_q));
  printf("LAUNCH %d %s %s items=%zu lbytes=%zu\n", g_launch++, name, tag, items, lbytes);
  fflush(stdout);
}
static void launch0(const char* name, const char* tag, size_t g = WG) {   // no-argument kernel
  cl_kernel k = kern(name);
  size_t l = WG;
  CL_CHECK(clEnqueueNDRangeKernel(g_q, k, 1, nullptr, &g, &l, 0, nullptr, nullptr));
  CL_CHECK(clFinish(g_q));
  printf("LAUNCH %d %s %s items=0 lbytes=0\n", g_launch++, name, tag);
  fflush(stdout);
}

// ------------------------------------------------------------------ sub-operators (host side of libcudf calls)
// apply_boolean_mask: count -> scan (+ host read of the count) -> scatter
static Buf compact(const Buf& mask, int n, int* out_count, const char* tag) {
  int nch = (int)(g_threads / WG);   // one work-group per resident work-group slot, each a contiguous chunk
  Buf counts = mk(nch * 4), offs = mk(nch * 4), total = mk(4);
  launch("mask_count", tag, (size_t)nch * WG, n, (size_t)n + nch * 4, mask.m, n, counts.m);
  launch("scan_tiles", tag, WG, nch, (size_t)nch * 8 + 4, counts.m, nch, offs.m, total.m);
  std::vector<int> c;
  rd(total, c, 1, "readback_count");
  *out_count = c[0];
  Buf idx = mk((size_t)c[0] * 4);
  launch("mask_scatter", tag, (size_t)nch * WG, n, (size_t)n + nch * 4 + (size_t)c[0] * 4, mask.m, n, offs.m, idx.m);
  return idx;
}
// exclusive scan of int lengths into n+1 offsets; returns total (host read-back, as cuDF strings do)
static Buf scan_offsets(const Buf& lens, int n, int* total_out, const char* tag) {
  int nch = (int)(g_threads / WG);
  Buf sums = mk(nch * 4), offs = mk(nch * 4), total = mk(4), out = mk((size_t)(n + 1) * 4);
  launch("tile_sum_i32", tag, (size_t)nch * WG, n, (size_t)n * 4 + nch * 4, lens.m, n, sums.m);
  launch("scan_tiles", tag, WG, nch, (size_t)nch * 8 + 4, sums.m, nch, offs.m, total.m);
  std::vector<int> t;
  rd(total, t, 1, "readback_chars_size");
  *total_out = t[0];
  launch("tile_scan_apply_i32", tag, (size_t)nch * WG, n, (size_t)n * 8 + nch * 4 + 4, lens.m, n, offs.m, total.m, out.m);
  return out;
}
struct Str { Buf off, chars; int n = 0, nchars = 0; };
static Str str_gather(const Str& s, const Buf& idx, int m, const char* tag) {
  Buf lens = mk((size_t)m * 4);
  launch("str_gather_len", tag, grid_stride(m), m, (size_t)m * 4 + (size_t)m * 8 + (size_t)m * 4, s.off.m, idx.m, lens.m, m);
  Str r;
  r.n = m;
  r.off = scan_offsets(lens, m, &r.nchars, tag);
  r.chars = mk(r.nchars);
  launch("str_gather_chars", tag, grid_stride(m), m, (size_t)m * 4 + (size_t)m * 8 + (size_t)m * 4 + 2 * (size_t)r.nchars,
         s.off.m, s.chars.m, idx.m, r.off.m, r.chars.m, m);
  return r;
}
static Buf gather(const char* kname, const Buf& src, int esize, const Buf& idx, int m, const char* tag) {
  Buf out = mk((size_t)m * esize);
  launch(kname, tag, grid_stride(m), m, (size_t)m * (4 + 2 * esize), src.m, idx.m, out.m, m);
  return out;
}
static Buf cast64(const Buf& in, int n, const char* tag) {
  Buf out = mk((size_t)n * 8);
  launch("cast_i32_i64", tag, grid_stride(n), n, (size_t)n * 12, in.m, out.m, n);
  return out;
}
static Buf binop(const Buf& a, const Buf& b, int n, int op, const char* tag) {
  Buf out = mk((size_t)n * 8);
  launch("binop_i64", tag, grid_stride(n), n, (size_t)n * 24, a.m, b.m, out.m, n, op);
  return out;
}
static Buf binop_s(long x, const Buf& b, int n, int op, const char* tag) {
  Buf out = mk((size_t)n * 8);
  cl_long xs = x;
  launch("binop_s_i64", tag, grid_stride(n), n, (size_t)n * 16, xs, b.m, out.m, n, op);
  return out;
}
static long reduce_sum(const char* kname, const Buf& in, int esize, int n, const char* tag) {
  size_t g = g_threads;
  int np = (int)(g / WG);
  Buf part = mk(np * 8), out = mk(8);
  launch(kname, tag, g, n, (size_t)n * esize + np * 8, in.m, n, part.m);
  launch("reduce_sum_final", tag, WG, np, np * 8 + 8, part.m, np, out.m);
  std::vector<cl_long> r;
  rd(out, r, 1, "readback_scalar");
  return r[0];
}
static std::pair<long, long> reduce_minmax(const Buf& in, int n, const char* tag) {
  size_t g = g_threads;
  int np = (int)(g / WG);
  Buf part = mk(np * 16), out = mk(16);
  launch("reduce_minmax_i64", tag, g, n, (size_t)n * 8 + np * 16, in.m, n, part.m);
  launch("reduce_minmax_final", tag, WG, np, np * 16 + 16, part.m, np, out.m);
  std::vector<cl_long> r;
  rd(out, r, 2, "readback_minmax");
  return {r[0], r[1]};
}
// hash group-by on up to two string keys, SUM of nv int64 columns + COUNT(*)
struct GB { std::vector<int> table; std::vector<cl_long> acc; int tsize = 0, nv = 0; };
static GB groupby(const Str& k0, const Str* k1, int n, const std::vector<Buf>& vals, const char* tag) {
  GB r;
  r.tsize = 16;   // power of two >= 2x the expected <= 8 groups (cuco sizes by the row count; see notes)
  r.nv = (int)vals.size();
  int w = r.nv + 1;
  Buf table = mk(r.tsize * 4), slots = mk((size_t)n * 4), acc = mk((size_t)r.tsize * w * 8), dummy = mk(8);
  launch("fill_i32", tag, WG, r.tsize, r.tsize * 4, table.m, (cl_int)-1, r.tsize);
  launch("fill_i64", tag, WG, r.tsize * w, r.tsize * w * 8, acc.m, (cl_long)0, r.tsize * w);
  int nkeys = k1 ? 2 : 1;
  const Str& kk1 = k1 ? *k1 : k0;
  launch("gb_map_str", tag, grid_stride(n), n, (size_t)n * (8 + 1) * nkeys + (size_t)n * 4, k0.off.m, k0.chars.m, kk1.off.m,
         kk1.chars.m, nkeys, n, table.m, r.tsize, slots.m);
  cl_mem v[6];
  for (int i = 0; i < 6; ++i) v[i] = (i < r.nv) ? vals[i].m : dummy.m;
  launch("gb_agg_sum", tag, grid_stride(n), n, (size_t)n * 4 + (size_t)n * 8 * r.nv, slots.m, n, r.tsize, r.nv, v[0], v[1],
         v[2], v[3], v[4], v[5], acc.m);
  rd(table, r.table, r.tsize, "readback_groupby_table");
  rd(acc, r.acc, (size_t)r.tsize * w, "readback_groupby_acc");
  return r;
}

// ------------------------------------------------------------------ resident columns
struct Table {
  int n = 0;
  std::vector<int16_t> shipdate;
  std::vector<int32_t> qty, price, disc, tax;
  std::vector<int32_t> rf_off, ls_off;
  std::vector<uint8_t> rf_ch, ls_ch;
  Buf b_shipdate, b_qty, b_price, b_disc, b_tax;
  Str rf, ls;
};
static Table T;
static void load_table(bool strings) {
  T.shipdate = load<int16_t>("l_shipdate.bin");
  T.qty = load<int32_t>("l_quantity.bin");
  T.price = load<int32_t>("l_extendedprice.bin");
  T.disc = load<int32_t>("l_discount.bin");
  T.tax = load<int32_t>("l_tax.bin");
  T.n = (int)T.shipdate.size();
  T.b_shipdate = mk(T.n * 2, T.shipdate.data());
  T.b_qty = mk(T.n * 4, T.qty.data());
  T.b_price = mk(T.n * 4, T.price.data());
  T.b_disc = mk(T.n * 4, T.disc.data());
  T.b_tax = mk(T.n * 4, T.tax.data());
  if (strings) {
    T.rf_off = load<int32_t>("l_returnflag.off.bin");
    T.rf_ch = load<uint8_t>("l_returnflag.chars.bin");
    T.ls_off = load<int32_t>("l_linestatus.off.bin");
    T.ls_ch = load<uint8_t>("l_linestatus.chars.bin");
    T.rf = {mk(T.rf_off.size() * 4, T.rf_off.data()), mk(T.rf_ch.size(), T.rf_ch.data()), T.n, (int)T.rf_ch.size()};
    T.ls = {mk(T.ls_off.size() * 4, T.ls_off.data()), mk(T.ls_ch.size(), T.ls_ch.data()), T.n, (int)T.ls_ch.size()};
  }
  printf("TABLE rows=%d\n", T.n);
}
static std::vector<uint8_t> host_mask_qty_le(int q100) {
  std::vector<uint8_t> m(T.n);
  for (int i = 0; i < T.n; ++i) m[i] = T.qty[i] <= q100;
  return m;
}
static std::vector<int> host_idx(const std::vector<uint8_t>& m) {
  std::vector<int> v;
  for (int i = 0; i < (int)m.size(); ++i) if (m[i]) v.push_back(i);
  return v;
}
static std::vector<cl_long> widen(const std::vector<int32_t>& a) { return std::vector<cl_long>(a.begin(), a.end()); }
template <typename T>
static std::vector<T> readv(const Buf& b, size_t count) {
  std::vector<T> v(count);
  if (count) CL_CHECK(clEnqueueReadBuffer(g_q, b.m, CL_TRUE, 0, count * sizeof(T), v.data(), 0, nullptr, nullptr));
  return v;   // result dump for verification (not a modelled host step)
}
static void print_groups(const GB& g, const Str& k0, const Str& k1, const std::vector<int32_t>& off0,
                         const std::vector<uint8_t>& ch0, const std::vector<int32_t>& off1, const std::vector<uint8_t>& ch1) {
  (void)k0; (void)k1;
  int w = g.nv + 1;
  for (int s = 0; s < g.tsize; ++s) {
    int r = g.table[s];
    if (r < 0) continue;
    std::string a((const char*)&ch0[off0[r]], off0[r + 1] - off0[r]);
    std::string b((const char*)&ch1[off1[r]], off1[r + 1] - off1[r]);
    printf("GROUP %s %s", a.c_str(), b.c_str());
    for (int v = 0; v < w; ++v) printf(" %lld", (long long)g.acc[s * w + v]);
    printf("\n");
  }
}

int main(int argc, char** argv) {
  int cores = 1, warps = 32, c;
  while ((c = getopt(argc, argv, "d:o:c:w:")) != -1) {
    if (c == 'd') g_data = optarg;
    if (c == 'o') g_out = optarg;
    if (c == 'c') cores = atoi(optarg);
    if (c == 'w') warps = atoi(optarg);
  }
  if (optind >= argc) { printf("usage: dbops -d data -o out -c cores -w warps <op> [args]\n"); return 2; }
  std::string op = argv[optind];
  int arg1 = (optind + 1 < argc) ? atoi(argv[optind + 1]) : 0;
  g_threads = (size_t)cores * warps * 32;
  if (g_out.empty()) g_out = ".";

  cl_platform_id platform;
  cl_device_id dev;
  cl_int err;
  CL_CHECK(clGetPlatformIDs(1, &platform, NULL));
  CL_CHECK(clGetDeviceIDs(platform, CL_DEVICE_TYPE_DEFAULT, 1, &dev, NULL));
  g_ctx = clCreateContext(NULL, 1, &dev, NULL, NULL, &err);
  CL_CHECK(err);
  g_q = clCreateCommandQueue(g_ctx, dev, 0, &err);
  CL_CHECK(err);
  std::ifstream f("kernel.cl");
  std::stringstream ss;
  ss << f.rdbuf();
  std::string src = ss.str();
  const char* p = src.c_str();
  size_t len = src.size();
  g_prog = clCreateProgramWithSource(g_ctx, 1, &p, &len, &err);
  CL_CHECK(err);
  err = clBuildProgram(g_prog, 1, &dev, NULL, NULL, NULL);
  if (err != CL_SUCCESS) {
    size_t lsz = 0;
    clGetProgramBuildInfo(g_prog, dev, CL_PROGRAM_BUILD_LOG, 0, NULL, &lsz);
    std::string log(lsz, 0);
    clGetProgramBuildInfo(g_prog, dev, CL_PROGRAM_BUILD_LOG, lsz, &log[0], NULL);
    printf("build failed:\n%s\n", log.c_str());
    return 3;
  }
  printf("OP %s arg=%d cores=%d warps=%d threads=%zu\n", op.c_str(), arg1, cores, warps, g_threads);

  bool ok = true;
  if (op == "empty") {
    // one work-group, then one work-item per resident hardware thread (the shape of the grid-stride kernels)
    for (int i = 0; i < std::max(1, arg1); ++i) launch0("empty_kernel", "empty_1wg");
    for (int i = 0; i < std::max(1, arg1); ++i) launch0("empty_kernel", "empty_full", g_threads);
  } else if (op == "pred_i16" || op == "pred_i32" || op == "range_i16" || op == "filter_conj" || op == "mask_and") {
    load_table(false);
    int n = T.n;
    Buf mask = mk(n);
    if (op == "pred_i16")
      launch("cmp_i16", "pred", grid_stride(n), n, (size_t)n * 3, T.b_shipdate.m, (cl_long)10471, (cl_int)3, mask.m, n);
    else if (op == "pred_i32")
      launch("cmp_i32", "pred", grid_stride(n), n, (size_t)n * 5, T.b_qty.m, (cl_long)2400, (cl_int)2, mask.m, n);
    else if (op == "range_i16")
      launch("range_i16", "range", grid_stride(n), n, (size_t)n * 3, T.b_shipdate.m, (cl_long)8766, (cl_long)9130, mask.m, n);
    else if (op == "mask_and") {
      std::vector<uint8_t> a(n), b(n);
      for (int i = 0; i < n; ++i) { a[i] = T.shipdate[i] >= 8766 && T.shipdate[i] <= 9130; b[i] = T.disc[i] >= 5 && T.disc[i] <= 7; }
      Buf ba = mk(n, a.data()), bb = mk(n, b.data());
      launch("mask_and", "and", grid_stride(n), n, (size_t)n * 3, ba.m, bb.m, mask.m, n);
    } else {
      launch("filter_conj", "filter", grid_stride(n), n, (size_t)n * 11, T.b_shipdate.m, T.b_disc.m, T.b_qty.m, T.b_qty.m,
             (cl_int)1, (cl_int)2, (cl_int)2, (cl_int)2, (cl_long)8766, (cl_long)9130, (cl_long)5, (cl_long)7,
             (cl_long)INT32_MIN, (cl_long)2399, (cl_long)0, (cl_long)0, (cl_int)3, mask.m, n);
    }
    save("mask.bin", readv<uint8_t>(mask, n));
  } else if (op == "xp_tile") {   // launch-shape experiment: argv[optind+2] = kernel name
    load_table(false);
    auto hm = host_mask_qty_le(2500);
    Buf mask = mk(T.n, hm.data());
    int ntiles = (T.n + TILE - 1) / TILE;
    Buf counts = mk(ntiles * 4);
    const char* kn = argv[optind + 2];
    for (int r = 0; r < std::max(1, arg1); ++r)
      launch(kn, "xp", (size_t)ntiles * WG, T.n, (size_t)T.n, mask.m, T.n, counts.m);
  } else if (op == "xp_store") {   // store-pattern experiment: argv[optind+2] = kernel name
    load_table(false);
    int ntiles = (T.n + TILE - 1) / TILE;
    Buf out = mk((size_t)T.n * 4);
    launch(argv[optind + 2], "xp", (size_t)ntiles * WG, T.n, (size_t)T.n * 4, out.m, T.n);
    auto v = readv<int>(out, T.n);
    for (int i = 0; i < T.n; ++i) if (v[i] != i) { printf("xp_store mismatch at %d\n", i); ok = false; break; }
  } else if (op == "compact") {
    load_table(false);
    auto hm = host_mask_qty_le(arg1 * 100);
    Buf mask = mk(T.n, hm.data());
    int cnt = 0;
    Buf idx = compact(mask, T.n, &cnt, "compact");
    save("idx.bin", readv<int>(idx, cnt));
  } else if (op == "gather_i32" || op == "gather_i64") {
    load_table(false);
    auto hidx = host_idx(host_mask_qty_le(arg1 * 100));
    int m = (int)hidx.size();
    Buf idx = mk((size_t)m * 4, hidx.data());
    if (op == "gather_i32") {
      Buf o = gather("gather_i32", T.b_price, 4, idx, m, "gather4");
      save("out.bin", readv<int32_t>(o, m));
    } else {
      auto p64 = widen(T.price);
      Buf src = mk((size_t)T.n * 8, p64.data());
      Buf o = gather("gather_i64", src, 8, idx, m, "gather8");
      save("out.bin", readv<cl_long>(o, m));
    }
  } else if (op == "cast") {
    load_table(false);
    Buf o = cast64(T.b_price, T.n, "cast");
    save("out.bin", readv<cl_long>(o, T.n));
  } else if (op == "mul") {
    load_table(false);
    auto a = widen(T.price), b = widen(T.disc);
    Buf ba = mk((size_t)T.n * 8, a.data()), bb = mk((size_t)T.n * 8, b.data());
    Buf o = binop(ba, bb, T.n, 2, "mul");
    save("out.bin", readv<cl_long>(o, T.n));
  } else if (op == "reduce_i32") {
    load_table(false);
    long s = reduce_sum("reduce_sum_i32", T.b_price, 4, T.n, "reduce4");
    printf("RESULT sum=%ld\n", s);
  } else if (op == "reduce_i64" || op == "minmax_i64") {
    load_table(false);
    auto a = widen(T.price);
    Buf ba = mk((size_t)T.n * 8, a.data());
    if (op == "reduce_i64") {
      long s = reduce_sum("reduce_sum_i64", ba, 8, T.n, "reduce8");
      printf("RESULT sum=%ld\n", s);
    } else {
      auto mm = reduce_minmax(ba, T.n, "minmax8");
      printf("RESULT min=%ld max=%ld\n", mm.first, mm.second);
    }
  } else if (op == "groupby") {
    load_table(true);
    auto q = widen(T.qty), pr = widen(T.price), di = widen(T.disc);
    std::vector<Buf> vals = {mk((size_t)T.n * 8, q.data()), mk((size_t)T.n * 8, pr.data()), mk((size_t)T.n * 8, di.data())};
    GB g = groupby(T.rf, &T.ls, T.n, vals, "groupby");
    print_groups(g, T.rf, T.ls, T.rf_off, T.rf_ch, T.ls_off, T.ls_ch);
  } else if (op == "probe") {
    load_table(false);
    int k = std::max(1, arg1);
    std::vector<int> keys;
    for (int i = 0; i < k; ++i) keys.push_back(100 + i * (4900 / k));   // k distinct quantities x100, sorted
    Buf bk = mk(k * 4, keys.data()), mask = mk(T.n);
    launch("probe_sorted_i32", "probe", grid_stride(T.n), T.n, (size_t)T.n * 5, T.b_qty.m, T.n, bk.m, k, mask.m);
    save("mask.bin", readv<uint8_t>(mask, T.n));
    save("keys.bin", keys);
  } else if (op == "chain_q6") {
    load_table(false);
    int n = T.n;
    Buf mask = mk(n);
    // 1. predicate (cuDF: one AST compute_column_kernel over the 3 referenced columns)
    launch("filter_conj", "q6.filter", grid_stride(n), n, (size_t)n * 11, T.b_shipdate.m, T.b_disc.m, T.b_qty.m, T.b_qty.m,
           (cl_int)1, (cl_int)2, (cl_int)2, (cl_int)2, (cl_long)8766, (cl_long)9130, (cl_long)5, (cl_long)7,
           (cl_long)INT32_MIN, (cl_long)2399, (cl_long)0, (cl_long)0, (cl_int)3, mask.m, n);
    // 2. apply_boolean_mask -> row indices (count read back)
    int m = 0;
    Buf idx = compact(mask, n, &m, "q6.compact");
    // 3. gather the two needed columns
    Buf gp = gather("gather_i32", T.b_price, 4, idx, m, "q6.gather_price");
    Buf gd = gather("gather_i32", T.b_disc, 4, idx, m, "q6.gather_disc");
    // 4. widen decimal32 -> decimal64, multiply
    Buf p64 = cast64(gp, m, "q6.cast_price");
    Buf d64 = cast64(gd, m, "q6.cast_disc");
    Buf prod = binop(p64, d64, m, 2, "q6.mul");
    // 5. Sirius SUM pre-check (min/max to decide the result width), then SUM
    reduce_minmax(prod, m, "q6.minmax");
    long rev = reduce_sum("reduce_sum_i64", prod, 8, m, "q6.sum");
    printf("RESULT q6 revenue_x1e4=%ld selected=%d\n", rev, m);
  } else if (op == "chain_q1") {
    load_table(true);
    int n = T.n;
    Buf mask = mk(n);
    launch("cmp_i16", "q1.filter", grid_stride(n), n, (size_t)n * 3, T.b_shipdate.m, (cl_long)10471, (cl_int)3, mask.m, n);
    int m = 0;
    Buf idx = compact(mask, n, &m, "q1.compact");
    Buf gq = gather("gather_i32", T.b_qty, 4, idx, m, "q1.gather_qty");
    Buf gp = gather("gather_i32", T.b_price, 4, idx, m, "q1.gather_price");
    Buf gd = gather("gather_i32", T.b_disc, 4, idx, m, "q1.gather_disc");
    Buf gt = gather("gather_i32", T.b_tax, 4, idx, m, "q1.gather_tax");
    Str grf = str_gather(T.rf, idx, m, "q1.gather_returnflag");
    Str gls = str_gather(T.ls, idx, m, "q1.gather_linestatus");
    Buf q64 = cast64(gq, m, "q1.cast_qty");
    Buf p64 = cast64(gp, m, "q1.cast_price");
    Buf d64 = cast64(gd, m, "q1.cast_disc");
    Buf t64 = cast64(gt, m, "q1.cast_tax");
    Buf q64b = cast64(gq, m, "q1.cast_sum_qty");     // cuDF unary_cast of the SUM inputs (2 per batch in the trace)
    Buf d64b = cast64(gd, m, "q1.cast_sum_disc");
    Buf onem = binop_s(100, d64, m, 1, "q1.sub");    // 1 - l_discount (scale 2)
    Buf dp = binop(p64, onem, m, 2, "q1.mul_disc_price");
    Buf onep = binop_s(100, t64, m, 0, "q1.add");    // 1 + l_tax
    Buf ch = binop(dp, onep, m, 2, "q1.mul_charge");
    reduce_minmax(q64, m, "q1.minmax_qty");
    reduce_minmax(p64, m, "q1.minmax_price");
    reduce_minmax(dp, m, "q1.minmax_disc_price");
    reduce_minmax(ch, m, "q1.minmax_charge");
    reduce_minmax(d64b, m, "q1.minmax_disc");
    std::vector<Buf> vals = {q64b, p64, dp, ch, d64b};
    GB g = groupby(grf, &gls, m, vals, "q1.groupby");
    auto ro = readv<int32_t>(grf.off, m + 1), lo = readv<int32_t>(gls.off, m + 1);
    auto rc = readv<uint8_t>(grf.chars, grf.nchars), lc = readv<uint8_t>(gls.chars, gls.nchars);
    print_groups(g, grf, gls, ro, rc, lo, lc);
    printf("RESULT q1 selected=%d\n", m);
  } else {
    printf("unknown op %s\n", op.c_str());
    ok = false;
  }
  printf("LAUNCHES %d\n", g_launch);
  printf("%s\n", ok ? "DONE" : "FAILED!");
  for (auto m : g_all) clReleaseMemObject(m);
  for (auto& kv : g_k) clReleaseKernel(kv.second);
  clReleaseProgram(g_prog);
  clReleaseCommandQueue(g_q);
  clReleaseContext(g_ctx);
  clReleaseDevice(dev);
  return ok ? 0 : 1;
}
