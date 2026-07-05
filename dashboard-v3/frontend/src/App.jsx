import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview.jsx";
import Sources from "./pages/Sources.jsx";
import Signals from "./pages/Signals.jsx";
import Reports from "./pages/Reports.jsx";
import Admin from "./pages/Admin.jsx";

const NAV = [
  { to: "/", label: "Overview", icon: "◈" },
  { to: "/sources", label: "Sources", icon: "≋" },
  { to: "/signals", label: "Signals & Trades", icon: "⇄" },
  { to: "/reports", label: "Reports", icon: "▤" },
  { to: "/admin", label: "Admin", icon: "⚙" },
];

export default function App() {
  return (
    <div className="min-h-screen md:flex">
      {/* sidebar (desktop) / top bar (mobile) */}
      <nav className="md:w-56 md:min-h-screen shrink-0 border-b md:border-b-0 md:border-r border-line bg-surface">
        <div className="px-5 py-4 md:py-6">
          <div className="text-[15px] font-semibold tracking-wide">
            Trading Bot
            <span className="ml-2 text-[10px] font-medium text-muted align-middle">v3</span>
          </div>
        </div>
        <div className="flex md:flex-col gap-1 px-3 pb-3 md:pb-6 overflow-x-auto">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] whitespace-nowrap transition-colors ${
                  isActive
                    ? "bg-accent-dim text-ink font-medium"
                    : "text-ink2 hover:text-ink hover:bg-surface2"
                }`
              }
            >
              <span className="text-[15px] opacity-70">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="flex-1 min-w-0 px-4 md:px-8 py-5 md:py-7 max-w-[1200px]">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </main>
    </div>
  );
}
