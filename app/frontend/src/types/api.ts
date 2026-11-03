// 本体APIの型定義

export type Role = "staff" | "manager";

export interface DepartmentRef {
  code: string;
  name: string;
  business_type: "order" | "production";
}

export interface Me {
  user_id: number;
  name: string;
  role: Role;
  // 所属部門
  departments: DepartmentRef[];
  // 操作できる部門(店長は全部門、担当者は所属部門)
  accessible_departments: DepartmentRef[];
}

export type ImportKind = "products" | "pos" | "inventory" | "waste";

export interface ImportLog {
  id: number;
  kind: ImportKind;
  department_code: string | null;
  file_name: string;
  imported_count: number;
  skipped_count: number;
  errors: { row: number; reason: string }[];
  imported_by_name: string | null;
  finished_at: string;
}

export interface InventoryLatest {
  product_code: string;
  product_name: string;
  quantity: number | null;
  based_at: string | null;
}

export interface InventoryInput {
  department_code: string;
  based_at: string;
  items: { product_code: string; quantity: number }[];
}

// 惣菜の陳列残数の入力(PUT /api/production/display-stock)
// 入力時刻は送らない(保存時のサーバーの時刻を使い、応答で返る)
export interface DisplayStockInput {
  department_code: string;
  target_date: string;
  items: { product_code: string; quantity: number }[];
}

export interface DisplayStockResult {
  saved: number;
  entered_at: string;
  job: Job;
}

export interface Product {
  product_code: string;
  name: string;
  department_code: string;
  department_name: string;
  order_unit: number;
  lead_time_days: number;
  can_carry_over: boolean;
  cost_price: number | null;
  selling_price: number | null;
  is_active: boolean;
}

export interface Promotion {
  id: number;
  product_code: string;
  product_name: string;
  department_code: string;
  department_name: string;
  start_date: string;
  end_date: string;
  description: string;
  created_by_name: string | null;
}

export interface PromotionInput {
  product_code: string;
  start_date: string;
  end_date: string;
  description: string;
}

export interface CalendarDay {
  id: number;
  date: string;
  kind: "holiday" | "event";
  name: string;
}

export type ProposalStatus = "pending" | "approved" | "confirmed" | "expired";
export type WarningCode = "NO_INVENTORY" | "NO_HISTORY" | "NO_WEATHER" | "STALE_POS";
export type AdjustReason = "weather" | "promotion" | "inventory" | "other";

// 提案(詳細設計書「API仕様」の提案(proposal)の項目)。根拠(basis)は平坦に並ぶ
export interface Proposal {
  id: number;
  department_code: string;
  product_code: string;
  product_name: string;
  target_date: string;
  time_band: number | null;
  proposed_qty: number;
  original_qty: number;
  recalculated_qty: number | null;
  is_adjusted: boolean;
  adjust_reason: AdjustReason | null;
  adjust_note: string | null;
  status: ProposalStatus;
  deadline: string;
  approved_by: number | null;
  approved_by_name: string | null;
  approved_at: string | null;
  warnings: WarningCode[];
  order_unit: number;
  calculated_at: string;
  created_at: string;
  updated_at: string;
  predicted_qty: number | null;
  model_version: string | null;
  is_baseline: boolean | null;
  weather_code: number | null;
  weather_label: string | null;
  temperature: number | null;
  precipitation: number | null;
  precipitation_probability: number | null;
  is_holiday: boolean | null;
  is_event_day: boolean | null;
  holiday_name: string | null;
  is_promotion: boolean | null;
  sales_lag_7d: number | null;
  inventory_qty: number | null;
  inventory_based_at: string | null;
  backlog_qty: number | null;
  carry_over_qty: number | null;
  expected_sales_qty: number | null;
  display_stock_qty: number | null;
  weather_fetched_at: string | null;
}

export interface Freshness {
  calculated_at: string | null;
  weather_fetched_at: string | null;
  inventory_based_at: string | null;
}

export interface Job {
  id: number;
  status: "running" | "succeeded" | "failed";
  processed: number;
  total: number;
  error: string | null;
  // 予測の注記(時間帯の設定変更など)
  notice: string | null;
}

export interface ProposalList {
  proposals: Proposal[];
  // 一覧の対象日。惣菜は既定表示でも決めた日、生鮮の既定表示は null
  target_date: string | null;
  freshness: Freshness;
  job: Job | null;
  notice: string | null;
}

export interface BulkApproveResult {
  approved_ids: number[];
  skipped: { id: number; reason: string }[];
}

export interface ApprovedOrder {
  product_code: string;
  product_name: string;
  target_date: string;
  proposed_qty: number;
  order_unit: number;
  status: ProposalStatus;
  approved_by_name: string | null;
  approved_at: string | null;
}

// 設定(GET /api/settings の settings)。キーは詳細設計書「設定項目」
export type Settings = Record<string, unknown>;

// 今日の状況(GET /api/dashboard)
export interface DashboardDepartment {
  department_code: string;
  department_name: string;
  business_type: DepartmentRef["business_type"];
  // この要求で開始した、または実行中のジョブ
  job: Job | null;
  last_job: { status: Job["status"]; finished_at: string | null; error: string | null } | null;
}

export interface DashboardDeadline {
  department_code: string;
  deadline: string;
  target_date: string;
  time_band: number | null;
  pending: number;
  approved: number;
  confirmed: number;
  expired: number;
  // 未承認のうち警告が無く一括承認できる件数
  bulk_approvable: number;
  warnings: { code: WarningCode; count: number }[];
}

export interface TomorrowWeather {
  weather_code: number | null;
  weather_label: string;
  temperature: number | null;
  temperature_min: number | null;
  precipitation: number | null;
  fetched_at: string;
}

export interface Dashboard {
  now: string;
  business_hours: { open: string; close: string };
  departments: DashboardDepartment[];
  deadlines: DashboardDeadline[];
  tomorrow: {
    date: string;
    weather: TomorrowWeather | null;
    promotions: { department_name: string; product_name: string; start_date: string; end_date: string; description: string }[];
    calendar: { kind: "holiday" | "event"; name: string }[];
  };
  data_status: {
    department_code: string;
    pos_latest_date: string | null;
    pos_imported_at: string | null;
    inventory_based_at: string | null;
    stale_pos: boolean;
  }[];
}
