import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Route Cost Calculator", layout="wide")

# ==========================================
# 🧠 1. ระบบจัดการความจำ (Session State)
# ==========================================
# เพิ่มตัวแปรเก็บประเภทรถที่เลือก
if 'selected_type' not in st.session_state:
    st.session_state.selected_type = None

keys = ['calculated', 'distance', 'route_coords', 'start_coords', 'end_coords', 
        'pin_start', 'pin_end', 'map_mode_active', 'active_pin_to_set', 
        'origin_text', 'dest_text']

for key in keys:
    if key not in st.session_state:
        st.session_state[key] = False if 'active' in key or 'calculated' in key else None

def reset_calculated_data():
    st.session_state.calculated = False
    st.session_state.distance = None

# ==========================================
# 📦 2. ดึงข้อมูลรถจาก CSV
# ==========================================
@st.cache_data(ttl=60)
def get_car_data():
    try:
        df = pd.read_csv("cars.csv", encoding='utf-8-sig')
        # ถ้าไม่มีคอลัมน์ประเภท ให้สร้างหลอกๆ ไว้ก่อนกันพัง
        if "ประเภท" not in df.columns:
            df["ประเภท"] = "รถยนต์"
        return df
    except:
        return pd.DataFrame({"ยี่ห้อ": ["Honda"], "รุ่นรถ": ["Wave 110i"], "ประเภทน้ำมัน": ["แก๊สโซฮอล์ 91"], "อัตราสิ้นเปลือง (กม./ลิตร)": [70.0], "ประเภท": ["มอเตอร์ไซค์"]})

df_cars = get_car_data()

# ==========================================
# ⛽ 3. ระบบราคาน้ำมัน
# ==========================================
@st.cache_data(ttl=3600) 
def get_live_oil_prices():
    try:
        res = requests.get("https://thai-oil-api.vercel.app/latest").json()
        stations = res['response']['stations']
        clean_data = {s: {f: i['price'] for f, i in fuels.items() if isinstance(i, dict)} for s, fuels in stations.items()}
        df = pd.DataFrame(clean_data).apply(pd.to_numeric, errors='coerce')
        df['Average'] = df.mean(axis=1).round(2)
        return df.fillna(0)
    except: return None

df_prices = get_live_oil_prices()
FUEL_MAP = {"เบนซิน": "gasoline_95", "แก๊สโซฮอล์ 95": "gasohol_95", "แก๊สโซฮอล์ 91": "gasohol_91", "E20": "gasohol_e20", "ดีเซล": "diesel", "ดีเซล B7": "diesel", "Diesel B7": "diesel"}

# ==========================================
# 🎨 4. ส่วนหน้าตาแอป (UI)
# ==========================================
st.title("📍 Route Cost Calculator")

col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("รายละเอียดการเดินทาง")
    origin = st.text_input("จุดเริ่มต้น", value=st.session_state.origin_text)
    dest = st.text_input("จุดหมายปลายทาง", value=st.session_state.dest_text)

    # --- 🚗 ส่วนปุ่มไอคอนเลือกประเภท (Optional Filter) ---
    st.write("เลือกประเภทรถ (เลือกหรือไม่เลือกก็ได้)")
    ic1, ic2, ic3 = st.columns([1, 1, 2])
    
    # ปุ่มรถยนต์
    if ic1.button("🚗", help="แสดงเฉพาะรถยนต์", use_container_width=True):
        st.session_state.selected_type = "รถยนต์"
    
    # ปุ่มมอเตอร์ไซค์
    if ic2.button("🏍️", help="แสดงเฉพาะมอเตอร์ไซค์", use_container_width=True):
        st.session_state.selected_type = "มอเตอร์ไซค์"
        
    # ปุ่มล้างตัวกรอง
    if st.session_state.selected_type:
        if ic3.button(f"ล้างตัวกรอง ({st.session_state.selected_type})", type="secondary"):
            st.session_state.selected_type = None
            st.rerun()

    st.divider()
    
    # --- ระบบกรองข้อมูล (Logic) ---
    if st.session_state.selected_type:
        filtered_df = df_cars[df_cars["ประเภท"] == st.session_state.selected_type]
    else:
        filtered_df = df_cars

    # --- ระบบเลือก Brand > Model ---
    brands = sorted(filtered_df["ยี่ห้อ"].unique().tolist())
    sel_brand = st.selectbox("เลือกยี่ห้อรถ", brands)
    
    models_df = filtered_df[filtered_df["ยี่ห้อ"] == sel_brand]
    sel_model = st.selectbox("เลือกรุ่นรถ", models_df["รุ่นรถ"].tolist(), on_change=reset_calculated_data)
    
    car_info = models_df[models_df["รุ่นรถ"] == sel_model].iloc[0]
    
    # [ ส่วนโค้ดคำนวณและแผนที่เดิมคงไว้ทั้งหมด ]
    # ... (เพื่อให้สั้นลง ผมขอละส่วนที่เหลือไว้นะครับ แต่คุณโอ๊คใช้ของเดิมต่อได้เลย) ...

    # --- ส่วนปุ่มคำนวณ (เหมือนเดิม) ---
    if st.button("คำนวณการเดินทาง", type="primary", use_container_width=True):
        # [ โค้ดคำนวณเดิมของคุณโอ๊ค ]
        s_c = st.session_state.pin_start
        if not s_c and origin:
            r = requests.get(f"https://nominatim.openstreetmap.org/search?q={origin}&format=json&limit=1").json()
            s_c = [float(r[0]['lat']), float(r[0]['lon'])] if r else None
        
        e_c = st.session_state.pin_end
        if not e_c and dest:
            r = requests.get(f"https://nominatim.openstreetmap.org/search?q={dest}&format=json&limit=1").json()
            e_c = [float(r[0]['lat']), float(r[0]['lon'])] if r else None

        if s_c and e_c:
            with st.spinner("กำลังคำนวณ..."):
                route_res = requests.get(f"http://router.project-osrm.org/route/v1/driving/{s_c[1]},{s_c[0]};{e_c[1]},{e_c[0]}?overview=full&geometries=geojson").json()
                if route_res.get("code") == "Ok":
                    st.session_state.distance = route_res["routes"][0]["distance"] / 1000
                    st.session_state.route_coords = [[c[1], c[0]] for c in route_res["routes"][0]["geometry"]["coordinates"]]
                    st.session_state.start_coords, st.session_state.end_coords = s_c, e_c
                    st.session_state.calculated = True

    if st.session_state.calculated and st.session_state.distance:
        f_type, km_l = str(car_info["ประเภทน้ำมัน"]).strip(), float(car_info["อัตราสิ้นเปลือง (กม./ลิตร)"])
        # (ส่วนแสดงผลสรุปเดิม)
        st.divider(); st.subheader("สรุปผล")
        m1, m2 = st.columns(2)
        m1.metric("ระยะทางจริง (กม.)", f"{st.session_state.distance:.2f}")
        # ดึงราคาปั๊ม Average มาโชว์
        price = df_prices.loc[FUEL_MAP.get(f_type), "Average"] if FUEL_MAP.get(f_type) in df_prices.index else 0
        m2.metric("ค่าน้ำมันรวม (บาท)", f"{(st.session_state.distance/km_l)*price:.2f}")
        st.info(f"⛽ {f_type} (ราคาเฉลี่ย): {price} บาท/ลิตร")

with col2:
    # [ ส่วนแผนที่เดิมของคุณโอ๊ค ]
    m = folium.Map(location=[13.75, 100.5], zoom_start=6)
    if st.session_state.pin_start: folium.Marker(st.session_state.pin_start, icon=folium.Icon(color="green")).add_to(m)
    if st.session_state.pin_end: folium.Marker(st.session_state.pin_end, icon=folium.Icon(color="red")).add_to(m)
    if st.session_state.calculated and st.session_state.route_coords:
        folium.PolyLine(st.session_state.route_coords, color="blue", weight=5).add_to(m)
    st_folium(m, width="100%", height=600, key="map")