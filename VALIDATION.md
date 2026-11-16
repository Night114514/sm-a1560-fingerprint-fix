# 本次實際驗證紀錄

執行環境：選定的 Codex Cloud Linux 預設環境，Debian GNU/Linux 13、x86_64；工作檔全部在 workspace。未連接手機，未提供原版 LineageOS GSI。

## 已交付 APK

`dist/SmA1560FingerprintFix.apk`，8,604 bytes。

```text
SHA-256 4950eecf4aab9ab7ea8f9b46eac5ccb8f144974208af391aaa587e9e53efd9c9
```

實驗簽署憑證 SHA-256：`b1b39dd96a0d48fd4c40195fb8c19114bcf09786c0fa54d832c39adf8d2ebb65`。不是平台簽章。私鑰不在交付檔內。

實際執行 `apksigner verify --verbose --print-certs` 通過；此 min SDK 29 APK 的報告顯示 v3 verified。報告的其他 scheme 沒有顯示 verified，沒有宣稱逐一驗證所有簽章 scheme。ZIP CRC 及 zipalign 4-byte 檢查也通過。

編譯後讀回：

```text
resource 0x7f010000 array/config_biometric_sensors
  () (array) size=0
    []
resource 0x7f020000 xml/overlays
```

compiled XML 僅一筆 `array/config_biometric_sensors → @0x7f010000`。這是 APK 自身的資源 ID，未假定它等於實際 GSI 的 framework private ID。無 DEX、native library、其他配置覆寫。完整輸出在 `dist/apk-verification/`。

## 已執行與未執行

| 項目 | 本次結果與界線 |
|---|---|
| Android 15 與 LineageOS 22.2 程式碼查閱 | 完成；固定 revision 及保存來源見 `docs/` |
| build.sh 實際構建 | 通過，最後一次退出 0 |
| 乾淨來源目錄、沒有既有 work/dist 的獨立構建 | 通過；從另一工作目錄呼叫也成功；新 keystore 的 APK 雜湊不同是預期行為 |
| APK ZIP/簽章/對齊/compiled array/explicit mapping | 通過 |
| Bash 語法、ShellCheck 0.10.0 | 通過，退出 0、無診斷 |
| Python 語法 | 通過 |
| 合成 raw EXT4 平面布局修補與輸出讀回 | 通過；含同資源的較低優先級 RRO |
| 合成 `/system` 巢狀布局及既有 OverlayConfig | 通過；保留註解及既有項目，新增條目位於 immutable 區末端 |
| SELinux xattr、owner/mode、既有檔案保護 | 合成 EXT4 測試通過；使用 GSI 形式的 file_contexts 和 libselinux matcher |
| 輸入 SHA 不變、輸出 SHA、e2fsck -fn | 合成 EXT4 測試通過 |
| 原生 Android 15 Linux host idmap2 | **未安裝／未執行**；只有邏輯映射與政策檢查 |
| 真實原版 GSI 修補與完整性 | **原版未提供，沒有真實 GSI 產物或其雜湊** |
| 真機 runtime idmap／overlay 最終順序／AIDL challenge／登記 | **全部未測試** |
| Windows PowerShell 收集腳本 | 已提供，但此 Linux 環境沒有 PowerShell，未實際執行 |
| 可選 setup-sdk.sh | 語法與 ShellCheck 通過；本次使用等效的手動下載／校驗／解壓流程，未另跑這個下載腳本 |

已執行的拒絕條件測試：既有輸出、輸出內容被改動、同分區 priority 999 的競爭 RRO、自訂 partition_order.xml、缺少 security.selinux、缺少原生 idmap2 的正式模式、Android sparse、非 EXT4、AVB footer、shared_blocks feature、含 merge 的 config、immutable 在 mutable 之後的 config。這些情況均未發布完成的修補映像；測試輸入 SHA 保持不變。

合成映像的最後一輪 input/output SHA 在 `validation/result.json`，e2fsck 與讀回結果收錄於對應 patch/verify logs。合成映像於測試後刪除，**不在交付檔內，也不可當作 ROM 使用**。這些 SHA 不是使用者 GSI 的 SHA。

## 實際工具與依賴處理

初始環境已有 Java 21、Python、curl、unzip；沒有 Android SDK、e2fsprogs、ShellCheck、host idmap2 或 javac。沒有修改 sudo／sandbox 設定或主機系統套件目錄。

- OpenJDK 21.0.13，Python 3.12.14。
- Google 官方 Build Tools 35.0.0：aapt2 `2.19-11948202`、apksigner `0.9`、zipalign；Platform 35 revision 2。
- SDK 兩個 zip 的 SHA-1 與 Google repository metadata 相符，並記錄 SHA-256；setup-sdk.sh 固定相同 SHA-256。
- Debian 13 e2fsprogs 1.47.2-3+b12，以及 libext2fs2t64、libss2；由 Debian 官方 pool 下載 .deb，`dpkg-deb -x` 解到 workspace 工具目錄，以 PATH 和 LD_LIBRARY_PATH 使用。
- ShellCheck 0.10.0-1 同樣解到 workspace。
- libselinux.so.1 由環境既有系統庫提供，Python 使用 ctypes 呼叫，不需 pip SELinux 模組。

Debian 13 的免 root 解包方式（其他 Linux 請使用其原生套件版本，不要任意套用不同 glibc 發行版的 binary）：

```bash
mkdir -p work/debs work/e2fs
cd work/debs
curl -fLO 'https://deb.debian.org/debian/pool/main/e/e2fsprogs/e2fsprogs_1.47.2-3+b12_amd64.deb'
curl -fLO 'https://deb.debian.org/debian/pool/main/e/e2fsprogs/libext2fs2t64_1.47.2-3+b12_amd64.deb'
curl -fLO 'https://deb.debian.org/debian/pool/main/e/e2fsprogs/libss2_1.47.2-3+b12_amd64.deb'
# 先依 validation/checks.json 的 download_sha256 核對這三個檔案，再解包：
for p in ./*.deb; do dpkg-deb -x "$p" ../e2fs; done
cd ../..
export PATH="$PWD/work/e2fs/usr/sbin:$PATH"
export LD_LIBRARY_PATH="$PWD/work/e2fs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
debugfs -V
```

所有下載的 SHA-256、工具版本及執行退出碼在 `validation/checks.json`。SDK 及 Debian binary 不隨專案重新分發；保存的 AOSP/LineageOS 原始碼保留上游版權與 Apache 授權。

README 的真機通過條件仍是最後關卡：確認有效空陣列與真實 AIDL 感測器，完成指紋登記，再實際驗證。此交付只完成可獨立構建與離線檢查的修復實驗專案。
