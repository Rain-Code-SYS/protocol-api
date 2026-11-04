// บันทึกสถานะตั้งค่าสำหรับ Trig Protocol 1
const configState = {
  age: 1,           // 0: Pediatric, 1: Adult, 2: Geriatric
  difficulty: 1,    // 0: Easy, 1: Medium, 2: Hard
  case_type: 0,     // 0: Basic/Trauma, 1: Emergency
  practice_mode: 1  // 0: Tutorial, 1: Guide, 2: Blind
};

// เลือก Module ในหน้าแรก
function selectModule(moduleName) {
  document.getElementById('selected-module-title').innerText = moduleName.toUpperCase();
  document.getElementById('step-modules').classList.remove('active');
  document.getElementById('step-config').classList.add('active');
}

function goBack() {
  document.getElementById('step-config').classList.remove('active');
  document.getElementById('step-modules').classList.add('active');
}

// สลับการกดปุ่ม Pill Options
function setPill(groupId, element) {
  const group = document.getElementById(groupId);
  group.querySelectorAll('.btn-pill').forEach(btn => btn.classList.remove('active'));
  element.classList.add('active');

  const val = parseInt(element.getAttribute('data-value'));
  if (groupId === 'age-group') configState.age = val;
  if (groupId === 'casetype-group') configState.case_type = val;
}

// ปรับค่า Slider ความยาก
function updateSliderLabel() {
  const slider = document.getElementById('difficulty-slider');
  configState.difficulty = parseInt(slider.value);
}

// เลือกโหมดการฝึก
function selectMode(element) {
  const group = document.getElementById('mode-group');
  group.querySelectorAll('.mode-card').forEach(card => card.classList.remove('active'));
  element.classList.add('active');
  configState.practice_mode = parseInt(element.getAttribute('data-value'));
}

// ส่ง Trig Protocol 1 ไปยัง FastAPI Backend และสลับไปหน้า Simulation
async function submitTrigProtocol1() {
  console.log("🚀 Sending Trig Protocol (1):", configState);

  try {
    const response = await fetch('/api/v1/protocols/trig_protocol_1/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(configState)
    });

    if (response.ok) {
      const data = await response.json();
      console.log("✅ API Build Success:", data);

      // บันทึกค่า Config เก็บไว้ให้หน้า simulation.html อ่านใช้งานต่อ
      sessionStorage.setItem('simConfig', JSON.stringify(configState));

      // ✅ สั่งเปลี่ยนหน้าไปยังหน้า Unity Simulation ทันที
      window.location.href = "/simulation";
    } else {
      alert("❌ ส่งข้อมูลไม่สำเร็จ ตรวจสอบการรัน FastAPI Server");
    }
  } catch (error) {
    console.error("API Error:", error);
    
    // กรณี Offline/Dev Mode: บันทึกค่าและอนุญาตให้เปลี่ยนหน้าทดสอบได้
    sessionStorage.setItem('simConfig', JSON.stringify(configState));
    window.location.href = "/simulation";
  }
}