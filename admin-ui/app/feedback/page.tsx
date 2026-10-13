import { redirect } from "next/navigation";

/** Feedback now lives in the Conversations table as a filterable column. */
export default function FeedbackRedirect() {
  redirect("/conversations?feedback=disliked");
}
