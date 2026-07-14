# Vue 3 + Spring Boot 后台管理 Demo

## Goal

在 `examples/admin-demo/` 创建一个可独立运行的后台管理 Demo，用于测试项目启动、源码扫描、页面发现、接口识别和原型生成。

## Requirements

- 前端使用 Vue 3、TypeScript、Vite 和 Vue Router。
- 前端包含三个可通过左侧导航切换的页面：仪表盘、用户管理、订单管理。
- 后端使用 Java 17 和 Spring Boot 3。
- 后端提供三个 GET 接口：`/api/dashboard`、`/api/users`、`/api/orders`。
- 页面必须调用真实后端接口，展示加载、成功和失败状态。
- 后端使用内存固定数据，不依赖数据库、登录或外部服务。
- 前后端分别位于 `examples/admin-demo/frontend/` 和 `examples/admin-demo/backend/`。
- 根目录提供中文 README，写清环境要求和启动命令。

## Acceptance Criteria

- [ ] Vue Router 注册并可访问 `/dashboard`、`/users`、`/orders`。
- [ ] 根路径自动跳转到 `/dashboard`，侧边栏可在三个页面间跳转。
- [ ] 三个页面分别请求对应接口并渲染业务数据。
- [ ] Spring Boot 启动后，三个接口均返回结构明确的 JSON 和 HTTP 200。
- [ ] 前端开发服务器可代理 `/api` 到 Spring Boot，避免本地跨域配置。
- [ ] 前端类型检查与生产构建通过。
- [ ] 后端测试或 Maven package 通过。

## Out of Scope

- 数据库、增删改操作、分页、权限、登录、Docker 和部署配置。
- 接入当前主项目的导航、API 或状态管理。

## Technical Notes

- Demo 是隔离示例，不修改现有产品运行逻辑。
- UI 采用安静、紧凑的后台管理布局，支持桌面和窄屏。
- 默认端口：前端 `5173`，后端 `8080`。
