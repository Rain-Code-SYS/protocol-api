# Simulation Setup UI (Thoracentesis / Paracentesis / Pericardiocentesis)

เว็บ UI ของส่วน **Simulation Software 2 (UI + API + User Tracking)** ในโปรเจกต์เข็มจำลอง
ผู้เรียนเลือกหัตถการ ตั้งค่าเคส แล้วกด Start ระบบจะแปลงค่าเป็นเลข INT (Trig Protocol 1) และส่งไปที่ฝั่ง Python

## ไฟล์
| ไฟล์ | หน้าที่ |
|---|---|
| `index.html` | หน้าเว็บทั้งหมดในไฟล์เดียว (Dashboard, Simulation setup, History & Analytics, Settings) |
| `server.py` | เซิร์ฟเวอร์ Flask: เปิดหน้าเว็บ และรับค่าที่ `POST /api/trig1` |
| `requirements.txt` | ไลบรารีที่ต้องติดตั้ง (flask, gunicorn) |

## วิธีรัน (Windows)
1. ดาวน์โหลดโปรเจกต์ (ปุ่ม Code > Download ZIP หรือ `git clone`) แล้วแตกไฟล์
   **ไฟล์ `index.html`, `server.py` และ `requirements.txt` ต้องอยู่ในโฟลเดอร์เดียวกัน** เพราะ `server.py` เปิดหน้าเว็บจาก `index.html` ที่อยู่ข้างกัน
   (ถ้าโหลดมาทั้งโปรเจกต์ ไฟล์จะอยู่รวมกันอยู่แล้ว ต้องระวังเฉพาะตอนโหลดทีละไฟล์)
2. ติดตั้ง Python 3.10 ขึ้นไป (ติ๊ก Add python.exe to PATH ตอนติดตั้ง)
3. เปิด Terminal ในโฟลเดอร์ที่มีไฟล์เหล่านั้น แล้วพิมพ์ `pip install -r requirements.txt`
4. พิมพ์ `python server.py`
5. เปิดเบราว์เซอร์ที่ `http://localhost:5000`
6. ถ้าอยากดูหน้า History พร้อมข้อมูลตัวอย่าง ให้พิมพ์ที่อยู่เว็บเป็น `http://localhost:5000/#history-demo`
   (ข้อมูลนี้เขียนขึ้นเพื่อดูหน้าตา ไม่ใช่ผลของผู้เรียนจริง และจะมีแถบ "Sample data" แจ้งไว้ ถ้ากดแท็บ History ตามปกติ หน้าจะว่างเปล่าจนกว่าจะมีข้อมูลจริง)

## Trig Protocol (1): INT 7 บิต
รูปแบบ `0b AA DD C MM`

| ฟิลด์ | บิต | ค่า |
|---|---|---|
| Age (AA) | 2 | 0 Pediatric, 1 Adult, 2 Geriatric |
| Difficulty (DD) | 2 | 0 Easy, 1 Medium, 2 Hard |
| Case type (C) | 1 | 0 Basic, 1 Emergency/Trauma |
| Training mode (MM) | 2 | 0 Tutorial, 1 Guide, 2 Blind |

ตัวอย่าง: Adult, Medium, Basic, Guide = `0b0101001` = 41
หน้าเว็บส่ง `{"value": 41, "procedure": "thoracentesis"}` ไปที่ `/api/trig1` และ `server.py` แกะค่ากลับด้วย `decode_trig1()`
ค่า INT ไม่แสดงบนหน้าจอผู้ใช้ (เก็บไว้ฝั่งหลังบ้านเท่านั้น)

## หน้าเว็บ
- `#dashboard` เลือกหัตถการ: กดการ์ดเพื่อเลือก แล้วกด Start Modules
- `#thoracentesis` `#paracentesis` `#pericardiocentesis` หน้าตั้งค่าเคส
- `#history` หน้าประวัติ (ตอนนี้ว่าง) และ `#history-demo` ดูข้อมูลตัวอย่างเพื่อดูหน้าตา
- `#settings` สลับภาษาไทย/อังกฤษ และโหมดสว่าง/มืด (เก็บใน localStorage ของเบราว์เซอร์)

## สิ่งที่ยังต้องทำต่อ
- `server.py` แกะค่าแล้วแค่พิมพ์ออกหน้าจอ ยังไม่ได้เก็บหรือส่งต่อให้ 3D Simulation
- Trig Protocol (1) ยังไม่มีฟิลด์หัตถการ (ตอนนี้ส่ง `procedure` แยกต่างหาก) ต้องตกลงกับทีม
- หน้า History ยังไม่มีข้อมูลจริง ใช้ `setHistoryData(list)` ใน `index.html` เพื่อใส่ข้อมูล รูปแบบข้อมูลอยู่ในคอมเมนต์ของโค้ด
- เกณฑ์ผ่าน (`PASS_SCORE = 80`) เป็นค่าชั่วคราว ทีมยังไม่ได้ตกลง
- แท็บ Modules และปุ่ม View ในตารางประวัติยังกดไม่ได้
- หลังกด Start ยังไม่ได้ต่อไปหน้าจำลองหรือหน้าประเมินผล
- ยังไม่ได้ทดสอบบนหลายเบราว์เซอร์

## เครดิต
ไอคอนโหมดฝึกมาจาก Material Design Icons (Pictogrammers) ใบอนุญาต Apache 2.0
