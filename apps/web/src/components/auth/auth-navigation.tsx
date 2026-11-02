import Link from "next/link";
import { connection } from "next/server";
import { auth } from "@/auth";
import { logOut } from "@/app/auth-actions";

export function GuestNavigation() {
  return (
    <nav aria-label="Account navigation" className="flex shrink-0 items-center gap-2">
      <Link
        href="/login"
        className="rounded-lg px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-white/10"
      >
        Log in
      </Link>
      <Link
        href="/signup"
        className="rounded-lg bg-blue-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-400"
      >
        Sign up
      </Link>
    </nav>
  );
}

export async function AuthNavigation() {
  // The cached shell can show public links; session-specific controls stream
  // only for the incoming request, behind the header's Suspense boundary.
  await connection();
  const session = await auth();

  if (!session?.user?.id) return <GuestNavigation />;

  return (
    <nav aria-label="Account navigation" className="flex shrink-0 items-center gap-2">
      <Link
        href="/account"
        className="rounded-lg px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-white/10"
      >
        My account
      </Link>
      <form action={logOut}>
        <button
          type="submit"
          className="rounded-lg border border-white/15 px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-white/10"
        >
          Log out
        </button>
      </form>
    </nav>
  );
}
