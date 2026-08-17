# SkyBlock Local Profile Connector

[日本語 README](README.md)

A Windows-only local utility that retrieves your own SkyBlock profile from the Hypixel Public API only when requested. It converts the response into structured JSON that can be analyzed by a local AI assistant or personal scripts.

This project is not affiliated with or endorsed by Hypixel, Inc. Use it in accordance with the [Hypixel API Policy](https://developer.hypixel.net/policies/).

## For Hypixel API reviewers

This is a working, local-only, read-only utility for the developer's own SkyBlock profile. It makes an authenticated profile request only when the developer manually runs `fetch`; it does not continuously poll players, provide session tracking, or retain profile history. The API key stays in Windows Credential Manager and is never written to source code, configuration JSON, snapshots, or logs. Static Resources API responses are cached for 24 hours.

## Features

- No management interface, web server, or background process.
- Stores the API key in Windows Credential Manager.
- Never writes the API key to source code, configuration JSON, snapshots, or standard output.
- Does not store the API key in a plaintext `.env` file.
- Retrieves the profile only when `fetch` is run manually.
- Does not retain profile history; it overwrites a single latest snapshot.
- Does not save raw Hypixel API responses.
- Caches only item names and Fishing level requirements from the official Resources API for 24 hours.

## Snapshot contents

- Armor, Equipment, Inventory, and Ender Chest
- Accessory Bag, Fishing Bag, and Sack of Sacks
- Sack item counts with official display names
- Fishing XP, current level, and XP remaining until the next level
- Purse and Bank balances
- Remaining API rate limit

SkyBlock inventory data is returned as base64-encoded, gzip-compressed NBT. The connector decompresses and parses that data locally.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or later
- An API key issued through the Hypixel Developer Dashboard

## Initial setup

### 1. Store the API key

Double-click `setup-key.cmd`, or run:

```powershell
py skyblock_connector.py setup-key
```

Enter the API key twice. The input is hidden. Do not paste the key into chats, GitHub, websites, or public mods.

The connector deliberately avoids `.env` because it is a plaintext file that can be accidentally committed or included in backups. The key remains in Windows Credential Manager and is retrieved through the operating system only when needed.

### 2. Store the target profile locally

```powershell
py skyblock_connector.py setup-profile
```

Enter the Minecraft player name, UUID, and an optional SkyBlock profile name. Leave the profile name empty to use the currently selected profile. These settings are stored under `%LOCALAPPDATA%\HypixelSkyBlockConnector` and are never added to the repository.

## Usage

Fetch the latest profile data:

```powershell
py skyblock_connector.py fetch
```

On success, the following file is overwritten:

```text
%LOCALAPPDATA%\HypixelSkyBlockConnector\latest.json
```

Check snapshot status:

```powershell
py skyblock_connector.py status
```

Test connectivity to a public endpoint without an API key:

```powershell
py skyblock_connector.py doctor
```

Delete the stored API key:

```powershell
py skyblock_connector.py delete-key
```

## API usage policy

- Intended for local use by an individual developer or a small private group.
- Does not continuously poll player data or provide session or historical tracking.
- Avoids repeated short-interval requests and caches Resources API responses for 24 hours.
- Uses a Development Key only during development; long-term use requires a Personal API Key.
- Does not use multiple keys to bypass rate limits.

## Tests

```powershell
py -m unittest -v
```

The tests use only fictional profiles, UUIDs, and NBT data. They do not contain real API keys or profile data.
