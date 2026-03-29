import streamlit as st
import gspread
import json  
import pandas as pd
import requests
import folium
from streamlit_folium import st_folium
import re        # <- เพิ่มตัวช่วยจัดการข้อความ
import textwrap  # <- เพิ่มตัวช่วยจัดเรียงบรรทัด

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
# 📦 2. เชื่อมต่อ Google Sheets 
# ==========================================
@st.cache_resource
def init_connection():
    try:
        # 1. โหลดข้อมูลกุญแจ
        creds_json = st.secrets["google_credentials"]
        creds_dict = json.loads(creds_json, strict=False)
        
        # 2. จัดการเรื่องตัวตัดบรรทัดให้ชัวร์ที่สุด
        if "private_key" in creds_dict:
            # ลบช่องว่างที่อาจติดมาจากการก๊อปปี้ และแปลง \n ให้ถูกต้อง
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
        # 3. ล็อกอิน
        client = gspread.service_account_from_dict(creds_dict)
        return client.open("Route Cost")
    except Exception as e:
        st.error(f"⚠️ เกิดข้อผิดพลาดในการเชื่อมต่อ Google Sheets: {e}")
        return None
    
    # 🔥🔥🔥 ระบบ "เครื่องซักผ้ากุญแจ" (Key Washer) 🔥🔥🔥
    # ดึงกุญแจเดิมมาล้างช่องว่างและจัดเรียงบรรทัดใหม่ให้ Google อ่านออก 100%
    raw_key = creds_dict.get("private_key", "")
    raw_key = raw_key.replace("-----BEGIN PRIVATE KEY-----", "")
    raw_key = raw_key.replace("-----END PRIVATE KEY-----", "")
    raw_key = re.sub(r'\s+', '', raw_key) # ลบช่องว่างและบรรทัดที่ผิดเพี้ยนทิ้งให้เกลี้ยง
    raw_key = raw_key.replace("\\n", "")
    
    # ประกอบร่างกุญแจใหม่ให้เป๊ะตามมาตรฐาน
    clean_key = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(textwrap.wrap(raw_key, 64)) + "\n-----END PRIVATE KEY-----\n"
    creds_dict["private_key"] = clean_key
    # 🔥🔥🔥 จบการทำงานเครื่องซักผ้า 🔥🔥🔥
    
    client = gspread.service_account_from_dict(creds_dict)
    return client.open("Route Cost") 

conn = init_connection()

@st.cache_data(ttl=600)
def get_car_data():
    return pd.DataFrame(conn.worksheet("DB_รถยนต์").get_all_records())

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
# 🗺️ 4. ระบบแผนที่และการคำนวณเส้นทาง
# ==========================================
def get_coords_from_text(place_name):
    if not place_name.strip() or place_name.startswith("📍"):
        return None, None
    url = f"https://nominatim.openstreetmap.org/search?q={place_name}&format=json&limit=1"
    headers = {'User-Agent': 'RouteCostApp/1.6'}
    try:
        res = requests.get(url, headers=headers).json()
        if len(res) > 0:
            return float(res[0]['lat']), float(res[0]['lon'])
    except:
        pass
    return None, None

def get_place_name(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&accept-language=th"
    headers = {'User-Agent': 'RouteCostApp/1.6'}
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
        st.info("👇 เลือกหมุดที่ต้องการ แล้วไปคลิกบนแผนที่ทางขวาได้เลยครับ")
        col_s, col_e = st.columns(2)
        
        st.session_state.active_pin_to_set = st.radio("คุณกำลังจะปักหมุดที่ไหน?", ["🟢 จุดเริ่มต้น (Start)", "🔴 ปลายทาง (End)"], horizontal=True, key="active_pin_radio")
        
        col_s.write(f"**สถานะ (เขียว):** {'✅ ปักแล้ว' if st.session_state.pin_start else 'รอคลิก...'}")
        col_e.write(f"**สถานะ (แดง):** {'✅ ปักแล้ว' if st.session_state.pin_end else 'รอคลิก...'}")
        
        col_c, col_d = st.columns(2)
        if col_c.button("ล้างหมุดทั้งหมด", use_container_width=True):
            st.session_state.pin_start = None
            st.session_state.pin_end = None
            st.session_state.origin_text = ""
            st.session_state.dest_text = ""
            reset_calculated_data()
            st.rerun()
            
        if col_d.button("❌ ปิดโหมดปักหมุด", type="primary", use_container_width=True):
            st.session_state.map_mode_active = False
            st.rerun()

    st.divider()
    selected_car = st.selectbox("เลือกรถของคุณ", df_cars.iloc[:, 0].tolist(), on_change=reset_calculated_data) 
    
    if df_prices is not None:
        station_options = ["Average"] + [col for col in df_prices.columns if col != "Average"]
        selected_station = st.selectbox("เลือกปั๊มน้ำมัน (หรือใช้ราคาเฉลี่ย)", station_options, on_change=reset_calculated_data)
    else:
        st.error("ไม่สามารถเชื่อมต่อ API ราคาน้ำมันได้")
        selected_station = None

    # --- การคำนวณ ---
    if st.button("คำนวณการเดินทาง", type="primary"):
        start_c = None
        end_c = None
        
        if st.session_state.pin_start:
            start_c = st.session_state.pin_start
        else:
            start_c = get_coords_from_text(st.session_state.origin_text)
            
        if st.session_state.pin_end:
            end_c = st.session_state.pin_end
        else:
            end_c = get_coords_from_text(st.session_state.dest_text)
            
        if not start_c or not end_c:
            st.error("❌ กรุณาระบุจุดเริ่มต้นและปลายทางให้ครบถ้วนก่อนคำนวณครับ")
        else:
            with st.spinner('กำลังคำนวณและวาดเส้นทาง...'):
                dist, coords, start, end = get_route_data_free(start_c, end_c)
                if dist is None:
                    st.error("❌ ไม่พบเส้นทางครับ ลองปักหมุดให้ใกล้ถนนใหญ่ดูนะครับ")
                else:
                    st.session_state.calculated = True
                    st.session_state.distance = dist
                    st.session_state.route_coords = coords
                    st.session_state.start_coords = start
                    st.session_state.end_coords = end
            
    if st.session_state.calculated and st.session_state.distance is not None:
        car_info = df_cars[df_cars.iloc[:, 0] == selected_car].iloc[0]
        sheet_fuel_name = str(car_info.iloc[1]).strip()
        km_per_liter = float(car_info.iloc[2])
        api_fuel_key = FUEL_MAPPING.get(sheet_fuel_name, None)
        
        if api_fuel_key and api_fuel_key in df_prices.index:
            current_price = df_prices.loc[api_fuel_key, selected_station]
            if current_price == 0:
                st.warning(f"⚠️ ปั๊ม {selected_station} ไม่มีข้อมูลน้ำมัน '{sheet_fuel_name}'")
            else:
                total_cost = (st.session_state.distance / km_per_liter) * current_price
                st.divider()
                st.subheader("สรุปผล")
                m1, m2 = st.columns(2)
                m1.metric("ระยะทางจริง (กม.)", f"{st.session_state.distance:.2f}")
                m2.metric("ค่าน้ำมันรวม (บาท)", f"{total_cost:.2f}")
                station_display = "ราคาเฉลี่ย" if selected_station == "Average" else f"ปั๊ม {selected_station.upper()}"
                st.success(f"ℹ️ รถกินน้ำมัน {km_per_liter} km/L | {sheet_fuel_name} {station_display} ลิตรละ {current_price} บาท")

with col2:
    st.subheader("แผนที่เส้นทาง")
    m = folium.Map(location=[13.7563, 100.5018], zoom_start=5)
    
    if st.session_state.pin_start:
        folium.Marker(st.session_state.pin_start, tooltip="จุดเริ่มต้น", icon=folium.Icon(color="green")).add_to(m)
    if st.session_state.pin_end:
        folium.Marker(st.session_state.pin_end, tooltip="ปลายทาง", icon=folium.Icon(color="red")).add_to(m)

    if st.session_state.calculated and st.session_state.route_coords:
        folium.PolyLine(st.session_state.route_coords, color="blue", weight=5, opacity=0.8).add_to(m)
        folium.Marker(st.session_state.start_coords, tooltip="จุดเริ่มต้น", icon=folium.Icon(color="green", icon="play")).add_to(m)
        folium.Marker(st.session_state.end_coords, tooltip="ปลายทาง", icon=folium.Icon(color="red", icon="flag")).add_to(m)
        
    map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"], key="interactive_map")
    
    if st.session_state.map_mode_active and map_data and map_data.get("last_clicked"):
        lat = map_data["last_clicked"]["lat"]
        lon = map_data["last_clicked"]["lng"]
        clicked_coord = [lat, lon]
        
        if st.session_state.active_pin_to_set == "🟢 จุดเริ่มต้น (Start)" and st.session_state.pin_start != clicked_coord:
            st.session_state.pin_start = clicked_coord
            place_name = get_place_name(lat, lon)
            st.session_state.origin_text = f"📍 {place_name}"
            reset_calculated_data()
            st.rerun() 
            
        elif st.session_state.active_pin_to_set == "🔴 ปลายทาง (End)" and st.session_state.pin_end != clicked_coord:
            st.session_state.pin_end = clicked_coord
            place_name = get_place_name(lat, lon)
            st.session_state.dest_text = f"📍 {place_name}"
            reset_calculated_data()
            st.rerun()