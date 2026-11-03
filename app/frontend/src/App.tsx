// ルーティングと、ログイン・権限による画面の出し分け
import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useNavigate } from "react-router";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { HOME_PATH, NAV_ITEMS } from "./auth/routes";
import Sidebar from "./components/Sidebar";
import LoginPage from "./pages/LoginPage";
import ApprovedOrdersPage from "./pages/ApprovedOrdersPage";
import OrdersPage from "./pages/OrdersPage";
import CalendarPage from "./pages/CalendarPage";
import DashboardPage from "./pages/DashboardPage";
import ImportsPage from "./pages/ImportsPage";
import InventoryPage from "./pages/InventoryPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import ProductionPage from "./pages/ProductionPage";
import PromotionsPage from "./pages/PromotionsPage";
import SettingsPage from "./pages/SettingsPage";

// 作成済みの画面。無い画面は PlaceholderPage(準備中)を出す
const PAGES: Record<string, () => JSX.Element> = {
  "/dashboard": DashboardPage,
  "/orders": OrdersPage,
  "/orders/approved": ApprovedOrdersPage,
  "/production": ProductionPage,
  "/settings": SettingsPage,
  "/imports": ImportsPage,
  "/inventory": InventoryPage,
  "/promotions": PromotionsPage,
  "/calendar": CalendarPage,
};

function pageFor(path: string, label: string) {
  const Page = PAGES[path];
  return Page ? <Page /> : <PlaceholderPage title={label} />;
}

// ログイン必須の画面の枠(左にサイドバー)
function Layout() {
  const { me, loading, logout } = useAuth();
  const navigate = useNavigate();
  if (loading) {
    return <p style={{ padding: 16 }}>読み込み中…</p>;
  }
  if (!me) {
    return <Navigate to="/login" replace />;
  }
  return (
    <div style={{ display: "flex" }}>
      <Sidebar
        me={me}
        onLogout={async () => {
          await logout();
          navigate("/login", { replace: true });
        }}
      />
      <main style={{ flex: 1, padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}

// 店長専用の画面に担当者が来たら、今日の状況へ戻す
function ManagerOnly({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  if (me && me.role !== "manager") {
    return <Navigate to={HOME_PATH} replace />;
  }
  return <>{children}</>;
}

function Home() {
  const { me } = useAuth();
  return <Navigate to={me ? HOME_PATH : "/login"} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            {NAV_ITEMS.map((item) => (
              <Route
                key={item.path}
                path={item.path}
                element={
                  item.managerOnly ? <ManagerOnly>{pageFor(item.path, item.label)}</ManagerOnly> : pageFor(item.path, item.label)
                }
              />
            ))}
            <Route path="*" element={<Home />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
