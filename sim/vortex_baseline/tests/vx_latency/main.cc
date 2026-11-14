// Pointer-chase latency probe for Vortex. Builds a random cyclic chain over `bytes` with nodes
// `spacing` bytes apart, and has one work-item follow it for `steps` loads. Cycles per load is
// best taken as the difference between two runs of different length (removes launch cost).
#include <CL/opencl.h>
#include <unistd.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <random>
#include <sstream>
#include <string>
#include <vector>

#define CL_CHECK(_expr)                                                \
  do {                                                                 \
    cl_int _err = _expr;                                               \
    if (_err != CL_SUCCESS) {                                          \
      printf("OpenCL Error: '%s' returned %d!\n", #_expr, (int)_err); \
      exit(-1);                                                        \
    }                                                                  \
  } while (0)
#define CL_CHECK2(_expr)                                               \
  ({                                                                   \
    cl_int _err = CL_INVALID_VALUE;                                    \
    decltype(_expr) _ret = _expr;                                      \
    if (_err != CL_SUCCESS) {                                          \
      printf("OpenCL Error: '%s' returned %d!\n", #_expr, (int)_err); \
      exit(-1);                                                        \
    }                                                                  \
    _ret;                                                              \
  })

int main(int argc, char** argv) {
  size_t bytes = 8192, spacing = 128;
  int steps = 128;
  int c;
  while ((c = getopt(argc, argv, "b:s:n:")) != -1) {
    if (c == 'b') bytes = strtoull(optarg, NULL, 0);
    if (c == 's') spacing = strtoull(optarg, NULL, 0);
    if (c == 'n') steps = atoi(optarg);
  }
  size_t elems = bytes / 8, stride = spacing / 8, count = elems / stride;
  std::vector<uint64_t> next(elems, 0);
  std::vector<size_t> order(count);
  for (size_t i = 0; i < count; ++i) order[i] = i;
  std::shuffle(order.begin() + 1, order.end(), std::mt19937_64(42));
  for (size_t i = 0; i < count; ++i)
    next[order[i] * stride] = order[(i + 1) % count] * stride;
  printf("chase: %zu KB, %zu B apart (%zu nodes), %d loads\n", bytes / 1024, spacing, count, steps);

  uint64_t want = 0;
  for (int i = 0; i < steps; ++i) want = next[want];

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
  cl_kernel k = CL_CHECK2(clCreateKernel(prog, "chase", &_err));
  cl_mem buf = CL_CHECK2(clCreateBuffer(ctx, CL_MEM_READ_ONLY, bytes, NULL, &_err));
  cl_mem out = CL_CHECK2(clCreateBuffer(ctx, CL_MEM_WRITE_ONLY, 8, NULL, &_err));
  CL_CHECK(clEnqueueWriteBuffer(q, buf, CL_TRUE, 0, bytes, next.data(), 0, NULL, NULL));
  CL_CHECK(clSetKernelArg(k, 0, sizeof(cl_mem), &buf));
  CL_CHECK(clSetKernelArg(k, 1, sizeof(int), &steps));
  CL_CHECK(clSetKernelArg(k, 2, sizeof(cl_mem), &out));
  size_t one = 1;
  CL_CHECK(clEnqueueNDRangeKernel(q, k, 1, NULL, &one, &one, 0, NULL, NULL));
  CL_CHECK(clFinish(q));
  uint64_t got = 0;
  CL_CHECK(clEnqueueReadBuffer(q, out, CL_TRUE, 0, 8, &got, 0, NULL, NULL));
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
