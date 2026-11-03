import { expect, test } from "vitest";
import { HOME_PATH, NAV_ITEMS, visibleNav } from "../src/auth/routes";
import type { DepartmentRef, Me } from "../src/types/api";

const veg: DepartmentRef = { code: "VEG", name: "青果", business_type: "order" };
const me = (role: Me["role"], departments: DepartmentRef[]): Me => ({
  user_id: 1,
  name: "a",
  role,
  departments,
  accessible_departments: departments,
});

test("nav has the 10 screens except login, dashboard first", () => {
  expect(NAV_ITEMS.map((n) => n.path)).toEqual([
    "/dashboard",
    "/orders",
    "/production",
    "/orders/approved",
    "/imports",
    "/inventory",
    "/promotions",
    "/calendar",
    "/settings",
    "/review",
  ]);
});

test("home is the dashboard", () => {
  expect(HOME_PATH).toBe("/dashboard");
});

test("staff cannot see calendar and settings", () => {
  const paths = visibleNav(me("staff", [veg])).map((n) => n.path);
  expect(paths).not.toContain("/calendar");
  expect(paths).not.toContain("/settings");
  expect(paths).toContain("/orders/approved");
  expect(paths).toContain("/dashboard");
});

test("manager sees all screens", () => {
  expect(visibleNav(me("manager", []))).toHaveLength(NAV_ITEMS.length);
});
