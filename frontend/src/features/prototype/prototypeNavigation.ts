import type { Prototype } from "@/lib/types";
import { safeJsonRecord } from "@/lib/utils";

export interface PrototypeRouteTarget {
  prototypeId: string;
  title: string;
  routePattern: string;
}

export function readPrototypeRoutePatterns(prototype: Prototype): string[] {
  if (!prototype.source_meta_json) return [];
  const metadata = safeJsonRecord(prototype.source_meta_json);
  const routePatterns = metadata?.["route_patterns"];
  if (!Array.isArray(routePatterns)) return [];
  return routePatterns.filter(
    (route): route is string => typeof route === "string" && route.startsWith("/"),
  );
}

export function buildPrototypeRouteTargets(prototypes: Prototype[]): PrototypeRouteTarget[] {
  return prototypes.flatMap((prototype) =>
    readPrototypeRoutePatterns(prototype).map((routePattern) => ({
      prototypeId: prototype.id,
      title: prototype.title,
      routePattern,
    })),
  );
}

function routeSegments(route: string): string[] {
  const pathname = route.split(/[?#]/, 1)[0] ?? "/";
  return pathname.split("/").filter(Boolean);
}

function routeMatchScore(route: string, pattern: string): number | null {
  const routeParts = routeSegments(route);
  const patternParts = routeSegments(pattern);
  let score = 0;

  for (let index = 0; index < patternParts.length; index += 1) {
    const patternPart = patternParts[index];
    const routePart = routeParts[index];
    if (patternPart === "*") return score;
    if (routePart === undefined || patternPart === undefined) return null;
    if (patternPart.startsWith(":")) {
      score += 1;
      continue;
    }
    if (patternPart !== routePart) return null;
    score += 10;
  }

  return routeParts.length === patternParts.length ? score : null;
}

export function matchPrototypeRoute(
  route: string,
  targets: PrototypeRouteTarget[],
): PrototypeRouteTarget | null {
  let best: { target: PrototypeRouteTarget; score: number } | null = null;
  for (const target of targets) {
    const score = routeMatchScore(route, target.routePattern);
    if (score === null || (best && best.score >= score)) continue;
    best = { target, score };
  }
  return best?.target ?? null;
}

const NAVIGATION_BRIDGE = String.raw`<script data-prototype-navigation-bridge>
(() => {
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    const origin = event.target;
    if (!(origin instanceof Element)) return;
    const target = origin.closest("a[href], [data-prototype-route]");
    if (!target) return;
    const route = target.getAttribute("data-prototype-route") || target.getAttribute("href");
    if (!route || !route.startsWith("/")) return;
    event.preventDefault();
    window.parent.postMessage({ type: "prototype:navigate", route }, "*");
  });
})();
</script>`;

export function injectPrototypeNavigationBridge(html: string): string {
  if (html.includes("data-prototype-navigation-bridge")) return html;
  const bodyClose = html.toLowerCase().lastIndexOf("</body>");
  if (bodyClose < 0) return `${html}${NAVIGATION_BRIDGE}`;
  return `${html.slice(0, bodyClose)}${NAVIGATION_BRIDGE}${html.slice(bodyClose)}`;
}
