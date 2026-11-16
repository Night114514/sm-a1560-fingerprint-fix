# SM-A1560：使用者真機測試回報

**結果：`FINGERPRINT_FIX_CONFIRMED`，僅限回報的裝置與配置。**

本紀錄由專案使用者透過對話提供，收錄日期為 **2026-11-16（UTC）**。這是收錄日期；使用者未提供實際測試日期。Codex 沒有直接操作或獨立觀察裝置。本次回報未附原始日誌或截圖。

## 測試配置與結果

| 項目 | 使用者回報 |
|---|---|
| 裝置 | Samsung Galaxy A15 5G (SM-A1560) |
| Stock Vendor | One UI 7 / Android 15 |
| Bootloader | `A1560ZHS6CYH2` |
| GSI | LineageOS 22.2 GApps EXT4 |
| Release | [`phase2-los22.2-20260105-rro1`](https://github.com/Night114514/sm-a1560-fingerprint-fix/releases/tag/phase2-los22.2-20260105-rro1) |
| 安裝方式 | DSU Sideloader + Shizuku |
| RRO enabled | PASS |
| RRO resource override | PASS |
| Fingerprint enrollment | PASS |
| Fingerprint unlock | PASS |
| Result | `FINGERPRINT_FIX_CONFIRMED` |
| Scope | Tested device and configuration only |

此回報支持指定配置的指紋登記與解鎖成功，不擴及其他裝置、Bootloader、Vendor、GSI 版本、永久刷寫方式或長期使用情境。AIDL sensor/session、generateChallenge 及 runtime idmap 的逐項追蹤未隨回報提供，因此不將它們另行標記為已獨立驗證。

## 對應發布檔

對應 Release 的 `system.img.xz` 公開 SHA-256 為：

```text
4a8641bd3557eb64abb2933742be320932cb821a5724a848994bc88a7a816b02
```

這是已發布附件的雜湊，並非使用者另行提供的手機端檔案量測。本次收錄不重新構建、不更換發布附件，也不變更其 SHA-256。Release 內既有測試報告與原始碼套件維持發布時的離線驗證快照；目前結果以本紀錄及倉庫中的[第二階段報告](phase2-report.md)為準。

結構化紀錄：[validation/device-tests/sm-a1560-rro1.json](../validation/device-tests/sm-a1560-rro1.json)。

## 使用者原文

```text
Device: Samsung Galaxy A15 5G (SM-A1560)
Stock Vendor: One UI 7 / Android 15
Bootloader: A1560ZHS6CYH2
GSI: LineageOS 22.2 GApps EXT4
Release: phase2-los22.2-20260105-rro1
Installation: DSU Sideloader + Shizuku

RRO enabled: PASS
RRO resource override: PASS
Fingerprint enrollment: PASS
Fingerprint unlock: PASS

Result: FINGERPRINT_FIX_CONFIRMED
Scope: Tested device and configuration only
```
