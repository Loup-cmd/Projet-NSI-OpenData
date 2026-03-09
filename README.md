# 🤖 PEPE/USDT Live Trading Bot — Gemini AI Signals

Un daemon Python qui se connecte en temps réel au flux de trades Binance sur la paire **PEPE/USDT**, analyse les données avec **Google Gemini**, et affiche un **graphique live** annoté des signaux BUY / SELL.

---

## 📋 Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Flux de données détaillé](#flux-de-données-détaillé)
4. [Fonctions principales](#fonctions-principales)
5. [Installation](#installation)
6. [Lancement](#lancement)
7. [Limites & pistes d'amélioration](#limites--pistes-damélioration)

---

## Vue d'ensemble

Binance WebSocket  ──►  on_message()  ──►  Buffer 20 trades
                                                │
                                         Thread Gemini
                                                │
                                        send_to_gemini()  ──►  Gemini API
                                                │
                                        gemini_signals[]  ◄──  "Buy" / "Sell"
                                                │
                                    print_price_data()  ──►  Graphique Matplotlib (main thread)

Le script tourne en continu jusqu'à ce que la fenêtre graphique soit fermée.

---

## Architecture

### Threads

| Thread | Rôle |
|---|---|
| **Main thread** | Fait tourner `print_price_data()` — obligatoire pour Matplotlib |
| **ws_thread** (daemon) | Connexion WebSocket Binance + `on_message()` |
| **gemini_thread** (daemon) | Appel API Gemini — lancé toutes les 20 trades |

Les threads partagent trois structures protégées par un `threading.Lock` :

- `price_times` — deque des 300 derniers timestamps (datetime)
- `price_values` — deque des 300 derniers prix (float)
- `gemini_signals` — liste des signaux `(datetime, price, "Buy"|"Sell")`

### Pourquoi séparer Gemini dans un thread ?

L'API Gemini peut prendre plusieurs secondes à répondre. Si l'appel bloquait le thread WebSocket, on manquerait des trades pendant ce temps. Le thread daemon permet d'attendre la réponse en arrière-plan sans jamais interrompre la réception des données.

---

## Flux de données détaillé

### 1. Réception d'un trade — `on_message()`

Binance envoie un message JSON à chaque trade exécuté. Le callback extrait :

{
  "s": "PEPEUSDT",    // symbole
  "p": "0.00001234",  // prix d'exécution
  "E": 1712345678901, // timestamp en millisecondes
  "m": true           // true = le vendeur est market maker
}


Ces données sont :

- Ajoutées aux deques `price_times` / `price_values` pour le graphique (thread-safe)
- Bufférisées dans `ws.data` jusqu'à atteindre **20 trades**

### 2. Analyse par Gemini — `send_to_gemini()`

Quand le buffer atteint 20 trades, un thread est lancé. Il :

1. Construit un prompt via `build_prompt()` contenant les 20 trades
2. Envoie le prompt à `gemini-2.0-flash`
3. Attend la réponse (`"Buy"` ou `"Sell"`)
4. Enregistre le signal avec le prix courant dans `gemini_signals`

Pendant ce temps, le flag `Is_Gemini_Thinking = True` empêche d'accumuler de nouveaux trades dans le buffer (pour éviter les chevauchements de requêtes).

### 3. Construction du prompt — `build_prompt()`

Le prompt donne à Gemini un rôle précis d'analyste algorithmique et lui interdit toute réponse autre que `Buy` ou `Sell`. Les consignes d'analyse portent sur :

- La progression des prix (haussier / baissier / chaotique)
- La fréquence et l'accélération des trades
- Le comportement des market makers (champ `m`)
- Les micro-patterns de momentum

### 4. Graphique temps réel — `print_price_data()`

`FuncAnimation` déclenche `_refresh()` toutes les **500 ms** sur le main thread. À chaque refresh :

- La courbe de prix est redessinée depuis les deques
- Chaque signal Gemini est affiché :
  - **▲ vert** + label `BUY` au-dessus du point
  - **▼ rouge** + label `SELL` en-dessous du point
- Les axes, la grille et la légende sont remis en forme

La fenêtre conserve les **300 derniers points** (rolling window) pour ne pas saturer la mémoire sur de longues sessions.

---

## Fonctions principales

| Fonction | Description |
|---|---|
| `build_prompt(trades)` | Formate les 20 trades en un prompt Markdown structuré pour Gemini |
| `send_to_gemini(trades)` | Appelle l'API Gemini et enregistre le signal résultant |
| `print_price_data()` | Lance la fenêtre Matplotlib avec rafraîchissement automatique |
| `on_message(ws, message)` | Callback WebSocket — parse le trade, met à jour les deques, déclenche Gemini |
| `on_error(ws, error)` | Affiche les erreurs WebSocket |
| `on_open(ws)` | Confirmation de connexion dans le terminal |

---

## Installation

### Prérequis

- Python **3.10+**
- Un terminal avec accès Internet (flux Binance public, aucun compte requis)

### Dépendances


pip install websocket-client matplotlib google-genai


| Package | Rôle |
|---|---|
| `websocket-client` | Connexion au stream Binance |
| `matplotlib` | Graphique temps réel |
| `google-genai` | Client officiel Gemini API |

---

## Lancement

python main.py

Une fenêtre graphique s'ouvre. Le terminal affiche chaque trade reçu et chaque recommandation Gemini. **Fermer la fenêtre arrête le programme.**

---

## Limites & pistes d'amélioration

| Limite actuelle | Amélioration possible |
|---|---|
| Gemini répond `Buy` / `Sell` uniquement | Demander un JSON avec `entry_price`, `stop_loss`, `take_profit` |
| Pas d'exécution réelle des ordres | Intégrer l'API REST Binance pour passer des ordres |
| Stratégie basée sur 20 trades seulement | Ajouter des indicateurs techniques (EMA, RSI, VWAP) |
| Clé API en dur | Utiliser `python-dotenv` + `.gitignore` |
| Pas de persistance des données | Logger les trades et signaux dans un fichier CSV ou une base SQLite |
| Fenêtre fixe de 300 points | Rendre la taille configurable via un argument CLI |