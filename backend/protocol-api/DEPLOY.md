# เอาขึ้นเว็บ (ลิงก์เดียว ข้อมูลถาวร อัปเดตด้วย git push)

## โครงสร้างที่ deploy
เว็บบริการเดียว (FastAPI) เสิร์ฟทั้งหน้าเว็บ (`static/index.html`) และ API ที่โดเมนเดียวกัน
ข้อมูลผู้ใช้/session/ประวัติ เก็บใน Postgres (ผ่าน `DATABASE_URL`) จึงไม่หายตอน deploy ใหม่

## ขั้นตอนครั้งแรก
1. **ฐานข้อมูล (ฟรี):** สมัคร https://neon.tech -> สร้าง Project -> คัดลอก Connection string (`postgresql://...sslmode=require`)
2. **GitHub:** push โฟลเดอร์ `protocol-api` ขึ้น repo (ต้องมี `static/index.html`, `protocol_sdk/`, `requirements.txt`, `render.yaml`) — `users.json`, `attempts.json`, `app.db` ถูกกันไว้ใน `.gitignore` แล้ว
3. **Render:** New + -> Blueprint -> เลือก repo -> ใส่ค่า `DATABASE_URL` ที่คัดลอกมา -> Deploy
4. ได้ลิงก์ `https://trig-simulation.onrender.com` (ชื่อตามที่ตั้ง) ตารางในฐานข้อมูลถูกสร้างอัตโนมัติตอนเริ่มรันครั้งแรก

## อัปเดตโค้ด
`git push` เท่านั้น Render build และสลับเวอร์ชันให้เอง ลิงก์เดิม ผู้ใช้และประวัติยังอยู่

## หน้าเว็บ
แก้ `static/index.html` (ไฟล์เดียวกับที่เคยอยู่ใน `frontend/trig_site-main`) ให้ใช้ไฟล์นี้เป็นต้นฉบับ

## เครื่องที่ต่อบอร์ด STM32
ต้องรัน `serial_bridge.py` บนเครื่องนั้นเอง โดยชี้ไปเว็บจริง:
`set API_URL=https://trig-simulation.onrender.com` แล้ว `python serial_bridge.py`

## รันในเครื่อง (ไม่ต้องมี Postgres)
`pip install -r requirements.txt` แล้ว `uvicorn main:app --reload` เปิด http://localhost:8000
ไม่ตั้ง `DATABASE_URL` จะใช้ SQLite ไฟล์ `app.db`

## รีเซ็ตบัญชีทั้งหมด
`python -c "from db import Database; Database().wipe_users()"` (ตั้ง `DATABASE_URL` ก่อนถ้าจะล้างบนเว็บจริง)