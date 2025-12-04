"""
JSON Intermediate Representation (IR) for research results.
Phase B: Structured data extraction from Phase 1 research.
"""

from typing import TypedDict, Literal, List, Optional
from datetime import datetime
import json


# ========================================
# Type Definitions
# ========================================

class FactIR(TypedDict):
    """Individual fact extracted from research"""
    statement: str  # Fact content
    source: Literal["web", "youtube", "model"]  # Source type
    source_detail: str  # Specific URL or model name
    date: Optional[str]  # Information date (YYYY-MM-DD format)
    confidence: Literal["high", "medium", "low", "unknown"]  # Confidence level


class OptionIR(TypedDict):
    """Option or alternative approach"""
    name: str  # Option name (e.g., "Plan A: On-premise migration")
    pros: List[str]  # Advantages
    cons: List[str]  # Disadvantages
    conditions: List[str]  # Conditions for success
    estimated_cost: Optional[str]  # Cost estimate if available


class RiskIR(TypedDict):
    """Risk identified during research"""
    statement: str  # Risk description
    severity: Literal["high", "medium", "low", "unknown"]  # Severity level
    timeframe: Literal["short", "medium", "long", "unknown"]  # Impact timeframe
    mitigation: Optional[str]  # Mitigation strategy if available


class UnknownIR(TypedDict):
    """Unknown or unclear point"""
    question: str  # Unknown question
    why_unknown: Literal[
        "insufficient_data",  # Insufficient data
        "conflicting_data",  # Conflicting data
        "grey_area",  # Grey area (legal, etc.)
        "future_dependent",  # Future-dependent
        "unknown"  # Unknown reason
    ]
    impact: Literal["high", "medium", "low", "unknown"]  # Impact of not knowing


class ResearchMetadataIR(TypedDict):
    """Metadata about the research process"""
    question: str  # Original user question
    language: str  # Language (e.g., "ja", "en")
    created_at: str  # ISO 8601 timestamp
    models: List[str]  # Models used in research
    sources_count: int  # Number of sources consulted
    search_queries: List[str]  # Search queries used


class ResearchIR(TypedDict):
    """Top-level research intermediate representation"""
    facts: List[FactIR]
    options: List[OptionIR]
    risks: List[RiskIR]
    unknowns: List[UnknownIR]
    metadata: ResearchMetadataIR


# ========================================
# Validation and Normalization
# ========================================

def validate_research_ir(ir: dict) -> tuple[ResearchIR, List[str]]:
    """
    Validate and normalize ResearchIR schema.
    
    Args:
        ir: Raw dictionary to validate
    
    Returns:
        Tuple of (normalized_ir, warnings)
        - normalized_ir: Validated and normalized ResearchIR
        - warnings: List of warning messages
    """
    warnings: List[str] = []
    
    # Ensure top-level keys exist
    normalized: ResearchIR = {
        "facts": ir.get("facts", []),
        "options": ir.get("options", []),
        "risks": ir.get("risks", []),
        "unknowns": ir.get("unknowns", []),
        "metadata": ir.get("metadata", {})
    }
    
    # Normalize facts
    normalized_facts: List[FactIR] = []
    for i, fact in enumerate(normalized["facts"]):
        if not isinstance(fact, dict):
            warnings.append(f"Fact {i} is not a dict, skipping")
            continue
        
        normalized_fact: FactIR = {
            "statement": str(fact.get("statement", "")),
            "source": fact.get("source", "model") if fact.get("source") in ["web", "youtube", "model"] else "model",
            "source_detail": str(fact.get("source_detail", "")),
            "date": fact.get("date"),
            "confidence": fact.get("confidence", "unknown") if fact.get("confidence") in ["high", "medium", "low", "unknown"] else "unknown"
        }
        
        if not normalized_fact["statement"]:
            warnings.append(f"Fact {i} has empty statement")
        
        normalized_facts.append(normalized_fact)
    
    normalized["facts"] = normalized_facts
    
    # Normalize options
    normalized_options: List[OptionIR] = []
    for i, option in enumerate(normalized["options"]):
        if not isinstance(option, dict):
            warnings.append(f"Option {i} is not a dict, skipping")
            continue
        
        normalized_option: OptionIR = {
            "name": str(option.get("name", f"Option {i+1}")),
            "pros": [str(p) for p in option.get("pros", [])],
"cons": [str(c) for c in option.get("cons", [])],
            "conditions": [str(c) for c in option.get("conditions", [])],
            "estimated_cost": option.get("estimated_cost")
        }
        
        normalized_options.append(normalized_option)
    
    normalized["options"] = normalized_options
    
    # Normalize risks
    normalized_risks: List[RiskIR] = []
    for i, risk in enumerate(normalized["risks"]):
        if not isinstance(risk, dict):
            warnings.append(f"Risk {i} is not a dict, skipping")
            continue
        
        normalized_risk: RiskIR = {
            "statement": str(risk.get("statement", "")),
            "severity": risk.get("severity", "unknown") if risk.get("severity") in ["high", "medium", "low", "unknown"] else "unknown",
            "timeframe": risk.get("timeframe", "unknown") if risk.get("timeframe") in ["short", "medium", "long", "unknown"] else "unknown",
            "mitigation": risk.get("mitigation")
        }
        
        if not normalized_risk["statement"]:
            warnings.append(f"Risk {i} has empty statement")
        
        normalized_risks.append(normalized_risk)
    
    normalized["risks"] = normalized_risks
    
    # Normalize unknowns
    normalized_unknowns: List[UnknownIR] = []
    for i, unknown in enumerate(normalized["unknowns"]):
        if not isinstance(unknown, dict):
            warnings.append(f"Unknown {i} is not a dict, skipping")
            continue
        
        valid_reasons = ["insufficient_data", "conflicting_data", "grey_area", "future_dependent", "unknown"]
        normalized_unknown: UnknownIR = {
            "question": str(unknown.get("question", "")),
            "why_unknown": unknown.get("why_unknown", "unknown") if unknown.get("why_unknown") in valid_reasons else "unknown",
            "impact": unknown.get("impact", "unknown") if unknown.get("impact") in ["high", "medium", "low", "unknown"] else "unknown"
        }
        
        if not normalized_unknown["question"]:
            warnings.append(f"Unknown {i} has empty question")
        
        normalized_unknowns.append(normalized_unknown)
    
    normalized["unknowns"] = normalized_unknowns
    
    # Normalize metadata
    metadata = normalized["metadata"]
    normalized_metadata: ResearchMetadataIR = {
        "question": str(metadata.get("question", "")),
        "language": str(metadata.get("language", "ja")),
        "created_at": str(metadata.get("created_at", datetime.now().isoformat())),
        "models": [str(m) for m in metadata.get("models", [])],
        "sources_count": int(metadata.get("sources_count", 0)),
        "search_queries": [str(q) for q in metadata.get("search_queries", [])]
    }
    
    normalized["metadata"] = normalized_metadata
    
    # Final validation
    if not normalized["facts"]:
        warnings.append("No facts extracted (empty facts list)")
    
    return normalized, warnings


# ========================================
# Synthesis Prompt Builder
# ========================================

def build_synthesis_prompt_from_ir(ir: ResearchIR, original_question: str) -> str:
    """
    Build Phase 2 synthesis prompt from JSON IR.
    
    Args:
        ir: Structured research IR
        original_question: Original user question
    
    Returns:
        Formatted prompt string for Phase 2 integration
    """
    
    # Facts section
    facts_section = "【確認された事実】\n"
    if ir["facts"]:
        confidence_marks = {
            "high": "✓",
            "medium": "△",
            "low": "?",
            "unknown": "·"
        }
        
        for fact in ir["facts"]:
            mark = confidence_marks.get(fact["confidence"], "·")
            facts_section += f"{mark} {fact['statement']}\n"
            if fact["source_detail"]:
                facts_section += f"  出典: {fact['source_detail']} ({fact['confidence']}信頼度)\n"
            if fact.get("date"):
                facts_section += f"  日付: {fact['date']}\n"
    else:
        facts_section += "（抽出された事実なし）\n"
    
    # Options section
    options_section = ""
    if ir["options"]:
        options_section = "\n【検討すべき選択肢】\n"
        for opt in ir["options"]:
            options_section += f"\n## {opt['name']}\n"
            if opt["pros"]:
                options_section += f"メリット: {', '.join(opt['pros'])}\n"
            if opt["cons"]:
                options_section += f"デメリット: {', '.join(opt['cons'])}\n"
            if opt["conditions"]:
                options_section += f"成立条件: {', '.join(opt['conditions'])}\n"
            if opt.get("estimated_cost"):
                options_section += f"コスト見積もり: {opt['estimated_cost']}\n"
    
    # Risks section
    risks_section = ""
    if ir["risks"]:
        risks_section = "\n【特定されたリスク】\n"
        severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢", "unknown": "⚪"}
        
        # Sort by severity
        severity_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
        sorted_risks = sorted(ir["risks"], key=lambda x: severity_order.get(x["severity"], 3))
        
        for risk in sorted_risks:
            emoji = severity_emoji.get(risk["severity"], "⚪")
            timeframe_ja = {"short": "短期", "medium": "中期", "long": "長期", "unknown": "不明"}
            timeframe = timeframe_ja.get(risk["timeframe"], "不明")
            
            risks_section += f"{emoji} {risk['statement']} ({timeframe})\n"
            if risk.get("mitigation"):
                risks_section += f"  対策: {risk['mitigation']}\n"
    
    # Unknowns section
    unknowns_section = ""
    if ir["unknowns"]:
        unknowns_section = "\n【不明点・要確認事項】\n"
        reason_map = {
            "insufficient_data": "データ不足",
            "conflicting_data": "情報が矛盾",
            "grey_area": "グレーゾーン",
            "future_dependent": "将来の状況次第",
            "unknown": "理由不明"
        }
        
        for unknown in ir["unknowns"]:
            reason = reason_map.get(unknown["why_unknown"], "理由不明")
            unknowns_section += f"? {unknown['question']}\n"
            unknowns_section += f"  理由: {reason}\n"
    
    # Metadata section
    metadata_section = f"""
【調査メタデータ】
- 調査日時: {ir['metadata']['created_at']}
- 情報源数: {ir['metadata']['sources_count']}
- 使用モデル: {', '.join(ir['metadata']['models'])}
"""
    
    # Final synthesis prompt
    synthesis_prompt = f"""
ユーザーの質問:
{original_question}

{facts_section}
{options_section}
{risks_section}
{unknowns_section}
{metadata_section}

【統合タスク】
上記の構造化データを元に、最終回答を作成してください。

**重要な制約:**
1. 「✓ 高信頼度」の事実は強く主張できます
2. 「△ 中信頼度」「? 低信頼度」の事実は「〜とされる」「〜可能性がある」と弱めてください
3. 「不明点」に該当する事項は、勝手に埋めずに「現時点では不明」と明記してください
4. リスクは深刻度順（🔴→🟡→🟢）に言及してください
5. 出典情報がある場合は適宜参照してください
"""
    
    return synthesis_prompt
