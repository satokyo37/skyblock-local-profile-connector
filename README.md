# SkyBlock Local Profile Connector

[English README](README.en.md)

Hypixel Public APIから、自分のSkyBlockプロフィールを必要なときだけ取得するWindows向けローカルツールです。取得結果をJSONへ整形し、ローカルのAIアシスタントや個人用スクリプトから解析しやすくします。

Hypixel, Inc.とは提携・協賛関係にありません。利用時は[Hypixel API Policy](https://developer.hypixel.net/policies/)に従ってください。

## For Hypixel API reviewers

This is a working, local-only, read-only utility for the developer's own SkyBlock profile. It makes an authenticated profile request only when the developer manually runs `fetch`; it does not continuously poll players, provide session tracking, or retain profile history. The API key stays in Windows Credential Manager and is never written to source code, configuration JSON, snapshots, or logs. Static Resources API responses are cached for 24 hours.

## 特徴

- 管理画面、サーバー、常駐処理はありません。
- APIキーはWindows資格情報マネージャーへ保存します。
- APIキーをソースコード、設定JSON、スナップショット、標準出力へ書き出しません。
- APIキーを平文で保存する`.env`ファイルは使用しません。
- プロフィールは手動で`fetch`したときだけ取得します。
- プレイ履歴は蓄積せず、最新の整形済みスナップショット1件だけを上書きします。
- Hypixel APIレスポンスの生データは保存しません。
- アイテム名とFishingレベル表だけは公式Resources APIから取得し、24時間キャッシュします。

## 取得内容

- Armor、Equipment、Inventory、Ender Chest
- Accessory Bag、Fishing Bag、Sack of Sacks
- Sack内のアイテム数と公式表示名
- Fishing XP、現在レベル、次のレベルまでの残りXP
- Purse、Bank
- APIレート制限の残量

SkyBlockのインベントリデータはbase64・gzip圧縮NBTとして返されるため、このツール内で展開・解析します。

## 必要環境

- Windows 10またはWindows 11
- Python 3.11以上
- Hypixel Developer Dashboardで発行されたAPIキー

## 初期設定

### 1. APIキーを保存

`setup-key.cmd`をダブルクリックするか、次を実行します。

```powershell
py skyblock_connector.py setup-key
```

APIキーを2回入力します。入力内容は画面に表示されません。キーはチャット、GitHub、Webサイト、公開MODへ貼り付けないでください。

`.env`は通常のテキストファイルであり、誤ってGitやバックアップへ含める危険があるため使用しません。APIキーはWindows資格情報マネージャー内に保存し、実行時だけOS経由で読み出します。

### 2. 取得対象を保存

```powershell
py skyblock_connector.py setup-profile
```

Minecraftプレイヤー名、UUID、任意のSkyBlockプロフィール名を入力します。プロフィール名を空欄にすると、現在選択中のプロフィールを使います。この設定は`%LOCALAPPDATA%\HypixelSkyBlockConnector`に置かれ、リポジトリには入りません。

## 利用方法

最新データを取得します。

```powershell
py skyblock_connector.py fetch
```

成功すると、次のファイルが上書きされます。

```text
%LOCALAPPDATA%\HypixelSkyBlockConnector\latest.json
```

状態確認:

```powershell
py skyblock_connector.py status
```

キー不要の公式API接続診断:

```powershell
py skyblock_connector.py doctor
```

保存済みAPIキーの削除:

```powershell
py skyblock_connector.py delete-key
```

## API利用方針

- 個人または少人数のローカル利用を想定しています。
- プレイヤーデータの連続ポーリング、セッショントラッキング、履歴サービスには使用しません。
- 同じデータの短時間再取得を避け、Resources APIは24時間キャッシュします。
- Development Keyは開発確認にだけ使用し、長期利用ではPersonal API Keyを申請してください。
- APIキーを複数作成してレート制限を回避しないでください。

## テスト

```powershell
py -m unittest -v
```

テスト用NBTは架空のプロフィールとUUIDだけを使用します。実APIキーや実プロフィールデータは含みません。
