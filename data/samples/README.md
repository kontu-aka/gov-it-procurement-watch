# オフライン表示用の公開サンプル

デジタル庁「調達情報」一般競争入札一覧の検証済み保存データです。
2026年10月3日BASELINE 15件と10月4日snapshot 15件、実比較はNO CHANGE／UNCHANGED 15件。
現在の調達状況ではありません。新規取得や差分を作るための合成変更は行っていません。
公開一覧の案件項目・取得日時・validation・出典を保持し、差分JSONの2つの参照パスだけを
このフォルダを基準とした相対パスに置き換えています。本番ファイルは変更していません。

出典：デジタル庁「調達情報」 https://www.digital.go.jp/procurement
加工：Gov IT Procurement Watch。デジタル庁公式サービスではありません。
利用条件：デジタル庁コピーライトポリシーと公共データ利用規約PDL1.0。
https://www.digital.go.jp/copyright-policy
https://www.digital.go.jp/resources/open_data/public_data_license_v1.0
外部詳細ページ本文、PDF、担当者情報、ロゴ、認証情報は含めていません。
PDL1.0を本プロジェクトのコードの利用ライセンスと混同しないでください。

ローカル起動：`.venv` のPythonで `-m streamlit run app.py --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1 -- --demo`。
公開サンプルは明示的に選択した場合だけ表示し、実取得データとは混在させません。
