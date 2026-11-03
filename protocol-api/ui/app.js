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

// ส่ง Trig Protocol 1 ไปยัง FastAPI Backend
async function submitTrigProtocol1() {
  console.log("🚀 Sending Trig Protocol (1):", configState);

  try {
    const response = await fetch('http://127.0.0.1:8000/api/v1/protocols/trig_protocol_1/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(configState)
    });

    if (response.ok) {
      const data = await response.json();
      alert(`✅ ส่งข้อมูล Trig Protocol (1) สำเร็จ!\nPayload: ${JSON.stringify(data)}`);
    } else {
      alert("❌ ส่งข้อมูลไม่สำเร็จ ตรวจสอบการรัน FastAPI Server");
    }
  } catch (error) {
    console.error("API Error:", error);
    alert(`⚡ ส่งข้อมูลจำลอง: \nAge=${configState.age}, Difficulty=${configState.difficulty}, CaseType=${configState.case_type}, PracticeMode=${configState.practice_mode}`);
  }
}