# data/drive_input — Drive 手動配置フォルダ

Google Drive からダウンロードしたファイルをこのフォルダに置いてください。
Google API・GCP は一切使いません。ここに置かれたファイルを Claude Code が直接読み、
土壌 R&D マスターデータの知見抽出に使います。

## 置けるファイル形式（想定）
- PDF（`.pdf`）
- Word（`.docx`）
- テキスト / Markdown（`.txt` / `.md`）
- PowerPoint（`.pptx`）※必要なら対応追加

## 使い方
1. Drive からファイルをダウンロードしてこのフォルダに置く
2. Claude Code に「drive_input のファイルを取り込んで」と伝える
3. 抽出結果は `output/` に xlsx / CSV で出力される

※ このフォルダの中身（README 以外）は Git にコミットしません（`.gitignore` 管理）。
