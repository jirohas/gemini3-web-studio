import os
import json
import re
import uuid
import datetime
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from youtube_transcript_api import YouTubeTranscriptApi

# Load environment variables
load_dotenv()

# Constants
USAGE_FILE = "usage_stats.json"
SESSIONS_FILE = "chat_sessions.json"
MAX_BUDGET_USD = float(os.getenv("MAX_BUDGET_USD", "5.0"))

# Pricing (USD per 1M tokens) - Approximate
PRICING = {
    "gemini-2.0-flash-exp": {"input": 0.0, "output": 0.0}, 
    "gemini-2.0-flash-thinking-exp": {"input": 0.0, "output": 0.0}, 
    "gemini-3-pro-preview": {"input": 2.0, "output": 12.0}, 
    "gemini-1.5-pro": {"input": 3.50, "output": 10.50},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}

st.set_page_config(page_title="Gemini 3 Web Studio", layout="wide")

# --- Helper Functions ---

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

def get_mime_type(filename):
    ext = filename.split('.')[-1].lower()
    if ext in ['jpg', 'jpeg']: return 'image/jpeg'
    if ext == 'png': return 'image/png'
    if ext == 'mp4': return 'video/mp4'
    if ext == 'mov': return 'video/quicktime'
    if ext == 'txt': return 'text/plain'
    if ext == 'pdf': return 'application/pdf'
    if ext == 'csv': return 'text/csv'
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

# --- Session Management ---

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

def create_new_session():
    new_id = str(uuid.uuid4())
    new_session = {
        "id": new_id,
        "title": "新しいチャット",
        "timestamp": datetime.datetime.now().isoformat(),
        "messages": []
    }
    st.session_state.sessions.insert(0, new_session)
    st.session_state.current_session_id = new_id
    save_sessions(st.session_state.sessions)
    st.rerun()

def switch_session(session_id):
    st.session_state.current_session_id = session_id
    st.rerun()

def update_current_session_messages(messages):
    if st.session_state.current_session_id:
        for session in st.session_state.sessions:
            if session["id"] == st.session_state.current_session_id:
                session["messages"] = messages
                # Auto-title if it's "New Chat" and has messages
                if session["title"] == "新しいチャット" and len(messages) > 0:
                    first_msg = messages[0]["content"]
                    session["title"] = (first_msg[:20] + "...") if len(first_msg) > 20 else first_msg
                session["timestamp"] = datetime.datetime.now().isoformat()
                break
        save_sessions(st.session_state.sessions)

def get_current_messages():
    if st.session_state.current_session_id:
        for session in st.session_state.sessions:
            if session["id"] == st.session_state.current_session_id:
                return session["messages"]
    return []

def delete_session(session_id):
    st.session_state.sessions = [s for s in st.session_state.sessions if s["id"] != session_id]
    save_sessions(st.session_state.sessions)
    if st.session_state.current_session_id == session_id:
        st.session_state.current_session_id = None
        if st.session_state.sessions:
            st.session_state.current_session_id = st.session_state.sessions[0]["id"]
    st.rerun()

# --- Initialization ---

if "sessions" not in st.session_state:
    st.session_state.sessions = load_sessions()

if "current_session_id" not in st.session_state:
    if st.session_state.sessions:
        st.session_state.current_session_id = st.session_state.sessions[0]["id"]
    else:
        create_new_session() # Will rerun

if "session_cost" not in st.session_state:
    st.session_state.session_cost = 0.0

usage_stats = load_usage()

# --- Sidebar ---

with st.sidebar:
    st.title("Gemini 3 Studio")
    
    if st.button("➕ 新しいチャット", use_container_width=True):
        create_new_session()
    
    st.markdown("---")
    
    # History Search & List
    search_query = st.text_input("🔍 履歴を検索", placeholder="キーワード...")
    
    filtered_sessions = []
    if search_query:
        for s in st.session_state.sessions:
            # Check title
            if search_query.lower() in s["title"].lower():
                filtered_sessions.append(s)
                continue
            # Check messages
            found_in_msg = False
            for m in s["messages"]:
                if search_query.lower() in m["content"].lower():
                    filtered_sessions.append(s)
                    found_in_msg = True
                    break
            if not found_in_msg:
                pass # Not found
    else:
        filtered_sessions = st.session_state.sessions

    with st.expander("📜 過去のチャット", expanded=not bool(search_query)):
        if not filtered_sessions:
            st.caption("チャットが見つかりません。")
        for session in filtered_sessions:
            col1, col2 = st.columns([0.8, 0.2])
            with col1:
                if st.button(session["title"], key=f"btn_{session['id']}", use_container_width=True):
                    switch_session(session["id"])
            with col2:
                if st.button("🗑️", key=f"del_{session['id']}"):
                    delete_session(session["id"])
    
    st.markdown("---")
    st.title("設定")
    
    # Model Selection
    model_options = ["gemini-3-pro-preview", "gemini-2.0-flash-thinking-exp", "gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"]
    model_id = st.selectbox("モデルID", options=model_options, index=0)
    
    # Search Grounding
    use_search = st.toggle("Google検索グラウンディングを使用", value=True)
    
    # Candidate Count
    candidate_count = st.slider("回答候補数", min_value=1, max_value=3, value=3)
    if use_search and candidate_count > 1:
        st.caption("⚠️ 検索グラウンディング使用時は候補数が1になります。")
    
    st.markdown("---")
    
    # File Upload
    st.subheader("添付ファイル")
    uploaded_files = st.file_uploader(
        "画像、動画、ファイルをアップロード", 
        type=['png', 'jpg', 'jpeg', 'mp4', 'mov', 'txt', 'pdf', 'csv'],
        accept_multiple_files=True
    )
    
    # YouTube Link
    youtube_url = st.text_input("YouTube URL (字幕を分析)")
    
    st.markdown("---")
    
    # Cost Tracking
    st.subheader("コスト追跡")
    
    # Budget Check
    if usage_stats["total_cost_usd"] >= MAX_BUDGET_USD:
        st.error(f"🚨 予算オーバー！ 上限: ${MAX_BUDGET_USD:.2f}")
        stop_generation = True
    else:
        stop_generation = False
    
    col1, col2 = st.columns(2)
    col1.metric("セッション", f"${st.session_state.session_cost:.4f}")
    col2.metric("合計", f"${usage_stats['total_cost_usd']:.4f}")
    
    st.progress(min(usage_stats["total_cost_usd"] / MAX_BUDGET_USD, 1.0) if MAX_BUDGET_USD > 0 else 0)
    st.caption(f"予算: ${MAX_BUDGET_USD:.2f}")
    
    st.markdown("---")
    st.code(f"PROJECT: {os.getenv('GOOGLE_CLOUD_PROJECT')}\nLOCATION: {os.getenv('GOOGLE_CLOUD_LOCATION')}")

# --- Main Interface ---

# st.title("Gemini 3 Web Studio") # Moved to sidebar title or keep here? Let's keep a header.
# Actually, let's show the current session title
current_session_title = "新しいチャット"
for s in st.session_state.sessions:
    if s["id"] == st.session_state.current_session_id:
        current_session_title = s["title"]
        break

st.header(current_session_title)
st.markdown("以下に質問を入力してください。マルチターン会話、ファイルアップロード、YouTube分析、検索グラウンディングに対応しています。")

# Initialize Client
@st.cache_resource
def get_client():
    return genai.Client(
        vertexai=True, 
        project=os.getenv("GOOGLE_CLOUD_PROJECT"), 
        location=os.getenv("GOOGLE_CLOUD_LOCATION")
    )

client = get_client()

# Get Messages for Current Session
messages = get_current_messages()

# Display History
for msg in messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat Input
if prompt := st.chat_input("何か聞いてください...", disabled=stop_generation):
    if stop_generation:
        st.error("予算上限に達しました。生成できません。")
    else:
        # 1. Show User Message
        with st.chat_message("user"):
            st.markdown(prompt)
            if uploaded_files:
                for uf in uploaded_files:
                    st.caption(f"📎 添付: {uf.name}")
            if youtube_url:
                st.caption(f"📺 YouTube: {youtube_url}")
        
        # Add to history (User) - Update local var and session state
        messages.append({"role": "user", "content": prompt})
        update_current_session_messages(messages)

        # 2. Generate Response
        with st.chat_message("assistant"):
            status_container = st.status("思考中...", expanded=True)
            
            try:
                # Prepare Contents (History + Current)
                contents = []
                
                # Add History
                for msg in messages[:-1]: 
                    contents.append(types.Content(
                        role=msg["role"],
                        parts=[types.Part.from_text(text=msg["content"])]
                    ))
                
                # Prepare Current Content
                current_parts = [types.Part.from_text(text=prompt)]
                
                # Handle File Uploads
                if uploaded_files:
                    for uf in uploaded_files:
                        mime_type = get_mime_type(uf.name)
                        file_bytes = uf.getvalue()
                        current_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
                
                # Handle YouTube
                if youtube_url:
                    vid_id = extract_youtube_id(youtube_url)
                    if vid_id:
                        status_container.write("YouTubeの字幕を取得中...")
                        transcript_text = get_youtube_transcript(vid_id)
                        current_parts.append(types.Part.from_text(text=f"YouTube Transcript:\n{transcript_text}"))
                    else:
                        status_container.write("無効なYouTube URLです。")
                
                contents.append(types.Content(role="user", parts=current_parts))

                # Config
                tools = []
                final_candidate_count = candidate_count
                
                if use_search:
                    tools.append(types.Tool(google_search=types.GoogleSearch()))
                    final_candidate_count = 1
                
                # System Instruction for "GPT-5.1 Pro Level"
                system_instruction = """
                あなたは世界最高峰の金融・技術アナリストです。
                ユーザーの質問に対し、以下の「理想的なフォーマット」に従って、極めて詳細かつ構造化された回答を作成してください。

                **必須フォーマット:**
                1. **エグゼクティブサマリー**: 結論を2-3行でズバリと述べる（太字を活用）。
                2. **基本データ (Stock Market Info)**: 株価、時価総額、売上高、PERなどの最新データを箇条書きで提示。
                3. **詳細分析 (Deep Dive)**:
                   - 各論点（例：NVDA問題、TPU競合、マイケル・バリーの指摘）ごとに見出しを立てる。
                   - 単なる事実だけでなく、「それが何を意味するか（Implication）」を深掘りする。
                   - ブル（強気）、ベース、ベア（弱気）のシナリオ分析を含める。
                4. **結論と投資判断**: 明確なスタンスを示す。
                5. **参考文献 (References)**: 記事やデータの出展元を明記する。

                **品質基準:**
                - **事実重視**: Google検索を活用し、最新の数字（日付つき）を引用すること。
                - **論理性**: 感情論ではなく、ロジックとデータで語ること。
                - **網羅性**: ユーザーが提示したキーワード（動画やファイル含む）は全て分析に組み込むこと。
                """

                config = types.GenerateContentConfig(
                    temperature=0.7, 
                    candidate_count=final_candidate_count,
                    tools=tools,
                    system_instruction=system_instruction
                )

                # Generate
                status_container.write("コンテンツ生成中...")
                response = client.models.generate_content(
                    model=model_id,
                    contents=contents,
                    config=config,
                )
                
                # Extract Text
                candidates_text = []
                grounding_metadata = None
                
                if response.candidates:
                    for i, cand in enumerate(response.candidates):
                        parts = cand.content.parts if cand.content and cand.content.parts else []
                        text = "".join(p.text or "" for p in parts)
                        candidates_text.append(text)
                        status_container.write(f"候補生成完了 {i+1}")
                        if cand.grounding_metadata:
                            grounding_metadata = cand.grounding_metadata
                
                final_answer = ""
                if len(candidates_text) >= 1:
                    final_answer = candidates_text[0]
                else:
                    final_answer = "回答が生成されませんでした。"

                # Update Cost
                if response.usage_metadata:
                    cost = calculate_cost(
                        model_id, 
                        response.usage_metadata.prompt_token_count, 
                        response.usage_metadata.candidates_token_count
                    )
                    st.session_state.session_cost += cost
                    usage_stats["total_cost_usd"] += cost
                    usage_stats["total_input_tokens"] += response.usage_metadata.prompt_token_count
                    usage_stats["total_output_tokens"] += response.usage_metadata.candidates_token_count
                
                # Save Stats
                save_usage(usage_stats)

                status_container.update(label="完了！", state="complete", expanded=False)
                
                st.markdown(final_answer)
                
                # Append Citations from Grounding Metadata if available
                if grounding_metadata:
                    st.markdown("---")
                    st.subheader("情報源と引用")
                    if grounding_metadata.search_entry_point:
                        st.markdown(grounding_metadata.search_entry_point.rendered_content, unsafe_allow_html=True)
                    if grounding_metadata.grounding_chunks:
                        with st.expander("詳細な引用箇所"):
                            for i, chunk in enumerate(grounding_metadata.grounding_chunks):
                                if chunk.web:
                                    st.markdown(f"**[{i+1}] {chunk.web.title}**")
                                    st.markdown(f"URL: {chunk.web.uri}")
                                    st.caption(f"Source: {chunk.web.uri}")

                # Add to History
                messages.append({"role": "model", "content": final_answer})
                update_current_session_messages(messages)

            except Exception as e:
                status_container.update(label="Error", state="error")
                st.error(f"An error occurred: {e}")
