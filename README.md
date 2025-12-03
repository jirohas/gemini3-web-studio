# Gemini 3 Web Studio

マルチモデルAI推論システム - Gemini、Grok、Claude 4.5 Sonnetを統合した高度なリサーチ&回答生成アプリ

## 🚀 機能

- **多層推論システム**: Gemini + Grok + Claude 4.5 Sonnet（Extended Thinking）
- **Google検索統合**: リアルタイム情報取得
- **YouTube分析**: 字幕自動取得
- **画像生成**: Gemini 3 Pro Image
- **コスト追跡**: リアルタイムAPI使用量管理
- **マルチセッション**: 会話履歴管理と分岐機能

## 📋 必要要件

- Python 3.9+
- Streamlit
- Google Cloud Platform (Vertex AI)
- AWS Account (Bedrock)
- OpenRouter API Key (Grok用)

## 🔧 セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/yourusername/gemini3-web-studio.git
cd gemini3-web-studio
```

### 2. 依存関係をインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数の設定

`.streamlit/secrets.toml` を作成（Streamlit Cloud使用時）:

```toml
# アプリケーション認証
APP_PASSWORD = "your-secure-password"
SECRET_TOKEN = "your-secret-token"

# Google Cloud (Vertex AI)
VERTEX_PROJECT = "your-gcp-project-id"
VERTEX_LOCATION = "us-central1"

# AWS Bedrock (Claude 4.5 Sonnet)
AWS_ACCESS_KEY_ID = "your-aws-access-key"
AWS_SECRET_ACCESS_KEY = "your-aws-secret-key"

# OpenRouter (Grok)
OPENROUTER_API_KEY = "your-openrouter-key"

# Puter.com (Claude Opus 4.5 - オプション)
PUTER_USERNAME = "your-puter-username"
PUTER_PASSWORD = "your-puter-password"
```

ローカル開発時は `.env` ファイルを使用:

```bash
cp .env.example .env
# .env を編集して上記の環境変数を設定
```

### 4. Google Cloud認証

```bash
gcloud auth application-default login
```

### 5. AWS Bedrock設定

AWS Console で Claude 4.5 Sonnet のモデルアクセスを有効化:
1. AWS Console → Bedrock → Model access
2. `us.anthropic.claude-sonnet-4-5-20250929-v1:0` を有効化

## 🏃 実行

### ローカル

```bash
streamlit run app.py
```

### Streamlit Cloud

1. [Streamlit Cloud](https://streamlit.io/cloud) にログイン
2. リポジトリを接続
3. Secrets に環境変数を設定
4. デプロイ

## 💰 料金

### Gemini (Google Vertex AI)
- Input: ~$0.30 / 1M tokens
- Output: ~$1.20 / 1M tokens

### Claude 4.5 Sonnet (AWS Bedrock)
- Input: $3.00 / 1M tokens
- Output: $15.00 / 1M tokens

### Grok (OpenRouter)
- 無料版: grok-beta

## 🔒 セキュリティ

### GitHubで公開する際の注意

**絶対にコミットしないファイル**:
- `.streamlit/secrets.toml`
- `.env`
- `usage.json`
- `sessions.json`

`.gitignore` に以下を追加:

```
.streamlit/secrets.toml
.env
usage.json
sessions.json
manual_cost.json
__pycache__/
*.pyc
```

## 📝 使い方

### 多層推論モード

`grok強化(+mz/Az)` > `熟考 (本気MAX)Az` を選択:

1. **Phase 1**: Gemini がGoogle検索で最新情報を収集
2. **Phase 1.5a**: メタ質問を生成
3. **Phase 1.5b**: Grok が独立思考
4. **Phase 1.5d**: Claude 4.5 Sonnet が Extended Thinking で深い推論
5. **Phase 2**: Gemini が全てを統合
6. **Phase 3**: 鬼軍曹レビュー
7. **Phase 3b**: Grok が最終レビュー

## 🎯 主要モード

- **熟考 (本気MAX)Az**: Claude 4.5 + Grok + Gemini 統合
- **熟考 + 鬼軍曹**: 厳格なレビュープロセス
- **通常 (高速)**: Gemini のみで高速回答

## 📊 コスト管理

サイドバーで以下を確認:
- セッションコスト（リアルタイム）
- 手動コスト入力（Google Cloud Console確認用）
- 予算上限設定

## 🛠️ トラブルシューティング

### Claude 4.5 が動かない

1. AWS認証情報を確認
2. Bedrock Model Access を確認
3. リージョンが `us-east-1` か確認

### Gemini エラー

1. `gcloud auth application-default login` を実行
2. Vertex AI APIが有効か確認
3. プロジェクトIDとロケーションを確認

## 📄 ライセンス

MIT License

## 🗺️ ロードマップ（今後の改善予定）

### 現在の完成度: 「優秀な調査員」レベル ✅

- ✅ 4モデル統合（Gemini + Grok + Claude 4.5 + o4-mini）
- ✅ Phase 1.3: Fact/Risk Summary（JSON化）
- ✅ セッション間記憶保持
- ✅ 判断憲法（DECISION_PROFILE）
- ✅ 自信度・比較フレームワーク

### 優先度: 中（実運用で必要性を確認後）

#### 1. Agentic Loop (Deep Research)
- 自律的な再検索・再検証ループ
- 最大ループ回数のガード必須
- コスト暴走リスクに注意
- **実装場所**: Phase 1のリサーチフェーズ

#### 2. Context Caching
- セッション開始時に大量データをキャッシュ
- RAG + Cachingのハイブリッド構成
- ストレージコスト発生
- **実装場所**: セッション初期化時

#### 3. Thought Trace UI
- 思考プロセスの可視化
- 検証可能性の担保
- **実装場所**: 各Phaseのexpander

### 優先度: 低（セキュリティリスク）

#### 4. Code Execution
- サンドボックス必須（E2B等）
- 数値検証・シミュレーション用
- **実装場所**: 新しいPhaseとして追加

### 実装方針

1. **実運用テスト**: 数十問でレイテンシ・コスト・出力品質を確認
2. **痛みメモ**: 「ここで再検索してほしい」等の体験を記録  
3. **段階的実装**: 痛みが見えた箇所から順に実装

## 🤝 貢献

Pull Requestを歓迎します！

## 📧 連絡先

問題があれば GitHub Issues で報告してください。
