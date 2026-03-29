import streamlit as st
import gspread
import json  
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
import textwrap

st.set_page_config(page_title="Route Cost", layout="wide")

# ==========================================
# 🧠 1. ส่วนบริหารจัดการความจำ (st.session_state)
# ==========================================
if 'calculated' not in st.session_state:
    st.session_state.calculated = False
    st.session_state.distance = None
    st.session_state.route_coords = None
    st.session_state.start_coords = None
    st.session_state.end_coords = None

if 'pin_start' not in st.session_state:
    st.session_state.pin_start = None
if 'pin_end' not in st.session_state:
    st.session_state.pin_end = None

if 'map_mode_active' not in st.session_state:
    st.session_state.map_mode_active = False
if 'active_pin_to_set' not in st.session_state:
    st.session_state.active_pin_to_set = None

if 'origin_text' not in st.session_state:
    st.session_state.origin_text = ""
if 'dest_text' not in st.session_state:
    st.session_state.dest_text = ""

def reset_calculated_data():
    st.session_state.calculated = False
    st.session_state.distance = None
    st.session_state.route_coords = None
    st.session_state.start_coords = None
    st.session_state.end_coords = None

# ==========================================
# 📦 2. เชื่อมต่อ Google Sheets (เวอร์ชันซ่อมกุญแจขั้นสูง)
# ==========================================
@st.cache_resource
def init_connection():
    try:
        # 1. โหลดข้อมูลกุญแจจาก Secrets
        creds_json = st.secrets["google_credentials"]
        creds_dict = json.loads(creds_json, strict=False)
        
        # 2. ระบบซ่อมแซมลายเซ็นกุญแจ (JWT Signature Fixer)
        # ป้องกันปัญหา Invalid JWT Signature จากการก๊อปปี้กุญแจไม่เป๊ะ
        private_key = creds_dict.get("private_key", "")
        cleaned_key = private_key.replace("\\n", "\n")
        
        if "-----BEGIN PRIVATE KEY-----" in cleaned_key:
            start_marker = "-----BEGIN PRIVATE KEY-----"
            end_marker = "-----END PRIVATE KEY-----"
            
            # แยกเฉพาะเนื้อกุญแจออกมาล้างช่องว่าง
            parts = cleaned_key.split(start_marker)
            if len(parts) > 1:
                sub_parts = parts[1].split(end_marker)
                if len(sub_parts) > 0:
                    core_key = "".join(sub_parts[0].split())
                    # จัดเรียงใหม่ให้เป๊ะ บรรทัดละ 64 ตัวอักษรตามมาตรฐาน PEM
                    formatted_core = "\n".join(textwrap.wrap(core_key, 64))
                    final_key = f"{start_marker}\n{formatted_core}\n{end_marker}\n"
                    creds_dict["private_key"] = final_key
        
        # 3. ล็อกอินเข้า Google Sheets
        client = gspread.service_account_from_dict(creds_dict)
        return client.open("Route Cost")
        
    except Exception as e:
        st.error(f"⚠️ เกิดข้อผิดพลาดในการเชื่อมต่อ Google Sheets: {e}")
        return None

conn = init_connection()

@st.cache_data(ttl=600)
def get_car_data():
    if conn:
        return pd.DataFrame(conn.worksheet("DB_รถยนต์").get_all_records())
    return pd.DataFrame()

df_cars = get_car_data()

# ==========================================
# ⛽ 3. ดึงราคาน้ำมันจาก API
# ==========================================
@st.cache_data(ttl=3600) 
def get_live_oil_prices():
    url = "https://thai-oil-api.vercel.app/latest"
    try:
        res = requests.get(url).json()
        stations_data = res['response']['stations']
        clean_data = {}
        for station_name, fuels in stations_data.items():
            clean_data[station_name] = {}
            for fuel_key, fuel_info in fuels.items():
                if isinstance(fuel_info, dict) and 'price' in fuel_info:
                    clean_data[station_name][fuel_key] = fuel_info['price']
        df = pd.DataFrame(clean_data)
        df = df.apply(pd.to_numeric, errors='coerce')
        df['Average'] = df.select_dtypes(include=['number']).mean(axis=1, skipna=True).round(2)
        df = df.fillna(0) 
        return df
    except:
        return None

df_prices = get_live_oil_prices()

FUEL_MAPPING = {
    "เบนซิน": "gasoline_95",
    "แก๊สโซฮอล์ 95": "gasohol_95",
    "แก๊สโซฮอล์ 91": "gasohol_91",
    "E20": "gasohol_e20",
    "E85": "gasohol_e85",
    "Diesel B7": "diesel",
    "ดีเซล": "diesel",
    "ดีเซล B7": "diesel",
    "Premium Diesel": "premium_diesel"
}

# ==========================================
# 🗺️ 4. ระบบพิกัดและการคำนวณเส้นทาง
# ==========================================
def get_coords_from_text(place_name):
    if not place_name.strip() or place_name.startswith("📍"):
        return None, None
    url = f"https://nominatim.openstreetmap.org/search?q={place_name}&format=json&limit=1"
    headers = {'User-Agent': 'RouteCostApp/2.0'}
    try:
        res = requests.get(url, headers=headers).json()
        if len(res) > 0:
            return float(res[0]['lat']), float(res[0]['lon'])
    except:
        pass
    return None, None

def get_place_name(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=th"
    headers = {'User-Agent': 'RouteCostApp/2.0'}
    try:
        res = requests.get(url, headers=headers).json()
        if "display_name" in res:
            parts = res["display_name"].split(", ")
            return ", ".join(parts[:3]) 
    except:
        pass
    return f"พิกัด {lat:.4f}, {lon:.4f}"

def get_route_data_free(start_coords, end_coords):
    if not start_coords or not end_coords:
        return None, None, None, None
    lat1, lon1 = start_coords
    lat2, lon2 = end_coords
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
    try:
        res = requests.get(osrm_url).json()
        if res.get("code") == "Ok":
            distance_km = res["routes"][0]["distance"] / 1000
            coords = res["routes"][0]["geometry"]["coordinates"]
            route_coords = [[coord[1], coord[0]] for coord in coords]
            return distance_km, route_coords, start_coords, end_coords
    except:
        pass
    return None, None, None, None

# ==========================================
# 🎨 5. จัดหน้า UI
# ==========================================
st.title("📍 Route Cost Calculator")

col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("รายละเอียดการเดินทาง")
    
    origin = st.text_input("จุดเริ่มต้น", value=st.session_state.origin_text)
    destination = st.text_input("จุดหมายปลายทาง", value=st.session_state.dest_text)
    
    if origin != st.session_state.origin_text:
        st.session_state.origin_text = origin
        reset_calculated_data()
    if destination != st.session_state.dest_text:
        st.session_state.dest_text = destination
        reset_calculated_data()
    
    if not st.session_state.map_mode_active:
        if st.button("🗺️ เลือกจากแผนที่", key="activate_map_mode_btn", type="secondary", use_container_width=True):
            st.session_state.map_mode_active = True
            st.rerun() 
    else:
        st.info("👇 เลือกหมุดที่ต้องการ แล้วคลิกบนแผนที่ได้เลยครับ")
        col_s, col_e = st.columns(2)
        st.session_state.active_pin_to_set = st.radio("เลือกจุดที่จะปัก:", ["🟢 จุดเริ่มต้น (Start)", "🔴 ปลายทาง (End)"], horizontal=True)
        
        col_s.write(f"**เขียว:** {'✅' if st.session_state.pin_start else '❌'}")
        col_e.write(f"**แดง:** {'✅' if st.session_state.pin_end else '❌'}")
        
        c1, c2 = st.columns(2)
        if c1.button("ล้างหมุด", use_container_width=True):
            st.session_state.pin_start = st.session_state.pin_end = None
            st.session_state.origin_text = st.session_state.dest_text = ""
            reset_calculated_data()
            st.rerun()
        if c2.button("❌ ปิดโหมดปัก", type="primary", use_container_width=True):
            st.session_state.map_mode_active = False
            st.rerun()

    st.divider()
    if not df_cars.empty:
        selected_car = st.selectbox("เลือกรถของคุณ", df_cars.iloc[:, 0].tolist(), on_change=reset_calculated_data) 
    else:
        st.warning("⚠️ ไม่พบข้อมูลรถในระบบ")
        selected_car = None
    
    if df_prices is not None:
        station_options = ["Average"] + [col for col in df_prices.columns if col != "Average"]
        selected_station = st.selectbox("เลือกปั๊มน้ำมัน", station_options, on_change=reset_calculated_data)
    else:
        selected_station = None

    if st.button("คำนวณการเดินทาง", type="primary", use_container_width=True):
        start_c = st.session_state.pin_start or get_coords_from_text(st.session_state.origin_text)
        end_c = st.session_state.pin_end or get_coords_from_text(st.session_state.dest_text)
            
        if not start_c or not end_c:
            st.error("❌ ระบุตำแหน่งให้ครบก่อนนะครับ")
        else:
            with st.spinner('กำลังคำนวณ...'):
                dist, coords, start, end = get_route_data_free(start_c, end_c)
                if dist:
                    st.session_state.calculated, st.session_state.distance = True, dist
                    st.session_state.route_coords, st.session_state.start_coords, st.session_state.end_coords = coords, start, end
                else:
                    st.error("❌ ไม่พบเส้นทางครับ")
            
    if st.session_state.calculated and st.session_state.distance:
        car_info = df_cars[df_cars.iloc[:, 0] == selected_car].iloc[0]
        sheet_fuel, km_l = str(car_info.iloc[1]).strip(), float(car_info.iloc[2])
        api_fuel = FUEL_MAPPING.get(sheet_fuel)
        
        if api_fuel and api_fuel in df_prices.index:
            price = df_prices.loc[api_fuel, selected_station]
            if price > 0:
                cost = (st.session_state.distance / km_l) * price
                st.divider()
                st.subheader("สรุปผล")
                m1, m2 = st.columns(2)
                m1.metric("ระยะทาง (กม.)", f"{st.session_state.distance:.2f}")
                m2.metric("ค่าน้ำมัน (บาท)", f"{cost:.2f}")
                st.success(f"ℹ️ {sheet_fuel} ลิตรละ {price} บาท")

with col2:
    st.subheader("แผนที่เส้นทาง")
    m = folium.Map(location=[13.7563, 100.5018], zoom_start=6)
    
    if st.session_state.pin_start:
        folium.Marker(st.session_state.pin_start, icon=folium.Icon(color="green")).add_to(m)
    if st.session_state.pin_end:
        folium.Marker(st.session_state.pin_end, icon=folium.Icon(color="red")).add_to(m)

    if st.session_state.calculated and st.session_state.route_coords:
        folium.PolyLine(st.session_state.route_coords, color="blue", weight=5).add_to(m)
        folium.Marker(st.session_state.start_coords, icon=folium.Icon(color="green", icon="play")).add_to(m)
        folium.Marker(st.session_state.end_coords, icon=folium.Icon(color="red", icon="flag")).add_to(m)
        
    map_data = st_folium(m, width="100%", height=550, returned_objects=["last_clicked"], key="interactive_map")
    
    if st.session_state.map_mode_active and map_data and map_data.get("last_clicked"):
        lat, lon = map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]
        clicked = [lat, lon]
        
        if st.session_state.active_pin_to_set == "🟢 จุดเริ่มต้น (Start)" and st.session_state.pin_start != clicked:
            st.session_state.pin_start = clicked
            st.session_state.origin_text = f"📍 {get_place_name(lat, lon)}"
            reset_calculated_data()
            st.rerun() 
        elif st.session_state.active_pin_to_set == "🔴 ปลายทาง (End)" and st.session_state.pin_end != clicked:
            st.session_state.pin_end = clicked
            st.session_state.dest_text = f"📍 {get_place_name(lat, lon)}"
            reset_calculated_data()
            st.rerun()