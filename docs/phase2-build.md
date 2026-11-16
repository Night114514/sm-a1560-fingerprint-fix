# 第二階段：相同 AVB 信任條件的 GSI 重封裝

指定來源為 [MisterZtr / LineageOS / Android 15](https://sourceforge.net/projects/misterztr-gsi/files/LineageOS/Android%2015/)，檔名必須是 `LineageOS-22.2-20260105-GAPPS-EXT4-GSI.7z`。不要拿 Vanilla、EROFS、22.1 或「latest」替代。

| 來源 | 值 |
|---|---|
| 7z 大小 | 1,127,244,589 bytes |
| 上游 SHA-1 | `abf4270323de66ffeb9f9b6cc065669b04dad2a6`，本次已比對 |
| 7z SHA-256 | `cf4992731f0fbb2a3d09fffeb16ed4f16ad8c023b38427cdc12a0818bc55c7c4` |
| 包內映像 | `LineageOS-22.2-20260105-GAPPS-EXT4-GSI.img` |
| 原版映像大小 | 3,340,144,640 bytes |
| 原版映像 SHA-256 | `cd3599e056ba82bc19379fbca7e81ee572589e0dd81b75092c1fee1691a077b7` |
| 包內 CRC32 | `891C44A8`，解壓後已比對 |
| 架構證據 | `ro.product.cpu.abi=arm64-v8a`；idmap2 ELF64/AArch64 |
| A/B 證據 | 上游 README 的 A/B 限定；build product `tdgsi_arm64_ab` |
| 系統 | LineageOS 22.2、Android 15、SDK 35、GApps、raw EXT4，非 Android sparse |

## 為何不能直接執行第一階段的預設修補

實際原版帶 AVB footer、SHA256_RSA2048 簽章、SHA-256 dm-verity tree，以及兩個 roots 的 Reed-Solomon FEC。只修改 EXT4 內容後保留舊 footer，會讓校驗失敗。預設 patch.sh 因此繼續拒絕 AVB 映像。

第二階段新增**明確啟用**的 `--avbtool --avb-key --fec` 模式：先驗證原版簽章、hashtree、FEC，確認提供的 key 與原版內嵌公鑰完全一致，才在副本移除過期 footer、加入 RRO，並重建 system.img 內原有的校驗樹、FEC 與簽章。

這會更新 **system.img 內的 AVB 元資料**；不操作手機，不修改或產生獨立的 vbmeta.img，也不修改手機的 vbmeta、boot、vendor 分區。若要求連 system.img 內的舊簽章／root digest 都不得改，則無法製作有效的內容修正版，應停止。

本版僅接受已測試的 layout：SHA256_RSA2048、SHA-256、4096-byte block、兩個 FEC roots、flags=0、rollback location=0、無額外 public-key metadata、單一 system hashtree 及 property descriptors。不同 layout 直接停止。

原版公鑰 SHA-1 是 `cdbb77177f731920bbe0a0f94f84d9038ae0617d`，與 AOSP `android-15.0.0_r1/test/data/testkey_rsa2048.pem` 相同。這是公開測試 fixture。重建沿用原版公鑰、algorithm、salt、rollback index `1764547200`、flags、properties、release string、所有幾何大小；只有必要的新 root digest／簽章與校驗資料更新。沒有降低 rollback index、停用 verity 或換用新公鑰。

## FEC 與 idmap2 的實際方法

`tools/fec_raw.cpp` 是 raw-image 專用 adapter，採用 AOSP 的 interleave 幾何及 libfec RS encoder，**不是完整 Android fec CLI**。本次已重新生成原版全部 26,198,016 bytes FEC parity，與原版逐位元組完全一致，才用於副本。另有損壞偵測與相同金鑰／不同金鑰測試。簽章與 hashtree 使用固定版本的原版 AOSP avbtool 驗證。

雲端沒有 x86_64 Linux host idmap2；`scripts/prepare-idmap2.py` 從原版 GSI 與其 runtime APEX 提取 Android 15 ARM64 idmap2、linker64、所需 libraries，在 QEMU 中執行真正的工具。這是工具程式模擬執行，沒有啟動 Android 或指紋 HAL。manifest 記錄 binary/library 來源及 SHA-256。

實際 framework 的目標 array ID 是 `0x01070028`，沒有 overlayable 群組。以 `--policy system`、不忽略 overlayable 檢查產生的 idmap，只有一筆：

```text
0x01070028 -> 0x7f010000 (array/config_biometric_sensors -> array/config_biometric_sensors)
```

只給 public policy 的負向測試不能取得此映射。system_ext 的 partition policy 是 system，並不由 APK 憑證或 SELinux type 名稱決定。QEMU 執行時的 missing linker configuration 警告是獨立 Linux 執行環境的警告；工具實際成功退出及映射輸出另有紀錄。

## 依賴與重現

先依主 README 配妥 Java、SDK 35 Build Tools、Python、e2fsprogs、libselinux。第二階段另需 `7zz`、`xz`、`qemu-aarch64`、`readelf`、g++、OpenSSL headers 與 libfec headers/library。Debian/Ubuntu 可使用其發行版套件：

```bash
sudo apt-get install 7zip xz-utils qemu-user binutils g++ libssl-dev libfec-dev
export PATH="/usr/sbin:/sbin:$PATH"
```

本次無 sudo，使用雲端既有 g++/OpenSSL headers，並在 workspace 解開 Debian 7zip、QEMU、libfec-dev 套件。版本與下載 SHA 在 `validation/phase2/toolchain.json`。沒有把 host 工具加進 GSI。

準備來源時保留原版解壓映像為唯讀，先核對上述雜湊。串流解壓可保留 zero holes：

```bash
set -euo pipefail
7zz x -so -bsp0 LineageOS-22.2-20260105-GAPPS-EXT4-GSI.7z \
  LineageOS-22.2-20260105-GAPPS-EXT4-GSI.img | cp --sparse=always /dev/stdin original-system.img
sha256sum original-system.img
chmod 444 original-system.img
```

固定來源工具下載與構建：

```bash
./scripts/setup-avb.sh
./scripts/build-fec.sh
# 使用解包到自有目錄的 libfec-dev 時，前綴可用 FEC_PREFIX 指定。
python3 scripts/prepare-idmap2.py --image original-system.img --output work/idmap2-runtime
```

修補與完整重查；輸出與 report 路徑都必須尚不存在：

```bash
./patch.sh --input original-system.img --output work/gsi/system.img \
  --idmap2 "$PWD/work/idmap2-runtime/idmap2-host" \
  --avbtool "$PWD/work/avb-tools/avbtool.py" \
  --avb-key "$PWD/work/avb-tools/testkey_rsa2048.pem" \
  --fec "$PWD/work/fec-bin/fec"

./verify.sh --image work/gsi/system.img --original original-system.img \
  --idmap2 "$PWD/work/idmap2-runtime/idmap2-host" --require-idmap \
  --avbtool "$PWD/work/avb-tools/avbtool.py" --fec "$PWD/work/fec-bin/fec"
```

此特定 GSI 中 `/system/system_ext/overlay` 是 real directory，沒有 config.xml，沒有自訂 partition_order.xml，也沒有同一分區競爭此資源的 RRO。新增的 canonical 路徑是 `/system_ext/overlay/SmA1560FingerprintFix/SmA1560FingerprintFix.apk`，由 manifest `isStatic=true, priority=999` 啟用且不可變；不新建 config.xml，不關閉 MediaTek overlay。

新目錄 0755、新 APK 0644、uid:gid 0:0。**實際原版 file_contexts 的預期標籤是 `u:object_r:vendor_overlay_file:s0`**；既有 overlay directory 也是此標籤。不可想當然改成 system_file。腳本使用實際 libselinux matcher，寫入並讀回 xattr，保存既有 framework、overlay 檔案及 contexts 的比較紀錄。

正常磁碟空間充足時可直接 `xz -T2 -6 --check=crc64 -k work/gsi/system.img`，再做 XZ CRC、解壓大小與 SHA 比對。雲端小磁碟可用已測試的 RAM staging：

```bash
python3 scripts/compress-verified.py --image work/gsi/system.img \
  --receipt work/gsi/system.img.report/receipt.json --output work/gsi/system.img.xz \
  --remove-raw-after-check
```

這先在 sealed Linux memfd 中完成壓縮，執行 xz test，完整解壓比對 raw 大小及 SHA，才清理 receipt 對應的新 raw 副本並寫出壓縮成品；不清理原版輸入。RAM staging 的匿名輸出限制為低於 2 GiB。發布檔使用 LZMA2 preset 6、8 MiB dictionary、CRC64。

## DSU 邊界

離線可以證實的，是 EXT4／AVB／映像大小／壓縮容器及 RRO 構造符合本版本的 system 映像要求。原版大小、分區名稱、公鑰與信任參數均保持一致。但沒有連接 SM-A1560，不能聲稱 Samsung DSU 已接受、已啟動或 AIDL 登記成功。實際操作與判讀見主 README 及本階段測試報告。
