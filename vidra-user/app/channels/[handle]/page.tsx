import { ChannelView } from "@/components/ChannelView";

export default async function ChannelPage({ params }: { params: Promise<{ handle: string }> }) {
  const { handle } = await params;
  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
      <ChannelView key={handle} handle={handle} />
    </main>
  );
}
