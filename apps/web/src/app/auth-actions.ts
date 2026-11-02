"use server";

import { signIn, signOut } from "@/auth";

export async function logInWithGoogle() {
  await signIn("google", { redirectTo: "/verify" });
}

export async function logOut() {
  await signOut({ redirectTo: "/" });
}
