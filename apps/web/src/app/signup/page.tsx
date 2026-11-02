import type { Metadata } from "next";
import { AuthPage } from "@/components/auth/auth-page";

export const metadata: Metadata = {
  title: "Sign up",
  description: "Get started using your Google account.",
};

export default function SignupPage() {
  return <AuthPage mode="signup" />;
}
