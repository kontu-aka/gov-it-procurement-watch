# ローカル検証記録

ローカルGitの初期化と初回commitは完了しています。Webへのホスティングは未実施です。
自作コードは[MIT License](../LICENSE)です。

## 2026年10月4日時点のローカル検証

以下はこの日付時点の保存データ・実行環境を使った検証記録です。現在のテスト件数や調達状況とは区別してください。
保存済みデータだけを使用し、追加live取得は0回でした。

|確認|当時の結果|
|---|---|
|Python|3.12.14（このプロジェクトの.venv）|
|Streamlit|1.65.0|
|requests / beautifulsoup4|2.34.2 / 4.15.0|
|依存整合|requirementsと実環境一致、pip check正常、lockに固定|
|単体テスト|59件PASS|
|AppTest|保存データ6件PASS、公開サンプル6件PASS|
|公開用ファイルのみのコピー|本番履歴・ログ・仮想環境を含めず、59件＋AppTest6件PASS|
|実サーバー|127.0.0.1で起動、healthとブラウザ表示を確認後に停止|
|最新保存snapshot|2026-10-04取得、15件|
|比較状態|READY、NO CHANGE、UNCHANGED15、NEW／UPDATED／NOT_LISTED各0|
|検索・フィルター|キーワード・日付範囲・公告種別・該当0件・rerun PASS|
|画面例外|AppTest例外・Tracebackなし|
|保存原本保護|BASELINE、snapshot、diff、取得ログ等の内容・mtime不変|

BASELINE SHA-256（前後一致）：
`E6B21073A160611256FA4F8B94FF7FE1E0A803E5607467A560BA89BB8A697E95`。
取得処理のコード変更と、本番BASELINE JSONの内容変更は別です。本番JSONは初回保存状態を保持しています。

実データは2世代各15件を比較したNO CHANGEです。実非ゼロ差分は未観測です。
NEW／UPDATED／NOT_LISTED等の非ゼロケースはfixture由来の合成テストで検証し、実データでの観測とは区別します。
画面画像は当日の保存データ表示です。現在の調達状況を示しません。

## 検証範囲の制限

Windows／Python3.12での検証です。別OS・新規クリーン.venvの再作成による検証は未実施です。
AppTestのbare-mode ScriptRunContext警告は残ります。取得頻度条件も未確定です。
コードライセンスはデータのPDL1.0とは別です。この検証時点では未指定でしたが、その後MIT Licenseに決定しました。

## 2026年10月5日のレビュー修正後の回帰検証

このプロジェクトの既存.venv（Python3.12.14）だけを使用しました。追加live取得は0回です。

|確認|結果|
|---|---|
|全単体テスト|73件PASS。既存59件に回帰14件を追加|
|保存データ＋合成差分のAppTest|7件PASS|
|公開候補26ファイルだけのコピー|AppTest7件PASS。保存原本・logs・.venv・Git metadataを含めない|
|再取得保護テスト単独|workが存在しないコピーで4件PASS。一時子領域は後始末済み|
|正順の実データ比較|2026-10-03→2026-10-04、SUCCESS／NO CHANGE／UNCHANGED15|
|逆順・同一snapshot|VALIDATION_ERROR。NEW／NOT_LISTEDを生成せず、結果保存を拒否|
|日時欠落・解析不能・timezoneなし|STRUCTURE_ERROR。結果保存を拒否|
|timezone差|文字列順ではなく時点で比較。同時点の別offset表記も拒否|
|非ゼロ差分表示|合成のNEW／UPDATED／NOT_LISTED／AMBIGUOUS_IDENTITYを描画、変更フィールドも表示、例外0|
|diff CLI main|正常保存、逆順・同一、入力欠落、壊れたJSON、validation失敗を確認|
|新しいdiff参照|ファイル名のみ保存。絶対参照の保存を抑止し、データ移動後もREADY|
|既存表示|保存原本・公開サンプルとも15件、READY、NO CHANGE。検索・フィルター正常|
|原本保護|BASELINEと保護対象29ファイルのSHA・mtime不変。sample JSONも変更なし|

合成差分はテスト中にfixtureから作成した専用データです。実サイトでの非ゼロ差分観測を示すものではありません。
同梱スクリーンショットは2026年10月4日の実データNO CHANGE画面のままです。
