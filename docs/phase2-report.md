# SM-A1560：第二階段 GSI 測試報告

已製作供真機測試的 LineageOS 22.2 / 20260105 GApps EXT4 ARM64 A/B GSI，離線檢查已通過。**後續使用者真機回報：`FINGERPRINT_FIX_CONFIRMED`，僅限 SM-A1560 / One UI 7 Android 15 Vendor / Bootloader `A1560ZHS6CYH2` / Release `phase2-los22.2-20260105-rro1`。** RRO 啟用、資源覆寫、指紋登記及解鎖均回報 PASS，完整來源與範圍見[真機紀錄](device-test-sm-a1560-rro1.md)。

Release 附件 `TEST-REPORT.md`、`WINDOWS-DSU.md` 與原始碼套件保留發布時的離線驗證快照；其中「尚無真機結果」描述的是當時狀態。此次只更新倉庫文件與 Release 說明，所有發布附件與雜湊維持不變。

[下載 Release](https://github.com/Night114514/sm-a1560-fingerprint-fix/releases/tag/phase2-los22.2-20260105-rro1) · [Git Repository](https://github.com/Night114514/sm-a1560-fingerprint-fix) · [Windows 安裝與驗證](windows-dsu-phase2.md) · [完整構建方式](phase2-build.md)

## 交付雜湊

| 產物 | 大小（bytes） | SHA-256 |
|---|---:|---|
| `system.img.xz` | 1,160,448,988 | `4a8641bd3557eb64abb2933742be320932cb821a5724a848994bc88a7a816b02` |
| 解壓後的 `system.img` | 3,340,144,640 | `6d2cb3f536d675dc85dd891a751c46f24d229bd1770f000a69ef23e46507b83f` |
| 內置 `SmA1560FingerprintFix.apk` | 8,604 | `4950eecf4aab9ab7ea8f9b46eac5ccb8f144974208af391aaa587e9e53efd9c9` |

XZ 使用 LZMA2 preset 6、8 MiB dictionary、CRC64。已執行 xz test 並完整解壓，確認解壓大小、SHA 與經 verify.sh 驗證的 raw 映像完全相同；寫出磁碟後的壓縮檔 SHA 也相同。

交付使用全映像比較所得的 45 個 4 KiB 差異區塊（137,067-byte 差異包），由 GitHub Actions 重組已驗證的相同位元組，再要求 raw 與 XZ SHA 都與本表完全一致才上傳草稿；不是另一個未核對雜湊的重建版本。

## 來源與 Git 保存

原版來自 [MisterZtr / LineageOS / Android 15](https://sourceforge.net/projects/misterztr-gsi/files/LineageOS/Android%2015/)，精確檔名 `LineageOS-22.2-20260105-GAPPS-EXT4-GSI.7z`，1,127,244,589 bytes。上游 SHA-1 `abf4270323de66ffeb9f9b6cc065669b04dad2a6` 與解壓 CRC32 `891C44A8` 均吻合。

- 7z SHA-256：`cf4992731f0fbb2a3d09fffeb16ed4f16ad8c023b38427cdc12a0818bc55c7c4`。
- 原版 raw SHA-256：`cd3599e056ba82bc19379fbca7e81ee572589e0dd81b75092c1fee1691a077b7`；修補後重新讀取仍相同，原版保留為唯讀。
- 實際屬性為 Android 15 / SDK 35、`arm64-v8a`、`tdgsi_arm64_ab`、LineageOS `22.2-20260105-GAPPS-EXT4-GSI`。工具 ELF64/AArch64 及上游 A/B 限定 README 均已核對。
- [第一階段 commit](https://github.com/Night114514/sm-a1560-fingerprint-fix/commit/ea409798df76366ff8e3dc76fe16fe53406e2ea5) 保存原始碼、APK、腳本及當時驗證紀錄；已從 GitHub 回讀 APK，比對 SHA 一致。
- 本映像的構建程式碼 revision：[`d053e04d9c2a`](https://github.com/Night114514/sm-a1560-fingerprint-fix/commit/d053e04d9c2a0f398803de0a71d2efaa5d7843fc)。倉庫原有初始 commit 也保留在合併歷史中，未 force-push。

## 變更範圍及 RRO

唯一新增的設定覆寫是 `android:array/config_biometric_sensors` 長度 0；APK 只有 array 及 explicit mapping XML，無程式碼與其他配置覆寫。

- Runtime 路徑：`/system_ext/overlay/SmA1560FingerprintFix/SmA1560FingerprintFix.apk`；本映像內對應 `/system/system_ext/overlay/...`。
- `targetPackage=android`、target SDK 35、`isStatic=true`、priority 999。實際 framework 無 overlayable 群組，預載 system_ext 符合 system policy。
- 原版該分區沒有 config.xml，故沿用 manifest 的開機啟用／不可變設定，沒有新建 config。未發現自訂 partition_order.xml；映像內 529 個 product/system_ext RRO 的 compiled resources 已掃描，未發現阻擋此放置方式的競爭者。
- 沒有停用、刪除 MediaTek 原 overlay，也沒有修改其他 Vendor 配置。手機 Vendor、boot、vbmeta 分區未被操作。
- 新目錄 0755、APK 0644、uid:gid 0:0。實際 file_contexts 對應 **`u:object_r:vendor_overlay_file:s0`**，已寫入並讀回 xattr，與既有 overlay directory 一致。

原版 Android 15 ARM64 idmap2 與 libraries 由來源 GSI 提取，在 QEMU 中執行。沒有 x86_64 Linux host idmap2，也沒有啟動 Android runtime。實際成功映射只有：

```text
0x01070028 -> 0x7f010000 (array/config_biometric_sensors -> array/config_biometric_sensors)
```

這次沒有使用 `--ignore-overlayable` 或 `--allow-unverified-idmap`。public-only policy 的負向檢查無法取得此映射。

## EXT4、AVB 與完整性

原版有 AVB footer；預設 raw 修補會拒絕它。本次明確啟用同 key 模式，只在副本重建 **system.img 內的** AVB tree、FEC、root digest 及簽章。沒有產生或刷寫獨立 vbmeta.img。

- 輸入與輸出 raw 大小均為 **3,340,144,640 bytes**，EXT4 data 部分均為 3,287,355,392 bytes；block size 4096，filesystem geometry 不變。
- e2fsck -f -n 前後皆退出 0。inode 使用量 8714 → 8716，block 使用量 794335 → 794339，符合新增一個目錄及 APK。
- 已比較既有 system_ext RRO、framework-res.apk 與使用的 SELinux contexts，共 6 條既有路徑；內容 SHA、inode/mode/owner 與 xattr 保持一致。未聲稱對整張映像所有檔案逐一鑑識。
- AVB algorithm **SHA256_RSA2048**、原公鑰、salt、rollback index **1764547200**、rollback location 0、flags 0、properties、release string 與 AVB/FEC 幾何均維持原值；未停用 verity。
- 公鑰 SHA-256：`22de3994532196f61c039e90260d78a93a4c57362c7e789be928036e80b77c8c`；與原版完全一致，對應公開 AOSP RSA2048 測試 fixture。
- Hashtree root digest 原值 `af2d84b2cf86acfc717eecde4c6d0c5f6cf6d24540d1da005dfe6c603b0a3250`，修補後 `83801435ae4b5e366b0e33fad86f708c4bc21d02dfc529126097a8cd48991cab`。
- 原版所有 **26,198,016 bytes FEC parity** 已重新生成並逐位元組匹配；新映像的 FEC 再次完整核對。FEC adapter 使用 AOSP interleave 與 libfec RS encoder，不冒稱完整 Android fec CLI。
- AOSP avbtool 驗證新簽章與 SHA-256 hashtree 成功；verify.sh 對完成的 raw 映像再次檢查，RRO、metadata、EXT4、AVB、FEC 皆通過。

雲端只有約 7 GB 可用磁碟且不支援 reflink，因此壓縮採 sealed RAM staging。完整 XZ 與解壓雜湊通過後才清理新 raw 副本；原版 raw 映像保留不改。已校驗的可重下載 .7z/工具下載快取曾為磁碟預算清理，來源 URL 與雜湊完整記錄。

## 驗證紀錄與實際限制

`validation/phase2/` 保存來源、架構、工具 SHA、原版 AVB、原版 FEC、真實映像 receipt、前後 e2fsck、RRO/idmap、完整重查及 XZ 紀錄。另有原有 integration regression、同 key 簽章 fixture、不同金鑰拒絕、FEC 損壞偵測、壓縮與原版保護測試；Bash/ShellCheck/Python/C++ 檢查通過。

獨立執行 idmap2 時沒有 Android 產生的 linker config，工具有相關警告但成功完成映射。主機 libselinux 對兩條含 `\d` 的規則提示回退 regex matching；實際標籤匹配與 xattr 讀回均成功。這些不是手機的 log。

DSU 的離線輸入結構已核對：raw EXT4、system partition 名稱、原大小、原公鑰信任條件及合法 XZ 容器皆成立。後續使用者回報以 DSU Sideloader + Shizuku 安裝此 Release，並完成指紋登記與解鎖；這是指定配置的真機回報，並非從離線結果推定。

本次回報的四項結果為 PASS：RRO enabled、RRO resource override、Fingerprint enrollment、Fingerprint unlock。Codex 沒有直接操作裝置；回報未附原始日誌或截圖，也未提供 AIDL/default sensor/session、generateChallenge 或 runtime idmap 的逐項紀錄。這些細項不另行標記為已獨立驗證。Windows/PowerShell 收集腳本也沒有新增執行證據。

其他裝置、Bootloader、Vendor 或 GSI 版本仍須依 [Windows DSU 步驟](windows-dsu-phase2.md) 各自測試；本次成功不能外推至未測試的配置。
