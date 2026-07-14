const textEncoder = new TextEncoder();

function compareUnicodeCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const leftPoint = leftPoints[index]?.codePointAt(0);
    const rightPoint = rightPoints[index]?.codePointAt(0);
    if (leftPoint === undefined || rightPoint === undefined || leftPoint === rightPoint) {
      continue;
    }
    return leftPoint < rightPoint ? -1 : 1;
  }
  if (leftPoints.length === rightPoints.length) return 0;
  return leftPoints.length < rightPoints.length ? -1 : 1;
}

function assertWellFormedString(value: string): void {
  if (!value.isWellFormed()) {
    throw new TypeError("Canonical runtime strings must contain valid Unicode");
  }
}

function canonicalize(value: unknown): string {
  if (value === null) {
    return "null";
  }
  if (typeof value === "string" || typeof value === "boolean") {
    if (typeof value === "string") assertWellFormedString(value);
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || Object.is(value, -0)) {
      throw new TypeError("Canonical runtime numbers must be safe integers");
    }
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalize(item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value).sort(([left], [right]) =>
      compareUnicodeCodePoints(left, right),
    );
    return `{${entries
      .map(([key, child]) => {
        assertWellFormedString(key);
        if (child === undefined) {
          throw new TypeError(`Canonical runtime object field ${key} is undefined`);
        }
        return `${JSON.stringify(key)}:${canonicalize(child)}`;
      })
      .join(",")}}`;
  }
  throw new TypeError(`Unsupported canonical runtime value type: ${typeof value}`);
}

function digestBytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function canonicalRuntimeJson(value: unknown): string {
  return canonicalize(value);
}

export async function hashRuntimeValue(value: unknown): Promise<string> {
  const canonical = canonicalRuntimeJson(value);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", textEncoder.encode(canonical));
  return `sha256:${digestBytesToHex(digest)}`;
}

function uuidToBytes(uuid: string): Uint8Array {
  const hex = uuid.replaceAll("-", "");
  if (!/^[0-9a-f]{32}$/u.test(hex)) {
    throw new TypeError(`Invalid UUID namespace: ${uuid}`);
  }
  const bytes = new Uint8Array(16);
  for (let index = 0; index < bytes.length; index += 1) {
    const offset = index * 2;
    bytes[index] = Number.parseInt(hex.slice(offset, offset + 2), 16);
  }
  return bytes;
}

function bytesToUuid(bytes: Uint8Array): string {
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
    16,
    20,
  )}-${hex.slice(20)}`;
}

export async function deterministicUuidV5(namespace: string, name: string): Promise<string> {
  const namespaceBytes = uuidToBytes(namespace);
  const nameBytes = textEncoder.encode(name);
  const input = new Uint8Array(namespaceBytes.length + nameBytes.length);
  input.set(namespaceBytes);
  input.set(nameBytes, namespaceBytes.length);
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest("SHA-1", input));
  const uuidBytes = digest.slice(0, 16);
  uuidBytes[6] = ((uuidBytes[6] ?? 0) & 0x0f) | 0x50;
  uuidBytes[8] = ((uuidBytes[8] ?? 0) & 0x3f) | 0x80;
  return bytesToUuid(uuidBytes);
}
