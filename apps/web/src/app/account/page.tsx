
import { Suspense } from "react";
import { connection } from "next/server";
import { auth, signIn, signOut } from "@/auth";

async function signInWithGoogle() {
  "use server";

  await signIn("google", {
    redirectTo: "/account",
  });
}

async function signOutUser() {
  "use server";

  await signOut({
    redirectTo: "/account",
  });
}

async function AccountControls() {
  // Authentication requires request-time rendering.
  // This prevents Next.js from prerendering random auth values.
  await connection();

  const session = await auth();

  if (!session?.user) {
    return (
      <div className="mt-8 space-y-6">
        <p className="text-gray-300">
          Sign in to use claim verification on the public service.
        </p>

        <form action={signInWithGoogle}>
          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-6 py-3 font-medium text-white transition hover:bg-blue-700"
          >
            Continue with Google
          </button>
        </form>
      </div>
    );
  }

  const user = session.user;

  return (
    <div className="mt-8 space-y-6">
      <div className="rounded-xl border border-gray-700 bg-gray-900 p-6">
        <div className="mb-4">
          <p className="text-sm text-gray-400">Authentication status</p>
          <p className="mt-1 font-medium text-green-400">
            Signed in successfully
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <p className="text-sm text-gray-400">Name</p>
            <p className="mt-1 text-white">
              {user.name || "Not available"}
            </p>
          </div>

          <div>
            <p className="text-sm text-gray-400">Email</p>
            <p className="mt-1 text-white">
              {user.email || "Not available"}
            </p>
          </div>
        </div>
      </div>

      <p className="text-sm text-gray-400">
        You are authenticated and can access features that require
        a signed-in account, subject to the platforms API permissions
        and usage limits.
      </p>

      <form action={signOutUser}>
        <button
          type="submit"
          className="rounded-lg border border-gray-600 px-6 py-3 font-medium text-white transition hover:bg-gray-800"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}

export default function AccountPage() {
  return (
    <main className="min-h-screen bg-[#080f1d] px-6 py-12 text-white">
      <div className="mx-auto w-full max-w-3xl">
        <h1 className="text-3xl font-semibold">
          Your account
        </h1>

        <Suspense
          fallback={
            <p className="mt-8 text-gray-400">
              Checking your session...
            </p>
          }
        >
          <AccountControls />
        </Suspense>
      </div>
    </main>
  );
}
