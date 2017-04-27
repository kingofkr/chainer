from chainer import function
from chainer.utils import type_check

from mkldnn.runtime import Engine
from mkldnn.compute_complex import *

# Most important thing
from mkldnn.support import *
import mkldnn.memory as m
import mkldnn.convolution_forward as conv_forward
import mkldnn.convolution_backward_data as conv_backdata
import mkldnn.convolution_backward_weights as conv_backweights
from mkldnn.mdarray import *

def create_forward_desc(d_creator, o_expect, *inputs):
    inputs_d = [m.desc(v.shape, m.memory.f32, m.memory.any)
            for v in inputs if v is not None]

    return d_creator(forward, *inputs_d, o_expect)

def create_backward_desc(d_creator, *inputs):
    inputs_d = [m.desc(v.shape, m.memory.f32, m.memory.any)
            for v in inputs if v is not None]

    return d_creator(*inputs_d)

class ConvolutionForward(ComputeComplex):
    def __init__(self, x, W, b = None, e=Engine()):
        super(LinearForward, self).__init__()
        x = _as_mat(x)

        y_d = m.desc((x.shape[0], W.shape[0]), m.memory.f32, m.memory.any)

        # Create primitive_desc from any
        cc_d = create_forward_desc(ip_forward.desc, y_d, x, W, b)
        cc_pd = ip_forward.primitive_desc(cc_d, e)

        # Transform inputs
        self.x = array(x, m.memory.nc, e)
        self.W = array(W, m.memory.oi, e)
        if b is not None:
            self.b = array(b, m.memory.x, e)

        # Prepare output
        y = mdarray(cc_pd.dst_primitive_desc())

        dag = self.dag_

        # Reorder if must
        x_m = reorder_if_must(self.x.memory, cc_pd.src_primitive_desc(), dag)
        W_m = reorder_if_must(self.W.memory, cc_pd.weights_primitive_desc(), dag)

        if b is None:
            dag.push_back(ip_forward.inner_product_forward(cc_pd,
                at(x_m), at(W_m), y.memory))
        else:
            dag.push_back(ip_forward.inner_product_forward(cc_pd,
                at(x_m), at(W_m), at(self.b.memory), y.memory))

        self.x_m = x_m
        self.W_m = W_m
        self._hint = cc_pd
        self.outputs = y,

class ConvolutionBackwardData(ComputeComplex):
    def __init__(self, x, W, dummy, gy, hint, e=Engine()):
        super(LinearBackwardData, self).__init__()
        x = _as_mat(x)

        # Create primitive descriptor
        cc_d = create_backward_desc(ip_backdata.desc, x, W, gy)
        cc_pd = ip_backdata.primitive_desc(cc_d, e, hint)

        # Transform inputs
        self.gy = array(gy, m.memory.nc, e)
        self.W = array(W, m.memory.oi, e)

        # Prepare output mdarray
        gx = mdarray(cc_pd.diff_src_primitive_desc())

        dag = self.dag_

        # Reorder if must
        gy_m = reorder_if_must(self.gy.memory, cc_pd.diff_dst_primitive_desc(), dag)
        W_m = reorder_if_must(self.W.memory, cc_pd.weights_primitive_desc(), dag)

        dag.push_back(ip_backdata.inner_product_backward_data(cc_pd,
            at(gy_m), at(W_m), gx.memory))

        self.gy_m = gy_m
        self.W_m = W_m

        self.outputs = gx,

class ConvolutionBackwardWeighs(ComputeComplex):
    def __init__(self, x, W, b, gy, hint, e=Engine()):
        super(LinearBackwardWeighs, self).__init__()
        x = _as_mat(x)

        cc_d = create_backward_desc(ip_backweights.desc, x, W, b, gy)
        cc_pd = ip_backweights.primitive_desc(cc_d, e, hint)

        # Transfer inputs to mdarray
        self.gy = array(gy, m.memory.nc, e)
        self.x = array(x, m.memory.nc, e)

        # Prepare outputs mdarray
        gW = mdarray(cc_pd.diff_weights_primitive_desc())
        if b is not None:
            gb = mdarray(cc_pd.diff_bias_primitive_desc())

        dag = self.dag_

        # Reorder if must
        gy_m = reorder_if_must(self.gy.memory, cc_pd.diff_dst_primitive_desc(), dag)
        x_m = reorder_if_must(self.x.memory, cc_pd.src_primitive_desc(), dag)

        if b is not None:
            dag.push_back(ip_backweights.inner_product_backward_weights(cc_pd,
                at(x_m), at(self.gy.memory), gW.memory, gb.memory))
        else:
            dag.push_back(ip_backweights.inner_product_backward_weights(cc_pd,
                at(x_m), at(self.gy.memory), gW.memory))

        self.x_m = x_m

        if b is not None:
            self.outputs = gW, gb
        else:
            self.outputs = gW,

def _pair(x):
    if hasattr(x, '__getitem__'):
        return x
    return x, x


class Convolution2DFunctionMKLDNN(function.Function):

    def __init__(self, stride=1, pad=0, cover_all=False, deterministic=False):
        self.sy, self.sx = _pair(stride)
        self.ph, self.pw = _pair(pad)
        self.cover_all = cover_all
        self.deterministic = deterministic

    def check_type_forward(self, in_types):
        n_in = in_types.size()
        type_check.expect(2 <= n_in, n_in <= 3)

        x_type = in_types[0]
        w_type = in_types[1]
        type_check.expect(
            x_type.dtype.kind == 'f',
            w_type.dtype.kind == 'f',
            x_type.ndim == 4,
            w_type.ndim == 4,
            x_type.shape[1] == w_type.shape[1],
        )

        if type_check.eval(n_in) == 3:
            b_type = in_types[2]
            type_check.expect(
                b_type.dtype == x_type.dtype,
                b_type.ndim == 1,
                b_type.shape[0] == w_type.shape[0],
            )

    def forward_cpu(self, inputs):
        cc = ConvolutionForward(*inputs)
        self.hint = cc.hint

        y, = cc.execute_on()

        return y,

    def backward_cpu(self, inputs, grad_outputs):
        if len(inputs) == 2:
            inputs += None,

        cc_data = ConvolutionBackwardData(*inputs, *grad_outputs, self.hint)
        cc_weight = ConvolutionBackwardWeighs(*inputs, *grad_outputs, self.hint)

        gx = cc_data.execute_on()
        gW_b = cc_weight.execute_on()

        return gx + gW_b

def convolution_2d_mkldnn(x, W, b=None):
    """Linear function, or affine transformation.

    It accepts two or three arguments: an input minibatch ``x``, a weight
    matrix ``W``, and optionally a bias vector ``b``. It computes
     .. math:: Y = xW^\\top + b.

    Args:
        x (:class:`~chainer.Variable` or :class:`numpy.ndarray` or \
        :class:`cupy.ndarray`): Input variable, which is a :math:`(s_B, s_1, \
            s_2, ..., s_n)`-shaped float array. Its first dimension
            :math:`(s_B)` is assumed to be the *minibatch dimension*. The
            other dimensions are treated as concatenated one dimension whose
            size must be :math:`(s_1 * ... * s_n = N)`.
        W (:class:`~chainer.Variable` or :class:`numpy.ndarray` or \
        :class:`cupy.ndarray`): Weight variable of shape :math:`(M, N)`,
            where :math:`(N = s_1 * ... * s_n)`.
        b (:class:`~chainer.Variable` or :class:`numpy.ndarray` or \
        :class:`cupy.ndarray`): Bias variable (optional) of shape
            :math:`(M,)`.

    Returns:
        ~chainer.Variable: Output variable. A float array with shape
        of :math:`(s_B, M)`.

    .. seealso:: :class:`~chainer.links.Linear`

    .. admonition:: Example

        >>> x = np.random.uniform(0, 1, (3, 4)).astype('f')
        >>> W = np.random.uniform(0, 1, (5, 4)).astype('f')
        >>> b = np.random.uniform(0, 1, (5,)).astype('f')
        >>> y = F.linear(x, W, b)
        >>> y.shape
        (3, 5)

    """
    func = Convolution2DFunction(
        stride, pad, cover_all, deterministic)
    if b is None:
        return func(x, W)
    else:
        return func(x, W, b)