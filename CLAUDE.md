# スーパーマーケットDX

このファイルはチーム共有の Claude Code 向け指示書(Gitで管理)。
個人だけに適用したい指示は `CLAUDE.local.md` に書く(Git管理外)。

## 概要
スーパーマーケットのDXを目的とした研究室プロジェクト。
気象・イベント連動の AI需要予測と、生鮮の発注提案・惣菜の製造計画を行うシステムプロトタイプを開発する。
複数人で共同開発する。

## 設計書(実装の正)
実装の前に `設計書/` の該当箇所を確認し、設計書と食い違う実装をしないこと。
設計書と合わない点や設計書に書かれていない判断が必要になったら、勝手に決めずに確認する。

| 文書 | 何を正とするか |
|---|---|
| `設計書/要件定義書.md` | 機能要件(F-xx)、業務ルール、ヒアリング確認項目 |
| `設計書/基本設計書.md` | システム構成、部品の分け方 |
| `設計書/詳細設計書.md` | モジュールの役割、API、テーブル、計算式、設定項目、テスト方針 |
| `設計書/技術スタック・ファイル構成.md` | 使う技術とバージョン、どこに何を置くか、実装の順序 |

## 技術スタック(要点)
詳細とバージョンは `設計書/技術スタック・ファイル構成.md` を参照。

- 本体: Python 3.11 / FastAPI / SQLAlchemy 2.0 + Alembic / Pydantic 2 + pydantic-settings / httpx / argon2-cffi / pytest
- 予測モデル作成: pandas 2・numpy / scikit-learn 1.5 系・LightGBM 4 系 / joblib / Jupyter Notebook
- 画面: Node.js 24 / React 18 + TypeScript 5 / Vite 5 / React Router 7 / Axios / CSS Modules / Vitest + React Testing Library
- DB・インフラ: PostgreSQL 16 / Docker Compose / 研究室AWSの EC2 1台(RDS は使わない)/ Caddy で HTTPS
- 気象データ: Open-Meteo(APIキー不要)

## ディレクトリ構成
### リポジトリのルート
`.gitignore` はルート直下を一括除外し、次のものだけをGit管理の対象にしている。

- `app/` — システム一式
- `設計書/` — 要件定義書・基本設計書・詳細設計書・技術スタック
- `テスト/` — テスト項目一覧(単体テスト・結合テストの項目と自動テストの有無)
- `提案資料/` — 店舗向けの提案書・システムマニュアル
- `.claude/settings.json` — Claude Code のチーム共有設定
- `CLAUDE.md`, `.gitignore`

ルート直下に新しいファイルやフォルダを作ってコミットしたいときは、`.gitignore` に `!/<名前>` を追加すること。追加しないとGitに載らない。

### app/ 配下
| フォルダ | 内容 |
|---|---|
| `app/features/` | 特徴量作成の共通パッケージ `smdx_features`(本体とモデル作成の両方が使う) |
| `app/backend/` | 本体 `smdx_api`(FastAPI)。モジュールは api, auth, imports, weather_client, predictor, order_calc, proposals, settings, db, commands |
| `app/model_training/` | モデル作成用プロジェクト `smdx_training`(学習・評価・バックテスト。本体とは別に実行) |
| `app/sample_data/` | 研究用サンプルデータ生成 `smdx_sample` |
| `app/frontend/` | 画面(React) |
| `app/infra/` | Docker Compose(開発用と評価環境用)、Dockerfile、Caddyfile、AWS構築手順 |
| `app/constraints.txt` | Python ライブラリの共通バージョン固定 |

## 実装上の決まりごと
- 実装は `設計書/技術スタック・ファイル構成.md` の「実装の進め方」の段階順に進め、各段階で動作する状態を保つ。
- Python ライブラリのバージョンは `app/constraints.txt` で固定し、本体・モデル作成・サンプル生成で同じものを使う(モデルファイルを読み込めるようにするため)。
- `order_calc` は DB に依存しない純粋な計算として書く(`model_training` のバックテストからも使うため)。
- DB 構造の変更は必ず Alembic のマイグレーションで行う。起動時の自動テーブル作成は使わない。
- 状態を変える API(POST/PUT/PATCH/DELETE)は、ヘッダ `X-Requested-With: smdx` が無い要求を 403 で拒否する(CSRF対策)。画面側は Axios の共通設定でこのヘッダを付ける。
- 設定値は環境変数(pydantic-settings)と DB の設定値で扱い、コードに直書きしない。項目は詳細設計書「設定項目」に従う。
- テストでは気象API(Open-Meteo)を実際に呼ばず、模擬応答を使う。

## Git に含めないもの
`.gitignore` で除外しているが、ファイルを置く場所を間違えないよう注意する。

- `.env`(`.env.example` のみコミットする。設定項目を増やしたら `.env.example` も更新する)
- モデルファイル(`app/backend/models/*.joblib`、`app/model_training/output/`)
- 生成したサンプルデータ(`app/sample_data/output/`)
- 店舗の実データ(POS・在庫・廃棄のCSV)。機密情報のため、リポジトリ内に置かず研究室AWS内でのみ扱う

## 開発ルール
- ブランチ: `master` に直接コミット・pushしない。作業ごとにブランチを切り、プルリクエストでマージする。
- コミットメッセージ: `<種別>: <日本語の要約>` の形式。
  - 種別: `feat`(機能追加), `fix`(バグ修正), `docs`(文書), `refactor`, `test`, `chore`(設定・雑務)
- テスト: プルリクエストを出す前に、変更した範囲のテスト(pytest / Vitest)を実行して通ることを確認する。
- 設計変更: 実装で設計を変える必要が出たら、先に `設計書/` を改訂する(改訂履歴も更新する)。
- 言語: コード中のコメント、ドキュメント、コミットメッセージは日本語で書く。識別子は英語。

## ファイル配置ルール
作成・保存するファイルは、原則としてすべてこのプロジェクトのルート配下に置くこと。
プロジェクトのディレクトリ外には保存しない。
