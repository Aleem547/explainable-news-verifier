/** Auth.js server configuration. OAuth tokens never leave the server. */
import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  session: { strategy: "jwt", maxAge: 7 * 24 * 60 * 60 },
  callbacks: {
    async jwt({ token, account }) {
      // Use the stable provider subject, never a mutable email or display name.
      if (account?.provider === "google" && account.providerAccountId) {
        token.verifiedSubject = `google:${account.providerAccountId}`;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && typeof token.verifiedSubject === "string") {
        session.user.id = token.verifiedSubject;
      }
      return session;
    },
  },
});
