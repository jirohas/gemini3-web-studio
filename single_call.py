# single_call.py
from dataclasses import dataclass
from typing import List, Tuple

from google import genai
from google.genai import types

MODEL_ID = "gemini-3-pro-preview"

# Vertex のだいたいの料金（短コンテキスト用）
INPUT_PRICE_PER_M = 2.0   # USD / 1M tokens
OUTPUT_PRICE_PER_M = 12.0 # USD / 1M tokens


@dataclass
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        return (
            self.prompt_tokens / 1_000_000 * INPUT_PRICE_PER_M
            + self.output_tokens / 1_000_000 * OUTPUT_PRICE_PER_M
        )


class Gemini3Client:
    def __init__(self):
        # 環境変数:
        #   GOOGLE_GENAI_USE_VERTEXAI=True
        #   GOOGLE_CLOUD_PROJECT=...
        #   GOOGLE_CLOUD_LOCATION=global
        # が設定されていれば Vertex に接続されます。
        self.client = genai.Client()
        self.total_usage = Usage()

    def _update_usage(self, response) -> Usage:
        um = response.usage_metadata
        if not um:
            return Usage()
        usage = Usage(
            prompt_tokens=um.prompt_token_count or 0,
            output_tokens=um.candidates_token_count or 0,
        )
        self.total_usage.prompt_tokens += usage.prompt_tokens
        self.total_usage.output_tokens += usage.output_tokens
        return usage

    def generate_candidates(
        self,
        question: str,
        n_candidates: int = 3,
    ) -> Tuple[List[str], Usage]:
        """同じ質問に対して n 個の候補回答を生成する。"""
        response = self.client.models.generate_content(
            model=MODEL_ID,
            contents=question,
            config=types.GenerateContentConfig(
                # thinking_level は使わず、シンプル設定だけにする
                temperature=1.0,
                candidate_count=n_candidates,
                max_output_tokens=2048,
            ),
        )
        usage = self._update_usage(response)

        answers: List[str] = []
        for cand in response.candidates:
            if cand.content and cand.content.parts:
                text = "".join(p.text or "" for p in cand.content.parts)
                answers.append(text.strip())

        return answers, usage

    def judge_and_aggregate(
        self,
        question: str,
        candidates: List[str],
    ) -> Tuple[str, Usage]:
        """複数候補を渡して、ベスト回答＋理由を 1 回の推論でまとめる。"""
        numbered = "\n\n".join(
            f"候補 {i+1}:\n{ans}" for i, ans in enumerate(candidates)
        )

        judge_prompt = f"""
あなたは厳密で慎重なAIジャッジです。
ユーザーの質問と複数の候補回答が与えられます。

1. 各候補の長所と短所（事実誤認・論理飛躍・日本語として不自然な点など）を簡潔に比較してください。
2. そのうえで、候補どうしの良い部分を統合し、
   「最も正確で一貫性のある最終回答」を日本語でまとめてください。
3. 最終回答では、余計なメタ説明は書かず、ユーザー向けの答えだけを示してください。

[ユーザーの質問]
{question}

[候補回答一覧]
{numbered}

出力フォーマット:
1. 比較結果（簡潔に）
2. 最終回答
""".strip()

        response = self.client.models.generate_content(
            model=MODEL_ID,
            contents=judge_prompt,
            config=types.GenerateContentConfig(
                temperature=1.0,
                max_output_tokens=2048,
            ),
        )
        usage = self._update_usage(response)
        final_answer = response.text.strip()
        return final_answer, usage


def main():
    client = Gemini3Client()

    MONTHLY_BUDGET_USD = 70.0  # ≒ 月1万円前後

    question = "2025年11月28日現在、コアウィーブの株価の見通しを。NVDA GPU/Google TPU問題、マイケル・バリーの問題を踏まえて。"

    # 1. 候補を生成
    candidates, usage_candidates = client.generate_candidates(
        question=question,
        n_candidates=3,
    )

    print("=== 候補回答 ===")
    for i, ans in enumerate(candidates, start=1):
        print(f"\n--- 候補 {i} (先頭だけ) ---")
        print(ans[:400], "...\n")

    print("候補生成のトークン/コスト:", usage_candidates)
    print("  → 約 USD:", usage_candidates.cost_usd)

    # 2. ジャッジ＋統合
    final_answer, usage_judge = client.judge_and_aggregate(
        question=question,
        candidates=candidates,
    )

    print("\n=== 最終統合回答 ===")
    print(final_answer)

    print("\nジャッジのトークン/コスト:", usage_judge)
    print("  → 約 USD:", usage_judge.cost_usd)

    print("\n=== 合計使用量（このスクリプト実行分） ===")
    print("入力トークン合計:", client.total_usage.prompt_tokens)
    print("出力トークン合計:", client.total_usage.output_tokens)
    print("推定コスト合計(USD):", client.total_usage.cost_usd)

    if client.total_usage.cost_usd > MONTHLY_BUDGET_USD:
        print("⚠ このペースだと月予算をオーバーします。")


if __name__ == "__main__":
    main()
