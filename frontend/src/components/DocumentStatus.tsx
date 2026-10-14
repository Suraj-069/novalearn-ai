import { CheckCircle2, CircleAlert, Clock3, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import type { Job } from "@/types";

/** User-facing names for job states. "Indexed" = searchable and usable by the tutor. */
const STAGE: Record<string, string> = {
  inspecting: "Checking file", inspected: "Checking file", extracting: "Reading content", chunking: "Splitting into passages",
  embedding: "Creating search index", indexing: "Saving", topics: "Finding topics",
};

export function JobBadge({ job }: { job: Job | null }) {
  switch (job?.status) {
    case "processing":
      return <Badge tone="indigo" icon={<Loader2 className="h-3 w-3 animate-spin" />}>{STAGE[job.stage] ?? "Processing"}</Badge>;
    case "inspected":
      return <Badge tone="cyan" icon={<CheckCircle2 className="h-3 w-3" />}>Verified</Badge>;
    case "indexed":
      return <Badge tone="ok" icon={<CheckCircle2 className="h-3 w-3" />}>Indexed</Badge>;
    case "failed":
      return <Badge tone="bad" icon={<CircleAlert className="h-3 w-3" />}>Needs attention</Badge>;
    default:
      return <Badge tone="neutral" icon={<Clock3 className="h-3 w-3" />}>Waiting</Badge>;
  }
}
