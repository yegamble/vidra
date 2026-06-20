import { WatchView } from "@/components/WatchView";

// The watch page is the destination feed cards link to. The video itself loads
// client-side in WatchView (route-mockable, refetchable); this server component
// just resolves the dynamic id.
export default async function WatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
      <WatchView id={id} />
    </main>
  );
}
