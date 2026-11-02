import type { Metadata } from "next";
import { AuthPage } from "@/components/auth/auth-page";

export const metadata: Metadata = {
  title: "Log in | Explainable Verifier",
  description: "Log in to your Explainable Verifier account with Google.",
};

export default function LoginPage() {
  return <AuthPage mode="login" />;
}
