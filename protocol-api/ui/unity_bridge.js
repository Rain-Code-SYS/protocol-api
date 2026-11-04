// ==========================================================================
// 1. อ่านค่า Trig Protocol 1 จาก sessionStorage (ที่ถูกส่งมาจากหน้า Dashboard Setup)
// ==========================================================================
const storedProcedure = sessionStorage.getItem("sim_procedure") || "Thoracentesis";
const storedConfigRaw = sessionStorage.getItem("sim_config");

// ค่า Default กรณีเปิดหน้า /simulation โดยตรงโดยไม่ผ่าน Modal
let trigProtocol1 = {
  age: 1,          // 0: Pediatric, 1: Adult, 2: Geriatric
  difficulty: 1,   // 0: Easy, 1: Medium, 2: Hard
  case_type: 0,    // 0: Trauma, 1: Emergency
  practice_mode: 1 // 0: Tutorial, 1: Guide, 2: Blind
};

if (storedConfigRaw) {
  try {
    trigProtocol1 = JSON.parse(storedConfigRaw);
    console.log("✅ Loaded Trig Protocol 1 from Setup:", trigProtocol1);
  } catch (e) {
    console.warn("⚠️ Failed to parse sim_config, using default.");
  }
}

// ==========================================================================
// 2. อัปเดต UI หน้า Simulation ตาม Trig Protocol 1
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  // อัปเดตชื่อ Procedure
  const titleEl = document.querySelector(".sim-title");
  if (titleEl) titleEl.innerText = storedProcedure;

  // แปลงค่า Difficulty Enum (0, 1, 2) เป็นข้อความ
  const diffMap = ["Easy", "Medium", "Hard"];
  const diffSelect = document.querySelector(".styled-select");
  if (diffSelect) {
    diffSelect.value = diffMap[trigProtocol1.difficulty] || "Medium";
  }

  // แปลงค่า Practice Mode Enum (0, 1, 2) เป็นข้อความอัปเดต Tag
  const modeMap = ["Tutorial", "Guided", "Blind"];
  const activeModeText = modeMap[trigProtocol1.practice_mode] || "Guided";
  
  document.querySelectorAll(".tag-guided, .tag-tutorial").forEach(tag => {
    tag.innerText = activeModeText;
    if (activeModeText === "Blind") {
      tag.style.background = "#f3e8ff";
      tag.style.color = "#9333ea";
    }
  });
});

// ==========================================================================
// 3. เชื่อมต่อ WebSocket สำหรับ Real-Time Telemetry & Trig Protocols
// ==========================================================================
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const wsUrl = `${wsProtocol}//${window.location.host}/ws/simulation`;

let socket = new WebSocket(wsUrl);

socket.onopen = () => {
  console.log("✅ Telemetry WebSocket Connected to UI Bridge");
  
  // ส่ง Trig Protocol 1 Configuration เข้า WebSocket Hub ทันทีที่ต่อสำเร็จ
  const configPayload = {
    type: "trig_protocol_1_config",
    procedure: storedProcedure,
    config: trigProtocol1
  };
  socket.send(JSON.stringify(configPayload));
};

socket.onmessage = (event) => {
  try {
    const data = JSON.parse(event.data);
    
    // รับข้อมูล Telemetry Real-time (Trig Protocol 2) จาก serial_bridge.py
    if (data.depth !== undefined) {
      const depthEl = document.getElementById("telemetry-depth");
      if (depthEl) depthEl.innerText = `${data.depth.toFixed(1)} mm`;
    }
    if (data.pitch !== undefined) {
      const angleEl = document.getElementById("telemetry-angle");
      if (angleEl) angleEl.innerText = `${data.pitch.toFixed(1)}°`;
    }
    if (data.speed !== undefined) {
      const speedEl = document.getElementById("telemetry-speed");
      if (speedEl) speedEl.innerText = `${data.speed.toFixed(1)} mm/s`;
    }

    // 💡 หากต้องการส่งค่ามุม/ความลึกต่อให้ Unity 3D Model:
    // if (window.unityInstance) {
    //   window.unityInstance.SendMessage("NeedleObject", "UpdateTelemetry", JSON.stringify(data));
    // }

  } catch (err) {
    console.error("Error parsing WebSocket message:", err);
  }
};

socket.onclose = () => {
  console.warn("⚠️ WebSocket Disconnected. Retrying in 3 seconds...");
  setTimeout(() => {
    socket = new WebSocket(wsUrl);
  }, 3000);
};