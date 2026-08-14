# usage-pulse

**Mac / Windows / Linux 対応 AI ツール使用量モニター**

tmux ステータスライン・OS ネイティブシステムトレイ・通知・モデル選択補助を統合した OSS ツール。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

---

## 概要

| 機能 | Mac | Windows | Linux |
|------|-----|---------|-------|
| tmux ステータスライン | ✅ | ✅ (WSL2) | ✅ |
| システムトレイ | ✅ | ✅ | ✅ |
| デスクトップ通知 | ✅ osascript | ✅ PowerShell | ✅ notify-send |
| codexbar 連携 | ✅ (TTY あり) | ❌ | ❌ |
| Claude Code フック | ✅ | ✅ | ✅ |
| モデル選択 Skill | ✅ | ✅ | ✅ |
| AI runtime/config 監査 | ✅ | ✅ | ✅ |

---

## インストール

### 前提条件

- Python 3.11+
- [ccusage](https://github.com/ryoppippi/ccusage) (`bun add -g ccusage`)
- または `ccusage` CLI が PATH に直接入っていること
- [codexbar](https://codexbar.app/) (macOS のみ・オプション)
- tmux 3.0+

### uv でインストール（推奨）

```bash
git clone https://github.com/<your-org>/usage-pulse ~/work/usage-pulse
cd ~/work/usage-pulse
uv sync --dev --frozen
```

### 検証

CI と同じ検証はリポジトリルートで実行します。

```bash
bash scripts/verify.sh ci
```

依存同期なしでプロバイダー pin メタデータだけを確認する場合:

```bash
bash scripts/verify.sh providers-static
```

### tmux ステータスライン

```bash
./scripts/install-tmux.sh
```

### Claude Code フック統合

```bash
./scripts/install-claude-hook.sh
```

---

## コマンド

```bash
# tmux ステータスライン文字列を出力（キャッシュあり）
usage-pulse statusline

# システムトレイデーモン起動
usage-pulse tray

# 今日の使用量サマリー表示
usage-pulse summary

# エージェント/CI 向け JSON サマリー
usage-pulse summary --json

# CodexBar の provider 別 rate window を表示
usage-pulse rates

# モデル別トークン ROI 表示
usage-pulse roi

# 使用量状態ファイルを更新（エージェントハンドシェイク）
usage-pulse sync
usage-pulse sync --json
usage-pulse sync --quiet

# 設定補助（インタラクティブ）
usage-pulse setup

# ローカル診断（依存 CLI / provider / state / cache）
usage-pulse doctor
usage-pulse doctor --json

# AI CLI の実行プロセス・安全な設定要約・トークン効率を監査
usage-pulse audit
usage-pulse audit --json
usage-pulse audit --json --skip-live

# SSH 接続先で audit JSON を集約
usage-pulse fleet-audit --host home-mac-main --host nicolas2025 --json
```

---

## モデル選択 Skill

Claude Code に Skill として組み込むことで、現在の使用量に基づくモデル選択補助が使えます。

```bash
# Skill をインストール
./scripts/install-skill.sh
```

インストール後、Claude Code で `/model-advisor` を実行するとリアルタイムの使用量とコスト予測に基づいたモデル推奨が得られます。

`scripts/install-claude-hook.sh` は `usage-pulse sync --quiet` を PostToolUse hook として登録します。設定ファイル変更時のバックアップは `*.usage-pulse.bak.<timestamp>` 形式で作成し、既定で最新 5 件だけ保持します。保持数は `USAGE_PULSE_BACKUP_KEEP` で変更できます。

---

## アーキテクチャ

```
usage-pulse
├── providers/          データ取得層
│   ├── ccusage.py      ccusage daily --json (全 OS 共通)
│   └── codexbar.py     codexbar usage --json (Mac TTY あり時のみ)
├── audit.py            AI CLI / 設定 / プロセス / tmux / 使用量監査
├── display/            表示層
│   ├── tmux.py         tmux status-right 文字列
│   ├── tray.py         pystray システムトレイ (Win/Linux)
│   └── notify.py       OS 別デスクトップ通知
├── analysis/           分析層
│   ├── roi.py          モデル別トークン ROI
│   └── advisor.py      使用量ベースモデル選択推奨
└── handshake.py        エージェント向け状態ファイル出力
```

### バッテリー効率設計

- tmux ステータスラインはキャッシュを即時返し、更新処理をバックグラウンド化
- ccusage は実スキーマ (`period` / `totalCost` / `totalTokens`) を検証して今日または最新日の行を選択
- CodexBar rate window は provider 別に並列取得し、遅い provider は短い timeout で切り離し
- 共有状態ファイルと tmux キャッシュは原子的に置換し、読者側に部分書き込みを見せない
- `audit` は設定ファイルの秘密値を出さず、モデル名・sandbox/approval・hook有無など安全なホワイトリストだけを要約
- `audit` は `ccusage` 由来のモデル別 cost/output/cache 効率、AI 関連プロセス、tmux ペイン数、load average からボトルネック候補を JSON 化

CodexBar の timeout は `USAGE_PULSE_CODEXBAR_TIMEOUT` で調整できます（既定: 4 秒）。

---

## エージェントハンドシェイク

`usage-pulse sync` は `~/.local/state/usage-pulse/current.json` を更新します。  
AI エージェントはこのファイルを読んで現在の使用量状況を把握できます。

```json
{
  "updated_at": "2026-06-19T10:00:00Z",
  "today": {
    "cost_usd": 12.50,
    "tokens": 2200000,
    "top_models": ["claude-sonnet-4-6", "gpt-5.5"]
  },
  "rate_windows": {
    "claude_5min_pct": 22,
    "claude_weekly_pct": 35
  },
  "recommendation": {
    "model": "claude-haiku-4-5",
    "reason": "claude_5min_pct=22% — sonnet/opus は残量十分"
  }
}
```

---

## アップデート体制

各プロバイダーの仕様変更を追いかけるための仕組みを用意しています。

- `providers/VERSION_PINS.json`: 各ツールの対応バージョンを記録
- `scripts/check-provider-updates.sh`: ccusage/codexbar の最新版とスキーマ変更を確認
- GitHub Actions: 週次で各プロバイダーの CHANGELOG を確認し差分を Issue 登録

README/docs/verifier の継続整備方針は [`docs/cleanup-roadmap.md`](./docs/cleanup-roadmap.md)、現在の再現性・CI 境界は [`docs/current-state.md`](./docs/current-state.md) に記録します。

---

## 参考・謝辞

このプロジェクトは以下のツールのコンセプトとデータソース設計から多くを学んでいます:

- **[ccusage](https://github.com/ryoppippi/ccusage)** by ryoppippi — Claude Code / Codex CLI の使用量を集計する OSS ツール。MIT License。usage-pulse の ccusage プロバイダーは `ccusage daily --json` API を利用しています。
- **[CodexBar](https://codexbar.app/)** by steipete — macOS メニューバー向け Codex/Claude 使用量モニター。usage-pulse の Mac 統合は codexbar CLI を補完的に利用しています。

バグ報告・機能要望は GitHub Issues へ。プルリクエスト歓迎します。

---

## ライセンス

MIT License — 詳細は [LICENSE](./LICENSE) を参照してください。
