import websocket
import json
import threading
from collections import deque
from datetime import datetime
import matplotlib
matplotlib.use("TkAgg")  # Use TkAgg backend for real-time interactive window
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from google import genai

client = genai.Client(api_key="AIzaSyBZk5mDYryEf62rHh4a_49CdZuVJQCrmg4")

# ─────────────────────────────────────────────
# SHARED STATE  (thread-safe with a lock)
# ─────────────────────────────────────────────

_lock = threading.Lock()

# Rolling window — keep the last 300 ticks on the chart
MAX_POINTS = 300

price_times  = deque(maxlen=MAX_POINTS)   # datetime objects
price_values = deque(maxlen=MAX_POINTS)   # float prices

# Every Gemini signal is stored as (datetime, price, "Buy"|"Sell")
gemini_signals: list[tuple] = []

Is_Gemini_Thinking = False


# ─────────────────────────────────────────────
# GEMINI FUNCTIONS
# ─────────────────────────────────────────────

def build_prompt(trades):
    return f"""
You are an algorithmic crypto trading analyst specializing in short-term momentum strategies.

CONTEXT:
- Asset: PEPE/USDT
- Data provided: Last 20 executed trades from Binance
- Strategy horizon: Very short-term (next trade decision only)
- No external indicators (RSI, EMA, order book, etc.)
- You must base your reasoning ONLY on the provided trade data.

OBJECTIVE:
Determine whether short-term momentum favors a BUY or SELL position.

ANALYSIS INSTRUCTIONS:
1. Analyze price progression (increasing, decreasing, choppy).
2. Evaluate trade frequency and acceleration.
3. Observe market maker behavior (m field).
4. Detect micro-momentum patterns.
5. If data is inconclusive, choose the statistically safer option.

DATA:
{trades}

OUTPUT RULES:
- Respond with exactly ONE word.
- Only allowed responses: Buy or Sell
- No explanations.
"""


def send_to_gemini(trades):
    """Run in a background thread so the WebSocket is never blocked."""
    global Is_Gemini_Thinking
    Is_Gemini_Thinking = True

    prompt = build_prompt(trades)

    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-preview",   
        contents=prompt             # 'contents' is the correct kwarg for google-genai
    )

    recommendation = response.text.strip()
    print("Gemini's recommendation:", recommendation)

    # ── Record the signal so the chart can display it ──────────────────────
    with _lock:
        if price_times and price_values:
            # Attach the signal to the latest known price point
            signal_time  = price_times[-1]
            signal_price = price_values[-1]
            gemini_signals.append((signal_time, signal_price, recommendation))

    Is_Gemini_Thinking = False


# ─────────────────────────────────────────────
# CHART FUNCTION
# ─────────────────────────────────────────────

def print_price_data():
    """
    Launch a live Matplotlib window that refreshes every 500 ms.

    • Blue line   — real-time PEPE/USDT price
    • Green  ▲    — Gemini said BUY  at that moment
    • Red    ▼    — Gemini said SELL at that moment
    """
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(14, 6))
    fig.suptitle("PEPE/USDT  —  Live Price  +  Gemini Signals",
                 fontsize=14, color="white", fontweight="bold")

    # Custom legend entries
    legend_elements = [
        Line2D([0], [0], color="#4FC3F7", linewidth=2, label="PEPE/USDT price"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#00E676",
               markersize=10, linestyle="None", label="Gemini → BUY"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="#FF5252",
               markersize=10, linestyle="None", label="Gemini → SELL"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", framealpha=0.3)

    def _refresh(_frame):
        with _lock:
            times  = list(price_times)
            prices = list(price_values)
            sigs   = list(gemini_signals)

        if len(times) < 2:
            return

        ax.clear()
        ax.set_facecolor("#0D1117")
        fig.patch.set_facecolor("#0D1117")

        # ── Price line ──────────────────────────────────────────────────────
        ax.plot(times, prices, color="#4FC3F7", linewidth=1.5, zorder=2)

        # Light fill under the curve
        ax.fill_between(times, prices,
                        min(prices) * 0.9999,
                        alpha=0.15, color="#4FC3F7", zorder=1)

        # ── Gemini signals ──────────────────────────────────────────────────
        for sig_time, sig_price, action in sigs:
            if action.lower() == "buy":
                ax.scatter(sig_time, sig_price,
                           marker="^", s=120, color="#00E676",
                           zorder=5, edgecolors="white", linewidths=0.5)
                ax.annotate("BUY",
                            xy=(sig_time, sig_price),
                            xytext=(0, 12), textcoords="offset points",
                            ha="center", va="bottom",
                            fontsize=7, color="#00E676", fontweight="bold")
            elif action.lower() == "sell":
                ax.scatter(sig_time, sig_price,
                           marker="v", s=120, color="#FF5252",
                           zorder=5, edgecolors="white", linewidths=0.5)
                ax.annotate("SELL",
                            xy=(sig_time, sig_price),
                            xytext=(0, -14), textcoords="offset points",
                            ha="center", va="top",
                            fontsize=7, color="#FF5252", fontweight="bold")

        # ── Axes formatting ─────────────────────────────────────────────────
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate(rotation=30)

        ax.set_title("PEPE/USDT  —  Live Price  +  Gemini Signals",
                     fontsize=13, color="white", fontweight="bold", pad=10)
        ax.set_ylabel("Price (USDT)", color="#AAAAAA")
        ax.tick_params(colors="#AAAAAA")
        ax.grid(color="#1E2A38", linewidth=0.5, linestyle="--")

        # Re-draw legend after ax.clear()
        ax.legend(handles=legend_elements, loc="upper left",
                  framealpha=0.3, fontsize=8)

    # Refresh every 500 ms using matplotlib's FuncAnimation
    from matplotlib.animation import FuncAnimation
    _anim = FuncAnimation(fig, _refresh, interval=500, cache_frame_data=False)

    plt.tight_layout()
    plt.show()   # blocks — must run in the main thread


# ─────────────────────────────────────────────
# WEBSOCKET FUNCTIONS
# ─────────────────────────────────────────────

def on_message(ws, message):
    global Is_Gemini_Thinking

    if not hasattr(ws, "message_count"):
        ws.message_count = 0
    if not hasattr(ws, "data"):
        ws.data = []

    data = json.loads(message)

    # Parse timestamp → datetime for the chart
    ts_ms    = data["E"]                                  # milliseconds
    ts_dt    = datetime.fromtimestamp(ts_ms / 1000)
    price    = float(data["p"])

    trade_info = {
        "symbol":       data["s"],
        "price":        data["p"],
        "timestamp":    ts_ms,
        "market_maker": data["m"],
    }

    # ── Update chart data (thread-safe) ──────────────────────────────────
    with _lock:
        price_times.append(ts_dt)
        price_values.append(price)

    if Is_Gemini_Thinking:
        print("Gemini is already processing — skipping this batch.")
    else:
        ws.data.append(trade_info)
        print(f"[{ts_dt.strftime('%H:%M:%S')}]  {trade_info['symbol']}  "
              f"price={price:.8f}  maker={trade_info['market_maker']}")
        ws.message_count += 1

    if ws.message_count >= 20:
        # Fire Gemini in a background thread — never blocks the WebSocket
        t = threading.Thread(
            target=send_to_gemini,
            args=(list(ws.data),),
            daemon=True
        )
        t.start()
        ws.message_count = 0
        ws.data = []


def on_error(ws, error):
    print("WebSocket error:", error)


def on_open(ws):
    print("✅  Connected to Binance stream — waiting for trades…")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    SOCKET = "wss://stream.binance.com:9443/ws/pepeusdt@trade"

    ws_app = websocket.WebSocketApp(
        SOCKET,
        on_message=on_message,
        on_error=on_error,
        on_open=on_open,
    )

    # Run the WebSocket in a background daemon thread
    ws_thread = threading.Thread(target=ws_app.run_forever, daemon=True)
    ws_thread.start()

    # The chart MUST run on the main thread (Matplotlib requirement)
    print_price_data()   # blocks here — close the window to quit