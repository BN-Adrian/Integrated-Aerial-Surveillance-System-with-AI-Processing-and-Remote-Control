import json
import sys
import pygame
import zmq

#tailscale rasp berry
PI_TAILSCALE_IP = ""
PORT = 5556

DEADZONE = 0.15

#zmq
context = zmq.Context()
sock = context.socket(zmq.PUB)
sock.setsockopt(zmq.SNDHWM, 1)
sock.connect(f"tcp://{PI_TAILSCALE_IP}:{PORT}")

#oystick
pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    print("joystick nedetectat")
    sys.exit()

joy = pygame.joystick.Joystick(0)
joy.init()
print(f"[OK] Joystick: {joy.get_name()}")
print(f"[STREAM] Trimit comenzi de la laptop (100.117.75.126) la Pi ({PI_TAILSCALE_IP}:{PORT})")
print("Ctrl+C pentru oprire.\n")

clock = pygame.time.Clock()

def send(msg: dict):
    sock.send_string(json.dumps(msg))

try:
    while True:
        for event in pygame.event.get():
            if event.type == pygame.JOYAXISMOTION:
                value = event.value if abs(event.value) > DEADZONE else 0.0
                send({"type": "axis", "id": event.axis, "value": round(value, 3)})

            elif event.type == pygame.JOYBUTTONDOWN:
                send({"type": "button", "id": event.button, "pressed": True})

            elif event.type == pygame.JOYBUTTONUP:
                send({"type": "button", "id": event.button, "pressed": False})

            elif event.type == pygame.JOYHATMOTION:
                send({"type": "hat", "id": event.hat, "value": list(event.value)})

        clock.tick(120)

except KeyboardInterrupt:
    print("\n[STOP] Se opresc")
finally:
    sock.close()
    context.term()
    pygame.quit()