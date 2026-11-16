# sm-a1560-fingerprint-fix

Samsung Galaxy A15 5G **SM-A1560** 的 Android 15 GSI 最小 RRO 修復實驗。目標環境為原廠 Android 15 / One UI 7 Vendor、已解鎖 Bootloader，以及 LineageOS 22.2 Android 15 GApps EXT4 GSI。

**目前已編譯並檢查 RRO APK；尚未取得使用者原版 GSI，沒有產生可安裝的真實 GSI，也沒有真機指紋登記結果。不能據此聲稱指紋已修復。** 本專案只改一項 framework 資源，不提供 HAL、TEE、Samsung 私有介面或 generateChallenge 相容層。

## 實驗依據

將最終生效的 `android:array/config_biometric_sensors` 從 `["0:2:15"]` 改為空字串陣列，是有程式碼依據的隔離實驗：

- AOSP Android 15 的 `AuthService` 用這個陣列建立舊式 HIDL 感測器配置；AIDL instance 則獨立經 `ServiceManager.getDeclaredInstances(IFingerprint.DESCRIPTOR)` 發現。
- 非空陣列會加入 `defaultHIDL` 候選。它可以與 AIDL `default` 同時存在；不能簡化成「一有陣列就必定完全停用 AIDL」。候選篩選與 HashMap 遍歷、虛擬感測器設定也有關。
- 空陣列讓框架不再建立這個錯誤的 HIDL 候選，但保留已宣告的 AIDL 感測器發現流程。AIDL 仍須成功執行 `getSensorProps`、建立 session、取得 challenge，才可能登記。
- 原始值 `0:2:15` 表示 sensor ID 0、fingerprint modality 2、strong strength 15。若真機的最終陣列還含其他 HIDL face/iris 項目，先停止；清空整個陣列也會移除那些舊式配置。
- AOSP 尚有 Android 11 / API 30 Vendor 的相容回退。本任務是 Android 15 Vendor；仍應記錄 `ro.vendor.build.version.sdk`，不要只依 UI 的 Android 版本推定。

完整推導、固定版本的來源連結及限制見 [docs/source-analysis.md](docs/source-analysis.md)。此處的 LineageOS 分支核對不能代表使用者那份 GSI 的實際編譯內容。

## 專案內容

| 檔案 | 用途 |
|---|---|
| `AndroidManifest.xml` | 目標 `android`，靜態 RRO，priority 999，target SDK 35，沒有程式碼 |
| `res/values/arrays.xml` | 唯一的值覆寫：真正長度 0 的 `string-array` |
| `res/xml/overlays.xml` | 唯一映射：`array/config_biometric_sensors` |
| `build.sh` | aapt2 編譯、zipalign、apksigner 簽署、讀回驗證 |
| `verify.sh` | 檢查 APK，或核對已修補的映像及 receipt |
| `patch.sh` | 不掛載、不需 root 的 raw EXT4 複本修補 |
| `scripts/setup-sdk.sh` | 可選的線上 SDK 工具下載；固定版本及 SHA-256 |
| `tests/integration.py` | 自建 EXT4 的修補、讀回與拒絕條件測試 |
| `windows/collect-logs.ps1` | Windows ADB 診斷收集，不推斷登記結果 |
| `VALIDATION.md`、`validation/` | 本次實際執行範圍、輸出與雜湊 |

APK 內的兩個資源 entry 分別是陣列和映射 XML。映射 XML 不是第二項 framework 配置覆寫。APK 沒有 Java/Kotlin、DEX、native library、權限或背景服務。

## Linux 依賴與構建

適用 x86_64 Codex Cloud Linux 或 Windows WSL2 Linux。不需要 Gradle、Android Studio、`javac` 或核心掛載權限。

基本工具：Bash、Python 3.9+、Java 17+（含 `keytool`）、coreutils、curl、unzip。APK 工具為 Android SDK Build Tools **35.0.0**，連結用 SDK Platform **35 revision 2** 的 `android.jar`。這個 SDK stub 不是待修補 GSI 的 `framework-res.apk`。

一般 Debian / Ubuntu 自有環境的安裝方式：

```bash
sudo apt-get update
sudo apt-get install python3 openjdk-17-jre-headless curl unzip coreutils e2fsprogs libselinux1 shellcheck
export PATH="/usr/sbin:/sbin:$PATH"
```

託管 Codex Cloud 若提供套件 helper，依環境政策使用 `sudo -n /usr/local/bin/cloud-agent-packages update`，再 `install` 所需的確切 Debian 套件名稱。本次預設環境沒有該 helper，也沒有 SDK/e2fsprogs；實際採用 workspace 內下載的 SDK，以及解開到使用者目錄的 Debian e2fsprogs 共用庫和執行檔，沒有假裝它們本來已安裝。詳細版本記錄於 `VALIDATION.md`。若不能安裝、下載或執行依賴，腳本會非零退出。

可用既有 SDK：

```bash
export ANDROID_SDK_ROOT=/absolute/path/to/android-sdk
# 已有 sdkmanager 時：
sdkmanager --sdk_root="$ANDROID_SDK_ROOT" 'platforms;android-35' 'build-tools;35.0.0'
./build.sh
```

或下載本次核驗的固定版本；使用 Android SDK 須遵守 Google 的授權條款：

```bash
chmod +x build.sh patch.sh verify.sh scripts/setup-sdk.sh
./scripts/setup-sdk.sh
export ANDROID_SDK_ROOT="$PWD/work/android-sdk"
./build.sh
./verify.sh --apk dist/SmA1560FingerprintFix.apk --report work/manual-apk-check
(cd dist && sha256sum -c SmA1560FingerprintFix.apk.sha256)
```

`build.sh`、`verify.sh`、`patch.sh` 本身不連網、不自動安裝套件。也可透過 `BUILD_TOOLS_DIR`、`ANDROID_JAR` 指定工具位置。預設建立 `work/experiment.jks` 作實驗簽署，密碼固定為公開測試值 `android`，**不是平台金鑰**；交付檔不含私鑰。自行重建的憑證及 APK 雜湊可以不同。使用自己的 keystore 時設定 `SIGNING_KEYSTORE`、`SIGNING_ALIAS`、`RRO_KS_PASS` 環境變數。

## RRO 政策與優先級

本專案保留 target SDK 35，沒有用低 target SDK 或 `--ignore-overlayable` 規避政策。AOSP Android 15 的 `ResourceMapping.cpp` 允許沒有任何 overlayable 群組宣告的目標，由符合 system/product 等預載分區政策的 RRO 覆寫。`system_ext` 使用 system policy。若實際 framework 定義了 overlayable 群組，檢查器會保守停止，要求先人工核對 targetName 與資源政策。

因此這個 APK 應預載到 GSI 內的 `/system_ext/overlay/`（預設）或經檢查的 `/product/overlay/`。**直接 `adb install` 到 `/data/app`，或只有 Shizuku 權限，不會讓它取得預載分區政策。** Shizuku 的用途是協助 DSU 安裝操作。

預設跨分區順序由低至高是 `system → vendor → odm → oem → product → system_ext`。999 只處理相同分區、沒有 OverlayConfig 時的靜態排序，不能單憑數字宣稱壓過 Vendor。腳本會：

- 辨識 EXT4 根目錄及 `/system` 巢狀布局，確認所選分區真正在同一映像中；不穿越 symlink 或修改外部 product/system_ext。
- 檢查 `/product/overlay/partition_order.xml`；遇自訂順序停止。
- 掃描映像中 product/system_ext RRO 的 compiled resources 與 resourcesMap，記錄可能覆寫同一資源的 APK，拒絕有疑義的同優先級、較高分區及已啟用 mutable 競爭者。
- 若所選分區沒有 `overlay/config/config.xml`，沿用靜態 manifest 排序，**不憑空新建 config 以免改變其他 RRO 的預設狀態**。
- 若已有 config，只插入本套件 `enabled="true" mutable="false"`，放在所有既有 immutable 之後、第一個 mutable 之前，保留其他文字和註解。遇 `<merge>`、重複 package 或不合法排序便停止。

映像外繼承的 Vendor/ODM/OEM、使用者既有 mutable overlay 狀態及 GSI 私有改動，仍要在真機檢查。不可關掉整個 `com.mediatek.frameworkresoverlay`；它包含本實驗不應移除的其他 Vendor 配置。

## 原版 GSI 的離線複本修補

本次沒有使用者提供的原版 GSI，因此以下是可執行流程，**不是本次已生成映像的聲明**。

輸入必須是未掛載、乾淨、長度符合 superblock 的 raw EXT4。腳本不處理 EROFS、super.img、Android sparse、壓縮檔、附帶 AVB footer／不明尾段、encrypted、shared_blocks 或 read-only feature 映像；也不自動長大、修復檔案系統、刪除 AVB 或重新簽署映像。

例如先保留下載檔，再準備獨立 raw 工作檔：

```bash
sha256sum original.img.xz > original.img.xz.sha256
xz -dk -- original.img.xz                       # 保留壓縮原版
# 若原檔是 Android sparse，另安裝 android-sdk-libsparse-utils，再轉到不同檔：
# simg2img original-sparse.img original-raw.img
```

若是 `shared_blocks`，在另外的工作複本上，使用支援的 e2fsprogs 評估 `e2fsck -f -E unshare_blocks 工作複本.img`，確認空間並手動處理提示，之後完整檢查；不要對原檔執行。AVB/DSU 相容問題在本任務中屬停止條件，不以修改 boot/vbmeta/vendor 解決。

正式修補預設要求 Android 15 **Linux host `idmap2`**。SDK Build Tools 不包含它，從手機取出的 ARM64 ELF 也不能直接在 x86_64 Linux 執行。若已有完整 AOSP Android 15 build checkout 和其必要依賴：

```bash
# 在該 AOSP checkout 中執行，依其 build 文件先設定環境：
source build/envsetup.sh
lunch aosp_arm64-trunk_staging-userdebug
m idmap2
# host binary 位於 out/host/linux-x86/bin/idmap2；本次沒有執行這項完整 AOSP 構建。
```

依 checkout 支援的 lunch target 調整產品。`idmap2` 的 Android.bp 明列 `host_supported: true`。工具若依賴其他 host libraries，也須保留其建置環境。

```bash
./patch.sh --input /absolute/path/original-raw.img \
  --output /absolute/path/lineage-sm-a1560-experiment.img \
  --idmap2 /absolute/path/aosp/out/host/linux-x86/bin/idmap2

./verify.sh --image /absolute/path/lineage-sm-a1560-experiment.img \
  --original /absolute/path/original-raw.img \
  --idmap2 /absolute/path/aosp/out/host/linux-x86/bin/idmap2 --require-idmap
```

若只做探索性離線檢查，可明確傳入 `--allow-unverified-idmap`；在缺少原生工具時，它只執行 compiled mapping／目標資源／分區政策的邏輯檢查，receipt 會標示 `NOT_RUN`。**這不等於 idmap2 成功，不應省略後續真機檢查。** 這是本次自建 fixture 測試使用的模式。要改放 product，加上 `--partition product`；腳本會額外檢查較高的 system_ext。

修補過程使用 `cp --reflink=auto --sparse=always` 建立獨立暫存複本，再由 debugfs 增加 RRO；既有 config 若需新增條目，只在複本內替換。它不重新建立整個 EXT4，也不解包／重建 Vendor。安全檢查包括：

1. 輸出與報告目錄都不得已存在；拒絕同檔、symlink 輸出及重複套用。
2. 輸入、輸出各執行 `e2fsck -f -n`，必須退出 0；輸出維持原長度。
3. 新 APK/目錄設定 uid:gid 0:0、檔案 0644、目錄 0755。以 GSI 內的 plat/product/system_ext `file_contexts`，透過真正的 libselinux matcher 求得標籤，寫入並讀回 `security.selinux` xattr；不把 Linux 主機標籤當 Android 標籤。
4. 比較所選 overlay 子樹內既有檔案、framework-res.apk 和已使用的 file_contexts 的內容 SHA、inode/mode/owner 及 xattr 清單；只有明列的 config 修改例外。這不是整張映像每個檔案的逐檔鑑識。
5. 從輸出讀回 APK，檢查 ZIP、簽章、對齊、長度 0 陣列和唯一映射；原生 idmap2 可用時，以分區 policy、啟用 overlayable 檢查產生並讀回唯一映射，不把本機測試 idmap 塞進 GSI。
6. 修補後重新計算原檔 SHA-256，確認未變；用無覆寫的 hard link 原子發布完成映像。失敗時刪除 `.partial`，保留診斷報告，沒有完成的映像輸出。

報告位於 `輸出.img.report/`，包含 `receipt.json`、e2fsck 輸出、優先級清單、APK 檢查及 SHA256SUMS。若重新執行，請選新的輸出／報告名稱。正式輸出需要空間容納一份完整映像和檢查暫存檔。檔案系統不支援 hard link 時會停止。

可選壓縮給 DSU Sideloader：

```bash
gzip -n -c lineage-sm-a1560-experiment.img > lineage-sm-a1560-experiment.img.gz
gzip -t lineage-sm-a1560-experiment.img.gz
sha256sum lineage-sm-a1560-experiment.img lineage-sm-a1560-experiment.img.gz
gzip -dc lineage-sm-a1560-experiment.img.gz | sha256sum  # 應與 raw .img 相同
```

## Windows + Shizuku + DSU Sideloader

只有取得上節的真實修補 GSI 後才進行；**不要把自建 fixture 或單獨的 RRO APK 當作 GSI 安裝**。

1. 在 Windows 解壓專案。需要自行構建／修補時使用 WSL2（例如管理員 PowerShell 的 `wsl --install -d Ubuntu`），在 WSL 的 Linux 工作目錄操作，依上節安裝工具。現有已簽署 APK 在 `dist/`。
2. 保留個人資料備份、原版 GSI 及雜湊，確認原版 GSI 在同一 Vendor/DSU 路徑的基準表現。Bootloader 已解鎖不代表 DSU/AVB 一定允許任意 GSI；請勿為本實驗再改 boot、vbmeta 或 vendor。
3. 由 [Google 官方 Platform Tools](https://developer.android.com/tools/releases/platform-tools) 取得 Windows ADB。在手機開啟 USB 偵錯，連線後執行 `.\adb.exe devices`，在手機接受該電腦授權。
4. 由 [Shizuku 官方來源](https://github.com/RikkaApps/Shizuku/releases) 安裝並開啟。用其「透過連接電腦啟動」顯示的指令。常見指令如下；若 App 顯示不同路徑，以 App 為準：

   ```powershell
   .\adb.exe shell sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh
   ```

   回到 Shizuku 確認服務執行中。每次重新開機後可能要重新啟動。也可依其指引用無線偵錯配對。
5. 安裝 [DSU Sideloader 官方發行版](https://github.com/VegaBobo/DSU-Sideloader/releases)，授予工作資料夾存取及 Shizuku 權限，確認 App 實際顯示 Shizuku operation mode。它協助啟動系統 DSU 安裝器，不能新增手機欠缺的 DSU 支援。
6. 在 Windows 與傳輸目的地核對檔案。例如先計算 `Get-FileHash .\lineage-sm-a1560-experiment.img -Algorithm SHA256`；以 `adb push` 傳到 Downloads 後，再執行手機端 `sha256sum` 比對。若傳的是 `.gz`，比對 `.gz` 本身的雜湊。

   ```powershell
   .\adb.exe push .\lineage-sm-a1560-experiment.img /sdcard/Download/
   .\adb.exe shell sha256sum /sdcard/Download/lineage-sm-a1560-experiment.img
   ```

7. 在 DSU Sideloader 選擇修補 `.img` 或 `.img.gz`，讓 App 自動決定 system 映像大小。依實際可用空間配置獨立 userdata（例如空間允許時 8–16 GB）。確認安裝，等系統 DSU 通知完成，再從通知啟動 GSI。全新 DSU userdata 可避免既有 mutable overlay 狀態干擾。
8. 如果 DSU 功能缺失、安裝權限／SELinux 失敗、映像簽章被拒或無法啟動，保留診斷並停止；不把刷寫 vbmeta 或安裝 root 模組當本任務的後續步驟。Shizuku 的 log access 若系統另行提示，依需要授權，沒有 log 存取也不能假稱驗證成功。

## 真機驗證與通過條件

以下 PowerShell 範例假設只有一台已授權裝置，且當前目錄有 adb.exe；多裝置請自行加入 `-s SERIAL`。切換 DSU 後需再次授權 USB 偵錯。

```powershell
.\adb.exe shell getprop ro.build.fingerprint
.\adb.exe shell getprop ro.gsid.image_running
.\adb.exe shell getprop ro.vendor.build.version.sdk
.\adb.exe shell getprop ro.product.first_api_level
.\adb.exe shell cmd overlay partition-order
.\adb.exe shell cmd overlay list --user 0
.\adb.exe shell cmd overlay dump io.github.sma1560.fingerprintfix
.\adb.exe shell cmd overlay dump com.mediatek.frameworkresoverlay
.\adb.exe shell cmd overlay lookup --user 0 --verbose android android:array/config_biometric_sensors
.\adb.exe shell cmd overlay lookup --user 0 android android:array/config_biometric_sensors
.\adb.exe shell service list | Select-String -Pattern "biometrics.fingerprint"
.\adb.exe shell ps -A | Select-String -Pattern "fingerprint"
.\adb.exe shell dumpsys fingerprint
.\adb.exe shell dumpsys biometric
```

確認建置確為該 GSI，Vendor SDK 符合預期；overlay 路徑是預載分區，狀態為 enabled/immutable，而 MediaTek 原 overlay 仍保留。檢查 `lookup --verbose` 的解析來源包含修補 APK。**AOSP 的非 verbose array lookup 逐項列印；空陣列是「成功退出但沒有任何項目行」，不一定會印出 `[]`。** 請同時確認退出碼、verbose 解析來源及 dumpsys，不能把命令失敗或空錯誤輸出認作空陣列。

`service list` 能顯示 AIDL binder；`lshal` 主要列 HIDL，不能因它未列出 Samsung AIDL 就斷定 AIDL 不存在。要確認 `/default` 的標準 AIDL instance 已被框架發現、感測器屬性已讀到；單看 vendor process 還在並不足夠。不要用猜測的 `service call` transaction number 呼叫 challenge。

先在登記前收集一次，再從設定建立鎖屏 PIN 並進入指紋登記，嘗試完成，之後收集一次：

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\collect-logs.ps1 -Adb .\adb.exe -OutputDirectory .\logs-before
# 在手機設定手動進行指紋登記；不要透過聊天或腳本傳送 PIN。
powershell -ExecutionPolicy Bypass -File .\windows\collect-logs.ps1 -Adb .\adb.exe -OutputDirectory .\logs-after
Select-String -Path .\logs-after\logcat.txt -Pattern "HIDL daemon is null|generateChallenge|AidlSession|Fingerprint|avc: denied"
```

此收集腳本只讀取診斷，不清空 logcat、不變更 overlay 狀態。紀錄可能含序號、帳戶／裝置資訊；分享前自行刪除不需要的個人資料。PowerShell 收集腳本沒有在本次 Linux 環境實際執行。

通過需要同時觀察到：生效資源為空、AIDL 感測器被框架使用、此次登記能越過 challenge 並完成、Settings 能重新列出指紋，且實際解鎖／驗證可用。若只有 HIDL 錯誤消失，應記為「錯誤 HIDL 候選已移除」；若仍卡 challenge，下一步依序查 AIDL getSensorProps/createSession、active user、SELinux denial、Gatekeeper/KeyMint/HAT 與 Samsung 介面相容性，不擴大修改 Vendor 配置。

測試結束可依 DSU 系統通知返回原系統並移除 dynamic system；失敗時先嘗試一般重新開機返回原系統，依裝置實際復原流程處理。本專案不設 persistent/sticky DSU，也不提供永久刷寫指令。

## 重跑本機檢查

```bash
./build.sh
bash -n build.sh patch.sh verify.sh scripts/common.sh scripts/setup-sdk.sh
shellcheck -x build.sh patch.sh verify.sh scripts/common.sh scripts/setup-sdk.sh
python3 -m py_compile scripts/*.py tests/*.py
export AAPT2="$ANDROID_SDK_ROOT/build-tools/35.0.0/aapt2"
python3 tests/integration.py
```

測試在 `work/` 建立並刪除合成 EXT4，不輸出可供手機使用的 ROM。保存的測試結果和 SHA 只代表那些合成樣本。原版 GSI、Android runtime idmap、有效 overlay 優先級、Samsung AIDL challenge 與真機登記，仍須取得原版及裝置後驗證。
