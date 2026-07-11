import { NextRequest, NextResponse } from "next/server";

import {
  CONSOLE_AUTH_COOKIE,
  consoleAuthCookieOptions,
  getConfiguredConsoleToken,
  isAllowedFrontendHost,
} from "@/lib/server/consoleAuth";

function requestHeadersWithConsoleCookie(request: NextRequest, token: string): Headers {
  const headers = new Headers(request.headers);
  const cookiePrefix = `${CONSOLE_AUTH_COOKIE}=`;
  const cookies = (headers.get("cookie") ?? "")
    .split(";")
    .map((cookie) => cookie.trim())
    .filter((cookie) => cookie.length > 0 && !cookie.startsWith(cookiePrefix));
  cookies.push(`${cookiePrefix}${token}`);
  headers.set("cookie", cookies.join("; "));
  return headers;
}

export function middleware(request: NextRequest): NextResponse {
  if (!isAllowedFrontendHost(request.headers.get("host"))) {
    return NextResponse.json(
      { detail: "host_not_allowed" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }

  const token = getConfiguredConsoleToken();
  if (token === null) {
    return NextResponse.json({ detail: "local_auth_unavailable" }, { status: 503 });
  }

  const response = NextResponse.next({
    request: { headers: requestHeadersWithConsoleCookie(request, token) },
  });
  if (request.cookies.get(CONSOLE_AUTH_COOKIE)?.value !== token) {
    response.cookies.set(
      CONSOLE_AUTH_COOKIE,
      token,
      consoleAuthCookieOptions(request.nextUrl.protocol === "https:"),
    );
  }
  response.headers.set("Cache-Control", "no-store");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
