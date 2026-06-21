import { SubscriptionsView } from "@/components/SubscriptionsView";

export default function SubscriptionsPage() {
  return (
    <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Subscriptions</h1>
      <SubscriptionsView />
    </main>
  );
}
