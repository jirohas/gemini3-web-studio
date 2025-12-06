# Gemini 3 Web Studio

マルチモデルAI推論システム - Gemini 3 Pro + Claude 4.5 + o4-mini + OpenRouter無料モデルを統合した高度なリサーチ＆回答生成アプリ

## 🚀 特徴

### 多層推論システム (Phase B)

- **Phase 1**: Gemini リサーチ (Google Search)
- **Phase 1.3**: JSON IR 抽出 (facts/risks/options/unknowns)
- **Phase 1.5**: マルチモデル並列思考 (OpenRouter無料枠 + Claude 4.5 + o4-mini)
- **Phase 2**: Gemini 統合 + Structured CoT
- **Phase 3**: 鬼軍曹レビュー + Devil's Advocate

### OpenRouter 無料モデル枠

OpenRouterでは期間限定で無料モデルが提供されています。現在は **Amazon Nova 2 Lite** を使用していますが、キャンペーン終了時には別の無料モデルに切り替わる場合があります。

## 🔧 セットアップ

```bash
git clone https://github.com/jirohas/gemini3-web-studio.git
cd gemini3-web-studio
pip install -r requirements.txt
```

`.streamlit/secrets.toml` を作成:

```toml
APP_PASSWORD = "your-password"
VERTEX_PROJECT = "your-gcp-project-id"
VERTEX_LOCATION = "us-central1"

# オプション
AWS_ACCESS_KEY_ID = "your-aws-key"
AWS_SECRET_ACCESS_KEY = "your-aws-secret"
OPENROUTER_API_KEY = "your-openrouter-key"
GITHUB_TOKEN = "your-github-token"
```

## 🏃 実行

```bash
streamlit run app.py
```

## 🎯 モード

| モード | 説明 | コスト |
|--------|------|--------|
| 熟考 (本気MAX)ms/Az | 全モデル統合 | 高 |
| 熟考 + 鬼軍曹 | Gemini + レビュー | 中 |
| β1. 通常 (高速) | Gemini単体 | 低 |

## 📄 ライセンス

MIT License
