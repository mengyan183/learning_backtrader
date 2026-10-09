# 在 Mac 上构建 APK

> **为什么会有这份文档**：公司 DLP **按文件类型**拦截，`.apk` 传不出来
> （飞书上传报「上传失败，请重试」，而 `.json` / `.zip` 能过）。
>
> ⇒ 那就**不传安装包，传源码**：这个包里只有 **约 10 KB**，Mac 有公网，
> 构建所需的一切都能自己装。**APK 从头到尾不碰公司网络。**

---

## 0. 你需要的文件

`fg-src-kit.zip` 里应该只有这些：

```
package.json             Capacitor 依赖声明
capacitor.config.json    应用配置（appId / appName / webDir）
www/index.html           应用外壳（服务器地址设置 + 刷新）
BUILD-ON-MAC.md          本文件
```

> `android/` 目录**故意不包含** —— 它由 `npx cap add android` 重新生成，
> 里面唯一有机器相关内容的 `local.properties` 本来就不该传。

---

## 1. 装工具链（一次性）

```bash
# JDK 21 —— ⚠️ 必须是 21，17 不行（Capacitor 7 硬写 JavaVersion.VERSION_21）
brew install --cask temurin@21

# Android 命令行工具
brew install --cask android-commandlinetools

# 接受许可 + 装平台与构建工具
# ⚠️ build-tools 要 34.0.0（AGP 8.7.2 的默认值），只装 35 不够
sdkmanager --sdk_root="$HOME/Library/Android/sdk" \
    "platform-tools" "platforms;android-35" "build-tools;34.0.0"

export ANDROID_HOME="$HOME/Library/Android/sdk"
export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
```

把这两行 `export` 加到 `~/.zshrc` 里，之后开新终端就不用再敲。

**没有 Homebrew？** 先装：<https://brew.sh>

---

## 2. 构建

```bash
mkdir -p ~/fg-mobile && cd ~/fg-mobile
unzip ~/Downloads/fg-src-kit.zip        # 解到当前目录

npm install                              # Mac 有公网，直连即可
npx cap add android                      # 生成 android/ 工程（首次）
npx cap sync android                     # 把 www/ 同步进去

cd android
./gradlew assembleDebug
```

**⚠️ 不要在 Mac 上跑 `patch_repos.py`** —— 那是给公司机器换内网 Nexus 用的。
Mac 用默认的公网仓库即可。

产物：

```
~/fg-mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

---

## 3. 装到手机

**手机与 Mac 连同一个 Wi-Fi**，然后在 Mac 上起一个下载服务：

```bash
cd ~/fg-mobile/android/app/build/outputs/apk/debug
python3 -m http.server 8899
```

手机浏览器打开 `http://<Mac的IP>:8899/app-debug.apk` 即下载。

查 Mac 的 IP：`ipconfig getifaddr en0`

装的时候 ColorOS 会提示，需允许「安装未知来源应用」：
设置 → 应用 → 特殊应用权限 → 安装未知应用。

**或者**用 USB + adb（需开 USB 调试）：

```bash
adb install -r ~/fg-mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

---

## 4. 首次使用

1. 打开 App → 弹出「服务器地址」
2. 填主系统那边打印的地址，形如 `http://192.168.1.10:8000`
3. 保存

之后每次打开 / 点「刷新」都会重新取最新结果，**不需要后台常驻**。

> 换 IP 或换 Wi-Fi，用 App 里的「设置」改地址即可，**不用重新打包**。

---

## 5. 出问题怎么办

| 现象 | 原因 | 处理 |
|---|---|---|
| `错误: 无效的源发行版：21` | JDK 不是 21 | `export JAVA_HOME="$(/usr/libexec/java_home -v 21)"` |
| `Failed to find Build Tools revision 34.0.0` | 只装了 35 | `sdkmanager "build-tools;34.0.0"` |
| `command not found: sdkmanager` | PATH 没配 | 加 `export PATH="$HOME/Library/Android/sdk/cmdline-tools/latest/bin:$PATH"` |
| `npx cap add android` 报目录已存在 | 重复执行 | 先 `rm -rf android`，或直接 `npx cap sync android` |
| App 白屏 / 一直转圈 | 连不上 Mac | 确认手机与 Mac 同一 Wi-Fi；确认 Mac 上 `serve_dashboard.py` 在跑 |
| App 显示「连接超时」 | 同上 | 同上；也可先用手机浏览器直接开那个地址验证 |

**仍解决不了**：把报错原文贴回来。
