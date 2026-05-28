import machine
import dht
import time
import network
import uasyncio as asyncio
from umqtt.simple import MQTTClient
import urequests

# --- 1. إعدادات الشبكة والتحديث اللاسلكي (OTA) ---
WIFI_SSID = "Sherif"
WIFI_PASSWORD = "@987654321@"

# 📡 رابط مستودع GitHub الخاص بك لسحب الكود لاسلكياً
OTA_URL = "https://githubusercontent.com"

# 🔑 تم وضع الـ App Key وبيانات السيرفر الخاصة بك هنا بدقة
APP_KEY = "be86-4542-88d5-29d7ae11fc48"
MQTT_SERVER = "iot.sinric.pro"
MQTT_PORT = 1883
MQTT_USER = APP_KEY

# 🆔 تم إدراج الـ Device IDs الجديدة المأخوذة من صورتك هنا
RELAY_DEVICE_IDS = [
    "6a178eef9b5f15fa7e19a99", 
    "6a178a96977a0619a74bc1a2", 
    "ID_RELAY_3", 
    "ID_RELAY_4",
    "ID_RELAY_5", 
    "ID_RELAY_6", 
    "ID_RELAY_7", 
    "ID_RELAY_8"
]
THERMOSTAT_DEVICE_ID = "6a178c13f9b5f15fa7e19c09R"

# --- 2. إعدادات الدبابيس والمتغيرات ---
DHT_PIN = 14

# دبابيس الـ 8 ريلاي المتاحة في لوحة ESP32 (قم بتغيير الأرقام حسب توصيلك الفعلي)
relay_pins = [15, 2, 4, 5, 18, 19, 21, 22]

# دبابيس محرك الاستيبر
step_pins = [
    machine.Pin(25, machine.Pin.OUT),  # IN1
    machine.Pin(26, machine.Pin.OUT),  # IN2
    machine.Pin(27, machine.Pin.OUT),  # IN3
    machine.Pin(13, machine.Pin.OUT)   # IN4
]

# --- 3. متغيرات النظام العامة وتتابع الحركة ---
TEMP_THRESHOLD = 30.0
stepper_status = "متوقف 🛑"
current_temp = 0.0
current_hum = 0.0

step_sequence = [
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1]
]

# تهيئة ريلايات النظام وإطفائها بالكامل في البداية
relays = [machine.Pin(pin, machine.Pin.OUT) for pin in relay_pins]
for r in relays: 
    r.value(0)

# --- 4. دوال التحكم بالمحرك والإعدادات ---

async def move_stepper_async(steps_count):
    global stepper_status
    stepper_status = "يعمل الآن دوران تلقائي ⚙️"
    for _ in range(steps_count):
        for step in step_sequence:
            for pin, value in zip(step_pins, step):
                pin.value(value)
            await asyncio.sleep_ms(3)
    for pin in step_pins: 
        pin.value(0)
    stepper_status = "متوقف (درجة الحرارة طبيعية) 🛑"

async def on_setting(setting: str, value) -> bool:
    global TEMP_THRESHOLD
    if setting in ["range", "targetTemperature"]:
        TEMP_THRESHOLD = float(value)
        print(f"🔥 تم تحديث الحد الحراري بنجاح إلى: {TEMP_THRESHOLD} °C")
        return True
    return True

def mqtt_callback(topic, msg):
    global relays
    topic_str = topic.decode()
    msg_str = msg.decode()
    
    for idx, device_id in enumerate(RELAY_DEVICE_IDS):
        if device_id in topic_str:
            if "On" in msg_str or "true" in msg_str:
                relays[idx].value(1)
            elif "Off" in msg_str or "false" in msg_str:
                relays[idx].value(0)

# --- 5. المهام الخلفية غير المتزامنة (Background Tasks) ---

async def sensors_loop(client):
    global current_temp, current_hum
    sns = dht.DHT11(machine.Pin(DHT_PIN))
    
    while True:
        try:
            sns.measure()
            current_temp = sns.temperature()
            current_hum = sns.humidity()
            
            if current_temp >= TEMP_THRESHOLD:
                asyncio.create_task(move_stepper_async(50))
            
            payload = f'{{"temperature":{current_temp},"humidity":{current_hum}}}'
            client.publish(f"stat/{THERMOSTAT_DEVICE_ID}/temperature", payload)
            
        except Exception as e:
            print("⚠️ خطأ في قراءة مستشعر DHT11 أو في إرسال البيانات")
        
        await asyncio.sleep(10)

async def mqtt_loop(client):
    while True:
        try:
            client.check_msg()
        except:
            pass
        await asyncio.sleep_ms(50)

def build_html_page():
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>نظام شريف الذكي</title>
    <style>body{{font-family:Arial;text-align:center;direction:rtl;background:#f4f7f6;padding:20px;}}</style></head><body>
    <h1>🌐 نظام التحكم اللاسلكي المحدث (nasherty)</h1>
    <p>🔥 الحرارة الحالية: {current_temp} °C | 💧 الرطوبة: {current_hum} %</p>
    <p>حد تشغيل المحرك المستهدف: {TEMP_THRESHOLD} °C | الحالة: {stepper_status}</p>
    </body></html>"""

async def handle_http_request(reader, writer):
    try:
        await reader.read(1024)
        response = "HTTP/1.1 200 OK\nContent-Type: text/html; charset=utf-8\nConnection: close\n\n" + build_html_page()
        writer.write(response.encode('utf-8'))
        await writer.drain()
    except:
        pass
    finally:
        writer.close()
        await writer.wait_closed()

# --- 6. الدالة الرئيسية للمشروع ---
async def main():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    while not wlan.isconnected(): 
        await asyncio.sleep(0.5)
    print(f"✅ متصل بالشبكة المحلية! الرابط: http://{wlan.ifconfig()[0]}")
    
    await check_for_ota_update()
    
    client = MQTTClient("ESP32_Sherif", MQTT_SERVER, port=MQTT_PORT, user=APP_KEY, password="")
    client.set_callback(mqtt_callback)
    try:
        client.connect()
        for device_id in RELAY_DEVICE_IDS: 
            client.subscribe(f"cmd/{device_id}/setPowerState")
        print("☁️ تم الربط مع منصة SinricPro بنجاح!")
    except Exception as e:
        print("⚠️ ثمة مشكلة في الاتصال بالسيرفر السحابي")

    await asyncio.start_server(handle_http_request, '0.0.0.0', 80)

    await asyncio.gather(
        mqtt_loop(client),
        sensors_loop(client)
    )

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("تم إيقاف النظام يدويًا.")
