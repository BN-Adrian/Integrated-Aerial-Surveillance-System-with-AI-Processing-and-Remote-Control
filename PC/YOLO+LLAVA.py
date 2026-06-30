import cv2
import zmq
import numpy as np
import threading
import time
import requests
import base64
from ultralytics import YOLO
import torch

PI_PORT         = 5555
LAPTOP_PORT     = 5556
YOLO_MODEL      = "yolov8n.pt"
CONFIDENCE      = 0.4
TARGET_FPS      = 15
FRAME_INTERVAL  = 1.0 / TARGET_FPS



OLLAMA_URL      = ""
LLAVA_MODEL = "llava-phi3"
OLLAMA_TIMEOUT  = 30

llava_semaphore = threading.Semaphore(1)

LAPTOP_W = 854
LAPTOP_H = 480

DETAIL_CLASSES = {"car", "bus", "motorcycle","person"}

CLASS_COLORS = {
    "person":       (0, 255, 0),
    "car":          (0, 0, 255),
    "bus":          (0, 60, 200),
    "bicycle":      (255, 200, 0),
    "motorcycle":   (255, 150, 0),
    "dog":          (180, 0, 255),
    "cat":          (220, 0, 200),
    "keyboard":     (0, 255, 255),
    "tv":           (255, 0, 255),
    "laptop":       (255, 0, 200),
    "mouse":        (255, 255, 0),
    "chair":        (128, 255, 0),
    "couch":        (100, 200, 0),
    "dining table": (0, 128, 255),
    "cell phone":   (255, 128, 0),
    "default":      (0, 200, 255),
}

#state
latest_detections: list = []
detections_lock = threading.Lock()

pending_frame: np.ndarray | None = None
pending_lock = threading.Lock()

detection_requested = threading.Event()

#cache detalii vehicule
car_details_cache: dict = {}
car_cache_lock = threading.Lock()

# evita duplicate
processing_keys: set = set()
processing_lock = threading.Lock()
#incarcare yolo
print(f"[INFO] incarc yolo: {YOLO_MODEL} ...")
yolo = YOLO(YOLO_MODEL)
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[INFO] yolo pe: {device.upper()}")


def recv_latest(socket) -> bytes | None:
    raw = None
    count = 0
    while True:
        try:
            raw = socket.recv(zmq.NOBLOCK)
            count += 1
        except zmq.Again:
            break
    if count > 5:
        print(f"[DRAIN] Aruncat {count-1} cadre vechi")
    return raw


def crop_to_b64(crop: np.ndarray) -> str:
    h, w = crop.shape[:2]
    max_side = 320
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        crop = cv2.resize(crop, (new_w, new_h))
    
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("conversie failed")
    return base64.b64encode(buf.tobytes()).decode()


def get_cache_key(x1: int, y1: int, x2: int, y2: int) -> tuple:
    return (x1 // 50, y1 // 50, x2 // 50, y2 // 50)


def llava_worker(cache_key: tuple, label: str, crop: np.ndarray):
    try:
        print(f"[DEBUG] Trimit la LLaVA: {label}")
        b64 = crop_to_b64(crop)

        if label == "car":
            prompt = "What is the brand and model of this car? Reply in max 5 words, only brand and model."
        elif label == "motorcycle":
            prompt = "What brand is this motorcycle? Reply in max 5 words."
        elif label == "person":
            prompt = "Is this person man or female? Reply with only one word: Man or Female."
        else:
            prompt = f"Describe this {label} briefly in max 5 words."

        payload = {
            "model": LLAVA_MODEL,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0, "num_predict": 20},
        }

        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        details = resp.json()["response"].strip()

        details = details.replace("\n", " ").strip(".")
        if len(details) > 30:
            details = details[:30] + "..."

        print(f"[LLAVA] {label} → {details}")

        with car_cache_lock:
            car_details_cache[cache_key] = (details, time.time())

    except Exception as e:
        print(f"[WARN] LLaVA eroare: {e}")
        with car_cache_lock:
            car_details_cache[cache_key] = ("", time.time())

    finally:
        with processing_lock:
            processing_keys.discard(cache_key)

def detection_worker():
    global latest_detections

    while True:
        detection_requested.wait()
        detection_requested.clear()

        with pending_lock:
            frame = pending_frame.copy() if pending_frame is not None else None

        if frame is None:
            continue

        t_start = time.time()
        h, w = frame.shape[:2]

        results = yolo(frame, device=device, verbose=False, conf=CONFIDENCE)[0]

        detections = []

        for box in results.boxes:
            cls_id = int(box.cls[0])
            label  = yolo.names[cls_id]
            conf   = float(box.conf[0])
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]

            norm_box = [x1/w, y1/h, x2/w, y2/h]

            details = ""
            if label in DETAIL_CLASSES:
                cache_key = get_cache_key(x1, y1, x2, y2)

                with car_cache_lock:
                    cached = car_details_cache.get(cache_key)
                    if cached:
                        cached_details, cached_time = cached
                        if time.time() - cached_time < 6.0:
                            details = cached_details
                        else:
                            del car_details_cache[cache_key]
                            details = ""

                if not details:
                    with processing_lock:
                        already_processing = cache_key in processing_keys

                    if not already_processing:
                        pad = 10
                        cx1 = max(0, x1 - pad)
                        cy1 = max(0, y1 - pad)
                        cx2 = min(w, x2 + pad)
                        cy2 = min(h, y2 + pad)
                        crop = frame[cy1:cy2, cx1:cx2].copy()

                        if crop.size > 0:
                            with processing_lock:
                                processing_keys.add(cache_key)

                            t = threading.Thread(
                                target=llava_worker,
                                args=(cache_key, label, crop),
                                daemon=True,
                            )
                            t.start()

            detections.append({
                "label":   label,
                "conf":    conf,
                "box":     norm_box,
                "details": details,
            })

        with detections_lock:
            latest_detections = detections

        elapsed = time.time() - t_start
        labels = [d["label"] for d in detections]
        print(f"[YOLO] {len(detections)} obiecte în {elapsed*1000:.0f}ms → {labels}")

def draw_detections(frame: np.ndarray, detections: list[dict]) -> np.ndarray:
    h, w = frame.shape[:2]
    out = frame.copy()

    for det in detections:
        label   = det.get("label", "?")
        conf    = det.get("conf", 0)
        box     = det.get("box", [])
        details = det.get("details", "")

        if len(box) != 4:
            continue

        x1 = int(box[0] * w)
        y1 = int(box[1] * h)
        x2 = int(box[2] * w)
        y2 = int(box[3] * h)

        x1, x2 = max(0, x1), min(w - 1, x2)
        y1, y2 = max(0, y1), min(h - 1, y2)

        color = CLASS_COLORS.get(label.lower(), CLASS_COLORS["default"])

        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

        font = cv2.FONT_HERSHEY_SIMPLEX

        #linia 1: label + confidence
        line1 = f"{label} {conf:.0%}"
        fs1 = 0.8
        (tw1, th1), bl1 = cv2.getTextSize(line1, font, fs1, 2)

        #linia 2: detalii vehicul
        line2 = details
        fs2 = 0.65
        tw2, th2 = 0, 0
        if line2:
            (tw2, th2), _ = cv2.getTextSize(line2, font, fs2, 1)

        #background
        bg_w = max(tw1, tw2) + 8
        bg_h = th1 + (th2 + 4 if line2 else 0) + 8
        cv2.rectangle(out,
                      (x1, y1 - bg_h),
                      (x1 + bg_w, y1),
                      color, cv2.FILLED)

        #scrie linia 1
        y_line1 = y1 - (th2 + 6 if line2 else 4)
        cv2.putText(out, line1, (x1 + 3, y_line1),
                    font, fs1, (255,255,255), 3, cv2.LINE_AA)

        #scrie linia 2
        if line2:
            y_line2 = y1 - 3
            cv2.putText(out, line2, (x1 + 3, y_line2),
                        font, fs2, (255,255,255), 2, cv2.LINE_AA)

    #contor
    cv2.putText(out, f"Obiecte: {len(detections)}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2, cv2.LINE_AA)

    return out

def warmup_llava():
    try:
        print("[INFO] Warm-up")
        dummy = np.ones((100, 100, 3), dtype=np.uint8) * 128
        ok, buf = cv2.imencode(".jpg", dummy)
        b64 = base64.b64encode(buf.tobytes()).decode()
        
        requests.post(OLLAMA_URL, json={
            "model": LLAVA_MODEL,
            "prompt": "Hi",
            "images": [b64],
            "stream": False,
            "options": {"num_predict": 5}
        }, timeout=60)
        print("[INFO] LLaVA gata!")
    except Exception as e:
        print(f"[WARN] Warm-up esuat: {e}")


#main
def main():
    global pending_frame
    warmup_llava()
    ctx = zmq.Context()

    sub = ctx.socket(zmq.SUB)
    sub.bind(f"tcp://*:{PI_PORT}")
    sub.setsockopt(zmq.SUBSCRIBE, b"")
    sub.setsockopt(zmq.RCVHWM, 100)

    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://*:{LAPTOP_PORT}")
    pub.setsockopt(zmq.SNDHWM, 1)

    t = threading.Thread(target=detection_worker, daemon=True)
    t.start()

    print(f"[INFO] Ascult Pi pe :{PI_PORT} | Trimit laptop pe :{LAPTOP_PORT}")
    print(f"[INFO] YOLO + LLaVA async pentru: {DETAIL_CLASSES}")
    print(f"[INFO] Target: {TARGET_FPS}fps | rezoluție laptop: {LAPTOP_W}x{LAPTOP_H}")

    last_send_time = 0
    fps_counter    = 0
    fps_timer      = time.time()

    while True:
        try:
            raw = recv_latest(sub)

            if raw is None:
                time.sleep(0.005)
                continue

            now = time.time()

            npimg = np.frombuffer(raw, dtype=np.uint8)
            frame = cv2.imdecode(npimg, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            with pending_lock:
                pending_frame = frame.copy()
            detection_requested.set()

            if now - last_send_time < FRAME_INTERVAL:
                continue

            with detections_lock:
                dets = list(latest_detections)

            annotated = draw_detections(frame, dets)

            annotated_small = cv2.resize(annotated, (LAPTOP_W, LAPTOP_H))
            ok, buf = cv2.imencode(".jpg", annotated_small,
                                   [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                pub.send(buf.tobytes())
                last_send_time = now
                fps_counter += 1

            if now - fps_timer >= 5.0:
                fps_real = fps_counter / (now - fps_timer)
                print(f"[FPS] Trimis la laptop: {fps_real:.1f} fps")
                fps_counter = 0
                fps_timer = now

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[ERR] Main loop: {e}")
            continue

    sub.close()
    pub.close()
    ctx.term()
    print("[STOP] Analysis server oprit.")


if __name__ == "__main__":
    main()