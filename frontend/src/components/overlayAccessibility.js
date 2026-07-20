import { useEffect, useRef } from 'react'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

let scrollLockCount = 0
let previousRootOverflow = ''
let previousBodyOverflow = ''

export function usePageScrollLock(isLocked, enabled = true) {
  useEffect(() => {
    if (!isLocked || !enabled) return undefined

    const root = document.documentElement
    const body = document.body
    if (scrollLockCount === 0) {
      previousRootOverflow = root.style.overflow
      previousBodyOverflow = body.style.overflow
      root.classList.add('user-dialog-scroll-locked')
      body.classList.add('user-dialog-scroll-locked')
      root.style.overflow = 'hidden'
      body.style.overflow = 'hidden'
    }
    scrollLockCount += 1

    return () => {
      scrollLockCount -= 1
      if (scrollLockCount === 0) {
        root.classList.remove('user-dialog-scroll-locked')
        body.classList.remove('user-dialog-scroll-locked')
        root.style.overflow = previousRootOverflow
        body.style.overflow = previousBodyOverflow
      }
    }
  }, [enabled, isLocked])
}

export function useDialogFocus({ isOpen, enabled = true, dialogRef, initialFocusRef, onRequestClose }) {
  const onRequestCloseRef = useRef(onRequestClose)

  useEffect(() => {
    onRequestCloseRef.current = onRequestClose
  }, [onRequestClose])

  useEffect(() => {
    if (!isOpen || !enabled) return undefined

    const returnFocusTo = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const frame = window.requestAnimationFrame(() => {
      const focusables = dialogRef.current?.querySelectorAll(FOCUSABLE_SELECTOR)
      const target = initialFocusRef?.current || focusables?.[0]
      target?.focus()
    })

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onRequestCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return

      const focusables = Array.from(dialogRef.current?.querySelectorAll(FOCUSABLE_SELECTOR) || [])
      if (focusables.length === 0) {
        event.preventDefault()
        return
      }

      const first = focusables[0]
      const last = focusables[focusables.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener('keydown', handleKeyDown)
      if (returnFocusTo?.isConnected) returnFocusTo.focus()
    }
  }, [dialogRef, enabled, initialFocusRef, isOpen])
}
