from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from caffe2.python import core, workspace
from hypothesis import given
import caffe2.python.hypothesis_test_util as hu
import hypothesis.strategies as st
import numpy as np

import unittest


class TestSoftmaxOps(hu.HypothesisTestCase):

    @given(n=st.integers(2, 10), D=st.integers(4, 16), **hu.gcs)
    def test_softmax(self, n, D, gc, dc):
        # n = number of examples, D = |labels|
        # Initialize X and add 1e-2 for numerical stability
        X = np.random.rand(n, D).astype(np.float32)
        X = X + 1e-2

        # Reference implementation of cross entropy with soft labels
        def label_softmax(X):
            probs = np.zeros((n, D))
            rowmax = np.zeros(n)
            for i in range(n):
                rowmax[i] = max(X[i, ])
                # We need to subtract the max to avoid numerical issues
                probs[i] = X[i] - rowmax[i]
                exps = np.exp(probs[i, ])
                norm = sum(exps)
                probs[i, ] = exps / norm

            return [probs]

        op = core.CreateOperator(
            "Softmax",
            ["X"],
            ["probs"]
        )

        self.assertReferenceChecks(
            device_option=gc,
            op=op,
            inputs=[X],
            reference=label_softmax,
        )

        self.assertGradientChecks(
            gc, op, [X], 0, [0], stepsize=1e-4, threshold=1e-2)

    @given(axis=st.integers(min_value=1, max_value=4), **hu.gcs)
    def test_softmax_axis(self, axis, gc, dc):
        np.random.seed(1)
        X = np.random.randn(1, 2, 3, 2, 1).astype(np.float32)
        X = X + 1e-2

        def prod(xs):
            p = 1
            for x in xs:
                p *= x
            return p

        N = prod(list(X.shape)[:axis])
        D = prod(list(X.shape)[axis:])

        # Reference implementation of cross entropy with soft labels
        def label_softmax(X):
            X_ = X.reshape(N, D)
            probs = np.zeros((N, D))
            rowmax = np.zeros(N)
            for i in range(N):
                rowmax[i] = max(X_[i, ])
                # We need to subtract the max to avoid numerical issues
                probs[i] = X_[i] - rowmax[i]
                exps = np.exp(probs[i, ])
                norm = sum(exps)
                probs[i, ] = exps / norm

            return [probs.reshape(*X.shape)]

        op = core.CreateOperator(
            "Softmax",
            ["X"],
            ["probs"],
            axis=axis,
        )

        self.assertReferenceChecks(
            device_option=gc,
            op=op,
            inputs=[X],
            reference=label_softmax,
        )

        self.assertGradientChecks(
            gc, op, [X], 0, [0], stepsize=1e-4, threshold=1e-2)

    @given(n=st.integers(2, 10), D=st.integers(4, 16), **hu.gcs)
    def test_softmax_with_loss(self, n, D, gc, dc):
        # n = number of examples, D = |labels|
        # Initialize X and add 1e-2 for numerical stability
        X = np.random.rand(n, D).astype(np.float32)
        X = X + 1e-2

        # Initialize label
        label = (np.random.rand(n) * D).astype(np.int32)

        # Reference implementation of cross entropy with soft labels
        def label_softmax_crossent(X, label):
            probs = np.zeros((n, D))
            rowmax = np.zeros(n)
            for i in range(n):
                rowmax[i] = max(X[i, ])
                # We need to subtract the max to avoid numerical issues
                probs[i] = X[i] - rowmax[i]
                exps = np.exp(probs[i, ])
                norm = sum(exps)
                probs[i, ] = exps / norm

            label_xent = [-np.log(max(probs[i][label[i]], 1e-20))
                          for i in range(n)]
            avgloss = np.sum(label_xent) / float(n)
            return (probs, avgloss)

        op = core.CreateOperator(
            "SoftmaxWithLoss",
            ["X", "label"],
            ["probs", "avgloss"]
        )

        self.assertReferenceChecks(
            device_option=gc,
            op=op,
            inputs=[X, label],
            reference=label_softmax_crossent,
        )

        self.assertGradientChecks(
            gc, op, [X, label], 0, [1], stepsize=1e-4, threshold=1e-2)

    @unittest.skipIf(not workspace.has_gpu_support, "No gpu support")
    @given(n=st.integers(2, 5), D=st.integers(2, 4),
           weighted=st.booleans(), **hu.gcs_gpu_only)
    def test_spatial_softmax_with_loss(self, n, D, weighted, gc, dc):
        # n = number of examples, D = |labels|
        # Initialize X and add 1e-2 for numerical stability
        W = 18
        H = 12
        X = np.random.rand(n, D, H, W).astype(np.float32)
        X = X + 1e-2

        weighted = True
        weights = None
        if weighted:
            weights = np.random.rand(n, H, W).astype(np.float32)

        # Initialize label. Some of the labels are (-1), i.e "DONT CARE"
        label = (np.random.rand(n, H, W) * (D + 1)).astype(np.int32) - 1

        def label_softmax_crossent_spatial(X, label, weights=None):
            probs = np.zeros((n, D, H, W))
            rowmax = np.zeros((n, H, W))
            label_xent = np.zeros((n, H, W))
            for i in range(n):
                for x in range(W):
                    for y in range(H):
                        rowmax[i, y, x] = max(X[i, :, y, x])
                        # We need to subtract the max to avoid numerical issues
                        probs[i, :, y, x] = X[i, :, y, x] - rowmax[i, y, x]
                        exps = np.exp(probs[i, :, y, x])
                        probs[i, :, y, x] = exps / sum(exps)

                        label_xent[:, y, x] = \
                            [-np.log(max(probs[j, label[i, y, x], y, x], 1e-20))
                             for j in range(n)]

            total_xent = 0.0
            total_weight = 0.0
            for y in range(H):
                for x in range(W):
                    for i in range(n):
                        l = label[i, y, x]
                        if (l != (-1)):
                            w = 1.0 if weights is None else weights[i, y, x]
                            total_xent += \
                                -np.log(max(probs[i, l, y, x], 1e-20)) * w
                            total_weight += w
            print("Total weight {}".format(total_weight))

            return (probs, total_xent / total_weight)

        op = core.CreateOperator(
            "SoftmaxWithLoss",
            ["X", "label"] + ([] if weights is None else ["weights"]),
            ["probs", "avgloss"],
            spatial=1
        )

        inputs = [X, label] + ([] if weights is None else [weights])
        self.assertReferenceChecks(
            device_option=gc,
            op=op,
            inputs=inputs,
            reference=label_softmax_crossent_spatial,
        )

        self.assertGradientChecks(
            gc, op, inputs, 0, [1], stepsize=1e-4, threshold=1e-2)

    @unittest.skipIf(not workspace.has_gpu_support, "No gpu support")
    def test_compare_cpugpu(self):
        '''
        Additional test that checks CPU and GPU returns same values
        with larger examples. This is mainly to test the more complex
        GPU implementation is correct.
        '''
        from caffe2.proto import caffe2_pb2

        for j in range(3):
            gpuop = core.CreateOperator(
                "SoftmaxWithLoss",
                ["X_gpu", "label_gpu"],
                ["probs_gpu", "avgloss_gpu"],
                spatial=1,
                device_option=core.DeviceOption(caffe2_pb2.CUDA, 0)
            )

            cpuop = core.CreateOperator(
                "SoftmaxWithLoss",
                ["X_cpu", "label_cpu"],
                ["probs_cpu", "avgloss_cpu"],
                spatial=1,
                device_option=core.DeviceOption(caffe2_pb2.CPU)
            )

            n = 8
            D = 4
            W = 64 + int(np.random.rand(1) * 1024)
            H = 64 + int(np.random.rand(1) * 1024)

            print("W: {} H: {}".format(W, H))

            X = np.random.rand(n, D, H, W).astype(np.float32)
            X = X + 1e-2

            # Initialize label. Some of the labels are (-1), i.e "DONT CARE"
            label = (np.random.rand(n, H, W) * (D + 1)).astype(np.int32) - 1

            gpu0 = core.DeviceOption(caffe2_pb2.CUDA, 0)
            workspace.FeedBlob("X_cpu", X)
            workspace.FeedBlob("label_cpu", label)
            workspace.FeedBlob("X_gpu", X, device_option=gpu0)
            workspace.FeedBlob("label_gpu", label, device_option=gpu0)

            workspace.RunOperatorOnce(gpuop)
            workspace.RunOperatorOnce(cpuop)

            probs_gpu = workspace.FetchBlob("probs_gpu")
            probs_cpu = workspace.FetchBlob("probs_cpu")
            loss_gpu = workspace.FetchBlob("avgloss_gpu")
            loss_cpu = workspace.FetchBlob("avgloss_cpu")

            np.testing.assert_allclose(probs_gpu, probs_cpu, rtol=1e-4)
            np.testing.assert_allclose(loss_gpu, loss_cpu, rtol=1e-1)