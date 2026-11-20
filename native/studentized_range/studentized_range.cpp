// Upper-tail studentized range probabilities for Tukey's HSD.
//
// The double integral SciPy evaluates through nquad, without the Python round trip for each
// inner integral. The integrand stays SciPy's own compiled _studentized_range_cdf, received
// as a capsule. dqagie, dqk15i, dqpsrt and dqelg follow QUADPACK (Piessens, de Doncker,
// Ueberhuber, Kahaner; public domain) in the same order of operations as SciPy's translation.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <algorithm>
#include <atomic>
#include <cfloat>
#include <cmath>
#include <thread>
#include <vector>

namespace {
using Integrand = double (*)(int, double*, void*);
const double kEpmach = DBL_EPSILON, kUflow = DBL_MIN, kOflow = DBL_MAX;
constexpr int kLimit = 50;

const double kXgk[8] = {0.9914553711208126392068546975263285, 0.9491079123427585245261896840478513,
    0.8648644233597690727897127886409262, 0.7415311855993944398638647732807884,
    0.5860872354676911302941448382587296, 0.4058451513773971669066064120769615,
    0.2077849550078984676006894037732449, 0.0};
const double kWgk[8] = {0.02293532201052922496373200805896959, 0.06309209262997855329070066318920429,
    0.1047900103222501838398763225415180, 0.1406532597155259187451895905102379,
    0.1690047266392679028265834265985503, 0.1903505780647854099132564024210137,
    0.2044329400752988924141619992346491, 0.2094821410847278280129991748171075};
const double kWg[8] = {0.0, 0.1294849661688696932706114326790820, 0.0, 0.2797053914892766679014677714237796,
    0.0, 0.3818300505051189449503697754889751, 0.0, 0.4179591836734693877551020408163265};

template <class F>
void qk15i(const F& f, int inf, double a, double b, double& result, double& abserr, double& resabs, double& resasc) {
  const double dinf = std::min(1, inf), boun = 0.0;
  const double centr = 0.5 * (a + b), hlgth = 0.5 * (b - a);
  double tabsc1 = boun + dinf * (1.0 - centr) / centr;
  double fval1 = f(tabsc1);
  if (inf == 2) fval1 += f(-tabsc1);
  const double fc = (fval1 / centr) / centr;
  double resg = kWg[7] * fc, resk = kWgk[7] * fc;
  resabs = std::fabs(resk);
  double fv1[7], fv2[7];
  for (int j = 0; j < 7; ++j) {
    const double absc = hlgth * kXgk[j], absc1 = centr - absc, absc2 = centr + absc;
    tabsc1 = boun + dinf * (1.0 - absc1) / absc1;
    const double tabsc2 = boun + dinf * (1.0 - absc2) / absc2;
    fval1 = f(tabsc1);
    double fval2 = f(tabsc2);
    if (inf == 2) {
      fval1 += f(-tabsc1);
      fval2 += f(-tabsc2);
    }
    fval1 = (fval1 / absc1) / absc1;
    fval2 = (fval2 / absc2) / absc2;
    fv1[j] = fval1;
    fv2[j] = fval2;
    const double fsum = fval1 + fval2;
    resg += kWg[j] * fsum;
    resk += kWgk[j] * fsum;
    resabs += kWgk[j] * (std::fabs(fval1) + std::fabs(fval2));
  }
  const double reskh = resk * 0.5;
  resasc = kWgk[7] * std::fabs(fc - reskh);
  for (int j = 0; j < 7; ++j) resasc += kWgk[j] * (std::fabs(fv1[j] - reskh) + std::fabs(fv2[j] - reskh));
  result = resk * hlgth;
  resasc *= hlgth;
  resabs *= hlgth;
  abserr = std::fabs((resk - resg) * hlgth);
  if (resasc != 0.0 && abserr != 0.0) abserr = resasc * std::min(1.0, std::pow(abserr * 200.0 / resasc, 1.5));
  if (resabs > kUflow / (kEpmach * 50.0)) abserr = std::max(kEpmach * 50.0 * resabs, abserr);
}

// One-based arrays, as in QUADPACK.
void qpsrt(int limit, int last, int& maxerr, double& ermax, const double* elist, int* iord, int& nrmax) {
  if (last <= 2) {
    iord[1] = 1;
    iord[2] = 2;
  } else {
    const double errmax = elist[maxerr];
    if (nrmax != 1) {
      const int ido = nrmax - 1;
      for (int i = 1; i <= ido; ++i) {
        const int isucc = iord[nrmax - 1];
        if (errmax <= elist[isucc]) break;
        iord[nrmax] = isucc;
        --nrmax;
      }
    }
    int jupbn = last;
    if (last > limit / 2 + 2) jupbn = limit + 3 - last;
    const double errmin = elist[last];
    const int jbnm1 = jupbn - 1, ibeg = nrmax + 1;
    bool placed = false;
    if (ibeg <= jbnm1) {
      for (int i = ibeg; i <= jbnm1; ++i) {
        const int isucc = iord[i];
        if (errmax >= elist[isucc]) {
          iord[i - 1] = maxerr;
          int k = jbnm1;
          bool done = false;
          for (int j = i; j <= jbnm1; ++j) {
            const int isucc2 = iord[k];
            if (errmin < elist[isucc2]) {
              iord[k + 1] = last;
              done = true;
              break;
            }
            iord[k + 1] = isucc2;
            --k;
          }
          if (!done) iord[i] = last;
          placed = true;
          break;
        }
        iord[i - 1] = isucc;
      }
    }
    if (!placed) {
      iord[jbnm1] = maxerr;
      iord[jupbn] = last;
    }
  }
  maxerr = iord[nrmax];
  ermax = elist[maxerr];
}

void qelg(int& n, double* epstab, double& result, double& abserr, double* res3la, int& nres) {
  ++nres;
  abserr = kOflow;
  result = epstab[n];
  if (n < 3) {
    abserr = std::max(abserr, kEpmach * 5.0 * std::fabs(result));
    return;
  }
  const int limexp = 50;
  epstab[n + 2] = epstab[n];
  const int newelm = (n - 1) / 2;
  epstab[n] = kOflow;
  const int num = n;
  int k1 = n;
  for (int i = 1; i <= newelm; ++i) {
    const int k2 = k1 - 1, k3 = k1 - 2;
    double res = epstab[k1 + 2];
    const double e0 = epstab[k3], e1 = epstab[k2], e2 = res;
    const double e1abs = std::fabs(e1);
    const double delta2 = e2 - e1, err2 = std::fabs(delta2);
    const double tol2 = std::max(std::fabs(e2), e1abs) * kEpmach;
    const double delta3 = e1 - e0, err3 = std::fabs(delta3);
    const double tol3 = std::max(e1abs, std::fabs(e0)) * kEpmach;
    if (err2 <= tol2 && err3 <= tol3) {
      result = res;
      abserr = err2 + err3;
      abserr = std::max(abserr, kEpmach * 5.0 * std::fabs(result));
      return;
    }
    const double e3 = epstab[k1];
    epstab[k1] = e1;
    const double delta1 = e1 - e3, err1 = std::fabs(delta1);
    const double tol1 = std::max(e1abs, std::fabs(e3)) * kEpmach;
    if (err1 <= tol1 || err2 <= tol2 || err3 <= tol3) {
      n = i + i - 1;
      break;
    }
    const double ss = 1.0 / delta1 + 1.0 / delta2 - 1.0 / delta3;
    const double epsinf = std::fabs(ss * e1);
    if (epsinf <= 1e-4) {
      n = i + i - 1;
      break;
    }
    res = e1 + 1.0 / ss;
    epstab[k1] = res;
    k1 -= 2;
    const double error = err2 + std::fabs(res - e2) + err3;
    if (error <= abserr) {
      abserr = error;
      result = res;
    }
  }
  if (n == limexp) n = 2 * (limexp / 2) - 1;
  int ib = (num / 2) * 2 == num ? 2 : 1;
  const int ie = newelm + 1;
  for (int i = 1; i <= ie; ++i) {
    const int ib2 = ib + 2;
    epstab[ib] = epstab[ib2];
    ib = ib2;
  }
  if (num != n) {
    int indx = num - n + 1;
    for (int i = 1; i <= n; ++i) {
      epstab[i] = epstab[indx];
      ++indx;
    }
  }
  if (nres < 4) {
    res3la[nres] = result;
    abserr = kOflow;
  } else {
    abserr = std::fabs(result - res3la[3]) + std::fabs(result - res3la[2]) + std::fabs(result - res3la[1]);
    res3la[1] = res3la[2];
    res3la[2] = res3la[3];
    res3la[3] = result;
  }
  abserr = std::max(abserr, kEpmach * 5.0 * std::fabs(result));
}

template <class F>
double qagie(const F& f, int inf, double epsabs, double epsrel) {
  const int limit = kLimit;
  double alist[limit + 2], blist[limit + 2], rlist[limit + 2], elist[limit + 2];
  int iord[limit + 2];
  double rlist2[53], res3la[4];
  alist[1] = 0.0;
  blist[1] = 1.0;
  double result = 0.0, abserr = 0.0, defabs = 0.0, resabs = 0.0;
  int ier = 0, last = 1;
  qk15i(f, inf, 0.0, 1.0, result, abserr, defabs, resabs);
  rlist[1] = result;
  elist[1] = abserr;
  iord[1] = 1;
  const double dres = std::fabs(result);
  double errbnd = std::max(epsabs, epsrel * dres);
  if (abserr <= kEpmach * 100.0 * defabs && abserr > errbnd) ier = 2;
  if (ier != 0 || (abserr <= errbnd && abserr != resabs) || abserr == 0.0) return result;

  rlist2[1] = result;
  double errmax = abserr, area = result, errsum = abserr, small = 0.0, erlarg = 0.0, ertest = 0.0, correc = 0.0;
  abserr = kOflow;
  int maxerr = 1, nrmax = 1, nres = 0, ktmin = 0, numrl2 = 2, ierro = 0, iroff1 = 0, iroff2 = 0, iroff3 = 0;
  bool extrap = false, noext = false, summed = false, bracket_done = false;
  const int ksgn = dres >= (1.0 - kEpmach * 50.0) * defabs ? 1 : -1;

  for (last = 2; last <= limit; ++last) {
    const double a1 = alist[maxerr], b1 = 0.5 * (alist[maxerr] + blist[maxerr]), a2 = b1, b2 = blist[maxerr];
    const double erlast = errmax;
    double area1, error1, area2, error2, defab1, defab2, unused;
    qk15i(f, inf, a1, b1, area1, error1, unused, defab1);
    qk15i(f, inf, a2, b2, area2, error2, unused, defab2);
    const double area12 = area1 + area2, erro12 = error1 + error2;
    errsum = errsum + erro12 - errmax;
    area = area + area12 - rlist[maxerr];
    if (defab1 != error1 && defab2 != error2) {
      if (std::fabs(rlist[maxerr] - area12) <= std::fabs(area12) * 1e-5 && erro12 >= errmax * 0.99) {
        if (extrap) ++iroff2; else ++iroff1;
      }
      if (last > 10 && erro12 > errmax) ++iroff3;
    }
    rlist[maxerr] = area1;
    rlist[last] = area2;
    errbnd = std::max(epsabs, epsrel * std::fabs(area));
    if (iroff1 + iroff2 >= 10 || iroff3 >= 20) ier = 2;
    if (iroff2 >= 5) ierro = 3;
    if (last == limit) ier = 1;
    if (std::max(std::fabs(a1), std::fabs(b2)) <= (kEpmach * 100.0 + 1.0) * (std::fabs(a2) + kUflow * 1000.0)) ier = 4;
    if (error2 > error1) {
      alist[maxerr] = a2;
      alist[last] = a1;
      blist[last] = b1;
      rlist[maxerr] = area2;
      rlist[last] = area1;
      elist[maxerr] = error2;
      elist[last] = error1;
    } else {
      alist[last] = a2;
      blist[maxerr] = b1;
      blist[last] = b2;
      elist[maxerr] = error1;
      elist[last] = error2;
    }
    qpsrt(limit, last, maxerr, errmax, elist, iord, nrmax);
    if (errsum <= errbnd) {
      summed = true;
      break;
    }
    if (ier != 0) break;
    if (last == 2) {
      small = 0.375;
      erlarg = errsum;
      ertest = errbnd;
      rlist2[2] = area;
      continue;
    }
    if (noext) continue;
    erlarg -= erlast;
    if (std::fabs(b1 - a1) > small) erlarg += erro12;
    if (!extrap) {
      if (std::fabs(blist[maxerr] - alist[maxerr]) > small) continue;
      extrap = true;
      nrmax = 2;
    }
    if (ierro != 3 && erlarg > ertest) {
      const int id = nrmax;
      int jupbnd = last;
      if (last > limit / 2 + 2) jupbnd = limit + 3 - last;
      bool again = false;
      for (int k = id; k <= jupbnd; ++k) {
        maxerr = iord[nrmax];
        errmax = elist[maxerr];
        if (std::fabs(blist[maxerr] - alist[maxerr]) > small) {
          again = true;
          break;
        }
        ++nrmax;
      }
      if (again) continue;
    }
    ++numrl2;
    rlist2[numrl2] = area;
    double reseps, abseps;
    qelg(numrl2, rlist2, reseps, abseps, res3la, nres);
    ++ktmin;
    if (ktmin > 5 && abserr < errsum * 0.001) ier = 5;
    if (abseps < abserr) {
      ktmin = 0;
      abserr = abseps;
      result = reseps;
      correc = erlarg;
      ertest = std::max(epsabs, epsrel * std::fabs(reseps));
      if (abserr <= ertest) break;
    }
    if (numrl2 == 1) noext = true;
    if (ier == 5) break;
    maxerr = iord[1];
    errmax = elist[maxerr];
    nrmax = 1;
    extrap = false;
    small *= 0.5;
    erlarg = errsum;
  }
  if (last > limit) last = limit;
  if (!summed) {
    if (abserr == kOflow) {
      summed = true;
    } else if (ier + ierro != 0) {
      if (ierro == 3) abserr += correc;
      if (ier == 0) ier = 3;
      if (result != 0.0 && area != 0.0) {
        if (abserr / std::fabs(result) > errsum / std::fabs(area)) summed = true;
      } else if (abserr > errsum) {
        summed = true;
      } else if (area == 0.0) {
        bracket_done = true;
      }
    }
    (void)ksgn;
    (void)bracket_done;
  }
  if (summed) {
    result = 0.0;
    for (int k = 1; k <= last; ++k) result += rlist[k];
  }
  return result;
}

constexpr double kEpsAbs = 1e-11, kEpsRel = 1e-12;

double cdf_one(Integrand integrand, double q, double k, double df, double log_const) {
  double data[4] = {q, k, df, log_const};
  auto outer = [&](double s) {
    auto inner = [&](double z) {
      double x[2] = {z, s};
      return integrand(2, x, data);
    };
    return qagie(inner, 2, kEpsAbs, kEpsRel);
  };
  return qagie(outer, 1, kEpsAbs, kEpsRel);
}

PyObject* cdf_many(PyObject*, PyObject* args) {
  PyObject* capsule;
  Py_buffer q;
  double k, df, log_const;
  int threads;
  if (!PyArg_ParseTuple(args, "Oy*dddi", &capsule, &q, &k, &df, &log_const, &threads)) return nullptr;
  auto integrand = reinterpret_cast<Integrand>(PyCapsule_GetPointer(capsule, PyCapsule_GetName(capsule)));
  if (integrand == nullptr || q.len % static_cast<Py_ssize_t>(sizeof(double)) != 0) {
    PyBuffer_Release(&q);
    if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "q must hold doubles");
    return nullptr;
  }
  const Py_ssize_t size = q.len / static_cast<Py_ssize_t>(sizeof(double));
  const double* values = static_cast<const double*>(q.buf);
  std::vector<double> out(static_cast<size_t>(size));
  Py_BEGIN_ALLOW_THREADS
  std::atomic<Py_ssize_t> next{0};
  auto work = [&] {
    for (Py_ssize_t i; (i = next.fetch_add(1)) < size;) out[static_cast<size_t>(i)] = cdf_one(integrand, values[i], k, df, log_const);
  };
  const int helpers = static_cast<int>(std::min<Py_ssize_t>(std::max(threads, 1), size)) - 1;
  std::vector<std::thread> pool;
  pool.reserve(static_cast<size_t>(std::max(helpers, 0)));
  for (int i = 0; i < helpers; ++i) pool.emplace_back(work);
  work();
  for (auto& thread : pool) thread.join();
  Py_END_ALLOW_THREADS
  PyBuffer_Release(&q);
  return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(out.data()), size * static_cast<Py_ssize_t>(sizeof(double)));
}

PyMethodDef kMethods[] = {{"cdf_many", cdf_many, METH_VARARGS, "Studentized range CDF at many q."}, {nullptr, nullptr, 0, nullptr}};
PyModuleDef kModule = {PyModuleDef_HEAD_INIT, "_studentized_range", nullptr, -1, kMethods, nullptr, nullptr, nullptr, nullptr};
}  // namespace

PyMODINIT_FUNC PyInit__studentized_range() {
  PyObject* module = PyModule_Create(&kModule);
  if (module != nullptr && PyModule_AddIntConstant(module, "ABI_VERSION", 1) < 0) {
    Py_DECREF(module);
    return nullptr;
  }
  return module;
}
