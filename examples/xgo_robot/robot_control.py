#!/usr/bin/env python3
#
# Usage
# ~~~~~
# ./robot_control.py ui [topic_path]  # Control robot and display camera input
# ./robot_control.py video_test       # Test for video transmission and display
#
# UI keyboard commands
# - r: Reset robot actuators to initial positions
# - s: Save image to disk as "z_image_??????.jpg"
# - v: Verbose screen detail (toggle state)
# - x: eXit
#
# Refactor
# ~~~~~~~~
# - ServiceDiscovery / ActorDiscovery (pipeline.py, transport/)
# - Combine _image_to_bgr() and _image_to_rgb() --> _image_convert()
# - Move to "aiko_services/video/" (or "media/") ...
#  - _camera*() and _screen*() functions
#  - _image_convert(), _image_resize()
# - Generalize daggy video (and audio) compression / transmission over MQTT
# - Generalize image overlay
# - Resource monitoring: CPU, memory, network, etc
#
# To Do
# ~~~~~
# - Discover "xgo_robot" Actor and use "topic_path/video" instead
#   - When absent, display a video image that shows "robot not found"
#
# - Keyboard commands: Display "help" on screen, key='?' ...
#   - Reset (R)
#   - Terminate (T) and Halt/Shutdown (H)
#   - Action, e.g sit
#   - Arm mode ... and arm and claw position
#   - Pitch, roll, yaw: keyboard arrows and display value
#   - Translate: x, y, z: keyboard arrows and display value
#   - Move forward, back, left, right, turn
#   - Motor speed and display value
#   - Pick-up and put-down ball
#
# - Payload includes frame id and other status, e.g battery level, motor speed
#
# - Send text to display on video screen
# - Send video to the LCD screen (overlay with local status)
# - Send audio sample (MP3 ?) to speaker
# - Disable / enable microphone audio transmission

from abc import abstractmethod
import click
import cv2
from io import BytesIO
import numpy as np
from threading import Thread
import time
import zlib

from aiko_services import *

ACTOR_TYPE_UI = "robot_control"
PROTOCOL_UI = f"{ServiceProtocol.AIKO}/{ACTOR_TYPE_UI}:0"
ACTOR_TYPE_VIDEO_TEST = "video_test"
PROTOCOL_VIDEO_TEST = f"{ServiceProtocol.AIKO}/{ACTOR_TYPE_VIDEO_TEST}:0"
TOPIC_VIDEO = "aiko/video"

_LOGGER = aiko.logger(__name__)
_VERSION = 0

# --------------------------------------------------------------------------- #

class RobotControl(Actor):
    Interface.implementations["RobotControl"] = "__main__.RobotControlImpl"

    @abstractmethod
    def image(self, aiko, topic, payload_in):
        pass

class RobotControlImpl(RobotControl):
    def __init__(self,
        implementations, name, protocol, tags, transport,
        robot_topic):

        implementations["Actor"].__init__(self,
            implementations, name, protocol, tags, transport)

        self.state["frame_id"] = 0
        self.state["robot_topic"] = robot_topic
        self.state["source_file"] = f"v{_VERSION}⇒{__file__}"
        self.state["topic_video"] = TOPIC_VIDEO

        self.add_message_handler(self.image, TOPIC_VIDEO, binary=True)

    def get_logger(self):
        return _LOGGER

    def image(self, aiko, topic, payload_in):
        frame_id = self.state["frame_id"]
        self.ec_producer.update("frame_id", frame_id + 1)

        payload_in = zlib.decompress(payload_in)
        payload_in = BytesIO(payload_in)
        image = np.load(payload_in, allow_pickle=True)

        image = self._image_to_bgr(image)
        cv2.imshow("xgo_robot", self._image_resize(image))
        key = cv2.waitKey(1) & 0xff
        if key == ord("r"):
            payload_out = "(reset)"
            aiko.message.publish(
                f"{self.state['robot_topic']}/in", payload_out)
            payload_out = "(claw 128)"
            aiko.message.publish(
                f"{self.state['robot_topic']}/in", payload_out)
        if key == ord("s"):
            cv2.imwrite(f"z_image_{frame_id:06d}.jpg", image)
        if key == ord("v"):
            payload_out = "(screen_detail)"  # toggle state
            aiko.message.publish(
                f"{self.state['robot_topic']}/in", payload_out)
        if key == ord("x"):
            cv2.destroyAllWindows()
            raise SystemExit()

    def _image_to_bgr(self, image):
        r, g, b = cv2.split(image)
        image = cv2.merge((b, g, r))
        return image

    def _image_resize(self, image, scale=2):
        width = int(image.shape[1] * scale)
        height = int(image.shape[0] * scale)
        dimensions = (width, height)
        image = cv2.resize(image, dimensions, interpolation = cv2.INTER_AREA)
        return image

# --------------------------------------------------------------------------- #

SLEEP_PERIOD = 0.2     # seconds
STATUS_XY = (10, 230)  # (10, 15)

class VideoTest(Actor):
    Interface.implementations["VideoTest"] = "__main__.VideoTestImpl"

class VideoTestImpl(VideoTest):
    def __init__(self, implementations, name, protocol, tags, transport):
        implementations["Actor"].__init__(self,
            implementations, name, protocol, tags, transport)

        self.state["sleep_period"] = SLEEP_PERIOD
        self.state["source_file"] = f"v{_VERSION}⇒{__file__}"
        self.state["topic_video"] = TOPIC_VIDEO

        self._camera = self._camera_initialize()
        self._thread = Thread(target=self._run).start()

    def get_logger(self):
        return _LOGGER

    def _camera_initialize(self):
        camera = cv2.VideoCapture(0)
        camera.set(3, 320)
        camera.set(4, 240)
        return camera

    def _image_to_rgb(self, image):
        b, g, r = cv2.split(image)
        image = cv2.merge((r, g, b))
        return image

    def _publish_image(self, image):
        payload_out = BytesIO()
        np.save(payload_out, image, allow_pickle=True)
        payload_out = zlib.compress(payload_out.getvalue())
        aiko.message.publish(self.state["topic_video"], payload_out)

    def _run(self):
        fps = 0
        while True:
            time_loop = time.time()
            status, image = self._camera.read()
            image = self._image_to_rgb(image)
            time_process = (time.time() - time_loop) * 1000

            status = f"{time_process:.01f} ms  {fps} FPS"
            cv2.putText(image, status, STATUS_XY, 0, 0.7, (255, 255, 255), 2)
            self._publish_image(image)

            self._sleep()
            fps = int(1 / (time.time() - time_loop))

    def _sleep(self, period=None):
        if not period:
            try:
                period = float(self.state["sleep_period"])
            except:
                period = SLEEP_PERIOD
        time.sleep(period)

# --------------------------------------------------------------------------- #

@click.group()
def main():
    pass

@main.command(help="Robot Control user interface")
@click.argument("robot_topic", default=None, required=False)
def ui(robot_topic):
    init_args = actor_args(ACTOR_TYPE_UI, PROTOCOL_UI)
    init_args["robot_topic"] = robot_topic
    robot_control = compose_instance(RobotControlImpl, init_args)
    aiko.process.run()

@main.command(name="video_test", help="Video test output")
def video_test():
    init_args = actor_args(ACTOR_TYPE_VIDEO_TEST, PROTOCOL_VIDEO_TEST)
    video_test = compose_instance(VideoTestImpl, init_args)
    aiko.process.run()

if __name__ == "__main__":
    main()

# --------------------------------------------------------------------------- #