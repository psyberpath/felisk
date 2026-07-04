import mfrc522
from machine import Pin, PWM
import network
import socket
import utime

# ---------------- Wi-Fi Config ----------------
WIFI_SSID = "Galaxy S21 FE 5G"
WIFI_PASS = "bevbevbev"

# ---------------- Hardware Pins ----------------
trig = Pin(2, Pin.OUT)
echo = Pin(3, Pin.IN)

servo = PWM(Pin(15))
servo.freq(50)

green_led = Pin(14, Pin.OUT)
red_led = Pin(13, Pin.OUT)
buzzer = Pin(12, Pin.OUT)

# ---------------- State Variables ----------------
portal_status = "Secure"
last_scanned_tag = "None"
current_distance = 100.0
authorized_felines = ["146_73_250_5"]

# Initialize GitHub MFRC522 Driver
rfid = mfrc522.MFRC522(sck=18, mosi=19, miso=16, rst=20, cs=17)

# ---------------- Hardware Helpers ----------------
def set_gate_angle(angle):
    # duty maps 0 to 180 degrees cleanly on the Pico W
    min_duty = 1638  # 0.5ms (Closed / Locked)
    max_duty = 8192  # 2.5ms (Open / Unlocked)
    duty = int(min_duty + (angle / 180) * (max_duty - min_duty))
    servo.duty_u16(duty)

def chirp(success=True):
    """Sounds clean audit alert tones using the active buzzer [cite: 10]."""
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
    """Reads non-blocking echo timing from the HC-SR04 sensor [cite: 10]."""
    trig.low()
    utime.sleep_us(2)
    trig.high()
    utime.sleep_us(10)
    trig.low()
    
    timeout_us = 20000  # Prevent hanging loops
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

# ---------------- Connect Wi-Fi ----------------
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

if not wlan.isconnected():
    print("Connecting to Wi-Fi...")
    wlan.connect(WIFI_SSID, WIFI_PASS)
    while not wlan.isconnected():
        utime.sleep_ms(500)

# Fix: Extract only the local IP address from the ifconfig tuple
pico_ip = wlan.ifconfig()
print("Network Connected! Portal Control Plane live at:", f"http://{pico_ip}/")

# ---------------- Unified Web API Socket (Port 80) ----------------
s = socket.socket()
s.bind(("0.0.0.0", 80))
s.listen(2)
s.setblocking(False)  # Ensure non-blocking so sensors continue polling! [cite: 11]

# Set Safe Initial State
set_gate_angle(0)
red_led.on()
green_led.off()
buzzer.off()

last_uid = ""
target_in_corridor = False

# ---------------- Unified Main Loop ----------------
while True:
    current_distance = measure_distance()

    # 1. Non-blocking Socket Listener (Supports JSON Status API and Actuation commands)
    try:
        conn, addr = s.accept()
        conn.settimeout(1.0)  # Give accepted connection 1s to send data
        req = conn.recv(1024).decode('utf-8')
        
        # Parse command queries
        if "GET /api/command?value=ACCESS_APPROVED" in req or "ACCESS_APPROVED" in req:
            print("Control plane command: ACCESS_APPROVED")
            portal_status = "Access Granted"
            chirp(success=True)
            red_led.off()
            green_led.on()
            
            set_gate_angle(90)  # Smooth lift
            utime.sleep(4)
            set_gate_angle(0)   # Relock
            
            green_led.off()
            red_led.on()
            portal_status = "Secure"
            response_body = '{"status":"executed","action":"ACCESS_APPROVED"}'
            
        elif "GET /api/command?value=LOCK_CAPTURE" in req or "LOCK_CAPTURE" in req:
            print("Control plane command: LOCK_CAPTURE")
            portal_status = "Stray Captured"
            chirp(success=False)
            set_gate_angle(0)   # Drop door to lock
            red_led.on()
            green_led.off()
            response_body = '{"status":"executed","action":"LOCK_CAPTURE"}'
            
        elif "GET /api/command?value=SAFE_RELEASE" in req or "SAFE_RELEASE" in req:
            print("Control plane command: SAFE_RELEASE")
            portal_status = "Secure"
            chirp(success=True)
            set_gate_angle(90)  # Open door to release cat
            red_led.off()
            green_led.on()
            response_body = '{"status":"executed","action":"SAFE_RELEASE"}'
            
        else:
            # Default GET /api/status request returning lightweight JSON parameters
            response_body = '{{"status":"{}","last_tag":"{}","distance":{:.2f}}}'.format(
                portal_status, last_scanned_tag, current_distance
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

    # 2. Local Proximity and RFID Scanning
    if current_distance < 15.0:
        if not target_in_corridor:
            # Local sensor feedback: sound a confirmation beep when an animal enters
            print(f"Target detected at {current_distance:.1f} cm. Initializing local scan...")
            chirp(success=True)
            target_in_corridor = True

        # Check card RFID scanner
        status, _ = rfid.request(rfid.REQIDL)
        if status == rfid.OK:
            status, uid = rfid.SelectTagSN()
            if status == rfid.OK:
                uid_string = "_".join(str(i) for i in uid)
                if uid_string!= last_uid:
                    last_uid = uid_string
                    last_scanned_tag = uid_string
                    print("RFID Scanned on Pico W:", uid_string)
                    
                    if uid_string not in authorized_felines:
                        portal_status = "Unauthorized Blocked"
                        print("Tag Access Denied.")
                        chirp(success=False)
                        for _ in range(3):
                            red_led.off()
                            utime.sleep_ms(100)
                            red_led.on()
                            utime.sleep_ms(100)
                        portal_status = "Secure"
                    else:
                        print("Authorized resident matched locally.")
                        portal_status = "Verifying Snout AI..."
    else:
        target_in_corridor = False
        last_uid = ""

    utime.sleep_ms(50)