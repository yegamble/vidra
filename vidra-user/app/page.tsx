import { VideoFeed } from "@/components/VideoFeed";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Recent videos</h1>
      <VideoFeed />
    </main>
  );
}
