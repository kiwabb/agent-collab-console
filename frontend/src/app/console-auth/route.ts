import { NextRequest, NextResponse } from "next/server";

import {
  CONSOLE_AUTH_COOKIE,
  consoleAuthCookieOptions,
  getConfiguredConsoleToken,
} from "@/lib/server/consoleAuth";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest): NextResponse {
  const token = getConfiguredConsoleToken();
  if (token === null) {
    return NextResponse.json(
      { detail: "local_auth_unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  const response = NextResponse.json(
    { ready: true },
    { headers: { "Cache-Control": "no-store, max-age=0" } },
  );
  response.cookies.set(
    CONSOLE_AUTH_COOKIE,
    token,
    consoleAuthCookieOptions(request.nextUrl.protocol === "https:"),
  );
  return response;
}
