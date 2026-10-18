# Streamlit Community Cloud 設定・起動手順

政府調達データ分析ツール / Government Procurement Analytics の公開サンプル版を設定する手順です。

## 公開に使う設定

|項目|設定|
|---|---|
|Repository|`kontu-aka/gov-it-procurement-watch`|
|Branch|`release/cloud-v1.0`|
|Main file path|`cloud_app.py`。`app.py`を選ばないこと|
|Advanced settings → Python version|`3.12`を明示的に選択|
|Python依存|ルートの`requirements.txt`。直接依存3件の版を固定|
|設定|ルートの`.streamlit/config.toml`。画面テーマを共通化|
|Secrets|本アプリには不要。実データ・パス・認証情報を入力しない|
|OS用packages.txt|本アプリの実装には不要|
|データ|Git管理済みの`data/samples/`だけ|

CloudはブランチのRepository全体をコピーし、ルートから起動します。
今回の依存ファイルは`requirements.txt`です。
`requirements-lock.txt`はWindows検証用であり、Cloudの依存ファイルとして指定しません。
推移的依存はCloudで改めて解決されるため、ビルドごとの版と動作の確認が必要です。
Pythonの既定版に依存せず、3.12を選択してください。パッチ版はCloud側の提供版になります。

## サンプルと実データの境界

`cloud_app.py`は`app.py`を明示的な公開サンプル専用モードで実行します。
サイドバーのサンプル選択をオン・操作不可にし、セッション状態にかかわらずサンプルを読みます。
ローカルの実取得データは公開しません。公開用に数値を作成・固定することもしません。

公開サンプルは2026年10月3日・4日の保存データです。
取得15件、新規0件、更新0件、非掲載0件、変更なし15件、品質警告0件です。
画面に取得時期・公開サンプル・現在の調達状況ではないことを明示します。
サンプルが欠損・不正の場合はエラーで停止し、ローカル実データで代用しません。
ローカル用の`app.py`も、実データ不在時に自動でサンプルへ切り替えません。

画面の表示・検索・フィルター・差分・品質表示は保存データの読取りで動作します。
取得・比較コマンドはCloudの起動経路では呼びません。Cloud上から再取得・定期実行しません。
公開サンプルの更新は手動のメンテナンスです。
外部の出典・案件リンクは閲覧者がクリックすると提供元へ移動します。
出典・利用条件は[公開対象方針](PUBLICATION_POLICY.md)と[サンプル説明](../data/samples/README.md)を参照してください。

## ローカルでの確認

RepositoryルートでPython環境を有効にし、次のコマンドを実行します。
`--server.address 127.0.0.1`は待受を端末内に限定し、`--browser.serverAddress 127.0.0.1`はローカルの接続先を明示します。

```sh
# 公開サンプル専用の入口。調達サイトへの取得はしません。
python -B -m streamlit run cloud_app.py --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1 --server.port 8503
# ローカルに保存した実データを表示
python -B -m streamlit run app.py --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1
# オフライン検証
python -B -m unittest discover -s tests -v
python -B tests/streamlit_app_checks.py
python -B tests/cloud_app_checks.py
```

プロジェクトのconfigではCloud用に待受アドレスを固定していません。
フラグを省くと全インターフェース（例：`0.0.0.0`）で待受し、LANから到達できる場合があります。
Streamlit自身による外部IP確認（`checkip.amazonaws.com`へのHTTP/HTTPS問い合わせ）や、
内部IP判定のための`8.8.8.8`へのソケット接続試行が発生する場合もあります。
これはアプリによる調達情報取得とは別です。利用統計を無効にしても、これらの問い合わせを一括で遮断するものではありません。
上記コマンドでローカル接続先を明示し、外部リンクを開かない場合の検証結果と、フラグなし起動の通信を区別してください。
これらのフラグはOSレベルの通信遮断を保証しません。

ユーザー設定を手動で行う場合の参考として、Windowsでは`%USERPROFILE%/.streamlit/config.toml`に
次の設定を置く方法もあります。既存設定を上書きせず、ほかのStreamlitアプリにも適用されることを確認してください。
この手順はユーザー全体の設定ファイルを自動作成・変更しません。Cloudの設定にも適用しません。

```toml
[server]
address = "127.0.0.1"
```

設定はユーザー設定、プロジェクト設定、環境変数、コマンドライン引数の順で上書きされます。
ローカルの起動コマンドを明示する方法なら、ユーザー全体の設定を変えずに確認できます。
Cloud用には既定の待受を利用します。CORS/XSRF保護を無効にしません。
静的ファイル配信は有効にせず、サンプルJSONを静的配信フォルダに移しません。

## デプロイ手順

1. GitHubの対象ブランチで`cloud_app.py`、公開サンプル3JSON、config、requirementsが揃っていることを確認する。
2. 実データ、仮想環境、秘密設定、ログ、一時ファイルが公開対象に含まれていないことを確認する。
3. Streamlit Community CloudにGitHubでログインし、対象Repositoryへの権限を確認する。
4. 「Create app」から既存アプリを選び、上表のRepository・Branch・Main file pathを入力する。
5. 「Advanced settings」でPython 3.12を選ぶ。Secretsは空欄。必要ならURL名を指定する（空き状況による）。
6. デプロイを実行し、ログで依存解決と正常起動を確認する。
7. 発行されたURLをPCとスマートフォンで開く。閲覧者のPowerShell操作は不要。
8. 正式名称、非公式表示、サンプルの時期、6KPI、案件一覧、検索・フィルター、比較・品質を確認する。
9. 取得件数が15件以外、または新規・更新・非掲載が0件以外なら公開を止め、入口と公開対象を確認する。
10. 変更なし15件、品質警告0件も確認する。休止からの復帰や再起動後も同じ公開サンプルを表示することを確認する。

公開元ブランチへのpushはCloudの自動更新につながります。公開元の変更には運用中アプリへの影響確認が必要です。
実データ、`.venv`、`.git`、`.env`、`secrets.toml`、ログ、`work/`、テスト出力を公開対象へ追加しません。

## 検証範囲とプラットフォーム上の注意

Windows／Python 3.12での検証に加え、Linux／Python 3.12.3でのオフライン検証結果があります。
LinuxではWindows lockと同じ依存版、およびCloud相当の解決版で、単体77件・既存画面7件・公開用画面11件のPASSが報告されています。
この結果は実際のCommunity Cloudビルド、HTTPS、リバースプロキシ、休止復帰、端末実機やPython 3.12以外の動作を保証しません。
それらはデプロイ環境で確認してください。検証条件は[検証記録](VERIFICATION.md)を参照してください。
将来のビルドで推移的依存の版が変わる可能性があります。

Community Cloudは米国ホストです。公式仕様では利用統計やXSRF等の設定をプラットフォームが上書きします。
ローカルの`gatherUsageStats=false`だけを根拠に、Cloudでも通信がゼロと説明しないでください。
アプリのデータ取得処理と、プラットフォームの管理・利用統計通信は別です。
公開される案件情報は過去の公開サンプルで、現在の入札情報や政府の公式案内ではありません。

## 公式資料

- [既存ブランチ・起動ファイル・Python版の指定](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)
- [ファイル構成とルートからの起動](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)
- [requirementsとLinux依存](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies)
- [configと起動引数の優先順位](https://docs.streamlit.io/develop/concepts/configuration/options)
- [Cloudの制限・設定上書き・ホスト地域](https://docs.streamlit.io/deploy/streamlit-community-cloud/status)
- [CloudのSecrets管理](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
