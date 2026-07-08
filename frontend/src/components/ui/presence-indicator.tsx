"use client";

import { cn } from "@/lib/utils";

interface PresenceUser {
  id: string;
  name: string;
  avatar?: string;
  color: string;
}

interface PresenceIndicatorProps {
  users?: PresenceUser[];
  maxVisible?: number;
}

const PRESENCE_COLORS = [
  "bg-brand",
  "bg-warning",
  "bg-success",
  "bg-pink-500",
  "bg-purple-500",
  "bg-cyan-500",
];

function getInitials(name: string): string {
  return name
    .split(" ")
    .map((n) => n[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function PresenceIndicator({ users = [], maxVisible = 4 }: PresenceIndicatorProps) {
  const visibleUsers = users.slice(0, maxVisible);
  const overflow = users.length - maxVisible;

  if (users.length === 0) {
    return null;
  }

  return (
    <div className="flex items-center gap-2">
      <div className="flex -space-x-2">
        {visibleUsers.map((user, i) => (
          <div
            key={user.id}
            className={cn(
              "size-7 rounded-full border-2 border-background flex items-center justify-center text-[9px] font-black text-background shadow-md",
              user.color || PRESENCE_COLORS[i % PRESENCE_COLORS.length],
            )}
            title={user.name}
            style={{ zIndex: maxVisible - i }}
          >
            {user.avatar ? (
              // Arbitrary local/profile avatar URLs are not guaranteed to fit Next Image remote allowlists.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={user.avatar}
                alt={user.name}
                className="size-full rounded-full object-cover"
              />
            ) : (
              getInitials(user.name)
            )}
          </div>
        ))}
        {overflow > 0 && (
          <div
            className="size-7 rounded-full border-2 border-background bg-surface-raised flex items-center justify-center text-[9px] font-black text-text-muted shadow-md"
            style={{ zIndex: 0 }}
          >
            +{overflow}
          </div>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <div className="size-1.5 rounded-full bg-success animate-pulse" />
        <span className="text-[10px] font-bold text-text-secondary">{users.length} online</span>
      </div>
    </div>
  );
}

interface PresenceAvatarProps {
  user: PresenceUser;
  showStatus?: boolean;
  size?: "sm" | "md" | "lg";
}

export function PresenceAvatar({ user, showStatus = true, size = "md" }: PresenceAvatarProps) {
  const sizeClasses = {
    sm: "size-6 text-[8px]",
    md: "size-8 text-[10px]",
    lg: "size-10 text-[12px]",
  };

  return (
    <div className="relative inline-flex">
      <div
        className={cn(
          "rounded-full flex items-center justify-center font-black text-background shadow-sm",
          user.color || "bg-brand",
          sizeClasses[size],
        )}
        title={user.name}
      >
        {user.avatar ? (
          // Arbitrary local/profile avatar URLs are not guaranteed to fit Next Image remote allowlists.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={user.avatar} alt={user.name} className="size-full rounded-full object-cover" />
        ) : (
          getInitials(user.name)
        )}
      </div>
      {showStatus && (
        <div className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full bg-success border-2 border-background shadow-sm" />
      )}
    </div>
  );
}
