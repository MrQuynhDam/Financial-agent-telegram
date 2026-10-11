import json
import os
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def fetch_single_feed(url, keywords, max_items_per_feed=5):
    """Hàm xử lý cào 1 trang RSS đơn lẻ"""
    feed_articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_items_per_feed]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            summary_raw = entry.get("summary", entry.get("description", ""))
            
            # Làm sạch HTML
            soup = BeautifulSoup(summary_raw, "html.parser")
            clean_summary = soup.get_text().strip()

            # Lọc từ khóa
            combined_text = f"{title} {clean_summary}".lower()
            if not keywords or any(kw.lower() in combined_text for kw in keywords):
                feed_articles.append({
                    "title": title,
                    "link": link,
                    "summary": clean_summary[:200] + "..." if len(clean_summary) > 200 else clean_summary
                })
    except Exception as e:
        print(f"Lỗi cào nguồn {url}: {e}")
    return feed_articles

def fetch_rss_news(rss_urls, keywords, max_items_per_feed=5):
    """Cào tin tức ĐA LUỒNG (Song song) từ tất cả URL cùng lúc"""
    articles = []
    seen_links = set()

    # Chạy song song tối đa 10 luồng cùng lúc
    with ThreadPoolExecutor(max_workers=min(len(rss_urls), 10)) as executor:
        future_to_url = {
            executor.submit(fetch_single_feed, url, keywords, max_items_per_feed): url 
            for url in rss_urls
        }
        for future in as_completed(future_to_url):
            try:
                data = future.result()
                for item in data:
                    if item["link"] not in seen_links:
                        articles.append(item)
                        seen_links.add(item["link"])
            except Exception as e:
                print(f"Lỗi luồng cào tin: {e}")

    return articles

def generate_llm_summary(config, news_items):
    """Gọi LLM API để tóm tắt bản tin (Có tự động retry khi gặp lỗi 503)"""
    if not news_items:
        return None

    top_news = news_items[:10]
    news_text = "\n\n".join([
        f"• Tiêu đề: {item['title']}\n  Tóm tắt: {item['summary']}\n  Nguồn: {item['link']}"
        for item in top_news
    ])

    prompt = f"{config['system_prompt']}\n\nDANH SÁCH TIN TỨC MỚI NHẤT:\n{news_text}"

    provider = config.get("llm_provider", "Google Gemini")
    api_key = config.get("llm_api_key", "").strip()
    model = config.get("llm_model", "gemini-3.8-flash").strip()

    if model.startswith("models/"):
        model = model.replace("models/", "")

    if provider == "Google Gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        # Cơ chế tự động thử lại tối đa 3 lần khi gặp 503
        max_retries = 3
        for attempt in range(max_retries):
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=90)
                res_json = res.json()

                if "error" in res_json:
                    err_details = res_json["error"]
                    code = err_details.get("code", 0)
                    msg = err_details.get("message", "Lỗi không xác định")

                    # Nếu dính lỗi 503 Quá tải, tạm dừng vài giây rồi thử lại
                    if code == 503 and attempt < max_retries - 1:
                        time.sleep(3 * (attempt + 1))  # Chờ 3s, 6s...
                        continue

                    raise Exception(f"Gemini API Error [{code}]: {msg}")

                return res_json['candidates'][0]['content']['parts'][0]['text']

            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                raise Exception(f"Lỗi kết nối Gemini API: {str(e)}")

    elif provider in ["OpenAI", "Groq"]:
        base_url = "https://api.openai.com/v1/chat/completions"
        if provider == "Groq":
            base_url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        res = requests.post(base_url, headers=headers, json=payload, timeout=90)
        res_json = res.json()
        if "error" in res_json:
            raise Exception(f"{provider} Error: {res_json['error'].get('message')}")
        try:
            return res_json['choices'][0]['message']['content']
        except Exception:
            raise Exception(f"Phản hồi {provider} không đúng định dạng.")

    return "Provider không hợp lệ."

def clean_html_for_telegram(text):
    """Tự động chuyển đổi các thẻ HTML không hỗ trợ thành văn bản chuẩn Telegram"""
    if not text:
        return ""
    # Chuyển thẻ <li> thành dấu đầu dòng •
    text = re.sub(r'<li[^>]*>', '• ', text)
    text = re.sub(r'</li[^>]*>', '\n', text)
    # Xóa hoàn toàn các thẻ ul, ol, p, div, h1-h6
    text = re.sub(r'</?(ul|ol|p|div|h[1-6])[^>]*>', '\n', text)
    text = re.sub(r'<br\s*/?>', '\n', text)
    # Xóa dòng trống thừa
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()

def send_telegram_message(config, message):
    """Hàm gửi tin nhắn sang Telegram"""
    token = config.get("telegram_bot_token", "").strip()
    chat_id = config.get("telegram_chat_id", "").strip()
    
    if not token or not chat_id:
        raise Exception("Chưa cấu hình Telegram Bot Token hoặc Chat ID.")
        
    # Làm sạch HTML trước khi gửi sang Telegram
    clean_message = clean_html_for_telegram(message)
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": clean_message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    res = requests.post(url, json=payload, timeout=30)
    res_json = res.json()
    
    if not res_json.get("ok"):
        raise Exception(f"Lỗi gửi Telegram: {res_json.get('description')}")
        
    return True

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
