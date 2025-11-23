import requests
from bs4 import BeautifulSoup
from bs4 import NavigableString
import os
import json
from requests_oauthlib import OAuth1

# --- CONFIGURATION ---
URL = "https://www.teslafi.com/firmware.php"
SHOP_URLS = [
    "https://shop.tesla.com/category/charging",
    "https://shop.tesla.com/category/vehicle-accessories",
    "https://shop.tesla.com/category/apparel",
    "https://shop.tesla.com/category/lifestyle",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
}
MEMORY_FILE = "memory.json"
WAVE_THRESHOLD = 5  # Trigger alert if new detection size is >= 5

# Secrets
bot_token = os.environ.get("TELEGRAM_TOKEN")
chat_id = os.environ.get("CHAT_ID")
SHEET_WEBHOOK_URL = os.environ.get("SHEET_WEBHOOK_URL")
X_API_KEY = os.environ.get("X_API_KEY")
X_API_SECRET = os.environ.get("X_API_SECRET")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET")


def notify_sheet_new_build(version):
    if not SHEET_WEBHOOK_URL:
        return
    try:
        requests.post(
            SHEET_WEBHOOK_URL,
            json={"version": version},
            timeout=10,
        )
    except Exception as e:
        print(f"Failed to notify sheet: {e}")


def post_to_x(text):
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
        print("Missing X credentials")
        return

    auth = OAuth1(
        X_API_KEY,
        X_API_SECRET,
        X_ACCESS_TOKEN,
        X_ACCESS_TOKEN_SECRET,
    )

    url = "https://api.twitter.com/2/tweets"
    payload = {"text": text}

    try:
        r = requests.post(url, auth=auth, json=payload, timeout=10)
        if r.status_code >= 300:
            print("X post failed", r.status_code, r.text)
    except Exception as e:
        print("X post error:", e)


def format_x_new_build(version, pending):
    return f"New build spotted. Tesla has started rolling out {version}."


def format_x_wave(version, diff, pending):
    return f"A new wave for {version} is rolling out now."
    

def format_x_new_product(name, price, url):
    lines = [
        "New Product on Tesla Shop:",
        "",
        name,
    ]
    if price:
        lines.append(price)
    lines.append(url)
    return "\n".join(lines)
    

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


def scrape_tesla_shop_products():
    products = {}  # product_id -> {name, price, url}

    for category_url in SHOP_URLS:
        print(f"Fetching Tesla Shop category: {category_url}")
        try:
            r = requests.get(category_url, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"Error fetching {category_url}: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")

        # look for links to /product/ pages and grab name + nearby price
        for a in soup.select('a[href*="/product/"]'):
            name = a.get_text(strip=True)
            href = a.get("href", "")

            if not name or not href:
                continue

            # normalize full URL
            if href.startswith("http"):
                url = href
            else:
                url = "https://shop.tesla.com" + href

            # use slug after /product/ as product id
            product_id = href.split("/product/")[-1].split("?")[0].strip("/")
            if not product_id:
                continue

            if product_id in products:
                continue  # already captured from another category

            price = None

            # first try siblings after the link
            for sib in a.next_siblings:
                try:
                    if isinstance(sib, NavigableString):
                        text = str(sib).strip()
                    else:
                        text = sib.get_text(strip=True)
                except Exception:
                    continue

                if not text:
                    continue
                if "$" in text and any(ch.isdigit() for ch in text):
                    price = text
                    break

            # fallback: scan parent for a price string
            if not price:
                parent = a.parent
                if parent:
                    for node in parent.stripped_strings:
                        if "$" in node and any(ch.isdigit() for ch in node):
                            price = node
                            break

            products[product_id] = {
                "name": name,
                "price": price or "",
                "url": url,
            }

    print(f"Found {len(products)} Tesla Shop products across categories.")
    return products


def check_tesla_shop(memory):
    # memory["products"] will hold known product ids
    seen_products = memory.get("products")
    current_products = scrape_tesla_shop_products()

    # first run: seed without alerting to avoid spamming all existing items
    if not isinstance(seen_products, dict) or not seen_products:
        memory["products"] = current_products
        print(f"Initialized Tesla Shop memory with {len(current_products)} products.")
        return

    new_items = []

    for pid, info in current_products.items():
        if pid not in seen_products:
            new_items.append(info)
            seen_products[pid] = info

    if not new_items:
        print("No new Tesla Shop products.")
    else:
        print(f"Detected {len(new_items)} new Tesla Shop products.")
        for info in new_items:
            name = info["name"]
            price = info["price"]
            url = info["url"]

            # Telegram message
            msg_lines = [
                "🛒 New Product on Tesla Shop:",
                "",
                name,
            ]
            if price:
                msg_lines.append(price)
            msg_lines.append(url)

            send_telegram("\n".join(msg_lines))

            # X message
            tweet = format_x_new_product(name, price, url)
            post_to_x(tweet)

    memory["products"] = seen_products


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
                f"🚨 New Build Detected\n\n"
                f"`{version}`\n\n"
                f"Initial Rollout: {pending}   \u2013 [TeslaFi]({detail_url})"
            )
            send_telegram(msg)

            tweet_text = format_x_new_build(version, pending)
            post_to_x(tweet_text)

            notify_sheet_new_build(version)
            versions_memory[version] = pending

        # SCENARIO 2: WAVE (Same Version, big jump in pending count)
        elif pending >= last_count + WAVE_THRESHOLD:
            diff = pending - last_count
            detail_url = f"https://www.teslafi.com/firmware.php?detail={version}"
            msg = (
                f"🌊 New Wave Rolling Out\n\n"
                f"`{version}`\n\n"
                f"Rollout Size: {diff}   \u2013 [TeslaFi]({detail_url})"
            )
            send_telegram(msg)

            tweet_text = format_x_wave(version, diff, pending)
            post_to_x(tweet_text)

            versions_memory[version] = pending

        else:
            # Small or no change: just keep memory up to date
            versions_memory[version] = pending

    # Save updated per-version memory and clean old keys if present
    memory["versions"] = versions_memory
    memory.pop("last_version", None)
    memory.pop("last_count", None)

    # also check Tesla Shop for new products using the same memory.json
    check_tesla_shop(memory)
    
    save_memory(memory)


if __name__ == "__main__":
    check_teslafi()
