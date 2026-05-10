"use client";

import { useState, useEffect, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

interface LazyImageProps {
  src: string;
  alt: string;
  className?: string;
  placeholderClassName?: string;
  fallback?: ReactNode;
  loadingComponent?: ReactNode;
}

export function LazyImage({
  src,
  alt,
  className,
  placeholderClassName,
  fallback,
  loadingComponent,
}: LazyImageProps) {
  const [isLoaded, setIsLoaded] = useState(false);
  const [isInView, setIsInView] = useState(false);
  const [error, setError] = useState(false);
  const imgRef = useState<HTMLImageElement | null>(null)[0];

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsInView(true);
          observer.disconnect();
        }
      },
      { rootMargin: "100px" }
    );

    // We'll observe when the component mounts
    const timer = setTimeout(() => {
      setIsInView(true);
    }, 100);

    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, []);

  const handleLoad = () => setIsLoaded(true);
  const handleError = () => setError(true);

  return (
    <div className={cn("relative overflow-hidden", className)}>
      {/* Loading state */}
      {!isLoaded && !error && (
        <div
          className={cn(
            "absolute inset-0 bg-surface-raised animate-pulse",
            placeholderClassName
          )}
        >
          {loadingComponent}
        </div>
      )}

      {/* Error state */}
      {error && fallback && (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-raised">
          {fallback}
        </div>
      )}

      {/* Actual image */}
      {isInView && !error && (
        <motion.img
          src={src}
          alt={alt}
          onLoad={handleLoad}
          onError={handleError}
          initial={{ opacity: 0 }}
          animate={{ opacity: isLoaded ? 1 : 0 }}
          transition={{ duration: 0.3 }}
          className={cn("w-full h-full object-cover", !isLoaded && "invisible")}
        />
      )}
    </div>
  );
}

interface LazyComponentProps {
  children: ReactNode;
  fallback?: ReactNode;
  className?: string;
  rootMargin?: string;
  triggerOnce?: boolean;
}

export function LazyComponent({
  children,
  fallback = null,
  className,
  rootMargin = "100px",
  triggerOnce = true,
}: LazyComponentProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [ref, setRef] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsVisible(true);
          if (triggerOnce) {
            observer.disconnect();
          }
        } else if (!triggerOnce) {
          setIsVisible(false);
        }
      },
      { rootMargin }
    );

    observer.observe(ref);

    return () => observer.disconnect();
  }, [ref, rootMargin, triggerOnce]);

  return (
    <div ref={setRef} className={className}>
      <AnimatePresence mode="wait">
        {isVisible ? (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          >
            {children}
          </motion.div>
        ) : (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            {fallback}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface LazySectionProps {
  children: ReactNode;
  className?: string;
  delay?: number;
}

export function LazySection({ children, className, delay = 0 }: LazySectionProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [ref, setRef] = useState<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTimeout(() => setIsVisible(true), delay);
          observer.disconnect();
        }
      },
      { rootMargin: "50px" }
    );

    observer.observe(ref);

    return () => observer.disconnect();
  }, [ref, delay]);

  return (
    <div ref={setRef} className={className}>
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={isVisible ? { opacity: 1, y: 0 } : { opacity: 0, y: 30 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      >
        {children}
      </motion.div>
    </div>
  );
}
