import cv2
import zmq
import numpy as np

#pc with yolo and llava
ANALYSIS_IP = ""
PORT = 5556

context = zmq.Context()
sock = context.socket(zmq.SUB)
sock.connect(f"tcp://{ANALYSIS_IP}:{PORT}")
sock.setsockopt(zmq.SUBSCRIBE, b"")
sock.setsockopt(zmq.RCVHWM, 100)

print(f"[INFO] Conectat la {ANALYSIS_IP}:{PORT} — aștept stream adnotat...")
print("[INFO] 'q' = ieșire | 'f' = fullscreen")

fullscreen = False

while True:
    try:
        #pstreaza doar ultimul cadru
        raw = None
        while True:
            try:
                raw = sock.recv(zmq.NOBLOCK)
            except zmq.Again:
                break

        if raw is None:
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            continue

        npimg = np.frombuffer(raw, dtype=np.uint8)
        frame = cv2.imdecode(npimg, cv2.IMREAD_COLOR)

        if frame is None:
            continue

        cv2.imshow("Detectie Live", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("f"):
            fullscreen = not fullscreen
            prop = cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL
            cv2.setWindowProperty("Detectie Live",
                                  cv2.WND_PROP_FULLSCREEN, prop)

    except KeyboardInterrupt:
        break

cv2.destroyAllWindows()
sock.close()
context.term()