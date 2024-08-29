import socket
import time
import os
from prometheus_client import start_http_server, Gauge, Counter

# Configuration from environment variables
IP_ADDRESS = os.getenv("BATTERY_IP", "192.168.2.22")
PORT = int(os.getenv("BATTERY_PORT", "8080"))
SERVER_PORT = int(os.getenv("PROMETHEUS_PORT", "3425"))
BUFFER_SIZE = 4096
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL", "30"))  # Polling interval in seconds
MESSAGE_DELAY = 0.2  # Delay between each message in seconds
waitTime = 3000  # Wait time in milliseconds

# State definitions
STATE_START = 2
STATE_DECODE_PACKET0 = 3
STATE_DECODE_PACKET1 = 4
STATE_CHECK_DETAILS = 5
STATE_START_MEASURING = 6
STATE_WAIT_MEASURING = 7
STATE_DECODE_PACKET5 = 8
STATE_DECODE_PACKET6 = 9
STATE_DECODE_PACKET7 = 10
STATE_DECODE_PACKET8 = 11
STATE_SECOND_TURN = 12
STATE_FINISH = 0

# MODBUS Messages (using actual hex values from the JavaScript file)
MESSAGE_0 = "010300000066c5e0"
MESSAGE_1 = "01030500001984cc"
MESSAGE_2 = "010300100003040e"
MESSAGE_3 = "0110055000020400018100f853"
MESSAGE_4 = "010305510001d517"
MESSAGE_5 = "01030558004104e5"
MESSAGE_6 = "01030558004104e5"
MESSAGE_7 = "01030558004104e5"
MESSAGE_8 = "01030558004104e5"
MESSAGE_9 = "01100100000306444542554700176f"
MESSAGE_10 = "0110055000020400018100f853"
MESSAGE_11 = "010305510001d517"
MESSAGE_12 = "01030558004104e5"
MESSAGE_13 = "01030558004104e5"

# Prometheus Metrics
soc_gauge = Gauge('byd_soc', 'State of Charge')
max_voltage_gauge = Gauge('byd_max_voltage', 'Maximum Voltage')
min_voltage_gauge = Gauge('byd_min_voltage', 'Minimum Voltage')
soh_gauge = Gauge('byd_soh', 'State of Health')
current_gauge = Gauge('byd_current', 'Battery Current')
battery_voltage_gauge = Gauge('byd_battery_voltage', 'Battery Voltage')
max_temp_gauge = Gauge('byd_max_temp', 'Maximum Temperature')
min_temp_gauge = Gauge('byd_min_temp', 'Minimum Temperature')
battery_temp_gauge = Gauge('byd_battery_temp', 'Battery Temperature')
eta_gauge = Gauge('byd_eta', 'Battery ETA')
charge_total_counter = Counter('byd_charge_total', 'Total Charge')
discharge_total_counter = Counter('byd_discharge_total', 'Total Discharge')
tower_voltage_gauge = Gauge('byd_tower_voltage', 'Tower Voltage', ['tower'])
tower_temp_gauge = Gauge('byd_tower_temp', 'Tower Temperature', ['tower'])
tower_balancing_gauge = Gauge('byd_tower_balancing', 'Tower Balancing Count', ['tower'])

# Global Variables
myState = STATE_START
myNumberforDetails = 0
towerAttributes = [{}]
hvsModules = 0
hvsBattType_fromSerial = ""
hvsNumCells = 0
hvsNumTemps = 0

# Helper Functions

def modbus_crc(msg):
    crc = 0xFFFF
    for n in range(len(msg)):
        crc ^= msg[n]
        for i in range(8):
            if crc & 1:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc

def buf2int32US(byteArray, pos):
    return byteArray[pos + 2] * 16777216 + byteArray[pos + 3] * 65536 + byteArray[pos] * 256 + byteArray[pos + 1]

def buf2int16SI(byteArray, pos):
    value = byteArray[pos] * 256 + byteArray[pos + 1]
    if value >= 32768:
        value -= 65536
    return value

def send_msg(client, msg, timeout):
    try:
        message_bytes = bytes.fromhex(msg)
    except ValueError:
        print(f"Invalid hexadecimal message: {msg}")
        return False, []

    client.send(message_bytes)
    client.settimeout(timeout)
    try:
        data = client.recv(BUFFER_SIZE)
    except socket.timeout:
        print("Timeout or error occurred during receiving data")
        return False, []

    d = list(data[:-2])
    crc = modbus_crc(d)
    crcx = data[-1] * 0x100 + data[-2]
    if crc != crcx:
        print(f"send_msg recv crc not ok ({crc:04x}/{crcx:04x})")
        return False, []

    return True, data

def decode_packet0(data):
    byteArray = list(data)
    hvsSerial = "".join(chr(byteArray[i]) for i in range(3, 22))
    global hvsBattType_fromSerial, hvsModules
    hvsBattType_fromSerial = "HVS" if byteArray[5] == 51 else "LVS" if byteArray[5] in (49, 50) else "Unknown"
    hvsBMUA = f"V{byteArray[27]}.{byteArray[28]}"
    hvsBMUB = f"V{byteArray[29]}.{byteArray[30]}"
    hvsBMU = f"{hvsBMUA}-A" if byteArray[33] == 0 else f"{hvsBMUB}-B"
    hvsBMS = f"V{byteArray[31]}.{byteArray[32]}-{chr(byteArray[34] + 65)}"
    hvsModules = byteArray[36] % 16
    hvsTowers = byteArray[36] // 16
    hvsGrid = {0: "OffGrid", 1: "OnGrid", 2: "Backup"}.get(byteArray[38], "Unknown")

    print({
        "Serial": hvsSerial,
        "BatteryType": hvsBattType_fromSerial,
        "FirmwareBMU": hvsBMU,
        "FirmwareBMS": hvsBMS,
        "Modules": hvsModules,
        "Towers": hvsTowers,
        "GridType": hvsGrid
    })

def decode_packet1(data):
    byteArray = list(data)
    hvsSOC = buf2int16SI(byteArray, 3)
    hvsMaxVolt = round(buf2int16SI(byteArray, 5) / 100.0, 2)
    hvsMinVolt = round(buf2int16SI(byteArray, 7) / 100.0, 2)
    hvsSOH = buf2int16SI(byteArray, 9)
    hvsA = round(buf2int16SI(byteArray, 11) / 10.0, 1)
    hvsBattVolt = round(buf2int32US(byteArray, 13) / 100.0, 1)
    hvsMaxTemp = buf2int16SI(byteArray, 15)
    hvsMinTemp = buf2int16SI(byteArray, 17)
    hvsBatTemp = buf2int16SI(byteArray, 19)

    print({
        "SOC": hvsSOC,
        "MaxVolt": hvsMaxVolt,
        "MinVolt": hvsMinVolt,
        "SOH": hvsSOH,
        "Current": hvsA,
        "BatteryVoltage": hvsBattVolt,
        "MaxTemp": hvsMaxTemp,
        "MinTemp": hvsMinTemp,
        "BatteryTemp": hvsBatTemp
    })

    # Update Prometheus metrics
    soc_gauge.set(hvsSOC)
    max_voltage_gauge.set(hvsMaxVolt)
    min_voltage_gauge.set(hvsMinVolt)
    soh_gauge.set(hvsSOH)
    current_gauge.set(hvsA)
    battery_voltage_gauge.set(hvsBattVolt)
    max_temp_gauge.set(hvsMaxTemp)
    min_temp_gauge.set(hvsMinTemp)
    battery_temp_gauge.set(hvsBatTemp)

def decode_packet2(data):
    global hvsNumCells, hvsNumTemps
    byteArray = list(data)
    hvsBattType = byteArray[5]
    hvsInvType = byteArray[3]

    if hvsBattType == 1:
        hvsNumCells = hvsModules * 16
        hvsNumTemps = hvsModules * 8
    elif hvsBattType == 2:
        hvsNumCells = hvsModules * 32
        hvsNumTemps = hvsModules * 12

    if hvsBattType_fromSerial == "LVS":
        hvsBattType = "LVS"
        hvsNumCells = hvsModules * 7
        hvsNumTemps = 0

    print({
        "BatteryType": hvsBattType,
        "InverterType": hvsInvType,
        "NumCells": hvsNumCells,
        "NumTemps": hvsNumTemps
    })

def decode_packet5(data, towerNumber=0):
    byteArray = list(data)
    towerAttributes[towerNumber]["hvsMaxmVolt"] = buf2int16SI(byteArray, 5)
    towerAttributes[towerNumber]["hvsMinmVolt"] = buf2int16SI(byteArray, 7)
    towerAttributes[towerNumber]["hvsMaxmVoltCell"] = byteArray[9]
    towerAttributes[towerNumber]["hvsMinmVoltCell"] = byteArray[10]
    towerAttributes[towerNumber]["hvsMaxTempCell"] = byteArray[15]
    towerAttributes[towerNumber]["hvsMinTempCell"] = byteArray[16]

    # Starting with byte 101, ending with 131, Cell voltage 1-16
    MaxCells = 16
    for i in range(MaxCells):
        towerAttributes[towerNumber].setdefault("hvsBatteryVoltsperCell", {})[i + 1] = buf2int16SI(byteArray, i * 2 + 101)

    # Balancing Flags
    towerAttributes[towerNumber]["balancing"] = data[17:33].hex()
    towerAttributes[towerNumber]["balancingcount"] = countSetBits(data[17:33])

    # Ensure the charge and discharge totals are updated correctly as counters
    charge_total = buf2int32US(byteArray, 33)
    discharge_total = buf2int32US(byteArray, 37)
    towerAttributes[towerNumber]["chargeTotal"] = charge_total
    towerAttributes[towerNumber]["dischargeTotal"] = discharge_total

    charge_total_counter.inc(charge_total)
    discharge_total_counter.inc(discharge_total)

    towerAttributes[towerNumber]["eta"] = discharge_total / charge_total if charge_total > 0 else 0
    towerAttributes[towerNumber]["batteryVolt"] = buf2int16SI(byteArray, 45)
    towerAttributes[towerNumber]["outVolt"] = buf2int16SI(byteArray, 51)
    towerAttributes[towerNumber]["hvsSOCDiagnosis"] = round(buf2int16SI(byteArray, 53) / 10.0, 1)
    towerAttributes[towerNumber]["soh"] = buf2int16SI(byteArray, 55)
    towerAttributes[towerNumber]["state"] = f"{byteArray[59]:02x}{byteArray[60]:02x}"

    # Update Prometheus metrics for this tower
    tower_voltage_gauge.labels(tower=towerNumber).set(towerAttributes[towerNumber]["batteryVolt"])
    tower_temp_gauge.labels(tower=towerNumber).set(towerAttributes[towerNumber]["hvsSOCDiagnosis"])
    tower_balancing_gauge.labels(tower=towerNumber).set(towerAttributes[towerNumber]["balancingcount"])

    print(f"Decoded packet 5 for tower {towerNumber}: {towerAttributes[towerNumber]}")

def decode_packet6(data, towerNumber=0):
    byteArray = list(data)
    MaxCells = hvsNumCells - 16
    if MaxCells > 64:
        MaxCells = 64

    for i in range(MaxCells):
        towerAttributes[towerNumber].setdefault("hvsBatteryVoltsperCell", {})[i + 17] = buf2int16SI(byteArray, i * 2 + 5)

    print(f"Decoded packet 6 for tower {towerNumber}: {towerAttributes[towerNumber]}")

def decode_packet7(data, towerNumber=0):
    byteArray = list(data)
    MaxCells = hvsNumCells - 80
    if MaxCells > 48:
        MaxCells = 48

    for i in range(MaxCells):
        towerAttributes[towerNumber].setdefault("hvsBatteryVoltsperCell", {})[i + 81] = buf2int16SI(byteArray, i * 2 + 5)

    MaxTemps = hvsNumTemps
    if MaxTemps > 30:
        MaxTemps = 30

    for i in range(MaxTemps):
        towerAttributes[towerNumber].setdefault("hvsBatteryTempperCell", {})[i + 1] = byteArray[i + 103]

    print(f"Decoded packet 7 for tower {towerNumber}: {towerAttributes[towerNumber]}")

def decode_packet8(data, towerNumber=0):
    byteArray = list(data)
    MaxTemps = hvsNumTemps - 30
    if MaxTemps > 34:
        MaxTemps = 34

    for i in range(MaxTemps):
        towerAttributes[towerNumber].setdefault("hvsBatteryTempperCell", {})[i + 31] = byteArray[i + 5]

    print(f"Decoded packet 8 for tower {towerNumber}: {towerAttributes[towerNumber]}")

def decode_response12(data, towerNumber=0):
    byteArray = list(data)
    MaxCells = 16
    start_byte = 101
    end_byte = start_byte + MaxCells * 2
    available_bytes = len(byteArray) - start_byte
    available_cells = available_bytes // 2
    cells_to_read = min(MaxCells, available_cells)

    for i in range(cells_to_read):
        cell_index = i + 1 + 128
        pos = i * 2 + start_byte
        cell_voltage = buf2int16SI(byteArray, pos)
        towerAttributes[towerNumber].setdefault("hvsBatteryVoltsperCell", {})[cell_index] = cell_voltage

    print(f"Decoded response 12 for tower {towerNumber}: {towerAttributes[towerNumber]}")

def setStates():
    print("Setting states:", towerAttributes)

def countSetBits(data):
    return sum(bin(byte).count('1') for byte in data)

def open_connection():
    """Open a socket connection to the battery."""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((IP_ADDRESS, PORT))
    return client

def close_connection(client):
    """Close the socket connection."""
    client.close()

def handle_state(client, next_state, message, decode_function, *args):
    """Handle state transition and decoding."""
    global myState
    res, data = send_msg(client, message, 1.0)
    if res:
        decode_function(data, *args)
        myState = next_state
    time.sleep(MESSAGE_DELAY)

def main():
    global myState, myNumberforDetails, hvsModules, hvsBattType_fromSerial, hvsNumCells, hvsNumTemps, towerAttributes

    print("BYD BatteryBox exporter v0.1")
    print(f"BBox IP: {IP_ADDRESS}")
    print(f"Port: {SERVER_PORT}")

    # Start Prometheus metrics server
    start_http_server(SERVER_PORT)
    print(f"Metrics server listening on port {SERVER_PORT}")

    while True:
        # Reopen the socket connection at the beginning of each polling cycle
        client = open_connection()

        try:
            if myState == STATE_START:
                handle_state(client, STATE_DECODE_PACKET0, MESSAGE_0, decode_packet0)

            if myState == STATE_DECODE_PACKET0:
                handle_state(client, STATE_DECODE_PACKET1, MESSAGE_1, decode_packet1)

            if myState == STATE_DECODE_PACKET1:
                handle_state(client, STATE_START_MEASURING, MESSAGE_2, decode_packet2)
                myNumberforDetails = 0
                handle_state(client, STATE_START_MEASURING, MESSAGE_3, lambda x: None)

            if myState == STATE_START_MEASURING:
                client.settimeout(waitTime / 1000)
                print(f"waiting {waitTime / 1000} seconds to measure cells")
                time.sleep(waitTime / 1000)
                handle_state(client, STATE_WAIT_MEASURING, MESSAGE_4, lambda x: None)

            if myState == STATE_WAIT_MEASURING:
                handle_state(client, STATE_DECODE_PACKET5, MESSAGE_5, decode_packet5)

            if myState == STATE_DECODE_PACKET5:
                handle_state(client, STATE_DECODE_PACKET6, MESSAGE_6, decode_packet6)

            if myState == STATE_DECODE_PACKET6:
                handle_state(client, STATE_DECODE_PACKET7, MESSAGE_7, decode_packet7)

            if myState == STATE_DECODE_PACKET7:
                handle_state(client, STATE_DECODE_PACKET8, MESSAGE_8, decode_packet8)

            if myState == STATE_DECODE_PACKET8:
                setStates()
                close_connection(client)
                myState = STATE_START
                time.sleep(POLLING_INTERVAL)
                continue  # Go to the next polling cycle

        except OSError as e:
            print(f"Socket error: {e}")
            close_connection(client)
            myState = STATE_START
            time.sleep(POLLING_INTERVAL)
            continue  # Attempt to reconnect in the next polling cycle

        except Exception as e:
            print(f"Unexpected error: {e}")
            close_connection(client)
            myState = STATE_START
            time.sleep(POLLING_INTERVAL)
            continue  # Restart the process in the next polling cycle

if __name__ == '__main__':
    main()
