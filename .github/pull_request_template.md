## 概要
<!-- 何を・なぜ変えたか。関係する機能要件(F-xx)や設計書の節 -->

## 変更内容
-

## 確認したこと
<!-- 実行したコマンドと結果(件数)を書く。当てはまらない項目は消さずに「対象外」と書く -->
- [ ] 本体の pytest を **TEST_DATABASE_URL を付けて** 実行し、失敗 0 件・DB 試験のスキップ 0 件(`TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/smdx_test .venv/Scripts/python -m pytest backend/tests -q`)
- [ ] 変更した範囲の pytest(features / sample_data / model_training)
- [ ] 画面を変えた場合は Vitest(`npx vitest run`)と型チェック(`npx tsc --noEmit`)
- [ ] `constraints.txt`・`pyproject.toml`・`package.json`・Dockerfile・Compose を変えた場合は `docker compose up -d --build` で起動できる
- [ ] DB 構造を変えた場合は Alembic のマイグレーションを追加した(`test_migrations.py` が通る)
- [ ] 設計を変えた場合は先に `設計書/` を改訂し、改訂履歴を更新した
- [ ] 設定項目を増やした場合は `.env.example` を更新した

## レビューで見てほしい点
