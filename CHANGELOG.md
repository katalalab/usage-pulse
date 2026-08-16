# Changelog

## Unreleased

### Added
- Repo-local `scripts/verify.sh` for reproducible uv-backed lint, typecheck, security, test, and provider-pin checks.
- `.python-version` to align local and CI Python selection.
- `docs/cleanup-roadmap.md` plus README/docs index links for ongoing README/docs/verifier cleanup tracking.

## [0.1.0] - 2026-06-19

### Added
- `usage-pulse statusline`: tmux status-right 用キャッシュ付きステータス出力
- `usage-pulse summary`: 今日の使用量サマリー表示
- `usage-pulse summary --json`: エージェント/CI 向け機械可読サマリー
- `usage-pulse sync --json` / `--quiet`: hook や自動化向けの非対話出力
- `usage-pulse doctor`: 依存 CLI・provider・state/cache path のローカル診断
- `usage-pulse roi`: モデル別トークン ROI テーブル
- `usage-pulse sync`: エージェントハンドシェイク状態ファイル更新
- `usage-pulse tray`: クロスプラットフォームシステムトレイデーモン (pystray)
- `usage-pulse setup`: インタラクティブセットアップ
- `CcusageProvider`: ccusage daily --json ベースのデータ取得（全 OS 対応、direct ccusage 優先）
- `CodexbarProvider`: codexbar レートウィンドウ取得（Mac、provider 別並列取得）
- `ModelAdvisor`: 使用量ベースのモデル選択推奨
- `ModelROI`: モデル別コスト効率・キャッシュ効率計算
- `Notifier`: OS 別デスクトップ通知（Mac/Linux/WSL/Windows）
- `handshake.py`: AI エージェント向け状態ファイル (`~/.local/state/usage-pulse/current.json`)
- `skills/model-advisor/SKILL.md`: Claude Code Skill
- `providers/VERSION_PINS.json`: プロバイダースキーマのバージョン管理
- GitHub Actions: CI（Mac/Win/Linux × Python 3.11/3.12）
- GitHub Actions: 週次プロバイダー更新チェック

### Fixed
- ccusage の実スキーマ (`period` / `totalCost` / `totalTokens`) に対応し、今日または最新日の行を選択。
- 状態ファイルと tmux キャッシュを原子的に書き込み、読者側の部分読み取りを防止。
- CodexBar の all-provider TTY hang を避け、provider 別の短 timeout 並列取得へ変更。
- Claude Code hook が参照していた `usage-pulse sync --quiet` を実装。
- install scripts のバックアップを timestamp + 最新 5 件保持に変更。
