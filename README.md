# 🌊 ระบบตรวจจับระดับน้ำอัตโนมัติจากกล้อง CCTV (เทศบาลเมืองปทุมธานี)
### AI Waterline Detection & Real-time Live Web Dashboard

ระบบตรวจจับระดับผิวน้ำเทียบกับสเกลเสาวัดระดับจริงผ่านกล้องสตรีม HLS พร้อมระบบแจ้งเตือนด้วยเสียง (Sound Alert), บันทึกภาพ Snapshot อัตโนมัติ และแสดงผลบน **Web Dashboard สดแบบเรียลไทม์**

---

## 🌟 ฟีเจอร์ของระบบเว็บไซต์ (Web Dashboard Features)
1. **Live CCTV Video Feed (MJPEG Stream)**:
   - ดึงสตรีมสดจากกล้อง HLS `http://101.109.253.60:8999/playlist.m3u8`
   - แสดงภาพพร้อมเส้นวัดระดับน้ำ Live HUD Overlay
   - สามารถเปิด/ปิดเส้นวัด HUD ได้แบบ Real-Time จากหน้าเว็บ
   - รองรับโหมด Fullscreen สำหรับเปิดดูบนจอมอนิเตอร์ห้องควบคุม (Control Room)
2. **Interactive Water Gauge (เกจวัดระดับน้ำจำลอง)**:
   - ทรงกระบอกแก้วพร้อมลูกเล่นคลื่นน้ำเคลื่อนไหว (Animated Wave)
   - ปรับระดับความสูงและเปลี่ยนสีตามสถานะอัตโนมัติ (เขียว = ปลอดภัย, ส้ม = เฝ้าระวัง, แดง = วิกฤต)
3. **Web Audio API Emergency Sound Alert (แจ้งเตือนด้วยเสียงบนเว็บ)**:
   - ทำงานได้บนทุกอุปกรณ์ (คอมพิวเตอร์, iPad, แท็บเล็ต, มือถือ) โดยตรงจากเว็บเบราว์เซอร์
   - **เกณฑ์สีส้ม/เฝ้าระวัง (>= 2.20 ม.)**: เสียง Beep ฉุกเฉินแบบ EAS Alert Tone (853Hz + 960Hz)
   - **เกณฑ์สีแดง/วิกฤต (>= 2.50 ม.)**: เสียงหวูดไซเรนอพยพภัย (Air Raid / Evacuation Siren Sweep) พร้อมเอฟเฟกต์ไฟกะพริบสีแดงรอบจอ
4. **Real-time Trend Chart**:
   - กราฟแนวโน้มระดับน้ำแบบเส้น (Chart.js) แสดงความเปลี่ยนแปลงของระดับน้ำย้อนหลังแบบสดๆ
5. **Event Snapshot Gallery**:
   - แกลเลอรีภาพถ่ายบันทึกเหตุการณ์อัตโนมัติเมื่อน้ำถึงระดับเตือนภัย
   - สามารถกดถ่าย Snapshot แบบแมนนวลได้จากหน้าเว็บ พร้อมดาวน์โหลดภาพความละเอียดสูง
6. **Dynamic Settings**:
   - สามารถปรับเปลี่ยนเกณฑ์เตือนภัย Warning และ Critical ได้โดยตรงผ่านหน้าต่างตั้งค่าบนเว็บ

---

## 🚀 วิธีการเริ่มต้นใช้งาน (Quick Start)

### 1. ติดตั้งไลบรารี
```bash
pip install -r requirements.txt
```

### 2. รันระบบ Web Dashboard
```bash
python app.py
```

### 3. เปิดใช้งานผ่านเว็บเบราว์เซอร์
- **บนเครื่องคอมพิวเตอร์ที่รันโปรแกรม:**  
  👉 เปิดเบราว์เซอร์ไปที่: [http://localhost:5000](http://localhost:5000)
- **บนมือถือหรือคอมพิวเตอร์เครื่องอื่นในวง Wi-Fi / LAN เดียวกัน:**  
  👉 เปิดเบราว์เซอร์ไปที่: `http://<IP-เครื่องที่รัน>:5000`

---

## 🎛️ โครงสร้างไฟล์ในโปรเจกต์
- `app.py`: ตัวขับเคลื่อนเซิร์ฟเวอร์หลัก (Flask Backend + Video Capture Worker + REST API)
- `water_monitor.py`: เวอร์ชัน Desktop GUI (OpenCV Window + Windows winsound)
- `templates/index.html`: หน้าเว็บ Dashboard
- `static/css/style.css`: ธีม Cyber-Precision Dark Mode & Glassmorphism
- `static/js/app.js`: ระบบ Web Audio API, กราฟ Chart.js, และการเชื่อมต่อ Telemetry
- `snapshots/`: โฟลเดอร์เก็บภาพถ่ายเหตุการณ์แจ้งเตือนอัตโนมัติ
