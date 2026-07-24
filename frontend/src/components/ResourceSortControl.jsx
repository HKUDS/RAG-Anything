import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  ArrowDownNarrowWide,
  ArrowUpNarrowWide,
  Check,
  ChevronDown,
  ListFilter,
} from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'

export default function ResourceSortControl({
  sortOptions,
  sortField,
  sortDirection,
  onSortFieldChange,
  onSortDirectionChange,
  menuId,
  ariaLabel,
}) {
  const [showSortMenu, setShowSortMenu] = useState(false)
  const [sortMenuImmediateExit, setSortMenuImmediateExit] = useState(false)
  const [sortMenuOpenMode, setSortMenuOpenMode] = useState(null)
  const [sortMenuPosition, setSortMenuPosition] = useState(null)
  const [sortMenuFocusIndex, setSortMenuFocusIndex] = useState(0)
  const sortControlRef = useRef(null)
  const sortTriggerRef = useRef(null)
  const sortMenuRef = useRef(null)
  const sortMenuItemRefs = useRef({})
  const sortMenuOpenModeRef = useRef(null)
  const prefersReducedMotion = useReducedMotion()

  const activeSortOption = sortOptions.find(option => option.value === sortField) || sortOptions[0]
  const ActiveSortIcon = activeSortOption.Icon
  const isTimeSort = activeSortOption.type === 'time'
  const directionDescription = isTimeSort
    ? (sortDirection === 'asc' ? '最早优先' : '最新优先')
    : (sortDirection === 'asc' ? '从少到多' : '从多到少')
  const directionLabel = sortDirection === 'asc' ? '当前为升序，切换为降序' : '当前为降序，切换为升序'

  const closeSortMenu = useCallback((restoreTriggerFocus = false, immediateExit = false) => {
    sortMenuOpenModeRef.current = null
    setSortMenuImmediateExit(immediateExit)
    setShowSortMenu(false)
    setSortMenuOpenMode(null)
    setSortMenuPosition(null)
    if (restoreTriggerFocus) {
      window.requestAnimationFrame(() => sortTriggerRef.current?.focus())
    }
  }, [])

  const closeHoverSortMenu = useCallback((event) => {
    if (sortMenuOpenModeRef.current !== 'hover') return
    const nextTarget = event?.relatedTarget
    const isWithinHoverSurface = typeof Node !== 'undefined' && nextTarget instanceof Node && (
      sortControlRef.current?.contains(nextTarget) || sortMenuRef.current?.contains(nextTarget)
    )
    if (isWithinHoverSurface) return
    closeSortMenu(false, true)
  }, [closeSortMenu])

  const openSortMenu = useCallback((mode = 'hover') => {
    if (mode === 'hover' && sortMenuOpenModeRef.current && sortMenuOpenModeRef.current !== 'hover') return
    sortMenuOpenModeRef.current = mode
    setSortMenuImmediateExit(false)
    const selectedIndex = Math.max(0, sortOptions.findIndex(option => option.value === sortField))
    setSortMenuFocusIndex(selectedIndex)
    setShowSortMenu(true)
    setSortMenuOpenMode(mode)
  }, [sortField, sortOptions])

  const handleSortTriggerClick = useCallback(() => {
    if (sortMenuOpenModeRef.current === 'pinned') {
      closeSortMenu()
      return
    }
    openSortMenu('pinned')
  }, [closeSortMenu, openSortMenu])

  const handleSortTriggerKeyDown = useCallback((event) => {
    if (!['ArrowDown', 'Enter', ' '].includes(event.key)) return
    event.preventDefault()
    if (sortMenuOpenModeRef.current === 'keyboard') {
      closeSortMenu()
      return
    }
    openSortMenu('keyboard')
  }, [closeSortMenu, openSortMenu])

  const focusSortMenuOption = useCallback((index) => {
    const normalizedIndex = (index + sortOptions.length) % sortOptions.length
    setSortMenuFocusIndex(normalizedIndex)
    window.requestAnimationFrame(() => sortMenuItemRefs.current[normalizedIndex]?.focus())
  }, [sortOptions.length])

  useLayoutEffect(() => {
    if (!showSortMenu || !sortControlRef.current || !sortMenuRef.current) return undefined

    const updateSortMenuPosition = () => {
      const controlRect = sortControlRef.current.getBoundingClientRect()
      const menuWidth = sortMenuRef.current.offsetWidth
      const menuHeight = sortMenuRef.current.offsetHeight
      const viewportMargin = 12
      const left = Math.max(
        viewportMargin,
        Math.min(controlRect.right - menuWidth, window.innerWidth - menuWidth - viewportMargin)
      )
      const belowTop = controlRect.bottom + 8
      const top = belowTop + menuHeight <= window.innerHeight - viewportMargin
        ? belowTop
        : Math.max(viewportMargin, controlRect.top - menuHeight - 8)

      setSortMenuPosition({ top, left })
    }

    updateSortMenuPosition()
    window.addEventListener('resize', updateSortMenuPosition)
    window.addEventListener('scroll', updateSortMenuPosition, true)
    if (sortMenuOpenMode === 'keyboard') {
      window.requestAnimationFrame(() => sortMenuItemRefs.current[sortMenuFocusIndex]?.focus())
    }

    return () => {
      window.removeEventListener('resize', updateSortMenuPosition)
      window.removeEventListener('scroll', updateSortMenuPosition, true)
    }
  }, [showSortMenu, sortMenuFocusIndex, sortMenuOpenMode])

  useEffect(() => {
    if (!showSortMenu) return undefined

    const isInsideSortControl = (target) => (
      sortControlRef.current?.contains(target) || sortMenuRef.current?.contains(target)
    )
    const closeOnOutsidePointer = (event) => {
      if (!isInsideSortControl(event.target)) closeSortMenu()
    }
    const closeOnFocusAway = (event) => {
      if (!isInsideSortControl(event.target)) closeSortMenu()
    }
    const closeOnEscape = (event) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      closeSortMenu(true)
    }

    document.addEventListener('pointerdown', closeOnOutsidePointer)
    document.addEventListener('focusin', closeOnFocusAway)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsidePointer)
      document.removeEventListener('focusin', closeOnFocusAway)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [closeSortMenu, showSortMenu])

  const selectSortField = (field) => {
    onSortFieldChange(field)
    closeSortMenu(true)
  }

  const handleSortMenuKeyDown = (event, index) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusSortMenuOption(index + 1)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      focusSortMenuOption(index - 1)
    } else if (event.key === 'Home') {
      event.preventDefault()
      focusSortMenuOption(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      focusSortMenuOption(sortOptions.length - 1)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      closeSortMenu(true)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      selectSortField(sortOptions[index].value)
    }
  }

  const sortMenu = typeof document === 'undefined' ? null : createPortal(
    <AnimatePresence>
      {showSortMenu && (
        <motion.div
          ref={sortMenuRef}
          id={menuId}
          className="resource-sort-menu"
          initial={prefersReducedMotion ? false : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={sortMenuImmediateExit || prefersReducedMotion ? undefined : { opacity: 0 }}
          transition={{ duration: sortMenuImmediateExit || prefersReducedMotion ? 0 : 0.16, ease: 'easeOut' }}
          style={{
            top: sortMenuPosition?.top ?? 0,
            left: sortMenuPosition?.left ?? 0,
            visibility: sortMenuPosition ? 'visible' : 'hidden',
          }}
          onMouseLeave={closeHoverSortMenu}
          role="menu"
          aria-label={`选择${ariaLabel}依据`}
        >
          {sortOptions.map(({ value, label, Icon }, index) => {
            const isSelected = sortField === value
            return (
              <button
                key={value}
                ref={element => { sortMenuItemRefs.current[index] = element }}
                type="button"
                role="menuitemradio"
                className={`resource-sort-option${isSelected ? ' is-selected' : ''}`}
                onClick={() => selectSortField(value)}
                onKeyDown={event => handleSortMenuKeyDown(event, index)}
                onFocus={() => setSortMenuFocusIndex(index)}
                aria-checked={isSelected}
                tabIndex={index === sortMenuFocusIndex ? 0 : -1}
              >
                <Icon size={16} aria-hidden="true" />
                <span>{label}</span>
                {isSelected && <Check size={16} className="resource-sort-option-check" aria-hidden="true" />}
              </button>
            )
          })}
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  )

  return (
    <>
      <div
        ref={sortControlRef}
        className="resource-sort-controls"
        role="group"
        aria-label={ariaLabel}
        onMouseLeave={closeHoverSortMenu}
      >
        <button
          ref={sortTriggerRef}
          type="button"
          className="resource-sort-trigger"
          onClick={handleSortTriggerClick}
          onKeyDown={handleSortTriggerKeyDown}
          onMouseEnter={() => openSortMenu('hover')}
          aria-expanded={showSortMenu}
          aria-controls={menuId}
          aria-haspopup="menu"
          aria-label={`排序依据：${activeSortOption.label}。当前排序方式：${directionDescription}`}
        >
          <ListFilter size={16} aria-hidden="true" />
          <span className="resource-sort-prefix">排序</span>
          <span className="resource-sort-value">
            <ActiveSortIcon size={15} aria-hidden="true" />
            {activeSortOption.label}
          </span>
          <ChevronDown size={16} className={`resource-sort-chevron${showSortMenu ? ' is-open' : ''}`} aria-hidden="true" />
        </button>
        <span className="resource-sort-divider" aria-hidden="true" />
        <button
          type="button"
          className="resource-sort-direction"
          onMouseEnter={closeHoverSortMenu}
          onClick={() => {
            onSortDirectionChange(sortDirection === 'asc' ? 'desc' : 'asc')
            closeSortMenu()
          }}
          title={directionLabel}
          aria-label={directionLabel}
          aria-pressed={sortDirection === 'asc'}
        >
          {sortDirection === 'asc'
            ? <ArrowUpNarrowWide size={17} aria-hidden="true" />
            : <ArrowDownNarrowWide size={17} aria-hidden="true" />}
        </button>
      </div>
      {sortMenu}
    </>
  )
}
