# 微软商店不可用时手动安装 OpenAI Codex

来源：[技术栈文章](https://jishuzhan.net/article/2047844923232288770)  
作者：程序员夏末  
发布时间：2026-04-25

## 背景

这篇文章记录了在 Windows 系统中无法正常使用微软商店时，如何绕过商店界面手动安装 OpenAI Codex。

作者遇到的问题包括：

- 微软商店无法正常使用。
- 系统中部分关键组件疑似损坏。
- 已经下载到本地的 `.msix` 安装包，双击后无法安装。
- 双击安装包时出现文件系统错误。

报错示例：

```text
文件系统错误(-2147219196)
```

作者判断，这类问题不一定是安装包本身损坏，更可能是 Windows 处理 `.msix` 安装包时依赖的系统组件、App Installer、微软商店相关服务或文件关联出现异常。

## 核心思路

不要依赖微软商店，也不要通过双击 `.msix` 触发图形化安装流程，而是：

1. 手动获取 Codex 的 `.msix` 安装包。
2. 使用 PowerShell 的 `Add-AppxPackage` 命令直接安装。

这样可以绕过微软商店界面和双击安装时调用的图形化入口。

## 手动获取 Codex 安装包

### 1. 打开微软商店链接解析站点

访问：

```text
https://store.rg-adguard.net
```

### 2. 输入 Codex 的微软商店链接

在解析站点的输入框中填入：

```text
https://apps.microsoft.com/detail/9PLM9XGG6VKS
```

### 3. 选择渠道

右侧下拉框选择：

```text
Retail
```

然后点击查询，页面会返回一批可下载文件。

### 4. 下载 `.msix` 安装包

在返回结果中找到 OpenAI Codex 对应的 `.msix` 文件并下载。

文件名可能类似：

```text
OpenAI.Codex_26.415.3242.0_x64__2p2nqsd0c76g0.Msix
```

注意事项：

- 版本号可能会变化，不需要和文章示例完全一致。
- 重点确认应用名、系统架构和文件后缀是否匹配。
- 如果点击下载没有反应，可能是浏览器或页面拦截了下载。
- 可尝试右键复制下载链接，并在链接前补上 `https://` 后再打开。

## 使用 PowerShell 安装

拿到 `.msix` 文件后，不要双击安装，而是打开 PowerShell，执行：

```powershell
Add-AppxPackage -Path "C:\Users\52412\Desktop\GoogleDownload\OpenAI.Codex_26.415.3242.0_x64__2p2nqsd0c76g0.Msix"
```

实际使用时，需要把 `-Path` 后面的路径替换成本机安装包的真实保存路径。

例如：

```powershell
Add-AppxPackage -Path "D:\Downloads\OpenAI.Codex_x64.Msix"
```

## 为什么 PowerShell 可能成功

双击 `.msix` 和执行 `Add-AppxPackage` 的最终目的都是安装应用包，但调用链路不同：

- 双击 `.msix` 更依赖 Windows 图形界面、文件关联、App Installer 和微软商店相关组件。
- `Add-AppxPackage` 直接调用 Windows 应用包部署能力。

如果系统的图形化安装入口、商店组件或文件关联异常，PowerShell 方式仍然可能正常工作。

## 安装完成后的检查

如果 PowerShell 命令执行结束后没有明显红色报错，一般可以认为安装已经成功。

可以继续检查：

- 打开开始菜单。
- 搜索 `Codex`。
- 确认是否出现 OpenAI Codex。
- 启动应用，检查能否进入主界面。

## 适用场景

这套方法适合以下情况：

- 微软商店打不开或无法下载应用。
- `.msix` 文件双击安装失败。
- 出现文件系统错误，例如 `-2147219196`。
- 暂时不方便重装 Windows 或修复系统组件。
- 想绕过微软商店界面直接安装 Codex。

## 总结

文章给出的关键解决方案是：

1. 使用 `store.rg-adguard.net` 从微软商店链接解析出 Codex 的真实安装包。
2. 下载匹配系统架构的 `.msix` 文件。
3. 不要双击安装包。
4. 使用 PowerShell 执行 `Add-AppxPackage` 直接安装。

这种方式可以在微软商店或图形化安装链路异常时，提高安装成功率。
