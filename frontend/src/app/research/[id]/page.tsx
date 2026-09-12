import { RunView } from "@/components/RunView";

// A run at its own URL (plan §2.15). Everything on the page comes from the
// API keyed on this id, so reopening it costs a read and nothing else.
export default async function ResearchPage({ params }: PageProps<"/research/[id]">) {
  const { id } = await params;
  return <RunView researchId={id} />;
}
