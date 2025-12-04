"""
Common utility module for Gemini3 Web Studio.

⚠️ IMPORTANT: This module is imported by app.py at startup.
   - Do NOT rename or delete this file
   - Do NOT import streamlit here (causes circular dependency)
   - Keep this as a pure utility module with no UI dependencies
"""

import os
import json
import re
import datetime
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
USER_PROFILE_FILE = "user_profile.json"
USD_TO_JPY = float(os.getenv("USD_TO_JPY", "150.0"))

# Increased budget limit for development
MAX_BUDGET_USD = float(os.getenv("MAX_BUDGET_USD", "1000.0"))  # Increased from 100 to 1000
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
    # None チェック：トークン数がNoneの場合は0として扱う
    input_tok = input_tok or 0
    output_tok = output_tok or 0
    
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

def get_client():
    """
    Gemini クライアントを取得（Vertex AI経由）
    
    ⚠️ NOTE: 
    - @st.cache_resource removed to avoid streamlit dependency
    - Caching should be handled in app.py if needed
    - Uses Application Default Credentials (gcloud auth)
    """
    try:
        # Application Default Credentials (works for local dev and Cloud)
        return genai.Client(
            vertexai=True,
            project=VERTEX_PROJECT,
            location=VERTEX_LOCATION,
        )
    except Exception as e:
        # エラー時はNoneを返す（アプリを止めない）
        print(f"❌ Vertex AI初期化エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

# =========================
# User Profile Management
# =========================

def load_user_profile():
    """
    ユーザープロファイルを読み込み
    
    Returns:
        dict: ユーザープロファイル情報
    """
    if os.path.exists(USER_PROFILE_FILE):
        with open(USER_PROFILE_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return get_default_profile()
    return get_default_profile()

def get_default_profile():
    """デフォルトのユーザープロファイルを返す"""
    return {
        "preferences": {},
        "interests": [],
        "facts_about_user": [],
        "next_suggestions": [],
        "last_updated": datetime.datetime.now().isoformat()
    }

def save_user_profile(profile):
    """
    ユーザープロファイルを保存
    
    Args:
        profile (dict): 保存するプロファイル情報
    """
    profile["last_updated"] = datetime.datetime.now().isoformat()
    with open(USER_PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=4, ensure_ascii=False)

def update_user_profile_from_conversation(client, question, answer, current_profile=None):
    """
    会話から自動的にプロファイルを更新
    
    Args:
        client: Vertex AI client
        question (str): ユーザーの質問
        answer (str): AIの回答
        current_profile (dict): 現在のプロファイル (Noneの場合は読み込む)
    
    Returns:
        tuple: (updated_profile, usage_dict)
    """
    if current_profile is None:
        current_profile = load_user_profile()
    
    # プロンプト設計: 会話からプロファイルを抽出・更新
    system_prompt = """あなたはユーザーの会話履歴から、プロファイル情報を抽出・更新するアシスタントです。

【タスク】
ユーザーの質問とAIの回答を分析し、以下の情報を抽出してください:
1. preferences: ユーザーの好み・要望 (例: "ニュースの元ネタまで確認したい", "タイムライン構造が好き")
2. interests: ユーザーの興味・関心トピック (例: "マクロ経済", "AI投資")
3. facts_about_user: ユーザーに関する事実 (例: "投資経験あり", "技術的なバックグラウンド")

【重要な制約】
- 既存のプロファイルと重複しない新情報のみ追加
- 推測ではなく、会話から明確に読み取れることだけを抽出
- 空の配列を返すのもOK (新情報がない場合)
- 出力はJSON形式で、以下の形式に従う:

{
  "new_preferences": {"キー": "値", ...},
  "new_interests": ["トピック1", "トピック2", ...],
  "new_facts": ["事実1", "事実2", ...]
}
"""
    
    # 現在のプロファイルを文字列化
    current_profile_str = json.dumps(current_profile, ensure_ascii=False, indent=2)
    
    user_content = f"""【現在のプロファイル】
{current_profile_str}

【今回の会話】
ユーザーの質問: {question[:500]}...

AIの回答: {answer[:800]}...

上記の会話から、新しく追加すべきプロファイル情報を抽出してください。"""
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_content}"}]}
            ],
            config=types.GenerateContentConfig(
                temperature=0.3,  # 安定した抽出のため低めに設定
                max_output_tokens=1000,
            )
        )
        
        # 使用量情報の取得
        usage_metadata = response.usage_metadata
        usage_dict = {
            "input_tokens": usage_metadata.prompt_token_count if usage_metadata else 0,
            "output_tokens": usage_metadata.candidates_token_count if usage_metadata else 0,
        }
        
        # レスポンスからJSON抽出
        result_text = extract_text_from_response(response)
        
        # JSONブロックの抽出 (```json ... ``` または直接JSON)
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', result_text, re.DOTALL)
        if json_match:
            extracted_data = json.loads(json_match.group(1))
        else:
            # ```なしの直接JSON
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                extracted_data = json.loads(json_match.group(0))
            else:
                # パースできない場合はデフォルト
                extracted_data = {"new_preferences": {}, "new_interests": [], "new_facts": []}
        
        # プロファイルを更新
        updated_profile = current_profile.copy()
        
        # preferencesのマージ
        if "new_preferences" in extracted_data:
            updated_profile["preferences"].update(extracted_data["new_preferences"])
        
        # interestsの追加 (重複排除)
        if "new_interests" in extracted_data:
            for interest in extracted_data["new_interests"]:
                if interest not in updated_profile["interests"]:
                    updated_profile["interests"].append(interest)
        
        # factsの追加 (重複排除)
        if "new_facts" in extracted_data:
            for fact in extracted_data["new_facts"]:
                if fact not in updated_profile["facts_about_user"]:
                    updated_profile["facts_about_user"].append(fact)
        
        return (updated_profile, usage_dict)
        
    except Exception as e:
        # エラー時は元のプロファイルをそのまま返す
        print(f"Profile update error: {e}")
        return (current_profile, {"input_tokens": 0, "output_tokens": 0})
        return (current_profile, {"input_tokens": 0, "output_tokens": 0})

def build_full_session_memory(sessions: list, current_session_id: str) -> str:
    """
    全セッションの履歴をテキスト化（Level 3用）
    
    Args:
        sessions: すべてのセッション
        current_session_id: 現在のセッションID
    
    Returns:
        str: 全履歴テキスト
    """
    # 現在のセッションを除外
    past_sessions = [s for s in sessions if s["id"] != current_session_id]
    
    if not past_sessions:
        return "（過去の履歴はありません）"
    
    # 時系列順（古い順）に並べ替え
    # timestampはISOフォーマットなので文字列比較でOK
    past_sessions.sort(key=lambda s: s.get("timestamp", ""), reverse=False)
    
    full_text = "【全チャット履歴アーカイブ】\n\n"
    
    for session in past_sessions:
        title = session.get("title", "No Title")
        date = session.get("timestamp", "")[:10]
        full_text += f"### Session: {title} ({date})\n"
        
        # 各セッションの要約的なものを抽出（全部は長すぎる場合があるが、Level 3ならある程度入れる）
        # ここでは「ユーザー質問」と「AI回答の冒頭」に絞るか、トークン許容なら全部入れる
        # gemini-2.0-flashは100万トークンいけるので、思い切って全部入れる
        for msg in session.get("messages", []):
            role = "User" if msg["role"] == "user" else "AI"
            content = msg["content"]
            # 極端に長いBase64画像などは除外すべきだが、テキスト前提
            full_text += f"- **{role}**: {content[:2000]}\n" # 1メッセージ2000文字制限で安全性確保
        
        full_text += "\n"
        
    return full_text
