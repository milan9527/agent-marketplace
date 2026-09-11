export type Agent = {
  read_only?: boolean;
  id: string;
  name: string;
  tagline: string;
  description: string;
  category: string;
  skills: string[];
  price: string;
  wallet: string | null;
  is_demo?: boolean;
  bookable?: boolean;
  tools?: string[];
  execution_mode?: "tools" | "local_demo";
  color: string;
  icon: string;
  featured: boolean;
  active: boolean;
  completed_tasks: number;
  rating: number | null;
  review_count: number;
  created_at: string;
};
export type Bid = {
  id: string;
  agent: Agent;
  price: string;
  match_score: number;
  quality_score: number;
  rationale: string;
  within_budget: boolean;
  value_score: number;
};
export type Payment = {
  read_only?: boolean;
  id: string;
  task_id: string;
  task_title: string;
  agent_name: string;
  amount: string;
  status: string;
  provider: string;
  transaction_hash: string | null;
  error: string | null;
  created_at: string;
};
export type Task = {
  read_only?: boolean;
  id: string;
  title: string;
  spec: string;
  category: string;
  budget: string;
  status: string;
  is_demo?: boolean;
  deadline: string;
  selection_mode?: "manual" | "auto";
  agent_scope?: "all" | "demo" | "live";
  selection_reason?: string | null;
  recommended_bid_id?: string | null;
  minimum_auto_match?: number;
  auto_execute?: boolean;
  automation?: {
    status: "queued" | "running" | "blocked" | "review_required" | "completed";
    stage: string;
    attempts: number;
    error: string | null;
  } | null;
  winner_id: string | null;
  created_at: string;
  bids: Bid[];
  delivery: string | null;
  rating: number | null;
  payment: Payment | null;
  requirements?: {
    summary: string;
    web: boolean;
    code: boolean;
    external_actions: string[];
    missing_inputs: string[];
    acceptance_criteria: string[];
  } | null;
  execution?: Execution | null;
};
export type Execution = {
  id: string;
  status: "running" | "validating" | "blocked" | "completed";
  started_at: string;
  updated_at: string;
  steps: number;
  error: string | null;
  has_previous_delivery: boolean;
  trace: {
    id: string;
    tool: string;
    status: "succeeded" | "failed";
    started_at: string;
    finished_at: string;
    input: Record<string, unknown>;
    output: Record<string, unknown>;
  }[];
  sources: {
    id: string;
    title: string;
    url: string;
    published_at?: string | null;
    retrieved_at: string;
    read: boolean;
    sha256?: string;
  }[];
  artifacts: { name: string; bytes: number; sha256: string }[];
  validation?: {
    passed: boolean;
    reason: string;
    checks: { requirement: string; passed: boolean; evidence: string }[];
  } | null;
};
export type User = {
  id: string;
  name: string;
  budget: string;
  spent: string;
  reserved: string;
  remaining: string;
  wallet_connected: boolean;
  wallet_url: string | null;
  wallet_address: string | null;
  wallet_provider: string;
  wallet_shared?: boolean;
  payment_limit?: string | null;
};
export type WalletInfo = {
  provider: string;
  status: string;
  balance: string | null;
  address: string | null;
  network: string;
  wallet_url: string | null;
  message?: string;
};
export type Activity = {
  id: string;
  kind: string;
  message: string;
  task_id: string | null;
  created_at: string;
};
export type Overview = {
  agents: number;
  tasks: number;
  completed: number;
  spent: string;
  events: Activity[];
};
export type AppConfig = {
  mode: "demo" | "aws";
  network: string;
  cognito_domain: string;
  cognito_client_id: string;
  cognito_region: string;
  runtime: string;
  payments: string;
  chain_sync: boolean;
};
export type Page =
  "discover" | "tasks" | "agents" | "payments" | "activity" | "settings";
