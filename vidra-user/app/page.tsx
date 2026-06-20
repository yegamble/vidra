export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-24 text-center">
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Vidra</h1>
      <p className="max-w-md text-lg text-zinc-600 dark:text-zinc-400">
        A federated video platform. The frontend is being built up one slice at a time.
      </p>
    </main>
  );
}
