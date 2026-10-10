import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    user: {
      /** Stable OAuth provider subject; derived in the JWT callback. */
      id: string;
    } & DefaultSession["user"];
  }
}
