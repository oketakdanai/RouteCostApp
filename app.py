import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Route Cost", layout="wide")

# ==========================================
# 🧠 1. ส่วนบริหารจัดการความจำ
# ==========================================
for key in ['calculated', 'distance', 'route_coords', 'start_coords', 'end_coords', 'pin_start', 'pin_end', 'map_mode_active', 'active_pin_to_set', 'origin_text', 'dest_text']:
    if key not in st.session_state:
        st.session_state[key] = False if 'active' in key or 'calculated' in key else None
if st.session_state.origin_text is None: st.session_state.origin_text = ""
if st.session_state.dest_text is None: st.session_state.dest_text = ""

def reset_calculated_data():
    st.session_state.calculated = False
    st.session_state.distance = st.session_state.route_coords = None

# ==========================================
# 📦 2. ดึงข้อมูลรถจากไฟล์ CSV (ง่ายกว่าเดิมเยอะ!)
# ==========================================
@st.cache_data(ttl=600)
def get_car_data():
    try:
        # อ่านไฟล์ชื่อ cars.csv ที่อยู่ในห้องเดียวกับ app.py
        return pd.read_csv("cars.csv")
    except:
        # ถ้าหาไฟล์ไม่เจอ ให้ใช้ข้อมูลตัวอย่างไปก่อน
        return pd.DataFrame({
            "รุ่นรถ": ["ตัวอย่าง: Honda CR-V"],
            "ประเภทน้ำมัน": ["แก๊สโซฮอล์ 95"],
            "อัตราสิ้นเปลือง (กม./ลิตร)": [12.0]
        })

df_cars = get_car_data()

# ==========================================
# ⛽ 3. ราคาน้ำมัน (ใช้ API เดิม)
# ==========================================
@st.cache_data(ttl=3600) 
def get_live_oil_prices():
    try:
        res = requests.get("https://thai-oil-api.vercel.app/latest").json()
        stations = res['response']['stations']
        data = {s: {f: i['price'] for f, i in fuels.items() if isinstance(i, dict)} for s, fuels in stations.items()}
        df = pd.DataFrame(data).apply(pd.to_numeric, errors='coerce')
        df['Average'] = df.mean(axis=1).round(2)
        return df.fillna(0)
    except: return None

df_prices = get_live_oil_prices()
FUEL_MAP = {"เบนซิน": "gasoline_95", "แก๊สโซฮอล์ 95": "gasohol_95", "แก๊สโซฮอล์ 91": "gasohol_91", "E20": "gasohol_e20", "E85": "gasohol_e85", "Diesel B7": "diesel", "ดีเซล": "diesel", "ดีเซล B7": "diesel", "Premium Diesel": "premium_diesel"}

# ==========================================
# 🗺️ 4. ฟังก์ชันแผนที่
# ==========================================
def get_place_name(lat, lon):
    try:
        res = requests.get(f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=th", headers={'User-Agent': 'RouteApp/4.0'}).json()
        return ", ".join(res.get("display_name", "").split(", ")[:3])
    except: return f"{lat:.4f}, {lon:.4f}"

# ==========================================
# 🎨 5. หน้าตาโปรแกรม
# ==========================================
st.title("📍 Route Cost Calculator")
col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("รายละเอียดการเดินทาง")
    origin = st.text_input("จุดเริ่มต้น", value=st.session_state.origin_text)
    destination = st.text_input("จุดหมายปลายทาง", value=st.session_state.dest_text)
    
    if origin != st.session_state.origin_text: st.session_state.origin_text = origin; reset_calculated_data()
    if destination != st.session_state.dest_text: st.session_state.dest_text = destination; reset_calculated_data()

    if not st.session_state.map_mode_active:
        if st.button("🗺️ เลือกจากแผนที่", use_container_width=True):
            st.session_state.map_mode_active = True; st.rerun()
    else:
        st.info("👇 คลิกบนแผนที่เพื่อปักหมุด")
        st.session_state.active_pin_to_set = st.radio("คุณกำลังจะปัก:", ["🟢 จุดเริ่มต้น (Start)", "🔴 ปลายทาง (End)"], horizontal=True)
        if st.button("❌ ปิดโหมดปักหมุด", use_container_width=True):
            st.session_state.map_mode_active = False; st.rerun()

    st.divider()
    if not df_cars.empty:
        car = st.selectbox("เลือกรถ", df_cars.iloc[:, 0].tolist(), on_change=reset_calculated_data)
        station = st.selectbox("เลือกปั๊ม", ["Average"] + [c for c in df_prices.columns if c != "Average"]) if df_prices is not None else None
        
        if st.button("คำนวณการเดินทาง", type="primary", use_container_width=True):
            s_c = st.session_state.pin_start or (None, None)
            if not s_c[0]:
                res = requests.get(f"https://nominatim.openstreetmap.org/search?q={st.session_state.origin_text}&format=json&limit=1").json()
                s_c = (float(res[0]['lat']), float(res[0]['lon'])) if res else (None, None)
            
            e_c = st.session_state.pin_end or (None, None)
            if not e_c[0]:
                res = requests.get(f"https://nominatim.openstreetmap.org/search?q={st.session_state.dest_text}&format=json&limit=1").json()
                e_c = (float(res[0]['lat']), float(res[0]['lon'])) if res else (None, None)

            if s_c[0] and e_c[0]:
                route_res = requests.get(f"http://router.project-osrm.org/route/v1/driving/{s_c[1]},{s_c[0]};{e_c[1]},{e_c[0]}?overview=full&geometries=geojson").json()
                if route_res.get("code") == "Ok":
                    st.session_state.distance = route_res["routes"][0]["distance"] / 1000
                    st.session_state.route_coords = [[c[1], c[0]] for c in route_res["routes"][0]["geometry"]["coordinates"]]
                    st.session_state.start_coords, st.session_state.end_coords = s_c, e_c
                    st.session_state.calculated = True
            else: st.error("❌ หาพิกัดไม่พบครับ")

    if st.session_state.calculated and st.session_state.distance:
        c_info = df_cars[df_cars.iloc[:, 0] == car].iloc[0]
        fuel_type, km_l = str(c_info.iloc[1]).strip(), float(c_info.iloc[2])
        price = df_prices.loc[FUEL_MAP.get(fuel_type), station] if station and FUEL_MAP.get(fuel_type) in df_prices.index else 0
        if price > 0:
            st.subheader("สรุปผล")
            st.metric("ระยะทาง (กม.)", f"{st.session_state.distance:.2f}")
            st.metric("ค่าน้ำมัน (บาท)", f"{(st.session_state.distance/km_l)*price:.2f}")

with col2:
    m = folium.Map(location=[13.75, 100.5], zoom_start=6)
    if st.session_state.pin_start: folium.Marker(st.session_state.pin_start, icon=folium.Icon(color="green")).add_to(m)
    if st.session_state.pin_end: folium.Marker(st.session_state.pin_end, icon=folium.Icon(color="red")).add_to(m)
    if st.session_state.calculated and st.session_state.route_coords:
        folium.PolyLine(st.session_state.route_coords, color="blue", weight=5).add_to(m)
    
    map_data = st_folium(m, width="100%", height=550, key="map")
    
    if st.session_state.map_mode_active and map_data.get("last_clicked"):
        pos = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
        if st.session_state.active_pin_to_set == "🟢 จุดเริ่มต้น (Start)":
            st.session_state.pin_start, st.session_state.origin_text = pos, f"📍 {get_place_name(pos[0], pos[1])}"
        else:
            st.session_state.pin_end, st.session_state.dest_text = pos, f"📍 {get_place_name(pos[0], pos[1])}"
        reset_calculated_data(); st.rerun()