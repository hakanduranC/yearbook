import bodoniItalic from '@fontsource-variable/bodoni-moda/files/bodoni-moda-latin-wght-italic.woff2?url'
import bodoni from '@fontsource-variable/bodoni-moda/files/bodoni-moda-latin-wght-normal.woff2?url'
import instrument from '@fontsource-variable/instrument-sans/files/instrument-sans-latin-wght-normal.woff2?url'
import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  HeadContent,
  Outlet,
  Scripts,
  useRouterState,
} from '@tanstack/react-router'
import { type ReactNode, useEffect } from 'react'
import { ToastProvider } from '~/components/Toast'
import { type Locale, LocaleContext, resolveLocale } from '~/i18n'
import { readLangCookie } from '~/lib/env'
import { incomingHeader } from '~/lib/request-context'
import globalCss from '~/styles/global.css?url'

interface RouterContext {
  queryClient: QueryClient
}

function detectLocale(): Locale {
  if (import.meta.env.SSR) {
    return resolveLocale(incomingHeader('cookie'), incomingHeader('accept-language'))
  }
  return resolveLocale(
    `yb_lang=${readLangCookie() ?? ''}`,
    navigator.languages?.join(',') ?? navigator.language,
  )
}

export const Route = createRootRouteWithContext<RouterContext>()({
  loader: () => ({ locale: detectLocale() }),
  shouldReload: false,
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
      { name: 'theme-color', content: '#f8f7f4' },
      { name: 'color-scheme', content: 'light' },
      { title: 'Yearbook' },
    ],
    links: [
      {
        rel: 'preload',
        href: instrument,
        as: 'font',
        type: 'font/woff2',
        crossOrigin: 'anonymous',
      },
      { rel: 'preload', href: bodoni, as: 'font', type: 'font/woff2', crossOrigin: 'anonymous' },
      {
        rel: 'preload',
        href: bodoniItalic,
        as: 'font',
        type: 'font/woff2',
        crossOrigin: 'anonymous',
      },
      { rel: 'stylesheet', href: globalCss },
      { rel: 'manifest', href: '/manifest.webmanifest' },
      { rel: 'icon', href: '/favicon.svg', type: 'image/svg+xml' },
      { rel: 'apple-touch-icon', href: '/icons/icon-192.png' },
    ],
  }),
  shellComponent: RootDocument,
  component: RootComponent,
})

function useRootLocale(): Locale {
  return useRouterState({
    select: (s) => (s.matches[0]?.loaderData as { locale?: Locale } | undefined)?.locale ?? 'de',
  })
}

function RootDocument({ children }: { children: ReactNode }) {
  const locale = useRootLocale()
  return (
    <html lang={locale}>
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  )
}

function RootComponent() {
  const locale = useRootLocale()
  // Marker for tests and progressive enhancement: set once React has taken over.
  useEffect(() => {
    document.documentElement.dataset.hydrated = 'true'
  }, [])
  return (
    <LocaleContext.Provider value={locale}>
      <ToastProvider>
        <Outlet />
      </ToastProvider>
    </LocaleContext.Provider>
  )
}
