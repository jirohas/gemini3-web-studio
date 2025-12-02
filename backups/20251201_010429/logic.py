import os
import json
import re
import datetime
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from youtube_transcript_api import YouTubeTranscriptApi
import io
from PIL import Image

load_dotenv()

USAGE_FILE = "usage_stats.json"
SESSIONS_FILE = "chat_sessions.json"
MANUAL_COST_FILE = "manual_cost.json"
USD_TO_JPY = float(os.getenv("USD_TO_JPY", "150.0"))
MAX_BUDGET_USD = float(os.getenv("MAX_BUDGET_USD", "100.0"))
MAX_BUDGET_JPY = MAX_BUDGET_USD * USD_TO_JPY
TRIAL_LIMIT_USD = float(os.getenv("TRIAL_LIMIT_USD", "300.0"))
TRIAL_LIMIT_JPY = TRIAL_LIMIT_USD * USD_TO_JPY
TRIAL_EXPIRY = os.getenv("TRIAL_EXPIRY", "2026-02-28")

PRICING = {
    "gemini-3-pro-preview":   {"input": 2.0,   "output": 12.0},
    "gemini-2.5-pro":         {"input": 1.25,  "output": 10.0},
    "gemini-2.5-flash":       {"input": 0.30,  "output": 2.50},
    "gemini-2.5-flash-lite":  {"input": 0.10,  "output": 0.40},
    "gemini-2.0-flash":       {"input": 0.10,  "output": 0.40},
}

VERTEX_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
VERTEX_LOCATION = "global"

def load_usage():
    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE, "r") as f:
            return json.load(f)
    return {"total_input_tokens": 0, "total_output_tokens": 0, "total_cost_usd": 0.0}

def save_usage(stats):
    with open(USAGE_FILE, "w") as f:
        json.dump(stats, f, indent=4)

def calculate_cost(model_id, input_tok, output_tok):
    price = PRICING.get(model_id, {"input": 0.0, "output": 0.0})
    cost = (input_tok / 1_000_000 * price["input"]) + (output_tok / 1_000_000 * price["output"])
    return cost

def load_manual_cost():
    if os.path.exists(MANUAL_COST_FILE):
        with open(MANUAL_COST_FILE, "r") as f:
            data = json.load(f)
            return data.get("manual_cost_usd", 0.0)
    return 0.0

def save_manual_cost(cost_usd):
    with open(MANUAL_COST_FILE, "w") as f:
        json.dump({"manual_cost_usd": cost_usd}, f, indent=4)

def get_mime_type(filename):
    ext = filename.split('.')[-1].lower()
    if ext in ['jpg', 'jpeg']:
        return 'image/jpeg'
    if ext == 'png':
        return 'image/png'
    if ext == 'mp4':
        return 'video/mp4'
    if ext == 'mov':
        return 'video/quicktime'
    if ext == 'txt':
        return 'text/plain'
    if ext == 'pdf':
        return 'application/pdf'
    if ext == 'csv':
        return 'text/csv'
    return 'application/octet-stream'

def extract_youtube_id(url):
    regex = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    if match:
        return match.group(1)
    return None

def get_youtube_transcript(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ja', 'en'])
        text = " ".join([t['text'] for t in transcript_list])
        return text
    except Exception as e:
        return f"字幕の取得エラー: {e}"

def get_relevant_context(query, sessions, current_session_id):
    """過去セッションからキーワードで簡易検索してコンテキストを返す"""
    if not query:
        return ""
    keywords = [k for k in query.split() if len(k) > 1]
    if not keywords:
        return ""

    relevant_sessions = []
    for session in sessions:
        if session["id"] == current_session_id:
            continue
        score = 0
        for k in keywords:
            if k.lower() in session["title"].lower():
                score += 3
        for msg in session["messages"][-4:]:
            for k in keywords:
                if k.lower() in msg["content"].lower():
                    score += 1
        if score > 0:
            relevant_sessions.append((score, session))

    relevant_sessions.sort(key=lambda x: (x[0], x[1]["timestamp"]), reverse=True)
    top_sessions = relevant_sessions[:3]

    context_str = ""
    if top_sessions:
        context_str += "### 過去の関連チャット履歴 (Context)\n"
        for score, session in top_sessions:
            last_response = "N/A"
            for m in reversed(session["messages"]):
                if m["role"] == "model":
                    last_response = m["content"][:300] + "..."
                    break
            context_str += f"- **Session: {session['title']}** ({session['timestamp'][:10]})\n"
            context_str += f"  Last Conclusion: {last_response}\n\n"
    return context_str

def extract_text_from_response(response):
    """Extract text from GenerateContentResponse"""
    if not response.candidates:
        return ""
    parts = response.candidates[0].content.parts or []
    return "".join(p.text or "" for p in parts)

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        with open(SESSIONS_FILE, "r") as f:
            try:
                data = json.load(f)
                return data.get("sessions", [])
            except json.JSONDecodeError:
                return []
    return []

def save_sessions(sessions):
    with open(SESSIONS_FILE, "w") as f:
        json.dump({"sessions": sessions}, f, indent=4, ensure_ascii=False)

@st.cache_resource
def get_client():
    # Streamlit Cloud用の認証（Service Account）
    if "GOOGLE_CREDENTIALS" in st.secrets:
        from google.oauth2 import service_account
        creds_dict = dict(st.secrets["GOOGLE_CREDENTIALS"])
        scoped_creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return genai.Client(
            vertexai=True,
            project=VERTEX_PROJECT,
            location=VERTEX_LOCATION,
            credentials=scoped_creds
        )
    
    # ローカル環境用（ADC）
    return genai.Client(
        vertexai=True,
        project=VERTEX_PROJECT,
        location=VERTEX_LOCATION,
    )
