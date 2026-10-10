import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { AgentResultView } from '~/components/AgentResult'
import { Button } from '~/components/Button'
import { ChipRow, chipClass } from '~/components/ChipRow'
import { Field } from '~/components/Field'
import { SearchInput } from '~/components/SearchInput'
import { ShareSheet } from '~/components/ShareSheet'
import { Sheet } from '~/components/Sheet'
import { SimpleGrid } from '~/components/SimpleGrid'
import { useToast } from '~/components/Toast'
import { useT } from '~/i18n'
import {
  type AgentTurn,
  isAgentNotConfigured,
  turnFromSearch,
  turnOf,
  withResolvedItems,
} from '~/lib/agent'
import type { Album, Chip } from '~/lib/api/types'
import {
  runSavedCommand,
  saveCommand,
  savedCommandsQuery,
  searchMedia,
  sendAgentMessage,
} from '~/lib/queries/agent'
import { keys } from '~/lib/queries/keys'
import { fetchMediaByIds } from '~/lib/queries/media'
import styles from './AgentPanel.module.css'

interface Props {
  /** Event scope, or null for everything the member can see. */
  slug: string | null
  eventTitle?: string
  /** A sentence to send right away, e.g. from the gallery's floating input. */
  initialQuery?: string
  /** A saved command to run right away. */
  initialCommand?: string
}

const PROMPTS = [
  'search.prompt.1',
  'search.prompt.2',
  'search.prompt.3',
  'search.prompt.4',
  'search.prompt.5',
  'search.prompt.6',
] as const

/** The conversation: input on top, turns below, suggestions when empty. Shared by the event and member search pages. */
export function AgentPanel({ slug, eventTitle, initialQuery, initialCommand }: Props) {
  const t = useT()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [input, setInput] = useState(initialQuery ?? '')
  const [turns, setTurns] = useState<AgentTurn[]>([])
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [saveFor, setSaveFor] = useState<AgentTurn | null>(null)
  const [label, setLabel] = useState('')
  const [saving, setSaving] = useState(false)
  const [shareAlbumFor, setShareAlbumFor] = useState<Album | null>(null)
  const commands = useQuery(savedCommandsQuery(slug))
  const endRef = useRef<HTMLDivElement>(null)
  const started = useRef(false)

  const push = (turn: AgentTurn) => {
    setTurns((prev) => [...prev, turn])
    if (turn.conversationId) setConversationId(turn.conversationId)
  }

  const submit = async (text: string) => {
    const q = text.trim()
    if (!q || busy) return
    setBusy(true)
    setInput('')
    try {
      const res = await sendAgentMessage({
        text: q,
        ...(slug ? { event_slug: slug } : {}),
        ...(conversationId ? { conversation_id: conversationId } : {}),
      })
      let turn = turnOf(res)
      if (turn.result.kind === 'media' && turn.result.pending.length) {
        turn = withResolvedItems(turn, await fetchMediaByIds(turn.result.pending))
      }
      push(turn)
    } catch (error) {
      if (isAgentNotConfigured(error)) {
        try {
          const page = await searchMedia(slug, q)
          push(turnFromSearch(q, page, t('search.empty.title')))
        } catch {
          toast(t('common.error'))
        }
      } else {
        toast(t('common.error'))
      }
    } finally {
      setBusy(false)
    }
  }

  const run = async (commandId: string) => {
    if (busy) return
    setBusy(true)
    try {
      let turn = turnOf(await runSavedCommand(commandId, slug))
      if (turn.result.kind === 'media' && turn.result.pending.length) {
        turn = withResolvedItems(turn, await fetchMediaByIds(turn.result.pending))
      }
      push(turn)
    } catch {
      toast(t('search.runFailed'))
    } finally {
      setBusy(false)
    }
  }

  const onChip = (chip: Chip) => {
    if (chip.command_id) run(chip.command_id)
    else submit(chip.text)
  }

  const save = async () => {
    if (!saveFor?.turnId) return
    setSaving(true)
    try {
      await saveCommand(saveFor.turnId, label.trim().slice(0, 30))
      queryClient.invalidateQueries({ queryKey: keys.savedCommands(slug) })
      queryClient.invalidateQueries({ queryKey: keys.savedCommands(null) })
      toast(t('search.chipSaved'))
      setSaveFor(null)
    } catch {
      toast(t('common.error'))
    } finally {
      setSaving(false)
    }
  }

  // Run what the URL asked for, once.
  // biome-ignore lint/correctness/useExhaustiveDependencies: deliberately only on mount
  useEffect(() => {
    if (started.current) return
    started.current = true
    if (initialCommand) run(initialCommand)
    else if (initialQuery) submit(initialQuery)
  }, [])

  // Keep the newest turn in view.
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when a turn arrives
  useEffect(() => {
    if (turns.length) endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [turns.length, busy])

  const reset = () => {
    setTurns([])
    setConversationId(null)
  }

  return (
    <div className={styles.panel} data-agent>
      <SearchInput
        inline
        autoFocus={!initialQuery && !initialCommand}
        value={input}
        onChange={setInput}
        onSubmit={submit}
        busy={busy}
      />
      {eventTitle ? (
        <p className={styles.scope}>{t('search.scopeEvent', { title: eventTitle })}</p>
      ) : (
        <p className={styles.scope}>{t('search.allEvents')}</p>
      )}

      {turns.length === 0 && !busy ? (
        <section className={styles.suggestions} data-prompts>
          <h2 className="eyebrow">{t('search.tryThese')}</h2>
          <ChipRow wrap>
            {PROMPTS.map((key) => (
              <button
                key={key}
                type="button"
                className={chipClass()}
                onClick={() => submit(t(key))}
                data-prompt
              >
                {t(key)}
              </button>
            ))}
          </ChipRow>
          {commands.data?.length ? (
            <>
              <h2 className="eyebrow">{t('search.savedTitle')}</h2>
              <ChipRow wrap>
                {commands.data.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={chipClass({ quiet: true })}
                    onClick={() => run(c.id)}
                    title={c.description}
                    data-command={c.id}
                  >
                    {c.label}
                  </button>
                ))}
              </ChipRow>
            </>
          ) : null}
        </section>
      ) : null}

      <ol className={styles.turns}>
        {turns.map((turn, i) => (
          <li key={`${turn.turnId ?? 'fallback'}-${i}`} className={styles.turn} data-turn={i}>
            <AgentResultView
              turn={turn}
              slug={slug}
              onChip={onChip}
              onSave={
                turn.turnId
                  ? () => {
                      setLabel(turn.understood.slice(0, 30))
                      setSaveFor(turn)
                    }
                  : undefined
              }
              onShareAlbum={(album) => setShareAlbumFor(album)}
            />
          </li>
        ))}
      </ol>
      {busy ? (
        <div className={styles.thinking} role="status" data-thinking>
          <p className={styles.thinkingLine}>{t('search.thinking')}</p>
          <SimpleGrid skeleton={6}>{null}</SimpleGrid>
        </div>
      ) : null}
      {turns.length > 0 && !busy ? (
        <div className={styles.footer}>
          <Button variant="quiet" small onClick={reset} data-new-question>
            {t('search.newQuestion')}
          </Button>
        </div>
      ) : null}
      <div ref={endRef} />

      <Sheet open={saveFor !== null} onClose={() => setSaveFor(null)} title={t('search.saveChip')}>
        <form
          className={styles.saveForm}
          onSubmit={(ev) => {
            ev.preventDefault()
            save()
          }}
        >
          <Field
            label={t('search.chipLabel')}
            value={label}
            maxLength={30}
            required
            onChange={(e) => setLabel(e.target.value)}
            data-chip-label
          />
          <Button type="submit" busy={saving} disabled={!label.trim()} data-save-confirm>
            {t('common.save')}
          </Button>
        </form>
      </Sheet>
      <ShareSheet
        open={shareAlbumFor !== null}
        albumId={shareAlbumFor?.id ?? null}
        title={t('album.shareTitle')}
        onClose={() => setShareAlbumFor(null)}
      />
    </div>
  )
}
