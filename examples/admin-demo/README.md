# 后台管理 Demo

一个用于源码扫描、页面发现、接口识别和原型生成测试的独立示例项目。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Vue Router、Lucide Vue
- 后端：Java 17+、Spring Boot 3、Maven

## 启动后端

先确认 `java -version` 显示 Java 17 或更高版本。macOS 同时安装了多个
JDK 时，可先执行：

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export PATH="$JAVA_HOME/bin:$PATH"
```

```bash
cd backend
mvn spring-boot:run
```

后端默认运行在 `http://127.0.0.1:8080`。

## 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 `http://127.0.0.1:5173`，Vite 会将 `/api` 请求代理到后端。
如果后端改用了其他端口，可在启动前设置
`VITE_API_PROXY_TARGET`，例如 `VITE_API_PROXY_TARGET=http://127.0.0.1:8081 npm run dev`。

## 页面与接口

| 页面 | 路由 | 接口 |
|---|---|---|
| 后端就绪检查 | — | `GET /api/health/ready`（固定返回 `service=admin-demo-backend`、`status=ready`） |
| 仪表盘 | `/dashboard` | `GET /api/dashboard` |
| 用户管理 | `/users` | `GET /api/users` |
| 订单管理 | `/orders` | `GET /api/orders` |

## 启动就绪识别

项目启动分析应为两个服务分别保存严格的 HTTP 就绪探针：

- 后端：`http://127.0.0.1:8080/api/health/ready`，期望 HTTP 200，JSON 子集为
  `{"service":"admin-demo-backend","status":"ready"}`。
- 前端：`http://127.0.0.1:5173/`，期望 HTTP 200，文本包含
  `Northstar 管理后台`。

两个探针独立判断，端口有任意 HTTP 响应只表示地址被占用，不表示本应用已就绪。
