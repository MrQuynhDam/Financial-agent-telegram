import json
import os
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def fetch_rss_news(rss_urls, keywords, max_items_per_feed=5):
    """Crawl tin tức từ danh sách RSS và lọc theo từ khóa"""
    articles = []
    seen_links = set()

    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_items_per_feed]:
                link = entry.get("link", "")
                if link in seen_links:
                    continue
                
                title = entry.get("title", "")
                summary_raw = entry.get("summary", entry.get("description", ""))
                
                # Làm sạch HTML trong summary
                soup = BeautifulSoup(summary_raw, "html.parser")
                clean_summary = soup.get_text().strip()

                # Kiểm tra từ khóa
                combined_text = f"{title} {clean_summary}".lower()
                if not keywords or any(kw.lower() in combined_text for kw in keywords):
                    articles.append({
                        "title": title,
                        "link": link,
                        "summary": clean_summary[:200] + "..." if len(clean_summary) > 200 else clean_summary
                    })
                    seen_links.add(link)
        except Exception as e:
            print(f"Lỗi khi cào dữ liệu từ {url}: {e}")

    return articles

def generate_llm_summary(config, news_items):
    """Gọi LLM API (Gemini hoặc OpenAI) để tóm tắt"""
    if not news_items:
        return None

    news_text = "\n\n".join([
        f"• Tiêu đề: {item['title']}\n  Tóm tắt: {item['summary']}\n  Nguồn: {item['link']}"
        for item in news_items
    ])

    prompt = f"{config['system_prompt']}\n\nDANH SÁCH TIN TỨC MỚI NHẤT:\n{news_text}"

    provider = config.get("llm_provider", "Google Gemini")
    api_key = config.get("llm_api_key", "")
    model = config.get("llm_model", "gemini-2.5-flash")

    if provider == "Google Gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, json=payload, timeout=30)
        res_json = res.json()
        try:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        except Exception:
            raise Exception(f"Lỗi Gemini API: {res_json}")

    elif provider in ["OpenAI", "Groq", "Custom OpenAI-Compatible"]:
        base_url = "https://api.openai.com/v1/chat/completions"
        if provider == "Groq":
            base_url = "https://api.groq.com/openai/v1/chat/completions"
        
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        res = requests.post(base_url, headers=headers, json=payload, timeout=30)
        res_json = res.json()
        try:
            return res_json['choices'][0]['message']['content']
        except Exception:
            raise Exception(f"Lỗi OpenAI API: {res_json}")

    return "Cấu hình AI Provider không hợp lệ."

def send_telegram_message(token, chat_id, text):
    """Gửi bản tin đã tổng hợp qua Telegram Bot API"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    response = requests.post(url, json=payload, timeout=15)
    return response.json()

def run_agent_job():
    """Hàm chạy quy trình tổng hợp & gửi tin"""
    config = load_config()
    print(f"[{datetime.now()}] Bắt đầu quy trình chạy Agent...")
    
    if not config.get("telegram_bot_token") or not config.get("telegram_chat_id"):
        return False, "Thiếu Telegram Bot Token hoặc Chat ID!"

    # 1. Crawl tin tức
    news = fetch_rss_news(config.get("rss_urls", []), config.get("keywords", []))
    if not news:
        return False, "Không phát hiện tin tức mới đáp ứng bộ lọc từ khóa."

    # 2. Tổng hợp bằng AI
    summary = generate_llm_summary(config, news)
    
    # 3. Gửi Telegram
    res = send_telegram_message(config["telegram_bot_token"], config["telegram_chat_id"], summary)
    if res.get("ok"):
        return True, f"Đã gửi thành công {len(news)} tin tức lên Telegram!"
    else:
        return False, f"Lỗi Telegram: {res.get('description')}"
