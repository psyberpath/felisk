"""
Felisk — Pico W Firmware (felisk.py)
Dual-mode smart cat portal controller.

DOMESTIC mode (default): Gate normally LOCKED (0°). Opens on command.
TNR mode: Gate normally OPEN (90°). Locks on command for capture.

Exposes HTTP API on port 80 for commands from the Temporal workflow.
Reads HC-SR04 proximity + MFRC522 RFID locally and reports to the workflow
via the vision node's listener.
"""

import mfrc522
from machine import Pin, PWM
import network
import socket
import utime

# ---------------- Wi-Fi Config ----------------
WIFI_SSID = "Galaxy S21 FE 5G"
WIFI_PASS = "bevbevbev"

# ---------------- Vision Node (Laptop) Config ----------------
LAPTOP_IP = "10.143.184.1"  # Update to your laptop's IP on the same network
LAPTOP_PORT = 5001          # Vision node listener port

# ---------------- Hardware Pins ----------------
trig = Pin(2, Pin.OUT)
echo = Pin(3, Pin.IN)

servo = PWM(Pin(15))
servo.freq(50)

green_led = Pin(14, Pin.OUT)
red_led = Pin(13, Pin.OUT)
buzzer = Pin(12, Pin.OUT)

# ---------------- State Variables ----------------
portal_mode = "DOMESTIC"  # "DOMESTIC" or "TNR"
portal_status = "Secure"
last_scanned_tag = "None"
current_distance = 100.0
authorized_felines = ["146_73_250_5"]

# Initialize MFRC522 RFID Reader (SPI0)
rfid = mfrc522.MFRC522(sck=18, mosi=19, miso=16, rst=20, cs=17)


# ---------------- Hardware Helpers ----------------
def set_gate_angle(angle):
    """Set servo to angle (0=closed, 90=open). PWM duty mapped for SG90."""
    min_duty = 1638   # 0.5ms pulse → 0°
    max_duty = 8192   # 2.5ms pulse → 180°
    duty = int(min_duty + (angle / 180) * (max_duty - min_duty))
    servo.duty_u16(duty)


def get_resting_angle():
    """Return the default gate position based on current mode."""
    return 0 if portal_mode == "DOMESTIC" else 90


def chirp(success=True):
    """Audible feedback via active buzzer."""
    if success:
        buzzer.on()
        utime.sleep_ms(80)
        buzzer.off()
    else:
        for _ in range(3):
            buzzer.on()
            utime.sleep_ms(60)
            buzzer.off()
            utime.sleep_ms(40)


def measure_distance():
    """HC-SR04 ultrasonic distance measurement (non-blocking timeout)."""
    trig.low()
    utime.sleep_us(2)
    trig.high()
    utime.sleep_us(10)
    trig.low()

    timeout_us = 20000
    start = utime.ticks_us()

    while echo.value() == 0:
        if utime.ticks_diff(utime.ticks_us(), start) > timeout_us:
            return 100.0
    pulse_start = utime.ticks_us()

    while echo.value() == 1:
        if utime.ticks_diff(utime.ticks_us(), pulse_start) > timeout_us:
            return 100.0
    pulse_end = utime.ticks_us()

    duration = utime.ticks_diff(pulse_end, pulse_start)
    return (duration * 0.0343) / 2


def set_mode_leds():
    """Update LED state to reflect current mode's resting position."""
    if portal_mode == "DOMESTIC":
        red_led.on()
        green_led.off()
    else:
        red_led.off()
        green_led.on()


def notify_laptop(message):
    """Send a message to the vision node's TCP listener (non-blocking best-effort)."""
    try:
        cs = socket.socket()
        cs.settimeout(1.0)
        cs.connect((LAPTOP_IP, LAPTOP_PORT))
        cs.send(message.encode('utf-8'))
        cs.recv(64)  # Wait for ACK
        cs.close()
    except:
        pass  # Best-effort — don't block main loop if laptop is unreachable



# ---------------- Connect Wi-Fi ----------------
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

if not wlan.isconnected():
    print("Connecting to Wi-Fi...")
    wlan.connect(WIFI_SSID, WIFI_PASS)
    while not wlan.isconnected():
        utime.sleep_ms(500)

pico_ip = wlan.ifconfig()[0]
print(f"Network Connected! Felisk Portal live at: http://{pico_ip}/")

# ---------------- HTTP API Socket (Port 80) ----------------
s = socket.socket()
s.bind(("0.0.0.0", 80))
s.listen(2)
s.setblocking(False)

# Set initial state (DOMESTIC = locked at 0°)
set_gate_angle(get_resting_angle())
set_mode_leds()
buzzer.off()

last_uid = ""
target_in_corridor = False

# ---------------- Main Loop ----------------
while True:
    current_distance = measure_distance()

    # 1. Non-blocking HTTP command listener
    try:
        conn, addr = s.accept()
        conn.settimeout(1.0)
        req = conn.recv(1024).decode('utf-8')

        # --- MODE SWITCH ---
        if "MODE_DOMESTIC" in req:
            print("Mode → DOMESTIC (gate locked)")
            portal_mode = "DOMESTIC"
            portal_status = "Secure"
            set_gate_angle(0)
            set_mode_leds()
            response_body = '{"status":"executed","action":"MODE_DOMESTIC","gate":0}'

        elif "MODE_TNR" in req:
            print("Mode → TNR (gate open)")
            portal_mode = "TNR"
            portal_status = "Monitoring"
            set_gate_angle(90)
            set_mode_leds()
            response_body = '{"status":"executed","action":"MODE_TNR","gate":90}'

        # --- ACCESS APPROVED (open gate temporarily in DOMESTIC, or keep open in TNR) ---
        elif "ACCESS_APPROVED" in req:
            print("Command: ACCESS_APPROVED")
            portal_status = "Access Granted"
            chirp(success=True)
            red_led.off()
            green_led.on()

            if portal_mode == "DOMESTIC":
                # Open gate temporarily, then relock
                set_gate_angle(90)
                utime.sleep(4)
                set_gate_angle(0)
                red_led.on()
                green_led.off()
                portal_status = "Secure"
            else:
                # TNR mode: gate stays open (it already is)
                set_gate_angle(90)
                portal_status = "Monitoring"

            response_body = '{"status":"executed","action":"ACCESS_APPROVED"}'

        # --- LOCK CAPTURE (close gate in TNR mode, confirm locked in DOMESTIC) ---
        elif "LOCK_CAPTURE" in req:
            print("Command: LOCK_CAPTURE")
            portal_status = "Captured"
            chirp(success=False)
            set_gate_angle(0)  # Lock gate shut
            red_led.on()
            green_led.off()
            response_body = '{"status":"executed","action":"LOCK_CAPTURE"}'

        # --- SAFE RELEASE (open gate, return to resting state) ---
        elif "SAFE_RELEASE" in req:
            print("Command: SAFE_RELEASE")
            chirp(success=True)
            set_gate_angle(90)  # Open to release
            red_led.off()
            green_led.on()
            portal_status = "Released"

            if portal_mode == "DOMESTIC":
                # After release, return to locked resting state
                utime.sleep(4)
                set_gate_angle(0)
                red_led.on()
                green_led.off()
                portal_status = "Secure"
            else:
                # TNR mode: stay open (resting state)
                portal_status = "Monitoring"

            response_body = '{"status":"executed","action":"SAFE_RELEASE"}'

        else:
            # Status API endpoint
            response_body = '{{"status":"{}","mode":"{}","last_tag":"{}","distance":{:.2f}}}'.format(
                portal_status, portal_mode, last_scanned_tag, current_distance
            )

        response = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: application/json\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Connection: close\r\n\r\n" + response_body
        )
        conn.send(response)
        conn.close()
    except OSError:
        pass

    # 2. Local Proximity + RFID Scanning
    if current_distance < 15.0:
        if not target_in_corridor:
            print(f"Target detected at {current_distance:.1f} cm")
            chirp(success=True)
            target_in_corridor = True
            # Notify vision node of presence
            notify_laptop("TRIGGER_CAMERA")

        # Scan RFID
        status, _ = rfid.request(rfid.REQIDL)
        if status == rfid.OK:
            status, uid = rfid.SelectTagSN()
            if status == rfid.OK:
                uid_string = "_".join(str(i) for i in uid)
                if uid_string != last_uid:
                    last_uid = uid_string
                    last_scanned_tag = uid_string
                    print("RFID Scanned:", uid_string)
                    # Forward tag to vision node → Temporal workflow
                    notify_laptop("RFID:" + uid_string)

                    if uid_string in authorized_felines:
                        print("Authorized resident — awaiting vision verification")
                        portal_status = "RFID Verified"
                    else:
                        print("Unknown tag — flagged")
                        chirp(success=False)
                        for _ in range(3):
                            red_led.off()
                            utime.sleep_ms(100)
                            red_led.on()
                            utime.sleep_ms(100)
    else:
        if target_in_corridor:
            notify_laptop("STOP_CAMERA")
        target_in_corridor = False
        last_uid = ""

    utime.sleep_ms(50)
