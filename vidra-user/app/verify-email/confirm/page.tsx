import { VerifyEmailConfirmForm } from "@/components/auth/VerifyEmailConfirmForm";

export default async function VerifyEmailConfirmPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return (
    <main className="mx-auto w-full max-w-sm flex-1 px-4 py-12">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Verify your email</h1>
      <VerifyEmailConfirmForm token={(token ?? "").trim()} />
    </main>
  );
}
