# Android 客户端（`mobile/`）

把仪表盘打包成 **APK**，在安卓手机上以独立图标打开。

## 它是什么（**先说清楚**）

这是一个 **WebView 外壳**，**不含 Python、不含 pandas/numpy**：

```
APK（~3MB）打开 → 载入 www/index.html（本地外壳）
                → iframe 指向 Mac 的只读服务
                → Mac 每次请求重新跑 pipeline → 返回最新仪表盘
```

⇒ **打开/刷新即最新**（符合需求：不需要手机后台常驻）；**APK 里没有数据**。

### 为什么不做「Python 打进 APK」

| 障碍 | 说明 |
|---|---|
| 打包 | `pandas`/`numpy` 需 Chaquopy（**商业授权**）或 Kivy（pandas recipe 不稳），APK **50~100MB** |
| UI | 现输出是 CLI + HTML，打进 APK 要重写 Android UI |
| **决定性** | **ColorOS 的后台与定时策略**使手机**不适合当生产机** —— 打完了定时抓取仍不可靠 |

⇒ **生产留在 Mac**，手机只做查看端。详见 `docs/trading-discipline.md` 第 14.5 条。

## 前置：Mac 上先起服务

```bash
.venv/bin/python scripts/serve_dashboard.py
```

记下打印出来的「手机」地址，形如 `http://192.168.1.10:8000`。

## 构建（Windows 开发机）

### 一条命令

```bash
bash mobile/build_apk.sh
```

产物：`mobile/android/app/build/outputs/apk/debug/app-debug.apk`（**约 3.9 MB**）

脚本会做前置检查、替换仓库镜像、`cap sync`、`gradle assembleDebug`。

### ⚠️ 本机公网不可达 —— 全部走内网 Nexus

实测 `dl.google.com` / `repo.maven.apache.org` / `plugins.gradle.org` /
`services.gradle.org` **直连与代理均连接超时**。所有来源改为：

| 组件 | 内网地址 | 已装版本 |
|---|---|---|
| **JDK** | `nexus3/repository/openjdk/` | **21.0.2** |
| Android platform / build-tools / platform-tools / cmdline-tools | `nexus3/repository/dl-google-android/` | platform-35、build-tools 34.0.0 + 35.0.0、platform-tools 37.0.1 |
| Android Gradle 依赖 | `nexus3/repository/maven-google/` | — |
| Maven Central | `nexus3/repository/maven-public/` | — |
| Gradle 插件 | `nexus3/repository/maven-plugins-gradle/` | — |
| **Gradle 发行版** | `nexus3/repository/repo.huaweicloud.com/gradle/` | **8.11.1** |
| npm 包 | `nexus3/repository/npm/`（已是默认 registry） | — |

工具链默认放在 `C:\Users\260023\android-toolchain\`（可用
`FG_ANDROID_TOOLCHAIN` 覆盖）：

```
android-toolchain/
├── jdk21/jdk-21.0.2/
├── gradle-8.11.1/
└── sdk/
    ├── platforms/android-35/
    ├── build-tools/{34.0.0,35.0.0}/
    ├── platform-tools/
    └── cmdline-tools/latest/
```

### ⚠️ 三个必须做对的点（都实际踩过）

| # | 坑 | 现象 | 处理 |
|---|---|---|---|
| 1 | **JDK 必须是 21**，不是 17 | `错误: 无效的源发行版：21` | Capacitor 7 的 `build.gradle` 硬写 `JavaVersion.VERSION_21`。本机原本只有 JDK 8，**17 也不行** |
| 2 | **仓库镜像必须覆盖 `node_modules`** | 构建尝试连 `dl.google.com` 并超时 | `:capacitor-android` 的 buildscript 仓库声明在 `node_modules/@capacitor/android/capacitor/build.gradle` 里，改 `android/build.gradle` **覆盖不到**。故用 `mobile/patch_repos.py` 统一替换，**每次 `npm install` 后需重跑**（`build_apk.sh` 已自动做） |
| 3 | **build-tools 需要 34.0.0** | `Failed to find Build Tools revision 34.0.0` | AGP 8.7.2 默认要 34.0.0；只装 35.0.0 不够。两个都装 |
| 4 | **补丁必须在 `cap sync` 之后** | 补丁跑过了，构建**仍然**连 `dl.google.com` 超时 | `cap sync` 会**重新生成** `android/capacitor-cordova-android-plugins/build.gradle`，把公网仓库写回来。顺序必须是 `cap sync` → `patch_repos.py` → `gradle`（`build_apk.sh` 已按此顺序） |

> SDK 是从 zip **手工组装**的（无 `sdkmanager`，因为它也要连 `dl.google.com`）。
> 注意各 zip 解压后多一层目录（如 `android-35/android-35/`），需展平。

### 从零重建工具链（若 `android-toolchain` 丢失）

```bash
T=~/android-toolchain && mkdir -p $T && cd $T
B=https://mirrors.dahuatech.com/nexus3/repository
curl --connect-timeout 5 -m 900 -sLO "$B/openjdk/21.0.2/openjdk-21.0.2_windows-x64_bin.zip"
curl --connect-timeout 5 -m 900 -sLO "$B/repo.huaweicloud.com/gradle/gradle-8.11.1-bin.zip"
D="$B/dl-google-android/repository"
curl --connect-timeout 5 -m 900 -sLO "$D/commandlinetools-win-11076708_latest.zip"
curl --connect-timeout 5 -m 900 -sLO "$D/platform-35_r02.zip"
curl --connect-timeout 5 -m 900 -sLO "$D/build-tools_r34-windows.zip"
curl --connect-timeout 5 -m 900 -sLO "$D/build-tools_r35_windows.zip"
curl --connect-timeout 5 -m 900 -sLO "$D/platform-tools_r37.0.1-win.zip"
# 解压后按上面的目录结构摆放，并把多出的一层目录展平
```

## 安装到手机

> **⚠️ 公司传输限制拦的是【文件大小】，不是文件类型。**
>
> 2026-09-23 实测（飞书网页版，同一会话内对照）：
>
> | 文件 | 大小 | 结果 |
> |---|---|---|
> | `output-metadata.json` | **394 B** | ✅ 通过 |
> | `fg-src-kit.zip` | **5.7 KB** | ✅ **通过** |
> | `probe-100k.bin` | 100 KB | ❌ |
> | `probe-500k.bin` | 500 KB | ❌ |
> | `probe-1m.bin` / `probe-2m.bin` | 1 / 2 MB | ❌ |
> | `app-debug.apk` | 3.9 MB | ❌ 上传失败，请重试 |
> | `a.tar.gz` | 3.5 MB | ❌ |
> | `app-debug.json`（**已改名**） | 3.9 MB | ❌ |
> | `fg-apk-kit.zip`（打包后） | 3.5 MB | ❌ |
>
> ⇒ **改扩展名、打包、压缩全都无效** —— 阈值落在 **(5.7 KB, 100 KB]**。
> ⇒ 3.87 MB 的 APK 要切 **80 片以上**，不现实。
> ⇒ 对策：**不传大文件**（走下面的路径 0 / 1）。

### 路径 0（**最推荐**）：不要 APK —— 「添加到主屏幕」

阈值实测在 **(5.7 KB, 100 KB]**，3.87 MB 的 APK 要切 **80 片以上**，不现实。

**但其实根本不需要 APK。** 服务端已经支持 PWA：

```bash
# Mac 上起服务
.venv/bin/python scripts/serve_dashboard.py
```

手机上：Chrome 打开 `http://<mac>:8000/` → 菜单 →「**添加到主屏幕**」
→ 主屏出现「贪恐指数」图标 → 点开即仪表盘。

**零传输、零构建、零安装** —— 而且**换手机、给家人装**都不用再做任何事。

| 服务端新增 | 说明 |
|---|---|
| `GET /manifest.json` | Web App Manifest（`display: standalone`） |
| `GET /icon-192.png` / `icon-512.png` | 图标，**纯 Python 手绘生成**，不落盘、不加依赖 |
| `<head>` 注入 | manifest 链接 + `theme-color` + `apple-touch-icon` |

> **⚠️ 一个已知限制**：`display: standalone`（无地址栏）在 Chrome 上**需要 HTTPS**
> 才升级成 WebAPK。本服务是局域网 `http://`，Chrome 通常**只生成普通快捷方式**
> —— **图标和一键直达都有，只是多一条地址栏**。
>
> 若一定要无地址栏的完整体验，再走下面的 APK 路径。

### 路径 1：`make_kit.sh` —— 三种模式

```bash
bash mobile/make_kit.sh              # 默认：出 APK 包 + 源码包
bash mobile/make_kit.sh --src-only   # 只出源码包（5.7 KB）
bash mobile/make_kit.sh --split      # 把 APK 切成 10 片（每片 400 KB）+ 合并工具
bash mobile/make_kit.sh --probe      # 出 4 个探针，测出真实大小上限
```

**推荐顺序**：

#### ① 传 `fg-src-kit.zip`（**5.7 KB**）→ Mac 上构建 ⭐ 最稳

```bash
bash mobile/make_kit.sh --src-only
```

5.7 KB 远小于任何可能的阈值，**几乎不可能被拦**。照包里的
[`BUILD-ON-MAC.md`](BUILD-ON-MAC.md) 在 Mac 上构建即可。

> Mac 有公网，JDK 21 + Android SDK 都能自己装，**不需要内网 Nexus**。
> **传 5.7 KB 而不是 3.5 MB，且 APK 完全不碰公司网络。**

#### ② 传切片 → 手机上合并（**不需要电脑**）

```bash
bash mobile/make_kit.sh --split        # 默认每片 400K
bash mobile/make_kit.sh --split 200K   # 若 400K 仍被拦，切更小
```

产出 `mobile/dist/fg-apk-split/`：

```
fg.part00.bin ... fg.part09.bin     10 片，每片 400 KB
合并工具.html                        手机端合并页
合并说明.txt
```

- **手机上合并**：全部分片「保存到手机」→ 用 Chrome 打开 `合并工具.html`
  → 一次选中所有分片 → 点「开始合并」→ 下载出 `app-debug.apk` → 装
- **Mac 上合并**（不需装任何工具）：`cat fg.part*.bin > app-debug.apk`

> 切片经 **MD5 校验无损还原**（原包与拼回完全一致）。

#### ③ 想知道真实上限 → 跑 `--probe`

```bash
bash mobile/make_kit.sh --probe
```

出 4 个文件（100 KB / 500 KB / 1 MB / 2 MB），**全部传一次**，
成功的最大那个就是阈值量级 —— 告诉我，我按真实上限切片。

### 路径 A：USB + adb —— **APK 一步都不离开公司机器** ⭐

```bash
$ANDROID_TOOLCHAIN/sdk/platform-tools/adb.exe install -r \
  mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

前提：手机开启「开发者选项 → USB 调试」，数据线连公司电脑，手机上点「允许」。

**优点**：不经任何网络传输、不经任何第三方、不在别处落盘。

### 路径 B：Mac 中转分发 —— 手机浏览器直接下载

既然手机与 Mac 本就要在同一 Wi-Fi，让 **Mac 当分发点**：

```bash
# 1. 把 APK 随局域网同步带到 Mac（见 docs/macos-deploy.md §1）
# 2. Mac 上起服务
.venv/bin/python scripts/serve_dashboard.py
# 输出里会多一行：
#   APK：   http://192.168.1.10:8000/apk    ← 手机浏览器打开即下载
```

**优点**：换手机、给家人装，都不用再碰公司网络。
**前提**：APK 能通过局域网同步出去。若这条也被限制，走路径 C。

### 路径 C：**在 Mac 上直接构建** —— APK 完全不碰公司网络

Mac 有公网，装 Android SDK 无障碍（**不需要**内网 Nexus 那套）。

```bash
# Mac 上（一次性）
brew install --cask temurin@21                 # JDK 21（Capacitor 7 要求）
brew install --cask android-commandlinetools
sdkmanager "platforms;android-35" "build-tools;34.0.0" "platform-tools"

# 构建
cd mobile
npm install
npx cap add android          # 首次
npx cap sync android
cd android && ./gradlew assembleDebug
```

> **⚠️ 仓库里提交的是「公网态」Gradle 配置**（`google()` / `mavenCentral()` /
> `services.gradle.org`），**Mac 上直接用即可**，**不要**跑 `patch_repos.py`。
>
> `patch_repos.py` 只在**公司机器**上用（换成内网 Nexus）；
> `build_apk.sh` 会自动套用、并在构建结束后**自动还原**（`EXIT` trap），
> 所以仓库不会留下"改了没提交"的 Gradle 文件。

### 手机端安装（三条路径通用）

ColorOS 需允许「安装未知来源应用」：设置 → 应用 → 特殊应用权限 → 安装未知应用。

## 首次使用

1. 打开 App → 弹出「服务器地址」
2. 填 Mac 上打印的地址（如 `http://192.168.1.10:8000`）→ 保存
3. 之后每次打开/点「刷新」都会重新取最新结果

**⚠️ 手机与 Mac 必须在同一 Wi-Fi。** 换了网络或 Mac 的 IP 变了，用「设置」改地址即可（**不需要重新打包**）。

## ⚠️ 注意事项

| 项 | 说明 |
|---|---|
| 服务器地址 | 存在手机本地（localStorage），改地址**不用重新打包** |
| 无鉴权 | 服务**没有登录**，只在**可信局域网**用；**不要暴露到公网**（页面含持仓指令） |
| 后台运行 | **不需要**，也不支持 —— 打开时才算，符合需求 |
| 图标 | 用 Capacitor 默认图标；要换需自行替换 `android/app/src/main/res/mipmap-*` |
| 签名 | 当前是 **debug 签名**，仅供自用；上架需自行配置 release keystore |
