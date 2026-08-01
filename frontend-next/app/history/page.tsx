import { redirect } from "next/navigation";

/**
 * History merged into Conversations.
 *
 * Two tabs answered nearly the same question — "how did that session go" and
 * "what did we actually say" — and a learner had to guess which to open. The
 * route stays as a redirect rather than a 404 so existing links and bookmarks
 * still land somewhere useful.
 */
export default function HistoryRedirect() {
  redirect("/conversations");
}
