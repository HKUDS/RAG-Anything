import { useEffect, useState } from 'react'
import { getToken } from '../utils/api'
import { controlledMediaUrl, publicMediaUrl } from '../utils/controlledMedia'

export function useControlledMediaSource(media) {
  const protectedUrl = controlledMediaUrl(media)
  const directUrl = publicMediaUrl(media)
  const [source, setSource] = useState(directUrl)

  useEffect(() => {
    if (!protectedUrl) {
      setSource(directUrl)
      return undefined
    }
    const token = getToken()
    if (!token) {
      setSource('')
      return undefined
    }

    let active = true
    let objectUrl = ''
    setSource('')
    fetch(protectedUrl, { headers: { Authorization: `Bearer ${token}` } })
      .then(response => (response.ok ? response.blob() : null))
      .then(blob => {
        if (!active || !blob) return
        objectUrl = URL.createObjectURL(blob)
        setSource(objectUrl)
      })
      .catch(() => {
        if (active) setSource('')
      })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [protectedUrl, directUrl])

  return source
}

export function ControlledMediaImage({ media, alt = '', className = '', onError, ...props }) {
  const source = useControlledMediaSource(media)
  if (!source) return null
  return (
    <img
      src={source}
      alt={alt}
      className={className}
      loading="lazy"
      onError={onError}
      {...props}
    />
  )
}
