import requests
from bs4 import BeautifulSoup
import os
import json

# --- CONFIGURATION ---
URL = "https://www.teslafi.com/firmware.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}
MEMORY_FILE = "memory.json"
WAVE_THRESHOLD = 5  # Trigger alert if new detection size is >= 5

# Secrets
bot_token = os.environ.get("TELEGRAM_TOKEN")
chat_id = os.environ.get("CHAT_ID")

def send_telegram(message):
    if not bot_token or not chat_id:
        print("Error: Missing Telegram tokens.")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=data)
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
    
    # --- LOGIC: Collect all builds in the fleet table ---
    builds = {}  # version -> pending installs

    for row in soup.find_all("tr"):
        cols = row.find_all("td")
        if not cols:
            continue

        text = cols[0].get_text().strip()

        # Valid version row
        if text.startswith("20") and "." in text and len(text) < 25:
            # skip rows that do not even have a pending column
            if len(cols) < 4:
                continue

            try:
                # Col 3 is the pending installs (your debug showed 3: '44')
                pending_text = cols[3].get_text().strip().replace(",", "")
                pending = int(pending_text) if pending_text.isdigit() else 0
            except Exception as e:
                print(f"Error parsing columns for version {text}: {e}")
                pending = 0

            # only take the first row for each version (ignore later ones)
            if text not in builds:
                builds[text] = pending

    if not builds:
        print("Could not find any version data. Structure may have changed.")
        return

    # --- COMPARE WITH MEMORY (per version) ---
    memory = load_memory()

    # Backward compatibility with old schema that used single last_version / last_count
    versions_memory = memory.get("versions")
    if versions_memory is None:
        versions_memory = {}
        if "last_version" in memory:
            versions_memory[memory["last_version"]] = memory.get("last_count", 0)

    print("Current pending counts:")
    for v, p in builds.items():
        last = versions_memory.get(v, 0)
        print(f"{v}: {p} (previous {last})")

    # --- DECISION TREE PER BUILD ---
    for version, pending in builds.items():
        last_count = versions_memory.get(version, 0)

        # SCENARIO 1: NEW BUILD (not seen before in memory)
        if version not in versions_memory:
            detail_url = f"https://www.teslafi.com/firmware.php?detail={version}"
            msg = (
                f"**🚨 New Build Detected**: `{version}`\n\n"
                f"Initial Rollout: {pending}  \u2013 [TeslaFi]({detail_url})"
            )
            send_telegram(msg)
            versions_memory[version] = pending

        # SCENARIO 2: WAVE (Same Version, big jump in pending count)
        elif pending >= last_count + WAVE_THRESHOLD:
            diff = pending - last_count
            detail_url = f"https://www.teslafi.com/firmware.php?detail={version}"
            msg = (
                f"🌊 New wave for `{version}`\n\n"
                f"Rollout Size: {diff}  \u2013 [TeslaFi]({detail_url})"
            )
            send_telegram(msg)
            versions_memory[version] = pending

        else:
            # Small or no change: just keep memory up to date
            versions_memory[version] = pending

    # Save updated per-version memory and clean old keys if present
    memory["versions"] = versions_memory
    memory.pop("last_version", None)
    memory.pop("last_count", None)
    save_memory(memory)

if __name__ == "__main__":
    check_teslafi()
