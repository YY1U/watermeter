"""
ระบบตรวจจับระดับน้ำอัตโนมัติจากกล้อง CCTV (เทศบาลเมืองปทุมธานี) - Web Application Server
Flask Web Server พร้อมสตรีมวิดีโอ MJPEG แบบเรียลไทม์, REST API, และระบบตรวจจับระดับน้ำ
"""

import cv2
import numpy as np
import time
import threading
import sys
import os
import json
from pathlib import Path

# ปรับ encoding ของ stdout/stderr ให้รองรับ UTF-8 บน Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from flask import Flask, render_template, Response, jsonify, request, send_from_directory

# ตรวจสอบ winsound บน Windows (สำหรับการส่งเสียงที่เครื่อง Server)
try:
    import winsound
    import ctypes
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / 'templates'),
    static_folder=str(BASE_DIR / 'static')
)

# ==========================================
# การตั้งค่าระบบ (Configuration)
# ==========================================
class Config:
    STREAM_URL = "http://101.109.253.60:8999/playlist.m3u8"
    POLE_X_MIN = 286
    POLE_X_MAX = 308
    Y_300M = 230               # พิกัดระดับ 3.00 ม.
    PIXELS_PER_METER = 176.0   # สเกลพิกเซลต่อเมตร
    ALERT_ORANGE_LEVEL = 2.20  # เกณฑ์เฝ้าระวัง (เมตร)
    ALERT_RED_LEVEL = 2.50     # เกณฑ์วิกฤต (เมตร)
    # บน Vercel ระบบไฟล์เป็น Read-only ให้บันทึกใน /tmp
    SNAPSHOT_DIR = Path("/tmp/snapshots") if os.environ.get("VERCEL") else (BASE_DIR / "snapshots")
    SNAPSHOT_COOLDOWN = 15.0   # วินาที
    SERVER_SOUND = not os.environ.get("VERCEL") # ปิดเสียงที่ Server หากอยู่บน Cloud

cfg = Config()
cfg.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# State Management
# ==========================================
class MonitorState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_frame = None          # ภาพพร้อม HUD
        self.raw_frame = None              # ภาพต้นฉบับ
        self.waterline_y = 405
        self.smoothed_y = 405.0
        self.water_level = 2.00
        self.status = "NORMAL"             # NORMAL, WARNING, CRITICAL
        self.is_connected = False
        self.fps = 0.0
        self.last_update = time.time()
        self.last_alert_time = 0.0
        self.last_snapshot_time = 0.0
        self.last_alert_status = "NORMAL"
        self.history = []                  # [{'time': '12:00:00', 'level': 2.05, 'status': 'NORMAL'}]
        self.total_snapshots = 0
        self.alert_counts = {"WARNING": 0, "CRITICAL": 0}

state = MonitorState()


# ==========================================
# Server-side Sound Helper
# ==========================================
def play_server_sound(status):
    """เล่นเสียงที่เครื่อง Server หากเปิดใช้งาน"""
    if not (HAS_WINSOUND and cfg.SERVER_SOUND):
        return
    try:
        if status == "CRITICAL":
            for _ in range(3):
                winsound.Beep(2000, 200)
                winsound.Beep(1200, 200)
        elif status == "WARNING":
            for _ in range(2):
                winsound.Beep(900, 250)
                time.sleep(0.1)
    except Exception as e:
        print(f"[Server Sound Error] {e}")


# ==========================================
# การตรวจจับระดับน้ำและการวาด HUD
# ==========================================
def detect_waterline(frame):
    h, w, _ = frame.shape
    roi = frame[:, cfg.POLE_X_MIN:cfg.POLE_X_MAX]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    row_sat = np.mean(sat, axis=1)

    waterline_y = 403
    max_scan_y = min(460, h)
    for y in range(200, max_scan_y):
        if row_sat[y] > 110:
            waterline_y = y

    level_m = 3.00 - ((waterline_y - cfg.Y_300M) / cfg.PIXELS_PER_METER)
    return waterline_y, round(level_m, 2)


def draw_hud(frame, waterline_y, level_m, status):
    annotated = frame.copy()
    h, w, _ = frame.shape

    y_red = int(cfg.Y_300M + (3.00 - cfg.ALERT_RED_LEVEL) * cfg.PIXELS_PER_METER)
    y_orange = int(cfg.Y_300M + (3.00 - cfg.ALERT_ORANGE_LEVEL) * cfg.PIXELS_PER_METER)

    # 1. เส้นขีดเตือนภัย
    cv2.line(annotated, (cfg.POLE_X_MIN - 50, y_red), (cfg.POLE_X_MAX + 150, y_red), (0, 0, 255), 2)
    cv2.putText(annotated, f"CRITICAL: {cfg.ALERT_RED_LEVEL:.2f}m", (cfg.POLE_X_MAX + 160, y_red + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

    cv2.line(annotated, (cfg.POLE_X_MIN - 50, y_orange), (cfg.POLE_X_MAX + 150, y_orange), (0, 165, 255), 2)
    cv2.putText(annotated, f"WARNING: {cfg.ALERT_ORANGE_LEVEL:.2f}m", (cfg.POLE_X_MAX + 160, y_orange + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1, cv2.LINE_AA)

    # 2. เส้นระดับน้ำปัจจุบัน
    water_color = (0, 255, 0) if status == "NORMAL" else ((0, 165, 255) if status == "WARNING" else (0, 0, 255))
    cv2.line(annotated, (cfg.POLE_X_MIN - 40, waterline_y), (cfg.POLE_X_MAX + 80, waterline_y), (0, 255, 255), 2)
    cv2.putText(annotated, f"<-- WATER: {level_m:.2f}m", (cfg.POLE_X_MAX + 85, waterline_y + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2, cv2.LINE_AA)

    # 3. แบนเนอร์แสดงสถานะ
    cv2.rectangle(annotated, (10, 10), (330, 105), (20, 20, 20), -1)
    cv2.rectangle(annotated, (10, 10), (330, 105), water_color, 2)

    status_text = "STATUS: SAFE (NORMAL)"
    if status == "WARNING":
        status_text = "STATUS: WARNING (ORANGE)"
    elif status == "CRITICAL":
        status_text = "STATUS: ALERT (RED CRITICAL)!"

    cv2.putText(annotated, status_text, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.55, water_color, 2, cv2.LINE_AA)
    cv2.putText(annotated, f"WATER LEVEL: {level_m:.2f} M", (20, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(annotated, time.strftime("%Y-%m-%d %H:%M:%S"), (20, 93), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1, cv2.LINE_AA)

    # จุดกะพริบแจ้งเตือน
    if status != "NORMAL" and (int(time.time() * 2) % 2 == 0):
        cv2.circle(annotated, (310, 32), 7, water_color, -1)

    return annotated


def save_snapshot_file(frame, status, level_m, trigger="AUTO"):
    """บันทึก Snapshot และคืนชื่อไฟล์"""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{trigger}_{status}_{level_m:.2f}m_{timestamp}.jpg"
    filepath = cfg.SNAPSHOT_DIR / filename
    cv2.imwrite(str(filepath), frame)
    print(f"[{time.strftime('%H:%M:%S')}] บันทึกภาพแล้ว: {filename}")
    return filename


def capture_single_sample():
    """ดึงภาพสด ณ วินาทีปัจจุบันจาก HLS Stream (รองรับ Serverless บน Vercel)"""
    import urllib.request
    import re
    try:
        # 1. ดึง m3u8 playlist เพื่อหา TS segment ล่าสุด (หลีกเลี่ยงการติดอยู่ที่ segment แรกเมื่อ 1.6 ชม. ก่อน)
        content = urllib.request.urlopen(cfg.STREAM_URL, timeout=3.5).read().decode('utf-8', errors='ignore')
        ts_files = re.findall(r'(\w+\.ts)', content)
        if ts_files:
            latest_ts = ts_files[-1]
            ts_url = f"http://101.109.253.60:8999/{latest_ts}"
        else:
            ts_url = cfg.STREAM_URL

        cap = cv2.VideoCapture(ts_url)
        if not cap.isOpened():
            return None

        # 2. กวาดเฟรมไปข้างหน้าตามเวลาจริงของวินาทีปัจจุบัน (segment ละ ~58 วินาที)
        sec = int(time.time()) % 58
        frames_to_grab = min(sec * 30, 1650)
        for _ in range(frames_to_grab):
            if not cap.grab():
                break
        ret, frame = cap.retrieve()
        if not ret or frame is None:
            # Fallback หาก retrieve ไม่ได้ ให้อ่านเฟรมเริ่มต้นของ segment
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return None

        raw_y, raw_level = detect_waterline(frame)
        status = "NORMAL"
        if raw_level >= cfg.ALERT_RED_LEVEL:
            status = "CRITICAL"
        elif raw_level >= cfg.ALERT_ORANGE_LEVEL:
            status = "WARNING"

        hud = draw_hud(frame, raw_y, raw_level, status)
        with state.lock:
            state.raw_frame = frame.copy()
            state.current_frame = hud
            state.waterline_y = raw_y
            state.water_level = raw_level
            state.status = status
            state.is_connected = True
            state.last_update = time.time()
            state.history.append({
                "ts": time.time(),
                "time": time.strftime("%H:%M:%S"),
                "level": raw_level,
                "status": status
            })
            if len(state.history) > 50:
                state.history.pop(0)
        return frame
    except Exception as e:
        print(f"[Sample Error] {e}")
        return None



# ==========================================
# Video Capture Worker Thread
# ==========================================
def video_worker():
    """เธรดสำหรับดึงและประมวลผลสตรีมวิดีโอตลอดเวลา"""
    print(f"[*] เริ่มต้น Video Worker: {cfg.STREAM_URL}")
    cap = None
    frame_count = 0
    fps_start_time = time.time()
    fps_counter = 0

    while True:
        if cap is None or not cap.isOpened():
            with state.lock:
                state.is_connected = False
            print("[*] กำลังเชื่อมต่อไปยังสตรีมกล้อง...")
            cap = cv2.VideoCapture(cfg.STREAM_URL)
            if not cap.isOpened():
                time.sleep(3)
                continue
            with state.lock:
                state.is_connected = True
            print("[+] เชื่อมต่อสตรีมสำเร็จ!")

        ret, frame = cap.read()
        if not ret:
            print("[-] สตรีมหยุดนิ่ง กำลังเชื่อมต่อใหม่...")
            cap.release()
            cap = None
            with state.lock:
                state.is_connected = False
            time.sleep(2)
            continue

        frame_count += 1
        fps_counter += 1

        # คำนวณ FPS
        if time.time() - fps_start_time >= 1.0:
            with state.lock:
                state.fps = round(fps_counter / (time.time() - fps_start_time), 1)
            fps_counter = 0
            fps_start_time = time.time()

        # ตรวจจับระดับน้ำทุกๆ 5 เฟรม
        if frame_count % 5 == 0:
            raw_y, raw_level = detect_waterline(frame)
            smoothed_y = 0.7 * state.smoothed_y + 0.3 * raw_y
            level_m = round(3.00 - ((smoothed_y - cfg.Y_300M) / cfg.PIXELS_PER_METER), 2)

            if level_m >= cfg.ALERT_RED_LEVEL:
                current_status = "CRITICAL"
            elif level_m >= cfg.ALERT_ORANGE_LEVEL:
                current_status = "WARNING"
            else:
                current_status = "NORMAL"

            now = time.time()

            with state.lock:
                state.waterline_y = int(smoothed_y)
                state.smoothed_y = smoothed_y
                state.water_level = level_m
                prev_status = state.status
                state.status = current_status
                state.last_update = now

                # เก็บประวัติสำหรับกราฟ (เก็บบันทึกทุก 3 วินาที หรือเมื่อสถานะเปลี่ยน)
                if len(state.history) == 0 or (now - state.history[-1].get("ts", 0) >= 3.0):
                    state.history.append({
                        "ts": now,
                        "time": time.strftime("%H:%M:%S"),
                        "level": level_m,
                        "status": current_status
                    })
                    if len(state.history) > 100:  # เก็บไว้ 100 จุดล่าสุด
                        state.history.pop(0)

                # อัปเดตสถิติเตือนภัย
                if current_status in ["WARNING", "CRITICAL"] and prev_status != current_status:
                    state.alert_counts[current_status] = state.alert_counts.get(current_status, 0) + 1

            # เสียงเตือนบน Server (ถ้ามี)
            if current_status in ["WARNING", "CRITICAL"]:
                if now - state.last_alert_time >= 3.0:
                    state.last_alert_time = now
                    threading.Thread(target=play_server_sound, args=(current_status,), daemon=True).start()

                # บันทึกภาพ Snapshot อัตโนมัติ
                status_changed = (current_status != state.last_alert_status and state.last_alert_status == "NORMAL")
                cooldown_passed = (now - state.last_snapshot_time >= cfg.SNAPSHOT_COOLDOWN)
                if status_changed or cooldown_passed:
                    state.last_snapshot_time = now
                    hud_img = draw_hud(frame, int(smoothed_y), level_m, current_status)
                    save_snapshot_file(hud_img, current_status, level_m, trigger="AUTO")

            state.last_alert_status = current_status

        # วาด HUD และเก็บเฟรมล่าสุด
        with state.lock:
            state.raw_frame = frame.copy()
            state.current_frame = draw_hud(frame, int(state.smoothed_y), state.water_level, state.status)

        time.sleep(0.01)  # ป้องกันการใช้ CPU สูงเกินไป


# ==========================================
# Generator สำหรับ MJPEG Stream
# ==========================================
def generate_mjpeg_stream(with_hud=True):
    """ส่งสตรีมภาพ JPEG ต่อเนื่องผ่าน HTTP multipart/x-mixed-replace"""
    while True:
        frame_to_send = None
        with state.lock:
            if with_hud and state.current_frame is not None:
                frame_to_send = state.current_frame.copy()
            elif not with_hud and state.raw_frame is not None:
                frame_to_send = state.raw_frame.copy()

        if frame_to_send is None:
            # ถ้ายังไม่มีภาพ ให้ส่งภาพ placeholder สีดำ
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(placeholder, "CONNECTING TO CCTV STREAM...", (120, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
            _, buffer = cv2.imencode('.jpg', placeholder, [cv2.IMWRITE_JPEG_QUALITY, 75])
        else:
            # บีบอัดเป็น JPEG คุณภาพ 80% เพื่อประสิทธิภาพการส่งข้อมูล
            _, buffer = cv2.imencode('.jpg', frame_to_send, [cv2.IMWRITE_JPEG_QUALITY, 80])

        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.04)  # ~25 FPS


# ==========================================
# Routes & API Endpoints
# ==========================================

@app.route('/')
def index():
    """หน้า Dashboard หลัก"""
    return render_template('index.html')


@app.route('/video_feed')
def video_feed():
    """Endpoint สตรีมวิดีโอสด MJPEG (รองรับ ?overlay=1 หรือ ?overlay=0)"""
    overlay = request.args.get('overlay', '1') == '1'
    return Response(generate_mjpeg_stream(with_hud=overlay),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/frame')
def api_frame():
    """ส่งภาพ JPEG สดล่าสุด 1 เฟรม (พร้อมปิดแคชเบราว์เซอร์และ CDN เพื่อให้ภาพเคลื่อนไหวสดตลอดเวลา)"""
    overlay = request.args.get('overlay', '1') == '1'

    # ในโหมด Vercel Serverless ให้ดึงเฟรมสดตามเวลาจริงเสมอ
    if os.environ.get("VERCEL") or state.current_frame is None or (time.time() - state.last_update > 0.8):
        capture_single_sample()

    frame_to_send = None
    with state.lock:
        if overlay and state.current_frame is not None:
            frame_to_send = state.current_frame.copy()
        elif not overlay and state.raw_frame is not None:
            frame_to_send = state.raw_frame.copy()

    if frame_to_send is not None:
        _, buffer = cv2.imencode('.jpg', frame_to_send, [cv2.IMWRITE_JPEG_QUALITY, 80])
        resp = Response(buffer.tobytes(), mimetype='image/jpeg')
    else:
        placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(placeholder, "CONNECTING TO CCTV STREAM...", (120, 240),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        _, buffer = cv2.imencode('.jpg', placeholder, [cv2.IMWRITE_JPEG_QUALITY, 75])
        resp = Response(buffer.tobytes(), mimetype='image/jpeg')

    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@app.route('/api/status')
def api_status():
    """ส่งข้อมูล Telemetry ระดับน้ำและสถานะปัจจุบันเป็น JSON"""
    if os.environ.get("VERCEL") or state.current_frame is None or (time.time() - state.last_update > 2.0 and not state.is_connected):
        capture_single_sample()

    with state.lock:
        data = {
            "level": state.water_level,
            "status": state.status,
            "waterline_y": state.waterline_y,
            "is_connected": state.is_connected,
            "fps": state.fps,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "history": state.history[-30:],  # ส่ง 30 จุดล่าสุด
            "thresholds": {
                "warning": cfg.ALERT_ORANGE_LEVEL,
                "critical": cfg.ALERT_RED_LEVEL
            },
            "alerts": state.alert_counts
        }
    resp = jsonify(data)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    return resp


@app.route('/api/snapshot/take', methods=['POST'])
def api_take_snapshot():
    """คำสั่งบันทึกภาพ Snapshot ด้วยตนเองจากหน้าเว็บ"""
    with state.lock:
        if state.current_frame is not None:
            filename = save_snapshot_file(state.current_frame, state.status, state.water_level, trigger="WEB_MANUAL")
            return jsonify({"success": True, "filename": filename})
        else:
            return jsonify({"success": False, "message": "ยังไม่มีเฟรมภาพ"}), 400


@app.route('/api/snapshots')
def api_get_snapshots():
    """ดึงรายชื่อภาพ Snapshot ทั้งหมดที่บันทึกไว้"""
    files = []
    for p in sorted(cfg.SNAPSHOT_DIR.glob("*.jpg"), key=os.path.getmtime, reverse=True):
        files.append({
            "filename": p.name,
            "url": f"/snapshots/{p.name}",
            "size": p.stat().st_size,
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
        })
    return jsonify({"snapshots": files[:20]})  # 20 ภาพล่าสุด


@app.route('/snapshots/<path:filename>')
def serve_snapshot(filename):
    """ส่งไฟล์ภาพ Snapshot ที่บันทึกไว้"""
    return send_from_directory(cfg.SNAPSHOT_DIR, filename)


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    """ปรับแต่งเกณฑ์แจ้งเตือน"""
    if request.method == 'POST':
        data = request.json or {}
        if 'warning' in data:
            cfg.ALERT_ORANGE_LEVEL = float(data['warning'])
        if 'critical' in data:
            cfg.ALERT_RED_LEVEL = float(data['critical'])
        return jsonify({"success": True, "warning": cfg.ALERT_ORANGE_LEVEL, "critical": cfg.ALERT_RED_LEVEL})
    return jsonify({
        "stream_url": cfg.STREAM_URL,
        "warning": cfg.ALERT_ORANGE_LEVEL,
        "critical": cfg.ALERT_RED_LEVEL,
        "cooldown": cfg.SNAPSHOT_COOLDOWN
    })


# ==========================================
# เริ่มต้นโปรแกรม
# ==========================================
if __name__ == '__main__':
    # รัน Video Worker ใน Background Thread
    worker_thread = threading.Thread(target=video_worker, daemon=True)
    worker_thread.start()

    print("=" * 60)
    print("  [WEB] WATER LEVEL MONITOR WEB APPLICATION")
    print("  [URL] Open browser at: http://localhost:5000")
    print("  [LAN] Or from mobile on same Wi-Fi: http://<YOUR-IP>:5000")
    print("=" * 60)

    # รัน Flask HTTP Server (threaded=True เพื่อรองรับสตรีมและ API พร้อมกัน)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
