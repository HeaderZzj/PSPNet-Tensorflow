from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from operator import mul
from functools import reduce

import tensorflow as tf

from nets import pspnet_rgbd_utils as pspnet_utils

pspnet_arg_scope = pspnet_utils.pspnet_arg_scope
slim = tf.contrib.slim

def root_block(inputs, scope=None):
  # conv     3x3, out depth  64, stride 2
  # conv     3x3, out depth  64, stride 1
  # conv     3x3, out depth 128, stride 1
  # max-pool 3x3, out depth 128, stride 2
  with tf.variable_scope(scope, 'root', [inputs]) as sc:
    depth_in = slim.utils.last_dimension(inputs.get_shape(), min_rank=4)
    conv1 = slim.conv2d(inputs, 64, [3, 3], stride=2, scope='conv1')
    conv2 = slim.conv2d(conv1,  64, [3, 3], stride=1, scope='conv2')
    conv3 = slim.conv2d(conv2, 128, [3, 3], stride=1, scope='conv3')
    pool1 = slim.max_pool2d(conv3, [3, 3], stride=2, scope='pool1')

  return pool1

def droot_block(inputs, scope=None):
  # conv     3x3, out depth  64, stride 2
  # conv     3x3, out depth  64, stride 1
  # conv     3x3, out depth 128, stride 1
  # max-pool 3x3, out depth 128, stride 2
  with tf.variable_scope(scope, 'droot', [inputs]) as sc:
    depth_in = slim.utils.last_dimension(inputs.get_shape(), min_rank=4)
    dconv1 = slim.conv2d(inputs, 64, [3, 3], stride=2, scope='dconv1')
    dconv2 = slim.conv2d(dconv1,  64, [3, 3], stride=1, scope='dconv2')
    dconv3 = slim.conv2d(dconv2, 128, [3, 3], stride=1, scope='dconv3')
    dpool1 = slim.max_pool2d(dconv3, [3, 3], stride=2, scope='dpool1')

  return dpool1


@slim.add_arg_scope
def bottleneck(inputs, depth, depth_bottleneck, stride, rate=1,
               outputs_collections=None, scope=None):

  with tf.variable_scope(scope, 'bottleneck_v1', [inputs]) as sc:
    depth_in = slim.utils.last_dimension(inputs.get_shape(), min_rank=4)
    if depth == depth_in:
      shortcut = pspnet_utils.subsample(inputs, reduce(mul, stride), 'shortcut')
    else:
      shortcut = slim.conv2d(inputs, depth, [1, 1], stride=reduce(mul, stride),
                             activation_fn=None, scope='shortcut')

    residual = slim.conv2d(inputs, depth_bottleneck, [1, 1], stride=stride[0],
                           scope='conv1')
    residual = pspnet_utils.conv2d_same(residual, depth_bottleneck, 3, stride[1],
                                        rate=rate, scope='conv2')
    residual = slim.conv2d(residual, depth, [1, 1], stride=stride[2],
                           activation_fn=None, scope='conv3')

    output = tf.nn.relu(shortcut + residual)

    return slim.utils.collect_named_outputs(outputs_collections,
                                            sc.original_name_scope,
                                            output)

@slim.add_arg_scope
def dbottleneck(inputs, depth, depth_bottleneck, stride, rate=1,
               outputs_collections=None, scope=None):

  with tf.variable_scope(scope, 'dbottleneck_v1', [inputs]) as sc:
    depth_in = slim.utils.last_dimension(inputs.get_shape(), min_rank=4)
    if depth == depth_in:
      shortcut = pspnet_utils.subsample(inputs, reduce(mul, stride), 'dshortcut')
    else:
      shortcut = slim.conv2d(inputs, depth, [1, 1], stride=reduce(mul, stride),
                             activation_fn=None, scope='dshortcut')

    residual = slim.conv2d(inputs, depth_bottleneck, [1, 1], stride=stride[0],
                           scope='dconv1')
    residual = pspnet_utils.conv2d_same(residual, depth_bottleneck, 3, stride[1],
                                        rate=rate, scope='dconv2')
    residual = slim.conv2d(residual, depth, [1, 1], stride=stride[2],
                           activation_fn=None, scope='dconv3')

    output = tf.nn.relu(shortcut + residual)

    return slim.utils.collect_named_outputs(outputs_collections,
                                            sc.original_name_scope,
                                            output)

@slim.add_arg_scope
def pyramid_pooling(inputs, pool_size, depth,
                    outputs_collections=None, scope=None):
  with tf.variable_scope(scope, 'pyramid_pool_v1', [inputs]) as sc:
    dims = inputs.get_shape().dims
    out_height, out_width = dims[1].value, dims[2].value
    pool1 = slim.avg_pool2d(inputs, pool_size, stride=pool_size, scope='pool1')
    conv1 = slim.conv2d(pool1, depth, [1, 1], stride=1, scope='conv1')
    output = tf.image.resize_bilinear(conv1, [out_height, out_width])

    return slim.utils.collect_named_outputs(outputs_collections,
                                            sc.original_name_scope,
                                            output)


def pspnet_v1(inputs,
              depths,
              blocks,
              dblocks,
              levels,
              num_classes=None,
              is_training=True,
              reuse=None,
              scope=None):

  with tf.variable_scope(scope, 'pspnet_v1', [inputs,depths], reuse=reuse) as sc:
    end_points_collection = sc.name + '_end_points'
    with slim.arg_scope([slim.conv2d, bottleneck, dbottleneck, pyramid_pooling,
                         pspnet_utils.stack_blocks_dense,
                         pspnet_utils.pyramid_pooling_module],
                        outputs_collections=end_points_collection):
      with slim.arg_scope([slim.batch_norm], is_training=is_training):
        net = inputs
        net2 = depths
        net = root_block(net)
        net2 = droot_block(net2)

        net = pspnet_utils.stack_blocks_dense(net, blocks, None)
        net2 = pspnet_utils.stack_blocks_dense(net2, dblocks, None)
        net = pspnet_utils.pyramid_pooling_module(net, net2, levels)
        net = slim.conv2d(net, 512, [3, 3], stride=1, scope='fc1')
        net = slim.dropout(net, keep_prob=0.9, is_training=is_training)

        net = slim.conv2d(net, num_classes, [1, 1], activation_fn=None,
                          normalizer_fn=None, scope='logits')

        dims = inputs.get_shape().dims
        out_height, out_width = dims[1].value, dims[2].value
        net = tf.image.resize_bilinear(net, [out_height, out_width])

        # TODO
        end_points = slim.utils.convert_collection_to_dict(end_points_collection)
        end_points['predictions'] = slim.softmax(net, scope='predictions')

        return net, end_points


def pspnet_v1_50(inputs,
                 depth_inputs=None,
                 num_classes=None,
                 is_training=True,
                 reuse=None,
                 scope='pspnet_v1_50'):
  blocks = [
      pspnet_utils.Block(
          'block1', bottleneck, [(256, 64, (1, 1, 1), 1)] * 3),
      pspnet_utils.Block(
          'block2', bottleneck, [(512, 128, (2, 1, 1), 1)] + [(512, 128, (1, 1, 1), 1)] * 3),
      pspnet_utils.Block(
          'block3', bottleneck, [(1024, 256, (1, 1, 1), 2)] * 6),
      pspnet_utils.Block(
          'block4', bottleneck, [(2048, 512, (1, 1, 1), 4)] * 3)
  ]

  dblocks = [
      pspnet_utils.Block(
          'dblock1', dbottleneck, [(256, 64, (1, 1, 1), 1)] * 3),
      pspnet_utils.Block(
          'dblock2', dbottleneck, [(512, 128, (2, 1, 1), 1)] + [(512, 128, (1, 1, 1), 1)] * 3),
      pspnet_utils.Block(
          'dblock3', dbottleneck, [(1024, 256, (1, 1, 1), 2)] * 6),
      pspnet_utils.Block(
          'dblock4', dbottleneck, [(2048, 512, (1, 1, 1), 4)] * 3)
  ]

  levels = [
      pspnet_utils.Level('level1', pyramid_pooling, ((60, 60), 512)),
      pspnet_utils.Level('level2', pyramid_pooling, ((30, 30), 512)),
      pspnet_utils.Level('level3', pyramid_pooling, ((20, 20), 512)),
      pspnet_utils.Level('level4', pyramid_pooling, ((10, 10), 512)),
  ]

  return pspnet_v1(inputs, depth_inputs, blocks, dblocks, levels, num_classes, is_training,
                   reuse=reuse, scope=scope)
