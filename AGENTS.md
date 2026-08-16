# usage-pulse Agent Rules

Global baseline: `~/work/agent-context/AGENTS.MD`.

Repo delta:

- Mac / Windows / Linux 対応の AI ツール使用量モニター（tmux ステータスライン・システムトレイ・通知統合）の OSS。本体は `src/usage_pulse/`、プロバイダ定義は `providers/`。公開 OSS 前提でプロバイダ秘密値を持ち込まない。
- 依存は `uv`。セットアップは `uv sync --dev --frozen`（Python 3.11+、ローカル既定は `.python-version`）。
- 検証は `bash scripts/verify.sh ci`。エントリポイントは `usage-pulse`(`usage_pulse.cli:main`)。
- 外部ツールのバージョンは `providers/VERSION_PINS.json` でピン留め。CI はピンと最新を突き合わせる。ピン更新は意図的に行い、勝手に追従させない。
- `CHANGELOG.md` / `CONTRIBUTING.md` / `LICENSE` を持つ公開プロジェクト。ユーザー向け変更は `CHANGELOG.md` に追記する。
