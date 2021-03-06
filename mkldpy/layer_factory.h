/*
 *COPYRIGHT
 *All modification made by Intel Corporation: © 2017 Intel Corporation.
 *Copyright (c) 2015 Preferred Infrastructure, Inc.
 *Copyright (c) 2015 Preferred Networks, Inc.
 *
 *Permission is hereby granted, free of charge, to any person obtaining a copy
 *of this software and associated documentation files (the "Software"), to deal
 *in the Software without restriction, including without limitation the rights
 *to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 *copies of the Software, and to permit persons to whom the Software is
 *furnished to do so, subject to the following conditions:
 *
 *The above copyright notice and this permission notice shall be included in
 *all copies or substantial portions of the Software.
 *
 *THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 *OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 *THE SOFTWARE.
 *
 *
 *######################################################################
 *# The CuPy is designed based on NumPy's API.
 *# CuPy's source code and documents contain the original NumPy ones.
 *######################################################################
 *Copyright (c) 2005-2016, NumPy Developers.
 *All rights reserved.
 *
 *Redistribution and use in source and binary forms, with or without
 *modification, are permitted provided that the following conditions are
 *met:
 *
 *    * Redistributions of source code must retain the above copyright
 *       notice, this list of conditions and the following disclaimer.
 *
 *    * Redistributions in binary form must reproduce the above
 *       copyright notice, this list of conditions and the following
 *       disclaimer in the documentation and/or other materials provided
 *       with the distribution.
 *
 *    * Neither the name of the NumPy Developers nor the names of any
 *       contributors may be used to endorse or promote products derived
 *       from this software without specific prior written permission.
 *
 *THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 *A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 *OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 *SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 *LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 *DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 *THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 *(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *######################################################################
 */


#ifndef _STREAM_FACTORY_
#define _STREAM_FACTORY_
#include <mkldnn.hpp>
#include <string>
#include "layer.h"
#include <unordered_map>

// Usage:
// When stream is created, call:
// LayerFactory::get_instance().setRELUFwdLayer(<input pointer>, <layer>)
// then when forward is needed, call
// layer = LayerFactory::get_instance().getRELUFwdLayer(<input pointer>)

template <typename T>
class LayerFactory {
private:
    LayerFactory();

public:
    static LayerFactory& get_instance() {
        static LayerFactory instance_;
        return instance_;
    }

private:
    Layer<T>* get_layer(std::string      key);
    void      set_layer(std::string      key,
                        Layer<T>*        layer);

public:
    // relu stream
    Layer<T>* get_relu_layer(int          size);
    void      set_relu_layer(int          size,
                             Layer<T>*    layer);
    // relu4d stream
    Layer<T>* get_relu4d_layer(int        x_d1,
                               int        x_d2,
                               int        x_d3,
                               int        x_d4);
    void      set_relu4d_layer(int        x_d1,
                               int        x_d2,
                               int        x_d3,
                               int        x_d4,
                               Layer<T>*  layer);

    // maxpool stream
    Layer<T>* get_max_pool_layer(int       x_d1,
                                 int       x_d2,
                                 int       x_d3,
                                 int       x_d4,
                                 int       stride_y,
                                 int       stride_x,
                                 int       ksize_h,
                                 int       ksize_w,
                                 int       pad_l_h,
                                 int       pad_l_w,
                                 int       pad_r_h,
                                 int       pad_r_w);

    void      set_max_pool_layer(int       x_d1,
                                 int       x_d2,
                                 int       x_d3,
                                 int       x_d4,
                                 int       stride_y,
                                 int       stride_x,
                                 int       ksize_h,
                                 int       ksize_w,
                                 int       pad_l_h,
                                 int       pad_l_w,
                                 int       pad_r_h,
                                 int       pad_r_w,
                                 Layer<T>* layer);

    // avgpool stream
    Layer<T>* get_avg_pool_layer(int       x_d1,
                                 int       x_d2,
                                 int       x_d3,
                                 int       x_d4,
                                 int       stride_y,
                                 int       stride_x,
                                 int       ksize_h,
                                 int       ksize_w,
                                 int       pad_l_h,
                                 int       pad_l_w,
                                 int       pad_r_h,
                                 int       pad_r_w);

    void      set_avg_pool_layer(int       x_d1,
                                 int       x_d2,
                                 int       x_d3,
                                 int       x_d4,
                                 int       stride_y,
                                 int       stride_x,
                                 int       ksize_h,
                                 int       ksize_w,
                                 int       pad_l_h,
                                 int       pad_l_w,
                                 int       pad_r_h,
                                 int       pad_r_w,
                                 Layer<T>* layer);

    // Local Response Normalization stream
    // TODO cross channel support
    Layer<T>* get_lrn_layer(int               x_d1,
                            int               x_d2,
                            int               x_d3,
                            int               x_d4,
                            int               local_size,
                            double             k,
                            double             alpha,
                            double             beta);
    void          set_lrn_layer(int               x_d1,
                                int               x_d2,
                                int               x_d3,
                                int               x_d4,
                                int               local_size,
                                double             k,
                                double             alpha,
                                double             beta,
                                Layer<T>*     layer);

    // Softmax Cross Entropy stream
    Layer<T>* get_softmax2d_layer(int               d1,
                                  int               d2,
                                  int               axis);
    void      set_softmax2d_layer(int               d1,
                                  int               d2,
                                  int               axis,
                                  Layer<T>*     layer);
    Layer<T>* get_softmax4d_layer(int               d1,
                                  int               d2,
                                  int               d3,
                                  int               d4,
                                  int               axis);
    void      set_softmax4d_layer(int               d1,
                                  int               d2,
                                  int               d3,
                                  int               d4,
                                  int               axis,
                                  Layer<T>*     layer);

    // Convolution2d stream
    Layer<T>* get_conv2d_layer( int           x_d1,
                                int           x_d2,
                                int           x_d3,
                                int           x_d4,
                                int           W_d1,
                                int           W_d2,
                                int           W_d3,
                                int           W_d4,
                                int           b_d1,
                                int           ksize_h,
                                int           ksize_w,
                                int           stride_y,
                                int           stride_x,
                                int           pad_l_h,
                                int           pad_l_w,
                                int           pad_r_h,
                                int           pad_r_w);

    void       set_conv2d_layer(int           x_d1,
                                int           x_d2,
                                int           x_d3,
                                int           x_d4,
                                int           W_d1,
                                int           W_d2,
                                int           W_d3,
                                int           W_d4,
                                int           b_d1,
                                int           ksize_h,
                                int           ksize_w,
                                int           stride_y,
                                int           stride_x,
                                int           pad_l_h,
                                int           pad_l_w,
                                int           pad_r_h,
                                int           pad_r_w,
                                Layer<T>*     layer);

    // DeConvolution2d stream
    Layer<T>* get_deconv2d_layer( int           x_d1,
                                  int           x_d2,
                                  int           x_d3,
                                  int           x_d4,
                                  int           W_d1,
                                  int           W_d2,
                                  int           W_d3,
                                  int           W_d4,
                                  int           b_d1,
                                  int           ksize_h,
                                  int           ksize_w,
                                  int           stride_y,
                                  int           stride_x,
                                  int           pad_l_h,
                                  int           pad_l_w,
                                  int           pad_r_h,
                                  int           pad_r_w);

    void       set_deconv2d_layer(int           x_d1,
                                  int           x_d2,
                                  int           x_d3,
                                  int           x_d4,
                                  int           W_d1,
                                  int           W_d2,
                                  int           W_d3,
                                  int           W_d4,
                                  int           b_d1,
                                  int           ksize_h,
                                  int           ksize_w,
                                  int           stride_y,
                                  int           stride_x,
                                  int           pad_l_h,
                                  int           pad_l_w,
                                  int           pad_r_h,
                                  int           pad_r_w,
                                  Layer<T>*     layer);

    //Linear stream
    Layer<T>* get_linear_layer(int            x_d1,
                               int            x_d2,
                               int            W_d1,
                               int            W_d2,
                               int            b_d1);
    void      set_linear_layer(int            x_d1,
                               int            x_d2,
                               int            W_d1,
                               int            W_d2,
                               int            b_d1,
                               Layer<T>*      layer);

    Layer<T>* get_batch_normalization_layer(int       x_d1,
                                            int       x_d2,
                                            int       x_d3,
                                            int       x_d4,
                                            int       W_d1,
                                            int       W_d2,
                                            int       mean_d1,
                                            double    eps,
                                            bool      is_training,
                                            bool      has_weights,
                                            bool      fixed_mean_var);
    void      set_batch_normalization_layer(int       x_d1,
                                            int       x_d2,
                                            int       x_d3,
                                            int       x_d4,
                                            int       W_d1,
                                            int       W_d2,
                                            int       mean_d1,
                                            double    eps,
                                            bool      is_training,
                                            bool      has_weights,
                                            bool      fixed_mean_var,
                                            Layer<T>* layer);

    LayerFactory(LayerFactory const&)  = delete;
    void operator=(LayerFactory const&) = delete;

private:
    //LayerFactory(LayerFactory const&);
    //void operator=(LayerFactory const&);
    std::unordered_map<std::string, Layer<T>*> map_;
};

#endif // _STREAM_FACTORY_


// vim: et ts=4 sw=4 cindent cino^=l0,\:0,N-s
