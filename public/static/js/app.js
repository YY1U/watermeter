/**
 * ระบบตรวจจับระดับน้ำอัตโนมัติ CCTV เทศบาลเมืองปทุมธานี
 * Client-side JavaScript: Web Audio API Synthesizer, Real-time Chart, Telemetry
 */

// =============================================================================
// 1. Audio Alert Synthesizer (Web Audio API)
// =============================================================================
class WebAudioAlertEngine {
  constructor() {
    this.audioCtx = null;
    this.isAudioEnabled = false;
    this.isSirenPlaying = false;
    this.sirenOscillator = null;
    this.sirenGain = null;
    this.lastSoundTime = 0;
  }

  init() {
    if (!this.audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new AudioContext();
    }
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
    this.isAudioEnabled = true;
  }

  // เสียงเตือนสีส้ม (Warning - Dual Tone EAS Alert 853Hz & 960Hz)
  playWarningTone() {
    if (!this.isAudioEnabled || !this.audioCtx) return;
    this.init();

    const now = this.audioCtx.currentTime;
    
    // เสียงบี๊บ 2 จังหวะ
    [0, 0.4].forEach(offset => {
      const start = now + offset;
      const duration = 0.25;

      const osc1 = this.audioCtx.createOscillator();
      const osc2 = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();

      osc1.type = 'sawtooth';
      osc1.frequency.setValueAtTime(853, start); // EAS frequency 1

      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(960, start); // EAS frequency 2

      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.35, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, start + duration);

      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(this.audioCtx.destination);

      osc1.start(start);
      osc2.start(start);
      osc1.stop(start + duration);
      osc2.stop(start + duration);
    });
  }

  // เสียงหวูดไซเรนฉุกเฉินสีแดง (Critical Alert - Sweeping Siren 650Hz -> 1600Hz)
  playCriticalSiren() {
    if (!this.isAudioEnabled || !this.audioCtx) return;
    this.init();

    const now = this.audioCtx.currentTime;
    const duration = 2.4; // 1 รอบของเสียงหวูด

    const osc = this.audioCtx.createOscillator();
    const gain = this.audioCtx.createGain();

    osc.type = 'sawtooth';

    // Ramping pitch ขึ้นและลง
    osc.frequency.setValueAtTime(650, now);
    osc.frequency.exponentialRampToValueAtTime(1700, now + 1.2);
    osc.frequency.exponentialRampToValueAtTime(650, now + duration);

    gain.gain.setValueAtTime(0.01, now);
    gain.gain.linearRampToValueAtTime(0.45, now + 0.1);
    gain.gain.setValueAtTime(0.45, now + duration - 0.2);
    gain.gain.exponentialRampToValueAtTime(0.01, now + duration);

    osc.connect(gain);
    gain.connect(this.audioCtx.destination);

    osc.start(now);
    osc.stop(now + duration);
  }
}

const audioAlert = new WebAudioAlertEngine();


// =============================================================================
// 2. Real-time Chart Initialization (Chart.js)
// =============================================================================
let waterChart = null;

function initWaterChart() {
  const ctx = document.getElementById('waterChart').getContext('2d');
  
  // สร้าง Gradient แรเงาใต้เส้น
  const gradient = ctx.createLinearGradient(0, 0, 0, 160);
  gradient.addColorStop(0, 'rgba(56, 189, 248, 0.45)');
  gradient.addColorStop(1, 'rgba(56, 189, 248, 0.0)');

  waterChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'ระดับน้ำ (เมตร)',
          data: [],
          borderColor: '#38bdf8',
          borderWidth: 2.5,
          backgroundColor: gradient,
          fill: true,
          tension: 0.35,
          pointRadius: 2,
          pointHoverRadius: 6,
          pointBackgroundColor: '#00f2fe'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: { color: '#64748b', font: { family: "'JetBrains Mono'", size: 10 } }
        },
        y: {
          min: 1.0,
          max: 3.2,
          grid: { color: 'rgba(255, 255, 255, 0.07)' },
          ticks: {
            color: '#94a3b8',
            font: { family: "'JetBrains Mono'", size: 11 },
            callback: value => value.toFixed(2) + 'm'
          }
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(15, 23, 42, 0.9)',
          titleFont: { family: "'Prompt'" },
          bodyFont: { family: "'JetBrains Mono'" },
          callbacks: {
            label: context => `ระดับน้ำ: ${context.parsed.y.toFixed(2)} ม.`
          }
        }
      }
    }
  });
}

function updateChart(history) {
  if (!waterChart || !history || history.length === 0) return;

  const labels = history.map(item => item.time || '');
  const data = history.map(item => item.level);

  waterChart.data.labels = labels;
  waterChart.data.datasets[0].data = data;
  waterChart.update('none'); // Update without full redraw animation
}


// =============================================================================
// 3. UI Updates & State Management
// =============================================================================
let currentHudOverlay = true;
let lastAlertPlayTime = 0;
const SOUND_COOLDOWN = 3500; // 3.5 วินาทีระหว่างเสียงเตือน

function updateTelemetryUI(data) {
  const level = data.level;
  const status = data.status;

  // 1. Digital Readout
  const numElem = document.getElementById('waterLevelNumber');
  numElem.textContent = level.toFixed(2);

  // 2. Liquid Gauge Cylinder Height
  // สูงสุด 3.00 เมตร = 100%
  const gaugePercent = Math.min(100, Math.max(0, (level / 3.00) * 100));
  const liquidElem = document.getElementById('gaugeLiquid');
  liquidElem.style.height = `${gaugePercent}%`;

  // เปลี่ยนสีของ Liquid ตามระดับสถานะ
  liquidElem.classList.remove('status-warning', 'status-critical');
  if (status === 'WARNING') {
    liquidElem.classList.add('status-warning');
  } else if (status === 'CRITICAL') {
    liquidElem.classList.add('status-critical');
  }

  // 3. Status Badge
  const badgeElem = document.getElementById('currentStatusBadge');
  badgeElem.className = `status-badge ${status.toLowerCase()}`;
  if (status === 'NORMAL') {
    badgeElem.textContent = 'ปลอดภัย (NORMAL)';
  } else if (status === 'WARNING') {
    badgeElem.textContent = 'เฝ้าระวัง (WARNING)';
  } else if (status === 'CRITICAL') {
    badgeElem.textContent = 'วิกฤต (CRITICAL)!';
  }

  // 4. Subtext Delta
  const subtextElem = document.getElementById('waterLevelSubtext');
  const warnDiff = (data.thresholds.warning - level);
  if (level >= data.thresholds.critical) {
    subtextElem.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="color:#ef4444"></i> เกินเกณฑ์วิกฤต +${(level - data.thresholds.critical).toFixed(2)} ม.!`;
  } else if (level >= data.thresholds.warning) {
    subtextElem.innerHTML = `<i class="fa-solid fa-triangle-exclamation" style="color:#f59e0b"></i> เข้าสู่เกณฑ์เฝ้าระวัง (+${(level - data.thresholds.warning).toFixed(2)} ม.)`;
  } else {
    subtextElem.innerHTML = `<i class="fa-solid fa-circle-check" style="color:#10b981"></i> ต่ำกว่าเกณฑ์เฝ้าระวัง ${warnDiff.toFixed(2)} ม.`;
  }

  // 5. Waterline Y & FPS
  document.getElementById('dispWaterlineY').textContent = `Y = ${data.waterline_y} px`;
  document.getElementById('fpsDisplay').textContent = `${data.fps} FPS`;

  // 6. Stream Status Pill
  const statusPill = document.getElementById('streamStatusPill');
  const statusText = document.getElementById('streamStatusText');
  statusPill.className = 'status-pill ' + (data.is_connected ? 'connected' : 'connecting');
  statusText.textContent = data.is_connected ? 'ออนไลน์ (ONLINE)' : 'กำลังเชื่อมต่อ...';

  // 7. Thresholds Display
  document.getElementById('dispWarnThreshold').innerHTML = `&ge; ${data.thresholds.warning.toFixed(2)} ม.`;
  document.getElementById('dispCritThreshold').innerHTML = `&ge; ${data.thresholds.critical.toFixed(2)} ม.`;

  // 8. Flashing Red Vignette on Critical Alert
  const vignette = document.getElementById('criticalVignette');
  if (status === 'CRITICAL') {
    vignette.classList.remove('hidden');
  } else {
    vignette.classList.add('hidden');
  }

  // 9. Play Browser Audio Alert (if enabled)
  const now = Date.now();
  if (status in { 'WARNING': 1, 'CRITICAL': 1 } && (now - lastAlertPlayTime > SOUND_COOLDOWN)) {
    lastAlertPlayTime = now;
    if (status === 'CRITICAL') {
      audioAlert.playCriticalSiren();
    } else if (status === 'WARNING') {
      audioAlert.playWarningTone();
    }
  }

  // 10. Update Chart
  if (data.history) {
    updateChart(data.history);
  }
}


// =============================================================================
// 4. Polling Telemetry from Server
// =============================================================================
async function fetchTelemetry() {
  try {
    const res = await fetch('/api/status');
    if (res.ok) {
      const data = await res.json();
      updateTelemetryUI(data);
    }
  } catch (err) {
    console.warn('[Telemetry Error]', err);
    document.getElementById('streamStatusPill').className = 'status-pill disconnected';
    document.getElementById('streamStatusText').textContent = 'ขาดการเชื่อมต่อ';
  }
}


// =============================================================================
// 5. Snapshot Gallery Management
// =============================================================================
async function loadSnapshots() {
  try {
    const res = await fetch('/api/snapshots');
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById('snapshotsGallery');

    if (!data.snapshots || data.snapshots.length === 0) {
      container.innerHTML = `
        <div class="gallery-empty">
          <i class="fa-regular fa-image"></i>
          <p>ยังไม่มีภาพบันทึกเหตุการณ์เตือนภัย</p>
        </div>`;
      return;
    }

    container.innerHTML = data.snapshots.map(s => `
      <div class="gallery-item" onclick="openImageModal('${s.url}', '${s.filename}')">
        <img src="${s.url}" alt="${s.filename}" loading="lazy">
        <div class="gallery-meta">
          <span>${s.filename.split('_')[1] || 'SNAP'}</span>
          <span>${s.time.split(' ')[1] || ''}</span>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Failed to load snapshots:', err);
  }
}

function openImageModal(url, title) {
  document.getElementById('modalImageTitle').textContent = title;
  document.getElementById('modalImagePreview').src = url;
  document.getElementById('btnDownloadSnapshot').href = url;
  document.getElementById('imageModal').classList.remove('hidden');
}


// =============================================================================
// 6. Event Handlers & Controls
// =============================================================================
document.addEventListener('DOMContentLoaded', () => {
  // เริ่มต้นกราฟ
  initWaterChart();

  // จัดการการแสดงผลวิดีโอ (อัปเดตเฟรมสดต่อเนื่อง รองรับทั้ง Local และ Vercel Serverless)
  const videoElem = document.getElementById('liveVideo');
  let frameUpdateInterval = null;

  function updateVideoFrame() {
    const nextImg = new Image();
    const url = `/api/frame?overlay=${currentHudOverlay ? '1' : '0'}&t=${Date.now()}`;
    nextImg.onload = () => {
      videoElem.src = url;
    };
    nextImg.src = url;
  }

  // อัปเดตเฟรมภาพทุก 1.2 วินาที
  frameUpdateInterval = setInterval(updateVideoFrame, 1200);

  // ดึงข้อมูลครั้งแรก
  fetchTelemetry();
  loadSnapshots();

  // Polling ข้อมูลทุก 1.5 วินาที
  setInterval(fetchTelemetry, 1500);

  // นาฬิกาดิจิทัล
  setInterval(() => {
    const now = new Date();
    document.getElementById('clockTime').textContent = now.toLocaleTimeString('th-TH');
  }, 1000);

  // ปุ่มเปิดระบบเสียงเตือน (Banner)
  const btnEnableAudio = document.getElementById('btnEnableAudio');
  const audioBanner = document.getElementById('audioBanner');
  btnEnableAudio.addEventListener('click', () => {
    audioAlert.init();
    audioBanner.classList.add('hidden');
    updateAudioButtonUI(true);
    // ทดสอบเล่นเสียงสั้นๆ เพื่อยืนยันว่าเปิดสำเร็จ
    audioAlert.playWarningTone();
  });

  // ปุ่มสลับเสียงที่ Header
  const btnAudioToggle = document.getElementById('btnAudioToggle');
  btnAudioToggle.addEventListener('click', () => {
    if (!audioAlert.isAudioEnabled) {
      audioAlert.init();
      audioBanner.classList.add('hidden');
      updateAudioButtonUI(true);
      audioAlert.playWarningTone();
    } else {
      audioAlert.isAudioEnabled = false;
      updateAudioButtonUI(false);
    }
  });

  function updateAudioButtonUI(enabled) {
    const icon = btnAudioToggle.querySelector('i');
    const text = document.getElementById('audioStatusText');
    if (enabled) {
      btnAudioToggle.classList.add('active');
      icon.className = 'fa-solid fa-volume-high';
      text.textContent = 'เสียง: เปิด';
    } else {
      btnAudioToggle.classList.remove('active');
      icon.className = 'fa-solid fa-volume-xmark';
      text.textContent = 'เสียง: ปิด';
    }
  }

  // ทดสอบเสียง Warning
  document.getElementById('btnTestWarning').addEventListener('click', () => {
    audioAlert.init();
    audioBanner.classList.add('hidden');
    updateAudioButtonUI(true);
    audioAlert.playWarningTone();
  });

  // ทดสอบเสียง Critical
  document.getElementById('btnTestCritical').addEventListener('click', () => {
    audioAlert.init();
    audioBanner.classList.add('hidden');
    updateAudioButtonUI(true);
    audioAlert.playCriticalSiren();
  });

  // สลับการแสดงผลเส้นวัดระดับน้ำ HUD บนสตรีม
  const btnToggleHud = document.getElementById('btnToggleHud');
  btnToggleHud.addEventListener('click', () => {
    currentHudOverlay = !currentHudOverlay;
    btnToggleHud.classList.toggle('active', currentHudOverlay);
    const videoElem = document.getElementById('liveVideo');
    videoElem.src = `/video_feed?overlay=${currentHudOverlay ? '1' : '0'}&t=${Date.now()}`;
  });

  // ถ่าย Snapshot ด้วยตนเอง
  document.getElementById('btnManualSnapshot').addEventListener('click', async () => {
    const btn = document.getElementById('btnManualSnapshot');
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> บันทึก...`;

    try {
      const res = await fetch('/api/snapshot/take', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        loadSnapshots();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setTimeout(() => {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-camera"></i> ถ่าย Snapshot`;
      }, 800);
    }
  });

  // ปุ่มรีเซ็ตสตรีม
  document.getElementById('btnReloadStream').addEventListener('click', () => {
    const videoElem = document.getElementById('liveVideo');
    videoElem.src = `/video_feed?overlay=${currentHudOverlay ? '1' : '0'}&t=${Date.now()}`;
  });

  // รีเฟรชแกลเลอรีภาพ
  document.getElementById('btnRefreshSnapshots').addEventListener('click', loadSnapshots);

  // ปุ่ม Fullscreen
  document.getElementById('btnFullscreen').addEventListener('click', () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(err => alert(err.message));
    } else {
      document.exitFullscreen();
    }
  });

  // Modal ดูภาพ Snapshot
  document.getElementById('btnCloseImageModal').addEventListener('click', () => {
    document.getElementById('imageModal').classList.add('hidden');
  });

  // Modal Settings
  const settingsModal = document.getElementById('settingsModal');
  document.getElementById('btnSettings').addEventListener('click', async () => {
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      document.getElementById('inputWarning').value = data.warning;
      document.getElementById('inputCritical').value = data.critical;
      settingsModal.classList.remove('hidden');
    } catch (e) {
      console.error(e);
    }
  });

  document.getElementById('btnCloseSettingsModal').addEventListener('click', () => {
    settingsModal.classList.add('hidden');
  });

  document.getElementById('btnSaveSettings').addEventListener('click', async () => {
    const warn = parseFloat(document.getElementById('inputWarning').value);
    const crit = parseFloat(document.getElementById('inputCritical').value);
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ warning: warn, critical: crit })
    });
    settingsModal.classList.add('hidden');
    fetchTelemetry();
  });
});
