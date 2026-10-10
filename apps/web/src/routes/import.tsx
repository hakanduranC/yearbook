import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { type ChangeEvent, useRef, useState } from 'react'
import { Button, ButtonLink } from '~/components/Button'
import { PageHeader } from '~/components/PageHeader'
import { useToast } from '~/components/Toast'
import { useLocale, useT } from '~/i18n'
import type { Import, ImportKind } from '~/lib/api/types'
import { formatBytes, formatTime } from '~/lib/format'
import { requireSession } from '~/lib/guards'
import { uploadArchive } from '~/lib/importUpload'
import {
  completeImport,
  createImport,
  importQuery,
  importRunning,
  importsQuery,
} from '~/lib/queries/imports'
import { keys } from '~/lib/queries/keys'
import styles from '~/styles/pages/import.module.css'

export const Route = createFileRoute('/import')({
  beforeLoad: async ({ context: { queryClient }, location }) => {
    await requireSession(queryClient, location.href)
  },
  loader: async ({ context: { queryClient } }) => {
    await queryClient.ensureQueryData(importsQuery()).catch(() => undefined)
  },
  component: ImportPage,
})

const KINDS: Array<{
  kind: ImportKind
  label: 'import.takeout' | 'import.zip'
  help: 'import.takeoutHelp' | 'import.zipHelp'
}> = [
  { kind: 'takeout', label: 'import.takeout', help: 'import.takeoutHelp' },
  { kind: 'zip', label: 'import.zip', help: 'import.zipHelp' },
]

function ImportPage() {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [kind, setKind] = useState<ImportKind>('takeout')
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const imports = useQuery(importsQuery())

  const onPick = (ev: ChangeEvent<HTMLInputElement>) => {
    setFile(ev.target.files?.[0] ?? null)
    ev.target.value = ''
  }

  const start = async () => {
    if (!file) return
    setProgress(0)
    try {
      const init = await createImport({ kind, filename: file.name, size: file.size })
      if (!init.upload) throw new Error('no upload target')
      const parts = await uploadArchive(file, init.upload, (loaded, total) =>
        setProgress(total ? Math.round((loaded / total) * 100) : 0),
      )
      const started = await completeImport(init.id, parts)
      queryClient.setQueryData(keys.import(started.id), started)
      queryClient.invalidateQueries({ queryKey: keys.imports() })
      setActiveId(started.id)
      setFile(null)
    } catch {
      toast(t('common.error'))
    } finally {
      setProgress(null)
    }
  }

  return (
    <>
      <PageHeader title={t('import.title')} back="/manage" />
      <main className={`page page--narrow ${styles.main}`} data-import>
        {activeId ? <ImportCard id={activeId} /> : null}

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('import.kind')}</h2>
          <div className={styles.kinds} role="radiogroup" aria-label={t('import.kind')}>
            {KINDS.map((k) => (
              // biome-ignore lint/a11y/useSemanticElements: a card-sized radio with two lines of help text
              <button
                key={k.kind}
                type="button"
                role="radio"
                aria-checked={kind === k.kind}
                className={styles.kind}
                onClick={() => setKind(k.kind)}
                data-kind={k.kind}
              >
                <span className={styles.kindLabel}>{t(k.label)}</span>
                <span className={styles.kindHelp}>{t(k.help)}</span>
              </button>
            ))}
          </div>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('import.file')}</h2>
          <input
            ref={inputRef}
            className={styles.input}
            type="file"
            accept=".zip,application/zip"
            onChange={onPick}
            data-testid="import-file"
            tabIndex={-1}
          />
          <div className={styles.fileRow}>
            <Button variant="secondary" onClick={() => inputRef.current?.click()} data-pick-file>
              {t('import.pick')}
            </Button>
            {file ? (
              <span className={styles.fileName} data-file-name>
                {file.name} · {formatBytes(file.size)}
              </span>
            ) : null}
          </div>
          <Button
            onClick={start}
            disabled={!file || progress !== null}
            busy={progress !== null}
            data-start-import
          >
            {progress !== null ? t('import.uploading', { percent: progress }) : t('import.start')}
          </Button>
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('import.past')}</h2>
          {imports.isSuccess && imports.data.length === 0 ? (
            <p className={styles.muted}>{t('import.none')}</p>
          ) : null}
          <ul className={styles.list}>
            {(imports.data ?? [])
              .filter((i) => i.id !== activeId)
              .map((i) => (
                <li key={i.id}>
                  <ImportSummary imp={i} />
                </li>
              ))}
          </ul>
          <ButtonLink to="/library" variant="secondary" data-go-library>
            {t('import.library')}
          </ButtonLink>
        </section>
      </main>
    </>
  )
}

/** Live card for one import: polls every 3 s while it is still moving. */
function ImportCard({ id }: { id: string }) {
  const t = useT()
  const queryClient = useQueryClient()
  const imp = useQuery({
    ...importQuery(id),
    refetchInterval: (query) =>
      query.state.data && importRunning(query.state.data.state) ? 3000 : false,
  })
  const data = imp.data
  if (!data) return null
  if (!importRunning(data.state)) queryClient.invalidateQueries({ queryKey: keys.imports() })
  return (
    <section
      className={styles.card}
      aria-live="polite"
      data-import-card={id}
      data-state={data.state}
    >
      <span className="eyebrow">
        {t(`import.${data.kind === 'folder' ? 'zip' : data.kind}`)} ·{' '}
        {t(`import.state.${data.state}`)}
      </span>
      {importRunning(data.state) ? <p className={styles.muted}>{t('import.running')}</p> : null}
      <Stats imp={data} />
    </section>
  )
}

function Stats({ imp }: { imp: Import }) {
  const t = useT()
  const s = imp.stats
  const cells: Array<[string, number | undefined]> = [
    [t('import.found'), s.found],
    [t('import.imported'), s.imported],
    [t('import.duplicates'), s.duplicates],
    [t('import.matched'), s.matched],
    [t('import.peopleSeeded'), s.people_seeded],
  ]
  return (
    <dl className={styles.stats}>
      {cells.map(([label, value]) => (
        <div key={label} className={styles.stat}>
          <dt>{label}</dt>
          <dd data-stat={label}>{value ?? 0}</dd>
        </div>
      ))}
    </dl>
  )
}

function ImportSummary({ imp }: { imp: Import }) {
  const t = useT()
  const locale = useLocale()
  return (
    <article className={styles.past} data-past-import={imp.id}>
      <div className={styles.pastHead}>
        <span className={styles.pastKind}>
          {t(`import.${imp.kind === 'folder' ? 'zip' : imp.kind}`)} ·{' '}
          {t(`import.state.${imp.state}`)}
        </span>
        <span className={styles.muted}>{formatTime(imp.created_at, locale)}</span>
      </div>
      <Stats imp={imp} />
      {imp.error ? <p className={styles.error}>{imp.error}</p> : null}
    </article>
  )
}
