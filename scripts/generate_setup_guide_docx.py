"""久保田様向けセットアップ手順書（Word）を生成するスクリプト。

実行方法:
    uv run python scripts/generate_setup_guide_docx.py

出力先:
    output/BGナレッジベース_セットアップ手順書_久保田様向け_v1.0.docx

注意: 本スクリプトは引き継ぎドキュメント生成専用の一回限りのユーティリティ。
外部 API は一切呼ばない（コストゼロ）。
"""

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

JP_FONT = "Yu Gothic"
CODE_FONT = "Consolas"

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "output" / (
    "BGナレッジベース_セットアップ手順書_久保田様向け_v1.0.docx"
)


def set_style_font(doc: Document, style_name: str, size: Pt | None = None) -> None:
    """指定スタイルの欧文・和文フォントを揃える。"""
    style = doc.styles[style_name]
    style.font.name = JP_FONT
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), JP_FONT)
    if size is not None:
        style.font.size = size


def h1(doc: Document, text: str) -> None:
    doc.add_heading(text, level=1)


def h2(doc: Document, text: str) -> None:
    doc.add_heading(text, level=2)


def p(doc: Document, text: str, bold: bool = False) -> None:
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.bold = bold


def bullet(doc: Document, text: str) -> None:
    doc.add_paragraph(text, style="List Bullet")


def step(doc: Document, number: str, text: str) -> None:
    """「手順 N.」形式の段落（番号は手動で振る）。"""
    para = doc.add_paragraph()
    run = para.add_run(f"{number} ")
    run.bold = True
    para.add_run(text)


def code(doc: Document, text: str) -> None:
    """グレー背景のコマンド表示ボックス。"""
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Cm(0.5)
    run = para.add_run(text)
    run.font.name = CODE_FONT
    run.font.size = Pt(10)
    rfonts = run._element.get_or_add_rPr()
    el = OxmlElement("w:rFonts")
    el.set(qn("w:ascii"), CODE_FONT)
    el.set(qn("w:hAnsi"), CODE_FONT)
    el.set(qn("w:eastAsia"), "MS Gothic")
    rfonts.append(el)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "F2F2F2")
    para._p.get_or_add_pPr().append(shd)


def prompt_box(doc: Document, text: str) -> None:
    """Claude Code への依頼文（プロンプト）を示す薄青背景ボックス。"""
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Cm(0.5)
    run = para.add_run(text)
    run.font.size = Pt(10.5)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), "E8F0FE")
    para._p.get_or_add_pPr().append(shd)


def note(doc: Document, text: str, label: str = "ポイント", fill: str = "FFF6DD") -> None:
    """注意書きボックス。"""
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Cm(0.5)
    run = para.add_run(f"【{label}】 ")
    run.bold = True
    run.font.color.rgb = RGBColor(0xB0, 0x60, 0x00)
    para.add_run(text)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    para._p.get_or_add_pPr().append(shd)


def check(doc: Document, text: str) -> None:
    """チェックリスト項目。"""
    doc.add_paragraph(f"□　{text}")


def table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, head in enumerate(headers):
        cell = t.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(head)
        run.bold = True
    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row):
            t.rows[r].cells[c].text = value
    doc.add_paragraph()


def build() -> None:
    doc = Document()
    for name in ("Normal", "List Bullet"):
        set_style_font(doc, name, Pt(10.5))
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        set_style_font(doc, name)

    # ---- 表紙 ----
    doc.add_heading("BGナレッジベース 運用セットアップ手順書", level=0)
    p(doc, "（久保田様向け・移行期間運用版）", bold=True)
    doc.add_paragraph()
    table(
        doc,
        ["項目", "内容"],
        [
            ["版", "v1.0"],
            ["作成日", "2026年6月12日"],
            ["作成", "勝山（Claude Code により作成）"],
            ["対象読者", "久保田様（運用責任者）"],
            ["前提", "Windows 11 のパソコン。Mac をお使いの場合は勝山までご連絡ください。"],
        ],
    )

    # ---- 1. この手順書について ----
    h1(doc, "1. この手順書について")
    p(
        doc,
        "この手順書は、BGナレッジベース（議事録から知見を抽出してマスターデータを作る仕組み）を、"
        "久保田様ご自身のパソコンで操作できるようにするためのものです。"
        "プログラミングの知識は不要です。書いてある通りに、上から順番に進めてください。",
    )
    bullet(doc, "初期セットアップ（第5章〜第11章）の所要時間：約60〜90分")
    bullet(doc, "日常の運用（第12章）の所要時間：1回あたり10〜30分程度")
    note(
        doc,
        "途中でエラーが出たり、画面の表示が手順書と違ったりしたら、無理に進めず勝山までご連絡ください。"
        "移行期間中は勝山がいつでもサポートします。",
        label="大事なこと",
    )

    # ---- 2. 全体像 ----
    h1(doc, "2. システムの全体像")
    p(
        doc,
        "このシステムの目的は、Google Meet の議事録（Word ファイル）から土壌R&Dの知見を抽出し、"
        "マスターデータ（Excel ファイル）にまとめることです。日常運用の流れは次の4ステップです。",
    )
    step(doc, "①", "Google Drive から新しい議事録ファイル（.docx）をダウンロードする")
    step(doc, "②", "Claude Code（AIアシスタント）に知見の抽出を頼む")
    step(doc, "③", "出来上がった Excel ファイル（output フォルダ）を確認する")
    step(doc, "④", "内容をマスターデータのスプレッドシートに転記する")
    doc.add_paragraph()
    h2(doc, "Claude Code とは")
    p(
        doc,
        "Claude Code は、Anthropic 社の AI「Claude」に、パソコン上のファイル操作を日本語でお願いできるツールです。"
        "黒い画面（ターミナル）で動きますが、コマンドを覚える必要はありません。"
        "「〇〇のファイルから知見を抽出して」と日本語で話しかけるだけで作業してくれます。",
    )
    note(
        doc,
        "このシステムは外部の API 課金（従量課金）を使いません。Claude の月額プラン（Pro など）の範囲内で動作します。"
        "また、Notion のデータは「読み取り専用」で、既存のページを書き換えることはありません。",
    )

    # ---- 3. 移行期間の体制 ----
    h1(doc, "3. 移行期間の体制とルール")
    p(
        doc,
        "いきなり完全移管はせず、当面は「移行期間」として、勝山と久保田様の両方が操作できる体制にします。"
        "二人で同じものを扱うため、次のルールを守ってください。",
    )
    table(
        doc,
        ["ルール", "理由"],
        [
            [
                "作業を始める前に、Slack 等で「今からKB作業をします」と一声かける",
                "二人が同時に作業すると、結果がぶつかる（competing edits）ことがあるため",
            ],
            [
                "作業の最初に Claude Code へ「git pull して最新の状態にしてください」と頼む",
                "もう一人が行った変更を取り込んでから作業を始めるため",
            ],
            [
                "作業の最後に「今回の作業内容を docs/decision_log.md に記録し、コミットしてプッシュしてください」と頼む",
                "作業の記録を残し、もう一人に変更を共有するため",
            ],
            [
                "Notion のトークン（後述）は各自専用のものを使い、共有しない",
                "問題があったときに、どちらの操作か切り分けられるようにするため",
            ],
            [
                "判断に迷ったら手を止めて勝山に連絡する",
                "移行期間中は勝山がサポートに入れるため",
            ],
        ],
    )
    p(
        doc,
        "移行期間が終わって完全移管するときに、勝山側のアクセス権の整理（GitHub・Notion トークンの無効化）を行います。"
        "それまでは勝山側の環境もそのまま残します。",
    )

    # ---- 4. 事前準備 ----
    h1(doc, "4. 事前準備チェックリスト")
    h2(doc, "4-1. ご自身で用意するもの")
    check(doc, "Windows 11 のパソコン（インターネットに接続できること）")
    check(doc, "GitHub のアカウント（無料）。https://github.com/ で「Sign up」から作成できます")
    check(
        doc,
        "Claude のアカウント（有料プラン）。https://claude.ai/ で登録し、Pro 以上のプランに加入してください"
        "（Claude Code の利用に必要です。プランは会社のご判断で構いません）",
    )
    check(doc, "Notion に BG ワークスペースの管理者としてログインできること")
    h2(doc, "4-2. 勝山から受け取るもの")
    p(doc, "以下は勝山から個別にお渡しします。届いていないものがあればご連絡ください。")
    table(
        doc,
        ["受け取るもの", "何に使うか", "受け渡し方法"],
        [
            [
                "GitHub リポジトリへの招待",
                "プログラム一式をご自身のパソコンに取得するため",
                "GitHub からの招待メール（Accept を押す）",
            ],
            [
                "Notion トークン（久保田様専用）",
                "Notion のデータを読み取るための「鍵」。パスワードと同じ扱いで管理してください",
                "安全な方法で個別連絡",
            ],
            [
                "設定ファイル（.env）に貼り付ける値の一覧",
                "第10章の初期設定で使用",
                "同上",
            ],
            [
                "引き継ぎファイル一式（過去の抽出結果など）",
                "過去の作業の続きから運用するため",
                "zip ファイル等で受け渡し（第10章で配置）",
            ],
        ],
    )

    # ---- 5. PowerShell ----
    h1(doc, "5. ステップ1：PowerShell（ターミナル）の開き方")
    p(
        doc,
        "この後の手順では「PowerShell（パワーシェル）」という、文字でパソコンに指示を出す画面を使います。"
        "開き方を覚えてください（今後何度も使います）。",
    )
    step(doc, "1.", "画面下の「スタートボタン（Windowsマーク）」を右クリックします。")
    step(doc, "2.", "メニューから「ターミナル」をクリックします。")
    step(doc, "3.", "黒っぽい画面が開き、「PS C:\\Users\\（お名前）>」のような文字が表示されれば成功です。")
    note(
        doc,
        "この手順書でグレーの枠に書かれている「コマンド」は、この画面にコピーして貼り付け、"
        "Enter キーを押して実行します。貼り付けは右クリック、または Ctrl+V でできます。"
        "1行ずつ実行してください。",
    )

    # ---- 6. Git ----
    h1(doc, "6. ステップ2：Git のインストール")
    p(
        doc,
        "Git（ギット）は、プログラム一式を取得・更新するための道具です。PowerShell で次のコマンドを実行します。",
    )
    code(doc, "winget install --id Git.Git -e --source winget")
    step(doc, "1.", "上のコマンドを実行すると、ダウンロードとインストールが自動で進みます。数分かかります。")
    step(doc, "2.", "「インストールが完了しました」等の表示が出たら、PowerShell をいったん閉じて、開き直します（重要）。")
    step(doc, "3.", "開き直した PowerShell で、次のコマンドを実行して確認します。")
    code(doc, "git --version")
    p(doc, "「git version 2.〜」のように数字が表示されれば成功です。")
    note(
        doc,
        "「winget が見つかりません」と出る場合は、https://git-scm.com/download/win から"
        "インストーラーをダウンロードして実行してください（設定はすべて「Next」のままで構いません）。",
        label="うまくいかないとき",
        fill="FDECEC",
    )

    # ---- 7. uv ----
    h1(doc, "7. ステップ3：uv のインストール")
    p(
        doc,
        "uv（ユーブイ）は、このシステムが使う Python（プログラムの実行環境）を自動で整えてくれる道具です。",
    )
    step(doc, "1.", "PowerShell で次のコマンドを実行します。")
    code(doc, "irm https://astral.sh/uv/install.ps1 | iex")
    step(doc, "2.", "完了したら PowerShell を閉じて開き直し、次のコマンドで確認します。")
    code(doc, "uv --version")
    p(doc, "「uv 0.〜」のように数字が表示されれば成功です。")

    # ---- 8. Claude Code ----
    h1(doc, "8. ステップ4：Claude Code のインストールとログイン")
    step(doc, "1.", "PowerShell で次のコマンドを実行します。")
    code(doc, "irm https://claude.ai/install.ps1 | iex")
    step(doc, "2.", "完了したら PowerShell を閉じて開き直し、次のコマンドで確認します。")
    code(doc, "claude --version")
    p(doc, "数字が表示されれば成功です。ログイン（次の手順）はプロジェクト取得後の第11章で行います。")

    # ---- 9. クローン ----
    h1(doc, "9. ステップ5：プロジェクトの取得（クローン）")
    p(
        doc,
        "GitHub に保管されているプログラム一式を、ご自身のパソコンにコピーします。これを「クローン」と呼びます。"
        "事前に GitHub の招待メール（4-2参照）を承諾（Accept invitation）しておいてください。",
    )
    step(doc, "1.", "PowerShell で次の2つのコマンドを順に実行します（ドキュメントフォルダに移動してから取得します）。")
    code(doc, "cd $HOME\\Documents")
    code(doc, "git clone https://github.com/bg-d-katsuyama/bg_knowledge-base.git")
    step(
        doc,
        "2.",
        "初回はブラウザが開いて GitHub のログインを求められます。「Sign in with your browser」を選び、"
        "ご自身の GitHub アカウントでログインして「Authorize」を押してください。",
    )
    step(doc, "3.", "PowerShell に戻り、エラーなく完了したら、次のコマンドでフォルダに移動します。")
    code(doc, "cd bg_knowledge-base")
    note(
        doc,
        "今後、Claude Code を使うときは毎回、PowerShell を開いて「cd $HOME\\Documents\\bg_knowledge-base」で"
        "このフォルダに移動してから始めます。この1行は覚えておいてください（コピーして使えば大丈夫です）。",
    )

    # ---- 10. 初期設定 ----
    h1(doc, "10. ステップ6：プロジェクトの初期設定")
    h2(doc, "10-1. 必要な部品のインストール")
    p(doc, "プロジェクトのフォルダ（bg_knowledge-base）にいる状態で、次のコマンドを実行します。")
    code(doc, "uv sync")
    p(
        doc,
        "Python 本体や必要な部品が自動でダウンロードされます。初回は数分かかります。"
        "エラーらしき赤い文字が出なければ成功です。",
    )
    h2(doc, "10-2. 設定ファイル（.env）の作成")
    p(
        doc,
        ".env（ドットエンブ）は、Notion トークンなどの秘密情報を書いておくファイルです。"
        "勝山から受け取った「設定値の一覧」（4-2参照）を手元に用意してから進めてください。",
    )
    step(doc, "1.", "次のコマンドで、ひな形をコピーして .env を作ります。")
    code(doc, "copy .env.example .env")
    step(doc, "2.", "次のコマンドでメモ帳が開きます。")
    code(doc, "notepad .env")
    step(
        doc,
        "3.",
        "勝山から受け取った値を、対応する行の「=」の右側に貼り付けます。対象は次の6行です。"
        "それ以外の行は変更せず、空欄のままで構いません。",
    )
    table(
        doc,
        ["行（設定名）", "貼り付ける値"],
        [
            ["NOTION_API_TOKEN", "久保田様専用の Notion トークン"],
            ["NOTION_DB_KNOWLEDGE_ENTRY", "ナレッジエントリDB の ID"],
            ["NOTION_DB_PEOPLE", "人DB の ID"],
            ["NOTION_DB_ORGANIZATION", "企業・団体DB の ID"],
            ["NOTION_DB_PROJECT", "プロジェクトDB の ID"],
            ["NOTION_DB_TAG", "タグDB の ID"],
        ],
    )
    step(doc, "4.", "メモ帳で「ファイル → 上書き保存」して閉じます。")
    note(
        doc,
        ".env はパスワードと同じです。メールに添付したり、Slack に貼り付けたりしないでください。"
        "値の前後に余計なスペースが入ると認証エラーになるので注意してください。",
        label="重要",
        fill="FDECEC",
    )
    h2(doc, "10-3. 引き継ぎファイルの配置")
    p(
        doc,
        "勝山から受け取った「引き継ぎファイル一式」（zip）を展開し、中のファイルを次の場所に置いてください。"
        "エクスプローラー（フォルダ画面）でのコピーで構いません。",
    )
    table(
        doc,
        ["ファイル", "置き場所"],
        [
            [
                "insights_drive.json（過去の抽出結果）",
                "bg_knowledge-base\\logs フォルダの中（フォルダがなければ作成）",
            ],
            [
                "議事録の docx ファイル一式",
                "bg_knowledge-base\\data\\drive_input フォルダの中",
            ],
            [
                "過去に生成した Excel ファイル（参考用）",
                "bg_knowledge-base\\output フォルダの中",
            ],
        ],
    )

    # ---- 11. 動作確認 ----
    h1(doc, "11. ステップ7：Claude Code の起動と動作確認")
    h2(doc, "11-1. 起動とログイン")
    step(doc, "1.", "プロジェクトのフォルダにいる状態で、次のコマンドを実行します。")
    code(doc, "claude")
    step(
        doc,
        "2.",
        "初回はログインを求められます。「Claude account with subscription」を選ぶとブラウザが開くので、"
        "ご自身の Claude アカウント（Pro 以上）でログインし、許可（Authorize）してください。",
    )
    step(
        doc,
        "3.",
        "画面の配色（テーマ）の選択などを聞かれたら、そのまま Enter で進めて構いません。"
        "「Do you trust the files in this folder?（このフォルダを信頼しますか）」と聞かれたら「Yes, proceed」を選びます。",
    )
    step(doc, "4.", "入力欄が表示されたら起動成功です。ここに日本語で話しかけて作業を進めます。")
    h2(doc, "11-2. Claude Code の「許可確認」について")
    p(
        doc,
        "Claude Code は、ファイルを変更したりコマンドを実行したりする前に「許可しますか？」と確認してきます。"
        "次の方針で答えてください。",
    )
    table(
        doc,
        ["確認の内容", "答え方"],
        [
            ["ファイルの読み取り、output フォルダへのファイル作成", "許可してOK（Yes）"],
            ["docs/decision_log.md への記録、git のコミット・プッシュ", "許可してOK（Yes）"],
            ["Notion への書き込み・更新・削除に見えるもの", "許可しない（No）→ 勝山に連絡"],
            ["内容がよく分からないもの", "許可しない（No）→ 勝山に連絡"],
        ],
    )
    h2(doc, "11-3. 動作確認テスト")
    step(doc, "1.", "まず、次の文をそのまま入力欄に貼り付けて Enter を押してください。")
    prompt_box(
        doc,
        "CLAUDE.md と docs/decision_log.md を読んで、このプロジェクトの目的と現在の状況を、"
        "専門用語を使わずに5行以内で説明してください。",
    )
    p(doc, "プロジェクトの説明が日本語で返ってくれば、Claude Code は正しく動いています。")
    step(doc, "2.", "次に、ファイルが読めることを確認します。")
    prompt_box(
        doc,
        "data/drive_input フォルダの中の docx ファイルを1つ選んで、内容を3行で要約してください。"
        "Notion への書き込みは行わないでください。",
    )
    p(doc, "議事録の要約が返ってくれば、セットアップはすべて完了です。お疲れさまでした。")
    note(
        doc,
        "Claude Code を終了するには、入力欄に /exit と入力するか、PowerShell の画面を閉じます。"
        "会話をリセットして新しく始めたいときは /clear と入力します。",
    )

    # ---- 12. 日常運用 ----
    h1(doc, "12. 日常の運用手順（新しい議事録から知見を抽出する）")
    p(doc, "新しい議事録が増えたときの定常作業です。毎回この順番で行ってください。")
    step(doc, "1.", "Slack 等で「今からKB作業をします」と一声かけます（移行期間ルール）。")
    step(
        doc,
        "2.",
        "Google Drive から新しい議事録ファイル（.docx）をダウンロードし、"
        "bg_knowledge-base\\data\\drive_input フォルダにコピーします。",
    )
    step(doc, "3.", "PowerShell を開き、次の2つを実行して Claude Code を起動します。")
    code(doc, "cd $HOME\\Documents\\bg_knowledge-base")
    code(doc, "claude")
    step(doc, "4.", "最初に、次の文を貼り付けて最新の状態に更新します。")
    prompt_box(doc, "git pull して、プロジェクトを最新の状態にしてください。")
    step(doc, "5.", "続けて、次の文を貼り付けます（ファイル名の部分はご自身で書き換えてください）。")
    prompt_box(
        doc,
        "data/drive_input に新しい議事録ファイル「（ここにファイル名）.docx」を追加しました。"
        "この内容から土壌R&Dの知見を抽出し、これまでの知見（logs/insights_drive.json）と統合した"
        "マスターデータの xlsx を output フォルダに作成してください。"
        "Notion への書き込みは行わないでください。",
    )
    step(
        doc,
        "6.",
        "完了したら、output フォルダにできた新しい Excel ファイルを開き、抽出された知見の内容を確認します。"
        "おかしな内容があれば、Claude Code に日本語で修正を頼めます（例：「3行目の知見は議事録の文脈と違うので削除して」）。",
    )
    step(doc, "7.", "問題なければ、マスターデータのスプレッドシートに転記します。")
    step(doc, "8.", "最後に、次の文を貼り付けて作業記録を残します。")
    prompt_box(
        doc,
        "今回の作業内容を docs/decision_log.md に記録して、変更をコミットしてプッシュしてください。",
    )

    # ---- 13. プロンプト集 ----
    h1(doc, "13. よく使う依頼文（プロンプト）集")
    p(doc, "Claude Code への依頼は自由な日本語で構いませんが、定型文として以下が便利です。")
    table(
        doc,
        ["やりたいこと", "依頼文の例"],
        [
            [
                "最新状態への更新（毎回最初に）",
                "git pull して、プロジェクトを最新の状態にしてください。",
            ],
            [
                "新しい議事録からの知見抽出",
                "第12章の手順5の文をご利用ください。",
            ],
            [
                "抽出結果の手直し",
                "output の最新の xlsx の〇行目について、（修正内容）に修正して再生成してください。",
            ],
            [
                "現状の確認",
                "docs/decision_log.md を読んで、いま何が完了していて、次に何をすべきか教えてください。",
            ],
            [
                "作業記録と共有（毎回最後に）",
                "今回の作業内容を docs/decision_log.md に記録して、変更をコミットしてプッシュしてください。",
            ],
            [
                "分からないことの質問",
                "（なんでも日本語で質問できます。例：このプロジェクトでの「タグDB」の役割を教えて）",
            ],
        ],
    )

    # ---- 14. やってはいけないこと ----
    h1(doc, "14. やってはいけないこと")
    bullet(
        doc,
        "Notion の既存ページ・データベースを Claude Code 経由で編集・削除すること。"
        "このシステムは Notion を「読み取り専用」で使う設計です。書き込みを求められても許可しないでください。",
    )
    bullet(
        doc,
        ".env ファイルや Notion トークンを、メール・Slack・チャットに貼り付けて共有すること（パスワードと同じ扱いです）。",
    )
    bullet(
        doc,
        "docs/architecture.md（設計書の正本）、infra フォルダ、.github/workflows/deploy.yml の変更。"
        "変更が必要な場合は勝山に相談してください。",
    )
    bullet(
        doc,
        "Claude Code の許可確認で、内容が理解できない操作を許可すること。迷ったら No を選び、勝山に確認してください。",
    )
    bullet(
        doc,
        "エラーが出た状態で操作を繰り返すこと。同じエラーが2回出たら手を止めて勝山に連絡してください。",
    )

    # ---- 15. トラブルシューティング ----
    h1(doc, "15. 困ったときは（トラブルシューティング）")
    table(
        doc,
        ["症状", "対処"],
        [
            [
                "「git は認識されません」「claude は認識されません」等と表示される",
                "PowerShell をいったん閉じて開き直してください。それでも直らなければ該当ステップのインストールをやり直してください。",
            ],
            [
                "uv sync でエラーが出る",
                "インターネット接続を確認して再実行。直らなければエラーの画面を撮って勝山へ。",
            ],
            [
                "Notion 関連で「unauthorized」「401」等のエラーが出る",
                ".env のトークンが正しいか（前後に空白がないか）を確認。直らなければ勝山へ（トークンの再発行で解決することがあります）。",
            ],
            [
                "git pull で「conflict（競合）」と表示される",
                "そのまま触らず勝山に連絡してください（二人の変更がぶつかった状態です）。",
            ],
            [
                "Claude Code の応答が止まった・様子がおかしい",
                "Esc キーで中断できます。/clear で新しい会話を始めるか、PowerShell を閉じて起動し直してください。",
            ],
            [
                "ログインのブラウザ画面が開かない",
                "PowerShell に表示される URL を手動でブラウザに貼り付けて開いてください。",
            ],
        ],
    )
    p(doc, "上記で解決しない場合の連絡先：勝山（GitHub: bg-d-katsuyama）。移行期間中は遠慮なくご連絡ください。", bold=True)

    # ---- 16. 用語集 ----
    h1(doc, "16. 用語集")
    table(
        doc,
        ["用語", "意味"],
        [
            ["ターミナル / PowerShell", "文字でパソコンに指示を出す画面。スタートボタン右クリック→「ターミナル」で開く"],
            ["コマンド", "ターミナルに入力する指示文。この手順書ではグレーの枠で示している"],
            ["リポジトリ", "プログラムや文書の一式を保管する場所。GitHub 上に正本がある"],
            ["クローン", "GitHub のリポジトリを自分のパソコンにコピーすること"],
            ["git pull / プッシュ", "pull は最新を取り込むこと、プッシュ（push）は自分の変更を GitHub に送ること"],
            ["コミット", "変更内容に説明を付けて記録すること"],
            ["トークン", "システムにアクセスするための「鍵」。パスワードと同じ扱いで管理する"],
            [".env", "トークンなどの秘密情報を書いておく設定ファイル。共有・コミット禁止"],
            ["uv", "Python（プログラム実行環境）を自動で整えてくれる道具"],
            ["プロンプト", "Claude Code への依頼文のこと。日本語で自由に書いてよい"],
        ],
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUTPUT_PATH))
    print(f"saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
