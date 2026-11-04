import asyncio
import json
import websockets
import serial

SERIAL_PORT = "COM3"
BAUD_RATE = 115200
WS_SERVER_URL = "ws://127.0.0.1:8000/ws/simulation"

def parse_trig_protocol_2(raw_string: str) -> dict:
    try:
        parts = raw_string.strip().split(";")
        if len(parts) >= 7:
            return {
                "type": "telemetry",
                "pitch": float(parts[0]),
                "yaw": float(parts[1]),
                "depth": float(parts[2]),
                "speed": float(parts[3]),
                "touch": int(parts[4]),
                "bp": int(parts[5]),
                "by": int(parts[6])
            }
    except Exception:
        pass
    return None

def build_trig_protocol_3(ki: float, kv: float, bp: int, by: int) -> str:
    return f"{ki:.2f};{kv:.2f};{bp};{by};\n"

async def run_serial_bridge():
    ser = None
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print(f"✅ Connected to Hardware on {SERIAL_PORT}")
    except Exception:
        print(f"⚠️ Could not open {SERIAL_PORT}. Running in MOCK SIMULATION mode.")

    # วนลูป Auto-Reconnect ป้องกันโปรแกรม Crash เมื่อ Server ยังไม่พร้อม
    while True:
        try:
            print(f"🔄 Connecting to WebSocket Hub ({WS_SERVER_URL})...")
            async with websockets.connect(WS_SERVER_URL) as websocket:
                print("✅ Connected to FastAPI WebSocket Hub")
                mock_depth = 0.0
                
                while True:
                    raw_data = ""
                    if ser and ser.in_waiting > 0:
                        raw_data = ser.readline().decode('utf-8', errors='ignore')
                    else:
                        mock_depth = (mock_depth + 0.5) if mock_depth < 80 else 0
                        raw_data = f"12.5;3.2;{mock_depth:.1f};1.2;1;0;0;"

                    telemetry = parse_trig_protocol_2(raw_data)
                    if telemetry:
                        await websocket.send(json.dumps(telemetry))

                        # Trig Protocol 3 Logic (คำนวณแรงต้าน)
                        depth = telemetry.get("depth", 0)
                        bp_state = 1 if depth > 50 else 0
                        cmd_p3 = build_trig_protocol_3(ki=1.5, kv=12.0, bp=bp_state, by=0)
                        
                        if ser and ser.is_open:
                            ser.write(cmd_p3.encode('utf-8'))

                    await asyncio.sleep(0.05)

        except (websockets.exceptions.WebSocketException, OSError, TimeoutError):
            print("⚠️ Server not ready or connection lost. Retrying in 3 seconds...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(run_serial_bridge())