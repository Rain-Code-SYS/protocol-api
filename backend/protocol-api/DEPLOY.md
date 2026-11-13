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

## ใช้เข็มกับหน้า Simulation (แต่ละคนต่อบอร์ดเข้าคอมตัวเอง)
- เปิดเว็บด้วย **Chrome หรือ Edge บนคอมพิวเตอร์** (Firefox/Safari/มือถือไม่รองรับ Web Serial) ต้องเป็น HTTPS หรือ localhost
- ล็อกอิน -> Settings -> ตั้ง Encoder/PPR -> กด Connect -> เลือกพอร์ตของบอร์ด STM32 ในหน้าต่างที่เบราว์เซอร์เปิดให้ -> Set Zero -> ไปหน้า Simulation
- เบราว์เซอร์อ่านบอร์ดเอง (230400 baud) แล้วส่งค่าขึ้นเว็บประมาณ 20 ครั้ง/วินาที ค่า raw, PPR และ offset แยกตามบัญชี ไม่ปนกัน (PPR/offset เก็บถาวรในฐานข้อมูล)
- ต้องปิดโปรแกรมอื่นที่เปิดพอร์ตนั้นอยู่ (เช่น `serial_bridge.py`, Arduino Serial Monitor) ไม่งั้นเปิดพอร์ตไม่ได้
- **แรงสะท้อนกลับ (Ki;Kv ส่งกลับบอร์ด):** ติ๊ก Force Feedback ในหน้า Simulation (ต้อง Connect บอร์ดก่อน) เบราว์เซอร์จะคำนวณแรงเองด้วย `static/haptic_model.js` แล้วเขียนคำสั่ง `Ki;Kv;bp;by` กลับบอร์ดผ่านพอร์ตเดียวกันทันทีที่อ่านตัวอย่างได้ ไม่ผ่านเซิร์ฟเวอร์ จึงไม่ขึ้นกับความเร็วอินเทอร์เน็ต ท่าเข็มบนหน้าจอก็คำนวณในเครื่องเช่นกัน
  - ถ้าบอร์ดรับช้ากว่าสตรีม ระบบส่งเฉพาะคำสั่งล่าสุด คิวไม่สะสม
  - ปิดติ๊ก Force Feedback / ออกจากหน้า Simulation / ตัดการเชื่อมต่อ = ส่งคำสั่งปล่อยแรง `0.0;0.5;1;1` (Ki=0, ปลดล็อก) ก่อน
  - ไม่ต้องรัน `serial_bridge.py` อีก (และห้ามรันพร้อมกัน เพราะแย่งพอร์ต)
  - สูตรแรงต้องตรงกับ `tissue_model.py`: แก้สูตรแล้วรัน `python -m tests.gen_haptic_vectors` และ `node --test` เพื่อเทียบ Python กับ JS

## รันในเครื่อง (ไม่ต้องมี Postgres)
`pip install -r requirements.txt` แล้ว `uvicorn main:app --reload` เปิด http://localhost:8000
ไม่ตั้ง `DATABASE_URL` จะใช้ SQLite ไฟล์ `app.db`

## รีเซ็ตบัญชีทั้งหมด
`python -c "from db import Database; Database().wipe_users()"` (ตั้ง `DATABASE_URL` ก่อนถ้าจะล้างบนเว็บจริง)