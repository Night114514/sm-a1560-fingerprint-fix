# Android 15 原始碼核對與實驗邊界

結論：**空陣列是正確且範圍有限的修復實驗，尚不是已證實的修復。** 它移除不存在的 HIDL 指紋 HAL 的配置來源，保留 AIDL 發現流程。Samsung AIDL 是否與這份 GSI 的 framework/TEE 相容，仍須真機完成登記才能確認。

以下核對基於 AOSP `android-15.0.0_r1`，frameworks/base commit `4e43ad12e1b211f15152e9c5b16b0fe88e6b93f3`；以及查閱時的 LineageOS `lineage-22.2` commit `906cba06036689b107a2fb6d7b6f54f41edc1fcd`。`upstream/SOURCES.json` 列出所保存檔案的 URL 及 SHA-256。這些版本用於可重查的推導，不代表使用者 GSI 的確切來源 revision。

## 1. 配置陣列不等於 AIDL 感測器清單

[AOSP config.xml #5598](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/core/res/res/values/config.xml#5598) 記錄格式 `ID:Modality:Strength`；預設 `config_biometric_sensors` 本來就是空陣列，註解範例是 `0:2:15`。

[AuthService.java #129](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/biometrics/AuthService.java#129) 讀取該 framework array。`getFingerprintConfiguration` 與 face/iris 配置讀取沿用它；[getFingerprintAidlInstances #205](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/biometrics/AuthService.java#205) 另用 `ServiceManager.getDeclaredInstances(IFingerprint.DESCRIPTOR)`，不是從陣列中解析 AIDL instance。

[registerFingerprintSensors #881](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/biometrics/AuthService.java#881) 只有在 HIDL 配置及 AIDL instances 兩者皆空時才回報無感測器。非空 HIDL 配置呼叫 `addHidlSensors`，非空 AIDL 宣告呼叫 `addAidlSensors`；兩者可以同時加入。它還根據 HIDL 是否非空決定 `resetLockoutRequiresHardwareAuthToken`，因此清空不只是「不印 HIDL log」，也會讓框架採取 AIDL 配置所需的相關行為。

[FingerprintSensorConfigurations.java #81](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/core/java/android/hardware/fingerprint/FingerprintSensorConfigurations.java#81) 把陣列解析成 `HidlFingerprintSensorConfig`，選 modality fingerprint，登記在 `defaultHIDL` 下；`addAidlSensors` 以 instance 名稱加入。兩者存入 HashMap。

[FingerprintService.java #1093](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/biometrics/sensors/fingerprint/FingerprintService.java#1093) 篩選可用候選，處理虛擬感測器，沒有一般性的「AIDL 永遠優先於 defaultHIDL」規則。不能只根據資源陣列，就斷言框架在所有情況下一定選哪個 provider。

對本案「只有 `0:2:15`，HIDL 2.1/default 不存在，但標準 AIDL/default 已宣告」的前提，空陣列會去掉 `defaultHIDL` 候選，讓 AIDL 的正常發現與屬性讀取成為可測試路徑。此推論也需要真機確認當時生效的配置，沒有其他 overlay 提供不同項目。

## 2. Samsung 服務活著仍不足以通過登記

[FingerprintSensorConfigurations.java #174](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/core/java/android/hardware/fingerprint/FingerprintSensorConfigurations.java#174) 會以 `waitForDeclaredService` 取得標準 AIDL，再呼叫 `getSensorProps()`。已在 service manager 註冊、VINTF 可見、能讀回感測器屬性、能建立 user session、能生成 challenge，是不同的驗證階段。

原始碼查閱不能證實 Samsung 專有 service 的 transaction、版本、TEE/KeyMint/Gatekeeper/HAT 行為。移除 HIDL null log 後仍卡住，應保留新 log 定位；不以替換 service、修改 Vendor VINTF 或停用 SELinux 作為此 RRO 的隱含後續。

Android 15 還存在針對 API 30 Vendor 的 fallback，見 [AuthService #758](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/biometrics/AuthService.java#758) 與其他 modality 註冊路徑。因此文件要求記錄真機的 Vendor SDK；不把此實驗外推到舊 Vendor。

## 3. LineageOS 22.2 的額外差異

[固定 commit 的 AuthService](https://github.com/LineageOS/android_frameworks_base/blob/906cba06036689b107a2fb6d7b6f54f41edc1fcd/services/core/java/com/android/server/biometrics/AuthService.java#L205) 把 AIDL instance 查詢轉交 `FingerprintService.getDeclaredInstances()`。同版本 [FingerprintService](https://github.com/LineageOS/android_frameworks_base/blob/906cba06036689b107a2fb6d7b6f54f41edc1fcd/services/core/java/com/android/server/biometrics/sensors/fingerprint/FingerprintService.java#L1137) 在找不到 `virtual` 時補入該名稱。

這不會使 Vendor 的 AIDL/default 自動相容；若只有虛擬候選或該功能被啟用，結果仍可能不同。真機需要辨認實際 instance/provider，不只看到「fingerprint service 存在」就認定使用的是 Samsung 真實感測器。

## 4. overlayable policy

[idmap2 ResourceMapping.cpp #55](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/cmds/idmap2/libidmap2/ResourceMapping.cpp#55) 的 `CheckOverlayable` 分兩種情況：

1. **目標完全沒有 overlayable 宣告**：允許 ODM/OEM/system/vendor/product 等預載分區 policy，或目標／指定配置簽章 policy。普通 `/data/app` 的實驗憑證不符合這些條件。
2. **目標有 overlayable 宣告**：被覆寫資源必須有對應宣告，targetName 必須相符，而且 fulfilled policy 至少符合一項。

因此不應捏造名叫 `FrameworkResources` 的 targetName，或說 platform 簽章在任何目標上都能無條件覆寫所有資源。本專案不設 targetName，支援的是經實際 framework-res.apk 檢查後「沒有群組宣告」的情況。若 framework 有任何群組，本版工具先停止，待核實實際政策後另行處理。

[IdmapManager.java #180](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/om/IdmapManager.java#180) 對 target SDK Q+ 啟用 overlayable 檢查，並在 [#248](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/om/IdmapManager.java#248) 把 system_ext 當 system policy。本專案 target 35，不降級 target，也不忽略政策。

最終資源 ID 必須從**原版 GSI 的 framework-res.apk**讀取，不使用 SDK 的 private ID 猜測，也不硬編碼 `0x0107xxxx`。APK 自己的陣列是 `0x7f010000`；explicit resourcesMap 依名稱連到目標 array。原生 host `idmap2 create` 應只建立一筆對應，並用 `dump` 讀回。

本次沒有原版 GSI、也沒有 Linux host idmap2，僅已驗證 APK compiled mapping，及對合成 framework 目標的邏輯政策檢查。不能宣稱已為使用者 GSI 生成成功的 idmap。

## 5. 優先級與 zygote

[PackagePartitions.java #78](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/core/java/android/content/pm/PackagePartitions.java#78) 列出預設分區順序；[OverlayConfig.java #179](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/core/java/com/android/internal/content/om/OverlayConfig.java#179) 僅在該分區沒有 config 時沿用 manifest `isStatic`/`priority`。

自訂順序檔的路徑是 `/product/overlay/partition_order.xml`，見 [OverlayConfig #77](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/core/java/com/android/internal/content/om/OverlayConfig.java#77)。這也是為何不把 priority 999 當成所有分區的全域最大值。

[OverlayConfig #491](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/core/java/com/android/internal/content/om/OverlayConfig.java#491) 收集 enabled、immutable、target android 的 overlay，於 zygote 建立 framework idmap。target SDK Q+ 啟用政策驗證。這個路徑需要 immutable，因此既有 config 的插入不能盲目放在所有 mutable 項目之後。

[官方 RRO 文件](https://source.android.com/docs/core/runtime/rros) 也說明 immutable framework overlay 對 `Resources.getSystem()` 的影響，以及 config 存在時 manifest 優先級不生效。本版 patcher 因而採取「沒有 config 就不新增，有 config 就保留既有項目並插入 immutable 區末端」的方式。

## 6. 手機端空陣列的輸出

[OverlayManagerShellCommand.java #577](https://android.googlesource.com/platform/frameworks/base/+/android-15.0.0_r1/services/core/java/com/android/server/om/OverlayManagerShellCommand.java#577) 的 array lookup 迴圈逐項 `println`。長度 0 會沒有項目行；不應把一定出現字面 `[]` 當成通過條件。verbose 模式會額外列資源解析紀錄。ADB exit code、overlay 狀態、來源路徑和實際登記結果必須一起判讀。

DSU 操作參考 [DSU Sideloader README](https://github.com/VegaBobo/DSU-Sideloader#readme) 的 operation modes；其 Shizuku mode 主要是免除手動 ADB 啟動系統安裝器，不會把任意 RRO 變成預載系統 overlay，也不保證 Samsung 的 DSU/AVB 接受映像。
