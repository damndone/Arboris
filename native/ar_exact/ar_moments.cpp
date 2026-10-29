// Opt-in exact original-binary64 second/fourth moments, p<=4.
// Integer input abs(value*2^1074)<2^2098; degree-four product<2^8392.
// Each positive/negative sum therefore fits 8392+ceil(log2(n))+1 bits.
// Four normalized 53-bit mantissas fit a 212-bit product; the shifted
// product needs five words. No floating multiplication or rounded statistics.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

#ifndef AR_MOMENTS_SOURCE_SHA256
#error "explicit exact-moments source registration required"
#endif

namespace {
constexpr int MAX_P = 4;
constexpr Py_ssize_t BLOCK_ROWS = 256;
constexpr size_t DEGREE = 4;
struct PythonError {};
struct Object {
    PyObject* p;
    explicit Object(PyObject* value) : p(value) { if (!p) throw PythonError{}; }
    ~Object() { Py_XDECREF(p); }
    Object(const Object&) = delete;
    PyObject* release() { auto* result=p; p=nullptr; return result; }
};
void invalid(const char* message) { PyErr_SetString(PyExc_ValueError,message); throw PythonError{}; }
void checkpoint(PyObject* callback) {
    if (PyErr_CheckSignals()<0) throw PythonError{};
    if (callback!=Py_None) { Object called(PyObject_CallNoArgs(callback)); }
}
struct Release {
    PyThreadState* state=PyEval_SaveThread();
    ~Release() { PyEval_RestoreThread(state); }
};
struct Buffer {
    Py_buffer b{};
    explicit Buffer(PyObject* source) {
        if (PyObject_GetBuffer(source,&b,PyBUF_FORMAT|PyBUF_STRIDES)<0) throw PythonError{};
        if (b.itemsize!=8 || !b.format || (std::strcmp(b.format,"d") &&
            std::strcmp(b.format,"=d") && std::strcmp(b.format,"@d")) || b.suboffsets) {
            PyBuffer_Release(&b); invalid("native_ar_moments_native_binary64_required");
        }
    }
    Buffer(const Buffer&) = delete;
    ~Buffer() { PyBuffer_Release(&b); }
    uint64_t word(Py_ssize_t row, Py_ssize_t column=0) const {
        uint64_t result;
        const char* ptr=static_cast<const char*>(b.buf)+row*b.strides[0];
        if (b.ndim==2) ptr+=column*b.strides[1];
        std::memcpy(&result,ptr,8); return result;
    }
};
struct Dyadic { uint64_t mantissa; int exponent; bool negative; };
Dyadic decode(uint64_t word) {
    const unsigned e=static_cast<unsigned>((word>>52)&2047);
    if (e==2047) invalid("nonfinite_original_binary64");
    uint64_t m=word&((uint64_t{1}<<52)-1);
    int exponent=-1074;
    if (e) { m|=uint64_t{1}<<52; exponent=static_cast<int>(e)-1075; }
    if (m) { const int zeros=__builtin_ctzll(m); m>>=zeros; exponent+=zeros; }
    else exponent=0;
    return {m,exponent,bool(word>>63)};
}
// These arrays encode polynomial degree, not design width. p=4 has six
// dynamic input columns, 21 second terms and 105 needed fourth terms.
struct Term { std::array<int,DEGREE> indices{}; int degree; };
using Product=std::array<uint64_t,DEGREE>;
Product product(const Dyadic* row, const Term& term, int& shift, bool& negative) {
    Product words{1,0,0,0};
    shift=1074*term.degree; negative=false;
    for (int k=0;k<term.degree;++k) {
        const auto& value=row[term.indices[k]];
        shift+=value.exponent; negative^=value.negative;
        __uint128_t carry=0;
        for (auto& word:words) {
            const __uint128_t total=static_cast<__uint128_t>(word)*value.mantissa+carry;
            word=static_cast<uint64_t>(total); carry=total>>64;
        }
        // Four 53-bit mantissas occupy at most 212 bits: no carry is lost.
    }
    return words;
}
void accumulate(std::vector<uint64_t>& sums, size_t offset, size_t limbs,
                const Product& product_words, unsigned shift) {
    size_t index=shift/64;
    const unsigned bits=shift%64;
    uint64_t previous=0;
    std::array<uint64_t,5> shifted{};
    for (size_t k=0;k<5;++k) {
        const uint64_t current=k<4?product_words[k]:0;
        shifted[k]=bits ? (current<<bits)|(previous>>(64-bits)) : current;
        previous=current;
    }
    size_t count=shifted.size();
    while (count && !shifted[count-1]) --count;
    __uint128_t carry=0;
    for (size_t k=0;k<count;++k) {
        if (index>=limbs) throw std::bad_alloc{};
        const __uint128_t total=static_cast<__uint128_t>(sums[offset+index])+shifted[k]+carry;
        sums[offset+index]=static_cast<uint64_t>(total); carry=total>>64;
        ++index;
    }
    while (carry) {
        if (index>=limbs) throw std::bad_alloc{};
        const __uint128_t total=static_cast<__uint128_t>(sums[offset+index])+carry;
        sums[offset+index++]=static_cast<uint64_t>(total); carry=total>>64;
    }
}
PyObject* as_integer(const std::vector<uint64_t>& words, size_t offset, size_t limbs) {
    std::vector<unsigned char> bytes(limbs*8);
    for (size_t j=0;j<bytes.size();++j) bytes[j]=static_cast<unsigned char>(words[offset+j/8]>>(8*(j%8)));
    Object raw(PyBytes_FromStringAndSize(reinterpret_cast<const char*>(bytes.data()),static_cast<Py_ssize_t>(bytes.size())));
    return PyObject_CallMethod(reinterpret_cast<PyObject*>(&PyLong_Type),"from_bytes","Os",raw.p,"little");
}
PyObject* moments(PyObject*, PyObject* args) {
    PyObject *yy,*xx,*zz,*ww,*callback=Py_None;
    if (!PyArg_ParseTuple(args,"OOOO|O",&yy,&xx,&zz,&ww,&callback)) return nullptr;
    try {
        if (callback!=Py_None && !PyCallable_Check(callback)) {
            PyErr_SetString(PyExc_TypeError,"native_ar_moments_check_cancel_must_be_callable");
            throw PythonError{};
        }
        Buffer y(yy),x(xx),z(zz),w(ww);
        if ((y.b.ndim!=1 && y.b.ndim!=2) || (y.b.ndim==2 && y.b.shape[1]!=1) ||
            x.b.ndim!=2 || x.b.shape[1]!=1 || z.b.ndim!=2 || w.b.ndim!=2)
            invalid("native_ar_moments_input_shape");
        const auto n=y.b.shape[0];
        if (n<=0 || x.b.shape[0]!=n || z.b.shape[0]!=n || w.b.shape[0]!=n)
            invalid("native_ar_moments_input_shape");
        if (z.b.shape[1]<1 || z.b.shape[1]>MAX_P || w.b.shape[1]>MAX_P-z.b.shape[1])
            invalid("outside_exact_moments_envelope");
        const auto p=z.b.shape[1]+w.b.shape[1];
        const int columns=static_cast<int>(p)+2;
        std::vector<Term> terms;
        for (int i=0;i<columns;++i) for (int j=i;j<columns;++j) terms.push_back({{i,j,0,0},2});
        const size_t second_count=terms.size();
        for (int i=0;i<columns;++i) for (int j=i;j<columns;++j)
            for (int k=j;k<columns;++k) for (int l=k;l<columns;++l)
                if ((i>=2)+(j>=2)+(k>=2)+(l>=2)>=2) terms.push_back({{i,j,k,l},4});
        unsigned logn=0;
        for (auto value=static_cast<uint64_t>(n-1);value;value>>=1) ++logn;
        const size_t limbs=(8392+logn+1+63)/64;
        std::vector<uint64_t> positive(terms.size()*limbs,0),negative(terms.size()*limbs,0);
        std::vector<Dyadic> block(static_cast<size_t>(BLOCK_ROWS*columns));
        int scale=0;
        for (Py_ssize_t start=0;start<n;) {
            checkpoint(callback);
            const auto count=std::min<Py_ssize_t>(BLOCK_ROWS,n-start);
            // The fitted design is execution-owned; general buffer callers
            // must not write aliases during this call. Exports retain owners.
            for (Py_ssize_t i=0;i<count;++i) for (int c=0;c<columns;++c) {
                const auto word=c==0?y.word(start+i):c==1?x.word(start+i):
                    c-2<w.b.shape[1]?w.word(start+i,c-2):z.word(start+i,c-2-w.b.shape[1]);
                auto value=decode(word); scale=std::max(scale,-value.exponent);
                block[static_cast<size_t>(i*columns+c)]=value;
            }
            {
                Release released;
                for (Py_ssize_t i=0;i<count;++i) for (size_t t=0;t<terms.size();++t) {
                    int shift; bool sign;
                    const auto words=product(block.data()+i*columns,terms[t],shift,sign);
                    if (words[0] || words[1] || words[2] || words[3])
                        accumulate(sign?negative:positive,t*limbs,limbs,words,static_cast<unsigned>(shift));
                }
            }
            start+=count;
        }
        Object second(PyDict_New()),fourth(PyDict_New());
        for (size_t t=0;t<terms.size();++t) {
            checkpoint(callback);
            Object pos(as_integer(positive,t*limbs,limbs)),neg(as_integer(negative,t*limbs,limbs));
            Object value(PyNumber_Subtract(pos.p,neg.p));
            Object amount(PyLong_FromLong(terms[t].degree*(1074-scale)));
            Object scaled(PyNumber_Rshift(value.p,amount.p));
            Object restored(PyNumber_Lshift(scaled.p,amount.p));
            const int equal=PyObject_RichCompareBool(value.p,restored.p,Py_EQ);
            if (equal<0) throw PythonError{};
            if (!equal) invalid("native_ar_moments_nonexact_scale_shift");
            Object indices(PyTuple_New(terms[t].degree));
            for (int j=0;j<terms[t].degree;++j) {
                Object index(PyLong_FromLong(terms[t].indices[j]));
                PyTuple_SET_ITEM(indices.p,j,index.release());
            }
            if (PyDict_SetItem(terms[t].degree==2?second.p:fourth.p,indices.p,scaled.p)<0) throw PythonError{};
        }
        // Analytic workspace payload only, not an allocator/RSS measurement.
        const size_t workspace=(positive.capacity()+negative.capacity())*sizeof(uint64_t)+block.capacity()*sizeof(Dyadic)+
            terms.capacity()*sizeof(Term)+limbs*8;
        return Py_BuildValue("{s:i,s:n,s:n,s:O,s:O,s:K,s:i,s:i,s:K,s:K}","scale",scale,"rows",n,"p",p,
            "second",second.p,"fourth",fourth.p,"workspace_requested_bytes",static_cast<unsigned long long>(workspace),
            "limb_bits_per_signed_sum",static_cast<int>(limbs*64),"max_p",MAX_P,
            "second_term_count",static_cast<unsigned long long>(second_count),
            "fourth_term_count",static_cast<unsigned long long>(terms.size()-second_count));
    } catch (const PythonError&) { return nullptr; }
      catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
}
PyMethodDef methods[]={{"moments",moments,METH_VARARGS,"Exact original-binary64 second/fourth moments, p<=4."},{nullptr,nullptr,0,nullptr}};
PyModuleDef module={PyModuleDef_HEAD_INIT,"_ar_moments_exact",nullptr,-1,methods,nullptr,nullptr,nullptr,nullptr};
} // namespace

PyMODINIT_FUNC PyInit__ar_moments_exact() {
    PyObject* result=PyModule_Create(&module);
    if (!result) return nullptr;
    if (PyModule_AddIntConstant(result,"ABI_VERSION",1)<0 ||
        PyModule_AddIntConstant(result,"MAX_P",MAX_P)<0 ||
        PyModule_AddIntConstant(result,"SNAPSHOT_ROWS",static_cast<long>(BLOCK_ROWS))<0 ||
        PyModule_AddIntConstant(result,"PYTHON_MAJOR",PY_MAJOR_VERSION)<0 ||
        PyModule_AddIntConstant(result,"PYTHON_MINOR",PY_MINOR_VERSION)<0 ||
        PyModule_AddStringConstant(result,"SOURCE_SHA256",AR_MOMENTS_SOURCE_SHA256)<0) {
        Py_DECREF(result); return nullptr;
    }
    return result;
}
