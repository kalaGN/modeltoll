export interface User {
  id: string;
  email: string;
  is_admin: boolean;
  status?: string;
  created_at?: string;
  last_login_at?: string | null;
}
export interface Branding {
  name: string;
  description: string;
  logo_url: string;
}
export interface ApiKey {
  id: string;
  name: string;
  display: string;
  status: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at?: string | null;
  deleted_at?: string | null;
}
export interface KeysResponse {
  items: ApiKey[];
  summary: { total: number; active: number; revoked: number };
}
export interface Range {
  from: string;
  to: string;
}
export interface Point {
  date: string;
  succeeded?: number;
  failed?: number;
  calls?: number;
  amount_yuan?: string;
}
export interface Price {
  version: string;
  model?: string;
  unit_price_yuan: string;
  unit_tokens: number;
  currency: string;
  billing_policy_version: string;
}
export interface Totals {
  calls_total: number;
  calls_succeeded?: number;
  calls_failed?: number;
  calls_in_progress?: number;
  input_tokens?: number;
  billable_tokens?: number;
  charged_amount_yuan?: string;
  charge_count?: number;
  billing_pending_count: number;
}
export interface Summary {
  range: Range;
  totals: Totals;
  series: Point[];
  price?: Price;
}
export interface CallRow {
  request_id: string;
  api_key: string;
  endpoint: string;
  started_at: string;
  status: string;
  input_tokens: number | null;
  duration_ms: number | null;
}
export interface ChargeRow {
  request_id: string;
  api_key: string;
  billable_tokens: number;
  unit_tokens: number;
  unit_price_yuan: string;
  pricing_version: string;
  amount_yuan: string;
}
export interface CursorPage<T> {
  items: T[];
  has_more: boolean;
  next_cursor: string;
}
export interface OffsetPage<T> {
  items: T[];
  page: number;
  total: number;
  has_more: boolean;
}
export interface AuditEvent {
  id: string;
  created_at: string;
  actor_email: string;
  target_email: string;
  action: string;
  previous_status: string;
  new_status: string;
  reason: string;
  target_key_id: string | null;
}
export interface Connection {
  base_url: string;
  model: string;
  timeout_seconds: number;
  enabled: boolean;
}
export interface ConnectionResponse {
  connection: Connection | null;
  runtime: string;
  credential_configured: boolean;
}
