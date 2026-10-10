export function isOnline(): boolean {
  return typeof navigator === 'undefined' ? true : navigator.onLine !== false
}

export function subscribeOnline(onChange: (online: boolean) => void): () => void {
  if (typeof window === 'undefined') return () => {}
  const on = () => onChange(true)
  const off = () => onChange(false)
  window.addEventListener('online', on)
  window.addEventListener('offline', off)
  return () => {
    window.removeEventListener('online', on)
    window.removeEventListener('offline', off)
  }
}
