# Live Translator for YouTube

## v0.4.4: 話者境界で字幕を分割・確定後にラベル固定

話者分離表示を変更しました。

- 認識途中の字幕は `話者 ?` のまま表示し、Sortformerの暫定判定でA/Bを切り替えない
- 発話確定時にParakeetのトークン時刻とSortformerの話者境界を照合
- 1つの発話内で話者が交代していた場合は、その境界で字幕を複数ブロックへ分割
- 発話確定後の話者ラベルはロックし、その後の暫定判定では変更しない
- 分割前のpartial字幕は削除して重複表示を防止


## v0.4.3: 翻訳字幕のちらつき・再翻訳を抑制

翻訳処理を変更し、ASRのpartial更新ごとには翻訳しないようにしました。

- 認識途中: 原文のみリアルタイム更新
- 発話確定: Chrome Translatorへ1回だけ送信
- 翻訳完了: 翻訳文を固定
- 同じ確定発話の重複翻訳をキャッシュで防止
- Parakeet EOU debounceを960msから640msへ短縮

これにより、翻訳文が何度も書き換わって読めない問題を抑えつつ、翻訳開始までの待ち時間も短くしています。


YouTube Live のタブ音声をリアルタイム文字起こしし、Chrome の組み込み Translator API で翻訳字幕を動画上へ表示する Manifest V3 拡張です。

## v0.4.2: 会話内容から話者名・役割を推定

話者分離ON時に、会話内容とYouTubeページ情報から話者名・役割を推定できます。

- 会話中の自己紹介: `I'm Alice` / `My name is Bob`
- 2人会話の呼びかけ: `Thanks, Sarah` / `Welcome, Mike`
- Chrome Prompt APIが利用可能なら、直近の発話と配信タイトル・チャンネル名・概要欄をGemini Nanoへ渡して構造化推定
- 声紋や声質から人物を特定しない
- 確信度が低い場合は名前を断定しない

表示例:

```
[Alice]
This is the new model.
これは新しいモデルです。

[Bob?]
When will it ship?
いつリリースされますか？

[ホスト]
Let's take the next question.
次の質問に移りましょう。
```

確信度の目安:

- 0.90以上: `Alice`
- 0.65〜0.89: `Alice?`
- 名前に十分な根拠がない: `ホスト` / `ゲスト` / `インタビュアー`
- 推定不能: `話者 A`

初回は設定の **名前推定AIを準備** を押すと、Chrome内蔵Prompt API用モデルを準備できます。モデル未準備・非対応環境でも、明示的な自己紹介/呼びかけのルール推定は動作します。

## v0.4.1: 発話ごとの話者付き翻訳字幕

話者分離ON時は、字幕を「現在話者」1個で表示するのではなく、**各発話ごとのブロック**として保持します。

```
[話者 A]
This is the new model.
これは新しいモデルです。

[話者 B]
When will it ship?
いつリリースされますか？

[話者 A]
Probably next week.
おそらく来週です。
```

各発話は `utteranceId`、開始/終了時刻、原文、翻訳文、話者IDを持ちます。Sortformerの判定が後から来た場合も、その発話ブロックだけ `話者 ?` → `話者 A/B` に更新されます。画面には直近3発話を残します。

## v0.4: FluidAudio + Qwen3 ハイブリッド

ローカル音声認識を用途ごとに切り替えます。

- **英語ライブ**: FluidAudio / Parakeet EOU 120M (320 ms)
- **英語 + 話者分離**: FluidAudio / Parakeet EOU + Sortformer
- **日本語・中国語・その他多言語**: Qwen3-ASR MLX
- **クラウド保険**: Deepgram Nova-3
- **翻訳**: Chrome Translator API

デフォルトのローカルバックエンドは **自動** です。

```
英語
 └─ FluidAudio
     ├─ Parakeet EOU 320ms
     └─ Sortformer（話者分離ON時）

英語以外
 └─ Qwen3-ASR 0.6B 4-bit

ローカルサービス利用不可
 └─ Deepgram（APIキー設定時）
```

## v0.4 の追加機能

- FluidAudio / CoreML バックエンド
- Parakeet EOU 120M の低遅延英語STT
- Sortformer によるストリーミング話者分離
- 字幕へ **話者 A / B / C...** を表示
- ローカルバックエンドを設定から切替
  - 自動
  - FluidAudio
  - Qwen3-ASR
- 話者分離 ON / OFF
- FluidAudioモデルを設定画面から準備
- Qwen3環境をそのまま維持
- Deepgramフォールバックも維持
- 翻訳字幕サイズ 70〜180%
- ローカルAIのワンクリック起動

## 話者分離について

話者分離は FluidAudio の Sortformer を使います。

リアルタイム話者分離は文字起こしより少し遅れて判定されるため、本拡張では字幕そのものを待たせません。

```
音声
 ↓
Parakeet → 発話ID付き字幕をすぐ表示
 ↓
Chrome Translator → 同じ発話IDへ翻訳文を追加
 ↓
Sortformer → 少し遅れて話者判定
 ↓
該当する発話ブロックだけ「話者 ?」→「話者 A / B...」へ更新
```

そのため低遅延を維持しつつ話者を追跡できます。

現在、話者分離は **英語 + FluidAudio** の場合に有効です。

## ローカルモデル

### FluidAudio

標準:

- Parakeet EOU 120M
- chunk: 320 ms
- Apple Neural Engine / CoreML
- 英語向け

話者分離:

- Sortformer
- CoreML
- ストリーミング推定

FluidAudioのモデルは必要になった時点で設定画面の **モデル準備** からダウンロードします。

### Qwen3-ASR

macOS (MLX):

- バランス: `moona3k/mlx-qwen3-asr-0.6b-4bit`
- 高精度: `moona3k/mlx-qwen3-asr-1.7b-4bit`

Windows (PyTorch / Transformers):

- バランス: `Qwen/Qwen3-ASR-0.6B-hf`
- 高精度: `Qwen/Qwen3-ASR-1.7B-hf`

Qwen3-ASRは日本語・中国語を含む多言語と、専門用語 `context` 用として残しています。Windows初版の話者分離は未対応です。

## 構成

```
Chrome Extension
  │
  ├─ tabCapture
  │
  ├─ Chrome Translator API
  │
  └─ WebSocket
       ↓
127.0.0.1:8765
       │
       ├─ FluidAudio Swift bridge
       │    ├─ Parakeet EOU
       │    └─ Sortformer
       │
       ├─ Qwen3-ASR MLX (macOS)
       └─ Qwen3-ASR PyTorch + llama.cpp Gemma 4 (Windows)
```

### 主な技術

- Chrome Manifest V3
- `chrome.tabCapture`
- `chrome.offscreen`
- Native Messaging
- Python / aiohttp routing server
- MLX / Qwen3-ASR (macOS)
- Transformers Qwen3-ASR + llama.cpp Gemma 4 E4B (Windows)
- Swift / FluidAudio
- CoreML / Apple Neural Engine
- Chrome Translator API

## Chrome拡張の導入

```bash
git clone https://github.com/noppiki/youtube-live-translator.git
cd youtube-live-translator
```

Chromeで:

1. `chrome://extensions`
2. デベロッパーモード ON
3. 「パッケージ化されていない拡張機能を読み込む」
4. このリポジトリのフォルダを選択

manifestを更新した場合は拡張を再読み込みしてください。

## Apple Silicon Mac のローカルAI導入

### 推奨

拡張を一度Chromeへ読み込んでから、ポップアップの

**初回インストール / ローカルAI更新**

に表示されるコマンドをコピーして実行してください。

コマンドには現在のChrome拡張IDが自動で含まれます。

形式:

```bash
curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-macos.sh | bash -s -- YOUR_EXTENSION_ID
```

### インストーラが行うこと

- `uv`
- Python 3.12隔離環境
- Qwen3-ASR / MLX
- Qwen3-ASR 0.6Bモデル
- aiohttpローカルルーター
- FluidAudio Swift bridgeのビルド
- macOS LaunchAgent
- Chrome Native Messaging起動ヘルパー

主な配置先:

```
~/Library/Application Support/YouTubeLiveTranslator/
├── .venv/
├── server.py
├── backends/
├── bin/
│   └── fluid-bridge
├── fluid-bridge-src/
├── native/
└── logs/
```

FluidAudioモデルはFluidAudio標準のモデルキャッシュへ保存されます。

## Windows 10/11 x64 のローカルAI導入

拡張を一度Chromeへ読み込んでから、ポップアップのインストール欄に表示されるPowerShellコマンドを実行してください。

```powershell
irm https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/install-windows.ps1 -OutFile "$env:TEMP\ytlt-install.ps1"; & "$env:TEMP\ytlt-install.ps1" -ExtensionId 'YOUR_EXTENSION_ID'
```

インストーラが行うこと:

- `uv` と Python 3.12 隔離環境
- Qwen3-ASR 0.6B (Transformers)
- Gemma 4 E4B Q4_0 (llama.cpp)
- NVIDIA CUDA 優先、なければ Vulkan、最後に CPU
- ログイン時自動起動 (Task Scheduler)
- Chrome Native Messaging 登録
- `http://127.0.0.1:8765/health` が 200 になるまで確認

配置先:

```
%LOCALAPPDATA%\YouTubeLiveTranslator\
├── .venv\
├── server.py
├── backends\
├── bin\llama-server.exe
├── models\
├── native\
└── logs\
```

Windows初版ではFluidAudioと話者分離は使いません。CPUのみの場合はポップアップに性能警告を出します。

## v0.3以前から更新する場合

```bash
cd ~/dev/youtube-live-translator
git pull
```

1. `chrome://extensions` で拡張を再読み込み
2. 拡張を開く
3. **初回インストール / ローカルAI更新** のコマンドを再実行
4. **ローカルAI起動**
5. **接続テスト**
6. 英語ライブなら FluidAudio を選択
7. 初回だけ **モデル準備**

既存のQwen3-ASR環境はそのまま利用できます。

## 設定

### 音声認識

- **自動**: ローカルAI → Deepgram
- **ローカルのみ**
- **Deepgramのみ**

### ローカルバックエンド

- **自動**
  - 英語 → FluidAudio
  - その他 → Qwen3
- **FluidAudio**
  - 英語専用
  - 話者分離対応
- **Qwen3-ASR**
  - 多言語
  - context対応

### 話者分離

```
☐ 話者分離（FluidAudio Sortformer）
```

有効時は字幕に以下のように表示します。

```
[話者 A]
This is the new model.
これは新しいモデルです。

[話者 B]
When will it ship?
いつリリースされますか？
```

話者IDは配信中の推定IDで、実名識別ではありません。

### 翻訳字幕サイズ

70〜180%を10%刻みで変更できます。

設定は `chrome.storage.local` に保存し、開いているYouTubeへ即時反映します。

### 固有名詞・専門用語

Qwen3-ASR使用時は入力内容を `context` に渡します。

例:

```
OpenAI
Anthropic
Claude
Gemini
Cursor
Codex
MCP
NVIDIA
```

## ローカルAPI

### Health

```bash
curl http://127.0.0.1:8765/health
```

FluidAudio bridgeが利用可能かも返します。

### Models

```bash
curl http://127.0.0.1:8765/models
```

### Streaming

```
ws://127.0.0.1:8765/stream
```

入力:

- PCM16
- mono
- 16 kHz

## アンインストール

```bash
curl -fsSL https://raw.githubusercontent.com/noppiki/youtube-live-translator/main/scripts/uninstall-macos.sh | bash
```

## セキュリティ

- ローカルサーバーは `127.0.0.1` のみにbind
- Native Messaging hostはインストール時に渡されたChrome拡張IDだけを許可
- Native Messaging helperが行う操作はローカルAI LaunchAgentの状態確認・起動のみ
- Deepgram APIキーは `chrome.storage.local` 保存
- 共有APIキーを拡張へ埋め込まない

## 制限

- FluidAudioの低遅延バックエンドは現在英語向け
- 話者分離はリアルタイム推定なので誤判定することがある
- 話者判定は字幕より後追いになる
- Qwen3経路では現在話者分離なし
- 初回FluidAudioモデル準備にはモデルダウンロードが必要
- 現在のローカルインストーラはApple Silicon Mac向け

## 今後

- YouTube公式ライブ字幕が存在する場合はSTTを省略
- 話者名の手動割当
- 話者ごとの字幕履歴
- 話者ラベル表示ON/OFF
- 原文字幕ON/OFF
- 字幕位置・背景透明度
- SRT / VTT出力
- Twitch / X Live対応
- Windows向けローカルエンジン

## Third-party components

This project can use:

- FluidAudio
- Parakeet EOU
- Sortformer
- Qwen3-ASR
- Deepgram
- Chrome Translator API

Please review the upstream model/library licenses before redistribution.

## License

MIT License. See [`LICENSE`](LICENSE).
