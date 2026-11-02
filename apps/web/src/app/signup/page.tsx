import type { Metadata } from "next";
import { AuthPage } from "@/components/auth/auth-page";

export const metadata: Metadata = {
  title: "Sign up | Explainable Verifier",
  description: "Get started with Explainable Verifier using your Google account.",
};

export default function SignupPage() {
  return <AuthPage mode="signup" />;
}
