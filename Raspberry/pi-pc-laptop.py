import sys
sys.path.append('/usr/lib/python3/dist-packages')

import time
import cv2
import zmq
from picamera2 import Picamera2

ANALYSIS_IP = ""  

PORT = 5555

context = zmq.Context()
footage_socket = context.socket(zmq.PUB)
footage_socket.setsockopt(zmq.SNDHWM, 1)
footage_socket.connect(f"tcp://{ANALYSIS_IP}:{PORT}")

picam2 = Picamera2()
config = picam2.create_video_configuration(
    main={"size": (1280, 720)},
    controls={"FrameRate": 15},
)
picam2.configure(config)
picam2.start()
time.sleep(1)

print(f"[STREAM] trimite video catre {ANALYSIS_IP}:{PORT}")

try:
    n = 0
    t0 = time.time()
    while True:
        frame = picam2.capture_array("main")
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        ok, buffer = cv2.imencode(".jpg", frame_bgr,
                                  [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            continue

        footage_socket.send(buffer.tobytes())

        n += 1
        if n % 30 == 0:
            fps = 30 / (time.time() - t0)
            t0 = time.time()
            print(f"  ~{fps:.1f} FPS trimis")

except KeyboardInterrupt:
    print("\n[STOP] orpire")
finally:
    picam2.stop()
    picam2.close()
    footage_socket.close()
    context.term()