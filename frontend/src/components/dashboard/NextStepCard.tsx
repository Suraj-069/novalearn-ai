import { ArrowUpRight, FolderPlus, Sparkles, Upload } from "lucide-react";
import { Link } from "react-router-dom";

import type { Course, Dashboard } from "@/types";

interface Step { title: string; text: string; to: string; cta: string; icon: typeof Upload }

/** Decide the single most useful next action from real account state. */
export function nextStep(d: Dashboard, courses: Course[]): Step {
  if (d.course_count === 0)
    return { title: "Create your first course", text: "A course holds the lectures, slides and textbooks for one subject.", to: "/courses", cta: "Create a course", icon: FolderPlus };
  if (d.document_count === 0) {
    const c = courses[0];
    return { title: "Add your course material", text: `Upload a PDF, slide deck or lecture video to ${c.title}.`, to: `/courses/${c.id}`, cta: "Upload material", icon: Upload };
  }
  const target = courses.find((c) => c.document_count > 0) ?? courses[0];
  if (d.indexed_document_count === 0)
    return { title: "Your files are being processed", text: "Once a file is indexed you can ask the tutor about it. If something failed, the course page explains why and lets you retry.", to: `/courses/${target.id}`, cta: "Check progress", icon: Sparkles };
  const ready = courses.find((c) => (c.status_counts.indexed ?? 0) > 0) ?? target;
  if (d.recent_assessments.length === 0)
    return { title: "Take your diagnostic", text: `Your material is indexed. A short diagnostic on ${ready.title} finds your starting point, so nothing is assumed about what you know.`, to: `/courses/${ready.id}/assessments?diagnostic=1`, cta: "Start the diagnostic", icon: Sparkles };
  if (d.weak_topics.length > 0)
    return { title: `Strengthen ${d.weak_topics[0].topic_name}`, text: `Your estimate there is ${Math.round(d.weak_topics[0].mastery * 100)}%. A short targeted quiz is the quickest way to improve it.`, to: `/courses/${d.weak_topics[0].course_id}/assessments`, cta: "Practice now", icon: Sparkles };
  return { title: "Ask your tutor", text: `${d.topic_count} topics found. Ask a question about ${ready.title} and open the exact page, slide or moment behind each answer.`, to: `/courses/${ready.id}/tutor`, cta: "Open the tutor", icon: Sparkles };
}

export function NextStepCard({ step }: { step: Step }) {
  const Icon = step.icon;
  return (
    <section className="relative overflow-hidden rounded-card bg-gradient-to-br from-nova-700 via-nova-600 to-violet p-6 text-white shadow-card sm:p-8">
      <div className="flex items-start gap-4">
        <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-white/15"><Icon className="h-5 w-5" aria-hidden /></div>
        <div>
          <p className="text-sm text-white/70">Next step</p>
          <h2 className="mt-1 text-xl font-semibold sm:text-2xl">{step.title}</h2>
          <p className="mt-2 max-w-xl text-white/80">{step.text}</p>
          <Link to={step.to} className="mt-5 inline-flex items-center gap-2 rounded-ctl bg-white px-4 py-2.5 text-sm font-semibold text-nova-700 hover:bg-nova-50">
            {step.cta}<ArrowUpRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
      </div>
      <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-cyan/25 blur-3xl" />
    </section>
  );
}
