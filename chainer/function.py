import collections
import traceback
import weakref

import six
import numpy as np
import chainer

from chainer import configuration
from chainer import cuda
from chainer import flag
from chainer.utils import type_check
from chainer import variable
from chainer import mkld
if mkld.enable_cosim():
    import copy
    from chainer import testing


def no_backprop_mode():
    """Disable back-propagation for Variable whose volatile is auto.

    In the default setting a :class:`~chainer.Variable` object whose
    ``volatile`` attribute is ``'auto'`` behaves like a **non-volatile**
    variable. That means such a :class:`~chainer.Variable` object builds a
    computational graph, consumes memory to store the graph, and you can
    execute back-propagation for it. With this context such a
    :class:`~chainer.Variable` object behaves like a **volatile** variable.
    So, you can easily switch training and evaluation.

    In this example, the volatility of ``x`` and ``y`` is ``'auto'``. So, ``y``
    does not have a computational graph.

    >>> x = chainer.Variable(numpy.array([1,], 'f'), volatile='auto')
    >>> with chainer.no_backprop_mode():
    ...    y = x + 1

    """
    return configuration.using_config('enable_backprop', False)


def force_backprop_mode():
    """Enable back-propagation for Variable whose volatile is auto.

    When you want to enable back-propagation in :func:`no_backprop_mode`,
    call this method. In this context, :class:`~chainer.Variable` object
    whose ``volatile`` attribute is ``'auto'`` behaves like a **volatile**
    variable. That means you can disable :func:`no_backprop_mode` in this
    context.

    If you call this method outside of :func:`no_backprop_mode` context, it
    changes nothing. :class:`~chainer.Variable` object with ``volatile='auto'``
    behaves like a volatile variable by default.

    In this example, the volatility of ``x`` and ``y`` is ``'auto'``. In
    :func:`no_backprop_mode` context, ``y`` does not have a computational graph
    but in :func:`force_backprop_mode` it has a graph.

    >>> with chainer.no_backprop_mode():
    ...   # Variable with volatile='auto' behaves like volatile='on'
    ...   with chainer.force_backprop_mode():
    ...     # Variable with volatile='auto' behaves like volatile='off'
    ...     y = x + 1

    .. seealso::

       See :func:`no_backprop_mode` for details of back-prop mode.

    """
    return configuration.using_config('enable_backprop', True)


class Function(object):

    """Function on variables with backpropagation ability.

    All function implementations defined in :mod:`chainer.functions` inherit
    this class.

    The main feature of this class is keeping track of function applications as
    a backward graph. When a function is applied to :class:`Variable` objects,
    its :meth:`forward` method is called on :data:`~Variable.data` fields of
    input variables, and at the same time it chains references from output
    variables to the function and from the function to its inputs.

    .. note::
       As of v1.5, a function instance cannot be used twice in any
       computational graphs. In order to reuse a function object multiple
       times, use :func:`copy.copy` before the function applications to make a
       copy of the instance.

       This restriction also means that we cannot make a *stateful function*
       anymore. For example, it is now not allowed to let a function hold
       parameters. Define a function as a pure (stateless) procedure, and use
       :class:`~chainer.Link` to combine it with parameter variables.

    .. admonition:: Example


       Let ``x`` an instance of :class:`Variable` and ``f`` an instance of
       :class:`Function` taking only one argument. Then a line

       >>> import numpy, chainer, chainer.functions as F
       >>> x = chainer.Variable(numpy.zeros(10))
       >>> f = F.Identity()
       >>> y = f(x)

       computes a new variable ``y`` and creates backward references. Actually,
       backward references are set as per the following diagram::

           x <--- f <--- y

       If an application of another function ``g`` occurs as

       >>> g = F.Identity()
       >>> z = g(x)

       then the graph grows with a branch::

               |--- f <--- y
           x <-+
               |--- g <--- z

       Note that the branching is correctly managed on backward computation,
       i.e. the gradients from ``f`` and ``g`` are accumulated to the gradient
       of ``x``.

    Every function implementation should provide :meth:`forward_cpu`,
    :meth:`forward_gpu`, :meth:`backward_cpu` and :meth:`backward_gpu`.
    Alternatively, one can provide :meth:`forward` and :meth:`backward` instead
    of separate methods. Backward methods have default implementations that
    just return ``None``, which indicates that the function is non-
    differentiable.

    Attributes:
        inputs: A tuple or list of input variables.
        outputs: A tuple or list of output variables.

    """

    def __call__(self, *inputs):
        """Applies forward propagation with chaining backward references.

        Basic behavior is expressed in documentation of :class:`Function`
        class.

        .. note::

           If the :data:`~Variable.data` attribute of input variables exist on
           GPU device, then, before it calls :meth:`forward` method, the
           appropriate device is selected, so in most cases implementers do
           not need to take care of device selection.

        Args:
            inputs: Tuple of input :class:`Variable`, :class:`numpy.ndarray` or
                :class:`cupy.ndarray` objects. The volatile flags of all input
                variables must agree. If the input is an :class:`numpy.ndarray`
                or a :class:`cupy.ndarray`, it is automatically wrapped with
                :class:`Variable`.

        Returns:
            One :class:`Variable` object or a tuple of multiple
            :class:`Variable` objects.

        """

        inputs = [x if isinstance(x, chainer.Variable)
                  else chainer.Variable(x, volatile=flag.AUTO)
                  for x in inputs]
        self.mkldnn_opt = False
        in_data = tuple([x.data for x in inputs])
        if chainer.is_debug():
            self._stack = traceback.extract_stack()

        if configuration.config.type_check:
            self._check_data_type_forward(in_data)

        hooks = chainer.get_function_hooks()
        if self._n_local_function_hooks != 0:
            hooks = collections.OrderedDict(hooks)
            hooks.update(self.local_function_hooks)
        for hook in six.itervalues(hooks):
            hook.forward_preprocess(self, in_data)
        # Forward prop
        with cuda.get_device(*in_data):
            cosim_outputs = self.forward_cpu_cosim(in_data)
            outputs = self.forward(in_data)
            self.cpu_cosim_verify_result(outputs, cosim_outputs)
            assert type(outputs) == tuple
        for hook in six.itervalues(hooks):
            hook.forward_postprocess(self, in_data)

        if chainer.is_debug():
            if any(out.dtype.kind == 'f' and
                   cuda.get_array_module(out).isnan(out).any()
                   for out in outputs):
                msg = 'NaN is detected on forward computation'
                raise RuntimeError(msg)

        out_v = flag.aggregate_flags([x.volatile for x in inputs])
        ret = tuple([variable.Variable(y, volatile=out_v) for y in outputs])

        if out_v == 'on':
            build_graph = False
        elif out_v == 'off':
            build_graph = True
        else:
            build_graph = configuration.config.enable_backprop

        if build_graph:
            # Topological ordering
            self.rank = max([x.rank for x in inputs]) if inputs else 0
            # Backward edges
            for y in ret:
                y.set_creator(self)
            self.inputs = inputs
            # Forward edges (must be weak references)
            self.outputs = tuple([weakref.ref(y) for y in ret])

        if len(ret) == 1:
            return ret[0]
        else:
            return ret

    @property
    def local_function_hooks(self):
        """Ordered Dictionary of registered function hooks.

        Contrary to ``chainer.thread_local.function_hooks``,
        which registers its elements to all functions,
        Function hooks in this property is specific to this function.
        """
        if not hasattr(self, '_local_function_hooks'):
            self._local_function_hooks = collections.OrderedDict()
        return self._local_function_hooks

    @property
    def _n_local_function_hooks(self):
        if hasattr(self, '_local_function_hooks'):
            return len(self._local_function_hooks)
        return 0

    @property
    def label(self):
        """Short text that represents the function.

        The default implementation returns its type name.
        Each function should override it to give more information.
        """
        return self.__class__.__name__

    @property
    def stack(self):
        if hasattr(self, '_stack'):
            return self._stack
        else:
            return None

    def _check_data_type_forward(self, in_data):
        in_type = type_check.get_types(in_data, 'in_types', False)
        with type_check.get_function_check_context(self):
            self.check_type_forward(in_type)

    def check_type_forward(self, in_types):
        """Checks types of input data before forward propagation.

        Before :meth:`forward` is called, this function is called.
        You need to validate types of input data in this function
        using :ref:`the type checking utilities <type-check-utils>`.

        Args:
            in_types (~chainer.utils.type_check.TypeInfoTuple): The type
                information of input data for :meth:`forward`.
        """
        pass

    def forward(self, inputs):
        """Applies forward propagation to input arrays.

        It delegates the procedure to :meth:`forward_cpu` or
        :meth:`forward_gpu` by default. Which it selects is determined by the
        type of input arrays.
        Implementations of :class:`Function` must implement either CPU/GPU
        methods or this method.

        Args:
            inputs: Tuple of input array(s).

        Returns:
            Tuple of output array(s).

        .. warning::

            Implementations of :class:`Function` must take care that the
            return value must be a tuple even if it returns only one array.

        """
        if any(isinstance(x, cuda.ndarray) for x in inputs):
            return self.forward_gpu(inputs)
        else:
            return self.forward_cpu(inputs)

    def forward_cpu(self, inputs):
        """Applies forward propagation to input arrays on CPU.

        Args:
            inputs: Tuple of :class:`numpy.ndarray` object(s).

        Returns:
            tuple: Tuple of :class:`numpy.ndarray` object(s).

        .. warning::

            Implementations of :class:`Function` must take care that the
            return value must be a tuple even if it returns only one array.

        """
        raise NotImplementedError()

    def forward_cpu_cosim(self, inputs):
        """forward cosim  between numpy and MKLDNN
        """
        if not mkld.enable_cosim():
            return None
        if self.func_in_cosim_skip_list():
            return None
        self.cosim_func = copy.copy(self)
        cosim_input = copy.copy(inputs)
        print('forward_cpu_cosim')
        print(self.cosim_func)
        mkld.set_mkldnn_disabled()
        outputs_cosim = self.cosim_func.forward(cosim_input)
        mkld.set_mkldnn_enabled()
        return outputs_cosim

    def forward_gpu(self, inputs):
        """Applies forward propagation to input arrays on GPU.

        Args:
            inputs: Tuple of :class:`cupy.ndarray` object(s).

        Returns:
            tuple: Tuple of :class:`cupy.ndarray` object(s).

        .. warning::

            Implementations of :class:`Function` must take care that the
            return value must be a tuple even if it returns only one array.

        """
        raise NotImplementedError()

    def backward(self, inputs, grad_outputs):
        """Applies backprop to output gradient arrays.

        It delegates the procedure to :meth:`backward_cpu` or
        :meth:`backward_gpu` by default. Which it selects is determined by the
        type of input arrays and output gradient arrays. Implementations of
        :class:`Function` must implement either CPU/GPU methods or this method,
        if the function is intended to be backprop-ed.

        Args:
            inputs: Tuple of input arrays.
            grad_outputs: Tuple of output gradient arrays.

        Returns:
            tuple: Tuple of input gradient arrays. Some or all of them can be
            ``None``, if the function is not differentiable on
            inputs.

        .. warning::

            Implementations of :class:`Function` must take care that the
            return value must be a tuple even if it returns only one array.

        """
        if any(isinstance(x, cuda.ndarray) for x in inputs + grad_outputs):
            return self.backward_gpu(inputs, grad_outputs)
        else:
            return self.backward_cpu(inputs, grad_outputs)

    def backward_cpu_cosim(self, inputs, grad_outputs):
        """backward cosim between numpy and MKLDNN
        """
        if not mkld.enable_cosim():
            return None
        if self.func_in_cosim_skip_list():
            return None
        print('backward_cosim')
        print(self.cosim_func)
        cosim_inputs = copy.copy(inputs)
        cosim_grad_outputs = copy.copy(grad_outputs)
        mkld.set_mkldnn_disabled()
        output_cosim = self.cosim_func.backward(cosim_inputs, cosim_grad_outputs)
        mkld.set_mkldnn_enabled()
        return output_cosim

    def func_in_cosim_skip_list(self):
        cosim_skip_list = (
            chainer.functions.noise.dropout.Dropout,
            chainer.functions.noise.gaussian.Gaussian,
            chainer.functions.noise.zoneout.Zoneout
        )
        for x in cosim_skip_list:
            if isinstance(self, x):
                return True
        return False

    def cpu_cosim_verify_result(self, mkl_result, numpy_result):
        """cosim verify result between MKLDNN and numpy
        """
        if not mkld.enable_cosim():
            return None
        if self.func_in_cosim_skip_list():
            return None
        check_options = {'atol': 5e-1, 'rtol': 5e-1, 'verbose': True}
        i = 0
        for mkl_x in numpy_result:
            numpy_y = mkl_result[i]
            i = i + 1
            if isinstance(mkl_x, np.ndarray):
                testing.assert_allclose(mkl_x, numpy_y, **check_options)
            elif mkl_x is None:
                if numpy_y is not None:
                    raise KeyError('cosim mismatch')

    def backward_cpu(self, inputs, grad_outputs):
        """Applies backprop to output gradient arrays on CPU.

        Args:
            inputs: Tuple of input :class:`numpy.ndarray` object(s).
            grad_outputs: Tuple of output gradient :class:`numpy.ndarray`
                object(s).

        Returns:
            tuple: Tuple of input gradient :class:`numpy.ndarray` object(s).
            Some or all of them can be ``None``, if the function is not
            differentiable on corresponding inputs.

        .. warning::

            Implementations of :class:`Function` must take care that the
            return value must be a tuple even if it returns only one array.

        """
        return tuple(None for _ in inputs)

    def backward_gpu(self, inputs, grad_outputs):
        """Applies backprop to output gradient arrays on GPU.

        Args:
            inputs: Tuple of input :class:`cupy.ndarray`
                object(s).
            grad_outputs: Tuple of output gradient
                :class:`cupy.ndarray` object(s).

        Returns:
            tuple: Tuple of input gradient :class:`cupy.ndarray`
            object(s). Some or all of them can be ``None``, if the function is
            not differentiable on corresponding inputs.

        .. warning::

            Implementations of :class:`Function` must take care that the
            return value must be a tuple even if it returns only one array.

        """
        return tuple(None for _ in inputs)

    def unchain(self):
        """Purges in/out variables and this function itself from the graph.

        This method is called from :meth:`Variable.unchain_backward` method.

        """
        for y in self.outputs:
            y_ref = y()
            if y_ref is not None:
                y_ref.creator = None
        self.inputs = None

    def add_hook(self, hook, name=None):
        """Registers the function hook.

        Args:
            hook(~chainer.function.FunctionHook):
                Function hook to be registered.
            name(str): Name of the function hook.
                name must be unique among function hooks
                registered to the function. If ``None``,
                default name of the function hook is used.
        """
        if not isinstance(hook, FunctionHook):
            raise TypeError('Hook must be a FunctionHook')
        if name is None:
            name = hook.name
        if name in self.local_function_hooks:
            raise KeyError('Hook %s already exists' % name)
        self.local_function_hooks[name] = hook

    def delete_hook(self, name):
        """Unregisters the function hook.

        Args:
            name(str): the name of the function hook
                to be unregistered.
        """
        del self.local_function_hooks[name]


class FunctionHook(object):
    """Base class of hooks for Functions.

    :class:`~chainer.function.FunctionHook` is an callback object
    that is registered to :class:`~chainer.Function`.
    Registered function hooks are invoked before and after
    forward and backward operations of each function.

    Function hooks that derive :class:`FunctionHook` are required
    to implement four methods:
    :meth:`~chainer.function.FunctionHook.forward_preprocess`,
    :meth:`~chainer.function.FunctionHook.forward_postprocess`,
    :meth:`~chainer.function.FunctionHook.backward_preprocess`, and
    :meth:`~chainer.function.FunctionHook.backward_postprocess`.
    By default, these methods do nothing.

    Specifically, when :meth:`~chainer.Function.__call__`
    method of some function is invoked,
    :meth:`~chainer.function.FunctionHook.forward_preprocess`
    (resp. :meth:`~chainer.function.FunctionHook.forward_postprocess`)
    of all function hooks registered to this function are called before
    (resp. after) forward propagation.

    Likewise, when :meth:`~chainer.Variable.backward` of some
    :class:`~chainer.Variable` is invoked,
    :meth:`~chainer.function.FunctionHook.backward_preprocess`
    (resp. :meth:`~chainer.function.FunctionHook.backward_postprocess`)
    of all function hooks registered to the function which holds this variable
    as a gradient are called before (resp. after) backward propagation.

    There are two ways to register :class:`~chainer.function.FunctionHook`
    objects to :class:`~chainer.Function` objects.

    First one is to use ``with`` statement. Function hooks hooked
    in this way are registered to all functions within ``with`` statement
    and are unregistered at the end of ``with`` statement.

    The following code is a simple example in which
    we measure the elapsed time of a part of forward propagation procedure
    with :class:`~chainer.function_hooks.TimerHook`, which is a subclass of
    :class:`~chainer.function.FunctionHook`.

    >>> import chainer, chainer.links as L, chainer.functions as F
    ... class Model(chainer.Chain):
    ...     def __call__(self, x1):
    ...         return F.exp(self.l(x1))
    ... model1 = Model(l=L.Linear(10, 10))
    ... model2 = Model(l=L.Linear(10, 10))
    ... x = chainer.Variable(numpy.zeros((1, 10), 'f'))
    ... with chainer.function_hooks.TimerHook() as m:
    ...     _ = model1(x)
    ...     y = model2(x)
    ...     print(m.total_time())
    ... model3 = Model(l=L.Linear(10, 10))
    ... z = model3(y)

    In this example, we measure the elapsed times for each forward propagation
    of all functions in ``model1`` and ``model2`` (specifically,
    :class:`~chainer.functions.LinearFunction` and
    :class:`~chainer.functions.Exp` of ``model1`` and ``model2``).
    Note that ``model3`` is not a target of measurement
    as :class:`~chainer.function_hooks.TimerHook` is unregistered
    before forward propagation of ``model3``.

    .. note::

       Chainer stores the dictionary of registered function hooks
       as a thread local object. So, function hooks registered
       are different depending on threads.

    The other one is to register directly to
    :class:`~chainer.Function` object with
    :meth:`~chainer.Function.add_hook` method.
    Function hooks registered in this way can be removed by
    :meth:`~chainer.Function.delete_hook` method.
    Contrary to former registration method, function hooks are registered
    only to the function which :meth:`~chainer.Function.add_hook`
    is called.

    Args:
        name(str): Name of this function hook.
    """

    name = 'FunctionHook'

    def __enter__(self):
        function_hooks = chainer.get_function_hooks()
        if self.name in function_hooks:
            raise KeyError('hook %s already exists' % self.name)

        function_hooks[self.name] = self
        return self

    def __exit__(self, *_):
        del chainer.get_function_hooks()[self.name]

    # forward
    def forward_preprocess(self, function, in_data):
        """Callback function invoked before forward propagation.

        Args:
            function(~chainer.Function): Function object to which
                the function hook is registered.
            in_data(tuple of numpy.ndarray or tuple of cupy.ndarray):
                Input data of forward propagation.
        """
        pass

    def forward_postprocess(self, function, in_data):
        """Callback function invoked after forward propagation.

        Args:
            function(~chainer.Function): Function object to which
                the function hook is registered.
            in_data(tuple of numpy.ndarray or tuple of cupy.ndarray):
                Input data of forward propagation.
        """
        pass

    # backward
    def backward_preprocess(self, function, in_data, out_grad):
        """Callback function invoked before backward propagation.

        Args:
            function(~chainer.Function): Function object to which
                the function hook is registered.
            in_data(tuple of numpy.ndarray or tuple of cupy.ndarray):
                Input data of forward propagation.
            out_grad(tuple of numpy.ndarray or tuple of cupy.ndarray):
                Gradient data of backward propagation.
        """
        pass

    def backward_postprocess(self, function, in_data, out_grad):
        """Callback function invoked after backward propagation.

        Args:
            function(~chainer.Function): Function object to which
                the function hook is registered.
            in_data(tuple of numpy.ndarray or tuple of cupy.ndarray):
                Input of forward propagation.
            out_grad(tuple of numpy.ndarray or tuple of cupy.ndarray):
                Gradient data of backward propagation.
        """
        pass
