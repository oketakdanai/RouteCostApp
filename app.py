import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Route Cost Calculator", layout="wide")

# ==========================================
# 🧠 1. ระบบจัดการความจำ (Session State)
# ==========================================
keys = ['calculated', 'distance', 'route_coords', 'start_coords', 'end_coords', 
        'pin_start', 'pin_end', 'map_mode_active', 'active_pin_to_set', 
        'origin_text', 'dest_text']

for key in keys:
    if key not in st.session_state:
        st.session_state[key] = False if 'active' in key or 'calculated' in key else None

if st.session_state.origin_text is None: st.session_state.origin_text = ""
if st.session_state.dest_text is None: st.session_state.dest_text = ""

def reset_calculated_data():
    st.session_state.calculated = False
    st.session_state.distance = None
    st.session_state.route_coords = None

# ==========================================
# 📦 2. ดึงข้อมูลรถจาก CSV (Database ใหม่)
# ==========================================
@st.cache_data(ttl=600)
def get_car_data():
    try:
        # พยายามอ่านไฟล์ cars.csv จาก GitHub
        df = pd.read_csv("cars.csv")
        return df
    except:
        # ข้อมูลสำรองกรณีหาไฟล์ไม่เจอ
        return pd.DataFrame({
            "ยี่ห้อ": ["Toyota", "Honda"],
            "รุ่นรถ": ["Corolla Cross", "Civic"],
            "ประเภทน้ำมัน": ["แก๊สโซฮอล์ 91", "แก๊สโซฮอล์ 95"],
            "อัตราสิ้นเปลือง (กม./ลิตร)": [23.3, 17.2]
        })

df_cars = get_car_data()

# ==========================================
# ⛽ 3. ระบบราคาน้ำมัน (Real-time API)
# ==========================================
@st.cache_data(ttl=3600) 
def get_live_oil_prices():
    try:
        res = requests.get("https://thai-oil-api.vercel.app/latest").json()
        stations = res['response']['stations']
        clean_data = {}
        for station_name, fuels in stations.items():
            clean_data[station_name] = {f: i['price'] for f, i in fuels.items() if isinstance(i, dict) and 'price' in i}
        df = pd.DataFrame(clean_data).apply(pd.to_numeric, errors='coerce')
        df['Average'] = df.mean(axis=1).round(2)
        return df.fillna(0)
    except: return None

df_prices = get_live_oil_prices()
FUEL_MAP = {
    "เบนซิน": "gasoline_95", "แก๊สโซฮอล์ 95": "gasohol_95", 
    "แก๊สโซฮอล์ 91": "gasohol_91", "E20": "gasohol_e20", 
    "E85": "gasohol_e85", "ดีเซล": "diesel", 
    "ดีเซล B7": "diesel", "Premium Diesel": "premium_diesel"
}

# ==========================================
# 🗺️ 4. ฟังก์ชันช่วยเหลือ (Map & Location)
# ==========================================
def get_place_name(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=th"
        res = requests.get(url, headers={'User-Agent': 'RouteApp/4.0'}).json()
        return ", ".join(res.get("display_name", "").split(", ")[:3])
    except: return f"{lat:.4f}, {lon:.4f}"

# ==========================================
# 🎨 5. หน้าตา UI
# ==========================================
st.title("📍 Route Cost Calculator")
col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("รายละเอียดการเดินทาง")
    origin = st.text_input("จุดเริ่มต้น", value=st.session_state.origin_text)
    dest = st.text_input("จุดหมายปลายทาง", value=st.session_state.dest_text)
    
    if origin != st.session_state.origin_text: st.session_state.origin_text = origin; reset_calculated_data()
    if dest != st.session_state.dest_text: st.session_state.dest_text = dest; reset_calculated_data()

    if not st.session_state.map_mode_active:
        if st.button("🗺️ เลือกจากแผนที่", use_container_width=True):
            st.session_state.map_mode_active = True; st.rerun()
    else:
        st.info("👇 คลิกบนแผนที่ทางขวาเพื่อปักหมุด")
        st.session_state.active_pin_to_set = st.radio("เลือกจุดที่จะปัก:", ["🟢 จุดเริ่มต้น (Start)", "🔴 ปลายทาง (End)"], horizontal=True)
        if st.button("❌ ปิดโหมดปักหมุด", type="primary", use_container_width=True):
            st.session_state.map_mode_active = False; st.rerun()

    st.divider()
    st.subheader("ข้อมูลรถและน้ำมัน")
    
    # --- ระบบเลือกแบบ 2 ชั้น (Brand > Model) ---
    brands = sorted(df_cars["ยี่ห้อ"].unique().tolist())
    sel_brand = st.selectbox("เลือกยี่ห้อรถ", brands)
    
    models_df = df_cars[df_cars["ยี่ห้อ"] == sel_brand]
    sel_model = st.selectbox("เลือกรุ่นรถ", models_df["รุ่นรถ"].tolist(), on_change=reset_calculated_data)
    
    car_info = models_df[models_df["รุ่นรถ"] == sel_model].iloc[0]
    
    # --- เลือกปั๊มน้ำมัน ---
    if df_prices is not None:
        stations = ["Average"] + [c for c in df_prices.columns if c != "Average"]
        sel_station = st.selectbox("เลือกปั๊มน้ำมัน", stations, on_change=reset_calculated_data)
    
    if st.button("คำนวณการเดินทาง", type="primary", use_container_width=True):
        # 1. หาพิกัด (จากหมุด หรือ จากพิมพ์)
        s_c = st.session_state.pin_start
        if not s_c:
            r = requests.get(f"https://nominatim.openstreetmap.org/search?q={origin}&format=json&limit=1").json()
            s_c = [float(r[0]['lat']), float(r[0]['lon'])] if r else None
        
        e_c = st.session_state.pin_end
        if not e_c:
            r = requests.get(f"https://nominatim.openstreetmap.org/search?q={dest}&format=json&limit=1").json()
            e_c = [float(r[0]['lat']), float(r[0]['lon'])] if r else None

        if s_c and e_c:
            with st.spinner("กำลังคำนวณเส้นทาง..."):
                route_res = requests.get(f"http://router.project-osrm.org/route/v1/driving/{s_c[1]},{s_c[0]};{e_c[1]},{e_c[0]}?overview=full&geometries=geojson").json()
                if route_res.get("code") == "Ok":
                    st.session_state.distance = route_res["routes"][0]["distance"] / 1000
                    st.session_state.route_coords = [[c[1], c[0]] for c in route_res["routes"][0]["geometry"]["coordinates"]]
                    st.session_state.start_coords, st.session_state.end_coords = s_c, e_c
                    st.session_state.calculated = True
        else: st.error("❌ หาพิกัดไม่พบ กรุณาระบุชื่อสถานที่ให้ชัดเจนครับ")

    # --- แสดงผลสรุป ---
    if st.session_state.calculated and st.session_state.distance:
        f_type, km_l = str(car_info["ประเภทน้ำมัน"]).strip(), float(car_info["อัตราสิ้นเปลือง (กม./ลิตร)"])
        price = df_prices.loc[FUEL_MAP.get(f_type), sel_station] if FUEL_MAP.get(f_type) in df_prices.index else 0
        
        if price > 0:
            st.divider()
            st.subheader("สรุปผลการคำนวณ")
            m1, m2 = st.columns(2)
            m1.metric("ระยะทางจริง (กม.)", f"{st.session_state.distance:.2f}")
            m2.metric("ค่าน้ำมันรวม (บาท)", f"{(st.session_state.distance/km_l)*price:.2f}")
            st.info(f"⛽ ใช้ราคา {f_type} จากปั๊ม {sel_station}: {price} บาท/ลิตร")
        else:
            st.warning(f"⚠️ ไม่พบราคา {f_type} ในฐานข้อมูลน้ำมันขณะนี้")

with col2:
    st.subheader("แผนที่เส้นทาง")
    m = folium.Map(location=[13.75, 100.5], zoom_start=6)
    
    # แสดงหมุด
    if st.session_state.pin_start: folium.Marker(st.session_state.pin_start, icon=folium.Icon(color="green")).add_to(m)
    if st.session_state.pin_end: folium.Marker(st.session_state.pin_end, icon=folium.Icon(color="red")).add_to(m)
    if st.session_state.calculated and st.session_state.route_coords:
        folium.PolyLine(st.session_state.route_coords, color="blue", weight=5, opacity=0.8).add_to(m)
        folium.Marker(st.session_state.start_coords, icon=folium.Icon(color="green", icon="play")).add_to(m)
        folium.Marker(st.session_state.end_coords, icon=folium.Icon(color="red", icon="flag")).add_to(m)
        m.fit_bounds([st.session_state.start_coords, st.session_state.end_coords])

    map_data = st_folium(m, width="100%", height=600, key="map")
    
    # ระบบปักหมุด
    if st.session_state.map_mode_active and map_data.get("last_clicked"):
        pos = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
        if st.session_state.active_pin_to_set == "🟢 จุดเริ่มต้น (Start)":
            st.session_state.pin_start, st.session_state.origin_text = pos, f"📍 {get_place_name(pos[0], pos[1])}"
        else:
            st.session_state.pin_end, st.session_state.dest_text = pos, f"📍 {get_place_name(pos[0], pos[1])}"
        reset_calculated_data(); st.rerun()