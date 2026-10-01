# Live Translator for YouTube

YouTube Live のタブ音声を Chrome 拡張から取得し、Deepgram Nova-3 でリアルタイム文字起こし、Chrome の組み込み Translator API で翻訳して動画上へ字幕表示する Manifest V3 拡張です。

## 現在の構成

- 音声取得: `chrome.tabCapture`
- 長時間音声処理: `chrome.offscreen`
- STT: Deepgram Streaming STT / Nova-3
- 翻訳: Chrome Translator API（オンデバイスの言語パック）
- 字幕描画: YouTube ページ上の content script
- 入力音声は 16 kHz / mono / Linear16 に変換して WebSocket 送信

## 必要環境

- デスクトップ版 Chrome 138 以降
- Deepgram API キー
- YouTube (`https://www.youtube.com/`)

Chrome Translator API は初回使用時に対象言語のモデル/言語パックをダウンロードする場合があります。

## インストール

1. Chrome で `chrome://extensions` を開く
2. 右上の「デベロッパー モード」を ON
3. 「パッケージ化されていない拡張機能を読み込む」
4. このフォルダ `youtube-live-translator` を選択
5. YouTube Live を開く
6. 拡張ボタンを押す
7. Deepgram API キーを入力
8. 「翻訳開始」

## 注意: API キー

この MVP は個人利用を最短で試すため、Deepgram API キーを `chrome.storage.local` に保存し、ブラウザ WebSocket の `Sec-WebSocket-Protocol` で Deepgram に渡します。

Chrome Web Store などで第三者へ配布する版では、固定 API キーを拡張へ入れてはいけません。バックエンドから短期トークンを発行する構成へ変更してください。

## ライブ字幕の動作

Deepgram では `interim_results=true` を使い、発話途中の暫定字幕を表示します。`endpointing` はポップアップから 220 / 350 / 500 ms を選択できます。

- 220ms: 最速、細切れになりやすい
- 350ms: バランス
- 500ms: 自然、少し遅い

## 次に入れたい機能

- YouTube に公式ライブ字幕がある場合は STT を使わず直接翻訳
- Deepgram の短期トークン発行サーバー
- 原文字幕 ON/OFF
- 字幕位置・文字サイズ・背景透明度
- Twitch / X Live / その他サイト対応
- 文脈バッファ付き自然翻訳モード
- 字幕ログ保存 / SRT・VTT 出力

## 権限

- `activeTab`: ユーザーが開始した現在の YouTube タブを対象にする
- `tabCapture`: タブ音声を取得
- `offscreen`: バックグラウンドで Web Audio を維持
- `storage`: 設定保存
- host permissions: YouTube と Deepgram のみ

## License

MIT License. See [`LICENSE`](LICENSE).
