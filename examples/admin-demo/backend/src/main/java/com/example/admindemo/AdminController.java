package com.example.admindemo;

import java.math.BigDecimal;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class AdminController {
    @GetMapping("/health/ready")
    public ReadinessResponse readiness() {
        return new ReadinessResponse("admin-demo-backend", "ready");
    }

    @GetMapping("/dashboard")
    public DashboardResponse dashboard() {
        return new DashboardResponse(
                2846,
                128,
                new BigDecimal("368420"),
                new BigDecimal("26.8"),
                List.of(
                        new Activity(1, "林悦加入了企业账号", "10 分钟前", "user"),
                        new Activity(2, "订单 NS-20260712-1042 已完成支付", "32 分钟前", "order"),
                        new Activity(3, "系统已完成每日数据备份", "1 小时前", "system"),
                        new Activity(4, "周子昂的账号权限已更新", "2 小时前", "user")));
    }

    @GetMapping("/users")
    public List<UserResponse> users() {
        return List.of(
                new UserResponse(1, "陈晓宁", "xiaoning.chen@example.com", "系统管理员", "active", "2026-01-18"),
                new UserResponse(2, "林悦", "yue.lin@example.com", "运营专员", "active", "2026-03-06"),
                new UserResponse(3, "周子昂", "ziang.zhou@example.com", "财务经理", "active", "2025-11-22"),
                new UserResponse(4, "孟雨桐", "yutong.meng@example.com", "访客", "inactive", "2026-05-14"),
                new UserResponse(5, "韩思远", "siyuan.han@example.com", "客户经理", "active", "2026-06-02"));
    }

    @GetMapping("/orders")
    public List<OrderResponse> orders() {
        return List.of(
                new OrderResponse("NS-20260712-1042", "远望科技", "企业协作专业版", new BigDecimal("12999"), "paid", "2026-07-12 09:18"),
                new OrderResponse("NS-20260712-1041", "嘉禾零售", "数据分析扩展包", new BigDecimal("3680"), "pending", "2026-07-12 08:42"),
                new OrderResponse("NS-20260711-1038", "清源设计", "企业协作基础版", new BigDecimal("4999"), "paid", "2026-07-11 17:26"),
                new OrderResponse("NS-20260711-1035", "星洲物流", "自动化工作流套件", new BigDecimal("8600"), "refunded", "2026-07-11 14:08"),
                new OrderResponse("NS-20260710-1029", "北辰教育", "企业协作专业版", new BigDecimal("12999"), "paid", "2026-07-10 11:35"));
    }

    public record ReadinessResponse(String service, String status) {}
    public record DashboardResponse(int totalUsers, int activeOrders, BigDecimal monthlyRevenue, BigDecimal conversionRate, List<Activity> recentActivities) {}
    public record Activity(long id, String description, String occurredAt, String type) {}
    public record UserResponse(long id, String name, String email, String role, String status, String joinedAt) {}
    public record OrderResponse(String id, String customerName, String product, BigDecimal amount, String status, String createdAt) {}
}
