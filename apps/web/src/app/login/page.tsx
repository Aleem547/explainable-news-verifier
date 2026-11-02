import type { Metadata } from "next";
import { AuthPage } from "@/components/auth/auth-page";

export const metadata: Metadata = {
  title: "Log in",
  description: "Log in to your account with Google.",
};

export default function LoginPage() {
  return <AuthPage mode="login" />;
}
