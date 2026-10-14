import { BookOpen, BookOpenCheck, LayoutDashboard, LogOut, Settings } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { BRAND, LogoMark } from "@/components/Logo";
import { useAuth } from "@/hooks/useAuth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/courses", label: "Courses", icon: BookOpen, end: false },
  { to: "/revision-cards", label: "Revise", icon: BookOpenCheck, end: false },
  { to: "/settings", label: "Settings", icon: Settings, end: false },
];

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const signOut = () => { logout(); navigate("/login"); };

  return (
    <div className="min-h-screen lg:pl-64">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-gradient-to-b from-nova-900 to-nova-950 p-4 text-white lg:flex">
        <div className="flex items-center gap-3 px-2 py-3">
          <LogoMark />
          <div className="leading-tight">
            <div className="text-[15px] font-semibold">{BRAND.name}</div>
            <div className="text-xs text-white/55">{BRAND.tagline}</div>
          </div>
        </div>
        <nav className="mt-8 flex flex-col gap-1" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => `relative flex items-center gap-3 rounded-ctl px-3 py-2.5 text-sm font-medium transition-colors
                ${isActive ? "bg-white/15 text-white before:absolute before:-left-4 before:top-2 before:bottom-2 before:w-1 before:rounded-r before:bg-violet" : "text-white/70 hover:bg-white/10 hover:text-white"}`}>
              <Icon className="h-[18px] w-[18px]" aria-hidden />{label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto rounded-ctl bg-white/10 p-3">
          <div className="truncate text-sm font-medium">{user?.name}</div>
          <div className="truncate text-xs text-white/55">{user?.email}</div>
          <button onClick={signOut} className="mt-3 flex items-center gap-2 text-[13px] text-white/70 hover:text-white">
            <LogOut className="h-4 w-4" aria-hidden />Sign out
          </button>
        </div>
      </aside>

      {/* Mobile / tablet top bar */}
      <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-line bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
        <LogoMark className="h-8 w-8" />
        <span className="font-semibold">{BRAND.name}</span>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-28 pt-6 sm:px-6 lg:px-10 lg:pb-12 lg:pt-10"><Outlet /></main>

      {/* Mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-line bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end}
            className={({ isActive }) => `flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium ${isActive ? "text-nova-600" : "text-ink-muted"}`}>
            <Icon className="h-5 w-5" aria-hidden />{label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
