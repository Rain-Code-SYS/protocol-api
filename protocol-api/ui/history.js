document.addEventListener("DOMContentLoaded", () => {
  initPerformanceChart();
  loadHistoryData();
});

// 1. วาดกราฟเส้น Performance Over Time ด้วย Chart.js
function initPerformanceChart() {
  const ctx = document.getElementById('performanceChart').getContext('2d');
  
  // สร้าง Gradient สีฟ้าใต้เส้นกราฟ
  const gradient = ctx.createLinearGradient(0, 0, 0, 200);
  gradient.addColorStop(0, 'rgba(0, 188, 212, 0.35)');
  gradient.addColorStop(1, 'rgba(0, 188, 212, 0.0)');

  new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['Week 1', 'Week 6', 'Week 10', 'Week 14', 'Week 18', 'Week 21', 'Week 24'],
      datasets: [{
        data: [5, 48, 35, 68, 55, 86, 98],
        borderColor: '#00bcd4',
        borderWidth: 3,
        fill: true,
        backgroundColor: gradient,
        tension: 0.4, // เพิ่มความโค้งเรียบของเส้น
        pointBackgroundColor: '#00bcd4',
        pointBorderColor: '#ffffff',
        pointBorderWidth: 2,
        pointRadius: 5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          min: 0,
          max: 100,
          ticks: { callback: value => value + '%' },
          grid: { color: '#f1f5f9' }
        },
        x: {
          grid: { display: false }
        }
      }
    }
  });
}

// 2. ดึงข้อมูลประวัติการฝึกซ้อมจาก Backend (/api/v1/history)
async function loadHistoryData() {
  const tableBody = document.getElementById("history-table-body");
  
  // ข้อมูล Mock สำรองกรณีไม่ได้ต่อ API
  const defaultHistory = [
    { id: 1, date: "Oct 06, 2026", procedure: "Thoracostomy", difficulty: "Intermediate", mode: "Guided", score: 94 },
    { id: 2, date: "Oct 04, 2026", procedure: "Paracentesis", difficulty: "Advanced", mode: "Blind Simulation", score: 88 },
    { id: 3, date: "Sep 29, 2026", procedure: "Pericardiocentesis", difficulty: "Advanced", mode: "Guided", score: 79 },
    { id: 4, date: "Sep 25, 2026", procedure: "Thoracostomy", difficulty: "Beginner", mode: "Tutorial", score: 98 },
    { id: 5, date: "Sep 20, 2026", procedure: "Paracentesis", difficulty: "Advanced", mode: "Guided", score: 92 }
  ];

  let historyData = defaultHistory;

  try {
    const res = await fetch("/api/v1/history");
    if (res.ok) {
      const data = await res.json();
      if (data && data.length > 0) historyData = data;
    }
  } catch (err) {
    console.warn("Using default history data.");
  }

  // สร้างแถบตาราง HTML
  tableBody.innerHTML = historyData.map((item, index) => {
    // เลือก Class ของ Badge Mode
    let modeClass = "mode-guided";
    if (item.mode.includes("Blind")) modeClass = "mode-blind";
    if (item.mode.includes("Tutorial")) modeClass = "mode-tutorial";

    // ปรับการแสดงผลคะแนน (แถบสีเขียว หรือ ข้อความสีส้ม)
    let scoreHtml = "";
    if (item.score >= 80) {
      scoreHtml = `
        <div class="score-cell">
          <div class="score-bar-bg"><div class="score-bar-fill" style="width: ${item.score}%;"></div></div>
          <span class="score-text-green">${item.score}%</span>
        </div>`;
    } else {
      scoreHtml = `<span class="score-text-orange font-bold">${item.score}%</span>`;
    }

    return `
      <tr>
        <td>${index + 1}.</td>
        <td>${item.date}</td>
        <td><strong>${item.procedure}</strong></td>
        <td>${item.difficulty}</td>
        <td><span class="mode-pill ${modeClass}">${item.mode}</span></td>
        <td>${scoreHtml}</td>
        <td><a href="#" class="btn-view">${index === 0 ? 'View Details' : 'View'}</a></td>
      </tr>
    `;
  }).join("");
}