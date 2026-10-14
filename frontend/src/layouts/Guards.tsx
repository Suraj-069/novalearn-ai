import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Skeleton } from "@/components/ui/Feedback";
import { useAuth } from "@/hooks/useAuth";

function Splash() {
  return <div className="grid min-h-screen place-items-center"><Skeleton className="h-10 w-48" /></div>;
}

/** Signed-in users only. New users are sent through onboarding first. */
export function RequireAuth() {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (!user.onboarded && loc.pathname !== "/onboarding") return <Navigate to="/onboarding" replace />;
  return <Outlet />;
}

/** Login/sign-up pages: bounce away if already signed in. */
export function PublicOnly() {
  const { user, loading } = useAuth();
  if (loading) return <Splash />;
  if (user) return <Navigate to="/" replace />;
  return <Outlet />;
}
