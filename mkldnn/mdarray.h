#ifndef _MDARRAY_H_
#define _MDARRAY_H_
#include <Python.h>
#include <cstring>
#include <iostream>
#include <vector>
#include <numeric>
#include <memory>
#include <stdexcept>
#include <mkldnn.hpp>
#include <type_traits>

// Just grab it from MKL-DNN
namespace avx {
  inline void* malloc(size_t size, int alignment) {
      void *ptr;
      int rc = ::posix_memalign(&ptr, alignment, size);
      return (rc == 0) ? ptr : 0;
  }
  inline void free(void* p) { ::free(p); }

  struct compatible {
      enum { default_alignment = 64 };
      static void* operator new(size_t sz) {
          return malloc(sz, default_alignment);
      }
      static void* operator new(size_t sz, void* p) { (void)sz; return p; }
      static void* operator new[](size_t sz) {
          return malloc(sz, default_alignment);
      }
      static void operator delete(void* p) { free(p); }
      static void operator delete[](void* p) { free(p); }
  };

  struct byte: public compatible {
    char q;
  };
}

class mdarray {
  struct InitPainInTheAss {
    void operator() (mkldnn::memory::dims dims
        , mkldnn::memory::data_type dt
        , mkldnn::memory::format format
        , mkldnn::engine &e) {
    }
  };

public:
  static constexpr int MAX_NDIM = 12; //XXX: For now
  typedef size_t size_type;
  // Generated on demand
  struct _data_desc {
    int ndims;
    char format[4];
    Py_ssize_t itemsize;
    Py_ssize_t strides[MAX_NDIM];
    Py_ssize_t shape[MAX_NDIM];
  };

  mdarray(mkldnn::memory::dims dims
      , mkldnn::memory::data_type dt
      , mkldnn::memory::format format
      , mkldnn::engine &engine) : 
              size_(std::accumulate(dims.begin(), dims.end(), 1
                    , std::multiplies<mkldnn::memory::dims::value_type>()))
              , data_(new avx::byte [size_ * 4])
              , m_({{dims, dt, format}, engine}, data_.get())
              , desc_(nullptr), view_(nullptr) {}

  mdarray(mkldnn::memory::primitive_desc pd): 
              size_([] (mkldnn::memory::primitive_desc &pd) {
                    auto md = pd.desc().data;
                    return std::accumulate(md.dims, md.dims + md.ndims, 1
                        , std::multiplies<int>());
                  }(pd))
              , data_(new avx::byte [size_ * 4])
              , m_(pd, data_.get())
              , desc_(nullptr), view_(nullptr) {}
  
  // XXX: Sorry for the mess
  mdarray(Py_buffer *view
      , mkldnn::memory::format format
      , mkldnn::engine &e): size_(view->len/view->itemsize)
           , data_([](Py_buffer *view) {
             unsigned long adrs = reinterpret_cast<unsigned long>(view->buf);
             if (adrs % 16 != 0) {
               return std::unique_ptr
                 <avx::byte []>(new avx::byte [view->len]);
             } else
               return std::unique_ptr<avx::byte []>(nullptr);
           }(view)), m_({d_from_view(view, format), e}, data_ == nullptr
              ? view->buf : data_.get()), desc_(nullptr), view_(view) {
    if (data_ != nullptr) {
      // XXX: OpenMP thing?
      memcpy(data_.get(), view->buf, view->len);
      view_.reset(nullptr);
    }
  }

  inline void *data() { return view_ == nullptr ? data_.get(): view_->buf; }
  inline size_type size() { return size_; }

  inline int ndims() {
    auto md = m_.get_primitive_desc().desc();
    return md.data.ndims;
  }

  inline mkldnn::memory &memory() {
    return m_;
  }

  // PEP: 3118 Buffer Protocol Producer
  int getbuffer(PyObject *obj, Py_buffer *view, int flags);

  Py_ssize_t getsegcount(PyObject *self, Py_ssize_t *lenp) {
    return 0;
  }
  Py_ssize_t getreadbuf(PyObject *self, Py_ssize_t segment, void **ptrptr) {
    return 0;
  }
  Py_ssize_t getwritebuf(PyObject *self, Py_ssize_t segment, void **ptrptr) {
    return 0;
  }
  Py_ssize_t getcharbuf(PyObject *self, Py_ssize_t segment, void **ptrptr) {
    return 0;
  }

private:
  struct WeDontManageIt {
    void operator() (Py_buffer *view) {
      PyBuffer_Release(view);
    }
  };

  size_type size_;
  std::unique_ptr<avx::byte []> data_;
  mkldnn::memory m_;

private:
  std::unique_ptr<_data_desc> desc_;
  std::unique_ptr<Py_buffer, WeDontManageIt> view_;

  void _collect_buffer_info() {
    if (desc_ == nullptr)
      desc_ = std::unique_ptr<_data_desc>(new _data_desc);

    // XXX: Do we need collect information every time?
    // For safety we do now.

    auto md = m_.get_primitive_desc().desc();
    int ndims = md.data.ndims;

    desc_->ndims = ndims;
    switch(md.data.data_type) {
      case mkldnn::memory::f32:
        strcpy(desc_->format, "f");
        desc_->itemsize = 4;
        break;
      case mkldnn::memory::s32:
        strcpy(desc_->format, "i");
        desc_->itemsize = 4;
        break;
      default:
        break;
    }

    // XXX: figure this out
    for (int i = 0; i < ndims; i ++) {
      desc_->shape[i] = md.data.dims[i];
    }

    Py_ssize_t sd = desc_->itemsize;

    for (int i = ndims -1; i >= 0; --i) {
      desc_->strides[i] = sd;
      sd *= desc_->shape[i];
    }
  }

  mkldnn::memory::desc d_from_view(Py_buffer *view
      , mkldnn::memory::format order) {
    mkldnn::memory::dims dims (view->ndim);

    for( int i=0; i < view->ndim; i++)
      dims[i] = view->shape[i];

    std::string format(view->format);
    mkldnn::memory::data_type dt; 

    if (view->itemsize == 4) {
      if (std::string::npos != format.find_last_of('f')) {
        dt = mkldnn::memory::f32;
      } else if (std::string::npos != format.find_last_of('i')) {
        dt = mkldnn::memory::s32;
      } else
        throw mkldnn::error(mkldnn::c_api::mkldnn_invalid_arguments
            , std::string("MKLDNN does not support data type: ")
            + format);
    } else
      throw mkldnn::error(mkldnn::c_api::mkldnn_invalid_arguments
          , "MKLDNN does not support itemsize other than 4");

    return mkldnn::memory::desc(dims, dt, order);
  }
};

int mdarray::getbuffer(PyObject *self, Py_buffer *view, int flags) {
  if ((flags & PyBUF_F_CONTIGUOUS) == PyBUF_F_CONTIGUOUS) {
    PyErr_SetString(PyExc_ValueError, "carray is not Fortran contiguous");
    goto fail;
  }

  if (view == nullptr) {
    PyErr_SetString(PyExc_ValueError, "NULL view in getbuffer");
    goto fail;
  }

  /* Fill in buffer detail */
  _collect_buffer_info();

  view->buf = data();
  view->itemsize = desc_->itemsize;
  view->readonly = 0;
  view->internal = nullptr;
  view->len = size_ * desc_->itemsize;

  if ((flags & PyBUF_FORMAT) == PyBUF_FORMAT) {
    view->format = desc_->format;
  } else {
    view->format = nullptr;
  }

  if ((flags & PyBUF_ND) == PyBUF_ND) {
    view->ndim = desc_->ndims;
    view->shape = desc_->shape;
  } else {
    view->ndim = 0;
    view->shape = nullptr;
  }

  if ((flags & PyBUF_STRIDES) == PyBUF_STRIDES) {
    view->strides = desc_->strides;
  } else
    view->strides = nullptr;

  // We do not have to check PyBUF_INDIRECT because we
  // are C contiguous
  view->suboffsets = nullptr;

  view->obj = self;
  Py_INCREF(self);

  return 0;

fail:
  return -1;
}

#endif