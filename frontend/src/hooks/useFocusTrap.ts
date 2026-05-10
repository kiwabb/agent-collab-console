"use client"

import { useEffect, useRef, useCallback } from "react"

const FOCUSABLE_ELEMENT_SELECTORS = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
  "[contenteditable]",
].join(", ")

interface UseFocusTrapOptions {
  enabled?: boolean
  autoFocus?: boolean
}

export function useFocusTrap<T extends HTMLElement>(
  options: UseFocusTrapOptions = {}
) {
  const { enabled = true, autoFocus = true } = options
  const ref = useRef<T>(null)
  const previousActiveElement = useRef<HTMLElement | null>(null)

  const getFocusableElements = useCallback(() => {
    if (!ref.current) return []
    return Array.from(
      ref.current.querySelectorAll<HTMLElement>(FOCUSABLE_ELEMENT_SELECTORS)
    ).filter((el) => el.offsetParent !== null)
  }, [])

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (!enabled) return
      if (event.key !== "Tab") return

      const focusableElements = getFocusableElements()
      if (focusableElements.length === 0) return

      const firstElement = focusableElements[0]
      const lastElement = focusableElements[focusableElements.length - 1]

      if (event.shiftKey) {
        if (document.activeElement === firstElement) {
          event.preventDefault()
          lastElement.focus()
        }
      } else {
        if (document.activeElement === lastElement) {
          event.preventDefault()
          firstElement.focus()
        }
      }
    },
    [enabled, getFocusableElements]
  )

  useEffect(() => {
    if (!enabled) return

    previousActiveElement.current = document.activeElement as HTMLElement

    if (autoFocus && ref.current) {
      const focusableElements = getFocusableElements()
      if (focusableElements.length > 0) {
        focusableElements[0].focus()
      } else {
        ref.current.focus()
      }
    }

    document.addEventListener("keydown", handleKeyDown)

    return () => {
      document.removeEventListener("keydown", handleKeyDown)
      if (previousActiveElement.current) {
        previousActiveElement.current.focus()
      }
    }
  }, [enabled, autoFocus, handleKeyDown, getFocusableElements])

  return ref
}