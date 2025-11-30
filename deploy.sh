#!/bin/bash

# デプロイ用スクリプト
# 変更をGitHubにプッシュし、Streamlit Cloudの自動更新をトリガーします

echo "🚀 デプロイを開始します..."

# 1. 変更をステージング
git add .

# 2. コミットメッセージの入力（引数がなければデフォルトメッセージ）
if [ -z "$1" ]; then
  COMMIT_MSG="Update: $(date +'%Y-%m-%d %H:%M:%S')"
else
  COMMIT_MSG="$1"
fi

# 3. コミット
git commit -m "$COMMIT_MSG"

# 4. プッシュ
echo "📤 GitHubにプッシュ中..."
git push origin main

echo "✅ デプロイ完了！"
echo "⏳ 数分後に https://jirohas.streamlit.app/ で変更が反映されます。"
