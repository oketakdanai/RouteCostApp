import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
import json
import os

# 1. Page Configuration
st.set_page_config(page_title="Route Cost Dashboard", layout="wide", initial_sidebar_state="collapsed")

# ==========================================
# 🎨 2. Strong Prompt Font & UI Styling
# ==========================================
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Prompt:wght@300;400;500;600&display=swap');
    
    /* บังคับทุกส่วนให้เป็น Prompt */
    * { font-family: 'Prompt', sans-serif !important; }
    
    .stApp { background-color: #0F172A; }
    
    .metric-card {
        background-color: #1E293B;
        border-radius: 15px;
        padding: 20px;
        border: 1px solid #334155;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        text-align: center;
    }
    
    .card-label { color: #94A3B8; font-size: 0.9rem; margin-bottom: 5px; }
    .card-value { color: #F8FAFC; font-size: 1.4rem; font-weight: 600; }

    div.stButton > button { border-radius: 12px !important; transition: all 0.3s ease; }
    h1, h2, h3 { color: #F8FAFC !important; font-weight: 600 !important; }
    
    /* ปรับแต่ง Dropdown และ Input ให้ดูเข้ากับ Dashboard */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1E293B !important;
        color: white !important;
        border-radius: 10px !important;
        border: 1px solid #334155 !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 🧠 3. ระบบจัดการความจำ (Session State)
# ==========================================
if 'selected_type' not in st.session_state: st.session_state.selected_type = None

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
# 📦 4. Load Data (CSV)
# ==========================================
@st.cache_data(ttl=10)
def load_car_database():
    for enc in ['utf-8-sig', 'utf-16', 'utf-8', 'cp874']:
        try:
            df = pd.read_csv("cars.csv", encoding=enc, skipinitialspace=True)
            df.columns = df.columns.str.strip()
            return df
        except: continue
    return pd.DataFrame()

df_cars = load_car_database()

# ==========================================
# ⛽ 5. Oil Price API
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
FUEL_MAP = {"เบนซิน": "gasoline_95", "แก๊สโซฮอล์ 95": "gasohol_95", "แก๊สโซฮอล์ 91": "gasohol_91", "E20": "gasohol_e20", "ดีเซล": "diesel", "ดีเซล B7": "diesel"}

# ==========================================
# 🗺️ 6. Helpers (Geocoding)
# ==========================================
def get_place_name(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=th"
        res = requests.get(url, headers={'User-Agent': 'RouteApp/Fixed'}).json()
        return ", ".join(res.get("display_name", "").split(", ")[:3])
    except: return f"{lat:.4f}, {lon:.4f}"

# ==========================================
# 🎨 7. Dashboard Layout
# ==========================================
st.markdown('<h1 style="text-align: left; margin-bottom: 30px;">🛰️ Route Cost Calculator</h1>', unsafe_allow_html=True)
col1, col2 = st.columns([1, 1.8], gap="large")

with col1:
    st.markdown("### 🗺️ รายละเอียดการเดินทาง")
    origin = st.text_input("จุดเริ่มต้น", value=st.session_state.origin_text)
    dest = st.text_input("จุดหมายปลายทาง", value=st.session_state.dest_text)
    
    if origin != st.session_state.origin_text: st.session_state.origin_text = origin; reset_calculated_data()
    if dest != st.session_state.dest_text: st.session_state.dest_text = dest; reset_calculated_data()

    if not st.session_state.map_mode_active:
        if st.button("📍 เปิดโหมดปักหมุดบนแผนที่", use_container_width=True):
            st.session_state.map_mode_active = True; st.rerun()
    else:
        st.info("💡 คลิกบนแผนที่ทางขวาเพื่อปักหมุด")
        st.session_state.active_pin_to_set = st.radio("คุณกำลังจะปัก:", ["🟢 จุดเริ่มต้น", "🔴 ปลายทาง"], horizontal=True)
        if st.button("❌ ปิดโหมดปักหมุด", type="primary", use_container_width=True):
            st.session_state.map_mode_active = False; st.rerun()

    st.divider()
    st.markdown("### 🚗 ข้อมูลรถและน้ำมัน")
    ic1, ic2, _ = st.columns([1, 1, 2])
    if ic1.button("🚗", help="เลือกเฉพาะรถยนต์", use_container_width=True, type="primary" if st.session_state.selected_type == "รถยนต์" else "secondary"):
        st.session_state.selected_type = None if st.session_state.selected_type == "รถยนต์" else "รถยนต์"; st.rerun()
    if ic2.button("🏍️", help="เลือกเฉพาะมอเตอร์ไซค์", use_container_width=True, type="primary" if st.session_state.selected_type == "มอเตอร์ไซค์" else "secondary"):
        st.session_state.selected_type = None if st.session_state.selected_type == "มอเตอร์ไซค์" else "มอเตอร์ไซค์"; st.rerun()

    f_df = df_cars[df_cars["ประเภท"] == st.session_state.selected_type] if st.session_state.selected_type else df_cars
    
    if not f_df.empty:
        sel_brand = st.selectbox("ยี่ห้อรถ", sorted(f_df["ยี่ห้อ"].unique().tolist()))
        m_df = f_df[f_df["ยี่ห้อ"] == sel_brand]
        sel_model = st.selectbox("รุ่นรถ", m_df["รุ่นรถ"].tolist(), on_change=reset_calculated_data)
        car_info = m_df[m_df["รุ่นรถ"] == sel_model].iloc[0]
        
        if df_prices is not None:
            sel_station = st.selectbox("เลือกปั๊ม", ["Average"] + [c for c in df_prices.columns if c != "Average"], on_change=reset_calculated_data)
        
        if st.button("🚀 คำนวณเส้นทางและค่าใช้จ่าย", type="primary", use_container_width=True):
            s_c = st.session_state.pin_start
            if not s_c and origin:
                r = requests.get(f"https://nominatim.openstreetmap.org/search?q={origin.replace('📍 ','')}&format=json&limit=1").json()
                s_c = [float(r[0]['lat']), float(r[0]['lon'])] if r else None
            e_c = st.session_state.pin_end
            if not e_c and dest:
                r = requests.get(f"https://nominatim.openstreetmap.org/search?q={dest.replace('📍 ','')}&format=json&limit=1").json()
                e_c = [float(r[0]['lat']), float(r[0]['lon'])] if r else None
            
            if s_c and e_c:
                with st.spinner("กำลังประมวลผล..."):
                    route_res = requests.get(f"http://router.project-osrm.org/route/v1/driving/{s_c[1]},{s_c[0]};{e_c[1]},{e_c[0]}?overview=full&geometries=geojson").json()
                    if route_res.get("code") == "Ok":
                        st.session_state.distance = route_res["routes"][0]["distance"] / 1000
                        st.session_state.route_coords = [[c[1], c[0]] for c in route_res["routes"][0]["geometry"]["coordinates"]]
                        st.session_state.start_coords, st.session_state.end_coords = s_c, e_c
                        st.session_state.calculated = True
            else: st.error("❌ ไม่พบพิกัดครับ")

with col2:
    st.markdown("### 🏁 แผนที่แสดงเส้นทาง")
    m = folium.Map(location=[13.75, 100.5], zoom_start=6, tiles='CartoDB dark_matter') 
    
    if st.session_state.pin_start: folium.Marker(st.session_state.pin_start, icon=folium.Icon(color="green", icon="play")).add_to(m)
    if st.session_state.pin_end: folium.Marker(st.session_state.pin_end, icon=folium.Icon(color="red", icon="flag")).add_to(m)
    
    if st.session_state.calculated and st.session_state.route_coords:
        folium.PolyLine(st.session_state.route_coords, color="#3B82F6", weight=6, opacity=0.8).add_to(m)
        m.fit_bounds([st.session_state.start_coords, st.session_state.end_coords])
    
    # --- ส่วนหัวใจสำคัญ: ดักจับการคลิกบนแผนที่ ---
    map_data = st_folium(m, width="100%", height=550, key="map")
    
    if st.session_state.map_mode_active and map_data.get("last_clicked"):
        click_pos = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
        # เช็กว่าเป็นการคลิกใหม่จริงๆ (พิกัดเปลี่ยนไป)
        last_pin = st.session_state.pin_start if st.session_state.active_pin_to_set == "🟢 จุดเริ่มต้น" else st.session_state.pin_end
        
        if click_pos != last_pin:
            if st.session_state.active_pin_to_set == "🟢 จุดเริ่มต้น":
                st.session_state.pin_start = click_pos
                st.session_state.origin_text = f"📍 {get_place_name(click_pos[0], click_pos[1])}"
            else:
                st.session_state.pin_end = click_pos
                st.session_state.dest_text = f"📍 {get_place_name(click_pos[0], click_pos[1])}"
            reset_calculated_data(); st.rerun()

    # --- สรุปผลด้านล่างแผนที่ ---
    if st.session_state.calculated and st.session_state.distance:
        st.markdown("### 📊 สรุปผลการเดินทาง")
        f_type, km_l = str(car_info["ประเภทน้ำมัน"]).strip(), float(car_info["อัตราสิ้นเปลือง (กม./ลิตร)"])
        price = df_prices.loc[FUEL_MAP.get(f_type), sel_station] if FUEL_MAP.get(f_type) in df_prices.index else 0
        
        r1, r2, r3 = st.columns(3)
        with r1: st.markdown(f'<div class="metric-card"><div class="card-label">📏 ระยะทาง</div><div class="card-value">{st.session_state.distance:.2f} กม.</div></div>', unsafe_allow_html=True)
        with r2: st.markdown(f'<div class="metric-card"><div class="card-label">💰 ค่าน้ำมัน</div><div class="card-value">{(st.session_state.distance/km_l)*price:.2f} บาท</div></div>', unsafe_allow_html=True)
        with r3: st.markdown(f'<div class="metric-card"><div class="card-label">⛽ ราคา/ลิตร</div><div class="card-value">{price} บาท</div></div>', unsafe_allow_html=True)