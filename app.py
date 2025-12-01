import os
import uuid
import datetime
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image
import io
from logic import (
    USAGE_FILE, SESSIONS_FILE, MAX_BUDGET_USD, PRICING,
    VERTEX_PROJECT, VERTEX_LOCATION,
    load_usage, save_usage, calculate_cost, get_mime_type,
    extract_youtube_id, get_youtube_transcript, get_relevant_context,
    extract_text_from_response, load_sessions, save_sessions, get_client
)

try:
    from st_img_pastebutton import paste
    import_error_msg = None
except ImportError as e:
    paste = None
    import_error_msg = str(e)

# =========================
# 環境変数 & 定数
# =========================

load_dotenv()



st.set_page_config(page_title="Gemini 3 Web Studio", layout="wide")

# 🔐 パスワードロック (***REMOVED***) + URLトークン永続化
SECRET_TOKEN = "access_granted_***REMOVED***"

# 1. URLトークンチェック
query_params = st.query_params
url_token = query_params.get("auth", None)

if url_token == SECRET_TOKEN:
    st.session_state.authenticated = True
elif "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# 2. 未認証ならパスワード画面
if not st.session_state.authenticated:
    st.title("Gemini 3 Studio")
    st.write("このアプリを利用するにはパスワードが必要です。")

    password = st.text_input("パスワード", type="password")

    if st.button("ログイン"):
        if password == "***REMOVED***":
            st.session_state.authenticated = True
            # URLにトークンを付与してリロード（これでブックマーク可能になる）
            st.query_params["auth"] = SECRET_TOKEN
            st.rerun()
        else:
            st.error("パスワードが違います。")

    st.stop()

# =========================
# Helper Functions
# =========================

# =========================
# Helper Functions
# =========================
# Moved to logic.py

# =========================
# Grok Review Function (OpenRouter API)
# =========================

import requests
from curl_cffi import requests as crequests  # Puter用

# OpenRouter API Keyの取得 (st.secrets優先、なければ環境変数)
try:
    if "OPENROUTER_API_KEY" in st.secrets:
        OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
    else:
        OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
except:
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Puter 認証情報
PUTER_USERNAME = None
PUTER_PASSWORD = None
try:
    if "PUTER_USERNAME" in st.secrets:
        PUTER_USERNAME = st.secrets["PUTER_USERNAME"]
        PUTER_PASSWORD = st.secrets["PUTER_PASSWORD"]
    else:
        PUTER_USERNAME = os.getenv("PUTER_USERNAME")
        PUTER_PASSWORD = os.getenv("PUTER_PASSWORD")
except Exception:
    PUTER_USERNAME = os.getenv("PUTER_USERNAME")
    PUTER_PASSWORD = os.getenv("PUTER_PASSWORD")

def review_with_grok(user_question: str, gemini_answer: str, research_text: str = None) -> str:
    """
    Grok 4.1 Fast Free を使って、Geminiの回答を最終レビューする
    research_text: Geminiが収集した調査メモ（最新情報を含む）
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    # プロンプトの構築
    user_content = f"ユーザーの質問:\n{user_question}\n\n"
    
    if research_text:
        user_content += f"Gemini の調査メモ（最新情報）:\n{research_text}\n\n"
    
    user_content += (
        f"Gemini の最終回答:\n{gemini_answer}\n\n"
        "**重要**: 調査メモに含まれる事実の方を、あなた自身の知識よりも優先してください。\n"
        "最新の情報が調査メモにある場合、それを信頼してください。\n\n"
        "1. **重大な事実誤認・論理飛躍の指摘**（なければ『特になし』）\n"
        "2. **具体的な修正提案のリスト**（『修正前』→『修正後』の形式で）\n"
        "3. **特に不確実性が高いポイント（前提不足、データ不足など）の bullet list**\n"
    )
    
    data = {
        "model": "x-ai/grok-4.1-fast:free",
        "reasoning": {"enabled": True},  # Enable multi-step reasoning for deeper review
        "messages": [
            {
                "role": "system",
                "content": (
                    "あなたは厳格なレビューアです。"
                    "事実誤認・論理の飛躍・抜け漏れを容赦なく指摘し、"
                    "必要なら回答を全文書き直してください。"
                ),
            },
            {
                "role": "user",
                "content": user_content.strip() + (
                    "だけを日本語で出してください。"
                ),
            },
        ],
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=60)
        resp.raise_for_status()
        j = resp.json()
        return j["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Grokレビューエラー: {e}]\n\n{gemini_answer}"

# =========================
# Session Management
# =========================



def think_with_grok(user_question: str, research_text: str, enable_x_search: bool = False) -> str:
    """
    Grok 4.1 Fast Free を使って、リサーチメモを元に独立した回答案を作成する
    enable_x_search=True の場合、X/Twitter情報の活用を促す
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    
    # X検索強化版の場合、特別な指示を追加
    x_search_instruction = ""
    if enable_x_search:
        x_search_instruction = (
            "\n\n**重要**: あなたはGrokとしてX（Twitter）の情報にアクセスできます。\n"
            "上記の調査メモに加えて、X上の最新のトレンド・議論・反応を考慮し、\n"
            "それらを含めた独立した回答案を作成してください。\n\n"
            "注意: X上の情報が確認できない場合は、その旨を正直に述べてください。\n"
            "架空の投稿や存在しない反応を作成しないこと。"
        )
    
    user_content = (
        f"ユーザーの質問:\n{user_question}\n\n"
        f"調査メモ:\n{research_text}\n\n"
        "指示:\n"
        "あなたはGeminiとは別の独立したAIです。\n"
        "上記の調査メモを参考にしつつも、あなた自身の視点で独立した回答案を作成してください。\n"
        "Geminiの意見に合わせる必要はありません。"
        f"{x_search_instruction}"
    )
    
    data = {
        "model": "x-ai/grok-2-1212",
        "messages": [
            {"role": "user", "content": user_content}
        ],
    }
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=60)
        resp.raise_for_status()
        j = resp.json()
        return j["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Grok思考エラー: {e}]"

def _extract_puter_text(message_content):
    """
    puter.ai.chat の返り値から テキストだけを取り出す
    """
    if isinstance(message_content, str):
        return message_content

    if isinstance(message_content, list):
        chunks = []
        for part in message_content:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(part.get("text", ""))
        return "".join(chunks)

    return str(message_content)


def call_claude_opus_via_puter(
    user_question: str,
    research_text: str | None = None,
    system_prompt: str | None = None,
) -> str:
    """
    Claude Opus 4.5（puter.com）で推論させる同期関数
    curl_cffiでChrome 124を偽装して直接APIを叩く
    """
    if not PUTER_USERNAME or not PUTER_PASSWORD:
        return "[Claude (puter) 認証情報未設定]"

    # 1. Prepare Headers (Chrome 124 Masquerading)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
        "Origin": "https://puter.com",
        "Referer": "https://puter.com/",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Content-Type": "application/json"
    }

    token = st.session_state.get("puter_token")

    # トークンがない、または再試行が必要な場合のログイン関数
    def perform_login():
        try:
            resp = crequests.post(
                "https://api.puter.com/login",
                json={"username": PUTER_USERNAME, "password": PUTER_PASSWORD},
                headers=headers,
                timeout=30,
                impersonate="chrome124"
            )
            if resp.status_code != 200:
                return None, f"[Claude Login Error] Status: {resp.status_code}"
            
            new_token = resp.json().get("token")
            if not new_token:
                return None, "[Claude Login Error] Token not found"
            
            return new_token, None
        except Exception as e:
            return None, f"[Claude Login Error] {str(e)}"

    # トークンがない場合はログイン
    if not token:
        token, error = perform_login()
        if error:
            return error
        st.session_state.puter_token = token

    # 2. Chat
    chat_url = "https://api.puter.com/drivers/call"
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    user_content = f"ユーザーの質問:\n{user_question}\n\n"
    if research_text:
        user_content += f"調査メモ:\n{research_text}\n\n"
        user_content += "この調査メモの事実を優先して回答してください。\n"

    messages.append({"role": "user", "content": user_content})
    
    payload = {
        "interface": "puter-chat-completion",
        "driver": "claude",
        "method": "complete",
        "args": {
            "messages": messages,
            "model": "claude-opus-4-5",
            "stream": False
        }
    }

    try:
        # 初回トライ
        auth_headers = headers.copy()
        auth_headers["Authorization"] = f"Bearer {token}"
        chat_resp = crequests.post(chat_url, json=payload, headers=auth_headers, timeout=120, impersonate="chrome124")

        # 401/403の場合は再ログイン
        if chat_resp.status_code in [401, 403]:
            token, error = perform_login()
            if error:
                return error
            st.session_state.puter_token = token
            
            # リトライ
            auth_headers["Authorization"] = f"Bearer {token}"
            chat_resp = crequests.post(chat_url, json=payload, headers=auth_headers, timeout=120, impersonate="chrome124")

        if chat_resp.status_code != 200:
            return f"[Claude API Error] Status: {chat_resp.status_code}"
            
        result = chat_resp.json()
        if not result.get("success", False):
             return f"[Claude API Error] {result.get('error', 'Unknown error')}"

        message = result["result"]["message"]
        return _extract_puter_text(message.get("content"))

    except Exception as e:
        return f"[Claude Error] {str(e)}"

def create_new_session():
    current_sessions = load_sessions()
    
    # 現在のセッションが空なら、新しく作らずにそれを再利用する（重複防止）
    if st.session_state.get("current_session_id"):
        for s in current_sessions:
            if s["id"] == st.session_state.current_session_id:
                if len(s["messages"]) == 0:
                    st.toast("すでに新しいチャットです")
                    return

    new_id = str(uuid.uuid4())
    new_session = {
        "id": new_id,
        "title": "新しいチャット",
        "timestamp": datetime.datetime.now().isoformat(),
        "messages": [],
    }
    current_sessions.insert(0, new_session)
    save_sessions(current_sessions)
    st.session_state.sessions = current_sessions
    st.session_state.current_session_id = new_id
    st.rerun()

def switch_session(session_id):
    st.session_state.current_session_id = session_id
    st.rerun()

def update_current_session_messages(messages):
    if st.session_state.current_session_id:
        current_sessions = load_sessions()
        target_index = -1
        for i, session in enumerate(current_sessions):
            if session["id"] == st.session_state.current_session_id:
                session["messages"] = messages
                if session["title"] == "新しいチャット" and len(messages) > 0:
                    first_msg = messages[0]["content"]
                    session["title"] = (first_msg[:20] + "...") if len(first_msg) > 20 else first_msg
                session["timestamp"] = datetime.datetime.now().isoformat()
                target_index = i
                break
        
        if target_index != -1:
            # 最新のセッションをリストの先頭に移動
            updated_session = current_sessions.pop(target_index)
            current_sessions.insert(0, updated_session)
            
        save_sessions(current_sessions)
        st.session_state.sessions = current_sessions

def get_current_messages():
    if st.session_state.current_session_id:
        for session in st.session_state.sessions:
            if session["id"] == st.session_state.current_session_id:
                return session["messages"]
    return []

def delete_session(session_id):
    current_sessions = load_sessions()
    current_sessions = [s for s in current_sessions if s["id"] != session_id]
    save_sessions(current_sessions)
    st.session_state.sessions = current_sessions
    if st.session_state.current_session_id == session_id:
        st.session_state.current_session_id = None
        if st.session_state.sessions:
            st.session_state.current_session_id = st.session_state.sessions[0]["id"]
    st.rerun()

def branch_session():
    """現在のセッションから新しいチャットを分岐"""
    current_messages = get_current_messages()
    current_sessions = load_sessions()
    
    # 現在のセッションのタイトルを取得
    current_title = "新しいチャット"
    for session in current_sessions:
        if session["id"] == st.session_state.current_session_id:
            current_title = session["title"]
            break
    
    # 新しいセッションを作成
    new_id = str(uuid.uuid4())
    new_session = {
        "id": new_id,
        "title": f"{current_title} (分岐)",
        "timestamp": datetime.datetime.now().isoformat(),
        "messages": current_messages.copy(),  # 現在の履歴をコピー
    }
    current_sessions.insert(0, new_session)
    save_sessions(current_sessions)
    
    st.session_state.sessions = current_sessions
    st.session_state.current_session_id = new_id
    st.session_state.session_cost = 0.0  # コストリセット
    st.rerun()

# =========================
# Initialization
# =========================

if "sessions" not in st.session_state:
    st.session_state.sessions = load_sessions()

if "current_session_id" not in st.session_state:
    # Always create a new session when the app starts
    create_new_session()

if "session_cost" not in st.session_state:
    st.session_state.session_cost = 0.0

usage_stats = load_usage()

# ==========================
# コストチェック（サイドバーの前に実行）
# ==========================
usage_stats = load_usage()
stop_generation = usage_stats["total_cost_usd"] >= MAX_BUDGET_USD

# =========================
# Sidebar
# =========================

with st.sidebar:
    # 🔐 ログアウトボタン
    if st.button("🔒 ログアウト", use_container_width=True):
        st.session_state.authenticated = False
        st.query_params.clear()  # URLトークンも削除
        st.rerun()

    st.markdown("""
    <div style="text-align: center; padding: 0; margin: 0; margin-top: -1rem;">
        <h1 style="font-size: 18px; font-weight: 700; margin: 0; padding: 0; letter-spacing: 1px;">
            Gemini 3<br/>Studio
        </h1>
    </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ 新規", use_container_width=True):
            create_new_session()
    with col2:
        if st.button("🌱 分岐", use_container_width=True):
            branch_session()

    # ---- 共有リンク作成 ----
    # ---- 共有リンク作成 ----
    current_messages = get_current_messages()
    if current_messages:
        with st.expander("🔗 共有リンク作成", expanded=False):
            export_title = "新しいチャット"
            for s in st.session_state.sessions:
                if s["id"] == st.session_state.current_session_id:
                    export_title = s["title"]
                    break

            export_md = f"# {export_title}\n\n"
            export_md += f"**作成日時**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"
            for msg in current_messages:
                role_label = "🧑 ユーザー" if msg["role"] == "user" else "🤖 AI"
                export_md += f"## {role_label}\n\n{msg['content']}\n\n---\n\n"

            if st.button("リンク生成", use_container_width=True):
                with st.spinner("生成中..."):
                    try:
                        import urllib.request
                        import urllib.parse

                        data = urllib.parse.urlencode(
                            {"content": export_md, "expiry_days": 7, "syntax": "md"}
                        ).encode()

                        req = urllib.request.Request("https://dpaste.org/api/", data=data)
                        req.add_header("User-Agent", "Mozilla/5.0 (Gemini3Studio)")

                        with urllib.request.urlopen(req) as response:
                            share_url = response.read().decode("utf-8").strip()
                            st.success("作成完了！")
                            st.code(share_url)
                            st.caption("※7日間有効")
                    except Exception as e:
                        st.error(f"エラー: {e}")

    st.markdown("---")

    # ---- ファイルアップロード & クリップボード ----
    # ---- ファイルアップロード & クリップボード ----
    with st.expander("📎 添付ファイル", expanded=False):
        uploaded_files = st.file_uploader(
            "ファイル",
            accept_multiple_files=True,
            type=["png", "jpg", "jpeg", "mp4", "mov", "txt", "pdf", "csv"],
            label_visibility="collapsed"
        )

    # クリップボード（Expanderの外に出す）
    pasted_image_bytes = None  # 初期化してNameErrorを防ぐ
    if paste:
        if "paste_key" not in st.session_state:
            st.session_state.paste_key = 0
        try:
            pasted_image_bytes = paste(
                label="📋 クリップボード貼付",
                key=f"paste_btn_{st.session_state.paste_key}",
            )
        except Exception as e:
            st.error(f"Error: {e}")
        
        if pasted_image_bytes:
            st.success("貼付完了")
            st.image(pasted_image_bytes, caption="画像", use_container_width=True)
            if st.button("🗑️ クリア", key="clear_paste"):
                st.session_state.paste_key += 1
                st.rerun()
    else:
        st.warning("Clipboard lib missing")

    # ---- YouTube URL ----
    with st.expander("📺 YouTube分析", expanded=False):
        youtube_url = st.text_input("URL", placeholder="https://youtu.be/...", label_visibility="collapsed")

    st.markdown("---")
    
    st.markdown("---")
    
    # ---- モードカテゴリ選択 ----
    mode_category = st.radio(
        "使用するモード",
        ["🎯 回答モード(多層)", "🎯 回答モード(通常)", "β：🎯 回答モード(多層+puter)"],
        index=2,  # デフォルトをPuterモードに変更
        horizontal=True,
    )
    
    # ---- 多層モード ----
    if mode_category == "🎯 回答モード(多層)":
        with st.expander("モード設定(多層)", expanded=True):
            mode_type = st.radio(
                "タイプ",
                ["選択1 (完全版)", "選択2 (不完全版)", "ベータ版"],
                index=0,
                horizontal=True,
                label_visibility="collapsed"
            )
            
            if mode_type == "選択1 (完全版)":
                response_mode = st.radio(
                    "モード",
                    [
                        "1. (試験中)熟考 + 鬼軍曹",
                        "2. 熟考 (メタ思考)",
                        "3. (試験中)熟考 (本気MAX)",
                        "4. 熟考(メタ思考)+grok検索強化版",
                    ],
                    index=1  # デフォルトをメタ思考に変更
                )
            elif mode_type == "選択2 (不完全版)":
                response_mode = st.radio(
                    "モード",
                    [
                        "1. 熟考 (リサーチ)",
                    ],
                    index=0
                )
            else:
                response_mode = st.radio(
                    "モード",
                    [
                        "β1. 通常 (高速)",
                    ],
                    index=0
                )
    
    # ---- 多層+puterモード ----
    elif mode_category == "β：🎯 回答モード(多層+puter)":
        with st.expander("モード設定(多層+puter)", expanded=True):
            mode_type = st.radio(
                "タイプ",
                ["選択1 (完全版)", "選択2 (不完全版)", "ベータ版"],
                index=0,
                horizontal=True,
                label_visibility="collapsed"
            )
            
            if mode_type == "選択1 (完全版)":
                response_mode = st.radio(
                    "モード",
                    [
                        "1. 熟考 + 鬼軍曹(localのみ)",
                        "2. 熟考 (メタ思考)",
                        "3. 熟考 (本気MAX)",
                    ],
                    index=0  # デフォルトを鬼軍曹に変更
                )
            elif mode_type == "選択2 (不完全版)":
                response_mode = st.radio(
                    "モード",
                    [
                        "1. 熟考 (リサーチ)",
                    ],
                    index=0
                )
            else:
                response_mode = st.radio(
                    "モード",
                    [
                        "β1. 通常 (高速)",
                    ],
                    index=0
                )
    
    # ---- 通常モード ----
    else:
        with st.expander("モード設定(通常)", expanded=True):
            mode_type = st.radio(
                "タイプ",
                ["選択1 (完全版)", "選択2 (不完全版)", "ベータ版"],
                index=0,
                horizontal=True,
                label_visibility="collapsed"
            )
            
            if mode_type == "選択1 (完全版)":
                response_mode = st.radio(
                    "モード",
                    [
                        "1. 熟考 + 鬼軍曹",
                        "2. 熟考 (メタ思考)",
                        "3. 熟考 (本気MAX)",
                    ],
                    index=0
                )
            elif mode_type == "選択2 (不完全版)":
                response_mode = st.radio(
                    "モード",
                    [
                        "1. 熟考 (リサーチ)",
                    ],
                    index=0
                )
            else:
                response_mode = st.radio(
                    "モード",
                    [
                        "β1. 通常 (高速)",
                    ],
                    index=0
                )
    
    strict_mode = False
    
    # ---- 設定 (モデルなど) ----
    with st.expander("⚙️ 設定", expanded=False):
        model_options = [
            "gemini-3-pro-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        ]
        model_id = st.selectbox("モデルID", options=model_options, index=0)

        use_search = st.toggle("Google検索", value=True)
        candidate_count = st.slider("候補数", min_value=1, max_value=3, value=3)

    st.markdown("---")

    # ---- 履歴検索 ----
    search_query = st.text_input("🔍 履歴検索", placeholder="キーワード...")
    if search_query:
        filtered_sessions = []
        for s in st.session_state.sessions:
            if search_query.lower() in s["title"].lower():
                filtered_sessions.append(s)
                continue
            found = False
            for m in s["messages"]:
                if search_query.lower() in m["content"].lower():
                    filtered_sessions.append(s)
                    found = True
                    break
            if not found:
                pass
    else:
        # 検索していない場合: 空の「新しいチャット」を除外（現在のセッションは除く）
        filtered_sessions = []
        for s in st.session_state.sessions:
            if s["id"] == st.session_state.current_session_id:
                filtered_sessions.append(s)
                continue
            if s["title"] == "新しいチャット" and len(s["messages"]) == 0:
                continue
            filtered_sessions.append(s)

    # CSSで見やすく使いやすく最適化
    st.markdown("""
    <style>
    /* 全体のフォントサイズ縮小 */
    .stApp, .stMarkdown, .stButton, .stSelectbox, .stTextInput, .stTextArea {
        font-size: 12px !important;
    }
    /* サイドバーの余白を極限まで詰める */
    section[data-testid="stSidebar"] .block-container {
        padding-top: 0.3rem !important;
        padding-bottom: 0.3rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    /* 各要素間の隙間を詰める */
    div[data-testid="stVerticalBlock"] > div {
        gap: 0.1rem !important;
    }
    /* Expanderの余白削減 */
    .streamlit-expanderHeader {
        font-size: 11px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
        min-height: 1.3rem !important;
    }
    .streamlit-expanderContent {
        padding-top: 0px !important;
        padding-bottom: 0px !important;
    }
    /* 過去アーカイブのタイトル */
    div[data-testid="stExpander"] summary p {
        font-size: 10px !important;
    }
    /* サイドバーのボタンテキスト */
    section[data-testid="stSidebar"] button p {
        font-size: 10px !important;
    }
    /* サイドバーのボタンをコンパクトに */
    section[data-testid="stSidebar"] button {
        padding: 0rem 0.2rem !important;
        min-height: 1.4rem !important;
        font-size: 10px !important;
        margin-bottom: 0px !important;
    }
    /* ラジオボタンのラベルを小さく */
    section[data-testid="stSidebar"] .stRadio label {
        font-size: 10px !important;
    }
    section[data-testid="stSidebar"] .stRadio > label > div {
        font-size: 10px !important;
    }
    /* テキストを切り詰める（改行させない） */
    section[data-testid="stSidebar"] label, 
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    /* 区切り線 */
    hr {
        margin-top: 0.1rem !important;
        margin-bottom: 0.1rem !important;
    }
    /* ヘッダー縮小 */
    h1, h2, h3 {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        margin-top: 0rem !important;
        margin-bottom: 0rem !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # タイムスタンプで降順ソート（最新が先頭）
    filtered_sessions.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
    
    # 直近5件と過去アーカイブに分割
    recent_sessions = filtered_sessions[:5] if len(filtered_sessions) > 5 else filtered_sessions
    archive_sessions = filtered_sessions[5:] if len(filtered_sessions) > 5 else []
    
    # 直近5件（常に展開）
    if recent_sessions:
        st.markdown("**📌 直近のチャット**")
        for session in recent_sessions:
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                if st.button(session["title"], key=f"btn_{session['id']}", use_container_width=True):
                    switch_session(session["id"])
            with col2:
                if st.button("🗑️", key=f"del_{session['id']}"):
                    delete_session(session["id"])
    
    # 過去アーカイブ（折りたたみ）
    if archive_sessions:
        with st.expander(f"📜 過去アーカイブ ({len(archive_sessions)}件)", expanded=False):
            for session in archive_sessions:
                col1, col2 = st.columns([0.8, 0.2])
                with col1:
                    if st.button(session["title"], key=f"btn_{session['id']}", use_container_width=True):
                        switch_session(session["id"])
                with col2:
                    if st.button("🗑️", key=f"del_{session['id']}"):
                        delete_session(session["id"])

    st.markdown("---")

    # ---- 画像生成 ----
    with st.expander("🎨 画像生成", expanded=False):
        img_prompt = st.text_area("プロンプト", placeholder="未来的な都市...")
        aspect_ratio = st.selectbox("比率", ["16:9", "1:1", "4:3", "3:4", "9:16"])

        generate_img_btn = st.button("生成", type="primary", disabled=not img_prompt)
        if generate_img_btn and img_prompt:
            st.session_state.generate_image_trigger = {
                "prompt": img_prompt,
                "aspect_ratio": aspect_ratio,
            }

    st.markdown("---")

    # ---- 評価分析 ----
    with st.expander("📊 品質分析", expanded=False):
        total_ratings = 0
        positive_ratings = 0
        model_ratings = {}

        for s in st.session_state.sessions:
            for m in s["messages"]:
                if "rating" in m and m["rating"] is not None:
                    total_ratings += 1
                    if m["rating"] == 1:
                        positive_ratings += 1
                    if "metadata" in m and "model" in m["metadata"]:
                        mod = m["metadata"]["model"]
                        if mod not in model_ratings:
                            model_ratings[mod] = {"total": 0, "positive": 0}
                        model_ratings[mod]["total"] += 1
                        if m["rating"] == 1:
                            model_ratings[mod]["positive"] += 1

        if total_ratings > 0:
            approval_rate = (positive_ratings / total_ratings) * 100
            st.metric("Positive Ratings", f"{positive_ratings}/{total_ratings}", f"{approval_rate:.1f}%")
            best_model = "N/A"
            best_rate = -1
            for mod, stats in model_ratings.items():
                rate = stats["positive"] / stats["total"]
                if rate > best_rate:
                    best_rate = rate
                    best_model = mod
            if best_model != "N/A":
                st.caption(f"🏆 Best: **{best_model}** ({best_rate*100:.0f}%)")
        else:
            st.caption("データなし")

    st.markdown("---")

    # ---- コスト表示 ----
    from logic import load_manual_cost, save_manual_cost, MAX_BUDGET_JPY, TRIAL_LIMIT_JPY, TRIAL_EXPIRY
    
    st.subheader("💰 Cost")
    st.caption(f"予算: ¥{MAX_BUDGET_JPY:,.0f}")
    st.caption(f"上限: ¥{TRIAL_LIMIT_JPY:,.0f}")
    st.caption(f"有効期限: {TRIAL_EXPIRY}")
    
    # 手動コスト入力（永続化）
    current_manual_cost = load_manual_cost()
    manual_cost = st.number_input(
        "手動入力 (¥)",
        min_value=0.0,
        value=current_manual_cost,
        step=10.0,
        format="%.0f",
        key="manual_cost_persistent",
        help="Google Cloud Consoleで確認した実際のコスト（円）を入力してください。この値はブラウザを閉じても保持されます。"
    )
    
    # 値が変更されたら保存
    if manual_cost != current_manual_cost:
        save_manual_cost(manual_cost)
    
    st.link_button("💰 Google Cloud Console", "https://console.cloud.google.com/welcome/new?_gl=1*kmr691*_up*MQ..&gclid=CjwKCAiAraXJBhBJEiwAjz7MZT0vQsfDK5zunRBCQmuN5iczgI4bP1lHo1Tcrcbqu1KCBE1D22GpFhoCOdgQAvD_BwE&gclsrc=aw.ds&hl=ja&authuser=5&project=sigma-task-479704-r6")

    st.markdown("---")
    st.code(f"PROJECT: {VERTEX_PROJECT}\nLOCATION: {VERTEX_LOCATION} (Vertex AI)")

# =========================
# Main UI
# =========================

current_session_title = "新しいチャット"
for s in st.session_state.sessions:
    if s["id"] == st.session_state.current_session_id:
        current_session_title = s["title"]
        break

st.header(current_session_title)
st.markdown(
    "以下に質問を入力してください。マルチターン会話、ファイルアップロード、YouTube分析、検索グラウンディングに対応しています。"
)


# ---- スクロールボタン (Floating) ----
st.markdown("""
    <style>
        .scroll-btn-container {
            position: fixed;
            bottom: 100px;
            right: 20px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .scroll-btn {
            background-color: #f0f2f6;
            color: #31333F;
            border: 1px solid #d6d6d8;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            font-size: 20px;
            padding: 0;
            line-height: 1;
        }
        .scroll-btn:hover {
            background-color: #e0e2e6;
            transform: scale(1.1);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }
    </style>
    
    <script>
        window.scrollStreamlit = function(direction) {
            console.log("Scroll triggered: " + direction);
            
            // ターゲットとなる可能性のある要素を順番に試す
            var targets = [];
            
            try {
                if (window.parent && window.parent.document) {
                    targets.push(window.parent.document.querySelector('section[data-testid="stAppViewContainer"]'));
                    targets.push(window.parent.document.querySelector('.main'));
                    targets.push(window.parent.document.documentElement);
                }
            } catch (e) {
                console.log("Access to parent window denied");
            }
            
            // フォールバック（iframe内）
            targets.push(document.querySelector('section[data-testid="stAppViewContainer"]'));
            targets.push(document.documentElement);

            var scrolled = false;
            for (var i = 0; i < targets.length; i++) {
                var el = targets[i];
                if (el) {
                    try {
                        // スクロール可能な要素かチェック（簡易的）
                        if (el.scrollHeight > el.clientHeight || el === window.parent.document.documentElement) {
                            console.log("Scrolling element:", el);
                            if (direction === 'top') {
                                el.scrollTo({top: 0, behavior: 'smooth'});
                            } else {
                                el.scrollTo({top: el.scrollHeight, behavior: 'smooth'});
                            }
                            scrolled = true;
                        }
                    } catch (e) {
                        console.error("Error scrolling element:", e);
                    }
                }
            }
            
            if (!scrolled) {
                console.log("No scrollable container found, trying window scroll");
                try {
                    if (direction === 'top') {
                        window.parent.scrollTo({top: 0, behavior: 'smooth'});
                    } else {
                        window.parent.scrollTo({top: window.parent.document.body.scrollHeight, behavior: 'smooth'});
                    }
                } catch(e) {
                    window.scrollTo({top: 0, behavior: 'smooth'});
                }
            }
        }
    </script>

    <div class="scroll-btn-container">
        <button class="scroll-btn" onclick="window.scrollStreamlit('top')" title="Top">⬆️</button>
        <button class="scroll-btn" onclick="window.scrollStreamlit('bottom')" title="Bottom">⬇️</button>
    </div>
    """, unsafe_allow_html=True)

# ---- Vertex AI Client ----



client = get_client()

# ---- 履歴表示 ----

messages = get_current_messages()
for idx, msg in enumerate(messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "model":
            col1, col2, col3 = st.columns([0.1, 0.1, 0.8])
            current_rating = msg.get("rating")
            with col1:
                if st.button("👍", key=f"up_{idx}"):
                    messages[idx]["rating"] = 1
                    update_current_session_messages(messages)
                    st.rerun()
            with col2:
                if st.button("👎", key=f"down_{idx}"):
                    messages[idx]["rating"] = -1
                    update_current_session_messages(messages)
                    st.rerun()
            with col3:
                if current_rating == 1:
                    st.caption("✅ 高評価")
                elif current_rating == -1:
                    st.caption("❌ 低評価")

# スクロールボタン（長いチャット用）
if len(messages) > 5:
    st.markdown("""
    <div style="position: fixed; right: 20px; bottom: 100px; z-index: 999;">
        <button onclick="window.scrollTo({top: 0, behavior: 'smooth'})" 
                style="display: block; margin: 5px; padding: 10px 15px; font-size: 24px; cursor: pointer; 
                       border: 2px solid #ccc; border-radius: 50%; background: white; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
            ⬆️
        </button>
        <button onclick="window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'})" 
                style="display: block; margin: 5px; padding: 10px 15px; font-size: 24px; cursor: pointer; 
                       border: 2px solid #ccc; border-radius: 50%; background: white; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">
            ⬇️
        </button>
    </div>
    """, unsafe_allow_html=True)


# =========================
# 画像生成ハンドリング
# =========================

if hasattr(st.session_state, "generate_image_trigger") and st.session_state.generate_image_trigger:
    img_data = st.session_state.generate_image_trigger
    del st.session_state.generate_image_trigger

    with st.chat_message("user"):
        st.markdown(f"🎨 画像生成: {img_data['prompt']}")
        st.caption(f"アスペクト比: {img_data['aspect_ratio']}")

    messages.append({"role": "user", "content": f"🎨 画像生成: {img_data['prompt']}"})
    update_current_session_messages(messages)

    with st.chat_message("assistant"):
        with st.status("画像を生成中...", expanded=True) as status:
            try:
                config = types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=img_data["aspect_ratio"]
                    ),
                )
                status.write("Gemini 3 Pro Imageで生成中...")
                response = client.models.generate_content(
                    model="gemini-3-pro-image-preview",
                    contents=img_data["prompt"],
                    config=config,
                )

                generated_image = None

                # 画像を取り出す
                if getattr(response, "candidates", None):
                    for candidate in response.candidates:
                        if getattr(candidate, "content", None) and candidate.content.parts:
                            for part in candidate.content.parts:
                                if getattr(part, "inline_data", None):
                                    try:
                                        generated_image = part.as_image()
                                    except AttributeError:
                                        image_bytes_raw = part.inline_data.data
                                        generated_image = Image.open(io.BytesIO(image_bytes_raw))
                                    break
                        if generated_image is not None:
                            break

                if generated_image is not None:
                    st.image(generated_image, caption=img_data["prompt"])
                    buf = io.BytesIO()
                    generated_image.save(buf, format="PNG")
                    image_bytes = buf.getvalue()
                    st.download_button(
                        label="💾 画像をダウンロード",
                        data=image_bytes,
                        file_name=f"generated_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                        mime="image/png",
                    )
                    messages.append(
                        {"role": "model", "content": f"✅ 画像を生成しました: {img_data['prompt']}"}
                    )
                    update_current_session_messages(messages)
                    status.update(label="✅ 画像生成完了", state="complete")
                else:
                    st.error("画像データが見つかりませんでした。")
                    status.update(label="❌ エラー", state="error")

            except Exception as e:
                status.update(label="❌ エラー", state="error")
                st.error(f"画像生成エラー: {e}")

# =========================
# チャット入力
# =========================

prompt = st.chat_input("何か聞いてください...", disabled=stop_generation)

if prompt:
    if stop_generation:
        st.error("予算上限に達しました。生成できません。")
    else:
        # ---- ユーザー発言表示 ----
        with st.chat_message("user"):
            st.markdown(prompt)
            if uploaded_files:
                for uf in uploaded_files:
                    st.caption(f"📎 添付: {uf.name}")
            if youtube_url:
                st.caption(f"📺 YouTube: {youtube_url}")
            if pasted_image_bytes:
                st.caption("📋 画像が貼り付けられました")

        messages.append({"role": "user", "content": prompt})
        update_current_session_messages(messages)

        # ---- モデル応答 ----
        with st.chat_message("assistant"):
            status_container = st.status("思考中...", expanded=True)
            try:
                # 会話履歴
                model_history = []
                for msg in messages[:-1]:
                    model_history.append(
                        types.Content(
                            role=msg["role"],
                            parts=[types.Part.from_text(text=msg["content"])],
                        )
                    )

                # 現在のターン
                current_parts = [types.Part.from_text(text=prompt)]

                # アップロードファイル
                for uploaded_file in uploaded_files or []:
                    try:
                        mime_type = get_mime_type(uploaded_file.name)
                        bytes_data = uploaded_file.getvalue()
                        part = types.Part.from_bytes(data=bytes_data, mime_type=mime_type)
                        current_parts.append(part)
                        status_container.write(f"ファイル準備完了: {uploaded_file.name}")
                    except Exception as e:
                        status_container.error(
                            f"ファイルの読み込みに失敗しました: {uploaded_file.name} - {e}"
                        )

                # 貼り付け画像
                if pasted_image_bytes:
                    import base64

                    status_container.write("貼り付けられた画像を処理中...")
                    try:
                        if isinstance(pasted_image_bytes, str):
                            if pasted_image_bytes.startswith("data:"):
                                base64_str = pasted_image_bytes.split(",", 1)[1]
                                image_bytes_decoded = base64.b64decode(base64_str)
                            else:
                                image_bytes_decoded = base64.b64decode(pasted_image_bytes)
                        else:
                            image_bytes_decoded = pasted_image_bytes
                        part = types.Part.from_bytes(
                            data=image_bytes_decoded, mime_type="image/png"
                        )
                        current_parts.append(part)
                        status_container.write("貼り付けられた画像の準備完了")
                    except Exception as e:
                        status_container.error(f"貼り付けられた画像の処理に失敗しました: {e}")

                # YouTube 字幕
                if youtube_url:
                    vid_id = extract_youtube_id(youtube_url)
                    if vid_id:
                        status_container.write("YouTubeの字幕を取得中...")
                        transcript_text = get_youtube_transcript(vid_id)
                        current_parts.append(
                            types.Part.from_text(text=f"YouTube Transcript:\n{transcript_text}")
                        )
                    else:
                        status_container.write("無効なYouTube URLです。")

                contents_for_model = model_history + [
                    types.Content(role="user", parts=current_parts)
                ]

                # ---- Tool / Config ----
                tools = []
                final_candidate_count = candidate_count
                if use_search:
                    tools.append(types.Tool(google_search=types.GoogleSearch()))
                    final_candidate_count = 1

                # ★ System Instruction の改善: メタ発言禁止とプロフェッショナルな振る舞いを指示
                base_system_instruction = (
                    "あなたは高度な知性を持つ専門的なリサーチ・アシスタントです。\n"
                    "以下のガイドラインを厳守してください：\n"
                    "1. **メタ発言の禁止**: 「私はAIです」「世界最高峰の～として」などの自己言及や前置きは一切行わないでください。\n"
                    "2. **意図の汲み取り**: ユーザーの質問の背後にある意図（文脈、暗黙の前提）を推測し、言葉通りではなく「ユーザーが本当に知りたいこと」に答えてください。\n"
                    "3. **構造化された回答**: 結論を先に述べ、その後に詳細な根拠、シナリオ分析、リスク要因を論理的に展開してください。\n"
                    "4. **客観性**: 予測を行う場合は、断定を避け、複数のシナリオ（楽観、悲観、中立）を提示してください。\n"
                    "5. **引用**: 検索を使用した場合は、必ず情報源を明示してください。"
                )

                final_answer = ""
                grounding_metadata = None
                
                # =========================
                # モード設定の解析
                # =========================
                # β1通常モード以外はリサーチを実行
                enable_research = "β1" not in response_mode
                enable_meta = "メタ" in response_mode or "MAX" in response_mode
                enable_strict = "鬼軍曹" in response_mode or "MAX" in response_mode
                enable_grok_x_search = "grok検索強化版" in response_mode

                # =========================
                # 通常モード (高速 / 鬼軍曹)
                # =========================
                if not enable_research:
                    config = types.GenerateContentConfig(
                        temperature=0.7,
                        candidate_count=1,
                        tools=tools,
                        system_instruction=base_system_instruction,
                    )
                    
                    status_container.write("回答生成中...")
                    response = client.models.generate_content(
                        model=model_id,
                        contents=contents_for_model,
                        config=config,
                    )
                    
                    final_answer = extract_text_from_response(response)
                    
                    # コスト計算
                    if response.usage_metadata:
                        cost = calculate_cost(
                            model_id,
                            response.usage_metadata.prompt_token_count,
                            response.usage_metadata.candidates_token_count,
                        )
                        st.session_state.session_cost += cost
                        usage_stats["total_cost_usd"] += cost
                        usage_stats["total_input_tokens"] += response.usage_metadata.prompt_token_count
                        usage_stats["total_output_tokens"] += response.usage_metadata.candidates_token_count

                    # 鬼軍曹レビュー (通常モード版)
                    if enable_strict:
                        status_container.write("レビューフェーズ実行中...")
                        reviewer_instruction = base_system_instruction + """
**あなたの役割**: 鬼軍曹レベルの厳格なレビューア
**タスク**: 初版回答をチェックし、必要なら修正版を返す
**出力**: 修正版の回答全文のみ
"""
                        review_contents = [types.Content(role="user", parts=[types.Part(text=f"ユーザー質問: {prompt}\n\n初版回答:\n{final_answer}\n\nレビューして修正版を出してください。")])]
                        review_resp = client.models.generate_content(
                            model=model_id,
                            contents=review_contents,
                            config=types.GenerateContentConfig(temperature=0.1, candidate_count=1, system_instruction=reviewer_instruction)
                        )
                        final_answer = extract_text_from_response(review_resp)
                        status_container.write("✓ レビュー完了")
                        
                        if review_resp.usage_metadata:
                            cost = calculate_cost(model_id, review_resp.usage_metadata.prompt_token_count, review_resp.usage_metadata.candidates_token_count)
                            st.session_state.session_cost += cost
                            usage_stats["total_cost_usd"] += cost
                            usage_stats["total_input_tokens"] += review_resp.usage_metadata.prompt_token_count
                            usage_stats["total_output_tokens"] += review_resp.usage_metadata.candidates_token_count

                # =========================
                # 熟考モード
                # =========================
                else:
                    # =========================
                    # 熟考モード: 多段階エージェントシステム
                    # =========================
                    
                    # --- Phase 1: リサーチエージェント ---
                    status_container.write("Phase 1: リサーチフェーズ実行中...")
                    
                    import datetime as dt
                    current_year = dt.datetime.now().year
                    
                    research_instruction = base_system_instruction + f"""

**あなたの役割**: リサーチ専任エージェント

**タスク**: ユーザーの質問に答えるための調査メモを作成してください。最終回答は書かず、事実収集に集中すること。

**調査観点**:
- 質問に関連する**最新の事実・データ・統計**（**{current_year}年の情報を最優先**）
- **現時点で存在する全ての選択肢・モデル・バージョンを網羅的に調査**（例: 製品比較なら、最新版だけでなく直近の全世代を調査）
- 公式情報や信頼できる情報源からの引用
- 関連する背景情報や文脈
- 競合・代替案・比較対象の**完全なリスト**
- リスク・制約・注意点（該当する場合）
- 参考にした主要な情報源のURL

**重要**: 
- 結論や推奨は書かず、後工程が判断できる調査メモに集中すること
- **必ず検索機能を使用し、最新の情報を取得すること**
- **検索結果に含まれる最新の日付・バージョン・モデル名を優先的に記載すること**
- **比較対象となる選択肢を見落とさないよう、複数の検索クエリを試すこと**（例: 「iPhone 最新モデル {current_year}」「iPhone {current_year}年発売」など）
- **「これより新しいモデル/バージョンは存在しないか？」を常に確認すること**
- 古い情報（{current_year-1}年以前など）しか見つからない場合は、その旨を明記すること
"""

                    # 過去の関連コンテキストを取得
                    past_context = get_relevant_context(prompt, st.session_state.sessions, st.session_state.current_session_id)
                    
                    # リサーチ用のコンテンツを構築
                    import datetime as dt
                    current_date = dt.datetime.now().strftime("%Y年%m月%d日")
                    research_parts = [types.Part(text=(
                        f"重要: 今日は{current_date}です。この日付より新しい情報を優先してください。\n\n"
                        f"質問: {prompt}"
                    ))]
                    
                    if past_context:
                        research_parts.insert(0, types.Part(text="以下は過去の関連チャットから抽出したコンテキストです：\n\n" + past_context))
                    
                    research_contents = contents_for_model + [
                        types.Content(role="user", parts=research_parts)
                    ]
                    
                    research_config = types.GenerateContentConfig(
                        temperature=0.4,  # 最新情報を柔軟に採用するため0.2→0.4に上昇
                        candidate_count=1,
                        tools=tools,
                        system_instruction=research_instruction,
                    )
                    
                    research_resp = client.models.generate_content(
                        model=model_id,
                        contents=research_contents,
                        config=research_config,
                    )
                    
                    research_text = extract_text_from_response(research_resp)
                    
                    # リサーチフェーズのグラウンディング情報を保存
                    if research_resp.candidates and research_resp.candidates[0].grounding_metadata:
                        grounding_metadata = research_resp.candidates[0].grounding_metadata
                    
                    status_container.write("✓ リサーチ完了")
                    with status_container.expander("収集した調査メモ", expanded=False):
                        st.markdown(research_text)
                    
                    # コスト計算 (Phase 1)
                    if research_resp.usage_metadata:
                        cost = calculate_cost(
                            model_id,
                            research_resp.usage_metadata.prompt_token_count,
                            research_resp.usage_metadata.candidates_token_count,
                        )
                        st.session_state.session_cost += cost
                        usage_stats["total_cost_usd"] += cost
                        usage_stats["total_input_tokens"] += research_resp.usage_metadata.prompt_token_count
                        usage_stats["total_output_tokens"] += research_resp.usage_metadata.candidates_token_count
                    
                    # --- Phase 1.5: メタ質問エージェント ---
                    questions_text = ""
                    if enable_meta:
                        status_container.write("Phase 1.5: メタ質問生成中...")
                        
                        question_instruction = base_system_instruction + """

**あなたの役割**: メタ質問エージェント

**目的**: 
ユーザーの元の質問と調査メモを踏まえて、このテーマをさらに深く理解するための「鋭いサブ質問」を作成すること。

**ルール**:
- 最大5個まで
- 各質問は1-2行で具体的かつ鋭く
- 以下の観点を意識:
  1. 前提が崩れる可能性はどこか？
  2. 強気/弱気シナリオの分岐点は何か？
  3. 競合・技術・規制の不確実性は？
  4. 「予測が外れるとしたらどんなパターンか？」

**出力**: 箇条書き（Q1, Q2...）のみ
"""

                        question_contents = [types.Content(role="user", parts=[types.Part(text=f"ユーザーの元の質問:\n{prompt}\n\n==== 調査メモ ====\n{research_text}\n==== 調査メモここまで ====\n\nこのテーマをさらに深掘りするための重要なサブ質問を作成してください。")])]
                        
                        question_resp = client.models.generate_content(
                            model=model_id,
                            contents=question_contents,
                            config=types.GenerateContentConfig(
                                temperature=0.4,
                                candidate_count=1,
                                system_instruction=question_instruction,
                            )
                        )
                        
                        questions_text = extract_text_from_response(question_resp)
                        
                        status_container.write("✓ メタ質問生成完了")
                        with status_container.expander("生成されたメタ質問", expanded=False):
                            st.markdown(questions_text)
                        
                        st.session_state.session_cost += cost
                        usage_stats["total_cost_usd"] += cost
                        usage_stats["total_input_tokens"] += question_resp.usage_metadata.prompt_token_count
                        usage_stats["total_output_tokens"] += question_resp.usage_metadata.candidates_token_count

                    # 多層+puterモードの鬼軍曹モードかチェック
                    is_puter_onigunsou = (
                        mode_category == "β：🎯 回答モード(多層+puter)" and
                        response_mode == "1. 熟考 + 鬼軍曹(localのみ)"
                    )

                    # --- Phase 1.5b: Grok 独立思考 (多層モードのみ) ---
                    # --- Phase 1.5b: Grok 独立思考 (多層モードのみ) ---
                    grok_thought = ""
                    grok_status = "skipped"
                    if enable_meta and OPENROUTER_API_KEY:
                        status_container.write("Phase 1.5b: Grok 独立思考中...")
                        try:
                            grok_thought = think_with_grok(prompt, research_text, enable_x_search=enable_grok_x_search)
                            if grok_thought:
                                grok_status = "success"
                                status_container.write("✓ Grok 4.1 Fast Free 独立思考完了")
                                with status_container.expander("Grokの独立回答案", expanded=False):
                                    st.markdown(grok_thought)
                            else:
                                grok_status = "empty"
                        except Exception as e:
                            grok_status = "error"
                            status_container.write(f"⚠ Grok思考エラー: {e}")

                    # --- Phase 1.5c: Claude Opus 4.5 独立思考 (多層+puterの鬼軍曹のみ) ---
                    # --- Phase 1.5c: Claude Opus 4.5 独立思考 (多層+puterの鬼軍曹のみ) ---
                    claude_thought = ""
                    claude_status = "skipped"
                    if is_puter_onigunsou and PUTER_USERNAME and PUTER_PASSWORD:
                        status_container.write("Phase 1.5c: Claude Opus 4.5 独立思考中...")
                        try:
                            claude_thought = call_claude_opus_via_puter(
                                user_question=prompt,
                                research_text=research_text,
                                system_prompt=(
                                    "あなたは Claude Opus 4.5 です。"
                                    "Gemini が集めた調査メモを参考にしつつも、"
                                    "自分の視点で独立した回答案・気づきを出してください。"
                                    "Gemini の意見に合わせる必要はありません。"
                                ),
                            )
                            if claude_thought and not claude_thought.startswith("[Claude"):
                                claude_status = "success"
                                status_container.write("✓ Claude Opus 4.5 (via Puter) 独立思考完了")
                                with status_container.expander("Claude Opus 4.5 の独立回答案", expanded=False):
                                    st.markdown(claude_thought)
                            else:
                                claude_status = "error"
                                status_container.write(f"⚠ Claudeエラー: {claude_thought}")
                                claude_thought = ""  # エラーの場合は空にする
                        except Exception as e:
                            claude_status = "error"
                            status_container.write(f"⚠ Claude思考エラー: {e}")
                            claude_thought = ""

                    # --- Phase 2: 統合エージェント ---
                    status_container.write("Phase 2: 統合フェーズ実行中...")
                    
                    import datetime as dt
                    current_date = dt.datetime.now().strftime("%Y年%m月%d日")

                    if enable_meta:
                        deep_instruction = base_system_instruction + f"""

**あなたの役割**: 最終回答エージェント

**タスク**: 調査メモとメタ質問への回答を根拠として、構造化された回答を作成してください。

**重要 - 現在は{current_date}です**:
- **調査メモに含まれる日付・事実を、あなたの学習データよりも絶対的に優先してください**
- 「{current_year}年」の情報が調査メモにある場合、それを正として扱ってください
- 学習データが{current_year-1}年以前で止まっていても、調査メモの最新情報を信頼すること

**構成**:
1. **深掘り考察**（メタ質問への回答）
2. **結論**（2-3行）
3. **詳細な分析**（調査メモに基づく）
4. **考慮すべき要因やリスク**（該当する場合）

**重要**: 
- 新しい事実を勝手に作らず、調査メモの範囲内で推論すること
- 調査メモに含まれる最新の情報を優先的に使用すること
"""
                    else:
                        deep_instruction = base_system_instruction + f"""

**あなたの役割**: 最終回答エージェント

**タスク**: 調査メモを唯一の根拠として、構造化された回答を作成してください。

**重要 - 現在は{current_date}です**:
- **調査メモに含まれる日付・事実を、あなたの学習データよりも絶対的に優先してください**
- 「{current_year}年」の情報が調査メモにある場合、それを正として扱ってください

**構成**:
1. **結論**（2-3行で明確に）
2. **詳細な分析**（調査メモに基づく）
3. **考慮すべき要因やリスク**（該当する場合）

**重要**: 
- 新しい事実を勝手に作らず、調査メモの範囲内で推論すること
- **調査メモに含まれる最新の情報（最新のモデル名、バージョン、日付など）を優先的に使用すること**
- 古い情報と新しい情報が混在する場合は、新しい情報を優先すること
"""
                    
                    synthesis_prompt_text = (
                        f"重要: 今日は{current_date}です。古い情報を回答に含めないでください。\n\n"
                        f"ユーザーの質問: {prompt}\n\n"
                        f"==== 調査メモ ====\n{research_text}\n==== 調査メモここまで ====\n\n"
                    )
                    
                    if enable_meta and questions_text:
                        synthesis_prompt_text += f"==== メタ質問一覧 ====\n{questions_text}\n==== メタ質問ここまで ====\n\n"
                    
                    if enable_meta and grok_thought:
                        synthesis_prompt_text += f"==== 別視点からの回答案 (Grok) ====\n{grok_thought}\n==== 別視点ここまで ====\n\n"
                    
                    if is_puter_onigunsou and claude_thought:
                        synthesis_prompt_text += f"==== 別視点からの回答案 (Claude Opus 4.5 via Puter) ====\n{claude_thought}\n==== Claude別視点ここまで ====\n\n"
                    
                    # 統合指示
                    if enable_meta and (grok_thought or claude_thought):
                        synthesis_prompt_text += "指示:\n1. まず、メタ質問 Q1〜Qn に一つずつ簡潔に答えてください。\n2. Grok"
                        if is_puter_onigunsou and claude_thought:
                            synthesis_prompt_text += " / Claude"
                        synthesis_prompt_text += " の回答案も参考にしつつ（ただし盲信せず）、独自の視点で統合してください。\n3. そのうえで、それらの回答を踏まえた『全体としての結論・分析・示唆』をまとめてください。"
                    elif enable_meta and questions_text:
                        synthesis_prompt_text += "指示:\n1. まず、メタ質問 Q1〜Qn に一つずつ簡潔に答えてください。\n2. そのうえで、それらの回答を踏まえた『全体としての結論・分析・示唆』をまとめてください。"
                    else:
                        synthesis_prompt_text += "上記メモを根拠に、最終回答を作成してください。**調査メモに含まれる最新の情報を必ず使用してください。**"

                    synthesis_contents = contents_for_model + [
                        types.Content(role="user", parts=[
                            types.Part(text=synthesis_prompt_text)
                        ])
                    ]
                    
                    synthesis_config = types.GenerateContentConfig(
                        temperature=0.3,
                        candidate_count=1,
                        tools=[],  # 統合フェーズでは検索OFF
                        system_instruction=deep_instruction,
                    )
                    
                    synthesis_resp = client.models.generate_content(
                        model=model_id,
                        contents=synthesis_contents,
                        config=synthesis_config,
                    )
                    
                    draft_answer = extract_text_from_response(synthesis_resp)
                    
                    status_container.write("✓ 統合完了")
                    
                    # コスト計算 (Phase 2)
                    if synthesis_resp.usage_metadata:
                        cost = calculate_cost(
                            model_id,
                            synthesis_resp.usage_metadata.prompt_token_count,
                            synthesis_resp.usage_metadata.candidates_token_count,
                        )
                        st.session_state.session_cost += cost
                        usage_stats["total_cost_usd"] += cost
                        usage_stats["total_input_tokens"] += synthesis_resp.usage_metadata.prompt_token_count
                        usage_stats["total_output_tokens"] += synthesis_resp.usage_metadata.candidates_token_count
                    
                    # --- Phase 3: レビューエージェント (鬼軍曹モードのみ) ---
                    if enable_strict:
                        status_container.write("Phase 3: レビューフェーズ実行中...")
                        

                        reviewer_instruction = base_system_instruction + """

**あなたの役割**: 鬼軍曹レベルの厳格なレビューア

**タスク**: 初版回答をチェックし、必要なら修正版を返す。ただし、**調査メモの情報を優先し、最新情報を維持すること**。

**レビュー観点**:
- 事実と推測を明確に分ける
- 過度に自信のある断定を弱める
- 数字や固有名詞が調査メモと矛盾していないか確認
- **調査メモに含まれる最新の情報（最新モデル、バージョン、日付など）が正しく使われているか確認**
- **古い情報で上書きしていないか確認**
- 見落としている重要なリスク・シナリオがあれば追加

**重要**: 
- 調査メモの情報が最新である場合、それを優先すること
- あなたの知識が古い場合は、調査メモの情報を信頼すること

**出力**: 修正版の回答全文のみ
"""

                        review_contents = [
                            types.Content(role="user", parts=[
                                types.Part.from_text(
                                    text=f"ユーザー質問: {prompt}\n\n"
                                    f"==== 調査メモ ====\n{research_text}\n==== 調査メモここまで ====\n\n"
                                    f"初版回答:\n{draft_answer}\n\n"
                                    "上記をレビューし、必要なら修正版を出してください。**調査メモに含まれる最新情報を維持してください。**"
                                )
                            ])
                        ]
                        
                        review_config = types.GenerateContentConfig(
                            temperature=0.1,
                            candidate_count=1,
                            system_instruction=reviewer_instruction,
                            thinking_config=types.ThinkingConfig(
                                thinking_level=types.ThinkingLevel.HIGH
                            ),
                        )
                        
                        review_resp = client.models.generate_content(
                            model=model_id,
                            contents=review_contents,
                            config=review_config,
                        )
                        
                        final_answer = extract_text_from_response(review_resp)
                        
                        status_container.write("✓ レビュー完了")
                        
                        # --- Phase 3b: Grok鬼軍曹レビュー (多層モード + 鬼軍曹モード全般) ---
                        # 多層モードで、かつ鬼軍曹系のモード（鬼軍曹、メタ思考、本気MAX）で発動
                        use_grok_reviewer = (mode_category == "🎯 回答モード(多層)" and enable_strict)
                        
                        if use_grok_reviewer and OPENROUTER_API_KEY:
                            status_container.write("Phase 3b: Grok 4.1 Fast で最終チェック中...")
                            try:
                                grok_answer = review_with_grok(prompt, final_answer, research_text)
                                # Grok使用時は、モデル名を明示し、2段構成で表示
                                final_answer = (
                                    f"**🤖 使用モデル: {model_id} (Deep Thinking / High Reasoning)**\n"
                                    f"**レビュア: Grok 4.1 Fast (free)**\n"
                                    f"**モード: {response_mode}**\n\n"
                                    "---\n\n"
                                    "## ✅ 最終回答（Gemini統合版）\n\n"
                                    f"{final_answer}\n\n"
                                    "---\n\n"
                                    "## 🔍 Grok によるレビュー\n\n"
                                    f"{grok_answer}"
                                )
                                status_container.write("✓ Grok最終レビュー完了")
                            except Exception as e:
                                status_container.write(f"⚠ Grokレビューエラー: {e}")
                        else:
                            # Geminiのみの場合もモデル名を表示（多層モードの場合）
                            if mode_category == "🎯 回答モード(多層)":
                                final_answer = (
                                    f"**🤖 使用モデル: {model_id} (Deep Thinking / High Reasoning)**\n"
                                    f"**モード: {response_mode}**\n\n---\n\n{final_answer}"
                                )
                        
                        # --- メタ思考モード: 結論を先出しする ---
                        if "メタ思考" in response_mode:
                            # 結論部分を抽出（簡易的な実装）
                            # "結論"や"まとめ"などのセクションを探して先頭に移動
                            lines = final_answer.split('\n')
                            conclusion_start = -1
                            for i, line in enumerate(lines):
                                if any(keyword in line for keyword in ['## 結論', '## まとめ', '**結論**', '**まとめ**']):
                                    conclusion_start = i
                                    break
                            
                            if conclusion_start != -1:
                                # 結論セクションを見つけた場合、それを先頭に移動
                                conclusion_section = []
                                other_content = lines[:conclusion_start]
                                
                                # 結論セクションの終わりを見つける（次の##まで or 文末）
                                conclusion_end = len(lines)
                                for i in range(conclusion_start + 1, len(lines)):
                                    if lines[i].startswith('## ') and i != conclusion_start:
                                        conclusion_end = i
                                        break
                                
                                conclusion_section = lines[conclusion_start:conclusion_end]
                                remaining_content = lines[conclusion_end:]
                                
                                # 再構成: モデル名 → 結論 → その他の詳細
                                # モデル名部分を保持
                                model_line = ""
                                if lines[0].startswith("**🤖"):
                                    model_line = lines[0]
                                    other_content = lines[1:conclusion_start]
                                
                                final_answer = '\n'.join([
                                    model_line,
                                    "",
                                    "---",
                                    "",
                                    "## 📌 結論（先出し）",
                                    *conclusion_section[1:],  # 元の見出しを除く
                                    "",
                                    "---",
                                    "",
                                    "## 📝 詳細",
                                    *other_content,
                                    *remaining_content
                                ]).strip()
                        
                        with status_container.expander("初版との比較", expanded=False):
                            st.markdown("**初版:**")
                            st.markdown(draft_answer[:500] + "..." if len(draft_answer) > 500 else draft_answer)
                            st.markdown("**修正版:**")
                            st.markdown(final_answer[:500] + "..." if len(final_answer) > 500 else final_answer)
                        
                        # コスト計算 (Phase 3)
                        if review_resp.usage_metadata:
                            cost = calculate_cost(
                                model_id,
                                review_resp.usage_metadata.prompt_token_count,
                                review_resp.usage_metadata.candidates_token_count,
                            )
                            st.session_state.session_cost += cost
                            usage_stats["total_cost_usd"] += cost
                            usage_stats["total_input_tokens"] += review_resp.usage_metadata.prompt_token_count
                            usage_stats["total_output_tokens"] += review_resp.usage_metadata.candidates_token_count
                    else:
                        final_answer = draft_answer

                save_usage(usage_stats)
                status_container.update(label="完了！", state="complete", expanded=False)

                # モデル名を表示
                models_used = [f"Gemini: {model_id}"]
                
                # Grok Status
                if enable_meta:
                    if grok_status == "success":
                        models_used.append("Grok: 4.1-fast-free (OK)")
                    elif grok_status == "error":
                        models_used.append("Grok: 4.1-fast-free (Error)")
                    elif grok_status == "empty":
                        models_used.append("Grok: 4.1-fast-free (Empty)")
                
                # Claude Status
                if is_puter_onigunsou:
                    if claude_status == "success":
                        models_used.append("Claude: Opus 4.5 (via Puter) (OK)")
                    elif claude_status == "error":
                        models_used.append("Claude: Opus 4.5 (via Puter) (Error)")
                
                st.caption(f"🤖 使用モデル: {' + '.join(models_used)}")
                st.markdown(final_answer)

                # ---- グラウンディング情報 ----
                if grounding_metadata:
                    st.markdown("---")
                    with st.expander("📚 情報源と引用", expanded=False):
                        if grounding_metadata.grounding_chunks:
                            st.markdown("**検索結果から利用した情報源:**")
                            unique_sources = {}
                            import urllib.parse

                            for chunk in grounding_metadata.grounding_chunks:
                                if getattr(chunk, "web", None):
                                    uri = getattr(chunk.web, "uri", None)
                                    title = getattr(chunk.web, "title", "情報源")
                                    if uri and uri not in unique_sources:
                                        parsed = urllib.parse.urlparse(uri)
                                        domain = parsed.netloc.replace("www.", "")
                                        unique_sources[uri] = {
                                            "title": title,
                                            "domain": domain,
                                        }
                            for i, (uri, info) in enumerate(unique_sources.items(), 1):
                                st.markdown(f"{i}. **[{info['title']}]({uri})**")
                                st.caption(f"   出典: {info['domain']}")

                messages.append({"role": "model", "content": final_answer})
                update_current_session_messages(messages)

            except Exception as e:
                status_container.update(label="Error", state="error")
                err_text = str(e)
                if "RESOURCE_EXHAUSTED" in err_text or "429" in err_text:
                    st.error(
                        "⚠️ Vertex AI / Gemini のクォータに達しました。\n\n"
                        "・プロジェクトのレート制限 / 日次制限の可能性があります。\n"
                        "・しばらく時間をおいて再度お試しください。\n"
                        "・Google Cloud Console の「Vertex AI → 使用状況」からクォータ状況を確認できます。"
                    )
                elif "NOT_FOUND" in err_text and "Publisher Model" in err_text:
                    st.error(
                        "⚠️ 指定したモデルがこのプロジェクト / ロケーションでは利用できません。\n"
                        "・サイドバーのモデルIDを、2.5系 または 3 Pro に変更してお試しください。\n"
                    )
                else:
                    st.error(f"An error occurred: {e}")
