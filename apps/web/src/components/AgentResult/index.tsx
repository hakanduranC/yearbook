import { Button, ButtonLink } from '~/components/Button'
import { ChipRow, chipClass } from '~/components/ChipRow'
import { EmptyState } from '~/components/EmptyState'
import { FaceChip } from '~/components/FaceChip'
import { MediaTile } from '~/components/MediaTile'
import { SimpleGrid } from '~/components/SimpleGrid'
import { useT } from '~/i18n'
import type { AgentTurn } from '~/lib/agent'
import type { Album, Chip } from '~/lib/api/types'
import styles from './AgentResult.module.css'
import { Attachments } from './Attachments'

interface Props {
  turn: AgentTurn
  /** Event scope, when the result belongs to one event. Lightbox links need it. */
  slug: string | null
  onChip: (chip: Chip) => void
  onSave?: () => void
  onShareAlbum?: (album: Album) => void
  saving?: boolean
}

export function AgentResultView({ turn, slug, onChip, onSave, onShareAlbum, saving }: Props) {
  const t = useT()
  const { result } = turn
  return (
    <section className={styles.result} data-result={result.kind}>
      {turn.fallback ? (
        <p className={styles.notice} role="status">
          {t('search.notConfigured')}
        </p>
      ) : null}
      {turn.understood ? <p className={styles.understood}>{turn.understood}</p> : null}

      {result.kind === 'media' ? (
        <>
          <h2 className={styles.title}>{result.title}</h2>
          {result.items.length ? (
            <SimpleGrid>
              {result.items.map((item, i) => (
                <MediaTile
                  key={item.id}
                  item={item}
                  priority={i < 6}
                  link={
                    slug
                      ? { to: '/e/$slug/photos/$photoId', params: { slug, photoId: item.id } }
                      : undefined
                  }
                />
              ))}
            </SimpleGrid>
          ) : result.pending.length ? (
            <SimpleGrid skeleton={Math.min(9, result.pending.length)}>{null}</SimpleGrid>
          ) : null}
        </>
      ) : null}

      {result.kind === 'people' ? (
        <>
          <h2 className={styles.title}>{result.title}</h2>
          <div className={styles.faces}>
            {result.persons.map((p) => (
              <FaceChip
                key={p.id}
                name={p.display_name}
                you={p.is_me}
                src={p.crop_url}
                count={p.media_count ?? p.face_count}
                link={
                  p.event_slug
                    ? {
                        to: '/e/$slug/people/$personId',
                        params: { slug: p.event_slug, personId: p.id },
                      }
                    : undefined
                }
              />
            ))}
          </div>
        </>
      ) : null}

      {result.kind === 'stat' ? (
        <>
          <h2 className={styles.title}>{result.title}</h2>
          <p className={styles.value}>{result.value}</p>
          {result.detail ? <p className={styles.detail}>{result.detail}</p> : null}
          {result.items.length ? (
            <SimpleGrid>
              {result.items.map((item) => (
                <MediaTile
                  key={item.id}
                  item={item}
                  link={
                    slug
                      ? { to: '/e/$slug/photos/$photoId', params: { slug, photoId: item.id } }
                      : undefined
                  }
                />
              ))}
            </SimpleGrid>
          ) : null}
        </>
      ) : null}

      {result.kind === 'album' ? (
        <div className={styles.album}>
          <span className="eyebrow">{t(`album.kind.${result.album.kind}`)}</span>
          <h2 className={styles.title}>{result.album.title}</h2>
          <p className={styles.detail}>{t('common.photos', { count: result.album.count })}</p>
          <div className={styles.albumActions}>
            <ButtonLink to="/albums/$albumId" params={{ albumId: result.album.id }} search={{}}>
              {t('search.openAlbum')}
            </ButtonLink>
            {onShareAlbum ? (
              <Button variant="secondary" onClick={() => onShareAlbum(result.album)}>
                {t('common.share')}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {result.kind === 'clarify' ? (
        <>
          <h2 className={styles.question}>{result.question}</h2>
          <ChipRow wrap>
            {result.options.map((option) => (
              <button
                key={option}
                type="button"
                className={chipClass()}
                onClick={() => onChip({ label: option, text: option })}
                data-option
              >
                {option}
              </button>
            ))}
          </ChipRow>
        </>
      ) : null}

      {result.kind === 'empty' ? (
        <EmptyState kind="search" title={result.title} body={turn.fallback ? '' : undefined} />
      ) : null}

      <Attachments list={turn.attachments} />

      {turn.suggestions.length ? (
        <ChipRow wrap>
          {turn.suggestions.map((chip) => (
            <button
              key={`${chip.command_id ?? ''}:${chip.text}`}
              type="button"
              className={chipClass({ quiet: true })}
              onClick={() => onChip(chip)}
              data-refine
            >
              {chip.label}
            </button>
          ))}
        </ChipRow>
      ) : null}

      {turn.saveable && onSave ? (
        <div className={styles.save}>
          <Button variant="secondary" small onClick={onSave} busy={saving} data-save-chip>
            {t('search.saveChip')}
          </Button>
        </div>
      ) : null}
    </section>
  )
}
