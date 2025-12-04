"""
Phase C: Question Router - Automatic Pipeline Selection
Analyzes user questions and routes to appropriate pipeline configuration.
"""

import json
import re
from typing import Dict, Any, Optional


def analyze_question_for_routing(
    client,
    user_question: str,
    user_profile: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Analyze user question to determine optimal pipeline configuration.
    
    Args:
        client: Gemini client
        user_question: User's question text
        user_profile: Optional user profile for context
    
    Returns:
        Classification dict with domain, complexity, risk_level, etc.
    """
    try:
        from google.genai import types
        
        # Safe default for fallback
        safe_default = {
            "domain": "general",
            "complexity": "medium",
            "risk_level": "medium",
            "needs_research": True,
            "needs_cross_check": False,
            "needs_x_search": False,
            "notes": "Default (classification not performed)"
        }
        
        # Build analysis prompt
        profile_context = ""
        if user_profile and user_profile.get("interests"):
            profile_context = f"\nユーザーの興味: {', '.join(user_profile['interests'][:3])}"
        
        analysis_prompt = f"""以下のユーザー質問を分析し、JSON形式**のみ**を出力してください。

【質問】
{user_question}{profile_context}

【タスク】
以下のJSON形式で出力（説明文・コードブロック不要）:

{{
  "domain": "domain_type",
  "complexity": "low|medium|high",
  "risk_level": "low|medium|high",
  "needs_research": true|false,
  "needs_cross_check": true|false,
  "needs_x_search": true|false,
  "notes": "簡潔なメモ"
}}

【判定基準】
**domain** (質問ドメイン):
- "medical": 医療・健康・医薬品に関する相談
- "legal": 法律・規制・権利に関する相談
- "finance": 投資・金融商品・税金・資産運用
- "coding": プログラミング・技術・開発
- "product": 製品比較・購入相談・レビュー
- "planning": 事業計画・戦略立案・意思決定
- "chitchat": 雑談・簡単なHow To・一般知識
- "news": ニュース・時事・トレンド
- "general": その他一般的な質問

**complexity** (複雑度):
- "low": 単純な事実確認・定義質問・基本的なHow To
- "medium": 比較検討・分析・中程度の調査が必要
- "high": 多面的検討・長期影響分析・深い洞察が必要

**risk_level** (リスクレベル = 誤情報の影響度):
- "high": 医療判断・法的決定・投資判断・危険行為など、誤情報が重大な影響
- "medium": 業務判断・プロダクト選定・計画立案など
- "low": 一般知識・雑談・エンタメ・軽いアドバイス

**needs_research**: Web検索・複数ソースが必要ならtrue
**needs_cross_check**: 複数モデルでのクロスチェックが望ましいならtrue  
**needs_x_search**: X/Twitter検索が有効そうならtrue（ニュース/トレンド系）

**notes**: 判定理由を1-2行で
"""

        # Call gemini-2.0-flash (lightweight)
        config = types.GenerateContentConfig(
            temperature=0.1,  # Low temperature for consistent classification
            max_output_tokens=512,
            response_mime_type="application/json"
        )
        
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[{"role": "user", "parts": [{"text": analysis_prompt}]}],
            config=config
        )
        
        # Extract text
        result_text = ""
        if hasattr(response, 'text'):
            result_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            parts = response.candidates[0].content.parts
            result_text = "".join([p.text for p in parts if hasattr(p, 'text')])
        
        if not result_text:
            print("[DEBUG] analyze_question_for_routing: No text in response")
            return safe_default
        
        # Remove code blocks if present
        result_text = re.sub(r'```json\s*|\s*```', '', result_text.strip())
        
        # Parse JSON
        classification = json.loads(result_text)
        
        # Validate and normalize
        classification.setdefault("domain", "general")
        classification.setdefault("complexity", "medium")
        classification.setdefault("risk_level", "medium")
        classification.setdefault("needs_research", True)
        classification.setdefault("needs_cross_check", False)
        classification.setdefault("needs_x_search", False)
        classification.setdefault("notes", "")
        
        # Normalize enum values
        valid_complexity = {"low", "medium", "high"}
        if classification["complexity"] not in valid_complexity:
            classification["complexity"] = "medium"
        
        valid_risk = {"low", "medium", "high"}
        if classification["risk_level"] not in valid_risk:
            classification["risk_level"] = "medium"
        
        print(f"[DEBUG] Question classified: {classification}")
        return classification
        
    except json.JSONDecodeError as e:
        print(f"[DEBUG] analyze_question_for_routing: JSON parse error: {e}")
        return safe_default
    except Exception as e:
        print(f"[DEBUG] analyze_question_for_routing: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return safe_default


def route_question_to_pipeline(classification: Dict[str, Any]) -> Dict[str, Any]:
    """
    Determine pipeline configuration based on question classification.
    
    Args:
        classification: Output from analyze_question_for_routing()
    
    Returns:
        Pipeline configuration dict with flags and routing reason
    """
    risk = classification.get("risk_level", "medium")
    complexity = classification.get("complexity", "medium")
    domain = classification.get("domain", "general")
    needs_research = classification.get("needs_research", True)
    needs_cross = classification.get("needs_cross_check", False)
    needs_x = classification.get("needs_x_search", False)
    
    # Default configuration
    pipeline = {
        "mode_name": "medium",
        "enable_research": False,
        "enable_meta": False,
        "enable_strict": False,
        "use_search": True,  # User toggle
        "candidate_count": 1,
        "use_grok": False,
        "use_claude": False,
        "use_o4_mini": False,
        "use_x_search": False,
        "routing_reason": ""
    }
    
    # High-risk domains (medical, legal, finance) → Full verification
    if risk == "high" or domain in ["medical", "legal", "finance"]:
        pipeline.update({
            "mode_name": "full_verify",
            "enable_research": True,
            "enable_meta": True,
            "enable_strict": True,
            "use_grok": True,
            "use_claude": True,
            "use_o4_mini": True,
            "routing_reason": f"高リスク質問（{domain}, risk={risk}）→ フル検証パイプライン（research+meta+strict+全モデル）"
        })
    
    # High complexity or cross-check needed → Research + Meta
    elif complexity == "high" or needs_cross:
        pipeline.update({
            "mode_name": "research_meta",
            "enable_research": True,
            "enable_meta": True,
            "enable_strict": False,
            "use_grok": True,
            "use_claude": complexity == "high",  # Claude only for high complexity
            "use_o4_mini": False,
            "routing_reason": f"高複雑度（{complexity}）→ リサーチ+メタ質問パイプライン"
        })
    
    # Medium complexity with research needs → Basic research
    elif complexity == "medium" or needs_research:
        pipeline.update({
            "mode_name": "research",
            "enable_research": True,
            "enable_meta": False,
            "enable_strict": False,
            "use_grok": False,
            "routing_reason": f"中複雑度（{complexity}）→ 基本リサーチパイプライン"
        })
    
    # Low complexity + low risk → Lightweight (no research)
    else:  # complexity == "low" and risk == "low"
        pipeline.update({
            "mode_name": "light",
            "enable_research": False,
            "enable_meta": False,
            "enable_strict": False,
            "routing_reason": f"低複雑度・低リスク（{complexity}/{risk}）→ 軽量モード（コスト節約）"
        })
    
    # X/Twitter search flag
    if needs_x or domain == "news":
        pipeline["use_x_search"] = True
        pipeline["use_grok"] = True  # Grok needed for X search
        pipeline["routing_reason"] += " + X検索強化"
    
    print(f"[DEBUG] Routed to: {pipeline['mode_name']} - {pipeline['routing_reason']}")
    return pipeline
