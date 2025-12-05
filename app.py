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
    extract_text_from_response, load_sessions, save_sessions, get_client,
    load_user_profile, save_user_profile, update_user_profile_from_conversation,
    build_full_session_memory
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

# 🔐 パスワードロック + URLトークン永続化
# パスワードとトークンを環境変数から取得
try:
    if "APP_PASSWORD" in st.secrets:
        APP_PASSWORD = st.secrets["APP_PASSWORD"]
        SECRET_TOKEN = st.secrets.get("SECRET_TOKEN", "access_granted_default")
    else:
        APP_PASSWORD = os.getenv("APP_PASSWORD", "198501")  # フォールバック（開発用）
        SECRET_TOKEN = os.getenv("SECRET_TOKEN", "access_granted_198501")
except:
    APP_PASSWORD = os.getenv("APP_PASSWORD", "198501")
    SECRET_TOKEN = os.getenv("SECRET_TOKEN", "access_granted_198501")

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
        if password == APP_PASSWORD:
            st.session_state.authenticated = True
            # セキュリティ修正: URLからトークンを削除（ブラウザ履歴/スクショ漏洩防止）
            st.query_params.clear()
            st.rerun()
        else:
            st.error("パスワードが違います。")

    st.stop()

# =========================
# Early Gemini Client Function (for recommendations before main init)
# =========================
@st.cache_resource
def get_gemini_client():
    """
    Gemini クライアントを初期化（Streamlit Secrets対応）
    
    Streamlit Cloud: st.secretsからサービスアカウント認証情報を使用
    ローカル開発: Application Default Credentials
    """
    try:
        # Get project ID from environment variable or secrets
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        
        # Streamlit Cloud: Service Account via secrets
        if "GOOGLE_CREDENTIALS" in st.secrets:
            from google.oauth2 import service_account
            creds_dict = dict(st.secrets["GOOGLE_CREDENTIALS"])
            
            # Use project_id from credentials if not set
            if not project_id:
                project_id = creds_dict.get("project_id")
            
            scoped_creds = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            
            print(f"[DEBUG] Using secrets auth with project_id: {project_id}")
            
            return genai.Client(
                vertexai=True,
                project=project_id,
                location=VERTEX_LOCATION,
                credentials=scoped_creds
            )
        else:
            # No secrets - use environment variables
            print(f"[DEBUG] No GOOGLE_CREDENTIALS in secrets, using env vars")
            
            if not project_id:
                raise ValueError("GOOGLE_CLOUD_PROJECT environment variable is required")
            
            # Check if we have service account JSON in env
            if "GOOGLE_APPLICATION_CREDENTIALS_JSON" in os.environ:
                import json
                from google.oauth2 import service_account
                
                creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
                creds_dict = json.loads(creds_json)
                
                scoped_creds = service_account.Credentials.from_service_account_info(
                    creds_dict,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                
                print(f"[DEBUG] Using env JSON auth with project_id: {project_id}")
                
                return genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=VERTEX_LOCATION,
                    credentials=scoped_creds
                )
            else:
                # Application Default Credentials
                print(f"[DEBUG] Using ADC with project_id: {project_id}")
                
                return genai.Client(
                    vertexai=True,
                    project=project_id,
                    location=VERTEX_LOCATION,
                )
    except Exception as e:
        print(f"❌ Gemini Client初期化エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

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
# curl_cffi は未使用のため削除（Puter廃止に伴い不要）
import textwrap

def wrap_recommendation_text(text, width=20):
    """
    推薦テキストを指定幅で自動改行（サイドバー表示用）
    見出しや重要な行は保持し、本文のみ改行
    
    Args:
        text: 改行するテキスト
        width: 1行の最大文字数（デフォルト20文字）
    
    Returns:
        改行処理されたテキスト
    """
    lines = text.split('\n')
    wrapped_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        # 空行はそのまま保持
        if not stripped:
            wrapped_lines.append(line)
            continue
        
        # 見出し行（#始まり、**囲み、数字.始まり）は改行しない
        if (stripped.startswith('#') or 
            stripped.startswith('**') or 
            (len(stripped) > 2 and stripped[0].isdigit() and stripped[1] == '.')):
            wrapped_lines.append(line)
            continue
        
        # 短い行（width以下）はそのまま保持
        if len(stripped) <= width:
            wrapped_lines.append(line)
            continue
        
        # インデント（箇条書き）を保持
        indent = len(line) - len(line.lstrip())
        indent_str = ' ' * indent
        
        # 長い本文のみ改行処理
        wrapped = textwrap.fill(
            stripped, 
            width=width,
            break_long_words=True,
            break_on_hyphens=True,
            initial_indent=indent_str,
            subsequent_indent=indent_str + '  '
        )
        wrapped_lines.append(wrapped)
    
    return '\n'.join(wrapped_lines)

# OpenRouter API Keyの取得 (st.secrets優先、なければ環境変数)
try:
    if "OPENROUTER_API_KEY" in st.secrets:
        OPENROUTER_API_KEY = str(st.secrets["OPENROUTER_API_KEY"]).strip()
        if not OPENROUTER_API_KEY:  # 空文字ならenv変数にフォールバック
            OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    else:
        OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
except Exception as e:
    # デバッグ用：エラーを表示
    # st.error(f"OPENROUTER_API_KEY読み込みエラー: {e}")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Puter認証情報は削除（AWS Bedrockに移行）


# ▼▼▼ AWS Bedrock (Claude 4.5 Sonnet用) ▼▼▼
try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

# AWS認証情報取得
try:
    if "AWS_ACCESS_KEY_ID" in st.secrets:
        AWS_ACCESS_KEY_ID = str(st.secrets["AWS_ACCESS_KEY_ID"]).strip()
        AWS_SECRET_ACCESS_KEY = str(st.secrets["AWS_SECRET_ACCESS_KEY"]).strip()
        # 空文字ならenv変数にフォールバック
        if not AWS_ACCESS_KEY_ID:
            AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
            AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    else:
        AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
        AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
except Exception as e:
    # st.error(f"AWS認証情報読み込みエラー: {e}")
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")

# Claude 4.5 Sonnet の inference profile ID
CLAUDE_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
CLAUDE_REGION = "us-east-1"
# ▲▲▲ 追加ここまで ▲▲▲

# ▼▼▼ GitHub Models (o4-mini用) ▼▼▼
try:
    if "GITHUB_TOKEN" in st.secrets:
        GITHUB_TOKEN = str(st.secrets["GITHUB_TOKEN"]).strip()
        if not GITHUB_TOKEN:  # 空文字ならenv変数にフォールバック
            GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    else:
        GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
except Exception as e:
    # st.error(f"GITHUB_TOKEN読み込みエラー: {e}")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

GITHUB_MODEL_ID = "o4-mini"
# ▲▲▲ GitHub Models ここまで ▲▲▲

# ▼▼▼ OpenRouter セカンダリモデル（元 Grok スロット）▼▼▼
# デフォルトは Amazon Nova 2 Lite (free)
DEFAULT_SECONDARY_MODEL_ID = "amazon/nova-2-lite-v1:free"

# 環境変数優先で差し替え可能
SECONDARY_MODEL_ID = (
    os.getenv("OPENROUTER_SECONDARY_MODEL_ID")   # 新しい推奨環境変数
    or os.getenv("GROK_MODEL_ID")               # 互換性のために残す
    or DEFAULT_SECONDARY_MODEL_ID
)

# UI 用に人間に見せる名前も ENV から変えられるようにしておく
SECONDARY_MODEL_NAME = os.getenv(
    "OPENROUTER_SECONDARY_MODEL_NAME",
    "Amazon Nova 2 Lite (free)",
)
# ▲▲▲ OpenRouter セカンダリモデル ここまで ▲▲▲


# =========================
# Session Management
# =========================

def compact_newlines(text: str) -> str:
    """
    過剰な空白行を圧縮し、見やすいレイアウトにする
    """
    import re
    # 1. 3行以上の連続改行を2行に圧縮
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 2. スペースのみの行を空行に変換
    text = re.sub(r'\n[ \t]+\n', '\n\n', text)
    # 3. 改行+スペース+改行のパターンを改行2つに
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
    # 4. テーブル後の過剰な空白を削除（テーブル行の後に3行以上の空白がある場合）
    text = re.sub(r'(\|[^\n]+\|)\n{3,}', r'\1\n\n', text)
    return text

def trim_history(messages: list, max_tokens: int = 25000) -> list:
    """
    Vertex AI Quotaエラー対策: 履歴のトークン数を制限
    新しいメッセージを優先し、古いメッセージを自動的に切り捨てる
    
    Args:
        messages: メッセージ履歴
        max_tokens: 推定最大トークン数（デフォルト25000 = Gemini 3 Proで余裕）
    
    Returns:
        トリムされたメッセージ履歴
    """
    if not messages:
        return []
    
    trimmed = []
    current_est_tokens = 0
    
    # 新しい順にスキャン（最新を優先保持）
    for msg in reversed(messages):
        content = msg.get("content", "")
        # 簡易トークン推定: 日本語1文字≒1.5トークン、安全側で文字数×2
        est_tokens = len(content) * 2
        
        if current_est_tokens + est_tokens > max_tokens:
            break  # 上限を超えたらストップ（古いメッセージは切り捨て）
        
        trimmed.insert(0, msg)  # 先頭に挿入して順序を維持
        current_est_tokens += est_tokens
    
    return trimmed

def parse_thinking(text: str) -> tuple[str, str]:
    """
    思考プロセス（<thinking>タグ）を回答から分離
    GPT 5.1 Pro/Claude 4.5のThinking Process機能を実装
    
    Args:
        text: LLMの生の回答テキスト
    
    Returns:
        (thinking_content, main_content) - 思考部分と本文
    """
    import re
    pattern = r"<thinking>(.*?)</thinking>"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        thinking = match.group(1).strip()
        content = re.sub(pattern, "", text, flags=re.DOTALL).strip()
        return thinking, content
    return None, text

def extract_facts_and_risks(client, model_id: str, research_text: str) -> tuple[str, str, dict]:
    """
    Phase B以前の後方互換用（v1）：事実とリスクをMarkdown形式で抽出
    
    ⚠️ このv1関数は、以下の場合のみ使用されます：
    - Phase B IR抽出（extract_facts_and_risks_v2）が失敗した場合のフォールバック
    - 古いセッションとの互換性維持
    
    Phase B実装後は、extract_facts_and_risks_v2() がメインパスです。
    
    Args:
        client: Gemini client
        model_id: 使用するモデル
        research_text: 調査テキスト
    
    Returns:
        Tuple of (fact_summary, risk_summary, usage_dict)
    """
    extraction_prompt = f"""以下の調査結果から、事実とリスクを分離してください。

【調査結果】
{research_text[:8000]}

【出力形式（厳守）】
以下のJSON形式で出力してください：
{{
  "facts": [
    "確認された事実1（日付・数値・引用元を含む）",
    "確認された事実2",
    ...（5-10項目）
  ],
  "risks": [
    "リスク・不確実性1（簡潔に）",
    "リスク・不確実性2",
    ...（3-7項目）
  ],
  "unknowns": [
    "情報が不足している点（ある場合のみ）"
  ]
}}

JSONのみを出力し、マークダウンや説明文を含めないでください。"""
    
    config = types.GenerateContentConfig(
        temperature=0.2,
        system_instruction="事実とリスクを正確に分離し、JSON形式で出力する専門家として振る舞ってください。"
    )
    
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=extraction_prompt,
            config=config
        )
        text = extract_text_from_response(response).strip()
        
        # usage情報を取得
        usage_dict = {
            "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
            "output_tokens": response.usage_metadata.candidates_token_count or 0,
        } if response.usage_metadata else {"prompt_tokens": 0, "output_tokens": 0}
        
        # JSONパースを試みる
        import json
        import re
        
        # コードブロックを除去（```json ... ```）
        json_text = re.sub(r'```json\s*|\s*```', '', text)
        
        try:
            data = json.loads(json_text)
            facts = data.get("facts", [])
            risks = data.get("risks", [])
            unknowns = data.get("unknowns", [])
            
            # 事実の整形
            fact_summary = "## 📊 事実\n" + "\n".join([f"- {f}" for f in facts])
            if unknowns:
                fact_summary += "\n\n### 不明点\n" + "\n".join([f"- {u}" for u in unknowns])
            
            # リスクの整形
            risk_summary = "## ⚠️ リスク・不確実性\n" + "\n".join([f"- {r}" for r in risks])
            
            return fact_summary, risk_summary, usage_dict
            
        except json.JSONDecodeError:
            # JSONパース失敗時はMarkdownフォールバック
            if "##" in text:
                parts = text.split("##")
                fact_summary = parts[1] if len(parts) > 1 else text[:len(text)//2]
                risk_summary = parts[2] if len(parts) > 2 else text[len(text)//2:]
            else:
                mid = len(text) // 2
                fact_summary = text[:len(text)//2]
            risk_summary = text[len(text)//2:]
            return fact_summary, risk_summary, usage_dict
            
    except Exception as e:
        # エラー時は空の結果を返す
        return "事実抽出エラー", "リスク抽出エラー", {"prompt_tokens": 0, "output_tokens": 0}


# ========================================
# Phase B: JSON IR Extraction (v2)
# ========================================

def extract_facts_and_risks_v2(
    client,
    model_id: str,
    user_question: str,
    research_text: str
) -> tuple:
    """
    Extract structured JSON IR from research text (Phase B).
    
    Returns: (ir_dict or None, usage_dict, raw_json_text)
    """
    try:
        from research_ir import validate_research_ir
        from datetime import datetime
        import json
        import re
        
        # Truncate research_text if too long
        truncated_research = research_text[:4000] if len(research_text) > 4000 else research_text
        
        extraction_prompt = f"""以下の調査メモから、構造化された情報を抽出してJSON形式で出力してください。

【調査メモ】
{truncated_research}

【タスク】
以下のJSON形式**のみ**を出力してください。説明文や前置きは不要です。

{{
  "facts": [
    {{
      "statement": "具体的な事実の記述",
      "source": "web",
      "source_detail": "URLまたは出典先",
      "date": "2024-12-04",
      "confidence": "high"
    }}
  ],
  "options": [
    {{
      "name": "選択肢・案の名前",
      "pros": ["メリット1", "メリット2"],
      "cons": ["デメリット1"],
      "conditions": ["成立条件1"],
      "estimated_cost": null
    }}
  ],
  "risks": [
    {{
      "statement": "リスクの内容",
      "severity": "high",
      "timeframe": "short",
      "mitigation": "対策案（あれば）"
    }}
  ],
  "unknowns": [
    {{
      "question": "不明な点・要確認事項",
      "why_unknown": "insufficient_data",
      "impact": "high"
    }}
  ],
  "metadata": {{
    "question": "{user_question[:150]}",
    "language": "ja",
    "created_at": "{datetime.now().isoformat()}",
    "models": ["{model_id}"],
    "sources_count": 1,
    "search_queries": []
  }}
}}

【重要な制約】
1. source は "web", "youtube", "model" のいずれか
2. confidence は "high", "medium", "low" のいずれか
   - high: 公式情報または複数ソースで確認
   - medium: 単一ソースまたは間接情報
   - low: 推測または古い情報
3. severity/impact は "high", "medium", "low" のいずれか
4. timeframe は "short", "medium", "long" のいずれか
5. why_unknown は "insufficient_data", "conflicting_data", "grey_area", "future_dependent" のいずれか
6. 該当項目がない場合は空配列 [] を使用
7. JSONのみを出力（コードブロックや説明文は不要）
"""

        config = types.GenerateContentConfig(
            temperature=0.1,  # 事実抽出は低温度
            response_mime_type="application/json"
        )
        
        response = client.models.generate_content(
            model=model_id,
            contents=[{"role": "user", "parts": [{"text": extraction_prompt}]}],
            config=config
        )
        
        raw_text = extract_text_from_response(response).strip()
        usage_dict = {
            "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
            "output_tokens": response.usage_metadata.candidates_token_count or 0,
        } if response.usage_metadata else {"prompt_tokens": 0, "output_tokens": 0}
        
        # Remove code blocks if present
        json_text = re.sub(r'```json\s*|\s*```', '', raw_text)
        
        # Parse JSON with retry
        ir_dict = None
        for attempt in range(2):
            try:
                ir_dict = json.loads(json_text)
                break
            except json.JSONDecodeError as e:
                if attempt == 0:
                    # Try to fix common issues
                    json_text = json_text.replace("'", '"')  # Single to double quotes
                    json_text = re.sub(r',\s*}', '}', json_text)  # Remove trailing commas
                    json_text = re.sub(r',\s*]', ']', json_text)
                else:
                    print(f"[DEBUG] JSON parse failed after retry: {e}")
                    return (None, usage_dict, raw_text)
        
        if ir_dict is None:
            return (None, usage_dict, raw_text)
        
        # Validate and normalize
        normalized_ir, warnings = validate_research_ir(ir_dict)
        
        if warnings:
            print(f"[DEBUG] IR validation warnings: {warnings}")
        
        return (normalized_ir, usage_dict, raw_text)
        
    except Exception as e:
        print(f"[DEBUG] extract_facts_and_risks_v2 exception: {e}")
        import traceback
        traceback.print_exc()
        return (None, {"prompt_tokens": 0, "output_tokens": 0}, str(e))


def convert_ir_to_markdown(ir: dict) -> tuple[str, str]:
    """
    Convert JSON IR to Markdown format for backward compatibility.
    
    Args:
        ir: ResearchIR dictionary
    
    Returns:
        Tuple of (fact_summary, risk_summary)
    """
    from research_ir import build_synthesis_prompt_from_ir
    
    # Facts section
    fact_lines = ["## 📊 事実"]
    confidence_marks = {
        "high": "✓",
        "medium": "△",
        "low": "?",
        "unknown": "·"
    }
    
    for fact in ir.get("facts", []):
        mark = confidence_marks.get(fact.get("confidence", "unknown"), "·")
        fact_lines.append(f"{mark} {fact.get('statement', '')}")
        if fact.get("source_detail"):
            fact_lines.append(f"  出典: {fact['source_detail']}")
    
    # Unknowns section
    if ir.get("unknowns"):
        fact_lines.append("\n### 不明点・要確認事項")
        for unknown in ir["unknowns"]:
            fact_lines.append(f"? {unknown.get('question', '')}")
    
    fact_summary = "\n".join(fact_lines) if fact_lines else "（抽出された事実なし）"
    
    # Risks section
    risk_lines = ["## ⚠️ リスク・不確実性"]
    severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢", "unknown": "⚪"}
    
    # Sort by severity
    severity_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    sorted_risks = sorted(
        ir.get("risks", []),
        key=lambda x: severity_order.get(x.get("severity", "unknown"), 3)
    )
    
    for risk in sorted_risks:
        emoji = severity_emoji.get(risk.get("severity", "unknown"), "⚪")
        risk_lines.append(f"{emoji} {risk.get('statement', '')}")
        if risk.get("mitigation"):
            risk_lines.append(f"  対策: {risk['mitigation']}")
    
    risk_summary = "\n".join(risk_lines) if risk_lines else "（特定されたリスクなし）"
    
    return (fact_summary, risk_summary)


# =========================
# Gemini Client Setup
# =========================
try:
    from google import genai
    from google.genai import types
except ImportError:
    st.error("Google Generative AI package not found. Please install: pip install google-generativeai")
    st.stop()


def build_session_memory(sessions: list, current_session_id: str, max_entries: int = 10) -> str:
    """
    
    Args:
        sessions: すべてのセッション
        current_session_id: 現在のセッションID
        max_entries: 最大エントリ数
    
    Returns:
        セッション記憶のテキスト
    """
    # 現在のセッションを除外
    past_sessions = [s for s in sessions if s["id"] != current_session_id]
    
    if not past_sessions:
        return ""
    
    # 最新のmax_entriesセッションを取得
    recent_sessions = past_sessions[-max_entries:]
    
    # ユーザーの質問と重要な判断を抽出
    key_contexts = []
    for session in recent_sessions:
        for msg in session.get("messages", []):
            if msg["role"] == "user" and len(msg["content"]) > 50:
                # 十分な長さの質問のみ
                key_contexts.append(msg["content"][:200])
    
    if not key_contexts:
        return ""
    
    # 簡易要約
    memory_text = "【過去の文脈・判断基準】\n"
    memory_text += "\n".join([f"- {ctx}..." for ctx in key_contexts[-5:]])
    memory_text += "\n\n"
    
    return memory_text


def generate_recommendations(client, sessions, current_session_id, user_profile, mode="normal"):
    """
    ユーザープロファイルと過去セッションから次の質問候補を生成
    
    Args:
        client: Vertex AI client
        sessions: 全セッション
        current_session_id: 現在のセッションID
        user_profile: ユーザープロファイル
        mode: "normal" (直近5件) or "deep" (全履歴)
    
    Returns:
        tuple: (recommendations_text, usage_dict)
    """
    if mode == "deep":
        # Level 3: 全履歴 × gemini-2.0-flash
        session_memory = build_full_session_memory(sessions, current_session_id)
        model_name = "gemini-2.0-flash"
        max_tokens = 3000
        role_desc = "あなたはユーザーの全チャット履歴を熟知した専属の戦略アドバイザーです。"
        task_desc = "これまでの全議論を俯瞰し、ユーザーがまだ気づいていない本質的な課題や、次に深掘りすべき戦略的なテーマを提案してください。"
    else:
        # Level 2: 直近5件 × gemini-2.5-flash
        session_memory = build_session_memory(sessions, current_session_id, max_entries=5)
        model_name = "gemini-2.5-flash"
        max_tokens = 1500
        role_desc = "あなたはユーザーの過去の会話履歴とプロファイルを分析して、次に聞くと良い質問を提案するアシスタントです。"
        task_desc = "ユーザーの興味・関心に基づき、次に聞くと良い質問を3〜5個提案してください。"

    # プロファイル情報の整形
    interests_str = ", ".join(user_profile.get("interests", [])) if user_profile.get("interests") else "まだ特定されていません"
    facts_str = "\n".join([f"- {fact}" for fact in user_profile.get("facts_about_user", [])]) if user_profile.get("facts_about_user", []) else "まだ蓄積されていません"
    
    prefs_str = ""
    if user_profile.get("preferences"):
        prefs_str = "\n".join([f"- {k}: {v}" for k, v in user_profile["preferences"].items()])
    else:
        prefs_str = "まだ設定されていません"
    
    system_prompt = f"""{role_desc}

【重要な制約】
- ユーザーの興味・好み・過去の文脈を最大限活用
- 3〜5個の具体的な質問を提案
- **質問文は簡潔に、30文字以内を目安にする**（サイドバーの幅が狭いため）
- 各質問には「なぜこれが良いか」の理由を簡潔に付ける
- 過去の会話との繋がりを明示
- **自然な日本語で文法的に正しい文章を生成すること**
- サイドバー表示のため、テキストが折り返されるように改行を入れる
- 出力は以下のMarkdown形式で:

1. [簡潔な質問文（30文字以内）]
   - 理由: [なぜこの質問が有益か]

2. [簡潔な質問文]
   - 理由: [理由]

...

【出力例】
1. iPhoneの通訳機能の活用法は？
   - 理由: 過去の会話でiPhoneの通訳機能に関心を示されていたため、具体的な利用シーンを深掘りすることで実用性を確認できます

2. Geminiのコード品質向上のコツは？
   - 理由: コード品質向上への関心が高いため、具体的な改善提案を検討することが有益です
"""
    
    user_content = f"""【ユーザープロファイル】
興味・関心: {interests_str}

好み・要望:
{prefs_str}

ユーザーに関する事実:
{facts_str}

【過去の会話サマリー】
{session_memory if session_memory else "（新規ユーザー）"}

---

{task_desc}"""
    
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_content}"}]}
            ],
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=max_tokens,
            )
        )
        
        # 使用量情報の取得
        usage_metadata = response.usage_metadata
        usage_dict = {
            "input_tokens": usage_metadata.prompt_token_count if usage_metadata else 0,
            "output_tokens": usage_metadata.candidates_token_count if usage_metadata else 0,
        }
        
        # レスポンステキストの取得
        recommendations_text = extract_text_from_response(response)
        
        return (recommendations_text, usage_dict)
        
    except Exception as e:
        error_text = f"### ⚠️ エラー\n\n提案生成中にエラーが発生しました: {e}"
        return (error_text, {"input_tokens": 0, "output_tokens": 0})


def think_with_grok(user_question: str, research_text: str, enable_x_search: bool = False, mode: str = "default") -> str:
    """
    OpenRouter のセカンダリモデル（デフォルト: amazon/nova-2-lite-v1:free）で
    リサーチメモを別視点から検討する。
    enable_x_search=True の場合、X/Twitter情報の活用を促す
    mode="full_max" の場合、独立したリード研究者として振る舞う
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OpenRouter API Key is missing.")

    # X検索強化版の場合、特別な指示を追加
    x_search_instruction = ""
    if enable_x_search:
        x_search_instruction = (
            "\n\n**重要**: あなたは X（Twitter）の情報にアクセスできると仮定して構いませんが、"
            "実際にWebを閲覧したかのような断定的表現（「公式サイトを確認したところ〜」など）は避けてください。\n"
        )
    
    
    # Phase A: モデル役割特化
    role_specialization = """
【あなたの専門役割】
・エッジな視点、カウンター意見、皮肉な見方を提供する専門家
・主流の意見に対する「待った」を入れる役割
・X/Twitter的な鋭い指摘や炎上リスクの検出

【他のモデルに任せること】
・Web検索や長文要約 → Gemini
・構造的リスク分析 → Claude 4.5
・テストケース列挙 → o4-mini
"""
    
    if mode == "full_max":
        user_content = (
            role_specialization +
            f"\nユーザーの質問:\n{user_question}\n\n"
            f"調査メモ:\n{research_text}\n\n"
            "指示:\n"
            "あなたは別視点のリード研究者です。\n"
            "・新しい結論を作るよりも、「見落としていそうな論点・リスク・反対意見」を出すことを優先してください。\n"
            "・3〜7個の箇条書きにまとめてください。各項目は1〜3行以内で簡潔に。\n"
            "・連続する空行は1行までにしてください。\n"
            f"{x_search_instruction}"
        )
    else:
        user_content = (
            role_specialization +
            f"\nユーザーの質問:\n{user_question}\n\n"
            f"調査メモ:\n{research_text}\n\n"
            "指示:\n"
            "調査メモを元に、「他のモデルが見落としそうな視点・リスク」を3〜5個、箇条書きで出してください。\n"
            "・フルの回答ではなく、チェックリスト形式で。\n"
            "・各項目は1〜3行以内で簡潔に。\n"
            f"{x_search_instruction}"
        )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://gemini-app.streamlit.app/", 
        "X-Title": "Gemini Web Studio",
    }
    
    data = {
        "model": SECONDARY_MODEL_ID,
        "messages": [
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.8,  # Phase A: エッジな視点・カウンター意見を出しやすく
        "max_tokens": 2000,
        # Nova 2 Lite など reasoning 対応モデルならここで有効化も可能：
        # "reasoning": {"effort": "medium"},
    }

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        # ここは raise にして、呼び出し側で error として扱う方が安全
        raise RuntimeError(f"Error calling OpenRouter model ({SECONDARY_MODEL_ID}): {e}")

def review_with_grok(user_question: str, gemini_answer: str, research_text: str, mode: str = "normal") -> str:
    """
    OpenRouterセカンダリモデルを使って、Geminiの最終回答をレビューする
    mode="onigunsou": 厳格な検察官としてレビュー
    mode="full_max": ダブル鬼軍曹としてレビュー
    """
    if not OPENROUTER_API_KEY:
        return "OpenRouter API Key is missing."

    # 共通: セカンダリモデルの役割を「レビューコメント専用」に厳しく制限
    system_content = (
        "あなたはGeminiの回答をチェックするレビューアです。\n"
        "\n"
        "【前提】\n"
        "・あなたの汎用知識はあくまで参考情報です。\n"
        "・ユーザーが渡した「調査メモ」と「Geminiの回答」に書かれている事実を、あなた自身の知識よりも常に優先してください。\n"
        "\n"
        "【禁止事項】\n"
        "・自分の知識のカットオフや最終更新日について言及してはいけません。\n"
        "  （例:「2024年12月時点では〜」「私の知識は2024年までです」など）\n"
        "・「〜というモデルは存在しない」「まだ発表されていない」と断定してはいけません。\n"
        "  必要な場合は「公開情報と食い違う可能性があるので要確認」のように、弱い表現にしてください。\n"
        "・Webサイトを『今見た』かのような表現（例:『公式サイトを確認したところ〜』）を使ってはいけません。\n"
        "\n"
        "【レビューの方針】\n"
        "・調査メモとGeminiの回答のあいだにある、具体的な矛盾・危険な誤り・過度な断定だけを指摘してください。\n"
        "・単に「自分の知識と違う」「自分の知識では確認できない」だけの場合、それをもって誤り認定してはいけません。\n"
        "  その場合は「公開情報と異なる可能性があるので要確認」程度の一行コメントに留めてください。\n"
        "・Markdownは使用してかまいませんが、連続する空行は1行までにしてください。\n"
    )
    
    if mode == "onigunsou":
        system_content += (
            "\n⚠️ 重要な注意:\n"
            "・あなたは **自分の学習知識ではなく、調査メモとGeminiの回答** を前提にレビューしてください。\n"
            "・調査メモに自分の記憶と異なる新しい情報があっても、「誤り」と決めつけず、\n"
            "  「公開情報と食い違う可能性があるので要確認」といった弱い表現にしてください。\n"
            "・「◯年◯月時点では〜」のような日付ベースの反論は行わないでください。\n"
        )
        instruction = (
            "以下の形式で、レビューコメントだけ返してください。\n\n"
            "## 評価概要\n"
            "- 回答は OK / 要修正 / 危険 のいずれかで評価してください。\n\n"
            "## 問題点\n"
            "- 箇条書きで、危険な誤り・過度な断定・論理の飛躍などを書いてください。\n\n"
            "## 修正のポイント\n"
            "- どの部分をどう弱める／書き換えるべきか だけを簡潔に示してください。\n\n"
            "※ Geminiの回答全文を書き直したり、独自の最終回答を作らないでください。"
        )
    elif mode == "full_max":
        system_content += (
            "\n⚠️ 重要な注意:\n"
            "・あなたは検察官レベルに厳しくレビューしますが、\n"
            "  それでもなお **調査メモの記載をファクトとして扱う** 必要があります。\n"
            "・自分の知識との差分だけを根拠に「誤り」「危険」と判断してはいけません。\n"
            "・最新情報かどうか分からない場合は「要確認」とだけ述べ、\n"
            "  カットオフや学習時期には一切触れないでください。\n"
        )
        instruction = (
            "以下の形式で、厳しめのレビューコメントだけ返してください。\n\n"
            f"## {SECONDARY_MODEL_NAME}評価概要\n"
            "- OK / 要修正 / 危険 のいずれかで評価してください。\n\n"
            "## 重大な問題点\n"
            "- 箇条書きで、特にユーザーを誤誘導しそうな点だけ挙げてください。\n\n"
            "## 改善のヒント\n"
            "- どの論点を弱めたり、追加で注意書きすべきかを書いてください。\n\n"
            "※ Geminiの回答全文を書き直したり、独自の最終回答を作らないでください。"
        )
    else:
        instruction = (
            "以下のGeminiの回答をレビューし、論理的な誤りや不足している視点があれば指摘してください。\n"
            "また、より良い回答にするための改善案を提示してください。"
        )

    user_content = (
        f"ユーザーの質問:\n{user_question}\n\n"
        f"調査メモ:\n{research_text}\n\n"
        f"Geminiの回答:\n{gemini_answer}\n\n"
        f"指示:\n{instruction}"
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://gemini-app.streamlit.app/", 
        "X-Title": "Gemini Web Studio",
    }
    
    data = {
        "model": SECONDARY_MODEL_ID,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.5, # レビューなので少し抑えめ
        "max_tokens": 2000,
    }
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        
        # カットオフ系のノイズを削除
        raw_content = result["choices"][0]["message"]["content"]
        return _clean_grok_review(raw_content)
    except requests.exceptions.HTTPError as e:
        # ステータスコードとレスポンス本文を返す
        status = e.response.status_code if e.response else "unknown"
        body = e.response.text[:500] if e.response is not None else ""
        return f"Error calling {SECONDARY_MODEL_NAME}: HTTP {status}: {body}"
    except Exception as e:
        return f"Error calling {SECONDARY_MODEL_NAME}: {type(e).__name__}: {e}"


def _clean_grok_review(text: str) -> str:
    """
    Grok のレビューから「知識カットオフ」「◯年◯月時点」系のノイズを軽く削る
    """
    NG_PHRASES = [
        "カットオフ",
        "cutoff",
        "知識は",
        "2024年12月時点",
        "2024 年 12 月時点",
        "2024年11月時点",
        "私の知識",
    ]
    lines = []
    for line in text.splitlines():
        if any(ng in line for ng in NG_PHRASES):
            # その行は捨てる
            continue
        lines.append(line)
    return "\n".join(lines).strip()



def think_with_claude45_bedrock(user_question: str, research_text: str) -> tuple[str, dict]:
    """
    AWS Bedrock 経由で Claude Sonnet 4.5 を使って独立した回答案を作成する
    Returns: (回答テキスト, usage辞書)
    """
    if not HAS_BOTO3:
        return ("Error: boto3 library not installed. (pip install boto3)", {})
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        return ("Error: AWS credentials are missing.", {})

    # Claude 4.5 への役割付与: 論理的推論とリスク指摘に特化
    system_prompt = (
        "あなたはGeminiとは異なる独立したAIアドバイザーです。\n"
        "提供された調査メモを事実のベースとしつつも、あなたの強みである「論理的推論(Reasoning)」を活かして、\n"
        "Geminiが見落としがちな『前提の誤り』『隠れたリスク』『別の可能性』を指摘してください。\n"
        "回答は簡潔に、箇条書きで出力してください。"
    )

    
    # Phase A: モデル役割特化
    role_specialization = """
【あなたの専門役割】
・構造的リスク、システム的な問題点の発見
・長期的なシナリオ分析（1年後、5年後の影響）
・見落とされがちな前提条件や依存関係の指摘

【あなたが重視すべきこと】
・短期的な視点よりも、長期的・構造的な視点
・「このアプローチが失敗する条件は？」
・「スケールした時に何が壊れるか？」
"""
    
    user_content = (
        role_specialization +
        f"\nユーザーの質問:\n{user_question}\n\n"
        f"調査メモ:\n{research_text}\n\n"
        "指示:\n"
        "調査メモの内容を元に、長期的な視点で「リスク」「前提条件」「依存関係」を中心に\n"
        "3〜5個の重要なポイントを箇条書きで書いてください。"
    )

    try:
        # AWS Bedrock クライアント作成
        bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=CLAUDE_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )

        # Bedrock converse API を使用（inference profile対応 + Extended Thinking）
        resp = bedrock.converse(
            modelId=CLAUDE_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": f"{system_prompt}\n\n{user_content}"}
                    ],
                }
            ],
            inferenceConfig={
                "maxTokens": 5000,  # Thinking modeでは多めに確保
                "temperature": 1.0,  # Extended Thinking mode では必須
            },
            # Extended Thinking Mode を有効化
            additionalModelRequestFields={
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 3000  # 思考用トークン数
                }
            }
        )

        # 思考ブロックと回答テキストの取り出し (reasoningContent対応)
        thinking_blocks = []
        text_chunks = []
        output = resp.get("output", {})
        message = output.get("message", {})
        
        for part in message.get("content", []):
            # Extended Thinking の推論プロセス (reasoningContent)
            if "reasoningContent" in part:
                rc = part["reasoningContent"]
                if isinstance(rc, dict):
                    # reasoningText.text を取得
                    rt = rc.get("reasoningText", {})
                    if isinstance(rt, dict):
                        t = rt.get("text")
                        if t:
                            thinking_blocks.append(t)
                    # フォールバック: rc["text"] も試す
                    elif "text" in rc:
                        thinking_blocks.append(rc["text"])
            # 最終回答テキスト
            elif "text" in part:
                text_chunks.append(part["text"])

        # 使用量情報の取得
        usage = resp.get("usage", {})
        usage_dict = {
            "inputTokens": usage.get("inputTokens", 0),
            "outputTokens": usage.get("outputTokens", 0)
        }

        result_text = "".join(text_chunks) if text_chunks else "[Claude 4.5 Sonnetからのテキストが空でした]"
        
        # 思考ブロックがある場合は冒頭に追加
        if thinking_blocks:
            thinking_text = "\n\n".join([f"**🧠 思考プロセス {i+1}:**\n{block}" for i, block in enumerate(thinking_blocks)])
            result_text = f"{thinking_text}\n\n---\n\n**💡 最終回答:**\n{result_text}"
        
        return (result_text, usage_dict)

    except Exception as e:
        # エラー詳細を返す
        return (f"Error calling Claude 4.5 Sonnet (Bedrock): {e}", {})




def think_with_o4_mini(user_question: str, research_text: str) -> tuple[str, dict]:
    """
    GitHub Models経由でo4-miniを使って独立した回答案を作成する
    制限: input 4000トークン以下の場合のみ使用
    Returns: (回答テキスト, 空dict - GitHub Modelsはusage情報を返さない)
    """
    if not GITHUB_TOKEN:
        return ("Error: GitHub Token is missing.", {})
    
    # 長さチェックは呼び出し側で実施済み（3800文字以下を保証）
    
    
    system_prompt = (
        "あなたは、与えられた要約をもとに「抜けていそうな観点」を列挙するテスター/チェッカーです。\n"
        "【重要な制約】\n"
        "・フルの回答は書かないでください。\n"
        "・「他のモデルが見落としそうなリスク・エッジケース・反論」だけを箇条書きで出してください。\n"
        "・最大5個まで。各項目は1〜3行以内で簡潔に。\n"
        "・連続する空行は1行までにしてください。"
    )
    
    
    # Phase A: モデル役割特化
    role_specialization = """
【あなたの専門役割】
・テストケース、エッジケースの列挙
・「◯◯の場合はどうなる？」というチェックリスト作成
・実装上の落とし穴や細かい注意点の指摘

【出力形式の推奨】
・箇条書きのチェックリスト形式
・「確認すべきこと」リスト
・「想定すべきケース」リスト
"""
    
    user_content = (
        role_specialization +
        f"\nユーザーの質問:\n{user_question}\n\n"
        f"調査メモ:\n{research_text}\n\n"
        "指示:\n"
        "調査メモを元に、考慮すべき「テストケース」「エッジケース」「チェック項目」を\n"
        "箇条書きで3〜7個出してください。"
    )
    
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }
    
    data = {
        "model": "gpt-4o-mini",  # GitHub Models用のモデル名
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
    }
    
    try:
        import requests
        response = requests.post(
            f"https://models.inference.ai.azure.com/chat/completions",
            headers=headers,
            json=data,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        answer_text = result["choices"][0]["message"]["content"]
        return (answer_text, {})  # GitHub Modelsはusage情報を返さない
    except Exception as e:
        return (f"Error calling o4-mini (GitHub Models): {e}", {})


# Puter関連の関数は削除（AWS Bedrockに移行）

def create_new_session():
    """
    安定版: session_stateをマスターとして使用
    ❌ 削除: load_sessions() ← 競合の原因
    """
    # session_stateをマスターとして使用
    if "sessions" not in st.session_state:
        st.session_state.sessions = load_sessions()  # 起動時のみ
    
    current_sessions = st.session_state.sessions
    
    # 現在のセッションが空なら、新しく作らずにそれを再利用する
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
    
    # 1. メモリを更新
    st.session_state.sessions = current_sessions
    st.session_state.current_session_id = new_id
    
    # 2. ファイルへ保存（バックアップ）
    save_sessions(st.session_state.sessions)
    st.rerun()

def switch_session(session_id):
    st.session_state.current_session_id = session_id
    st.rerun()

def update_current_session_messages(messages):
    """
    履歴安定化版: session_stateをマスターとして扱い、ファイルは保存のみ
    ❌ 修正前: load_sessions()で毎回ファイルから読み込み → 先祖返り発生
    ⭕ 修正後: session_stateを直接更新 → ファイルはバックアップとして保存
    """
    if st.session_state.current_session_id:
        # ❌ 削除: current_sessions = load_sessions()  ← これが先祖返りの原因
        
        # ⭕ session_stateをマスターとして使用
        if "sessions" not in st.session_state or not st.session_state.sessions:
            st.session_state.sessions = load_sessions()  # 起動時のみ
        
        current_sessions = st.session_state.sessions
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
        
        # 1. メモリを即時更新（これで画面上の表示は安定する）
        st.session_state.sessions = current_sessions
        
        # 2. ファイルへ保存（バックアップ）
        save_sessions(current_sessions)

def get_current_messages():
    """
    コピーを返す版: 参照を返すと意図しない変更が起きる
    ❌ 修正前: return session["messages"]  ← 参照を返す
    ⭕ 修正後: return list(...)  ← コピーを返す
    """
    if st.session_state.current_session_id:
        for session in st.session_state.sessions:
            if session["id"] == st.session_state.current_session_id:
                return list(session["messages"])  # コピーを返す（重要）
    return []

def delete_session(session_id):
    """
    安定版: session_stateをマスターとして使用
    """
    if "sessions" not in st.session_state:
        st.session_state.sessions = load_sessions()
    
    current_sessions = [s for s in st.session_state.sessions if s["id"] != session_id]
    
    # 1. メモリを更新
    st.session_state.sessions = current_sessions
    
    if st.session_state.current_session_id == session_id:
        st.session_state.current_session_id = None
        if current_sessions:
            st.session_state.current_session_id = current_sessions[0]["id"]
    
    # 2. ファイルへ保存（バックアップ）
    save_sessions(st.session_state.sessions)
    st.rerun()

def branch_session():
    """
    安定版: session_stateをマスターとして使用
    現在のセッションから新しいチャットを分岐
    """
    if "sessions" not in st.session_state:
        st.session_state.sessions = load_sessions()
    
    current_messages = get_current_messages()  # これはコピーを返す
    current_sessions = st.session_state.sessions
    
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
        "messages": list(current_messages),  # ディープコピー
    }
    current_sessions.insert(0, new_session)
    
    # 1. メモリを更新
    st.session_state.sessions = current_sessions
    st.session_state.current_session_id = new_id
    st.session_state.session_cost = 0.0  # コストリセット
    
    # 2. ファイルへ保存（バックアップ）
    save_sessions(st.session_state.sessions)
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
    if st.button("🔒 ログアウト", width="stretch"):
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
        if st.button("➕ 新規", width="stretch"):
            create_new_session()
    with col2:
        if st.button("🌱 分岐", width="stretch"):
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

            if st.button("リンク生成", width="stretch"):
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
            st.image(pasted_image_bytes, caption="画像", width="stretch")
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
        ["🎯 回答モード(多層)", "🎯 回答モード(通常)"],
        index=0,  #デフォルトを多層モードに変更
        horizontal=True,
    )
    
    # ---- 多層モード ----
    if mode_category == "🎯 回答モード(多層)":
        with st.expander("モード設定(多層)", expanded=True):
            mode_type = st.radio(
                "タイプ",
                ["🚀 本気MAX", "🧪 ベータ", "⚡ 軽量", "その他"],
                index=0,
                horizontal=True,
                label_visibility="collapsed"
            )
            st.caption("本気MAX=旧gr強化+msAz | ベータ=旧gr通常 | 軽量=旧gr強化")
            
            if mode_type == "🚀 本気MAX":
                # ▼▼▼ メニュー簡素化: 本気MAXをメインに ▼▼▼
                st.markdown("### 🚀 推奨モード")
                response_mode = st.radio(
                    "応答モード:",
                    options=[
                        "熟考 (本気MAX)ms/Az",  # メイン推奨
                    ],
                    index=0,
                    key="response_mode"
                )
                
                with st.expander("🧪 その他のモード (ベータ版)", expanded=False):
                    beta_mode = st.radio(
                        "ベータモードを選択:",
                        options=[
                            "使用しない",
                            "熟考 + 鬼軍曹",
                            "熟考(本気MAX)/grok",
                            "熟考/grok",
                            "熟考 (中規模MAX)Az",
                            "熟考 (本気)ms",
                            "熟考 (中規模)", 
                            "β1高速 (通常)",
                        ],
                        index=0,
                        key="beta_mode"
                    )
                    if beta_mode != "使用しない":
                        response_mode = beta_mode
                # ▲▲▲ メニュー簡素化 ここまで ▲▲▲
            elif mode_type == "🧪 ベータ":
                response_mode = st.radio(
                    "ベータモード",
                    [
                        "熟考 + 鬼軍曹",
                        "熟考 (メタ思考)",
                        "熟考 (本気MAX)",
                    ],
                    index=0
                )
            elif mode_type == "⚡ 軽量":
                response_mode = st.radio(
                    "軽量モード",
                    [
                        "熟考 (中規模)",
                        "β1高速 (通常)",
                    ],
                    index=0
                )
            else:  # その他
                response_mode = st.radio(
                    "その他",
                    [
                        "1. 熟考 (リサーチ)",
                        "β1. 通常 (高速)",
                    ],
                    index=0
                )
    
    # Puterモードは削除（AWS Bedrockに移行）
    
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
    
    # ---- おすすめ ----
    with st.expander("💡 おすすめ", expanded=False):
        # ボタンを縦に配置
        if st.button("✨ 提案 (直近)", width="stretch"):
            with st.spinner("生成中..."):
                rec_client = get_gemini_client()  # 早期定義済み関数を使用
                user_profile = load_user_profile()
                rec_text, usage = generate_recommendations(rec_client, st.session_state.sessions, st.session_state.current_session_id, user_profile, mode="normal")
                
                # コスト加算
                cost = calculate_cost("gemini-2.5-flash", usage["input_tokens"], usage["output_tokens"])
                st.session_state.session_cost += cost
                
                # グローバル使用量の更新
                usage_stats["total_cost_usd"] += cost
                usage_stats["total_input_tokens"] += usage["input_tokens"]
                usage_stats["total_output_tokens"] += usage["output_tokens"]
                save_usage(usage_stats)
                
                # テキストをそのまま保存（CSSで自動折り返し）
                st.session_state.recommendation_text = rec_text
        
        st.markdown("") # 隙間

        if st.button("🔥 提案 (全履歴)", width="stretch"):
            with st.spinner("全履歴分析中..."):
                rec_client = get_gemini_client()  # 早期定義済み関数を使用
                user_profile = load_user_profile()
                rec_text, usage = generate_recommendations(rec_client, st.session_state.sessions, st.session_state.current_session_id, user_profile, mode="deep")
                
                # コスト加算 (gemini-2.0-flash)
                cost = calculate_cost("gemini-2.0-flash", usage["input_tokens"], usage["output_tokens"])
                st.session_state.session_cost += cost
                
                # グローバル使用量の更新
                usage_stats["total_cost_usd"] += cost
                usage_stats["total_input_tokens"] += usage["input_tokens"]
                usage_stats["total_output_tokens"] += usage["output_tokens"]
                save_usage(usage_stats)
                
                # テキストをそのまま保存（CSSで自動折り返し）
                st.session_state.recommendation_text = rec_text

        # 結果表示 (ボタンの下に表示)
        if "recommendation_text" in st.session_state:
            st.markdown("---")
            st.markdown(
                f"<div class='recommendation-text'>{st.session_state.recommendation_text}</div>",
                unsafe_allow_html=True
            )

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
    /* サイドバーのセッション名などを1行に収める */
    section[data-testid="stSidebar"] label, 
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    
    /* 💡おすすめエリアだけは折り返し＆改行を許可 */
    section[data-testid="stSidebar"] .recommendation-text,
    section[data-testid="stSidebar"] .recommendation-text p {
        white-space: pre-wrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        line-height: 1.4;
        font-size: 11px;
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
    
    /* チャットメッセージ内のインラインコードを折り返す */
    [data-testid="stChatMessageContent"] code {
        white-space: pre-wrap !important;
        word-break: break-word !important;
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
                if st.button(session["title"], key=f"btn_{session['id']}", width="stretch"):
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
                    if st.button(session["title"], key=f"btn_{session['id']}", width="stretch"):
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
    from logic import MAX_BUDGET_JPY, TRIAL_LIMIT_JPY, TRIAL_EXPIRY
    
    st.subheader("💰 Cost")
    st.caption(f"Gemini予算: ¥45,000 ($300) | AWS: ¥15,000 ($100)")
    st.caption(f"有効期限 - GCP: {TRIAL_EXPIRY} | AWS: Jun 02, 2026")
    
    # ▼▼▼ コスト表示（セッションベース） ▼▼▼
    GEMINI_BUDGET_USD = 300.0
    AWS_BUDGET_USD = 100.0
    GEMINI_COST_PER_RUN = 1.8
    AWS_COST_PER_RUN = 0.2
    
    session_cost = usage_stats['total_cost_usd']
    gemini_est = session_cost * 0.85
    aws_est = session_cost * 0.15
    
    gemini_runs = max(0, int((GEMINI_BUDGET_USD - gemini_est) / GEMINI_COST_PER_RUN))
    aws_runs = max(0, int((AWS_BUDGET_USD - aws_est) / AWS_COST_PER_RUN))
    
    # プログレスバー（セッション使用量のみ表示）
    st.progress(min(1.0, session_cost / 50.0))  # 1セッション50$を100%として表示
    
    st.markdown(f"<small>📊 今セッション: ${session_cost:.2f} | Gemini {gemini_runs}回相当 | AWS {aws_runs}回相当</small>", unsafe_allow_html=True)
    st.caption("⚠️ 実際の請求額はGCP/AWSコンソールで確認してください")
    # ▲▲▲ コスト表示 ここまで ▲▲▲
    
    st.link_button("💰 Google Cloud Console", "https://console.cloud.google.com/welcome/new?_gl=1*kmr691*_up*MQ..&gclid=CjwKCAiAraXJBhBJEiwAjz7MZT0vQsfDK5zunRBCQmuN5iczgI4bP1lHo1Tcrcbqu1KCBE1D22GpFhoCOdgQAvD_BwE&gclsrc=aw.ds&hl=ja&authuser=5&project=sigma-task-479704-r6")
    st.link_button("☁️ AWS Free Tier Dashboard", "https://us-east-1.console.aws.amazon.com/costmanagement/home?region=us-east-1#/freetier")
    st.caption("📘 GitHub Models: 使用状況は [Settings → Developer settings → Tokens](https://github.com/settings/tokens) で確認")
    
    # ▼▼▼ Debug: API Key Status ▼▼▼
    with st.expander("🔍 API Status (Debug)", expanded=False):
        # 詳細デバッグ情報
        aws_ok = bool(AWS_ACCESS_KEY_ID and AWS_ACCESS_KEY_ID.strip())
        openrouter_ok = bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY.strip())
        github_ok = bool(GITHUB_TOKEN and GITHUB_TOKEN.strip())
        
        st.caption(f"AWS: {'✅' if aws_ok else '❌'}")
        st.caption(f"OpenRouter: {'✅' if openrouter_ok else '❌'}")
        st.caption(f"GitHub: {'✅' if github_ok else '❌'}")
        
        # Secrets詳細デバッグ
        st.caption("---")
        try:
            secrets_keys = list(st.secrets.keys()) if hasattr(st.secrets, 'keys') else []
            st.caption(f"Secrets keys available: {len(secrets_keys)}")
            if secrets_keys:
                st.caption(f"Keys: {', '.join([k for k in secrets_keys if not k.startswith('GOOGLE_CREDENTIALS')])}")
            st.caption(f"AWS in secrets: {'AWS_ACCESS_KEY_ID' in st.secrets}")
            st.caption(f"OPENROUTER in secrets: {'OPENROUTER_API_KEY' in st.secrets}")
            st.caption(f"GITHUB in secrets: {'GITHUB_TOKEN' in st.secrets}")
        except Exception as e:
            st.caption(f"Secrets check error: {e}")
        
        # 環境変数確認
        st.caption("---")
        st.caption(f"OS env AWS: {bool(os.getenv('AWS_ACCESS_KEY_ID'))}")
        st.caption(f"OS env OPENROUTER: {bool(os.getenv('OPENROUTER_API_KEY'))}")
        st.caption(f"OS env GITHUB: {bool(os.getenv('GITHUB_TOKEN'))}")
    # ▲▲▲ Debug ▲▲▲

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



# =========================
# Initialize Gemini Client (function defined at line 81)
# =========================
# Initialize client
client = get_gemini_client()

# Store initialization error for display
init_error = None
if client is None:
    # Try to get the actual error message
    try:
        import sys
        # Re-run to capture exception
        test_client = get_gemini_client()
    except Exception as e:
        init_error = str(e)

# Check if client is ready
if client is None:
    st.error("❌ Gemini API初期化に失敗しました")
    if init_error:
        st.error(f"**エラー詳細:** {init_error}")
    st.info("💡 Streamlit Cloudの場合: 「Manage app」→「Settings」→「Secrets」で`GOOGLE_CREDENTIALS`を設定してください")
    st.info("💡 ローカル開発の場合: `gcloud auth application-default login`を実行してください")
    
    # Show debug info
    with st.expander("🔍 デバッグ情報", expanded=True):
        st.code(f"VERTEX_PROJECT = {VERTEX_PROJECT}")
        st.code(f"VERTEX_LOCATION = {VERTEX_LOCATION}")
        st.code(f"Has GOOGLE_CREDENTIALS in secrets = {'GOOGLE_CREDENTIALS' in st.secrets}")
        if "GOOGLE_CREDENTIALS" in st.secrets:
            creds = dict(st.secrets["GOOGLE_CREDENTIALS"])
            st.code(f"project_id in credentials = {creds.get('project_id')}")
    st.stop()

# ---- 履歴表示 ----

# チャット先頭にアンカーを設置
st.markdown('<a id="chat-top"></a>', unsafe_allow_html=True)

messages = get_current_messages()
for idx, msg in enumerate(messages):
    with st.chat_message(msg["role"]):
        # Display timestamp if available
        if "timestamp" in msg:
            st.caption(f"🕒 {msg['timestamp']}")
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
            
            # ▼▼▼ Deep Log: 保存された推論プロセスの表示 ▼▼▼
            if "reasoning_logs" in msg and msg["reasoning_logs"]:
                with st.expander("🧠 推論プロセス (Deep Log)", expanded=False):
                    logs = msg["reasoning_logs"]
                    
                    # メタデータ表示
                    if "metadata" in msg:
                        meta = msg["metadata"]
                        st.caption(f"🤖 Model: {meta.get('model', 'N/A')} | 💰 Cost: ${meta.get('cost', 0):.4f}")
                    
                    if logs.get("phase1_research"):
                        st.markdown("### 📚 Phase 1: 調査メモ")
                        st.markdown(logs["phase1_research"][:2000] + "..." if len(logs.get("phase1_research", "")) > 2000 else logs["phase1_research"])
                        st.markdown("---")
                    
                    if logs.get("phase1_5b_secondary"):
                        st.markdown(f"### ⚡ Phase 1.5b: セカンダリモデルの視点")
                        st.markdown(logs["phase1_5b_secondary"][:1500] + "..." if len(logs.get("phase1_5b_secondary", "")) > 1500 else logs["phase1_5b_secondary"])
                        st.markdown("---")
                    
                    if logs.get("phase1_5d_claude"):
                        st.markdown("### 🧠 Phase 1.5d: Claude 4.5 Sonnet の視点")
                        st.markdown(logs["phase1_5d_claude"][:1500] + "..." if len(logs.get("phase1_5d_claude", "")) > 1500 else logs["phase1_5d_claude"])
            # ▲▲▲ Deep Log ここまで ▲▲▲

# チャット末尾にアンカー設置 + ナビゲーションリンク
st.markdown('<a id="chat-bottom"></a>', unsafe_allow_html=True)

# ナビゲーションリンク（長いチャット用）
if len(messages) > 5:
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        st.markdown('[⬆️ チャット先頭へ](#chat-top)', unsafe_allow_html=True)
    with col3:
        st.markdown('[⬇️ 最新へ](#chat-bottom)', unsafe_allow_html=True)


# =========================
# 画像生成ハンドリング
# =========================

if hasattr(st.session_state, "generate_image_trigger") and st.session_state.generate_image_trigger:
    img_data = st.session_state.generate_image_trigger
    del st.session_state.generate_image_trigger

    with st.chat_message("user"):
        st.markdown(f"🎨 画像生成: {img_data['prompt']}")
        st.caption(f"アスペクト比: {img_data['aspect_ratio']}")

    messages.append({
        "role": "user",
        "content": f"🎨 画像生成: {img_data['prompt']}",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
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
                        {"role": "model",
                        "content": f"✅ 画像を生成しました: {img_data['prompt']}",
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
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
# Budget Check & Warnings
# =========================
stop_generation = usage_stats["total_cost_usd"] >= MAX_BUDGET_USD

# Show budget status in sidebar
with st.sidebar:
    st.caption("---")
    st.caption(f"💰 現在のコスト: ${usage_stats['total_cost_usd']:.4f} / ${MAX_BUDGET_USD:.2f}")
    if stop_generation:
        st.warning("⚠️ 予算上限に達しています")

# Show warning in main area if budget exceeded
if stop_generation:
    st.warning(
        "⚠️ **コスト上限に達しました**\n\n"
        f"現在のコスト: ${usage_stats['total_cost_usd']:.4f} / 上限: ${MAX_BUDGET_USD:.2f}\n\n"
        "新しいリクエストは一時的にブロックされます。開発中はlogic.pyの`MAX_BUDGET_USD`を増やしてください。"
    )

# =========================
# チャット入力
# =========================
prompt = st.chat_input("何か聞いてください...")

if prompt:
    # Budget check at submission time
    if stop_generation:
        st.error("❌ コスト上限に達しているため、この実行はキャンセルしました。予算設定を見直してください。")
        st.info(f"現在: ${usage_stats['total_cost_usd']:.4f} / 上限: ${MAX_BUDGET_USD:.2f}")
        st.stop()
    
    # ---- ユーザー発言表示 ----
    with st.chat_message("user"):
        # コピーボタン付きメッセージ表示
        import html
        escaped_prompt = html.escape(prompt)
        message_id = f"user_msg_{len(messages)}"
        
        st.markdown(f"""
<div style="position: relative;">
    <div id="{message_id}" style="padding-right: 40px;">{escaped_prompt}</div>
    <button onclick="copyToClipboard('{message_id}')" style="position: absolute; right: 0; top: 0; background: transparent; border: 1px solid #444; border-radius: 4px; cursor: pointer; padding: 4px 8px; color: #aaa; font-size: 12px;" title="コピー">
        📋
    </button>
</div>
<script>
function copyToClipboard(elementId) {{
    const element = document.getElementById(elementId);
    const text = element.innerText;
    navigator.clipboard.writeText(text).then(() => {{
        // コピー成功フィードバック
        const button = event.target;
        button.textContent = '✓';
        setTimeout(() => {{ button.textContent = '📋'; }}, 1000);
    }});
}}
</script>
""", unsafe_allow_html=True)
        if uploaded_files:
            for uf in uploaded_files:
                st.caption(f"📎 添付: {uf.name}")
        if youtube_url:
            st.caption(f"📺 YouTube: {youtube_url}")
        if pasted_image_bytes:
            st.caption("📋 画像が貼り付けられました")

    messages.append({
        "role": "user",
        "content": prompt,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    update_current_session_messages(messages)

    # ========================================
    # モデル応答
    # ========================================
    with st.chat_message("assistant"):
        with st.status("思考中...", expanded=True) as status_container:
            try:
                # 過去のメッセージをモデルの履歴に変換
                model_history = []
                for msg in messages[:-1]:  # 最新のユーザーメッセージは別途追加
                    if msg["role"] == "user":
                        model_history.append(
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(text=msg["content"])],
                            )
                        )
                    elif msg["role"] == "model":
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
                    "\n"
                    "**【判断憲法 - この原則に従ってください】**\n"
                    "・安全性 > 品質 > コスト > スピード の優先順位で判断する\n"
                    "・取り返しのつかないリスクは絶対に避ける（人命、セキュリティ、法令違反）\n"
                    "・不確実な情報は必ず明示し、確信が持てない場合は「自信度: Low」と記載する\n"
                    "・複数の選択肢がある場合は、リスクとリターンを定量的に比較する\n"
                    "\n"
                    "以下のガイドラインを厳守してください：\n"
                    "1. **メタ発言の禁止**: 「私はAIです」「世界最高峰の～として」などの自己言及や前置きは一切行わないでください。\n"
                    "2. **意図の汲み取り**: ユーザーの質問の背後にある意図（文脈、暗黙の前提）を推測し、言葉通りではなく「ユーザーが本当に知りたいこと」に答えてください。\n"
                    "3. **構造化された回答**: 結論を先に述べ、その後に詳細な根拠、シナリオ分析、リスク要因を論理的に展開してください。\n"
                    "4. **客観性**: 予測を行う場合は、断定を避け、複数のシナリオ（楽観、悲観、中立）を提示してください。\n"
                    "5. **引用**: 検索を使用した場合は、必ず情報源を明示してください。\n"
                    "6. **改行の制限**: Markdownは使用してよいですが、連続する空行は1行までにしてください。"
                )

                final_answer = ""
                grounding_metadata = None
                
                # =========================
                # Manual Mode Settings
                # =========================
                # β1通常モード以外はリサーチを実行
                enable_research = "β1" not in response_mode
                enable_meta = "メタ" in response_mode or "MAX" in response_mode or "grok" in response_mode
                enable_strict = "鬼軍曹" in response_mode or "MAX" in response_mode
                
                # Grok X検索はニュース/トレンド系のみ
                def should_use_x_search(prompt: str) -> bool:
                    keywords = ["Xで", "Twitter", "ツイッター", "ポスト", "トレンド", "炎上", "バズ", "話題"]
                    return any(kw in prompt for kw in keywords)
                
                enable_grok_x_search = "grok" in response_mode and should_use_x_search(prompt)

                # =========================
                # 通常モード (高速 / 鬼軍曹)
                # =========================
                if not enable_research:
                    config = types.GenerateContentConfig(
                        temperature=0.8,  # Phase A: アイデア出しフェーズ - 多様性重視
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
                        usage_stats["total_input_tokens"] += (response.usage_metadata.prompt_token_count or 0)
                        usage_stats["total_output_tokens"] += (response.usage_metadata.candidates_token_count or 0)

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
                            usage_stats["total_input_tokens"] += (review_resp.usage_metadata.prompt_token_count or 0)
                            usage_stats["total_output_tokens"] += (review_resp.usage_metadata.candidates_token_count or 0)

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
                    
                    # セッション間記憶を取得
                    session_memory = build_session_memory(
                        st.session_state.sessions,
                        st.session_state.current_session_id,
                        max_entries=10
                    )
                    
                    # リサーチ用のコンテンツを構築
                    import datetime as dt
                    current_date = dt.datetime.now().strftime("%Y年%m月%d日")
                    research_parts = [types.Part(text=(
                        f"重要: 今日は{current_date}です。この日付より新しい情報を優先してください。\n\n"
                        f"質問: {prompt}"
                    ))]
                    
                    # セッション記憶を先頭に追加
                    if session_memory:
                        research_parts.insert(0, types.Part(text=session_memory))
                    
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
                    
                    # TODO: Agentic Loop (Deep Research)
                    # - 検索結果の不確実性が高い場合、while ループで自律的に再検索
                    # - 最大ループ回数のガード（例: max_loops=3）
                    # - 1ターンあたりの最大コスト制限
                    # - 実装優先度: 中（実運用で「ここで再検索してほしい」という痛みが見えてから）
                    
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
                        usage_stats["total_input_tokens"] += (research_resp.usage_metadata.prompt_token_count or 0)
                        usage_stats["total_output_tokens"] += (research_resp.usage_metadata.candidates_token_count or 0)
                    
                    # --- Phase 1.3: 事実とリスクの抽出 (ms/Azモードのみ) ---
                    # Phase B: JSON IR extraction with v1 fallback
                    fact_summary = ""
                    risk_summary = ""
                    current_ir = None  # Store IR for Phase 2
                    is_ms_az_mode = "ms/Az" in response_mode
                    
                    if is_ms_az_mode:  # ms/Azモードでのみ重いJSON抽出を実行
                        status_container.write("Phase 1.3: JSON IR抽出中...")
                        
                        # Try v2 extraction first
                        ir, ir_usage, ir_raw_json = extract_facts_and_risks_v2(
                            client=client,
                            model_id=model_id,
                            user_question=prompt,
                            research_text=research_text
                        )
                        
                        if ir is not None:
                            # IR extraction succeeded
                            current_ir = ir
                            fact_summary, risk_summary = convert_ir_to_markdown(ir)
                            phase13_usage = ir_usage
                            status_container.write("✓ Phase 1.3完了 (JSON IR)")
                            
                            # Debug UI
                            with status_container.expander("📊 抽出された事実とリスク (Phase B: JSON IR)", expanded=False):
                                st.markdown(f"{fact_summary}\n\n{risk_summary}")
                                
                                st.markdown("---")
                                st.markdown("### 🔍 デバッグ: JSON IR構造")
                                st.json(ir)
                                
                                st.markdown("### 📄 生のJSON出力")
                                st.code(ir_raw_json, language="json")
                        
                        else:
                            # IR extraction failed - fallback to v1
                            status_container.write("⚠️ IR抽出失敗 - v1にフォールバック中...")
                            fact_summary, risk_summary, phase13_usage = extract_facts_and_risks(
                                client, model_id, research_text
                            )
                            status_container.write("✓ Phase 1.3完了 (v1 fallback)")
                            
                            with status_container.expander("抽出された事実とリスク (v1 fallback)", expanded=False):
                                st.markdown(f"{fact_summary}\n\n{risk_summary}")
                                st.warning(f"IR抽出エラー: {ir_raw_json[:200]}")
                        
                        # コスト計算 (Phase 1.3)
                        phase13_cost = calculate_cost(
                            model_id,
                            phase13_usage["prompt_tokens"],
                            phase13_usage["output_tokens"]
                        )
                        st.session_state.session_cost += phase13_cost
                        usage_stats["total_cost_usd"] += phase13_cost
                        usage_stats["total_input_tokens"] += phase13_usage["prompt_tokens"]
                        usage_stats["total_output_tokens"] += phase13_usage["output_tokens"]

                    
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
                        
                        # コスト計算
                        if question_resp.usage_metadata:
                            cost = calculate_cost(
                                model_id,
                                question_resp.usage_metadata.prompt_token_count,
                                question_resp.usage_metadata.candidates_token_count,
                            )
                            st.session_state.session_cost += cost
                            usage_stats["total_cost_usd"] += cost
                            usage_stats["total_input_tokens"] += (question_resp.usage_metadata.prompt_token_count or 0)
                            usage_stats["total_output_tokens"] += (question_resp.usage_metadata.candidates_token_count or 0)

                    # --- Phase 1.5b: OpenRouter セカンダリモデル 独立思考 (多層モードのみ) ---
                    grok_thought = ""
                    grok_status = "skipped"
                    grok_error_msg = None

                    # ▼▼▼ Phase 1.5b/d/e: 並列処理（高速化） ▼▼▼
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    
                    # 並列タスク用のヘルパー関数（スレッドセーフ）
                    def run_grok_task():
                        """Grok/OpenRouter セカンダリモデル"""
                        if not (enable_meta and OPENROUTER_API_KEY):
                            return {"status": "skipped", "thought": "", "error": None}
                        try:
                            grok_mode = "full_max" if "MAX" in response_mode else "default"
                            grok_input = f"【事実】\n{fact_summary}\n\n【リスク】\n{risk_summary}" if fact_summary else research_text
                            result = think_with_grok(prompt, grok_input, enable_x_search=enable_grok_x_search, mode=grok_mode).strip()
                            if result:
                                return {"status": "success", "thought": result, "error": None}
                            return {"status": "empty", "thought": "", "error": None}
                        except Exception as e:
                            return {"status": "error", "thought": "", "error": str(e)}
                    
                    def run_claude_task():
                        """Claude 4.5 Sonnet (AWS Bedrock)"""
                        is_az_mode = "Az" in response_mode
                        if not (is_az_mode and AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY):
                            return {"status": "skipped", "thought": "", "usage": {}, "error": None}
                        try:
                            if fact_summary:
                                safe_text = f"【事実】\n{fact_summary}\n\n【リスク】\n{risk_summary}"
                            else:
                                safe_text = research_text[:40000]
                            thought, usage = think_with_claude45_bedrock(prompt, safe_text)
                            thought = thought.strip() if thought else ""
                            if thought and not thought.startswith("Error"):
                                return {"status": "success", "thought": thought, "usage": usage, "error": None}
                            return {"status": "error", "thought": thought, "usage": {}, "error": None}
                        except Exception as e:
                            return {"status": "error", "thought": "", "usage": {}, "error": str(e)}
                    
                    def run_o4mini_task():
                        """o4-mini (GitHub Models)"""
                        if fact_summary:
                            safe_text = f"{fact_summary[:1500]}\n\n{risk_summary[:1500]}"
                        else:
                            safe_text = research_text[:3000]
                        input_len = len(f"{prompt}\n\n{safe_text}")
                        
                        if not (is_ms_az_mode and GITHUB_TOKEN and input_len <= 3800):
                            return {"status": "skipped", "thought": "", "input_len": input_len, "error": None}
                        try:
                            thought, _ = think_with_o4_mini(prompt, safe_text)
                            thought = thought.strip() if thought else ""
                            if thought and not thought.startswith("Error"):
                                return {"status": "success", "thought": thought, "input_len": input_len, "error": None}
                            return {"status": "error", "thought": thought, "input_len": input_len, "error": None}
                        except Exception as e:
                            return {"status": "error", "thought": "", "input_len": input_len, "error": str(e)}
                    
                    # 並列実行
                    status_container.write("🚀 Phase 1.5: マルチモデル並列思考中...")
                    
                    grok_thought = ""
                    grok_status = "skipped"
                    claude45_thought = ""
                    claude45_status = "skipped"
                    claude45_usage = {}
                    o4mini_thought = ""
                    o4mini_status = "skipped"
                    
                    with ThreadPoolExecutor(max_workers=3) as executor:
                        futures = {
                            executor.submit(run_grok_task): "grok",
                            executor.submit(run_claude_task): "claude",
                            executor.submit(run_o4mini_task): "o4mini"
                        }
                        
                        for future in as_completed(futures, timeout=60):
                            name = futures[future]
                            try:
                                result = future.result()
                                
                                if name == "grok":
                                    grok_status = result["status"]
                                    grok_thought = result["thought"]
                                    grok_error_msg = result.get("error")
                                    if grok_status == "success":
                                        status_container.write(f"✓ {SECONDARY_MODEL_NAME} 完了")
                                    elif grok_status == "error":
                                        status_container.write(f"⚠ {SECONDARY_MODEL_NAME}: {grok_error_msg}")
                                
                                elif name == "claude":
                                    claude45_status = result["status"]
                                    claude45_thought = result["thought"]
                                    claude45_usage = result.get("usage", {})
                                    if claude45_status == "success":
                                        status_container.write("✓ Claude 4.5 Sonnet 完了")
                                        # コスト計算
                                        if claude45_usage:
                                            input_tokens = claude45_usage.get("inputTokens", 0)
                                            output_tokens = claude45_usage.get("outputTokens", 0)
                                            claude_cost = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
                                            st.session_state.session_cost += claude_cost
                                            usage_stats["total_cost_usd"] += claude_cost
                                            status_container.write(f"💰 Claude: ${claude_cost:.4f}")
                                    elif claude45_status == "error":
                                        status_container.write("⚠ Claude 4.5 エラー")
                                
                                elif name == "o4mini":
                                    o4mini_status = result["status"]
                                    o4mini_thought = result["thought"]
                                    if o4mini_status == "success":
                                        status_container.write("✓ o4-mini 完了")
                                    elif o4mini_status == "skipped" and is_ms_az_mode and GITHUB_TOKEN:
                                        input_len = result.get("input_len", 0)
                                        if input_len > 3800:
                                            status_container.write(f"ℹ️ o4-mini スキップ (入力長: {input_len})")
                            
                            except Exception as e:
                                status_container.write(f"⚠ {name} 並列処理エラー: {e}")
                    
                    # 結果をExpanderに表示（成功したもののみ）
                    if grok_status == "success" and grok_thought:
                        with status_container.expander(f"{SECONDARY_MODEL_NAME} の独立回答案", expanded=False):
                            st.markdown(grok_thought)
                    
                    if claude45_status == "success" and claude45_thought:
                        with status_container.expander("Claude 4.5 Sonnet の独立回答案", expanded=False):
                            st.markdown(claude45_thought)
                    
                    if o4mini_status == "success" and o4mini_thought:
                        with status_container.expander("o4-mini の独立回答案", expanded=False):
                            st.markdown(o4mini_thought)
                    # ▲▲▲ Phase 1.5 並列処理 ここまで ▲▲▲

                    # --- Phase 2: 統合エージェント ---
                    status_container.write("Phase 2: 統合フェーズ実行中...")
                    
                    import datetime as dt
                    current_date = dt.datetime.now().strftime("%Y年%m月%d日")

                    if enable_meta:
                        deep_instruction = base_system_instruction + f"""

【Phase 3: 深い統合と総括指示】

上記の多段フェーズで得られた情報（リサーチメモ、Grok回答、Claude回答、o4-mini回答、各レビュー）を総合し、
ユーザーにとって最も価値ある最終回答を作成してください。

**将来予測の注意事項（特にマクロ経済・株価など）:**
・将来の数値（株価水準や金利水準）は、具体的な水準を1つに固定せず、「レンジ」と「不確実性」を明示すること。
・政治シナリオも1つに決め打ちせず、複数の可能性を示すこと。
・断定的な予測ではなく、シナリオとリスクに寄せた表現にすること。

**文章スタイル:**
- 見出し・箇条書きを効果的に使い、読みやすくする
- Markdownを許可するが、連続する空行は1行まで
- リサーチメモに引用元URLがあれば、適宜参照リンクとして提示する

**思考プロセスの公開:**
- 「Phase 1: リサーチ」「Phase 2: 多モデル回答」「Phase 3: 統合」を踏まえた上で、
  どのような判断軸で最終回答を構成したのかを軽く述べてもよい

ユーザーの質問:
{prompt}

**あなたの役割**: 最終判断エージェント

**タスク**: 調査メモとサブモデル(Grok, Claude, o4-mini)の指摘を統合し、
ユーザーにとって実務的に使える「判断」を出してください。

**出力構成**（この順番で必須）:

1. 📌 結論
   - 1〜3行で、方針 / Yes/No / 推奨案をはっきり書く

2. 🔑 主要な根拠
   - 箇条書きで3〜7個
   - それぞれについて「どの情報源 / どのモデルがそう言っているか」を書く
   - できれば「強さ (強/中/弱)」も付ける

3. 📉📈 シナリオ分岐
   - 楽観 / ベース / 悲観 の3パターンでどう変わりうるかを書く
   - それぞれ何がトリガーになるかも書く

4. ⚠️ リスク・反対意見
   - Grok, Claude, o4-mini が挙げた懸念・反論を統合して列挙
   - 「どのモデルが指摘しているか」も書く

5. ❓ 残っている不確実性と今後必要な検証
   - まだはっきりしない点
   - 追加で確認すべきデータや実験
   - 「ここまでが AI が安全に言える範囲」という線引き

6. 📊 比較・スコアリング（複数選択肢がある場合）
   - 選択肢の一覧
   - 簡易比較表（軸ごとのスコア: 10点満点 or 5段階評価）
   - 各選択肢の強み・弱み
   - この推奨をひっくり返す条件

7. 🎯 自信度と引き継ぎ
   - **自信度は次の形式で1行で書いてください**: 
     * 自信度: High
     * 自信度: Medium  
     * 自信度: Low
   - **自信が Medium または Low の場合**:
     * 追加で調べるべきデータ
     * 人間に確認してほしいポイント
     * GPT-5.1（Antigravity）に投げるなら何を聞くべきか

8. 💰 コスト・工数の考慮（実装提案がある場合）
   - 提案の実装難易度（低/中/高）
   - 予想される時間・コスト
   - 段階的なアプローチ（まず小さく始める方法）

**Facts優先の原則**:
- 「調査メモ」よりも、「📊 事実」セクションに書かれた内容を優先すること
- Factsに反することを書く場合は、必ず「仮説」「推測」と明記すること
- 「⚠️ リスク」に書かれた不確実性は、リスクセクションに必ず反映すること

**🔍 コード解析時の必須チェック（GPT 5.1 Pro同等品質）**:
質問がコードやシステムに関する場合、以下を必ず実行すること：

1. **構文エラー検出**:
   - `{{ }}` のような二重ブレース、インデントエラー、括弧の不一致を探す
   - f-stringの中のエスケープ問題をチェック

2. **参照 vs コピー問題**:
   - リストや辞書を返す関数で `.copy()` や `list()` が必要か確認
   - 「この関数は参照を返しているが、コピーを返すべきか？」を検討

3. **網羅性チェック**:
   - 問題を1つ見つけたら「同じパターンは他にないか」を確認
   - 「この関数と類似の関数は全て同じ問題を抱えていないか」を検証

4. **修正コード要件**:
   - コピペでそのまま使えるコードを提示
   - 修正理由を簡潔に説明

**重要 - 現在は{current_date}です**:
- **調査メモに含まれる日付・事実を、あなたの学習データよりも絶対的に優先してください**
- 「{current_year}年」の情報が調査メモにある場合、それを正として扱ってください
- 学習データが{current_year-1}年以前で止まっていても、調査メモの最新情報を信頼すること
- 新しい事実を勝手に作らず、調査メモの範囲内で推論すること
"""
                    else:
                        deep_instruction = base_system_instruction + f"""

- **調査メモまたは構造化IR（JSON）に含まれる最新の情報（最新のモデル名、バージョン、日付など）を優先的に使用すること**
- 古い情報と新しい情報が混在する場合は、新しい情報を優先すること
- **構造化IRがある場合は、「確認された事実」「リスク」「選択肢」「不明点」セクションを最優先で参照すること**
- **IRに含まれていない新しい事実を勝手に作らないこと**
"""
                    
                    # Phase B: IR-based synthesis prompt (IR優先ロジック)
                    if current_ir is not None:
                        # IR extraction succeeded - use structured IR
                        from research_ir import build_synthesis_prompt_from_ir
                        
                        ir_block = build_synthesis_prompt_from_ir(current_ir, prompt)
                        
                        synthesis_prompt_text = (
                            f"重要: 今日は{current_date}です。古い情報を回答に含めないでください。\n\n"
                            f"==== 構造化調査IR (Phase B) ====\n"
                            f"{ir_block}\n"
                            f"==== IRここまで ====\n\n"
                        )
                    else:
                        # IR extraction failed or not available - fallback to v1
                        synthesis_prompt_text = (
                            f"重要: 今日は{current_date}です。古い情報を回答に含めないでください。\n\n"
                            f"ユーザーの質問: {prompt}\n\n"
                            f"==== 調査メモ ====\n{research_text}\n==== 調査メモここまで ====\n\n"
                        )
                    
                    if enable_meta and questions_text:
                        synthesis_prompt_text += f"==== メタ質問一覧 ====\n{questions_text}\n==== メタ質問ここまで ====\n\n"
                    
                    if enable_meta and grok_thought:
                        synthesis_prompt_text += f"==== 別視点からのリスク指摘 ({SECONDARY_MODEL_NAME}) ====\n{grok_thought}\n==== {SECONDARY_MODEL_NAME} ここまで ====\n\n"
                    
                    
                    # ▼▼▼ Claude 4.5 の回答を統合プロンプトに加える ▼▼▼
                    if claude45_thought and claude45_status == "success":
                        synthesis_prompt_text += f"==== 別視点からの回答案 (Claude 4.5 Sonnet / AWS Bedrock) ====\n{claude45_thought}\n==== Claude 4.5 Sonnet ここまで ====\n\n"
                    # ▲▲▲ Claude 4.5 追加ここまで ▲▲▲
                    
                    # ▼▼▼ o4-mini の回答を統合プロンプトに加える ▼▼▼
                    if o4mini_thought and o4mini_status == "success":
                        synthesis_prompt_text += f"==== 見落とし/リスクチェック (o4-mini / GitHub Models) ====\n{o4mini_thought}\n==== o4-mini ここまで ====\n\n"
                    # ▲▲▲ o4-mini 追加ここまで ▲▲▲
                    
                    # 統合指示の修正
                    if enable_meta and (grok_thought or claude45_thought or o4mini_thought):
                        synthesis_prompt_text += f"指示:\n1. まず、メタ質問 Q1〜Qn に一つずつ簡潔に答えてください。\n2. 他のモデル ({SECONDARY_MODEL_NAME}, Claude 4.5 Sonnet, o4-mini) の回答案も参考にしつつ（ただし盲信せず）、独自の視点で統合してください。\n3. そのうえで、それらの回答を踏まえた『全体としての結論・分析・示唆』をまとめてください。"
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
                        temperature=0.4,  # Phase A: 統合時の柔軟性向上
                        candidate_count=1,
                        tools=[],  # 統合フェーズでは検索OFF
                        system_instruction=deep_instruction,
                        thinking_config=types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.HIGH
                        ),
                    )
                    
                    # Phase 2 リトライ機能（クォータエラー対策）
                    import time
                    max_retries = 3
                    draft_answer = None
                    synthesis_resp = None
                    
                    for attempt in range(max_retries):
                        try:
                            synthesis_resp = client.models.generate_content(
                                model=model_id,
                                contents=synthesis_contents,
                                config=synthesis_config,
                            )
                            draft_answer = extract_text_from_response(synthesis_resp)
                            
                            # ▼▼▼ finish_reason検出：途中で切れたら自動継続 ▼▼▼
                            candidate = synthesis_resp.candidates[0] if synthesis_resp.candidates else None
                            if candidate and hasattr(candidate, 'finish_reason'):
                                finish_reason = str(candidate.finish_reason).upper()
                                if "MAX_TOKENS" in finish_reason or "LENGTH" in finish_reason:
                                    status_container.write("⚠️ 回答が途中で切れました。続きを取得中...")
                                    try:
                                        continuation_resp = client.models.generate_content(
                                            model=model_id,
                                            contents=[
                                                types.Content(role="user", parts=[
                                                    types.Part.from_text(text="先ほどの回答が途中で途切れました。続きを書いてください。要約せず、途切れた箇所から続けてください。")
                                                ])
                                            ],
                                            config=synthesis_config,
                                        )
                                        continuation_text = extract_text_from_response(continuation_resp)
                                        draft_answer += "\n\n" + continuation_text
                                        status_container.write("✓ 統合完了（自動継続）")
                                    except Exception as cont_e:
                                        draft_answer += "\n\n*（続きの取得に失敗しました）*"
                                else:
                                    status_container.write("✓ 統合完了")
                            else:
                                status_container.write("✓ 統合完了")
                            # ▲▲▲ finish_reason検出 ここまで ▲▲▲
                            
                            break
                        except Exception as e:
                            error_msg = str(e).lower()
                            if "quota" in error_msg or "rate" in error_msg or "resource" in error_msg:
                                if attempt < max_retries - 1:
                                    wait_time = (attempt + 1) * 15 + 15  # 30秒, 45秒, 60秒（強化版）
                                    status_container.write(f"⏳ クォータ制限のため {wait_time}秒待機中... (試行 {attempt + 2}/{max_retries})")
                                    time.sleep(wait_time)
                                else:
                                    status_container.warning("⚠️ Phase 2: クォータ制限により断念。リサーチ結果のサマリーを表示します。")
                                    # フォールバック: リサーチ結果の要約を回答として使用
                                    draft_answer = f"**⚠️ 統合フェーズがクォータ制限により中断されました**\n\n### 収集した情報（Phase 1）:\n\n{research_text[:3000]}..."
                            else:
                                raise e
                    
                    if draft_answer is None:
                        draft_answer = f"**⚠️ Phase 2エラー**\n\n{research_text[:2000]}..."
                    
                    # コスト計算 (Phase 2)
                    if synthesis_resp.usage_metadata:
                        cost = calculate_cost(
                            model_id,
                            synthesis_resp.usage_metadata.prompt_token_count,
                            synthesis_resp.usage_metadata.candidates_token_count,
                        )
                        st.session_state.session_cost += cost
                        usage_stats["total_cost_usd"] += cost
                        usage_stats["total_input_tokens"] += (synthesis_resp.usage_metadata.prompt_token_count or 0)
                        usage_stats["total_output_tokens"] += (synthesis_resp.usage_metadata.candidates_token_count or 0)
                    
                    # --- Phase 3: レビューエージェント (鬼軍曹モードのみ) ---
                    grok_review_status = "skipped"  # デフォルト値（Phase 3実行しない場合も安全）
                    if enable_strict:
                        status_container.write("Phase 3: レビューフェーズ実行中...")
                        

                        reviewer_instruction = base_system_instruction + """

**あなたの役割**: 鬼軍曹レベルの厳格なレビューア + Devil's Advocate（悪魔の代弁者）

**タスク**: 初版回答をチェックし、必要なら修正版を返す。ただし、**調査メモの情報を優先し、最新情報を維持すること**。

**レビュー観点**:
- 事実と推測を明確に分ける
- 過度に自信のある断定を弱める
- 数字や固有名詞が調査メモと矛盾していないか確認
- **調査メモに含まれる最新の情報（最新モデル、バージョン、日付など）が正しく使われているか確認**
- **古い情報で上書きしていないか確認**
- 見落としている重要なリスク・シナリオがあれば追加

**🔥 Devil's Advocate（悪魔の代弁者）- 必須**:
レビュー時に以下を必ず実施してください：
1. **この結論を覆す最強の反論を3つ**考える
2. それでも結論が正しいと言えるか検証する
3. 反論に対する再反論が弱い場合は、結論を修正する
4. 最終回答に「🔴 最強の反論」セクションを追加し、考慮した反論と、それでも結論を維持する理由を明記

**📊 5段階確信度 - 必須**:
回答の最後に以下の形式で確信度を明記：
- **確信度: Very High (90%+)** - ほぼ確実、覆る可能性は低い
- **確信度: High (70-90%)** - 高い信頼性、主要なリスクは考慮済み
- **確信度: Medium (50-70%)** - 妥当な推論だが不確実性あり
- **確信度: Low (30-50%)** - 仮説段階、追加検証が必要
- **確信度: Very Low (<30%)** - 推測の域を出ない、慎重に扱うべき

確信度がMedium以下の場合は、「⚠️ 確信度を上げるために必要なこと」を追記すること。

**🔍 自己矛盾チェック - 必須**:
- Phase 1（調査メモ）の情報と、Phase 2（統合回答）の内容に矛盾がないか確認
- 矛盾がある場合は「⚡ 矛盾検出」として明記し、どちらを採用したか理由を説明

**📎 エビデンス引用 - 重要**:
- 主要な主張には必ず根拠を示す（「調査メモによると...」「XXXの情報源では...」）
- 根拠なき断定は避け、推測の場合は「おそらく」「可能性がある」と明記
- 情報源が複数ある場合は、より信頼性の高いものを優先

**🚫 代替案の棄却理由 - 重要**:
- 結論を導く際に、検討した他の選択肢を明記
- 「なぜその選択肢を採用しなかったか」を簡潔に説明
- 例: 「選択肢Aは〇〇の理由で不適、選択肢Bは△△のリスクがあるため、結論Cを採用」

**重要**: 
- 調査メモの情報が最新である場合、それを優先すること
- あなたの知識が古い場合は、調査メモの情報を信頼すること

**出力**: 修正版の回答全文（Devil's Advocateセクション、確信度、エビデンス引用を含む）
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
                        
                        # Phase 3 リトライ機能（クォータエラー対策）
                        import time
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                review_resp = client.models.generate_content(
                                    model=model_id,
                                    contents=review_contents,
                                    config=review_config,
                                )
                                final_answer = extract_text_from_response(review_resp)
                                status_container.write("✓ レビュー完了")
                                break
                            except Exception as e:
                                error_msg = str(e).lower()
                                if "quota" in error_msg or "rate" in error_msg or "resource" in error_msg:
                                    if attempt < max_retries - 1:
                                        wait_time = (attempt + 1) * 15 + 5  # 20秒, 35秒, 50秒（強化版）
                                        status_container.write(f"⏳ クォータ制限のため {wait_time}秒待機中... (試行 {attempt + 2}/{max_retries})")
                                        time.sleep(wait_time)
                                    else:
                                        status_container.warning("⚠️ Phase 3: クォータ制限により断念。Phase 2の結果を使用します。")
                                        final_answer = draft_answer  # Phase 2の結果を使用
                                else:
                                    raise e
                        
                        # --- Phase 3b: Grok鬼軍曹レビュー (多層モード + 鬼軍曹モード全般) ---
                        # 多層モードで、かつ鬼軍曹系のモード（鬼軍曹、メタ思考、本気MAX）で発動
                        use_grok_reviewer = (mode_category == "🎯 回答モード(多層)" and (enable_strict or "鬼軍曹" in response_mode))
                        if use_grok_reviewer and OPENROUTER_API_KEY:
                            status_container.write(f"{SECONDARY_MODEL_NAME}による最終レビュー実行中...")
                            
                            review_mode = "normal"
                            if "鬼軍曹" in response_mode:
                                review_mode = "onigunsou"
                            elif "MAX" in response_mode:
                                review_mode = "full_max"

                            grok_answer = review_with_grok(prompt, final_answer, research_text, mode=review_mode).strip()
                            
                            # エラーチェック：Grokがエラー文字列を返した場合
                            if grok_answer.startswith("Error calling"):
                                grok_review_status = "error"
                                status_container.error(f"⚠️ {SECONDARY_MODEL_NAME} 最終レビュー エラー\n\n{grok_answer}")
                                # final_answerはGemini鬼軍曹版のまま使用
                            else:
                                grok_review_status = "success"
                                # 処理履歴を先に構築
                                
                processing_history = []
                processing_history.append("**Phase 1**: Gemini リサーチ (Google検索)")
                if enable_meta:
                    processing_history.append("**Phase 1.5a**: Gemini メタ質問生成")
                    if grok_status == "success":
                        processing_history.append(f"**Phase 1.5b**: {SECONDARY_MODEL_NAME} 独立思考 ✓")
                    if claude45_status == "success":
                        processing_history.append("**Phase 1.5d**: Claude 4.5 Sonnet 独立思考 (AWS Bedrock) ✓")
                    if o4mini_status == "success":
                        processing_history.append("**Phase 1.5e**: o4-mini 独立思考 (GitHub Models) ✓")
                processing_history.append("**Phase 2**: Gemini 統合フェーズ")
                if enable_strict:
                    processing_history.append("**Phase 3**: Gemini 鬼軍曹レビュー")
                    processing_history.append(f"**Phase 3b**: {SECONDARY_MODEL_NAME} 最終レビュー ✓")
                else: # This 'else' belongs to 'if use_grok_reviewer and OPENROUTER_API_KEY:'
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
                            usage_stats["total_input_tokens"] += (review_resp.usage_metadata.prompt_token_count or 0)
                            usage_stats["total_output_tokens"] += (review_resp.usage_metadata.candidates_token_count or 0)
                    else:
                        final_answer = draft_answer

                save_usage(usage_stats)

                # --- ユーザープロファイルの自動更新 & 自動提案 ---
                try:
                    status_container.write("ユーザープロファイルを更新中...")
                    # client already initialized at startup
                    
                    # プロファイル更新
                    updated_profile, profile_usage = update_user_profile_from_conversation(
                        client, prompt, final_answer
                    )
                    save_user_profile(updated_profile)
                    
                    # プロファイル更新コスト
                    p_cost = calculate_cost("gemini-2.5-flash", profile_usage["input_tokens"], profile_usage["output_tokens"])
                    st.session_state.session_cost += p_cost
                    usage_stats["total_cost_usd"] += p_cost
                    usage_stats["total_input_tokens"] += profile_usage["input_tokens"]
                    usage_stats["total_output_tokens"] += profile_usage["output_tokens"]
                    
                    # --- 回答末尾への自動提案 (Phase 3-A) ---
                    status_container.write("次の質問を提案中...")
                    suggestion_prompt = f"""
以下の会話の続きとして、ユーザーが次に深掘りすべき「価値ある質問」を3つ提案してください。
ユーザーのプロファイル（興味関心）: {updated_profile.get('interests', [])}

【直前の会話】
User: {prompt[:800]}
AI: {final_answer[:1000]}

【質問生成ガイドライン】
- 表面的な質問ではなく、回答の核心を深掘りする質問を生成
- 実務で役立つ具体的なアクションにつながる質問
- 見落とされがちなリスクや代替案を問う質問
- 各質問は60〜100文字程度で、具体的かつ詳細に

【出力形式（厳守）】
- [質問1: 具体的で深い質問文？]
- [質問2: 実務につながる質問文？]
- [質問3: リスクや代替案を問う質問文？]
"""
                    suggestion_resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[{"role": "user", "parts": [{"text": suggestion_prompt}]}],
                        config=types.GenerateContentConfig(temperature=0.7, max_output_tokens=512)
                    )
                    
                    # 出力を整形してから追加
                    import re
                    raw = extract_text_from_response(suggestion_resp).strip()
                    lines = [l.strip() for l in raw.splitlines() if l.strip()]

                    questions = []
                    for l in lines:
                        if not l.startswith("-"):
                            continue
                        q = l.lstrip("- ").strip()
                        if not q:
                            continue
                        # 「理由:」等が付いていたら手前だけを採用
                        if "理由" in q:
                            q = q.split("理由", 1)[0].strip()
                        # 40文字を超える場合は切り詰める
                        if len(q) > 40:
                            q = q[:40].rstrip() + "..."
                        # 必ず?で終わるようにする
                        if not q.endswith(("?", "？")):
                            q += "？"
                        questions.append(f"- {q}")
                        if len(questions) >= 3:
                            break

                    if questions:
                        suggestions_text = "\n".join(questions)
                        final_answer += "\n\n---\n\n### 🔁 次に試せる質問候補\n" + suggestions_text
                    
                        # 提案生成コスト
                        s_usage = suggestion_resp.usage_metadata
                        s_cost = calculate_cost("gemini-2.5-flash", s_usage.prompt_token_count, s_usage.candidates_token_count)
                        st.session_state.session_cost += s_cost
                        usage_stats["total_cost_usd"] += s_cost
                        usage_stats["total_input_tokens"] += s_usage.prompt_token_count
                        usage_stats["total_output_tokens"] += s_usage.candidates_token_count
                    
                    save_usage(usage_stats)
                    
                except Exception as e:
                    print(f"Profile/Suggestion update failed: {e}")

                status_container.update(label="完了！", state="complete", expanded=False)

                # モデル名を表示
                models_used = [f"Gemini: {model_id}"]
                
                # Grok Status
                if enable_meta:
                    if grok_status == "success":
                        models_used.append(f"OpenRouter: {SECONDARY_MODEL_NAME} (OK)")
                    elif grok_status == "error":
                        models_used.append(f"OpenRouter: {SECONDARY_MODEL_NAME} (Error)")
                    elif grok_status == "empty":
                        models_used.append(f"OpenRouter: {SECONDARY_MODEL_NAME} (Empty)")
                
                # ▼▼▼ Claude 4.5 Sonnet Status ▼▼▼
                if claude45_status == "success":
                    models_used.append(f"Claude 4.5 Sonnet (AWS Bedrock) (OK)")
                elif claude45_status == "error":
                    models_used.append(f"Claude 4.5 Sonnet (AWS Bedrock) (Error)")
                # ▲▲▲ Claude 4.5 Sonnet Status ここまで ▲▲▲
                
                # ▼▼▼ o4-mini Status ▼▼▼
                if o4mini_status == "success":
                    models_used.append(f"o4-mini (GitHub Models) (OK)")
                elif o4mini_status == "error":
                    models_used.append(f"o4-mini (GitHub Models) (Error)")
                # ▲▲▲ o4-mini Status ここまで ▲▲▲
                
                
                st.caption(f"🤖 使用モデル: {' + '.join(models_used)}")
                
                # ▼▼▼ 処理履歴を最終回答の冒頭に追加 ▼▼▼
                processing_history = []
                processing_history.append("**Phase 1**: Gemini リサーチ (Google検索)")
                
                if enable_meta:
                    processing_history.append("**Phase 1.5a**: Gemini メタ質問生成")
                # Grok/セカンダリモデル status
                if grok_status == "success":
                    processing_history.append(f"**Phase 1.5b**: OpenRouterセカンダリモデル ({SECONDARY_MODEL_NAME}) 独立思考 ✓")
                elif grok_status == "error":
                    msg = grok_error_msg or "エラー"
                    processing_history.append(f"**Phase 1.5b**: OpenRouterセカンダリモデル ({SECONDARY_MODEL_NAME}) 独立思考 ⚠️ {msg}")
                elif grok_status == "empty":
                    processing_history.append(f"**Phase 1.5b**: OpenRouterセカンダリモデル ({SECONDARY_MODEL_NAME}) 独立思考（出力なし）")
                
                # Phase 1.5c (Puter) は廃止
                
                
                if claude45_status == "success":
                    processing_history.append(f"**Phase 1.5d**: Claude 4.5 Sonnet 独立思考 (AWS Bedrock) ✓")
                elif claude45_status == "error":
                    processing_history.append(f"**Phase 1.5d**: Claude 4.5 Sonnet 独立思考 ⚠️ エラー")
                
                if o4mini_status == "success":
                    processing_history.append(f"**Phase 1.5e**: o4-mini 独立思考 (GitHub Models) ✓")
                elif o4mini_status == "error":
                    processing_history.append(f"**Phase 1.5e**: o4-mini 独立思考 ⚠️ エラー")
                
                processing_history.append("**Phase 2**: Gemini 統合フェーズ")
                
                if enable_strict:
                    processing_history.append("**Phase 3**: Gemini 鬼軍曹レビュー")
                    if use_grok_reviewer:
                        if grok_review_status == "success":
                            processing_history.append(f"**Phase 3b**: {SECONDARY_MODEL_NAME} 最終レビュー ✓")
                        else:
                            processing_history.append(f"**Phase 3b**: {SECONDARY_MODEL_NAME} 最終レビュー ⚠️ エラー")
                
                # 処理履歴を最終回答に追加（Grokレビュー成功時は既に含まれているのでスキップ）
                if grok_review_status == "success":
                    # Grokレビューが既に処理履歴を含めているのでそのまま使用
                    final_answer_with_history = final_answer
                else:
                    # Grokレビューがない、またはエラー時のみ処理履歴を追加
                    final_answer_with_history = (
                        "## 📊 処理履歴\n\n"
                        + "\n".join([f"- {item}" for item in processing_history])
                        + "\n\n---\n\n"
                        + final_answer
                    )
                
                # 改行圧縮：3行以上の連続改行を2行に圧縮
                final_answer_with_history = compact_newlines(final_answer_with_history)
                
                # コピーボタン付き回答表示
                import html
                escaped_answer = html.escape(final_answer_with_history)
                answer_id = f"assistant_msg_{len(messages)}"
                
                st.markdown(f"""
<div style="position: relative;">
    <div id="{answer_id}" style="padding-right: 40px; white-space: pre-wrap;">{escaped_answer}</div>
    <button onclick="copyToClipboard('{answer_id}')" style="position: absolute; right: 0; top: 0; background: transparent; border: 1px solid #444; border-radius: 4px; cursor: pointer; padding: 4px 8px; color: #aaa; font-size: 12px;" title="コピー">
        📋
    </button>
</div>
<script>
function copyToClipboard(elementId) {{
    const element = document.getElementById(elementId);
    const text = element.innerText;
    navigator.clipboard.writeText(text).then(() => {{
        const button = event.target;
        button.textContent = '✓';
        setTimeout(() => {{ button.textContent = '📋'; }}, 1000);
    }});
}}
</script>
""", unsafe_allow_html=True)
                
                # ▼▼▼ コストサマリー表示 ▼▼▼
                st.markdown("---")
                st.markdown("## 💰 コストサマリー")
                
                # Claude 4.5 Sonnet のコスト
                claude_cost = 0.0
                if claude45_usage:
                    input_tokens = claude45_usage.get("inputTokens", 0)
                    output_tokens = claude45_usage.get("outputTokens", 0)
                    claude_cost = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
                    st.markdown(f"**Claude 4.5 Sonnet (AWS Bedrock)**")
                    st.markdown(f"- Input: {input_tokens:,} tokens")
                    st.markdown(f"- Output: {output_tokens:,} tokens")
                    st.markdown(f"- コスト: ${claude_cost:.4f}")
                    st.markdown("")
                
                # Gemini のコスト (total_session_cost - claude_cost)
                gemini_cost = st.session_state.session_cost - claude_cost
                if gemini_cost > 0:
                    st.markdown(f"**Gemini (gemini-3-pro-preview)**")
                    st.markdown(f"- コスト: ${gemini_cost:.4f}")
                    st.markdown("")
                
                # 合計
                total_cost = st.session_state.session_cost
                st.markdown(f"**合計セッションコスト**: ${total_cost:.4f}")
                    
                # ▲▲▲ 処理履歴追加ここまで ▲▲▲

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

                # ▼▼▼ Deep Log: 推論プロセスを保存（確実性向上） ▼▼▼
                reasoning_logs = {
                    "phase1_research": research_text if 'research_text' in dir() else None,
                    "phase1_5_meta_questions": questions_text if 'questions_text' in dir() else None,
                    "phase1_5b_secondary": grok_thought if 'grok_thought' in dir() else None,
                    "phase1_5d_claude": claude45_thought if 'claude45_thought' in dir() else None,
                    "phase1_5e_o4mini": o4mini_thought if 'o4mini_thought' in dir() else None,
                    "phase2_draft": draft_answer if 'draft_answer' in dir() else None,
                }
                
                # 情報源URLを抽出
                grounding_sources = []
                if grounding_metadata and hasattr(grounding_metadata, 'grounding_chunks'):
                    for chunk in grounding_metadata.grounding_chunks:
                        if hasattr(chunk, 'web') and hasattr(chunk.web, 'uri'):
                            grounding_sources.append(chunk.web.uri)
                
                messages.append({
                    "role": "model",
                    "content": final_answer_with_history,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "reasoning_logs": reasoning_logs,  # Deep Log
                    "metadata": {
                        "model": model_id,
                        "cost": round(st.session_state.session_cost, 4),
                        "sources": grounding_sources[:10]  # 最大10件
                    }
                })
                # ▲▲▲ Deep Log ここまで ▲▲▲
                update_current_session_messages(messages)

            except Exception as e:
                # 🔥 実行完遂保証: どんなエラーでも必ず回答を生成
                import traceback
                err_text = str(e)
                error_traceback = traceback.format_exc()
                print(f"[ERROR] Main processing failed: {err_text}")
                print(error_traceback)
                
                # エラー時のフォールバック回答を生成
                fallback_answer = ""
                
                if "RESOURCE_EXHAUSTED" in err_text or "429" in err_text:
                    fallback_answer = (
                        "## ⚠️ クォータ制限により処理が中断されました\n\n"
                        "Vertex AI / Gemini のレート制限に達しました。\n\n"
                        "### 対処法:\n"
                        "1. **数分待ってから再試行**してください\n"
                        "2. Google Cloud Console の「Vertex AI → 使用状況」でクォータを確認\n"
                        "3. 必要に応じてクォータ増加をリクエスト\n\n"
                        f"### 質問内容（保存済み）:\n{prompt[:500]}..."
                    )
                elif "NOT_FOUND" in err_text and "Publisher Model" in err_text:
                    fallback_answer = (
                        "## ⚠️ モデルが利用できません\n\n"
                        "指定したモデルがこのプロジェクト / ロケーションでは利用できません。\n\n"
                        "### 対処法:\n"
                        "サイドバーのモデルIDを、`gemini-2.5-pro` または `gemini-3-pro-preview` に変更してお試しください。"
                    )
                else:
                    fallback_answer = (
                        "## ⚠️ 処理中にエラーが発生しました\n\n"
                        f"**エラー内容**: `{err_text[:200]}`\n\n"
                        "### 自動リカバリーを試みています...\n\n"
                        f"### 質問内容（保存済み）:\n{prompt[:500]}...\n\n"
                        "**推奨アクション**: ページをリロードして再試行してください。"
                    )
                
                # フォールバック回答を表示
                st.error(fallback_answer)
                
                # 🔥 重要: エラー時も回答を履歴に保存（次回参照用）
                messages.append({
                    "role": "model",
                    "content": fallback_answer,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "error": True  # エラーフラグ
                })
                update_current_session_messages(messages)
