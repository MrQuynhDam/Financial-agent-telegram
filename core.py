import json
import os
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime

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
                
                # Làm sạch HTML
                soup = BeautifulSoup(summary_raw, "html.parser")
                clean_summary = soup.get_text().strip()

                # Lọc từ khóa
                combined_text = f"{title} {clean_summary}".lower()
                if not keywords or any(kw.lower() in combined_text for kw in keywords):
                    articles.append({
                        "title": title,
                        "link": link,
                        "summary": clean_summary[:200] + "..." if len(clean_summary) > 200 else clean_summary
                    })
                    seen_links.add(link)
        except Exception as e:
            print(f"Lỗi crawl {url}: {e}")

    return articles

def generate_llm_summary(config, news_items):
    """Gọi LLM API để tóm tắt bản tin"""
    if not news_items:
        return None

    # Lấy tối đa 10 tin tức mới nhất để tối ưu tốc độ xử lý
    top_news = news_items[:10]

    news_text = "\n\n".join([
        f"• Tiêu đề: {item['title']}\n  Tóm tắt: {item['summary']}\n  Nguồn: {item['link']}"
        for item in top_news
    ])
    
    # ... (Giữ nguyên các đoạn code bên dưới)

def send_telegram_message(token, chat_id, text):
    """Gửi bản tin sang Telegram"""
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
    """Hàm thực thi chính - Đã bọc try...except an toàn"""
    config = load_config()
    print(f"[{datetime.now()}] Đang chạy Agent...")
    
    if not config.get("telegram_bot_token") or not config.get("telegram_chat_id"):
        return False, "⚠️ Thiếu Telegram Bot Token hoặc Chat ID! Vui lòng cấu hình trong Tab API."

    if not config.get("llm_api_key"):
        return False, "⚠️ Thiếu LLM API Key! Vui lòng điền API Key trong Tab API."

    # 1. Crawl tin tức
    news = fetch_rss_news(config.get("rss_urls", []), config.get("keywords", []))
    if not news:
        return False, "ℹ️ Không tìm thấy tin tức nào khớp với bộ lọc từ khóa hiện tại."

    # 2. Gọi AI tóm tắt (Bắt lỗi an toàn)
    try:
        summary = generate_llm_summary(config, news)
    except Exception as e:
        return False, f"❌ Lỗi xử lý AI: {str(e)}"

    # 3. Gửi sang Telegram
    res = send_telegram_message(config["telegram_bot_token"], config["telegram_chat_id"], summary)
    if res.get("ok"):
        return True, f"🎉 Đã tổng hợp thành công {len(news)} tin tức và gửi qua Telegram!"
    else:
        return False, f"❌ Lỗi gửi Telegram: {res.get('description', 'Không xác định')}"
