import { StudioView } from "@/components/StudioView";

export default function StudioPage() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Studio</h1>
      <StudioView />
    </main>
  );
}
