import { useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useDialogFocus, usePageScrollLock } from './overlayAccessibility'

export function UserDialog({
  isOpen,
  title,
  icon,
  onRequestClose,
  children,
  footer,
  dialogRef: suppliedDialogRef,
  initialFocusRef,
  closeDisabled = false,
  closeLabel = '关闭弹窗',
  size = 'md',
  layer = 'base',
  trapFocus = true,
  lockScroll = true,
  ariaHidden = false,
}) {
  const generatedDialogRef = useRef(null)
  const dialogRef = suppliedDialogRef || generatedDialogRef
  const titleId = useId()

  usePageScrollLock(isOpen, lockScroll)
  useDialogFocus({
    isOpen,
    enabled: trapFocus,
    dialogRef,
    initialFocusRef,
    onRequestClose,
  })

  if (!isOpen || typeof document === 'undefined') return null

  return createPortal(
    <div className={`user-dialog-layer user-dialog-layer--${layer}`} onMouseDown={(event) => {
      if (event.target === event.currentTarget && !closeDisabled) onRequestClose()
    }}>
      <section
        ref={dialogRef}
        className={`user-dialog-panel user-dialog-panel--${size}`}
        role="dialog"
        aria-modal={ariaHidden ? undefined : 'true'}
        aria-hidden={ariaHidden || undefined}
        aria-labelledby={titleId}
      >
        <header className="user-dialog-header">
          <div className="flex min-w-0 items-center gap-2.5">
            {icon && <span className="user-dialog-title-icon" aria-hidden="true">{icon}</span>}
            <h2 id={titleId} className="user-dialog-title">{title}</h2>
          </div>
          <button
            type="button"
            onClick={onRequestClose}
            className="user-dialog-close"
            aria-label={closeLabel}
            disabled={closeDisabled}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>
        <div className="user-dialog-body">{children}</div>
        {footer && <footer className="user-dialog-footer">{footer}</footer>}
      </section>
    </div>,
    document.body,
  )
}

export function UserDialogConfirmation({
  isOpen,
  title,
  description,
  icon,
  confirmLabel,
  onConfirm,
  cancelLabel,
  onCancel,
  danger = false,
  confirmDisabled = false,
  closeDisabled = false,
  lockScroll = false,
}) {
  const cancelButtonRef = useRef(null)

  return (
    <UserDialog
      isOpen={isOpen}
      title={title}
      icon={icon}
      onRequestClose={closeDisabled ? () => {} : onCancel}
      closeLabel={cancelLabel}
      size="sm"
      layer="confirmation"
      lockScroll={lockScroll}
      closeDisabled={closeDisabled}
      initialFocusRef={cancelButtonRef}
      footer={(
        <div className="flex gap-3">
          <button ref={cancelButtonRef} type="button" onClick={onCancel} className="btn-secondary flex-1 py-2.5 text-sm" disabled={closeDisabled}>
            {cancelLabel}
          </button>
          <button type="button" onClick={onConfirm} className={danger ? 'user-dialog-danger-action flex-1' : 'btn-primary flex-1 py-2.5 text-sm'} disabled={confirmDisabled}>
            {confirmLabel}
          </button>
        </div>
      )}
    >
      <p className="user-dialog-confirmation-copy">{description}</p>
    </UserDialog>
  )
}
