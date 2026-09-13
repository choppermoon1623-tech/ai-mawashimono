# AIの回し者 バックナンバー

登別中学校 教務主任・三浦のAI通信「AIの回し者」を、表紙から選んで読めるページ。

- 公開: https://choppermoon1623-tech.github.io/ai-mawashimono/
- 元データ: Google ドライブ「AI通信」フォルダ（リンクを知っている全員が閲覧可）

## 新しい号の追加

**ドライブのフォルダに `AIの回し者_No84.pdf` のような名前で PDF を置くだけ。**
GitHub Actions が1時間ごとにフォルダを確認し、表紙画像・発行日・テーマ・本文（検索用）を取り込んで公開し直す。
急ぐときは GitHub の Actions タブ →「ドライブから新しい号を取り込んで公開」→ Run workflow。

- ファイル名の `No○○` から号数を読む（`No` がないファイルは無視）
- 同じ号の PDF を差し替えると、次の確認で取り込み直す
- ドライブから消した号はページからも消える

## テーマ・日付の手直し

PDF から自動で読み取ったテーマや日付がおかしいときは `data/overrides.json` に書く。

```json
{ "30": { "theme": "30号記念 回し続ける理由" } }
```

## 構成

| ファイル | 役割 |
|---|---|
| `index.html` | ページ本体（外部ライブラリなし） |
| `scripts/sync.py` | ドライブの確認と取り込み（`pip install pymupdf` が必要） |
| `data/issues.json` | 号の一覧（自動生成） |
| `data/search.json` | 全文検索用の本文（自動生成） |
| `covers/` | 表紙画像（自動生成）。`latest.jpg` は SNS/LINE のリンクプレビュー用 |
| `.github/workflows/sync.yml` | 1時間ごとの取り込みと Pages への公開 |

個別の号へのリンクは `…/ai-mawashimono/#no83` の形。
