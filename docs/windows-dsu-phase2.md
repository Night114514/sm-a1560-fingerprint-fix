# Windows：安裝 SM-A1560 指紋 RRO 實驗版 GSI

目標：Galaxy A15 5G SM-A1560、One UI 7 / Android 15 Vendor、ARM64 A/B、已解鎖 Bootloader、無 Root。已收到[使用者真機成功回報](device-test-sm-a1560-rro1.md)：Bootloader `A1560ZHS6CYH2` 搭配 Release `phase2-los22.2-20260105-rro1`，透過 DSU Sideloader + Shizuku 測試，RRO 啟用／覆寫、指紋登記及解鎖均為 PASS。成功範圍僅限該裝置與配置；其他配置仍須各自驗證。

## 下載與檔案核對

由 [本專案 GitHub Releases](https://github.com/Night114514/sm-a1560-fingerprint-fix/releases) 下載 `system.img.xz`、`SHA256SUMS`、測試報告及本文件。使用 Release 的測試版本；不要用 SourceForge 的 latest 取代指定基底。

在放置這些檔案的 PowerShell 目錄核對：

```powershell
$entry = Get-Content .\SHA256SUMS | Where-Object { $_ -match '\s+system\.img\.xz$' }
if (@($entry).Count -ne 1) { throw "SHA256SUMS 中找不到唯一的 system.img.xz" }
$expected = ($entry -split '\s+')[0].ToUpperInvariant()
$actual = (Get-FileHash .\system.img.xz -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw "SHA-256 不一致，停止安裝" }
"SHA-256 OK: $actual"
```

XZ 完整解壓後的 system.img 大小應為 **3,340,144,640 bytes**；它在發布前已通過完整解壓雜湊比對。Windows 端不必先解壓，DSU Sideloader 可選擇 `.xz`。

## ADB、Shizuku 與 DSU

1. 保留個人資料備份及原版 GSI。確認裝置有足夠內部儲存空間；若配置 8 GiB DSU userdata，建議先保留約 20 GB 可用空間供下載、暫存、system 與 userdata。實際上限以 One UI / DSU Sideloader 回報為準。
2. 取得 [Google Windows Platform Tools](https://developer.android.com/tools/releases/platform-tools)，開啟手機 USB 偵錯並接受這台電腦授權。以下路徑請改成你的實際位置：

   ```powershell
   $adb = "C:\platform-tools\adb.exe"
   & $adb devices
   ```

   一次只連一台待測裝置。看不到手機時先處理 Samsung USB 驅動、傳輸線與 USB 授權。
3. 安裝並開啟 [Shizuku](https://github.com/RikkaApps/Shizuku/releases)。依 App「透過連接電腦啟動」顯示的指令執行；常見指令如下，若 App 顯示不同，使用 App 畫面的指令：

   ```powershell
   & $adb shell sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh
   ```

   在手機確認 Shizuku 服務執行中。重新開機後通常須重新啟動。
4. 安裝 [DSU Sideloader](https://github.com/VegaBobo/DSU-Sideloader/releases)，建立並授予一個專用工作資料夾，允許 Shizuku 存取，確認它顯示 Shizuku operation mode。
5. 傳輸並再次核對手機上的壓縮檔：

   ```powershell
   & $adb push .\system.img.xz /sdcard/Download/system.img.xz
   & $adb shell sha256sum /sdcard/Download/system.img.xz
   ```

   輸出必須與 Windows 的 `$actual` 一致。
6. 在 DSU Sideloader 選擇 `system.img.xz`。保留 system 大小自動判定，依可用額度配置獨立 userdata（GApps 建議先試 8 GiB）。確認系統 DSU 安裝提示，等待完成，再從 DSU 通知啟動 GSI。首次測試使用新的 DSU userdata，避免既有 overlay 狀態干擾；不要設定持續啟動模式。
7. 若 One UI 沒有可用 DSU、安裝器拒絕、AVB/SELinux 失敗或無法啟動，保留錯誤並停止。本實驗不以刷寫 boot、vbmeta、vendor 或安裝 Root 模組處理這些問題。離線檢查不能保證這台 Samsung 的 DSU 執行結果。

## 啟動後檢查

重新授權 GSI 中的 USB 偵錯。執行以下唯讀命令：

```powershell
& $adb shell getprop ro.build.fingerprint
& $adb shell getprop ro.lineage.version
& $adb shell getprop ro.gsid.image_running
& $adb shell getprop ro.vendor.build.version.sdk
& $adb shell cmd overlay partition-order
& $adb shell cmd overlay list --user 0
& $adb shell cmd overlay dump io.github.sma1560.fingerprintfix
& $adb shell cmd overlay dump com.mediatek.frameworkresoverlay
& $adb shell cmd overlay lookup --user 0 --verbose android android:array/config_biometric_sensors
& $adb shell cmd overlay lookup --user 0 android android:array/config_biometric_sensors
& $adb shell service list | Select-String -Pattern "biometrics.fingerprint"
& $adb shell ps -A | Select-String -Pattern "fingerprint"
& $adb shell dumpsys fingerprint
& $adb shell dumpsys biometric
```

預期要確認：

- 系統為來源 LineageOS 22.2 / 20260105，且目前確在 DSU；Vendor SDK 符合 Android 15。
- 新 RRO 路徑為 `/system_ext/overlay/SmA1560FingerprintFix/SmA1560FingerprintFix.apk`，處於 enabled / immutable 狀態；MediaTek 原 overlay 仍保留。
- verbose lookup 的解析來源包含新 RRO，最終 array 長度為 0。AOSP 的非 verbose array lookup 逐項列印，**空陣列可能是成功退出但沒有項目行，不一定印 `[]`**；同時檢查退出碼及 verbose 輸出，命令失敗不算通過。
- 真實 `android.hardware.biometrics.fingerprint.IFingerprint/default` 存在，框架有讀到感測器屬性並使用真實 AIDL provider。單看 Samsung vendor process 存在，或 HIDL 錯誤不再出現，都不足以證明成功。

不要修改 MediaTek overlay 的 enable 狀態。新 RRO 的不可變狀態由預載 manifest 在開機時決定。

## 登記與紀錄

先收集基準紀錄，再在手機設定中建立測試鎖屏 PIN、進入指紋登記並嘗試完成。PIN 只在手機輸入。解壓原始碼／驗證套件後可使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\sm-a1560-fingerprint-fix\windows\collect-logs.ps1 -Adb $adb -OutputDirectory .\logs-before
# 在手機手動進行指紋登記。
powershell -ExecutionPolicy Bypass -File .\sm-a1560-fingerprint-fix\windows\collect-logs.ps1 -Adb $adb -OutputDirectory .\logs-after
Select-String -Path .\logs-after\logcat.txt -Pattern "HIDL daemon is null|generateChallenge|AidlSession|Fingerprint|avc: denied"
```

收集腳本不清空 logcat、不變更 overlay。分享紀錄前檢查其中的序號、帳戶及其他個人資訊。腳本尚未在 Windows／真機實際執行。

測試結果請分開記錄：

| 觀察結果 | 可以得出的結論 |
|---|---|
| RRO 未啟用或 array 仍有舊值 | 開機載入、優先級或 DSU mount 路徑尚未成立 |
| array 空，但框架未登記感測器 | AIDL 發現／getSensorProps 等階段仍有問題 |
| 有 AIDL sensor，但 challenge 仍失敗 | 繼續查 session、user、SELinux、HAT/TEE 或 Samsung 相容性 |
| 能完成登記並列出指紋 | 已通過登記階段，還需實際解鎖／驗證 |
| 完成登記且實際驗證可用 | 才有這台裝置此次測試成功的證據 |

測試結束可透過 DSU 通知返回原系統並移除 dynamic system。啟動失敗時先嘗試一般重新開機回原系統，保留紀錄後停止。已收錄的[成功回報](device-test-sm-a1560-rro1.md)僅代表指定裝置與配置的此次測試結果。
