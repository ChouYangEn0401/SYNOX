; SYNOX installer texts, Japanese (ja). Model-written translation: NEEDS NATIVE-SPEAKER REVIEW.
; Loaded after lang\en.isl, so a missing key falls back to English. Keys must match en.isl (tests/test_installer_script.py).

[LangOptions]
LanguageName=日本語 (Japanese)

[Messages]
SelectLanguageTitle=言語 · Language
SelectLanguageLabel=言語を選んでください。インストーラー、セットアップウィザード、SYNOX のすべてで使われます。
WelcomeLabel1=SYNOX へようこそ。楽しく使ってください。
WelcomeLabel2=•  あなたのパソコンに住む小さなアシスタント。Telegram、Discord、または Web ページから話しかけられます。%n•  専用の Python を同梱し、このパソコンのほかのものには手を触れません。%n•  管理者パスワードは不要。すべてあなたのアカウントの 1 つのフォルダーに入ります。%n•  まず短いチュートリアルをやってから、必要なツールを選びましょう。
WizardSelectTasks=何を準備しますか？
SelectTasksDesc=すべておすすめの設定になっています。
SelectTasksLabel2=どれも後から変えられます。インストーラーをもう一度実行するか、SYNOX の設定から変更してください。
FinishedHeadingLabel=SYNOX のインストールが完了しました
FinishedLabel=あと 1 ステップ：セットアップウィザードを開いて Telegram（または Discord）をつなぎ、使う AI を選びます。約 3 分です。そのあと短いチュートリアルをやってみてください。
ClickFinish=「完了」を押すとインストーラーを閉じます。
ConfirmUninstall=%1 を今すぐ削除しますか？
UninstalledAll=%1 を削除しました。
UninstalledMost=%1 を削除しました。%n%n設定とデータは SYNOX フォルダーに残っています。再インストールすると続きから使えます。
FinishedLabelNoIcons=あと 1 ステップ：セットアップウィザードを開いて Telegram（または Discord）をつなぎ、使う AI を選びます。約 3 分です。そのあと短いチュートリアルをやってみてください。

[CustomMessages]
DirNotWritable=SYNOX はこのフォルダーにデータを保存しますが、ここには書き込めません。別の場所を選んでください。
FinishedClaudeSkipped=Claude Code はいったんスキップしました（インターネットにつながっていないかもしれません）。あとでセットアップウィザードの AI ページの「ワンクリックでインストール（PowerShell）」で追加できます。
IconOpen=SYNOX を開く
IconUninstall=SYNOX をアンインストール
IconWizard=SYNOX セットアップウィザード
LicenseFile=LICENSE
LicenseLine=個人利用は無料です。商用で使う場合は <a id="license">AGPL-3.0 ライセンス</a>をお読みください。
RunSetupNow=今すぐセットアップウィザードを開く（おすすめ）
StatusClaude=Claude Code をインストールしています（インターネットが必要。数分かかることがあります）…
SynoxLangCode=ja
TaskAllTools=公式ツールをすべてインストールする（おすすめしません：先にチュートリアルをやってから必要なものを選びましょう）
TaskAutostart=サインイン時に SYNOX を起動する（小さなウィンドウが表示され、いつでも閉じられます）
TaskClaude=Claude Code をインストールする（ない場合のみ。インターネットが必要。ユーザーフォルダーに入ります）
TaskClaudePresent=Claude Code はインストール済みです
TaskDesktop=デスクトップに「SYNOX」のショートカットを作る
TaskFileType=.synoxpack ファイルをダブルクリックでインストールできるようにする（インストール前に確認があります）
TaskStartMenu=スタートメニューに「SYNOX」を追加する
TypeCustom=カスタム（フォルダーと各項目を自分で選ぶ）
TypeDesc=ほとんどの人は「おすすめ」のままで大丈夫です。
TypeLabel=「おすすめ」では、専用の Python、デスクトップとスタートメニューのショートカット、.synoxpack ファイルのダブルクリックインストール、サインイン時の起動、チュートリアルを用意します。このパソコンにまだ Claude Code がなければ一緒にインストールします（インターネットが必要。ユーザーフォルダーに入ります）。あとで変えたくなったら、インストーラーをもう一度実行するだけ。データは残ります。
TypeRecommended=おすすめ（すべて任せる）
TypeTitle=どのようにインストールしますか？
UninstallConfirmData=本当にデータも削除しますか？%n%n設定、メモ、家計簿、保存したキー、インストールしたツールが削除され、元に戻せません。
UninstallDeleteData=データも一緒に削除する
UninstallDeleteDataNote=元に戻せません。チェックするともう一度確認します。
UninstallHeading=SYNOX を削除しますか？
UninstallKeeps=残すもの：設定、メモ、家計簿、保存したキー、インストールしたツール。SYNOX フォルダーに残り、再インストールすると続きから使えます。
UninstallRemoves=削除するもの：SYNOX 本体、専用の Python、ショートカット、サインイン時の起動、.synoxpack のダブルクリックインストール。
UninstallTitle=SYNOX のアンインストール
UninstallUntouched=このパソコンのほかの Python、Conda、Claude Code には手を触れません。
