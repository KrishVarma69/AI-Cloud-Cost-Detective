import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive ? "bg-white/10 text-white" : "text-gray-400 hover:text-white hover:bg-white/5"
  }`;

export default function Navbar() {
  const { email, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <header className="border-b border-white/10 bg-[#0d131a]">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <div className="flex items-center gap-6">
          <span className="flex items-center gap-2 font-semibold text-white">
            <span className="text-brand">◆</span> Cost Detective
            <span className="rounded bg-brand/20 px-1.5 py-0.5 text-[10px] font-bold text-brand">
              AWS
            </span>
          </span>
          <nav className="flex gap-1">
            <NavLink to="/" className={linkClass} end>
              Dashboard
            </NavLink>
            <NavLink to="/history" className={linkClass}>
              History
            </NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-gray-500 sm:inline">{email}</span>
          <button
            onClick={() => {
              logout();
              navigate("/login");
            }}
            className="rounded-md border border-white/10 px-3 py-1.5 text-xs text-gray-300 hover:bg-white/5"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
