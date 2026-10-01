# Live Translator for YouTube

YouTube Live のタブ音声をリアルタイム文字起こしし、Chrome の組み込み Translator API で翻訳字幕を動画上へ表示する Manifest V3 拡張です。

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

- バランス: `moona3k/mlx-qwen3-asr-0.6b-4bit`
- 高精度: `moona3k/mlx-qwen3-asr-1.7b-4bit`

Qwen3-ASRは日本語・中国語を含む多言語と、専門用語 `context` 用として残しています。

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
       └─ Qwen3-ASR MLX
```

### 主な技術

- Chrome Manifest V3
- `chrome.tabCapture`
- `chrome.offscreen`
- Native Messaging
- Python / aiohttp routing server
- MLX / Qwen3-ASR
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
├── bin/
│   └── fluid-bridge
├── fluid-bridge-src/
├── native/
└── logs/
```

FluidAudioモデルはFluidAudio標準のモデルキャッシュへ保存されます。

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
