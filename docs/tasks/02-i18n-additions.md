# Task: Add i18n Keys for Runtime Settings Redesign

在 `frontend/src/lib/i18n.ts` 中，为两种语言分别添加以下 key（加在已有 `runtime.*` key 的同一区域）：

## zh-CN 新增

```typescript
"runtime.executor.type": "CLI 类型",
"runtime.executor.apiEndpoint": "API 地址",
"runtime.executor.apiKey": "API 密钥",
"runtime.executor.defaultModel": "默认模型",
"runtime.executor.addExecutor": "添加执行器",
"runtime.executor.delete": "删除",
"runtime.executor.claudeCli": "Claude CLI",
"runtime.executor.codexCli": "Codex CLI",
"runtime.executor.endpointPlaceholder": "https://api.anthropic.com（留空使用默认）",
"runtime.executor.keyPlaceholder": "sk-...（留空使用环境变量）",
"runtime.executor.modelPlaceholder": "claude-sonnet-4-6",
"runtime.executor.deleteConfirm": "确认删除此执行器？",
"runtime.executor.advanced": "高级配置",
```

## en-US 新增

```typescript
"runtime.executor.type": "CLI Type",
"runtime.executor.apiEndpoint": "API Endpoint",
"runtime.executor.apiKey": "API Key",
"runtime.executor.defaultModel": "Default Model",
"runtime.executor.addExecutor": "Add Executor",
"runtime.executor.delete": "Delete",
"runtime.executor.claudeCli": "Claude CLI",
"runtime.executor.codexCli": "Codex CLI",
"runtime.executor.endpointPlaceholder": "https://api.anthropic.com (leave blank for default)",
"runtime.executor.keyPlaceholder": "sk-... (leave blank to use env var)",
"runtime.executor.modelPlaceholder": "claude-sonnet-4-6",
"runtime.executor.deleteConfirm": "Delete this executor?",
"runtime.executor.advanced": "Advanced",
```
