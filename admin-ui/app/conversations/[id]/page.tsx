import { redirect } from "next/navigation";

/** Old permalink: the thread now opens inside the conversations workspace. */
export default async function ConversationRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/conversations?id=${encodeURIComponent(id)}`);
}
