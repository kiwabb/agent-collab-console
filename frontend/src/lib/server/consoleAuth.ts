export const CONSOLE_AUTH_COOKIE = "console_auth_token";

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,}$/;
const LOOPBACK_HOST_PATTERN = /^(?:localhost|127\.0\.0\.1|\[::1\])(?::([0-9]{1,5}))?$/i;

export function isAllowedFrontendHost(hostHeader: string | null): boolean {
  if (hostHeader === null || hostHeader.length === 0 || hostHeader !== hostHeader.trim()) {
    return false;
  }

  const match = LOOPBACK_HOST_PATTERN.exec(hostHeader);
  if (match === null) return false;

  const portText = match[1];
  if (portText === undefined) return true;

  const port = Number(portText);
  return Number.isInteger(port) && port >= 1 && port <= 65_535;
}

export function getConfiguredConsoleToken(): string | null {
  const token = process.env["CONSOLE_AUTH_TOKEN"]?.trim();
  return token && TOKEN_PATTERN.test(token) ? token : null;
}

export function consoleAuthCookieOptions(secure: boolean) {
  return {
    httpOnly: true,
    sameSite: "strict" as const,
    secure,
    path: "/",
  };
}
