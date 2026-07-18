"use client";

import { useLayoutEffect, useRef, type CSSProperties } from "react";

import {
  restoreStructuredPrototypeDragMirrorScrollState,
  type StructuredPrototypeDragMirrorSnapshot,
} from "./structuredPrototypeDragMirror";

interface Props {
  snapshot: StructuredPrototypeDragMirrorSnapshot;
}

export function StructuredPrototypeDragMirrorView({ snapshot }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    host.replaceChildren(snapshot.element);
    restoreStructuredPrototypeDragMirrorScrollState(snapshot.scrollStates);
    return () => {
      if (snapshot.element.parentElement === host) host.replaceChildren();
    };
  }, [snapshot]);

  const outerStyle: CSSProperties & Record<`--prototype-${string}`, string> = {
    ...snapshot.customProperties,
    width: snapshot.geometry.clientWidth,
    height: snapshot.geometry.clientHeight,
    fontFamily: snapshot.fontFamily,
    colorScheme: snapshot.colorScheme,
  };

  return (
    <div
      className="pointer-events-none relative overflow-visible"
      style={outerStyle}
      data-prototype-drag-overlay="node"
      data-prototype-drag-mirror="true"
      data-prototype-drag-mirror-width={snapshot.geometry.clientWidth}
      data-prototype-drag-mirror-height={snapshot.geometry.clientHeight}
      aria-hidden
      inert
    >
      <div
        ref={hostRef}
        className="pointer-events-none absolute left-0 top-0 origin-top-left"
        style={{
          width: snapshot.geometry.contentWidth,
          height: snapshot.geometry.contentHeight,
          transform: `scale(${snapshot.geometry.scaleX}, ${snapshot.geometry.scaleY})`,
        }}
      />
    </div>
  );
}
