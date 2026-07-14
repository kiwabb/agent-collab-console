export interface DashboardData {
  totalUsers: number;
  activeOrders: number;
  monthlyRevenue: number;
  conversionRate: number;
  recentActivities: Activity[];
}

export interface Activity {
  id: number;
  description: string;
  occurredAt: string;
  type: "user" | "order" | "system";
}

export interface User {
  id: number;
  name: string;
  email: string;
  role: string;
  status: "active" | "inactive";
  joinedAt: string;
}

export interface Order {
  id: string;
  customerName: string;
  product: string;
  amount: number;
  status: "paid" | "pending" | "refunded";
  createdAt: string;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getDashboard: () => get<DashboardData>("/api/dashboard"),
  getUsers: () => get<User[]>("/api/users"),
  getOrders: () => get<Order[]>("/api/orders"),
};
