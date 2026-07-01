import { ResetPasswordConfirmForm } from "@/components/auth/ResetPasswordConfirmForm";

export default async function ResetPasswordConfirmPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return (
    <main className="mx-auto w-full max-w-sm flex-1 px-4 py-12">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Choose a new password</h1>
      <ResetPasswordConfirmForm token={(token ?? "").trim()} />
    </main>
  );
}
