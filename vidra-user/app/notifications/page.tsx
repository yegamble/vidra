import { NotificationsView } from "@/components/NotificationsView";

export default function NotificationsPage() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Notifications</h1>
      <NotificationsView />
    </main>
  );
}
