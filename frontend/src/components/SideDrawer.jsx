import { useRef } from 'react'
import { createPortal } from 'react-dom'
import { motion, useReducedMotion } from 'framer-motion'
import { useDialogFocus, usePageScrollLock } from './overlayAccessibility'

export default function SideDrawer({
  isOpen,
  onRequestClose,
  ariaLabel,
  initialFocusRef,
  size = 'sm',
  className = '',
  children,
}) {
  const panelRef = useRef(null)
  const prefersReducedMotion = useReducedMotion()
  const transition = { duration: prefersReducedMotion ? 0 : 0.22, ease: [0.16, 1, 0.3, 1] }

  usePageScrollLock(isOpen)
  useDialogFocus({
    isOpen,
    dialogRef: panelRef,
    initialFocusRef,
    onRequestClose,
  })

  if (!isOpen || typeof document === 'undefined') return null

  return createPortal(
    <motion.div
      className="side-drawer-layer"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={transition}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onRequestClose()
      }}
    >
      <motion.aside
        ref={panelRef}
        className={`side-drawer-panel side-drawer-panel--${size} ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        initial={{ opacity: 0, x: prefersReducedMotion ? 0 : 32 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: prefersReducedMotion ? 0 : 32 }}
        transition={transition}
      >
        {children}
      </motion.aside>
    </motion.div>,
    document.body,
  )
}
