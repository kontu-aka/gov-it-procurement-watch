# Streamlit UI 改善・確認記録

確認日：2026年10月15日。実装・検証完了後のHuman確認待ち。

## 作業の分離

- 対象：`kontu-aka/gov-it-procurement-watch`
- 開始時の元チェックアウト：`main`、未コミット・staged変更なし。
- 基点HEAD：`2ee7b1ae3a0369a0ebd68e13d4bc73563d2fe0e6`
- 専用worktree・ブランチ：`gov-it-procurement-watch-ui` / `codex/ui-design-improvement`
- 元の`main`は同じHEAD・cleanを維持。commit・push・デプロイなし。

## 改善内容

白を基調にネイビーとターコイズを使用。取得件数・4種の差分・品質警告を大きなKPIカードで表示する。
PCでは基本6列、表示領域が狭ければ3列、小画面では2列に配置する。

|保存された判定|表示|色|
|---|---|---|
|NEW|新規掲載|緑 `#187247`|
|UPDATED|内容更新|紫 `#7541aa`|
|NOT_LISTED|今回の一覧から非掲載|赤 `#b93b4c`|
|UNCHANGED|変更なし|青 `#275eb0`|

案件一覧は全文を折り返すカードと従来の表を切り替えられる。
検索・日付・公告種別の条件は案件一覧だけに適用し、全件のKPI・集計には適用しない。
差分ラベルは保存済みイベントの`stable_key`で今回のレコードと対応付ける。
判定の再計算、タイトルによる推測、比較未作成時のゼロ件・変更なしの代用は行わない。
非掲載案件は比較詳細から参照し、取消・終了・落札を意味しない旨を表示する。

表示ヘルパーは保存テキストをHTMLエスケープする。詳細URLには既存の`safe_detail_url`を使用する。
差分の要約レコードに更新日が含まれていない場合、更新日を推測表示しない。
出典・取得日時・保存ファイル名・サンプル表示の注記を維持する。

## 変更ファイル

|ファイル|内容|
|---|---|
|`app.py`|KPI、カード／表、比較詳細、表示順・日本語の調整|
|`assets/dashboard.css`|配色、余白、カード、レスポンシブ表示|
|`src/dashboard_ui.py`|表示用ラベル、保存イベントとの対応、HTML生成|
|`.streamlit/config.toml`|lightテーマ・基本色。server設定は維持|
|`tests/test_dashboard_ui.py`|表示用対応付け・未比較・エスケープ等の回帰4件|
|`.gitattributes`|固定SHAを検査する既存fixture一つだけLF改行に固定|
|`docs/UI_DESIGN_REVIEW.md`|本記録|

取得・差分判定・保存データ選択を担う`baseline.py`、`diff_engine.py`、`dashboard_data.py`は変更していない。
依存パッケージの追加・更新はない。

Windowsの自動改行変換により、worktree作成直後にfixtureの固定SHA検査が失敗した。
fixtureをHEADの元のバイト列へ戻し、指定のSHA-256と一致することを確認した。
JSONの値の変更はない。`.gitattributes`は同じ問題の再発を防ぐ指定。

## 検証結果

環境：Windows、Python 3.12.10、Streamlit 1.65.0。既存Python環境のローカルコピーを使用。

|確認|結果|
|---|---|
|既存単体テスト|73件PASS|
|追加表示回帰テスト|4件PASS。合計77件PASS|
|実保存データの既存AppTest|7件PASS（合成差分1件を含む）|
|公開サンプルの既存AppTest|7件PASS（合成差分1件を含む）|
|保存データなし／一世代／二世代で差分未作成|追加画面検証3状態PASS|
|取得・外部通信|追加取得なし。AppTestは既存の外部通信禁止ガード付き|
|実画面|実保存データ20件を表示。新規7件・変更なし13件のラベル対応を確認|
|非掲載の実画面|実際の非掲載案件を開き、赤色・案件名・番号を確認|
|内容更新|実データでは0件。非ゼロ表示は合成データのAppTestで検証|
|小画面|320px・390px・768px幅でページ横はみ出しなし。390pxで全文カードを目視確認|
|原本保護|保存JSON5ファイルは原本・検証用コピーとも開始時SHA-256と一致|
|Git|`git diff --check`正常。元main・HEAD維持。staged変更なし|

実データ表示値は、2026年10月14日20:21:14（UTC+09:00）取得snapshotと対応する保存差分から得たもの。
取得20件、新規7件、更新0件、非掲載2件、変更なし13件、品質警告0件。
値のハードコードはない。公開サンプルは15件・差分0件として別表示する。

AppTest実行時にはStreamlitのbare-mode `ScriptRunContext`警告が出るが、テスト例外はない。
CSSはStreamlit 1.65.0のDOMで検証。Streamlit更新時は表示の再確認が必要。

## 画面確認方法

専用worktreeのルートで実行する。元のmainのアプリと取り違えないこと。

```powershell
.\.venv\Scripts\python.exe -B -m streamlit run app.py --server.port 8502 --server.address 127.0.0.1 --server.fileWatcherType none
```

ブラウザーで `http://127.0.0.1:8502` を開く。
「公開サンプルで表示（オフライン）」をオフにすると検証用の実保存データ、オンにすると同梱の公開サンプルを表示する。
検索、カード／表の切り替え、比較詳細の展開を確認できる。
この起動はローカルだけを対象とし、Web公開や再取得は行わない。停止は起動ターミナルでCtrl+C。

再検証コマンド：

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B tests\streamlit_app_checks.py
$env:GOV_IT_APPTEST_DEMO = '1'
.\.venv\Scripts\python.exe -B tests\streamlit_app_checks.py
Remove-Item Env:\GOV_IT_APPTEST_DEMO
```

ローカル証跡はGit除外の`work/ui-review/`に保持する。
`unit-tests.txt`、`apptest-real.txt`、`apptest-sample.txt`、`empty-states.json`、`data-integrity.json`を参照。
実画面画像：`desktop.jpg`、`mobile.jpg`、`mobile-cases.jpg`、`comparison.jpg`。
実保存データのコピー・Python環境・検証ログ・画像はstageしない。

Human確認後の統合・commit・push・Web公開は別工程とする。

## 2026年10月16日：KPIエリアの部分修正

今回の追加変更は`assets/dashboard.css`と本記録のみ。
既存のUI改善worktreeを継続使用し、`app.py`や集計・判定処理、保存JSONは変更していない。

- KPI内の上下余白・要素間隔・ラベルの行高を縮小。数字は33.6pxを維持。
- 表示領域に応じて6列／3列／2列に切り替え、スマートフォンでは2列。
- 長いラベルが折り返しても、同じ行の数値の位置を揃える。
- 既存の配色と「前回15件→今回20件」の保存データ由来の補足を維持。
- KPIだけに適用するCSSで、案件カード・比較詳細・品質エリアのスタイルは変更していない。

|確認|結果|
|---|---|
|PC・1280px幅、サイドバーを閉じた同一条件|KPIエリア272.4px → 84.3px。案件一覧が188.1px上へ移動|
|PC・980px幅|6列、約98.2px高。数値の縦位置が一致、横はみ出しなし|
|700px幅|表示領域に合わせ3列|
|320px・390px幅|2列。長いラベルの折り返し・横はみ出しなし|
|実保存データの表示値|20／7／0／2／13／0を維持|
|単体テスト|77件PASS|
|既存AppTest|実保存データ7件、公開サンプル7件PASS。既存の外部通信禁止ガード付き|
|原本・ロジックの保護|元mainは同じHEAD・clean。原本5ファイルのSHA一致。worktreeの保護対象15ファイルとapp.pyも変更なし|
|Git|staged変更なし。commit・push・デプロイなし|

今回の検証記録と実画面画像はGit除外の`work/kpi-compact/`に保持。
`desktop.jpg`、`mobile.jpg`、`before-desktop.json`、`after-desktop.json`、テストログを参照。
ローカル確認URL・再起動方法は上記と同じ。Human確認待ちで停止。

## 2026年10月16日：画面表示名の変更

今回の追加変更は`app.py`の表示文字列と本記録のみ。

- 最上部タイトル・ブラウザーのタブタイトルを「政府調達データ分析ツール」に変更。
- タイトル直下に既存のアクセント文字スタイルで「Government Procurement Analytics」を配置。
- 説明文を「デジタル庁の公開調達情報を整理・可視化。新規掲載や前回からの変更をひと目で確認できます。」に変更。
- 「デジタル庁の公開情報を利用した非公式ツールです。」を画面上部に表示。既存の出典・非公式サービスの説明も維持。
- サイドバーの表示名称も正式名称に揃える。

リポジトリ名、フォルダー名、Python内部識別子は変更していない。
CSS・KPIのサイズと配置・データ・集計と差分の処理を含む保護対象16ファイルは開始時のSHA-256と一致。

検証：単体77件PASS、既存AppTestは実保存データ7件・公開サンプル7件PASS。
ローカル確認用サーバーを再起動し、新しいタブタイトル、正式名称、英語表記、指定の説明文・注意書きを実画面で確認。
PCは6列、390px幅は2列を維持。実データのKPI値は20／7／0／2／13／0、画面例外なし。
元mainは同じHEAD・clean、原本5ファイルのSHA一致。commit・push・Web公開は未実施。

ローカル証跡：`work/display-name/`のテストログ、`desktop-verification.json`、`desktop.jpg`、`mobile.jpg`。
確認URLは `http://127.0.0.1:8502`。Human確認待ちで停止。
