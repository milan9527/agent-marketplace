import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Bell,
  Blocks,
  Bot,
  ChartNoAxesCombined,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  CirclePlus,
  Clock3,
  Code2,
  Compass,
  CreditCard,
  Database,
  ExternalLink,
  Eye,
  FileText,
  Globe2,
  Layers3,
  LayoutGrid,
  LoaderCircle,
  LogOut,
  Menu,
  Network,
  PenTool,
  Plus,
  Radar,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Star,
  Wallet,
  Workflow,
  X,
  Zap,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { api, completeSignIn, post, signOut } from "./api";
import LoginPage from "./LoginPage";
import type {
  Agent,
  AppConfig,
  Overview,
  Page,
  Payment,
  Task,
  User,
  WalletInfo,
} from "./types";

type CatalogPage = "discover" | "agents";
type CatalogFilters = {
  query: string;
  category: string;
  sort: string;
  onlyFeatured: boolean;
};
const defaultCatalogFilters: CatalogFilters = {
  query: "",
  category: "All agents",
  sort: "recommended",
  onlyFeatured: false,
};

const categories = [
  "All agents",
  "Research",
  "Finance",
  "Development",
  "Content",
  "Data",
  "Automation",
];
const categoryIcons: Record<string, LucideIcon> = {
  "All agents": LayoutGrid,
  Research: Globe2,
  Finance: ChartNoAxesCombined,
  Development: Code2,
  Content: PenTool,
  Data: Database,
  Automation: Workflow,
};
const agentIcons: Record<string, LucideIcon> = {
  globe: Globe2,
  chart: ChartNoAxesCombined,
  code: Code2,
  pen: PenTool,
  database: Database,
  workflow: Workflow,
  radar: Radar,
  sparkles: Sparkles,
};
const pageNames: Record<Page, string> = {
  discover: "Discover agents",
  tasks: "My tasks",
  agents: "My agents",
  payments: "Payments",
  activity: "Activity",
  settings: "Settings",
};
const statuses: Record<string, string> = {
  open: "Open",
  quoting: "Collecting bids",
  bidding: "Bids received",
  awaiting_payment: "Awaiting payment",
  paying: "Processing payment",
  paid: "Ready for delivery",
  demo_ready: "Ready to run demo",
  delivering: "Working on it",
  completed: "Completed",
  payment_review: "Review required",
  payment_failed: "Payment failed",
  settled: "Settled",
  pending: "Pending",
  failed: "Failed",
  review_required: "Review required",
};
const cash = (value: string | number, min = 2) =>
  Number(value).toLocaleString("en-US", {
    minimumFractionDigits: min,
    maximumFractionDigits: 6,
  });
const date = (value: string) =>
  new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
type ModalState =
  | { type: "task-form"; agent?: Agent }
  | { type: "agent-form" }
  | { type: "agent"; agent: Agent }
  | { type: "task"; task: Task }
  | { type: "wallet" }
  | { type: "guide" }
  | null;

function AgentIcon({
  agent,
  small = false,
}: {
  agent: Pick<Agent, "icon" | "color">;
  small?: boolean;
}) {
  const Icon = agentIcons[agent.icon] || Sparkles;
  return (
    <span className={`agent-icon ${agent.color} ${small ? "small" : ""}`}>
      <Icon size={small ? 19 : 25} strokeWidth={1.7} />
    </span>
  );
}

function Status({ status }: { status: string }) {
  return (
    <span className={`status status-${status}`}>
      <i />
      {statuses[status] || status}
    </span>
  );
}

function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
      if (e.key === "Tab") {
        const elements = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input, select, textarea, [tabindex="0"]',
        );
        if (!elements?.length) return;
        const first = elements[0],
          last = elements[elements.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = originalOverflow;
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? "modal-wide" : ""}`}
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        tabIndex={-1}
      >
        <header className="modal-header">
          <div>
            <h2 id="modal-title">{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon size={29} strokeWidth={1.5} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}

function HeroArt() {
  return (
    <div className="hero-art" aria-hidden="true">
      <div className="art-grid" />
      <div className="orbit orbit-one" />
      <div className="orbit orbit-two" />
      <svg className="connections" viewBox="0 0 380 250">
        <path d="M70 64 195 121 309 55M195 121 304 203M195 121 70 204" />
        <circle cx="195" cy="121" r="5" />
      </svg>
      <div className="art-core">
        <Layers3 size={45} strokeWidth={1.4} />
        <span>agent market</span>
      </div>
      <div className="art-node node-one">
        <Globe2 size={25} />
        <span>Research</span>
      </div>
      <div className="art-node node-two">
        <Code2 size={26} />
        <span>Build</span>
      </div>
      <div className="art-node node-three">
        <ChartNoAxesCombined size={25} />
        <span>Analyze</span>
      </div>
      <span className="art-dot dot-one" />
      <span className="art-dot dot-two" />
      <div className="art-payment">
        <span>
          <Check size={12} />
        </span>
        Outcome delivered <b>↗</b>
      </div>
    </div>
  );
}

function AgentCard({
  agent,
  onOpen,
  onHire,
}: {
  agent: Agent;
  onOpen: () => void;
  onHire: () => void;
}) {
  return (
    <article className="agent-card">
      <div className="card-top">
        <AgentIcon agent={agent} />
        <span className="category-label">{agent.category}</span>
        {agent.is_demo && <span className="demo-profile-badge">Demo</span>}
        {agent.read_only && <span className="demo-profile-badge">Shared</span>}
        {agent.featured && (
          <span className="featured-mark" title="Editor's pick">
            <Sparkles size={14} />
          </span>
        )}
      </div>
      <button className="card-title" onClick={onOpen}>
        {agent.name}
        <ArrowUpRight size={17} />
      </button>
      <p className="agent-tagline">{agent.tagline}</p>
      <p className="agent-description">{agent.description}</p>
      <div className="tags">
        {agent.skills.slice(0, 3).map((skill) => (
          <span key={skill}>{skill}</span>
        ))}
      </div>
      <div className="card-proof">
        <span>
          <Star size={13} className={agent.rating ? "star-filled" : ""} />
          {agent.rating ? (
            <>
              <strong>{agent.rating.toFixed(1)}</strong>{" "}
              <span>({agent.review_count})</span>
            </>
          ) : agent.is_demo ? (
            "Demo workflow"
          ) : (
            "New agent"
          )}
        </span>
        <span>
          <CheckCheck size={14} />
          {agent.is_demo
            ? "No wallet needed"
            : `${agent.completed_tasks} tasks`}
        </span>
      </div>
      <div className="card-footer">
        <div>
          <strong>
            {agent.is_demo ? "Free demo" : `$${cash(agent.price)}`}
          </strong>
          {!agent.is_demo && <span> / task</span>}
        </div>
        <button onClick={agent.bookable === false ? onOpen : onHire}>
          {agent.bookable === false
            ? "View profile"
            : agent.is_demo
              ? "Try agent"
              : "Hire agent"}{" "}
          <ArrowRight size={15} />
        </button>
      </div>
    </article>
  );
}

export default function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [page, setPage] = useState<Page>(() => {
    const hash = location.hash.slice(1) as Page;
    return Object.hasOwn(pageNames, hash) ? hash : "discover";
  });
  const [catalogFilters, setCatalogFilters] = useState<
    Record<CatalogPage, CatalogFilters>
  >({
    discover: { ...defaultCatalogFilters },
    agents: { ...defaultCatalogFilters },
  });
  const catalogPage: CatalogPage = page === "agents" ? "agents" : "discover";
  const { query, category, sort, onlyFeatured } = catalogFilters[catalogPage];
  function updateCatalogFilters(
    changes: Partial<CatalogFilters>,
    target: CatalogPage = catalogPage,
  ) {
    setCatalogFilters((current) => ({
      ...current,
      [target]: { ...current[target], ...changes },
    }));
  }
  const [modal, setModal] = useState<ModalState>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [ownAgents, setOwnAgents] = useState<Agent[]>([]);
  const [walletInfo, setWalletInfo] = useState<WalletInfo | null>(null);

  const refresh = useCallback(async () => {
    const [
      nextAgents,
      nextTasks,
      nextPayments,
      nextOverview,
      nextUser,
      nextOwn,
    ] = await Promise.all([
      api<Agent[]>("/agents"),
      api<Task[]>("/tasks"),
      api<Payment[]>("/payments"),
      api<Overview>("/overview"),
      api<User>("/me"),
      api<Agent[]>("/agents?mine=true"),
    ]);
    setAgents(nextAgents);
    setTasks(nextTasks);
    setPayments(nextPayments);
    setOverview(nextOverview);
    setUser(nextUser);
    setOwnAgents(nextOwn);
  }, []);

  useEffect(() => {
    const expired = () => {
      setAuthRequired(true);
      setUser(null);
      setModal(null);
    };
    window.addEventListener("auth-expired", expired);
    async function start() {
      let loadedConfig: AppConfig | null = null;
      try {
        const c = await api<AppConfig>("/config");
        loadedConfig = c;
        setConfig(c);
        await completeSignIn(c);
        if (
          (c.mode === "aws" && !sessionStorage.getItem("access_token")) ||
          location.pathname === "/login"
        ) {
          setAuthRequired(true);
          return;
        }
        await refresh();
      } catch (e) {
        setError((e as Error).message);
        if (
          loadedConfig?.mode === "aws" &&
          !sessionStorage.getItem("access_token")
        ) {
          setAuthRequired(true);
        }
      } finally {
        setLoading(false);
      }
    }
    void start();
    return () => window.removeEventListener("auth-expired", expired);
  }, [refresh]);

  useEffect(() => {
    const sync = () => {
      const hash = location.hash.slice(1) as Page;
      if (Object.hasOwn(pageNames, hash)) setPage(hash);
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    if (
      modal?.type !== "task" ||
      !(
        ["quoting", "paying", "delivering"].includes(modal.task.status) ||
        ["queued", "running"].includes(modal.task.automation?.status || "")
      )
    )
      return;
    const id = modal.task.id;
    const timer = setInterval(() => {
      api<Task>(`/tasks/${id}`)
        .then((task) =>
          setModal((current) =>
            current?.type === "task" && current.task.id === id
              ? { type: "task", task }
              : current,
          ),
        )
        .catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [modal]);

  useEffect(() => {
    if (
      !tasks.some((task) =>
        ["queued", "running"].includes(task.automation?.status || ""),
      )
    )
      return;
    const timer = setInterval(() => void refresh().catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [tasks, refresh]);

  function navigate(next: Page) {
    setPage(next);
    location.hash = next;
    setMobileNav(false);
  }

  async function run(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function openWallet() {
    setModal({ type: "wallet" });
    setWalletInfo(null);
    if (user?.wallet_connected || config?.mode === "demo") {
      await run(async () => setWalletInfo(await api<WalletInfo>("/me/wallet")));
    }
  }

  async function taskAction(task: Task, action: string, data: unknown = {}) {
    await run(async () => {
      try {
        const updated = await post<Task>(`/tasks/${task.id}/${action}`, data);
        setModal({ type: "task", task: updated });
        await refresh();
        setToast(
          action === "pay"
            ? "Payment settled. Your agent is ready to work."
            : action === "deliver"
              ? "Your deliverable is ready."
              : action === "rate"
                ? "Thanks! Your review has been recorded."
                : "Task updated.",
        );
      } catch (e) {
        const updated = await api<Task>(`/tasks/${task.id}`).catch(() => null);
        if (updated) setModal({ type: "task", task: updated });
        await refresh().catch(() => {});
        throw e;
      }
    });
  }

  function exportPayments() {
    const cell = (v: string) =>
      `"${(/^[=+\-@]/.test(v) ? "'" + v : v).replace(/"/g, '""')}"`;
    const rows = [
      [
        "Payment ID",
        "Task",
        "Agent",
        "USDC",
        "Status",
        "Provider",
        "Transaction",
        "Date",
      ],
      ...payments.map((p) => [
        p.id,
        p.task_title,
        p.agent_name,
        p.amount,
        p.status,
        p.provider,
        p.transaction_hash || "",
        p.created_at,
      ]),
    ];
    const url = URL.createObjectURL(
      new Blob([rows.map((row) => row.map(cell).join(",")).join("\n")], {
        type: "text/csv",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "marketplace-payments.csv";
    a.click();
    URL.revokeObjectURL(url);
    setToast("Payment history exported.");
  }

  const filtered = (page === "agents" ? ownAgents : agents)
    .filter(
      (agent) =>
        (category === "All agents" || agent.category === category) &&
        (!onlyFeatured || agent.featured) &&
        `${agent.name} ${agent.description} ${agent.skills.join(" ")}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "price"
        ? Number(a.price) - Number(b.price)
        : sort === "rating"
          ? (b.rating || 0) - (a.rating || 0)
          : Number(b.featured) - Number(a.featured),
    );
  const activeTasks = tasks.filter((t) => t.status !== "completed").length;

  const closeModal = () => {
    if (!busy) setModal(null);
  };
  const formBusy = (
    <>
      <LoaderCircle size={16} className="spin" /> Working…
    </>
  );

  if (authRequired && config) {
    return (
      <LoginPage
        config={config}
        onSignedIn={async () => {
          await refresh();
          setError("");
          setAuthRequired(false);
          history.replaceState({}, "", "/#discover");
          setPage("discover");
        }}
      />
    );
  }

  return (
    <div className="app-shell">
      {mobileNav && (
        <div className="nav-backdrop" onClick={() => setMobileNav(false)} />
      )}
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <a
          className="brand"
          href="#discover"
          onClick={() => navigate("discover")}
        >
          <span className="brand-mark">
            <Layers3 size={25} strokeWidth={1.8} />
          </span>
          <span>
            agent<span className="brand-light">market</span>
            <small>INTELLIGENCE, ON DEMAND</small>
          </span>
        </a>
        <button
          className="workspace-select"
          onClick={() => navigate("settings")}
        >
          <span className="workspace-avatar">A</span>
          <span>
            Personal workspace<small>Builder plan</small>
          </span>
          <ChevronDown size={15} />
        </button>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {(
            [
              ["discover", Compass],
              ["tasks", Layers3],
              ["agents", Bot],
              ["payments", CreditCard],
              ["activity", Activity],
            ] as [Page, LucideIcon][]
          ).map(([key, Icon]) => (
            <button
              key={key}
              className={`nav-item ${page === key ? "active" : ""}`}
              onClick={() => navigate(key)}
            >
              <Icon size={19} strokeWidth={1.7} />
              <span>{pageNames[key]}</span>
              {key === "tasks" && activeTasks > 0 && (
                <small className="nav-count">{activeTasks}</small>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-grow" />
        <div className="builder-card">
          <span className="builder-icon">
            <Code2 size={19} />
          </span>
          <h4>Build. Publish. Earn.</h4>
          <p>
            Give your agent a place
            <br />
            to do its best work.
          </p>
          <button onClick={() => setModal({ type: "agent-form" })}>
            Publish an agent <ArrowUpRight size={15} />
          </button>
        </div>
        <button
          className={`nav-item ${page === "settings" ? "active" : ""}`}
          onClick={() => navigate("settings")}
        >
          <Settings2 size={18} />
          Settings
        </button>
        <button
          className="nav-item"
          onClick={() => setModal({ type: "guide" })}
        >
          <CircleHelp size={18} />
          How it works
          <ArrowUpRight size={14} className="nav-external" />
        </button>
        <div className="runtime-indicator">
          <span className="live-dot" />
          <div>
            {config?.mode === "aws"
              ? "AgentCore connected"
              : "Local demo environment"}
            <small>
              {config?.mode === "aws"
                ? config.network
                : "Explore with simulated USDC"}
            </small>
          </div>
        </div>
        <button className="user-menu" onClick={() => navigate("settings")}>
          <span className="user-avatar">
            {(user?.name || "Builder").slice(0, 1)}
          </span>
          <span>
            {user?.name || "Your workspace"}
            <small>
              {config?.mode === "aws" ? "Connected account" : "Demo account"}
            </small>
          </span>
          <ChevronDown size={15} />
        </button>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Open navigation"
            onClick={() => setMobileNav(true)}
          >
            <Menu size={22} />
          </button>
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <strong>{pageNames[page]}</strong>
          </div>
          <div className="topbar-actions">
            <span className="network-badge">
              <span />
              {config?.network || "Base Sepolia"}
            </span>
            <button
              className="notification-button"
              aria-label="View activity"
              onClick={() => navigate("activity")}
            >
              <Bell size={18} />
              {overview?.events.length ? <i /> : null}
            </button>
            <span className="top-avatar">A</span>
          </div>
        </header>
        <main>
          {error && (
            <div
              className={`error-banner ${modal ? "floating-error" : ""}`}
              role="alert"
            >
              <span>{error}</span>
              <button
                className="icon-button"
                onClick={() => setError("")}
                aria-label="Dismiss error"
              >
                <X size={17} />
              </button>
            </div>
          )}
          {loading ? (
            <div className="loading-screen">
              <LoaderCircle size={28} className="spin" />
              <p>Getting your workspace ready…</p>
            </div>
          ) : !user ? (
            <EmptyState
              icon={Network}
              title="Let's reconnect"
              description="The marketplace API could not be reached. Start the backend and try again."
              action={
                <button
                  className="button primary"
                  onClick={() => void run(refresh)}
                >
                  Try again <ArrowRight size={16} />
                </button>
              }
            />
          ) : (
            <>
              {page === "discover" && (
                <>
                  <div className="page-heading">
                    <div>
                      <div className="eyebrow">
                        THE AGENT ECONOMY STARTS HERE
                      </div>
                      <h1>
                        Discover your next advantage
                        <span className="orange-text">.</span>
                      </h1>
                      <p>
                        Find the right intelligence. Put it to work. Pay for
                        what it delivers.
                      </p>
                    </div>
                    <button
                      className="button primary"
                      onClick={() => setModal({ type: "task-form" })}
                    >
                      <Plus size={17} />
                      Post a task
                    </button>
                  </div>
                  <section className="hero">
                    <div className="hero-content">
                      <div className="hero-pill">
                        <Sparkles size={12} />
                        SMALL TASKS. BIG POSSIBILITIES.
                      </div>
                      <h2>
                        Specialist agents.
                        <br />
                        <em>Extraordinary outcomes.</em>
                      </h2>
                      <p>
                        A world of expertise, one task away. Discover autonomous
                        <br className="desktop-break" /> agents that research,
                        build, and create alongside you.
                      </p>
                      <div className="hero-actions">
                        <button
                          className="button dark"
                          onClick={() => setModal({ type: "task-form" })}
                        >
                          Put an agent to work <ArrowUpRight size={17} />
                        </button>
                        <button
                          className="text-button"
                          onClick={() => setModal({ type: "guide" })}
                        >
                          How it works <span className="play-circle">▶</span>
                        </button>
                      </div>
                      <div className="hero-trust">
                        <ShieldCheck size={14} />
                        Budget-controlled payments
                        <span />
                        Powered by Amazon Bedrock AgentCore
                      </div>
                    </div>
                    <HeroArt />
                  </section>
                  <section
                    className="metrics"
                    aria-label="Marketplace statistics"
                  >
                    {(
                      [
                        [
                          Bot,
                          "Listed agents",
                          overview?.agents || 0,
                          "Specialists to explore",
                        ],
                        [
                          Layers3,
                          "Your tasks",
                          overview?.tasks || 0,
                          "Ideas put into motion",
                        ],
                        [
                          CheckCheck,
                          "Tasks completed",
                          overview?.completed || 0,
                          "Outcomes delivered",
                        ],
                        [
                          Wallet,
                          "Total spent",
                          `$${cash(overview?.spent || "0")}`,
                          "USDC · Pay per task",
                        ],
                      ] as [LucideIcon, string, string | number, string][]
                    ).map(([Icon, label, value, caption]) => (
                      <div className="metric" key={label}>
                        <span className="metric-icon">
                          <Icon size={19} strokeWidth={1.6} />
                        </span>
                        <div>
                          <span className="metric-label">{label}</span>
                          <strong>{value}</strong>
                          <small>{caption}</small>
                        </div>
                      </div>
                    ))}
                  </section>
                </>
              )}
              {(page === "discover" || page === "agents") && (
                <section className="catalog-section">
                  {page === "agents" ? (
                    <div className="page-heading">
                      <div>
                        <div className="eyebrow">YOUR SPECIALIST TEAM</div>
                        <h1>My agents</h1>
                        <p>
                          {ownAgents.some((agent) => agent.read_only)
                            ? "Your published agents and shared business demo profiles."
                            : "Expertise you've published to the marketplace."}
                        </p>
                      </div>
                      <button
                        className="button primary"
                        onClick={() => setModal({ type: "agent-form" })}
                      >
                        <Plus size={16} />
                        Publish an agent
                      </button>
                    </div>
                  ) : (
                    <div className="section-heading">
                      <div>
                        <h2>Find your kind of brilliant</h2>
                        <p>Explore specialists and find the right expertise.</p>
                      </div>
                      <span className="subtle-label">
                        <span className="live-dot" />
                        {agents.length > 0 &&
                        agents.every((agent) => agent.bookable === false)
                          ? "Demo catalog"
                          : "Open for business"}
                      </span>
                    </div>
                  )}
                  {page === "discover" &&
                    agents.some((agent) => agent.is_demo) && (
                      <div className="demo-catalog-note">
                        <Sparkles size={18} />
                        <p>
                          <strong>Explore the demo catalog.</strong> Post a
                          task, compare demo bids, and generate a deliverable.
                          Demo agents run free, with no wallet or payment
                          required.
                        </p>
                      </div>
                    )}
                  <div className="catalog-tools">
                    <div className="search-input">
                      <Search size={18} />
                      <input
                        aria-label="Search agents"
                        placeholder="Search agents, skills, or possibilities…"
                        value={query}
                        onChange={(e) =>
                          updateCatalogFilters({ query: e.target.value })
                        }
                      />
                      {query ? (
                        <button
                          aria-label="Clear search"
                          onClick={() => updateCatalogFilters({ query: "" })}
                        >
                          <X size={15} />
                        </button>
                      ) : (
                        <kbd>⌕</kbd>
                      )}
                    </div>
                    <button
                      className={`button filter-button ${onlyFeatured ? "filter-on" : ""}`}
                      aria-pressed={onlyFeatured}
                      onClick={() =>
                        updateCatalogFilters({ onlyFeatured: !onlyFeatured })
                      }
                    >
                      <SlidersHorizontal size={16} />
                      Featured {onlyFeatured && <Check size={13} />}
                    </button>
                  </div>
                  <div className="category-tabs" aria-label="Agent categories">
                    {categories.map((c) => {
                      const Icon = categoryIcons[c];
                      return (
                        <button
                          key={c}
                          className={category === c ? "selected" : ""}
                          onClick={() => updateCatalogFilters({ category: c })}
                        >
                          <Icon size={15} />
                          {c}
                          {c === "All agents" && (
                            <small>
                              {page === "agents"
                                ? ownAgents.length
                                : agents.length}
                            </small>
                          )}
                        </button>
                      );
                    })}
                  </div>
                  <div className="result-row">
                    <span>
                      <strong>{filtered.length}</strong> agents for your next
                      big thing
                    </span>
                    <label>
                      Sort by:{" "}
                      <select
                        aria-label="Sort agents"
                        value={sort}
                        onChange={(e) =>
                          updateCatalogFilters({ sort: e.target.value })
                        }
                      >
                        <option value="recommended">Recommended</option>
                        <option value="price">Lowest price</option>
                        <option value="rating">Highest rated</option>
                      </select>
                    </label>
                  </div>
                  {filtered.length ? (
                    <div className="agent-grid">
                      {filtered.map((agent) => (
                        <AgentCard
                          key={agent.id}
                          agent={agent}
                          onOpen={() => setModal({ type: "agent", agent })}
                          onHire={() => setModal({ type: "task-form", agent })}
                        />
                      ))}
                    </div>
                  ) : page === "agents" && ownAgents.length === 0 ? (
                    <EmptyState
                      icon={Bot}
                      title="No agents published yet"
                      description="Agents you publish and profiles shared with your account appear here. Browse Discover agents to hire a specialist."
                      action={
                        <button
                          className="button secondary"
                          onClick={() => setModal({ type: "agent-form" })}
                        >
                          Publish an agent
                        </button>
                      }
                    />
                  ) : (
                    <EmptyState
                      icon={Search}
                      title="No agents found"
                      description="Try a different search or publish a specialist of your own."
                      action={
                        <button
                          className="button secondary"
                          onClick={() =>
                            updateCatalogFilters(defaultCatalogFilters)
                          }
                        >
                          Clear filters
                        </button>
                      }
                    />
                  )}
                  <div className="publish-banner">
                    <div className="publish-art">
                      <Blocks size={33} strokeWidth={1.4} />
                    </div>
                    <div>
                      <h3>Your agent could be someone's next breakthrough.</h3>
                      <p>
                        Bring your expertise to the marketplace. Connect with
                        tasks. Earn per outcome.
                      </p>
                    </div>
                    <button
                      className="button secondary"
                      onClick={() => setModal({ type: "agent-form" })}
                    >
                      Publish an agent <ArrowUpRight size={16} />
                    </button>
                  </div>
                </section>
              )}
              {page === "tasks" && (
                <>
                  <div className="page-heading">
                    <div>
                      <div className="eyebrow">FROM NEED TO OUTCOME</div>
                      <h1>My tasks</h1>
                      <p>
                        Your ideas, in good hands. Follow every bid, payment,
                        and delivery.
                      </p>
                    </div>
                    <button
                      className="button primary"
                      onClick={() => setModal({ type: "task-form" })}
                    >
                      <Plus size={17} />
                      Post a task
                    </button>
                  </div>
                  <div className="summary-pills">
                    <span>
                      <i className="dot-orange" />
                      {activeTasks} in progress
                    </span>
                    <span>
                      <i className="dot-green" />
                      {tasks.length - activeTasks} completed
                    </span>
                  </div>
                  {tasks.some((task) => task.read_only) && (
                    <div className="demo-catalog-note">
                      <Eye size={18} />
                      <p>
                        <strong>Shared test tasks.</strong> Explore bids,
                        payment receipts, and completed deliverables. Shared
                        tasks are read-only; you can also post your own tasks.
                      </p>
                    </div>
                  )}
                  {tasks.length ? (
                    <div className="task-list">
                      {tasks.map((task) => (
                        <button
                          className="task-row"
                          key={task.id}
                          onClick={() => setModal({ type: "task", task })}
                        >
                          <span className="task-icon">
                            <FileText size={21} />
                          </span>
                          <div className="task-row-title">
                            <h3>{task.title}</h3>
                            {task.is_demo && (
                              <span className="demo-profile-badge">
                                Demo · No charge
                              </span>
                            )}
                            {task.read_only && (
                              <span className="demo-profile-badge">
                                Shared · Read only
                              </span>
                            )}
                            <p>
                              {task.category}
                              <span>·</span>
                              {date(task.created_at)}
                              <span>·</span>
                              {task.bids.length} bids
                            </p>
                          </div>
                          <Status status={task.status} />
                          <div className="task-budget">
                            <strong>${cash(task.budget)}</strong>
                            <small>max. budget</small>
                          </div>
                          <ChevronRight size={18} />
                        </button>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      icon={Layers3}
                      title="Good things start with a task"
                      description="Describe what you need, set a budget, and let specialist agents compete to help."
                      action={
                        <button
                          className="button primary"
                          onClick={() => setModal({ type: "task-form" })}
                        >
                          <Plus size={16} />
                          Post your first task
                        </button>
                      }
                    />
                  )}
                </>
              )}
              {page === "payments" && (
                <>
                  <div className="page-heading">
                    <div>
                      <div className="eyebrow">EVERY CENT, ACCOUNTED FOR</div>
                      <h1>Payments</h1>
                      <p>
                        Clear budgets. Transparent transactions. Intelligence
                        that pays off.
                      </p>
                    </div>
                    <button
                      className="button secondary"
                      onClick={exportPayments}
                      disabled={!payments.length}
                    >
                      <ArrowDownToLine size={16} />
                      Export history
                    </button>
                  </div>
                  <div className="payment-cards">
                    <div className="balance-card">
                      <span>
                        <Wallet size={18} />
                        Remaining spending limit
                      </span>
                      <strong>
                        ${cash(user.remaining)} <small>USDC</small>
                      </strong>
                      <p>
                        {config?.mode === "demo"
                          ? "Demo allowance · No real funds are moved"
                          : "Application allowance · Not your wallet balance"}
                      </p>
                      <button onClick={() => navigate("settings")}>
                        Manage spending limit <ArrowRight size={15} />
                      </button>
                    </div>
                    <div className="spend-card">
                      <span>Total settled</span>
                      <strong>${cash(user.spent)}</strong>
                      <p>
                        {
                          payments.filter(
                            (p) => p.status === "settled" && !p.read_only,
                          ).length
                        }{" "}
                        successful transactions
                      </p>
                      <span className="reserved">
                        Reserved: ${cash(user.reserved)} USDC
                      </span>
                    </div>
                    <div className="provider-card">
                      <span className="provider-icon">
                        <ShieldCheck size={25} />
                      </span>
                      <h3>Payments that work for agents.</h3>
                      <p>
                        {config?.mode === "demo"
                          ? "Simulated x402 payments keep your local workspace ready to explore."
                          : "AgentCore Payments signs. The x402 facilitator verifies and settles."}
                      </p>
                      <button
                        className="text-button"
                        onClick={() => void openWallet()}
                      >
                        {user.wallet_connected
                          ? "Stripe / Privy wallet"
                          : "Connect existing wallet"}{" "}
                        <ArrowUpRight size={15} />
                      </button>
                    </div>
                  </div>
                  <div className="section-heading">
                    <h2>Transaction history</h2>
                    <span className="subtle-label">
                      {payments.length} transactions
                    </span>
                  </div>
                  {payments.some((payment) => payment.read_only) && (
                    <div className="demo-catalog-note">
                      <Eye size={18} />
                      <p>
                        Shared test transactions are shown for reference and do
                        not count toward your spending.
                      </p>
                    </div>
                  )}
                  {payments.length ? (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Task / agent</th>
                            <th>Date</th>
                            <th>Amount</th>
                            <th>Status</th>
                            <th>Receipt</th>
                          </tr>
                        </thead>
                        <tbody>
                          {payments.map((p) => (
                            <tr key={p.id}>
                              <td>
                                <button
                                  className="table-link"
                                  onClick={() => {
                                    const task = tasks.find(
                                      (t) => t.id === p.task_id,
                                    );
                                    if (task) setModal({ type: "task", task });
                                  }}
                                >
                                  {p.task_title}
                                </button>
                                <small>{p.agent_name}</small>
                                {p.read_only && (
                                  <small>Shared test transaction</small>
                                )}
                              </td>
                              <td>{date(p.created_at)}</td>
                              <td className="mono">
                                ${cash(p.amount)}
                                <small>USDC</small>
                              </td>
                              <td>
                                <Status status={p.status} />
                              </td>
                              <td>
                                {p.transaction_hash ? (
                                  <a
                                    href={`https://sepolia.basescan.org/tx/${p.transaction_hash}`}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    View transaction <ExternalLink size={13} />
                                  </a>
                                ) : (
                                  <span className="muted">
                                    {p.provider === "demo"
                                      ? "Demo receipt"
                                      : "Not confirmed"}
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <EmptyState
                      icon={CreditCard}
                      title="Your first outcome is waiting"
                      description="Payments appear here when you hire an agent. You'll always see the price before paying."
                    />
                  )}
                </>
              )}
              {page === "activity" && (
                <>
                  <div className="page-heading">
                    <div>
                      <div className="eyebrow">
                        A CLEAR VIEW OF YOUR WORKSPACE
                      </div>
                      <h1>Activity</h1>
                      <p>
                        Task updates, payments, and milestones, all in one
                        place.
                      </p>
                    </div>
                    <button
                      className="button secondary"
                      disabled={busy}
                      onClick={() => void run(refresh)}
                    >
                      <Activity size={16} />
                      Refresh
                    </button>
                  </div>
                  {overview?.events.length ? (
                    <div className="activity-list">
                      {overview.events.map((event) => (
                        <div className="activity-row" key={event.id}>
                          <span
                            className={`activity-icon ${event.kind.includes("payment") ? "orange" : "green"}`}
                          >
                            {event.kind.includes("payment") ? (
                              <Wallet size={18} />
                            ) : event.kind === "delivered" ? (
                              <CheckCheck size={18} />
                            ) : (
                              <Zap size={18} />
                            )}
                          </span>
                          <div>
                            <h3>{event.message}</h3>
                            <p>
                              {date(event.created_at)} at{" "}
                              {new Date(event.created_at).toLocaleTimeString(
                                "en-US",
                                { hour: "2-digit", minute: "2-digit" },
                              )}
                            </p>
                          </div>
                          {event.task_id && (
                            <button
                              className="text-button"
                              onClick={() => {
                                const task = tasks.find(
                                  (t) => t.id === event.task_id,
                                );
                                if (task) setModal({ type: "task", task });
                              }}
                            >
                              View task <ArrowUpRight size={14} />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      icon={Activity}
                      title="A fresh start"
                      description="Publish an agent or post a task to start building your activity history."
                    />
                  )}
                </>
              )}
              {page === "settings" && (
                <>
                  <div className="page-heading">
                    <div>
                      <div className="eyebrow">MAKE IT YOURS</div>
                      <h1>Workspace settings</h1>
                      <p>
                        Your account, spending guardrails, and connected
                        services.
                      </p>
                    </div>
                  </div>
                  <div className="settings-grid">
                    <section className="settings-panel">
                      <h3>
                        <Wallet size={19} />
                        Spending guardrails
                      </h3>
                      <p>
                        Set the total amount this account can spend. Settled and
                        reserved payments count toward this limit.
                      </p>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          const data = new FormData(e.currentTarget);
                          void run(async () => {
                            await api("/me/budget", {
                              method: "PATCH",
                              body: JSON.stringify({
                                budget: data.get("budget"),
                              }),
                            });
                            await refresh();
                            setToast("Spending limit updated.");
                          });
                        }}
                      >
                        <label>
                          Total spending limit (USDC)
                          <input
                            key={user.budget}
                            name="budget"
                            type="number"
                            min="0.000001"
                            max="1000"
                            step="0.000001"
                            defaultValue={Number(user.budget)}
                            required
                          />
                        </label>
                        <div className="settings-totals">
                          <span>
                            Spent <b>${cash(user.spent)}</b>
                          </span>
                          <span>
                            Reserved <b>${cash(user.reserved)}</b>
                          </span>
                        </div>
                        <button className="button primary" disabled={busy}>
                          {busy ? formBusy : "Save spending limit"}
                        </button>
                      </form>
                    </section>
                    <section className="settings-panel">
                      <h3>
                        <Network size={19} />
                        Connected services
                      </h3>
                      <dl className="service-list">
                        <div>
                          <dt>Environment</dt>
                          <dd>
                            {config?.mode === "demo"
                              ? "Local demonstration"
                              : "AWS"}
                          </dd>
                        </div>
                        <div>
                          <dt>Agent runtime</dt>
                          <dd>{config?.runtime}</dd>
                        </div>
                        <div>
                          <dt>Payments</dt>
                          <dd>{config?.payments}</dd>
                        </div>
                        <div>
                          <dt>Settlement network</dt>
                          <dd>{config?.network}</dd>
                        </div>
                        <div>
                          <dt>Reputation storage</dt>
                          <dd>Marketplace database</dd>
                        </div>
                      </dl>
                      <p className="small-note">
                        {config?.mode === "demo"
                          ? "Demo agents and payments are simulated. Your tasks, reviews, and activity are saved in the database."
                          : "Contract sources are included with this project. On-chain registry and reputation synchronization is not enabled."}
                      </p>
                    </section>
                    <section className="settings-panel">
                      <h3>
                        <ShieldCheck size={19} />
                        Your account
                      </h3>
                      <div className="account-info">
                        <span className="user-avatar">
                          {user.name.slice(0, 1)}
                        </span>
                        <div>
                          <strong>{user.name}</strong>
                          <p>
                            {config?.mode === "demo"
                              ? "Shared local demo account"
                              : "Authenticated with Amazon Cognito"}
                          </p>
                        </div>
                      </div>
                      {config?.mode === "aws" && (
                        <>
                          <dl className="service-list">
                            <div>
                              <dt>Account ID</dt>
                              <dd className="wallet-address">{user.id}</dd>
                            </div>
                          </dl>
                          <button
                            className="button secondary"
                            onClick={() => signOut(config)}
                          >
                            <LogOut size={16} />
                            Sign out
                          </button>
                        </>
                      )}
                    </section>
                  </div>
                </>
              )}
              <footer className="footer">
                <span>
                  <Layers3 size={14} />
                  Built for a world where agents work together.
                </span>
                <span>
                  Powered by <strong>Amazon Bedrock AgentCore</strong>
                  <i />
                  {config?.mode === "demo" ? "DEMO" : "AWS"}
                </span>
              </footer>
            </>
          )}
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <span>
            <Check size={15} />
          </span>
          {toast}
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={15} />
          </button>
        </div>
      )}
      {busy && (
        <div className="busy-indicator" role="status">
          <LoaderCircle size={15} className="spin" />
          Processing your request…
        </div>
      )}
      {modal && renderModal()}
    </div>
  );

  function renderModal() {
    if (!modal) return null;
    if (modal.type === "task-form") {
      const agent = modal.agent;
      return (
        <Modal
          title={
            agent
              ? `${agent.is_demo ? "Try" : "Work with"} ${agent.name}`
              : "What can an agent do for you?"
          }
          subtitle="A clear brief is the start of a great outcome."
          onClose={closeModal}
        >
          <form
            className="modal-form"
            onSubmit={(e: FormEvent<HTMLFormElement>) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              void run(async () => {
                const task = await post<Task>("/tasks", {
                  title: data.get("title"),
                  spec: data.get("spec"),
                  category: data.get("category"),
                  budget: data.get("budget"),
                  deadline: new Date(
                    Date.now() + Number(data.get("hours")) * 3600000,
                  ).toISOString(),
                  preferred_agent_id: agent?.id || null,
                  selection_mode: data.get("selection_mode") || "manual",
                  auto_execute: data.get("selection_mode") === "auto",
                  agent_scope: agent
                    ? agent.is_demo
                      ? "demo"
                      : "live"
                    : data.get("agent_scope") || "all",
                });
                setModal({ type: "task", task });
                navigate("tasks");
                await refresh();
                if (task.auto_execute) {
                  setToast(
                    "Automatic task started. Bidding, payment, and delivery continue in the background.",
                  );
                  return;
                }
                const quoted = await post<Task>(`/tasks/${task.id}/quote`);
                setModal({ type: "task", task: quoted });
                await refresh();
                setToast(
                  quoted.winner_id
                    ? "Your agent was selected automatically. Review the next step."
                    : "Your task is live. Explore the bids.",
                );
              });
            }}
          >
            {agent && (
              <div className="selected-agent">
                <AgentIcon agent={agent} small />
                <strong>{agent.name}</strong>
                <span>
                  {agent.is_demo
                    ? "Free demo · No wallet needed"
                    : `$${cash(agent.price)} / task`}
                </span>
              </div>
            )}
            <label>
              Task title
              <input
                name="title"
                placeholder="e.g. Analyze the competitive landscape for AI coding tools"
                minLength={3}
                maxLength={160}
                required
                autoFocus
              />
            </label>
            <label>
              Your brief
              <textarea
                name="spec"
                placeholder="Describe what you need, provide any relevant data, and tell the agent what a successful deliverable looks like."
                minLength={10}
                maxLength={8000}
                rows={5}
                required
              />
            </label>
            <label>
              Category
              <select
                name="category"
                defaultValue={agent?.category || "Research"}
              >
                {categories.slice(1).map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <div className="form-columns">
              <label>
                Maximum budget (USDC)
                <input
                  name="budget"
                  type="number"
                  min="0.000001"
                  max="100"
                  step="0.000001"
                  defaultValue={agent ? Number(agent.price) : "0.05"}
                  required
                />
              </label>
              <label>
                Accept bids for
                <select name="hours" defaultValue="24">
                  <option value="1">1 hour</option>
                  <option value="24">24 hours</option>
                  <option value="72">3 days</option>
                  <option value="168">7 days</option>
                </select>
              </label>
            </div>
            <div className="form-columns">
              <label>
                Agent selection
                <select name="selection_mode" defaultValue="manual">
                  <option value="manual">I'll choose an agent</option>
                  <option value="auto">Automatic: bid, pay & run</option>
                </select>
              </label>
              {!agent && (
                <label>
                  Agent pool
                  <select name="agent_scope" defaultValue="all">
                    <option value="all">All available agents</option>
                    <option value="demo">Free demo agents</option>
                    <option value="live">Paid agents</option>
                  </select>
                </label>
              )}
            </div>
            <p className="small-note">
              Automatic mode collects bids, selects a qualifying agent, pays
              through AgentCore Payments, and generates the deliverable.
              Publishing an automatic task authorizes the winning payment up to
              your task budget and remaining account allowance. Requires at
              least a 70% match; ranks quality × match / price.
            </p>
            <div className="form-note">
              <ShieldCheck size={17} />
              <span>
                Posting is free. Demo agents deliver without a payment.
                Automatic paid tasks use your connected Stripe / Privy wallet.
                Manual tasks wait for you to approve payment.
                {config?.mode === "demo" && " Demo payments use no real funds."}
              </span>
            </div>
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={closeModal}
                disabled={busy}
              >
                Cancel
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? (
                  formBusy
                ) : (
                  <>
                    Post task & get bids <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
          </form>
        </Modal>
      );
    }
    if (modal.type === "agent-form")
      return (
        <Modal
          title="Put your agent on the map."
          subtitle="Publish a specialist and start earning per outcome."
          onClose={closeModal}
        >
          <form
            className="modal-form"
            onSubmit={(e) => {
              e.preventDefault();
              const data = new FormData(e.currentTarget);
              void run(async () => {
                await post("/agents", {
                  name: data.get("name"),
                  tagline: data.get("tagline"),
                  description: data.get("description"),
                  category: data.get("category"),
                  skills: String(data.get("skills"))
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                  price: data.get("price"),
                  wallet: data.get("wallet"),
                });
                await refresh();
                setModal(null);
                updateCatalogFilters(defaultCatalogFilters, "agents");
                navigate("agents");
                setToast("Your agent is now on the marketplace.");
              });
            }}
          >
            <div className="form-columns">
              <label>
                Agent name
                <input
                  name="name"
                  placeholder="e.g. Nova Analyst"
                  minLength={2}
                  maxLength={80}
                  required
                />
              </label>
              <label>
                Category
                <select name="category">
                  {categories.slice(1).map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              One-line introduction
              <input
                name="tagline"
                placeholder="What makes your agent different?"
                minLength={5}
                maxLength={180}
                required
              />
            </label>
            <label>
              Specialist instructions
              <textarea
                name="description"
                rows={4}
                placeholder="Describe the expertise, approach, and deliverables your agent provides. This profile guides the hosted specialist."
                minLength={20}
                maxLength={4000}
                required
              />
            </label>
            <label>
              Skills{" "}
              <span className="label-hint">Separate with commas · up to 8</span>
              <input
                name="skills"
                placeholder="Market research, Strategy, Reports"
                required
              />
            </label>
            <label>
              Price per task (USDC)
              <input
                name="price"
                type="number"
                min="0.000001"
                max="100"
                step="0.000001"
                defaultValue="0.03"
                required
              />
            </label>
            <label>
              Recipient wallet address
              <input
                name="wallet"
                className="mono"
                placeholder="0x…"
                pattern="0x[0-9a-fA-F]{40}"
                maxLength={42}
                required
              />
            </label>
            <div className="form-note">
              <Bot size={18} />
              <span>
                {config?.mode === "demo"
                  ? "This profile runs with a simulated specialist in demo mode."
                  : "Your specialist profile runs in the shared AgentCore bidder runtime using Amazon Bedrock."}{" "}
                Use a wallet you control to receive payments.
              </span>
            </div>
            <div className="modal-actions">
              <button
                className="button secondary"
                type="button"
                onClick={closeModal}
                disabled={busy}
              >
                Cancel
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? (
                  formBusy
                ) : (
                  <>
                    Publish agent <ArrowUpRight size={16} />
                  </>
                )}
              </button>
            </div>
          </form>
        </Modal>
      );
    if (modal.type === "agent") {
      const agent = modal.agent;
      return (
        <Modal title={agent.name} subtitle={agent.tagline} onClose={closeModal}>
          <div className="agent-detail">
            <AgentIcon agent={agent} />
            <span className="category-label">{agent.category}</span>
            {agent.is_demo && (
              <span className="demo-profile-badge">Demo profile</span>
            )}
            <p>{agent.description}</p>
            <div className="tags">
              {agent.skills.map((s) => (
                <span key={s}>{s}</span>
              ))}
            </div>
            <dl className="service-list">
              <div>
                <dt>{agent.is_demo ? "Demo run" : "Per task"}</dt>
                <dd>
                  {agent.is_demo
                    ? "Free · No payment required"
                    : `$${cash(agent.price)} USDC`}
                </dd>
              </div>
              <div>
                <dt>Completed tasks</dt>
                <dd>{agent.completed_tasks}</dd>
              </div>
              <div>
                <dt>{agent.is_demo ? "Feedback" : "Verified reviews"}</dt>
                <dd>
                  {agent.is_demo
                    ? "Saved privately with your demo tasks"
                    : agent.rating
                      ? `${agent.rating} / 5 · ${agent.review_count} reviews`
                      : "No reviews yet"}
                </dd>
              </div>
              <div>
                <dt>Recipient wallet</dt>
                <dd className="wallet-address">
                  {agent.wallet || "Not needed for demo runs"}
                </dd>
              </div>
            </dl>
            {agent.is_demo && (
              <div className="demo-catalog-note">
                <Sparkles size={18} />
                <p>
                  Try the complete workflow: post a brief, compare bids, select
                  an agent, and generate your demo deliverable. No wallet is
                  charged.
                </p>
              </div>
            )}
            <button
              className="button primary full-width"
              disabled={agent.bookable === false}
              onClick={() => setModal({ type: "task-form", agent })}
            >
              {agent.is_demo ? "Try" : "Work with"} {agent.name}{" "}
              <ArrowRight size={16} />
            </button>
          </div>
        </Modal>
      );
    }
    if (modal.type === "task") {
      const task = modal.task;
      const winner = task.bids.find((b) => b.agent.id === task.winner_id);
      const autoRunning = ["queued", "running"].includes(
        task.automation?.status || "",
      );
      const stage =
        task.status === "completed"
          ? 4
          : ["paid", "delivering"].includes(task.status)
            ? 3
            : [
                  "awaiting_payment",
                  "demo_ready",
                  "paying",
                  "payment_review",
                  "payment_failed",
                ].includes(task.status)
              ? 2
              : task.status === "bidding"
                ? 1
                : 0;
      return (
        <Modal
          title={task.title}
          subtitle={`${task.category} · Posted ${date(task.created_at)}`}
          wide
          onClose={closeModal}
        >
          <div className="task-detail">
            {task.read_only && (
              <div className="demo-catalog-note">
                <Eye size={18} />
                <p>
                  <strong>Shared demo task · Read only.</strong> View the
                  original bids and payment record, and download the
                  deliverable.
                </p>
              </div>
            )}
            <div className="task-stepper">
              {[
                "Post",
                "Compare bids",
                task.is_demo ? "Run demo" : "Pay",
                "Deliver",
                task.is_demo ? "Feedback" : "Review",
              ].map((step, i) => (
                <div className={i <= stage ? "step-active" : ""} key={step}>
                  <span>{i < stage ? <Check size={12} /> : i + 1}</span>
                  {step}
                </div>
              ))}
            </div>
            <div className="task-detail-meta">
              <Status status={task.status} />
              {task.is_demo && (
                <span className="demo-profile-badge">Demo · No charge</span>
              )}
              <span>
                Budget <strong>${cash(task.budget)} USDC</strong>
              </span>
            </div>
            {task.automation && (
              <div
                className={`form-note ${["blocked", "review_required"].includes(task.automation.status) ? "warning" : ""}`}
              >
                {autoRunning ? (
                  <LoaderCircle size={18} className="spin" />
                ) : (
                  <Sparkles size={18} />
                )}
                <span>
                  <strong>
                    {task.status === "completed"
                      ? "Task completed"
                      : autoRunning
                        ? "Automatic workflow is running"
                        : task.automation.status === "review_required"
                          ? "Payment needs review"
                          : "Automatic workflow paused"}
                  </strong>
                  <br />
                  {task.status === "completed"
                    ? "Your result is saved and ready to download."
                    : autoRunning
                      ? "Bidding, selection, payment, and delivery continue in the background. You can close this page."
                      : task.automation.error}
                </span>
              </div>
            )}
            <div className="brief-box">
              <h4>THE BRIEF</h4>
              <p>{task.spec}</p>
              <small>
                <Clock3 size={12} /> Bidding closes{" "}
                {new Date(task.deadline).toLocaleString("en-US")}
              </small>
            </div>
            {(task.selection_reason || task.selection_mode === "auto") && (
              <div className="form-note">
                <Sparkles size={18} />
                <span>
                  <strong>
                    {task.selection_mode === "auto"
                      ? "Automatic selection"
                      : "Agent selection"}
                  </strong>
                  <br />
                  {task.selection_reason ||
                    (task.auto_execute
                      ? "The best qualifying bid will be selected, paid within your budget, and executed automatically."
                      : "The best qualifying bid will be selected once quotes arrive. Payment still requires your confirmation.")}
                </span>
              </div>
            )}
            {task.bids.some((bid) => bid.agent.is_demo) && (
              <div className="demo-catalog-note">
                <Sparkles size={18} />
                <p>
                  {task.is_demo
                    ? "This is a free demo workflow. Quotes use example prices to compare agents; your wallet and spending limit are not charged."
                    : "Demo bids run free without a wallet. Live agents use the normal payment flow."}
                </p>
              </div>
            )}
            {!task.read_only &&
              !autoRunning &&
              [
                "open",
                "bidding",
                "awaiting_payment",
                "paid",
                "demo_ready",
              ].includes(task.status) && (
                <div className="checkout-box">
                  <div>
                    <Sparkles size={20} />
                    <span>
                      <strong>Run the remaining steps automatically.</strong>
                      <small>
                        Authorize bidding, selection, payment up to $
                        {cash(task.budget)} USDC, and delivery within your
                        account allowance.
                      </small>
                    </span>
                  </div>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => void taskAction(task, "automate")}
                  >
                    {busy
                      ? formBusy
                      : task.auto_execute
                        ? "Resume automatic task"
                        : "Run automatically"}
                  </button>
                </div>
              )}
            {!task.read_only && !autoRunning && task.status === "open" && (
              <button
                className="button primary"
                disabled={busy}
                onClick={() => void taskAction(task, "quote")}
              >
                {busy ? (
                  formBusy
                ) : (
                  <>
                    Find matching agents <Sparkles size={16} />
                  </>
                )}
              </button>
            )}
            {["quoting", "paying", "delivering"].includes(task.status) && (
              <div className="processing-note">
                <LoaderCircle size={20} className="spin" />
                <p>{statuses[task.status]}… This view updates automatically.</p>
              </div>
            )}
            {!task.read_only && !autoRunning && task.status === "bidding" && (
              <div className="checkout-box">
                <div>
                  <Sparkles size={20} />
                  <span>
                    <strong>Let the marketplace choose.</strong>
                    <small>
                      At least {task.minimum_auto_match || 70}% match, within
                      budget, then highest quality × match / price. You confirm
                      any payment.
                    </small>
                  </span>
                </div>
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => void taskAction(task, "auto-select")}
                >
                  {busy ? (
                    formBusy
                  ) : (
                    <>
                      Choose best agent <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </div>
            )}
            {task.bids.length > 0 && (!task.delivery || task.read_only) && (
              <>
                <div className="section-heading compact">
                  <h3>
                    {task.read_only
                      ? "Bid history"
                      : winner
                        ? "Your chosen specialist"
                        : `${task.bids.length} specialists. Your choice.`}
                  </h3>
                  {!winner && (
                    <span className="subtle-label">
                      Ranked by quality × match / price
                    </span>
                  )}
                </div>
                <div className="bid-list">
                  {(winner && !task.read_only ? [winner] : task.bids).map(
                    (bid, i) => (
                      <div
                        key={bid.id}
                        className={`bid-card ${i === 0 && bid.within_budget ? "best-bid" : ""}`}
                      >
                        <div className="bid-header">
                          <AgentIcon agent={bid.agent} small />
                          <div>
                            <strong>{bid.agent.name}</strong>
                            {task.read_only &&
                              bid.agent.id === task.winner_id && (
                                <span className="demo-profile-badge">
                                  Selected
                                </span>
                              )}
                            {bid.agent.is_demo && (
                              <span className="demo-profile-badge">
                                Free demo
                              </span>
                            )}
                            <small>
                              {bid.match_score}% match · {bid.quality_score}/100
                              quality
                            </small>
                          </div>
                          {(bid.id === task.recommended_bid_id || i === 0) &&
                            bid.within_budget &&
                            !winner && (
                              <span className="best-label">
                                <Sparkles size={10} />
                                {bid.id === task.recommended_bid_id
                                  ? "Recommended"
                                  : "Best value"}
                              </span>
                            )}
                          <strong className="bid-price">
                            {bid.agent.is_demo && <small>Example quote </small>}
                            ${cash(bid.price)}
                          </strong>
                        </div>
                        <p>{bid.rationale}</p>
                        {!task.read_only &&
                          !autoRunning &&
                          task.status === "bidding" && (
                            <button
                              className={`button ${i === 0 ? "primary" : "secondary"} small-button`}
                              disabled={
                                busy ||
                                !bid.within_budget ||
                                bid.agent.bookable === false
                              }
                              onClick={() =>
                                void taskAction(task, "select", {
                                  bid_id: bid.id,
                                })
                              }
                            >
                              {bid.within_budget ? (
                                <>
                                  {bid.agent.is_demo
                                    ? "Choose demo agent"
                                    : "Choose agent"}{" "}
                                  <ArrowRight size={13} />
                                </>
                              ) : (
                                "Over budget"
                              )}
                            </button>
                          )}
                      </div>
                    ),
                  )}
                </div>
              </>
            )}
            {!task.read_only &&
              !autoRunning &&
              task.status === "awaiting_payment" &&
              winner && (
                <div className="checkout-box">
                  <div>
                    <ShieldCheck size={20} />
                    <span>
                      <strong>One task. One clear price.</strong>
                      <small>
                        {config?.mode === "demo"
                          ? "Simulated payment · No real funds"
                          : "USDC · AgentCore Payments · Base Sepolia"}
                      </small>
                    </span>
                  </div>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => {
                      if (config?.mode === "aws" && !user?.wallet_connected)
                        void openWallet();
                      else void taskAction(task, "pay");
                    }}
                  >
                    {busy ? (
                      formBusy
                    ) : config?.mode === "aws" && !user?.wallet_connected ? (
                      "Connect Stripe / Privy"
                    ) : (
                      <>
                        Pay ${cash(winner.price)} & authorize{" "}
                        <ArrowRight size={16} />
                      </>
                    )}
                  </button>
                </div>
              )}
            {!task.read_only &&
              !autoRunning &&
              task.status === "demo_ready" && (
                <div className="checkout-box">
                  <div>
                    <Sparkles size={21} />
                    <span>
                      <strong>Your demo agent is ready.</strong>
                      <small>
                        Generate a deliverable. No wallet, payment, or
                        spending-limit deduction.
                      </small>
                    </span>
                  </div>
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => void taskAction(task, "deliver")}
                  >
                    {busy ? (
                      formBusy
                    ) : (
                      <>
                        Run demo <ArrowRight size={16} />
                      </>
                    )}
                  </button>
                </div>
              )}
            {!task.read_only && !autoRunning && task.status === "paid" && (
              <div className="checkout-box">
                <div>
                  <CheckCheck size={21} />
                  <span>
                    <strong>Payment confirmed.</strong>
                    <small>
                      Start delivery. Retries never charge you again.
                    </small>
                  </span>
                </div>
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => void taskAction(task, "deliver")}
                >
                  {busy ? (
                    formBusy
                  ) : (
                    <>
                      Get deliverable <Sparkles size={16} />
                    </>
                  )}
                </button>
              </div>
            )}
            {["payment_review", "payment_failed"].includes(task.status) && (
              <div className="form-note warning">
                <CircleHelp size={18} />
                <span>
                  {task.payment?.error ||
                    "Please contact your workspace operator to review this payment."}{" "}
                  Reference: {task.payment?.id}
                </span>
              </div>
            )}
            {task.delivery && (
              <>
                <div className="delivery-header">
                  <h3>
                    <CheckCheck size={19} />
                    Your outcome, delivered.
                  </h3>
                  <button
                    className="text-button"
                    onClick={() => {
                      const url = URL.createObjectURL(
                        new Blob([task.delivery!], { type: "text/markdown" }),
                      );
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `delivery-${task.id}.md`;
                      a.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    <ArrowDownToLine size={15} />
                    Download
                  </button>
                </div>
                <div className="markdown">
                  <ReactMarkdown>{task.delivery}</ReactMarkdown>
                </div>
                {!task.read_only && (
                  <div className="review-box">
                    <div>
                      <strong>
                        {task.rating
                          ? "Thanks for sharing your experience."
                          : "How did your agent do?"}
                      </strong>
                      <p>
                        {task.is_demo
                          ? "Demo feedback is saved to this task and does not affect paid-agent reputation."
                          : task.rating
                            ? "Your verified review contributes to this agent’s reputation."
                            : "Help the next person find great intelligence."}
                      </p>
                    </div>
                    <div className="rating-stars">
                      {[1, 2, 3, 4, 5].map((score) => (
                        <button
                          key={score}
                          aria-label={`Rate ${score} stars`}
                          disabled={busy || !!task.rating}
                          onClick={() =>
                            void taskAction(task, "rate", { score })
                          }
                        >
                          <Star
                            size={24}
                            className={
                              task.rating && score <= task.rating
                                ? "star-filled"
                                : ""
                            }
                          />
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </Modal>
      );
    }
    if (modal.type === "wallet") {
      return (
        <Modal
          title={
            config?.mode === "demo"
              ? "Room to explore."
              : "Your Stripe / Privy wallet"
          }
          subtitle="Your existing wallet. Connected to AgentCore Payments."
          onClose={closeModal}
        >
          <div className="modal-form">
            {config?.mode === "demo" ? (
              <>
                <div className="form-note">
                  <Wallet size={22} />
                  <span>
                    This local workspace uses simulated USDC. Your existing
                    Stripe/Privy wallet is only accessed after AWS payment
                    resources are configured.
                  </span>
                </div>
                <button className="button primary" onClick={closeModal}>
                  Got it <Check size={16} />
                </button>
              </>
            ) : walletInfo ? (
              <>
                <div className="selected-agent">
                  <span className="agent-icon purple small">
                    <Wallet size={19} />
                  </span>
                  <strong>{walletInfo.provider}</strong>
                  <span>{walletInfo.status}</span>
                </div>
                <dl className="service-list">
                  <div>
                    <dt>Network</dt>
                    <dd>{walletInfo.network}</dd>
                  </div>
                  <div>
                    <dt>Wallet balance</dt>
                    <dd>
                      {walletInfo.balance === null
                        ? "Unavailable"
                        : `${cash(walletInfo.balance)} USDC`}
                    </dd>
                  </div>
                  <div>
                    <dt>Wallet address</dt>
                    <dd className="wallet-address">
                      {walletInfo.address || "Not available"}
                    </dd>
                  </div>
                </dl>
                <p className="small-note">
                  {user?.wallet_shared && (
                    <>
                      Shared test wallet. Your account has a total allowance of{" "}
                      {cash(user.payment_limit || "0")} USDC, with{" "}
                      {cash(user.remaining)} USDC remaining. The wallet balance
                      is shared; your tasks and payment records belong to your
                      account.{" "}
                    </>
                  )}
                  Task payments use this wallet through AgentCore Payments.
                  Privy signing permissions are checked when you authorize a
                  payment.
                </p>
                <div className="modal-actions">
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => void openWallet()}
                  >
                    {busy ? formBusy : "Refresh balance"}
                  </button>
                  {walletInfo.wallet_url && (
                    <a
                      className="button primary"
                      href={walletInfo.wallet_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Manage in Privy <ExternalLink size={15} />
                    </a>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="form-note">
                  <ShieldCheck size={20} />
                  <span>
                    Connect your existing Stripe/Privy wallet to pay for agent
                    tasks. You'll review the exact price before authorizing each
                    payment.
                  </span>
                </div>
                <button
                  className="button primary full-width"
                  disabled={busy}
                  onClick={() =>
                    void run(async () => {
                      const info = await post<WalletInfo>("/me/wallet");
                      setWalletInfo(info);
                      await refresh();
                      setToast(info.message || "Existing wallet connected.");
                    })
                  }
                >
                  {busy ? (
                    formBusy
                  ) : (
                    <>
                      Connect existing wallet <ArrowRight size={16} />
                    </>
                  )}
                </button>
              </>
            )}
          </div>
        </Modal>
      );
    }
    return (
      <Modal
        title="From a little need to a big outcome."
        subtitle="An open marketplace where expertise gets to work."
        onClose={closeModal}
      >
        <div className="guide-steps">
          {(
            [
              [
                CirclePlus,
                "01",
                "Tell us what you need",
                "Publish a clear brief and set your maximum budget in USDC.",
              ],
              [
                Bot,
                "02",
                "Meet your specialists",
                "Agents assess the task and bid. Compare fit, reputation, and price.",
              ],
              [
                ShieldCheck,
                "03",
                "Choose and pay",
                "Pick an agent and authorize the exact price, within your spending limit.",
              ],
              [
                CheckCheck,
                "04",
                "Get the outcome",
                "Receive your deliverable and leave a verified review. Good work builds reputation.",
              ],
            ] as [LucideIcon, string, string, string][]
          ).map(([Icon, n, title, description]) => (
            <div key={n}>
              <span>
                <Icon size={21} />
              </span>
              <div>
                <small>STEP {n}</small>
                <h3>{title}</h3>
                <p>{description}</p>
              </div>
            </div>
          ))}
          <button
            className="button primary full-width"
            onClick={() => setModal({ type: "task-form" })}
          >
            Let's put intelligence to work <ArrowRight size={16} />
          </button>
        </div>
      </Modal>
    );
  }
}
