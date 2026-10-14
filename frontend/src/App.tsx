import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/layouts/AppShell";
import { PublicOnly, RequireAuth } from "@/layouts/Guards";
import AuthPage from "@/pages/AuthPage";
import Analytics from "@/pages/Analytics";
import Assessments from "@/pages/Assessments";
import CourseDetail from "@/pages/CourseDetail";
import Courses from "@/pages/Courses";
import Dashboard from "@/pages/Dashboard";
import Evaluation from "@/pages/Evaluation";
import NotFound from "@/pages/NotFound";
import Onboarding from "@/pages/Onboarding";
import Results from "@/pages/Results";
import RevisionCards from "@/pages/RevisionCards";
import Knowledge from "@/pages/Knowledge";
import SettingsPage from "@/pages/Settings";
import TakeAssessment from "@/pages/TakeAssessment";
import Tutor from "@/pages/Tutor";

export default function App() {
  return (
    <Routes>
      <Route element={<PublicOnly />}>
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/signup" element={<AuthPage mode="signup" />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route element={<AppShell />}>
          <Route index element={<Dashboard />} />
          <Route path="courses" element={<Courses />} />
          <Route path="courses/:id" element={<CourseDetail />} />
          <Route path="courses/:id/knowledge" element={<Knowledge />} />
          <Route path="courses/:id/tutor" element={<Tutor />} />
          <Route path="courses/:id/assessments" element={<Assessments />} />
          <Route path="courses/:id/analytics" element={<Analytics />} />
          <Route path="courses/:id/evaluation" element={<Evaluation />} />
          <Route path="revision-cards" element={<RevisionCards />} />
          <Route path="assessments/:aid/take" element={<TakeAssessment />} />
          <Route path="attempts/:tid" element={<Results />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
