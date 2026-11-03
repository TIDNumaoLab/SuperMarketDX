import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, expect, test, vi } from "vitest";
import * as authApi from "../src/api/auth";
import { AuthProvider } from "../src/auth/AuthContext";
import LoginPage from "../src/pages/LoginPage";
import type { Me } from "../src/types/api";

vi.mock("../src/api/auth");

const deliStaff: Me = {
  user_id: 1,
  name: "惣菜 花子",
  role: "staff",
  departments: [{ code: "DELI", name: "惣菜", business_type: "production" }],
  accessible_departments: [{ code: "DELI", name: "惣菜", business_type: "production" }],
};

function renderLogin() {
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<p>今日の状況画面</p>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

async function submit(id: string, pw: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("ログインID"), id);
  await user.type(screen.getByLabelText("パスワード"), pw);
  await user.click(screen.getByRole("button", { name: "ログイン" }));
}

beforeEach(() => {
  vi.mocked(authApi.fetchMe).mockResolvedValue(null);
});

test("shows error message on 401", async () => {
  vi.mocked(authApi.login).mockRejectedValue({ isAxiosError: true, response: { status: 401, data: { detail: "x" } } });
  renderLogin();
  await submit("u1", "bad");
  expect(await screen.findByText("ログインIDまたはパスワードが正しくありません。")).toBeInTheDocument();
  expect(screen.getByLabelText("ログインID")).toHaveValue("u1");
});

test("navigates to the dashboard after login", async () => {
  vi.mocked(authApi.login).mockResolvedValue(deliStaff);
  renderLogin();
  await submit("hanako", "pass1234");
  expect(await screen.findByText("今日の状況画面")).toBeInTheDocument();
  expect(authApi.login).toHaveBeenCalledWith("hanako", "pass1234");
});
