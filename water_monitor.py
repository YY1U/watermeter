"""
ระบบตรวจจับระดับน้ำอัตโนมัติจากกล้อง CCTV (เทศบาลเมืองปทุมธานี)
พร้อมระบบแจ้งเตือนเสียง (Sound Alert) เมื่อระดับน้ำถึงเกณฑ์สีเหลืองหรือสีแดง

ฟีเจอร์หลัก:
1. ดึงภาพสตรีมสดจากกล้อง HLS (m3u8) แบบเรียลไทม์ และ Reconnect อัตโนมัติเมื่อหลุด
2. ตรวจจับระดับผิวน้ำ (Waterline Detection) เทียบกับสเกลเสาวัดระดับจริง
3. แสดงผลหน้าจอ Live HUD แสดงขีดระดับน้ำ, สถานะ, และเวลาปัจจุบัน
4. ระบบเสียงเตือน (Sound Alert) ผ่านลำโพงคอมพิวเตอร์ (Windows winsound / Win32 API):
   - เกณฑ์สีส้ม/เหลือง (>= 2.20 ม.): เสียงเตือน Beep / EAS Alert (Warning)
   - เกณฑ์สีแดง (>= 2.50 ม.): เสียงไซเรนฉุกเฉิน (Critical Alert)
5. บันทึกภาพ Snapshot อัตโนมัติเมื่อเกิดเหตุการณ์แจ้งเตือนลงโฟลเดอร์ snapshots/
"""

import cv2
import numpy as np
import time
import threading
import sys
import os
from pathlib import Path

# สำหรับเสียงเตือนบน Windows
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# นำเข้า Win32 API สำหรับเร่งเสียงระบบ Windows อัตโนมัติ
try:
    import ctypes
    HAS_CTYPES = True
except ImportError:
    HAS_CTYPES = False

# ==========================================
# การตั้งค่าระบบ (Configuration)
# ==========================================
STREAM_URL = "http://101.109.253.60:8999/playlist.m3u8"

# พิกัดเสาวัดระดับน้ำ (แกน X บนภาพ 640x480)
POLE_X_MIN = 286
POLE_X_MAX = 308

# ตำแหน่งอ้างอิงของระดับน้ำ (แกน Y)
Y_300M = 230               # พิกัด Y ที่ระดับ 3.00 เมตร
PIXELS_PER_METER = 176.0   # สเกลความสูง 1 เมตร = ~176 พิกเซล

# ระดับเกณฑ์แจ้งเตือน (เมตร)
ALERT_ORANGE_LEVEL = 2.20  # ลูกศรสีส้ม/เหลือง (ระดับเฝ้าระวัง ~2.20 ม.)
ALERT_RED_LEVEL = 2.50     # ลูกศรสีแดง (ระดับวิกฤต ~2.50 ม.)

# พิกัด Y ของขีดเตือนภัย
Y_RED_ARROW = int(Y_300M + (3.00 - ALERT_RED_LEVEL) * PIXELS_PER_METER)       # ประมาณ Y=318
Y_ORANGE_ARROW = int(Y_300M + (3.00 - ALERT_ORANGE_LEVEL) * PIXELS_PER_METER) # ประมาณ Y=371

# การหน่วงเวลาเสียงเตือน (วินาที เพื่อไม่ให้เสียงดังถี่จนเกินไป)
ALERT_SOUND_INTERVAL = 3.0
last_alert_time = 0

# การตั้งค่าบันทึกภาพ Snapshot
SNAPSHOT_DIR = Path("snapshots")
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOT_COOLDOWN = 15.0   # ถ่ายภาพเตือนภัยอัตโนมัติห่างกันอย่างน้อย 15 วินาที
last_snapshot_time = 0
last_alert_status = "NORMAL"

# ตัวแปรสถานะการทำงาน
current_status = "NORMAL"  # NORMAL, WARNING, CRITICAL
current_level_m = 2.00
is_running = True


def maximize_system_volume():
    """เร่งเสียง Master Volume ของ Windows ขึ้นสูงสุดและเปิดเสียง (Unmute) อัตโนมัติ"""
    if not HAS_CTYPES:
        return
    try:
        VK_VOLUME_UP = 0xAF
        for _ in range(25):
            ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 2, 0)
    except Exception:
        pass


def play_alert_sound(status):
    """ฟังก์ชันเล่นเสียงเตือนระดับสูง ใน Background Thread"""
    if not HAS_WINSOUND:
        return

    maximize_system_volume()
    try:
        if status == "CRITICAL":
            # เสียงหวูดไซเรนอพยพน้ำท่วม (Air Raid / Evacuation Siren)
            if os.path.exists("loud_siren.wav"):
                winsound.PlaySound("loud_siren.wav", winsound.SND_FILENAME)
            else:
                for _ in range(4):
                    winsound.Beep(2000, 200)
                    winsound.Beep(1200, 200)
        elif status == "WARNING":
            # เสียงเตือนภัยฉุกเฉิน EAS Alert Tone
            if os.path.exists("eas_alarm.wav"):
                winsound.PlaySound("eas_alarm.wav", winsound.SND_FILENAME)
            else:
                for _ in range(2):
                    winsound.Beep(900, 300)
                    time.sleep(0.1)
    except Exception as e:
        print(f"[Sound Error] {e}")


def save_snapshot(frame, status, level_m, trigger_type="AUTO"):
    """บันทึกภาพ Snapshot ลงโฟลเดอร์ snapshots/ พร้อมป้ายกำกับ"""
    try:
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        filename = SNAPSHOT_DIR / f"{trigger_type}_{status}_{level_m:.2f}m_{timestamp_str}.jpg"
        cv2.imwrite(str(filename), frame)
        print(f"[{time.strftime('%H:%M:%S')}] [SNAPSHOT] บันทึกภาพแล้ว: {filename}")
        return str(filename)
    except Exception as e:
        print(f"[Snapshot Error] {e}")
        return None


def detect_waterline(frame):
    """
    ตรวจจับตำแหน่งผิวน้ำที่ตัดกับเสาสีเหลือง
    ใช้เทคนิค Saturation + Contrast Drop ระหว่างตัวเสาในอากาศกับใต้น้ำ
    คืนค่า: waterline_y (พิกัด Y บนภาพ) และระดับน้ำเป็นเมตร
    """
    h, w, _ = frame.shape
    roi = frame[:, POLE_X_MIN:POLE_X_MAX]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    row_sat = np.mean(sat, axis=1)

    # กวาดจากบนลงล่าง เพื่อหาจุดสุดท้ายที่เสายังโผล่พ้นน้ำ
    waterline_y = 403
    max_scan_y = min(460, h)
    for y in range(200, max_scan_y):
        if row_sat[y] > 110:
            waterline_y = y

    # แปลงพิกัด Y เป็นระดับความสูงน้ำจริง (หน่วยเมตร)
    level_m = 3.00 - ((waterline_y - Y_300M) / PIXELS_PER_METER)
    level_m = round(level_m, 2)
    return waterline_y, level_m


def draw_hud(frame, waterline_y, level_m, status):
    """วาดกราฟิกและสถานะเตือนภัยลงบนภาพ"""
    annotated = frame.copy()
    h, w, _ = frame.shape

    # 1. วาดเส้นอ้างอิงระดับต่างๆ
    # ขีดสีแดง (ระดับวิกฤต 2.50 ม.)
    cv2.line(annotated, (POLE_X_MIN - 50, Y_RED_ARROW), (POLE_X_MAX + 150, Y_RED_ARROW), (0, 0, 255), 2)
    cv2.putText(annotated, f"CRITICAL: {ALERT_RED_LEVEL:.2f}m", (POLE_X_MAX + 160, Y_RED_ARROW + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)

    # ขีดสีส้ม (ระดับเฝ้าระวัง 2.20 ม.)
    cv2.line(annotated, (POLE_X_MIN - 50, Y_ORANGE_ARROW), (POLE_X_MAX + 150, Y_ORANGE_ARROW), (0, 165, 255), 2)
    cv2.putText(annotated, f"WARNING: {ALERT_ORANGE_LEVEL:.2f}m", (POLE_X_MAX + 160, Y_ORANGE_ARROW + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1, cv2.LINE_AA)

    # ขีดระดับผิวน้ำปัจจุบัน (Detected Waterline)
    water_color = (0, 255, 0) if status == "NORMAL" else ((0, 165, 255) if status == "WARNING" else (0, 0, 255))
    cv2.line(annotated, (POLE_X_MIN - 40, waterline_y), (POLE_X_MAX + 80, waterline_y), (0, 255, 255), 2)
    cv2.putText(annotated, f"<-- WATER: {level_m:.2f}m", (POLE_X_MAX + 85, waterline_y + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2, cv2.LINE_AA)

    # 2. แถบป้ายแสดงผลสถานะด้านบน (Dashboard Banner)
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

    # จุดไฟกะพริบแจ้งเตือนเมื่อไม่ใช่ NORMAL
    if status != "NORMAL" and (int(time.time() * 2) % 2 == 0):
        cv2.circle(annotated, (310, 32), 7, water_color, -1)

    return annotated


def main():
    global last_alert_time, last_snapshot_time, last_alert_status
    global current_status, current_level_m

    print("=" * 65)
    print(" ระบบตรวจจับระดับน้ำและเตือนภัยอัตโนมัติ (เทศบาลเมืองปทุมธานี)")
    print(f" สตรีม: {STREAM_URL}")
    print(f" เกณฑ์สีส้ม/เหลือง (เฝ้าระวัง): >= {ALERT_ORANGE_LEVEL:.2f} ม.")
    print(f" เกณฑ์สีแดง (วิกฤต): >= {ALERT_RED_LEVEL:.2f} ม.")
    print("=" * 65)
    print(" [ปุ่มควบคุม]")
    print("  't' หรือ 'w' : ทดสอบเสียงเตือนสีส้ม (Warning)")
    print("  'c'         : ทดสอบเสียงไซเรนสีแดง (Critical)")
    print("  's'         : บันทึกภาพ Snapshot ด้วยตนเอง")
    print("  'q'         : ออกจากโปรแกรม")
    print("=" * 65)

    cap = cv2.VideoCapture(STREAM_URL)
    if not cap.isOpened():
        print("[ข้อผิดพลาด] ไม่สามารถเชื่อมต่อสตรีมกล้องได้ กรุณาตรวจสอบ URL หรือการเชื่อมต่อเครือข่าย")
        return

    frame_count = 0
    smoothed_y = 405.0
    annotated_frame = None

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[เชื่อมต่อใหม่] สตรีมหยุดชั่วคราว กำลังเชื่อมต่อใหม่...")
            cap.release()
            time.sleep(2)
            cap = cv2.VideoCapture(STREAM_URL)
            continue

        frame_count += 1

        # ตรวจจับทุกๆ 5 เฟรมเพื่อความลื่นไหลและประหยัดทรัพยากร
        if frame_count % 5 == 0:
            raw_y, raw_level = detect_waterline(frame)

            # ตัวกรอง Exponential Moving Average (EMA) เพื่อให้เส้นระดับน้ำนิ่ง ไม่สั่นจากคลื่นน้ำ
            smoothed_y = 0.7 * smoothed_y + 0.3 * raw_y
            current_level_m = round(3.00 - ((smoothed_y - Y_300M) / PIXELS_PER_METER), 2)

            # กำหนดระดับสถานะ
            if current_level_m >= ALERT_RED_LEVEL:
                current_status = "CRITICAL"
            elif current_level_m >= ALERT_ORANGE_LEVEL:
                current_status = "WARNING"
            else:
                current_status = "NORMAL"

            # ตรวจสอบการส่งเสียงเตือนและการบันทึก Snapshot
            current_time = time.time()
            if current_status in ["WARNING", "CRITICAL"]:
                # ตรวจสอบเสียงเตือน
                if current_time - last_alert_time >= ALERT_SOUND_INTERVAL:
                    last_alert_time = current_time
                    print(f"[{time.strftime('%H:%M:%S')}] แจ้งเตือน: {current_status} | ระดับน้ำ: {current_level_m:.2f} ม.")
                    threading.Thread(target=play_alert_sound, args=(current_status,), daemon=True).start()

                # บันทึกภาพ Snapshot อัตโนมัติเมื่อสถานะเปลี่ยนเป็นเตือนภัย หรือพ้นระยะ Cooldown
                status_changed = (current_status != last_alert_status and last_alert_status == "NORMAL")
                cooldown_passed = (current_time - last_snapshot_time >= SNAPSHOT_COOLDOWN)

                if status_changed or cooldown_passed:
                    last_snapshot_time = current_time
                    preview_annotated = draw_hud(frame, int(smoothed_y), current_level_m, current_status)
                    save_snapshot(preview_annotated, current_status, current_level_m, trigger_type="ALERT")

            last_alert_status = current_status

        # วาดหน้าจอ HUD
        annotated_frame = draw_hud(frame, int(smoothed_y), current_level_m, current_status)

        # แสดงภาพหน้าต่าง OpenCV
        cv2.imshow("Water Level Monitor - Pathumthani", annotated_frame)

        # จัดการปุ่มกดควบคุม
        key = cv2.waitKey(20) & 0xFF
        if key == ord('q'):
            break
        elif key in (ord('t'), ord('w')):
            print("[ทดสอบ] เล่นเสียงเตือนระดับสีส้ม (Warning)")
            threading.Thread(target=play_alert_sound, args=("WARNING",), daemon=True).start()
        elif key == ord('c'):
            print("[ทดสอบ] เล่นเสียงไซเรนระดับวิกฤต (Critical)")
            threading.Thread(target=play_alert_sound, args=("CRITICAL",), daemon=True).start()
        elif key == ord('s') and annotated_frame is not None:
            save_snapshot(annotated_frame, current_status, current_level_m, trigger_type="MANUAL")

    cap.release()
    cv2.destroyAllWindows()
    print("ปิดระบบเรียบร้อยแล้ว")


if __name__ == "__main__":
    main()
