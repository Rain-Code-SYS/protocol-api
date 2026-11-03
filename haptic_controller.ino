#include <SimpleFOC.h>
#include <Encoder.h>

// 1. ตั้งค่า Omron Encoder 2000 P/R (ใช้ Encoder.h อ่านผ่าน PinChangeInterrupt)
Encoder encoderPitch(2, 3); // Encoder ตัวที่ 1: Pitch Angle
Encoder encoderYaw(4, 5);   // Encoder ตัวที่ 2: Yaw Angle (theta1)

const float PULSES_PER_REV = 2000.0 * 4.0; // 2000 P/R Quadrature = 8000 counts/rev

// 2. ตั้งค่า Gimbal Motor GBM2804H-100T (theta2) ผ่าน SimpleFOC
BLDCMotor motor = BLDCMotor(7); // Pole pairs (ปรับตามสเปกจริง)
BLDCDriver3PWM driver = BLDCDriver3PWM(9, 10, 11, 8); // Pins 3PWM + Enable

// Magnetic / Encoder Sensor สำหรับติดตามมุม theta2 ของ Gimbal Motor
MagneticSensorI2C gimbalSensor = MagneticSensorI2C(AS5600_I2C); 

// 3. Touch Sensor & Brake Pins
const int TOUCH_SENSOR_PIN = 6;
const int BRAKE_PITCH_PIN  = 12;
const int BRAKE_YAW_PIN    = 13;

// ตัวแปรควบคุมจาก Trig Protocol 3 (Ki;Kv;bp;by)
float Ki = 0.0;
float Kv = 0.0;
int bp = 1; // เริ่มต้นให้ล็อกเบรกไว้ก่อน (สัมผัส = 0)
int by = 1;

unsigned long last_send_time = 0;
const unsigned long SEND_INTERVAL_MS = 20; // 50 Hz

void setup() {
  Serial.begin(115200);

  pinMode(TOUCH_SENSOR_PIN, INPUT_PULLUP);
  pinMode(BRAKE_PITCH_PIN, OUTPUT);
  pinMode(BRAKE_YAW_PIN, OUTPUT);

  // SimpleFOC Init
  gimbalSensor.init();
  motor.linkSensor(&gimbalSensor);
  driver.voltage_power_supply = 12.0;
  driver.init();
  motor.linkDriver(&driver);
  motor.controller = MotionControlType::torque;
  motor.init();
  motor.initFOC();
}

void loop() {
  motor.loopFOC();

  // 1. อ่านค่าจาก Touch Sensor
  int touch_val = digitalRead(TOUCH_SENSOR_PIN);
  
  // เงื่อนไขตามสเปก: Touch = 0 (ไม่สัมผัส) -> bp=1, by=1 | Touch = 1 (สัมผัส) -> bp=0, by=0
  if (touch_val == 0) {
    bp = 1;
    by = 1;
  } else {
    bp = 0;
    by = 0;
  }

  // 2. รับคำสั่ง Trig Protocol 3 (Ki;Kv;bp;by) จาก Python
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    if (input.length() > 0) {
      parseTrigProtocol3(input);
    }
  }

  // ส่งแรงบิดไปยัง Gimbal Motor
  motor.move(Ki);

  // ควบคุมสถานะ เบรก
  digitalWrite(BRAKE_PITCH_PIN, bp ? HIGH : LOW);
  digitalWrite(BRAKE_YAW_PIN, by ? HIGH : LOW);

  // 3. ส่ง Telemetry (Trig Protocol 2) ออกทาง Serial ทุกๆ 20ms
  if (millis() - last_send_time >= SEND_INTERVAL_MS) {
    last_send_time = millis();
    sendTrigProtocol2(touch_val);
  }
}

void sendTrigProtocol2(int touch_status) {
  // คำนวณมุม Pitch และ Yaw (theta1) เป็น องศา
  float pitch = (encoderPitch.read() / PULSES_PER_REV) * 360.0;
  float yaw   = (encoderYaw.read() / PULSES_PER_REV) * 360.0; // theta1

  // อ่านมุมหมุน theta2 ของ Gimbal Motor (แปลงเป็นองศา ช่วง 0 - 60 deg)
  float theta2 = gimbalSensor.getAngle() * (180.0 / M_PI);

  // ส่งฟอร์แมต: pitch;yaw;theta2;touch
  Serial.print(pitch, 2);   Serial.print(";");
  Serial.print(yaw, 2);     Serial.print(";");
  Serial.print(theta2, 2);  Serial.print(";");
  Serial.println(touch_status);
}

void parseTrigProtocol3(String data) {
  int f1 = data.indexOf(';');
  int f2 = data.indexOf(';', f1 + 1);
  int f3 = data.indexOf(';', f2 + 1);

  if (f1 != -1 && f2 != -1 && f3 != -1) {
    Ki = data.substring(0, f1).toFloat();
    Kv = data.substring(f1 + 1, f2).toFloat();
    // bp และ by ถูกคุมด้วย Touch Sensor ใน Loop หรืออัปเดตจากคำสั่ง
  }
}