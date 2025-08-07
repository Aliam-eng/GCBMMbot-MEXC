import time
import hmac
import hashlib
import requests
import logging
import os
import json
from dotenv import load_dotenv

# === LOAD .env CONFIG ===
load_dotenv()

API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
SYMBOL = os.getenv('SYMBOL')
TARGET_PRICE = float(os.getenv('TARGET_PRICE'))
SPREAD_PERCENT = float(os.getenv('SPREAD_PERCENT'))
ORDER_SIZE = float(os.getenv('ORDER_SIZE'))
PRICE_FLOOR = float(os.getenv('PRICE_FLOOR'))
PRICE_CEIL = float(os.getenv('PRICE_CEIL'))
API_BASE = os.getenv('API_BASE')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_USER_IDS = os.getenv('TELEGRAM_USER_IDS').split(',')

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')

def sign(timestamp, method, request_path, body_json=""):
    message = f"{timestamp}{method.upper()}{request_path}{body_json}"
    signature = hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return signature

def send_telegram_alert(message):
    for user_id in TELEGRAM_USER_IDS:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": user_id.strip(),
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            requests.post(url, json=payload)
        except Exception as e:
            logging.error(f"Telegram error: {e}")

def get_price():
    url = f"{API_BASE}/sapi/v2/ticker"
    params = {"symbol": SYMBOL}
    try:
        resp = requests.get(url, params=params)
        data = resp.json()
        if 'last' in data:
            price = float(data['last'])
            send_telegram_alert(f"📊 *{SYMBOL} Price Update:* `{price}`")
            return price
        else:
            logging.warning(f"Unexpected price response: {data}")
            return TARGET_PRICE
    except Exception as e:
        logging.error(f"Price fetch error: {e}")
        return TARGET_PRICE

def get_balance(asset):
    timestamp = str(int(time.time() * 1000))
    method = "GET"
    request_path = "/sapi/v1/account"
    signature = sign(timestamp, method, request_path)

    headers = {
        "X-CH-APIKEY": API_KEY,
        "X-CH-TS": timestamp,
        "X-CH-SIGN": signature
    }

    url = f"{API_BASE}{request_path}"
    try:
        resp = requests.get(url, headers=headers)
        data = resp.json()
        if "balances" in data:
            for item in data["balances"]:
                if item["asset"] == asset:
                    return float(item["free"])
        else:
            logging.warning(f"Balance fetch error: {data}")
    except Exception as e:
        logging.error(f"Balance fetch failed: {e}")
    return 0.0

def place_order(side, price):
    timestamp = str(int(time.time() * 1000))
    method = "POST"
    request_path = "/sapi/v2/order"
    body = {
        "symbol": SYMBOL,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": ORDER_SIZE,
        "price": f"{price:.6f}"
    }
    body_json = json.dumps(body, separators=(',', ':'))
    signature = sign(timestamp, method, request_path, body_json)

    headers = {
        "X-CH-APIKEY": API_KEY,
        "X-CH-TS": timestamp,
        "X-CH-SIGN": signature,
        "Content-Type": "application/json"
    }

    url = f"{API_BASE}{request_path}"
    try:
        resp = requests.post(url, headers=headers, data=body_json)
        data = resp.json()
        if "orderId" in data:
            logging.info(f"✅ Placed {side} order at {price}")
        else:
            logging.warning(f"⚠️ Order error: {data}")
    except Exception as e:
        logging.error(f"Error placing {side} order: {e}")

def cancel_all_orders():
    try:
        # Step 1: Get open orders
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        request_path = "/sapi/v2/openOrders"
        query = f"symbol={SYMBOL}"
        signature = sign(timestamp, method, request_path)

        headers = {
            "X-CH-APIKEY": API_KEY,
            "X-CH-TS": timestamp,
            "X-CH-SIGN": signature
        }

        url = f"{API_BASE}{request_path}?{query}"
        resp = requests.get(url, headers=headers)
        orders = resp.json()

        if isinstance(orders, dict) and "code" in orders:
            logging.warning(f"Open Orders Error: {orders}")
            return
        if not isinstance(orders, list):
            logging.warning(f"Unexpected open orders response: {orders}")
            return

        # Step 2: Cancel each order using POST /sapi/v2/cancel
        for order in orders:
            cancel_timestamp = str(int(time.time() * 1000))
            cancel_method = "POST"
            cancel_path = "/sapi/v2/cancel"
            cancel_body = {
                "symbol": SYMBOL,
                "orderId": order["orderId"]
            }
            cancel_body_json = json.dumps(cancel_body, separators=(',', ':'))
            cancel_signature = sign(cancel_timestamp, cancel_method, cancel_path, cancel_body_json)

            cancel_headers = {
                "X-CH-APIKEY": API_KEY,
                "X-CH-TS": cancel_timestamp,
                "X-CH-SIGN": cancel_signature,
                "Content-Type": "application/json"
            }

            cancel_url = f"{API_BASE}{cancel_path}"
            cancel_resp = requests.post(cancel_url, headers=cancel_headers, data=cancel_body_json)
            cancel_result = cancel_resp.json()

            if "status" in cancel_result and cancel_result["status"] == "CANCELED":
                logging.info(f"✅ Cancelled Order {order['orderId']}")
            else:
                logging.warning(f"⚠️ Failed to cancel {order['orderId']}: {cancel_result}")

    except Exception as e:
        logging.error(f"Error canceling orders: {e}")

def main():
    while True:
        try:
            current_price = get_price()
            time.sleep(10)

            spread = TARGET_PRICE * SPREAD_PERCENT
            bid_price = max(TARGET_PRICE - spread, PRICE_FLOOR)
            ask_price = min(TARGET_PRICE + spread, PRICE_CEIL)

            logging.info(f"Target: {TARGET_PRICE} | Bid: {bid_price:.6f} | Ask: {ask_price:.6f} | Market: {current_price:.6f}")

            cancel_all_orders()
            time.sleep(10)

            base_asset = SYMBOL[:-4]
            quote_asset = SYMBOL[-4:]

            base_balance = get_balance(base_asset)
            time.sleep(10)

            quote_balance = get_balance(quote_asset)
            time.sleep(10)

            required_quote = bid_price * ORDER_SIZE
            required_base = ORDER_SIZE

            if quote_balance >= required_quote:
                place_order("BUY", bid_price)
            else:
                msg = f"❗ Not enough {quote_asset} to BUY: Have {quote_balance:.2f}, need {required_quote:.2f}"
                logging.warning(msg)
                send_telegram_alert(msg)
            time.sleep(10)

            if base_balance >= required_base:
                place_order("SELL", ask_price)
            else:
                msg = f"❗ Not enough {base_asset} to SELL: Have {base_balance:.2f}, need {required_base:.2f}"
                logging.warning(msg)
                send_telegram_alert(msg)
            time.sleep(10)

        except Exception as e:
            logging.error(f"Error in loop: {e}")
            send_telegram_alert(f"❌ Bot Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
