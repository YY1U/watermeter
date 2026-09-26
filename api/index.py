"""
Vercel Serverless Functions Entrypoint
"""

import sys
import os
from pathlib import Path

# เพิ่มไดเรกทอรีรากเข้าสู่ sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# ตั้งค่าสถานะ VERCEL environment variable
os.environ["VERCEL"] = "1"

# นำเข้า WSGI Flask app
from app import app

# Vercel มองหาตัวแปร app เป็น WSGI callable
# app.debug = False
