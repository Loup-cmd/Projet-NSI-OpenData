import websocket
import json
import threading
from collections import deque
from datetime import datetime
import matplotlib
matplotlib.use("TkAgg")  # Forcer le backend TkAgg pour afficher une fenêtre interactive en temps réel
                         # (obligatoire hors environnement Jupyter / sans display virtuel)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from google import genai

# Initialisation du client Gemini avec la clé API
# Ce client sera utilisé pour envoyer les données de trades et recevoir une recommandation BUY/SELL
client = genai.Client(api_key="AIzaSyBZk5mDYryEf62rHh4a_49CdZuVJQCrmg4")

# ─────────────────────────────────────────────
# ÉTAT PARTAGÉ  (protégé par un verrou thread-safe)
# ─────────────────────────────────────────────
# Ce script utilise plusieurs threads (WebSocket, Gemini, Matplotlib).
# Toute donnée partagée entre threads est protégée par _lock pour éviter les race conditions.

_lock = threading.Lock()

# Fenêtre glissante : on ne conserve que les 300 derniers ticks pour le graphique.
# deque(maxlen=N) supprime automatiquement les éléments les plus anciens quand la limite est atteinte.
MAX_POINTS = 300

price_times  = deque(maxlen=MAX_POINTS)   # Horodatages (objets datetime) des trades reçus
price_values = deque(maxlen=MAX_POINTS)   # Prix correspondants (float, en USDT)

# Liste de tous les signaux générés par Gemini, sous forme de tuples : (datetime, prix, "Buy"|"Sell")
# Cette liste est lue par le thread graphique pour afficher les marqueurs sur la courbe
gemini_signals: list[tuple] = []

# Drapeau booléen indiquant si Gemini est actuellement en train de traiter un batch de trades.
# Permet d'éviter d'envoyer un nouveau batch pendant qu'un autre est en cours d'analyse.
Is_Gemini_Thinking = False


# ─────────────────────────────────────────────
# FONCTIONS GEMINI
# ─────────────────────────────────────────────

def build_prompt(trades):
    """
    Construit le prompt textuel envoyé à Gemini à partir d'un batch de 20 trades.

    Le prompt définit :
    - Le contexte (asset, source des données, horizon de décision)
    - Les contraintes d'analyse (uniquement les données fournies, pas d'indicateurs externes)
    - Les données brutes des 20 derniers trades exécutés
    - Le format de réponse attendu : un seul mot, "Buy" ou "Sell"

    Paramètres :
        trades (list[dict]) : liste des 20 derniers trades avec symbole, prix, timestamp, market_maker

    Retourne :
        str : le prompt formaté prêt à être envoyé à l'API Gemini
    """
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
    """
    Envoie un batch de 20 trades à l'API Gemini et enregistre le signal renvoyé.

    Cette fonction est toujours exécutée dans un thread secondaire (daemon) afin de
    ne jamais bloquer le thread WebSocket qui reçoit les données en temps réel.

    Déroulement :
        1. Passe Is_Gemini_Thinking à True pour bloquer les envois concurrents
        2. Construit le prompt et appelle l'API Gemini
        3. Récupère la recommandation ("Buy" ou "Sell")
        4. Enregistre le signal (timestamp + prix courant + action) dans gemini_signals
        5. Remet Is_Gemini_Thinking à False pour autoriser le prochain batch

    Paramètres :
        trades (list[dict]) : snapshot des 20 derniers trades au moment de l'appel
    """
    global Is_Gemini_Thinking
    Is_Gemini_Thinking = True

    prompt = build_prompt(trades)

    # Appel synchrone à l'API Gemini — bloquant, mais isolé dans son propre thread
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=prompt             # 'contents' est le paramètre correct pour google-genai
    )

    recommendation = response.text.strip()
    print("Gemini's recommendation:", recommendation)

    # Enregistrement du signal dans la liste partagée, protégé par le verrou
    # Le signal est ancré au dernier prix connu au moment de la réponse de Gemini
    with _lock:
        if price_times and price_values:
            signal_time  = price_times[-1]   # Dernier timestamp reçu du WebSocket
            signal_price = price_values[-1]  # Dernier prix reçu du WebSocket
            gemini_signals.append((signal_time, signal_price, recommendation))

    Is_Gemini_Thinking = False


# ─────────────────────────────────────────────
# FONCTION GRAPHIQUE
# ─────────────────────────────────────────────

def print_price_data():
    """
    Ouvre une fenêtre Matplotlib interactive et rafraîchit le graphique toutes les 500 ms.

    Affiche :
        • Ligne bleue  — courbe de prix PEPE/USDT en temps réel
        • Triangle ▲ vert  — signal BUY de Gemini (avec annotation textuelle)
        • Triangle ▼ rouge — signal SELL de Gemini (avec annotation textuelle)

    Architecture :
        - FuncAnimation appelle _refresh() toutes les 500 ms dans le thread principal
        - _refresh() copie les données partagées sous verrou puis redessine le graphe
        - plt.show() bloque le thread principal — fermer la fenêtre termine le programme

    Note : Matplotlib doit impérativement tourner dans le thread principal (contrainte Tkinter/Qt).
    """
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(14, 6))
    fig.suptitle("PEPE/USDT  —  Live Price  +  Gemini Signals",
                 fontsize=14, color="white", fontweight="bold")

    # Définition des entrées de légende personnalisées (créées une seule fois, réutilisées après chaque clear)
    legend_elements = [
        Line2D([0], [0], color="#4FC3F7", linewidth=2, label="PEPE/USDT price"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor="#00E676",
               markersize=10, linestyle="None", label="Gemini → BUY"),
        Line2D([0], [0], marker="v", color="w", markerfacecolor="#FF5252",
               markersize=10, linestyle="None", label="Gemini → SELL"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", framealpha=0.3)

    def _refresh(_frame):
        """
        Callback appelé par FuncAnimation toutes les 500 ms.

        Copie atomiquement les données partagées (sous verrou), puis :
            1. Efface les axes (ax.clear) pour repartir d'une ardoise propre
            2. Trace la courbe de prix et un remplissage sous la courbe
            3. Itère sur gemini_signals pour placer les marqueurs BUY/SELL
            4. Formate les axes (dates, couleurs, grille, légende)

        Le paramètre _frame est fourni par FuncAnimation mais non utilisé ici.
        """
        # Copie thread-safe des données partagées pour éviter de tenir le verrou pendant le rendu
        with _lock:
            times  = list(price_times)
            prices = list(price_values)
            sigs   = list(gemini_signals)

        # Attendre d'avoir au moins 2 points pour pouvoir tracer une ligne
        if len(times) < 2:
            return

        ax.clear()
        ax.set_facecolor("#0D1117")
        fig.patch.set_facecolor("#0D1117")

        # ── Tracé de la courbe de prix ──────────────────────────────────────
        ax.plot(times, prices, color="#4FC3F7", linewidth=1.5, zorder=2)

        # Remplissage translucide sous la courbe (effet "area chart")
        ax.fill_between(times, prices,
                        min(prices) * 0.9999,   # Plancher légèrement sous le prix min
                        alpha=0.15, color="#4FC3F7", zorder=1)

        # ── Tracé des signaux Gemini ────────────────────────────────────────
        # Chaque signal est dessiné à sa position temporelle et prix exacts
        for sig_time, sig_price, action in sigs:
            if action.lower() == "buy":
                # Triangle vert pointant vers le haut = signal d'achat
                ax.scatter(sig_time, sig_price,
                           marker="^", s=120, color="#00E676",
                           zorder=5, edgecolors="white", linewidths=0.5)
                ax.annotate("BUY",
                            xy=(sig_time, sig_price),
                            xytext=(0, 12), textcoords="offset points",
                            ha="center", va="bottom",
                            fontsize=7, color="#00E676", fontweight="bold")
            elif action.lower() == "sell":
                # Triangle rouge pointant vers le bas = signal de vente
                ax.scatter(sig_time, sig_price,
                           marker="v", s=120, color="#FF5252",
                           zorder=5, edgecolors="white", linewidths=0.5)
                ax.annotate("SELL",
                            xy=(sig_time, sig_price),
                            xytext=(0, -14), textcoords="offset points",
                            ha="center", va="top",
                            fontsize=7, color="#FF5252", fontweight="bold")

        # ── Formatage des axes ──────────────────────────────────────────────
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate(rotation=30)  # Rotation des labels de l'axe X pour lisibilité

        ax.set_title("PEPE/USDT  —  Live Price  +  Gemini Signals",
                     fontsize=13, color="white", fontweight="bold", pad=10)
        ax.set_ylabel("Price (USDT)", color="#AAAAAA")
        ax.tick_params(colors="#AAAAAA")
        ax.grid(color="#1E2A38", linewidth=0.5, linestyle="--")

        # Réenregistrement de la légende après ax.clear() (qui l'efface)
        ax.legend(handles=legend_elements, loc="upper left",
                  framealpha=0.3, fontsize=8)

    # FuncAnimation appelle _refresh toutes les 500 ms
    # cache_frame_data=False évite la mise en cache des frames (données changent à chaque appel)
    from matplotlib.animation import FuncAnimation
    _anim = FuncAnimation(fig, _refresh, interval=500, cache_frame_data=False)

    plt.tight_layout()
    plt.show()   # Bloquant — le programme tourne tant que la fenêtre est ouverte


# ─────────────────────────────────────────────
# FONCTIONS WEBSOCKET
# ─────────────────────────────────────────────

def on_message(ws, message):
    """
    Callback déclenché à chaque trade reçu depuis le stream Binance.

    Pipeline de traitement :
        1. Désérialisation du message JSON
        2. Extraction du timestamp (converti en datetime) et du prix
        3. Ajout du tick dans les deques partagées (thread-safe) → mise à jour du graphique
        4. Si Gemini est libre ET que 20 trades ont été accumulés :
               → Lancement d'un thread daemon pour envoyer le batch à Gemini
               → Remise à zéro du compteur et du buffer local

    Attributs dynamiques attachés à l'objet ws :
        ws.message_count (int)      : nombre de messages accumulés depuis le dernier envoi Gemini
        ws.data (list[dict])        : buffer des trades en attente d'analyse

    Structure d'un message Binance (stream @trade) :
        {
          "E": <timestamp ms>,   # Event time
          "s": <symbol>,         # Ex : "PEPEUSDT"
          "p": <price str>,      # Prix d'exécution
          "m": <bool>            # True = vendeur est market maker (vente agressive)
        }
    """
    global Is_Gemini_Thinking

    # Initialisation des attributs la première fois que le callback est appelé
    if not hasattr(ws, "message_count"):
        ws.message_count = 0
    if not hasattr(ws, "data"):
        ws.data = []

    data = json.loads(message)

    # Conversion du timestamp millisecondes → objet datetime pour le graphique
    ts_ms    = data["E"]
    ts_dt    = datetime.fromtimestamp(ts_ms / 1000)
    price    = float(data["p"])

    # Structuration des données pertinentes du trade pour l'analyse Gemini
    trade_info = {
        "symbol":       data["s"],
        "price":        data["p"],
        "timestamp":    ts_ms,
        "market_maker": data["m"],   # True si le vendeur est market maker (indique pression vendeuse)
    }

    # Mise à jour thread-safe des deques partagées avec le graphique
    with _lock:
        price_times.append(ts_dt)
        price_values.append(price)

    if Is_Gemini_Thinking:
        # Gemini traite déjà un batch : on skip ce trade pour ne pas surcharger l'API
        print("Gemini is already processing — skipping this batch.")
    else:
        ws.data.append(trade_info)
        print(f"[{ts_dt.strftime('%H:%M:%S')}]  {trade_info['symbol']}  "
              f"price={price:.8f}  maker={trade_info['market_maker']}")
        ws.message_count += 1

    if ws.message_count >= 20:
        # Seuil atteint : on envoie le batch de 20 trades à Gemini dans un thread séparé
        # → daemon=True : le thread s'arrête automatiquement si le programme principal se termine
        t = threading.Thread(
            target=send_to_gemini,
            args=(list(ws.data),),   # Snapshot de la liste au moment du lancement
            daemon=True
        )
        t.start()
        # Remise à zéro du compteur et du buffer pour le prochain batch
        ws.message_count = 0
        ws.data = []


def on_error(ws, error):
    """Callback déclenché en cas d'erreur WebSocket (réseau, déconnexion, etc.)."""
    print("WebSocket error:", error)


def on_open(ws):
    """Callback déclenché à la connexion initiale au stream Binance."""
    print("✅  Connected to Binance stream — waiting for trades…")


# ─────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # URL du stream WebSocket Binance pour les trades en temps réel sur PEPE/USDT
    # Le suffixe @trade indique qu'on s'abonne au flux "trade" (chaque trade exécuté)
    SOCKET = "wss://stream.binance.com:9443/ws/pepeusdt@trade"

    ws_app = websocket.WebSocketApp(
        SOCKET,
        on_message=on_message,
        on_error=on_error,
        on_open=on_open,
    )

    # Lancement du WebSocket dans un thread secondaire (daemon)
    # → daemon=True : s'arrête automatiquement si le thread principal (graphique) se termine
    ws_thread = threading.Thread(target=ws_app.run_forever, daemon=True)
    ws_thread.start()

    # Le graphique DOIT tourner dans le thread principal (contrainte Matplotlib/Tkinter)
    # plt.show() est bloquant : fermer la fenêtre arrête l'ensemble du programme
    print_price_data()