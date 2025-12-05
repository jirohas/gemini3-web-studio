# GitHub App (ChatGPT Codex Connector) での Git 反映手順

このリポジトリのローカルやサーバー上で生成したテスト結果ファイルなどを GitHub に同期したい場合、以下の流れで Codex に依頼できます。

## 0. すでに手元で変更済みの場合の最短依頼例
「手元の変更をそのまま GitHub に上げたい」だけなら、ブランチとコミットメッセージを指定してシンプルに依頼できます。

- 「現在の変更を `feature/test-log` ブランチで `Add testing output log` というメッセージでコミットし、そのブランチを push して PR を作成してください」
- この一言で、ステージ→コミット→push→PR 作成まで Codex がまとめて実行できます。

## 1. ファイルをリポジトリに追加する
1. コマンドでファイルを作成・更新します。
2. `git status` で変更を確認し、コミットに含めたいファイルがステージされていない場合は `git add <path>` を依頼します。

例: `logs/testing_output.txt` を追加したい場合
- 「`logs/testing_output.txt` をステージしてコミットしてください」

## 2. コミットとプッシュを依頼する
コミットメッセージと対象ファイルを明示して依頼すると確実です。

- 「`logs/testing_output.txt` を含めて `Add testing output log` というメッセージでコミットし、`main` ブランチに push してください」
- Codex がサーバー側から GitHub API を利用する場合は、`contents: write` 権限でインストールされたブランチへ push できます。

## 3. Pull Request を作成する
機能追加や修正をレビュー経由で反映したい場合は PR 作成を指示します。

- 「`feature/test-log` ブランチから `main` ブランチ向けに `Add testing output log` というタイトルで PR を作成してください。概要にはテストログの場所と用途を書いてください」
- Codex は `pull_requests: write` 権限を使って PR を作成します。

## 4. PR へのレビューを書いてもらう
PR の変更内容を確認し、承認や差戻しを依頼できます。

- 「PR #123 にレビューコメントを追加し、承認してください」
- 「PR #123 の `logs/testing_output.txt` について、このログがどのテストに対応するか説明するコメントを書いてください」

## 5. 追加の fix commit を push する
レビュー指摘に対応する場合は、修正内容を明示して依頼します。

- 「PR #123 のブランチに、`Fix log file naming` というコミットを追加してください。`logs/testing_output.txt` の名前を `logs/e2e_output.txt` に変更し、README に参照を追記してください」
- Codex は同じブランチにコミットを積み、既存 PR が自動で更新されます。

## 6. 同期できない場合のチェックポイント
- GitHub App (ChatGPT Codex Connector) が該当リポジトリに **インストール** され、必要な権限 (`contents: write`, `pull_requests: write`, `pull_request_reviews: write`) を付与されているか確認してください。
- 保護ブランチに直接 push できない場合は、別ブランチを作成して PR を経由してください。
- CI が生成した大容量アーティファクトは、リポジトリにコミットする代わりにリリースやオブジェクトストレージを検討してください。

## 7. 例: テストファイルを同期したいときの指示テンプレート
```
logs/testing_output.txt をコミットして GitHub に反映してください。
- コミットメッセージ: "Add testing output log"
- ブランチ: feature/test-log（なければ作成）
- そのブランチから main 向けに PR を作ってください。
- PR 本文にログの出力元のテスト名と実行日時を書いてください。
```

このように「何を」「どのブランチに」「どんなメッセージで」反映するかを具体的に伝えると、Codex が GitHub API を通じて確実に同期できます。
