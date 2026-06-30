import json
import time
import threading
import zmq
from pymavlink import mavutil
import sys


ZMQ_PORT = 5556
MAVLINK_CONN = "/dev/ttyAMA0"
BAUD = 57600

JOYSTICK_TIMEOUT = 0.5
RC_RATE_HZ = 50
HEARTBEAT_HZ = 1


# joystick
AXIS_ROLL      = 0
AXIS_PITCH     = 1
AXIS_YAW       = 2
AXIS_THROTTLE  = 3

PITCH_SPAN = 100
ROLL_SPAN  = 100
YAW_SPAN   = 300
AXIS_BTN_R2 =5
AXIS_BTN_L2 =4


# butoane
#jos
BTN_A      = 0
#rotatie dreapta
BTN_B      = 1
#rotatie stanga
BTN_X      = 2
#sus
BTN_Y      = 3
BTN_L1     = 4
BTN_R1     = 5
BTN_BACK   = 6
BTN_START  = 7



BTN_ARM     = BTN_START
BTN_DISARM  = BTN_BACK
#sus
BTN_UP      = BTN_Y
#jos
BTN_DOWN    = BTN_A
#dreapta
BTN_R_RIGHT = BTN_B
#stanga
BTN_R_LEFT  = BTN_X


BTN_STAB    = BTN_R1
BTN_LOITER  = BTN_L1
BTN_ALTHOLD = AXIS_BTN_R2
BTN_AUTOTUNE =AXIS_BTN_L2
#BTN_RTL     = BTN_LB
#BTN_LAND    = BTN_RB


RC_MIN = 1000
RC_MID = 1500
RC_MAX = 1900
THROTTLE_MIN_PWM = 1000
THROTTLE_MAX_PWM = 2000

#roatie stanga<->dreapta
yaw_pwm_target=RC_MID
yaw_pressed_left=False
yaw_pressed_right=False
YAW_RATE=150
YAW_RAMP_STEP=20

#sus<->jos
throttle_pwm_target = THROTTLE_MIN_PWM   
throttle_pressed_up = False
throttle_pressed_down = False
THROTTLE_STEP = 2
THROTTLE_HOVER = 1500  


state = {"roll": 0.0, "pitch": 0.0, "throttle": -1.0, "yaw": 0.0}
last_msg_time = time.time()
armed = False
rc_override_active = False
lock = threading.Lock()


print(f"[MAVLINK] conectare {MAVLINK_CONN} @ {BAUD}...")
while True:
    try:
        master = mavutil.mavlink_connection(MAVLINK_CONN, baud=BAUD)
        heartbeat = master.wait_heartbeat(timeout=10)
        if heartbeat is not None:
            break
        print("[MAVLINK] Nu raspunde inca, reîncerc...")
        time.sleep(2)
    except Exception as e:
        print(f"[MAVLINK] Eroare: {e}, reîncerc...")
        time.sleep(2)

print(f"[MAVLINK] OK -- system {master.target_system}, comp {master.target_component}")

#zmq
ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.bind(f"tcp://*:{ZMQ_PORT}")
sock.setsockopt_string(zmq.SUBSCRIBE, "")
sock.setsockopt(zmq.RCVHWM, 1)
sock.setsockopt(zmq.CONFLATE, 1)
print(f"[ZMQ] ascult joystick pe portul {ZMQ_PORT}")



def axis_to_pwm(value, span):
    #-1=1100, 0=1500, 1=1900
    pwm = int(RC_MID + value * span)
    return max(RC_MIN, min(RC_MAX, pwm))


def throttle_to_pwm(value):
    
    norm = (value + 1) / 2
    pwm = int(THROTTLE_MIN_PWM + norm * (RC_MAX - THROTTLE_MIN_PWM))
    return max(THROTTLE_MIN_PWM, min(RC_MAX, pwm))


def send_rc():
    global throttle_pwm_target
    global yaw_pwm_target

    if not rc_override_active:
        return

    # modifica throttle dupa butoane
    if throttle_pressed_up:
        throttle_pwm_target = min(RC_MAX, throttle_pwm_target + THROTTLE_STEP)
    elif throttle_pressed_down:
        throttle_pwm_target = max(THROTTLE_MIN_PWM, throttle_pwm_target - THROTTLE_STEP)

    #yay
    #if yaw_pressed_left:
    #    yaw_pwm_target=RC_MID-YAW_RATE
    #elif yaw_pressed_right:
    #    yaw_pwm_target=RC_MID+YAW_RATE
    if yaw_pressed_left:
        target = RC_MID - YAW_RATE
        yaw_pwm_target = max(target, yaw_pwm_target - YAW_RAMP_STEP)
    elif yaw_pressed_right:
        target = RC_MID + YAW_RATE
        yaw_pwm_target = min(target, yaw_pwm_target + YAW_RAMP_STEP)
    else:
        # revenire lentă la centru când butonul e eliberat
        if yaw_pwm_target > RC_MID:
            yaw_pwm_target = max(RC_MID, yaw_pwm_target - YAW_RAMP_STEP)
        elif yaw_pwm_target < RC_MID:
            yaw_pwm_target = min(RC_MID, yaw_pwm_target + YAW_RAMP_STEP)
    with lock:
        roll_pwm  = axis_to_pwm(state["roll"], ROLL_SPAN)
        #
        pitch_pwm = axis_to_pwm(state["pitch"], PITCH_SPAN)
        yaw_pwm   = axis_to_pwm(state["yaw"], YAW_SPAN)

    master.mav.rc_channels_override_send(
        master.target_system, master.target_component,
        roll_pwm,
        pitch_pwm,
        throttle_pwm_target,    
        yaw_pwm_target,
        0, 0, 0, 0,
    )

def release_rc():
    master.mav.rc_channels_override_send(
        master.target_system, master.target_component,
        0, 0, 0, 0, 0, 0, 0, 0,
    )


def set_mode(name):
    print(f"[MODE] -> {name}")
    try:
        master.set_mode_apm(name)
    except Exception as e:
        print(f"[MODE ERROR] {e}")


def arm():
    global armed, rc_override_active
    global throttle_pwm_target
    print("[ARM] STABILIZE + arming")
    master.set_mode_apm("STABILIZE")
    time.sleep(0.5)
    master.arducopter_arm()
    
    start = time.time()
    while time.time() - start < 5.0:
        msg = master.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
        if msg and (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
            armed = True
            rc_override_active = True
            throttle_pwm_target = 1150
            print("[ARM] ARMED")
            return
    
    # chiar daca timeout, seteaza armed=True pentru ca pixhawk s-a armat
    print("[ARM] Timeout confirmare, dar continui oricum")
    armed = True
    rc_override_active = True


def disarm():
    global armed
    global rc_override_active
    global throttle_pwm_target
    global throttle_pressed_up
    global throttle_pressed_down
    global yaw_pwm_target
    global yaw_pressed_right
    global yaw_pressed_left

    print("[DISARM]")

    with lock:
        state.update(roll=0.0, pitch=0.0, yaw=0.0, throttle=-1.0)

    rc_override_active = False
    release_rc()

    for _ in range(4):
        master.mav.command_long_send(
            master.target_system, master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0, 21196,
            0, 0, 0, 0, 0,
        )
        time.sleep(0.05)

    armed = False
    throttle_pwm_target=THROTTLE_MIN_PWM
    throttle_pressed_up=False
    throttle_pressed_down=False
    yaw_pwm_target=RC_MID
    yaw_pressed_left=False
    yaw_pressed_right=False
    print("[DISARM] OK")


def panic_rtl():
    print("[PANIC] RTL")
    set_mode("RTL")


def panic_land():
    print("[PANIC] LAND")
    set_mode("LAND")


last_r2_mode_switch = 0
last_l2_mode_switch=0
def handle_msg(msg):
    global last_msg_time 
    global throttle_pressed_up
    global throttle_pressed_down
    global yaw_pressed_left
    global yaw_pressed_right
    global last_r2_mode_switch
    global last_l2_mode_switch
    global throttle_pwm_target
    last_msg_time = time.time()

    if msg["type"] == "axis":
        v = msg["value"]
        aid = msg["id"]

        if aid == AXIS_BTN_R2 and v > 0.5:
            now = time.time()
            if now - last_r2_mode_switch > 2.0:
                last_r2_mode_switch = now
                throttle_pwm_target = RC_MID
                set_mode("ALT_HOLD")
            return
        if aid == AXIS_BTN_L2 and v>0.5:
            now =time.time()
            if now-last_l2_mode_switch >2.0:
                last_l2_mode_switch=now
                set_mode("AUTOTUNE")
            return 

        with lock:
            if   aid == AXIS_ROLL:     state["roll"]     = v
            elif aid == AXIS_PITCH:    state["pitch"]    = v
            elif aid == AXIS_THROTTLE: state["throttle"] = v
            elif aid == AXIS_YAW:      state["yaw"]      = v
        return

    if msg["type"]=="button":
        bid=msg["id"]
        pressed=msg["pressed"]
        
        #throttle
        if bid ==BTN_UP:
            throttle_pressed_up=pressed
            print(f"[THROTTLE UP] {throttle_pwm_target}")
            return 
        if bid==BTN_DOWN:
            throttle_pressed_down=pressed
            print(f"[THROTTLE DOWN] {throttle_pwm_target}")
            return
        
        #yaw
        if bid==BTN_R_LEFT:
            yaw_pressed_left=pressed
            return
        
        if bid==BTN_R_RIGHT:
            yaw_pressed_right=pressed
            return

        #if bid==BTN_R_LEFT:
        #    yaw_pressed_left=pressed
        #    if not pressed:
        #        yaw_pwm_target=RC_MID
        #    return
        
        #if bid==BTN_R_RIGHT:
        #    yaw_pressed_right=pressed
        #    if not pressed:
        #        yaw_pwm_target=RC_MID
        #    return
        
        if not pressed:
            return

        if   bid == BTN_ARM:     arm()
        elif bid == BTN_DISARM:  disarm()
        elif bid == BTN_STAB:    set_mode("STABILIZE")
        elif bid == BTN_LOITER:  set_mode("LOITER")
        #elif bid == AXIS_BTN_R2:    set_mode("ALT_HOLD")
            #elif bid == BTN_ALTHOLD: set_mode("ALT_HOLD")
            #elif bid == BTN_RTL:     panic_rtl()
            #elif bid == BTN_LAND:    panic_land()


#threads
def heartbeat_loop():
    while True:
        try:
            master.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0, 0, 0,
            )
        except Exception as e:
            print(f"[HB ERROR] {e}")
        time.sleep(1.0 / HEARTBEAT_HZ)


def telemetry_loop():
    last_print = 0
    while True:
        try:
            msg = master.recv_match(blocking=False)
            if msg is None:
                time.sleep(0.05)
                continue

            t = msg.get_type()

            if t == "COMMAND_ACK":
                results = {0: "OK", 1: "TEMP_REJECTED", 2: "DENIED",
                           3: "UNSUPPORTED", 4: "FAILED"}
                print(f"[ACK cmd={msg.command}] {results.get(msg.result, msg.result)}")
                continue

            now = time.time()
            if now - last_print < 2.0:
                continue

            if t == "HEARTBEAT":
                mode = mavutil.mode_string_v10(msg)
                arm_status = "ARMED" if (msg.base_mode & 128) else "DISARMED"
                print(f"[TLM] {arm_status} | mod: {mode}")
                last_print = now
            elif t == "SYS_STATUS":
                volt = msg.voltage_battery / 1000.0
                pct  = msg.battery_remaining
                print(f"[TLM] baterie: {volt:.2f}V ({pct}%)")
                last_print = now
        except Exception:
            time.sleep(0.1)


# main

threading.Thread(target=heartbeat_loop, daemon=True).start()
threading.Thread(target=telemetry_loop, daemon=True).start()

print("\n========================================")
print(" CONTROL DRONA — JOYSTICK PRIN MOONLIGHT")
print("========================================")
print(f"A      -> Down")
print(f"Y      -> Up")
print(f"B      -> rotate right")
print(f"X      -> rotate left")
print("========================================\n")
print("[RUN] Astept joystick. Ctrl+C pentru stop.\n")

PERIOD = 1.0 / RC_RATE_HZ

try:
    while True:
        t0 = time.time()

        while True:
            try:
                raw = sock.recv_string(zmq.NOBLOCK)
                handle_msg(json.loads(raw))
            except zmq.Again:
                break
            except Exception as e:
                print(f"[ZMQ ERROR] {e}")
                break

        #if time.time() - last_msg_time > JOYSTICK_TIMEOUT:
        #    with lock:
        #        state.update(roll=0.0, pitch=0.0, yaw=0.0, throttle=-1.0)
        if time.time() - last_msg_time > JOYSTICK_TIMEOUT:
            with lock:
                state.update(roll=0.0, pitch=0.0, yaw=0.0, throttle=-1.0)
                yaw_pressed_left = False
                yaw_pressed_right = False
    # yaw_pwm_target revine singur prin rampă
        send_rc()

        dt = time.time() - t0
        if dt < PERIOD:
            time.sleep(PERIOD - dt)

except KeyboardInterrupt:
    print("\n\n[STOP] Cleanup...")
    try:
        if armed:
            disarm()
        release_rc()
    except Exception as e:
        print(f"[CLEANUP ERROR] {e}")
finally:
    sock.close()
    ctx.term()
    print("[BYE]")
