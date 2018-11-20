# Copyright 2018 Robert Adams
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import io
import sys

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import Image
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Int32MultiArray
from std_msgs.msg import MultiArrayDimension

import imageio

class ROS2_whatlooking_node(Node):

    def __init__(self):
        super().__init__('ros2_whatlooking_node', namespace='raspicam')

        self.set_parameter_defaults( [
            ('image_topic', Parameter.Type.STRING, 'raspicam_compressed'),
            ('image_is_compressed', Parameter.Type.BOOL, True),
            ('bounding_box_topic', Parameter.Type.STRING, 'found_faces'),
            ] )

        self.initialize_display()
        self.initialize_image_subscriber()
        self.initialize_bounding_box_subscriber()

    def destroy_node(self):
        # overlay Node function called when class is being stopped and camera needs closing
        super().destroy_node()

    def initialize_display(self):
        pass

    def initialize_image_subscriber(self):
        if self.get_parameter_value('image_is_compressed'):
            self.image_receiver = self.create_subscription(
                                        CompressedImage,
                                        self.get_parameter_value('image_topic'),
                                        self.receive_image)
        else:
            self.image_receiver = self.create_subscription(
                                        Image,
                                        self.get_parameter_value('image_topic'),
                                        self.receive_image)
    def receive_image(self, msg):
        # Receive an image and store it (self.last_image) for displaying when bounding boxes appear
        img = []
        if self.get_parameter_value('image_is_compressed'):
            # As of 20181016, msg.data is returned as a list of ints.
            # Convert to bytearray so it can be processed.
            converted_data = []
            with CodeTimer(self.get_logger().debug, 'convert to byte array'):
                converted_data = bytearray(msg.data)
            img = self.convert_image(converted_data)
        else:
            img = msg.data

        self.last_image = img

    def convert_image(self, raw_img):
        # Convert the passed buffer into a proper Python image. I.e., use imageio
        #    to do any uncompression, etc.
        # Note that the returned array is a subclass of numpy.array that includes a
        #    '.meta' dictionary which returns 'height' and 'width' of the converted image.
        img = None
        try:
            # imageio.imread returns a numpy array where img[h][w] => [r, g, b]
            with CodeTimer(self.get_logger().debug, 'decompress image'):
                img = imageio.imread(io.BytesIO(raw_img))
                img.meta['width'] = len(img[0])
                img.meta['height'] = len(img)
            self.get_logger().debug('WhatLooking: imread image: h=%s, w=%s' % (len(img), len(img[0])))
        except Exception as e:
            self.get_logger().error('WhatLooking: exception uncompressing image. %s: %s'
                            % (type(e), e.args) )
            img = None
        return img

    def initialize_bounding_box_subscriber(self):
        # Setup subscription for incoming bounding box info
        self.receiver = self.create_subscription(Int32MultiArray,
                        self.get_parameter_value('bounding_box_topic'),
                        self.receive_bounding_box)

    def receive_bounding_box(self, msg):
        if type(msg) != type(None) and hasattr(msg, 'data'):
            self.get_logger().debug('WhatLooking: receive_bbox. dataLen=%s' % (len(msg.data)))
            # Bounding boxes come in a two dimensional array:
            #   Row 0 => ( 0, 0, imageAreaWidth, imageAreaHeight)
            #   Row n => ( bb_right, bb_top, bb_width, bb_height )
            bboxes = AccessInt32MultiArray(msg)
            width = bboxes.get(0, 2)
            widthhalf = width / 2
            height = bboxes.get(0, 3)
            heighthalf = height / 2
            self.get_logger().debug('WhatLooking: process_bounding_boxes. image=%s/%s' % (width, height) )
        else:
            self.get_logger().error('WhatLooking: receive_bbox. no data attribute')

    def get_parameter_or(self, param, default):
        # Helper function to return value of a parameter or a default if not set
        ret = None
        param_desc = self.get_parameter(param)
        if param_desc.type_== Parameter.Type.NOT_SET:
            ret = default
        else:
            ret = param_desc.value
        return ret

    def get_parameter_value(self, param):
        # Helper function to return value of a parameter
        ret = None
        param_desc = self.get_parameter(param)
        if param_desc.type_== Parameter.Type.NOT_SET:
            raise Exception('Fetch of parameter that does not exist: ' + param)
        else:
            ret = param_desc.value
        return ret

    def set_parameter_defaults(self, params):
        # If a parameter has not been set externally, set the value to a default.
        # Passed a list of "(parameterName, parameterType, defaultValue)" tuples.
        parameters_to_set = []
        for (pparam, ptype, pdefault) in params:
            if not self.has_parameter(pparam):
                parameters_to_set.append( Parameter(pparam, ptype, pdefault) )
        if len(parameters_to_set) > 0:
            self.set_parameters(parameters_to_set)

    def has_parameter(self, param):
        # Return 'True' if a parameter by that name is specified
        param_desc = self.get_parameter(param)
        if param_desc.type_== Parameter.Type.NOT_SET:
            return False
        return True

class AccessInt32MultiArray:
    # Wrap a multi-access array with functions for 2D access
    def __init__(self, arr):
        self.arr = arr
        self.columns = self.ma_get_size_from_label('width')
        self.rows = self.ma_get_size_from_label('height')

    def rows(self):
        # return the number of rows in the multi-array
        return self.rows

    def get(self, row, col):
        # return the entry at column 'ww' and row 'hh'
        return self.arr.data[col + ( row * self.columns)]

    def ma_get_size_from_label(self, label):
        # Return dimension size for passed label (usually 'width' or 'height')
        for mad in self.arr.layout.dim:
            if mad.label == label:
                return int(mad.size)
        return 0

class CodeTimer:
    # A little helper class for timing blocks of code
    def __init__(self, logger, name=None):
        self.logger = logger
        self.name = " '"  + name + "'" if name else ''

    def __enter__(self):
        self.start = time.clock()

    def __exit__(self, exc_type, exc_value, traceback):
        self.took = (time.clock() - self.start) * 1000.0
        self.logger('Code block' + self.name + ' took: ' + str(self.took) + ' ms')

def main(args=None):
    rclpy.init(args=args)

    ffNode = ROS2_whatlooking_node()

    try:
        rclpy.spin(ffNode)
    except KeyboardInterrupt:
        ffNode.get_logger().info('WhatLooking: Keyboard interrupt')

    ffNode.destroy_node()

    rclpy.shutdown()


if __name__ == '__main__':
    main()
