// 画面の試験の共通部品。各試験ファイルで vi.mock("../src/api/auth") を宣言してから使う
import { render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import * as authApi from "../src/api/auth";
import { AuthProvider, useAuth } from "../src/auth/AuthContext";
import type { DepartmentRef, Me } from "../src/types/api";

export const VEG: DepartmentRef = { code: "VEG", name: "青果", business_type: "order" };
export const FISH: DepartmentRef = { code: "FISH", name: "鮮魚", business_type: "order" };
export const DELI: DepartmentRef = { code: "DELI", name: "惣菜", business_type: "production" };

export function staff(...departments: DepartmentRef[]): Me {
  return { user_id: 1, name: "担当 太郎", role: "staff", departments, accessible_departments: departments };
}

export function manager(): Me {
  return { user_id: 9, name: "店長", role: "manager", departments: [], accessible_departments: [DELI, FISH, VEG] };
}

// 本番の Layout と同じく、ログイン中の利用者を読み込んでから画面を描く
function LoadedOnly({ children }: { children: ReactNode }) {
  const { loading } = useAuth();
  return loading ? null : <>{children}</>;
}

// ログイン中の利用者を me にして画面を描き、読み込みが終わるまで待つ。url で開く URL(クエリつき)を指定できる
export async function renderPage(ui: ReactElement, me: Me, waitText: string, url = "/") {
  vi.mocked(authApi.fetchMe).mockResolvedValue(me);
  const result = render(
    <AuthProvider>
      <MemoryRouter initialEntries={[url]}>
        <LoadedOnly>{ui}</LoadedOnly>
      </MemoryRouter>
    </AuthProvider>,
  );
  await screen.findByText(waitText);
  return result;
}
