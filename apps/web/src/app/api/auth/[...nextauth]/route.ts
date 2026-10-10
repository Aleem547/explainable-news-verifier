import { handlers } from "@/auth";

// Cache Components is enabled in next.config.ts. Do not add `dynamic` or
// `runtime` route segment settings; both conflict with that configuration.
export const { GET, POST } = handlers;
