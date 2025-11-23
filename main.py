import requests
from bs4 import BeautifulSoup
import os
import json
import sys

# --- CONFIGURATION ---
URL = "https://www.teslafi.com/firmware.php"
# To prevent TeslaFi from blocking us, we look like a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}
MEMORY_FILE = "memory.json"

# Secrets from GitHub Environment
bot_token = os.environ.get("TELEGRAM_TOKEN")
chat_id = os.environ.get("CHAT_ID")

def send_telegram_alert(message):
    if not bot_token or not chat_id:
        print("Error: Telegram tokens not found.")
        return
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(send_url, data=data)
    except Exception as e:
        print(f"Failed to send alert: {e}")

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memory(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f)

def check_teslafi():
    print("Fetching TeslaFi data...")
    try:
        response = requests.get(URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
    except Exception as e:
        print(f"Connection error: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    
    # Logic: Find the "Software Version" table. 
    # TeslaFi structure changes, but usually the first <a> tag with a version number is the latest.
    # We look for the specific table ID or class usually found on the firmware page.
    
    # Attempt to find the main firmware table
    # Note: Scrapers break if websites change. This looks for the first row of data.
    versions_found = []
    
    # Targeting the main table (often has id 'table' or specific class, simplified approach below)
    # We search for links that look like firmware versions (e.g., "2024.44")
    for link in soup.find_all("a"):
        text = link.get_text().strip()
        # rudimentary check if it looks like a version number (starts with 202)
        if text.startswith("202") and "." in text and len(text) < 20:
            # We found a version candidate
            versions_found.append(text)
    
    if not versions_found:
        print("No versions found. Website structure might have changed.")
        return

    # The top one is usually the latest
    latest_version = versions_found[0]
    print(f"Latest detected version: {latest_version}")

    # Load previous state
    memory = load_memory()
    last_known = memory.get("last_version", "None")

    # --- DECISION LOGIC ---
    
    # 1. NEW VERSION DETECTED
    if latest_version != last_known:
        msg = f"🚨 **New Tesla Firmware Detected!**\n\nVersion: `{latest_version}`\nseen on TeslaFi.com"
        print("New version! Sending alert.")
        send_telegram_alert(msg)
        
        # Update memory
        memory["last_version"] = latest_version
        save_memory(memory)
    else:
        print(f"No change. Still {last_known}")

if __name__ == "__main__":
    check_teslafi()
