import time
import hmac
import hashlib
import requests
import logging
import os
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


def sign(params):
    query = '&'.join(f"{k}={params[k]}" for k in sorted(params))
    return hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()


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
    url = f"{API_BASE}/ticker/price"
    try:
        resp = requests.get(url, params={"symbol": SYMBOL})
        data = resp.json()
        if "price" in data:
            price = float(data["price"])
            send_telegram_alert(f"📊 *{SYMBOL} Price Update:* `{price}`")
            return price
        else:
            logging.warning(f"Unexpected price response: {data}")
            return TARGET_PRICE
    except Exception as e:
        logging.error(f"Price fetch error: {e}")
        return TARGET_PRICE


def get_balance(asset):
    url = f"{API_BASE}/account"
    params = {
        "timestamp": int(time.time() * 1000)
    }
    params["signature"] = sign(params)
    headers = {"X-CH-APIKEY": API_KEY, "X-CH-APIKEY": *}

    try:
        resp = requests.get(url, headers=headers, params=params)
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
    url = f"{API_BASE}/api/v3/order"
    params = {
        "symbol": SYMBOL,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": ORDER_SIZE,
        "price": f"{price:.6f}",
        "timestamp": int(time.time() * 1000)
    }
    params["signature"] = sign(params)
    headers = {"X-CH-APIKEY": API_KEY, "X-CH-APIKEY": *}
    try:
        resp = requests.post(url, headers=headers, params=params)
        data = resp.json()
        if "orderId" in data:
            logging.info(f"Placed {side} order at {price}")
        else:
            logging.warning(f"Order error: {data}")
    except Exception as e:
        logging.error(f"Error placing {side} order: {e}")


def cancel_all_orders():
    url = f"{API_BASE}/openOrders"
    params = {
        "symbol": SYMBOL,
        "timestamp": int(time.time() * 1000)
    }
    params["signature"] = sign(params)
    headers = {"X-CH-APIKEY": API_KEY, "X-CH-APIKEY": *}

    try:
        resp = requests.get(url, headers=headers, params=params)
        orders = resp.json()

        if isinstance(orders, dict) and "code" in orders:
            logging.warning(f"Cancel Orders Error: {orders}")
            return
        if not isinstance(orders, list):
            logging.warning(f"Unexpected orders response: {orders}")
            return

        for order in orders:
            cancel_params = {
                "symbol": SYMBOL,
                "orderId": order["orderId"],
                "timestamp": int(time.time() * 1000)
            }
            cancel_params["signature"] = sign(cancel_params)
            cancel_url = f"{API_BASE}/api/v3/order"
            requests.delete(cancel_url, headers=headers, params=cancel_params)
            logging.info(f"Cancelled Order {order['orderId']} [{order['side']}]")

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
