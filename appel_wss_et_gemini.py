import websocket
import json
from google import genai

client = genai.Client(api_key="AIzaSyBZk5mDYryEf62rHh4a_49CdZuVJQCrmg4")


def build_prompt(trades):
    return f"""
You are a professional market analyst.
Here are the last trades:
{trades}

Answer in one word only: Buy or Sell
"""

def on_message(ws, message):
    if not hasattr(ws, "message_count"):
        ws.message_count = 0
    if not hasattr(ws, "data"):
        ws.data = []

    data = json.loads(message)

    trade_info = {
        "symbol": data["s"],
        "price": data["p"],
        "timestamp": data["E"],
        "market_maker": data["m"]
    }

    ws.data.append(trade_info)
    print(trade_info)

    ws.message_count += 1

    if ws.message_count >= 20:
        print("Envoi à Gemini...")

        prompt = build_prompt(ws.data)

        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt
        )

        print("Gemini:", response.text)

        ws.message_count = 0
        ws.data = []

socket = "wss://stream.binance.com:9443/ws/pepeusdt@trade"

ws = websocket.WebSocketApp(socket, on_message=on_message)
ws.run_forever()
