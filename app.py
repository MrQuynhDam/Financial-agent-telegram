import streamlit as st
import json
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from core import load_config, CONFIG_FILE, run_agent_job

st.set_page_config(page_title="AI Financial News Agent", page_icon="📈", layout="wide")

# Thiết lập Scheduler chạy ẩn
@st.cache_resource
def get_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.start()
    return scheduler

scheduler = get_scheduler()

# Load cấu hình
config = load_config()

st.title("📈 Agent Trợ Lý Tài Chính & Chứng Khoán")
st.caption("Tổng hợp thông tin thị trường tự động qua LLM và Telegram")

tabs = st.tabs(["🚀 Điều khiển & Log", "⚙️ Cấu hình API & Telegram", "📰 Nguồn tin & Từ khóa", "🧠 Cấu hình Prompt AI"])

# ----------------- TAB 1: Điều khiển -----------------
with tabs[0]:
    st.subheader("Trạng thái Hoạt động")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("⚡ Chạy kích hoạt thủ công (Run Now)", type="primary"):
            with st.spinner("Đang cào tin tức, gửi AI phân tích và bắn Telegram..."):
                success, msg = run_agent_job()
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
                    
    with col2:
        schedule_hours = config.get("schedule_interval_hours", 1)
        job_id = "financial_agent_hourly_job"
        
        # Thêm/Cập nhật job chạy tự động
        if not scheduler.get_job(job_id):
            scheduler.add_job(run_agent_job, 'interval', hours=schedule_hours, id=job_id)
            
        st.info(f"⏱️ Lịch tự động: Đang quét mỗi **{schedule_hours} giờ/lần**")

# ----------------- TAB 2: API & Telegram -----------------
with tabs[1]:
    st.subheader("Cấu hình Telegram Bot & LLM Provider")
    
    with st.form("api_config_form"):
        tg_token = st.text_input("Telegram Bot Token", value=config.get("telegram_bot_token", ""), type="password")
        tg_chat_id = st.text_input("Telegram Chat ID", value=config.get("telegram_chat_id", ""))
        
        st.divider()
        
        provider = st.selectbox("Chọn LLM Provider", ["Google Gemini", "OpenAI", "Groq"], 
                                index=["Google Gemini", "OpenAI", "Groq"].index(config.get("llm_provider", "Google Gemini")))
        
        llm_key = st.text_input("LLM API Key", value=config.get("llm_api_key", ""), type="password")
        llm_model = st.text_input("Tên Model", value=config.get("llm_model", "gemini-2.5-flash"), 
                                  help="VD: gemini-2.5-flash, gpt-4o-mini, llama-3.3-70b-versatile")
        
        submitted = st.form_submit_button("💾 Lưu Cấu Hình API")
        if submitted:
            config["telegram_bot_token"] = tg_token
            config["telegram_chat_id"] = tg_chat_id
            config["llm_provider"] = provider
            config["llm_api_key"] = llm_key
            config["llm_model"] = llm_model
            
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            st.success("Đã lưu cấu hình thành công!")

# ----------------- TAB 3: Nguồn tin & Từ khóa -----------------
with tabs[2]:
    st.subheader("Cấu hình Nguồn quét tin RSS & Từ khóa lọc")
    
    with st.form("news_config_form"):
        rss_text = st.text_area("Danh sách URL RSS (Mỗi URL 1 dòng)", 
                                value="\n".join(config.get("rss_urls", [])))
        
        kw_text = st.text_input("Từ khóa ưu tiên (Phân cách bằng dấu phẩy)", 
                                value=", ".join(config.get("keywords", [])))
        
        interval = st.number_input("Tần suất quét tự động (Giờ)", min_value=1, max_value=24, 
                                   value=config.get("schedule_interval_hours", 1))
        
        submitted_news = st.form_submit_button("💾 Lưu Nguồn Tin")
        if submitted_news:
            config["rss_urls"] = [url.strip() for url in rss_text.split("\n") if url.strip()]
            config["keywords"] = [kw.strip() for kw in kw_text.split(",") if kw.strip()]
            config["schedule_interval_hours"] = interval
            
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                
            # Cập nhật lại lịch chạy
            scheduler.reschedule_job(job_id, trigger='interval', hours=interval)
            st.success("Đã lưu nguồn tin và cập nhật lại lịch quét hàng giờ!")

# ----------------- TAB 4: Prompt AI -----------------
with tabs[3]:
    st.subheader("Tùy chỉnh Prompt cho AI Agent")
    
    with st.form("prompt_config_form"):
        prompt_val = st.text_area("System Prompt (Chỉ thị phong cách phân tích & Định dạng HTML Telegram)", 
                                  value=config.get("system_prompt", ""), height=250)
        
        submitted_prompt = st.form_submit_button("💾 Lưu Prompt")
        if submitted_prompt:
            config["system_prompt"] = prompt_val
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            st.success("Đã cập nhật System Prompt thành công!")
