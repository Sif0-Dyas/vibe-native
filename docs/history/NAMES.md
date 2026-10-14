# Product names

The package has been `vibenative` throughout; this is the name a user reads.

| When | Name | Notes |
|---|---|---|
| Predecessor (WSL) app | Vibedentify | Repository and folder `Vibe_Identify`; Python package `vibedentify` (`tools/make_oracle.py` imports it). |
| Phase 3, "one name, one version" | Vibe Identify | `PRODUCT_NAME` introduced and set to the two-word spelling. Config `%APPDATA%\Vibe Identify`, logs `%LOCALAPPDATA%\Vibe Identify`, taskbar id `VibeIdentify.App`, User-Agent `VibeIdentify/<version>`, installer `VibeIdentify-Setup-<version>.exe` installing `Vibe Identify.exe`. |
| Phase 5 (2026-10-13) | Vibedentify | Reversed. The old config folder's contents move on first start (`paths.move_legacy_config`); the installer removes the old exe and shortcuts on upgrade and both config folders on uninstall. |

Outside this folder the two-word name appears only where it must, to clean up
after it: `paths.LEGACY_APP_DIR_NAME` and the installer's `LegacyAppName`
(`tests/test_one_name.py` holds it to that).
