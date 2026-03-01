import websocket
import json
from google import genai
import socket
client = genai.Client(api_key="AIzaSyBZk5mDYryEf62rHh4a_49CdZuVJQCrmg4")  
# I hardcoded the Gemini API key because this is a free tier project.
# If I had a paid plan, I would store it in a .env file and add it to .gitignore.

# Global flag to track if Gemini is processing
Is_Gemini_Thinking = False

#========================================
# GEMINI FUNCTIONS
#========================================

def build_prompt(trades):  
    # Small function to build the prompt sent to Gemini.
    # We provide the last 20 trades and ask for a recommendation
    # for the next trade: either Buy or Sell.
    
    # This is cleaner than building the prompt directly inside
    # the on_message function and allows us to separate concerns.
    
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
# the prompt is designed to be clear and concise, providing Gemini with specific instructions on how to analyze the trade data and what kind of response is expected.
# Later, we could ask Gemini to return a JSON-formatted response
# (that we could process like the Binance API),
# including more details such as recommended entry price,
# stop loss, take profit, etc.
# But for now, we keep it simple to test the integration.

def send_to_gemini(trades):
    global Is_Gemini_Thinking
    Is_Gemini_Thinking = True  
    # We set this flag to True to indicate that Gemini is processing a request.
    # This will prevent us from adding new trades to the data array
    # while we wait for Gemini's response.

    prompt = build_prompt(trades)  
    # We build the prompt using the function defined above.

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        input=prompt
    )  
    # We send the prompt to Gemini and wait for the response.
    # The generate_content method is used to get a text response based on the provided prompt.

    print("Gemini's recommendation:", response.text)  
    # We log Gemini's recommendation to verify that we receive it correctly.

    Is_Gemini_Thinking = False  
    # Once we have received and logged the response, we set the flag back to False
    # to allow new trades to be added to the data array.


#========================================
# WSS FUNCTIONS
#========================================

def on_message(ws, message):  
    # Callback function triggered every time a new trade message is received
    
    if not hasattr(ws, "message_count"):
        ws.message_count = 0  
        # We use a WebSocketApp object attribute to count received messages.
        # Once we receive 20 messages, we send the data to Gemini
        # and reset the counter.
        
    if not hasattr(ws, "data"):
        ws.data = []  
        # We also create an attribute to store received trade data.
        # This will be used to build the prompt sent to Gemini.
    data = json.loads(message)   

    trade_info = {
        "symbol": data["s"],
        "price": data["p"],  
        # After analyzing the data format returned by the Binance API,
        # I created a new dictionary to extract and format
        # the relevant information.
        "timestamp": data["E"],
        "market_maker": data["m"]
    }

    if Is_Gemini_Thinking:
        print("Gemini is already processing a request, not adding the trades to the data array.")
    else:
        ws.data.append(trade_info)  
        # We add the trade information to the data array
        # that will be sent to Gemini only if he is not already processing a request.
        print("Received trade_info:", trade_info)  
        # Log the trade information to ensure everything works correctly.

        ws.message_count += 1  
        # Increment the message counter whenever a new trade is received.
        # This allows us to know when we reach 20 messages.

    if ws.message_count >= 20:  
        # Once we have collected 20 trades,
        # we send the data to Gemini for a recommendation.
        send_to_gemini(ws.data)
        ws.message_count = 0
        ws.data = []

def on_error(ws, error):
    print("WebSocket error:", error)

ws = websocket.WebSocketApp(
    socket,
    on_message=on_message,
    on_error=on_error
)

socket = "wss://stream.binance.com:9443/ws/pepeusdt@trade"  
# This is where I defined the endpoint to connect to the data stream.
# See the README and JOURNAL_DE_BORD to understand why this one was chosen.

ws = websocket.WebSocketApp(socket, on_message=on_message)  
# The on_message function is called each time a trade is received.



ws.run_forever()  
# When the daemon is launched, it runs indefinitely,
# continuously processing the received data.


# Read the README and the JOURNAL_DE_BORD for more details
# about the implementation and the design choices made in this code.