// Read-bandwidth probe for Vortex: sums an array of n longs, iters times, and checks the result.
// Bytes requested per cycle = n * 8 * iters / cycles (cycles from the PERF line).
#include <CL/opencl.h>
#include <unistd.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#define CL_CHECK(_expr)                                                          \
  do {                                                                           \
    cl_int _err = _expr;                                                         \
    if (_err != CL_SUCCESS) {                                                    \
      printf("OpenCL Error: '%s' returned %d!\n", #_expr, (int)_err);           \
      exit(-1);                                                                  \
    }                                                                            \
  } while (0)
#define CL_CHECK2(_expr)                                                         \
  ({                                                                             \
    cl_int _err = CL_INVALID_VALUE;                                              \
    decltype(_expr) _ret = _expr;                                                \
    if (_err != CL_SUCCESS) {                                                    \
      printf("OpenCL Error: '%s' returned %d!\n", #_expr, (int)_err);           \
      exit(-1);                                                                  \
    }                                                                            \
    _ret;                                                                        \
  })

int main(int argc, char** argv) {
  int n = 1024, iters = 100;
  size_t global_size = 128, local_size = 128;
  int c;
  while ((c = getopt(argc, argv, "n:i:g:l:")) != -1) {
    if (c == 'n') n = atoi(optarg);
    if (c == 'i') iters = atoi(optarg);
    if (c == 'g') global_size = atoi(optarg);
    if (c == 'l') local_size = atoi(optarg);
  }
  printf("read probe: %d longs (%d KB) x %d passes = %.1f MB requested\n", n, n * 8 / 1024, iters,
         (double)n * 8 * iters / 1e6);

  std::vector<int64_t> h(n);
  for (int i = 0; i < n; ++i) h[i] = i % 1000;
  std::vector<int64_t> res(global_size);

  cl_platform_id platform;
  cl_device_id dev;
  CL_CHECK(clGetPlatformIDs(1, &platform, NULL));
  CL_CHECK(clGetDeviceIDs(platform, CL_DEVICE_TYPE_DEFAULT, 1, &dev, NULL));
  cl_context ctx = CL_CHECK2(clCreateContext(NULL, 1, &dev, NULL, NULL, &_err));
  cl_command_queue q = CL_CHECK2(clCreateCommandQueue(ctx, dev, 0, &_err));
  std::ifstream f("kernel.cl");
  std::stringstream ss;
  ss << f.rdbuf();
  std::string src = ss.str();
  const char* p = src.c_str();
  size_t len = src.size();
  cl_program prog = CL_CHECK2(clCreateProgramWithSource(ctx, 1, &p, &len, &_err));
  CL_CHECK(clBuildProgram(prog, 1, &dev, NULL, NULL, NULL));
  cl_kernel k = CL_CHECK2(clCreateKernel(prog, "rd", &_err));
  cl_mem buf = CL_CHECK2(clCreateBuffer(ctx, CL_MEM_READ_ONLY, n * 8, NULL, &_err));
  cl_mem out = CL_CHECK2(clCreateBuffer(ctx, CL_MEM_WRITE_ONLY, global_size * 8, NULL, &_err));
  CL_CHECK(clEnqueueWriteBuffer(q, buf, CL_TRUE, 0, n * 8, h.data(), 0, NULL, NULL));
  CL_CHECK(clSetKernelArg(k, 0, sizeof(cl_mem), &buf));
  CL_CHECK(clSetKernelArg(k, 1, sizeof(int), &n));
  CL_CHECK(clSetKernelArg(k, 2, sizeof(int), &iters));
  CL_CHECK(clSetKernelArg(k, 3, sizeof(cl_mem), &out));
  CL_CHECK(clEnqueueNDRangeKernel(q, k, 1, NULL, &global_size, &local_size, 0, NULL, NULL));
  CL_CHECK(clFinish(q));
  CL_CHECK(clEnqueueReadBuffer(q, out, CL_TRUE, 0, global_size * 8, res.data(), 0, NULL, NULL));

  int64_t got = 0, want = 0;
  for (auto v : res) got += v;
  for (auto v : h) want += v;
  want *= iters;
  printf("%s\n", got == want ? "PASSED!" : "FAILED!");

  // Releasing the device is what makes the Vortex runtime print its performance counters.
  clReleaseMemObject(buf);
  clReleaseMemObject(out);
  clReleaseKernel(k);
  clReleaseProgram(prog);
  clReleaseCommandQueue(q);
  clReleaseContext(ctx);
  clReleaseDevice(dev);
  return got == want ? 0 : 1;
}
