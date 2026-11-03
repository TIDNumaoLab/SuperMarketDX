// 今日の状況 API
import type { Dashboard } from "../types/api";
import { api } from "./client";

export async function getDashboard(): Promise<Dashboard> {
  const res = await api.get<Dashboard>("/api/dashboard");
  return res.data;
}
