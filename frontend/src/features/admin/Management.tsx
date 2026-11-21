import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { z } from 'zod'
import { ClipboardList, MessageSquare, UsersRound } from 'lucide-react'
import { Badge, Button, Card, EmptyState, ErrorState, Input, LoadingSkeleton } from '../../components/ui/Primitives'
import { ConfirmDialog, Modal } from '../../components/ui/Modal'
import { locale, number } from '../../i18n'
import { action, adminMessage, feedbackStatus, pageSize, readAdminUser, role,
  useAdminWrite, useAudit, useFeedback, useSettings, useUsers } from './data'
import type { AdminRole, AdminUser, RuntimeSettings } from './data'

const roles = { user: 'Пользователь', admin: 'Администратор', super_admin: 'Суперадминистратор' }
const feedbackLabels = { new: 'Новое', reviewing: 'На рассмотрении', closed: 'Закрыто' }
const actions = {
  role_changed: 'Изменение роли', account_suspended: 'Блокировка', account_reactivated: 'Восстановление доступа',
  feedback_status_changed: 'Изменение статуса обращения', settings_updated: 'Изменение настроек',
  super_admin_bootstrapped: 'Назначение первого суперадминистратора',
}
const timestamp = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })
const stamp = (value: string) => timestamp.format(new Date(value)) + ' UTC'

function Pagination({ offset, more, onChange }: { offset: number; more: boolean; onChange: (offset: number) => void }) {
  return <nav className="admin-filters" aria-label="Страницы результатов">
    <Button variant="secondary" disabled={!offset} onClick={() => onChange(offset - pageSize)}>Назад</Button>
    <span>Страница {number.format(offset / pageSize + 1)}</span>
    <Button variant="secondary" disabled={!more || offset + pageSize > 100000}
      onClick={() => onChange(offset + pageSize)}>Далее</Button>
  </nav>
}

function ResultError({ error, retry }: { error: unknown; retry: () => void }) {
  return <ErrorState description={adminMessage(error)} onRetry={retry} />
}

function UserActions({ user, owner, access }: { user: AdminUser; owner: string; access: AdminRole }) {
  const write = useAdminWrite(owner)
  const [confirmation, setConfirmation] = useState<'role' | 'status'>()
  const [nextRole, setNextRole] = useState(user.role)
  const operation = user.suspended_at ? 'Восстановить доступ' : 'Заблокировать аккаунт'
  if (user.id === owner || (access === 'admin' && user.role !== 'user')) return null
  return <>
    {access === 'super_admin' && <form className="admin-filters" onSubmit={(event) => {
      event.preventDefault()
      write.reset()
      setConfirmation('role')
    }}>
      <label>Новая роль<select value={nextRole} onChange={(event) => setNextRole(role.parse(event.target.value))}>
        {role.options.map((item) => <option key={item} value={item}>{roles[item]}</option>)}
      </select></label>
      <Button disabled={nextRole === user.role || write.isPending} type="submit">Изменить роль</Button>
    </form>}
    <Button variant={user.suspended_at ? 'secondary' : 'danger'} disabled={write.isPending}
      onClick={() => { write.reset(); setConfirmation('status') }}>
      {operation}
    </Button>
    <ConfirmDialog open={Boolean(confirmation)} onClose={() => { if (!write.isPending) setConfirmation(undefined) }}
      title={confirmation === 'role' ? 'Подтвердить изменение роли?' : operation + '?'}
      description={write.isError ? adminMessage(write.error) : confirmation === 'role' ? user.email + ' получит роль «' + roles[nextRole] + '».'
        : user.suspended_at ? 'Для входа в аккаунт потребуется новый сеанс.'
          : 'Доступ будет закрыт, а действующие сеансы пользователя завершатся.'}
      confirmLabel="Подтвердить" danger={confirmation === 'status' && !user.suspended_at} busy={write.isPending}
      onConfirm={() => {
        if (!confirmation) return
        write.mutate(confirmation === 'role' ? { kind: 'role', id: user.id, value: nextRole }
          : { kind: 'status', id: user.id, value: user.suspended_at ? 'active' : 'suspended' },
        { onSuccess: () => setConfirmation(undefined) })
      }} />
  </>
}

export function Users({ owner, access }: { owner: string; access: AdminRole }) {
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [filterRole, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, select] = useState<string>()
  const users = useUsers(owner, offset, query, filterRole, status)
  const detail = useQuery({
    queryKey: ['admin', owner, 'user', selected], enabled: Boolean(selected), retry: false,
    queryFn: ({ signal }) => readAdminUser(selected!, signal),
  })
  return <>
    <form className="admin-filters" onSubmit={(event) => { event.preventDefault(); setOffset(0); setQuery(search.trim()) }}>
      <label>Электронная почта<Input type="search" maxLength={254} value={search}
        onChange={(event) => setSearch(event.target.value)} placeholder="Поиск по адресу" /></label>
      <label>Роль<select value={filterRole} onChange={(event) => { setOffset(0); setRole(event.target.value) }}>
        <option value="">Все роли</option>{role.options.map((item) => <option key={item} value={item}>{roles[item]}</option>)}
      </select></label>
      <label>Статус<select value={status} onChange={(event) => { setOffset(0); setStatus(event.target.value) }}>
        <option value="">Все статусы</option><option value="active">Активен</option><option value="suspended">Заблокирован</option>
      </select></label><Button type="submit">Найти</Button>
    </form>
    {users.isPending ? <LoadingSkeleton label="Загружаем пользователей" />
      : users.isError ? <ResultError error={users.error} retry={() => { void users.refetch() }} />
      : <Card className="admin-card">
        {users.data.items.length ? <div className="admin-table-wrap"><table>
          <thead><tr><th scope="col">Адрес</th><th scope="col">Роль</th><th scope="col">Статус</th><th scope="col">Регистрация</th></tr></thead>
          <tbody>{users.data.items.map((user) => <tr key={user.id}>
            <th scope="row"><button type="button" className="admin-text-button" onClick={() => select(user.id)}>{user.email}</button></th>
            <td>{roles[user.role]}</td>
            <td><Badge tone={user.suspended_at ? 'orange' : 'lime'}>{user.suspended_at ? 'Заблокирован' : 'Активен'}</Badge></td>
            <td>{stamp(user.created_at)}</td>
          </tr>)}</tbody>
        </table></div> : <EmptyState visual={<UsersRound aria-hidden="true" />} title="Пользователи не найдены"
          description="Проверьте адрес или сбросьте фильтры.">
          <Button variant="secondary" onClick={() => { setSearch(''); setQuery(''); setRole(''); setStatus(''); setOffset(0) }}>
            Сбросить фильтры
          </Button>
        </EmptyState>}
        <Pagination offset={offset} more={users.data.has_more} onChange={setOffset} />
      </Card>}
    <Modal open={Boolean(selected)} title="Карточка пользователя" onClose={() => select(undefined)}>
      {detail.isError ? <ResultError error={detail.error} retry={() => { void detail.refetch() }} />
        : detail.data ? <div className="admin-details">
          <dl>
            <dt>Электронная почта</dt><dd>{detail.data.email}</dd>
            <dt>Идентификатор</dt><dd><code>{detail.data.id}</code></dd>
            <dt>Дата регистрации</dt><dd>{stamp(detail.data.created_at)}</dd>
            <dt>Роль</dt><dd>{roles[detail.data.role]}</dd>
            <dt>Статус</dt><dd>{detail.data.suspended_at ? 'Заблокирован с ' + stamp(detail.data.suspended_at) : 'Активен'}</dd>
          </dl>
          <UserActions key={detail.data.id + detail.data.role + detail.data.suspended_at} user={detail.data} owner={owner} access={access} />
        </div> : <LoadingSkeleton label="Загружаем сведения об аккаунте" />}
    </Modal>
  </>
}

export function FeedbackInbox({ owner }: { owner: string }) {
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const results = useFeedback(owner, offset, status)
  const write = useAdminWrite(owner)
  return <>
    <div className="admin-filters"><label>Статус обращения
      <select value={status} onChange={(event) => { setOffset(0); setStatus(event.target.value) }}>
        <option value="">Все статусы</option>
        {feedbackStatus.options.map((item) => <option key={item} value={item}>{feedbackLabels[item]}</option>)}
      </select></label></div>
    {results.isPending ? <LoadingSkeleton label="Загружаем обращения" />
      : results.isError ? <ResultError error={results.error} retry={() => { void results.refetch() }} />
      : <>
        {!results.data.items.length && <EmptyState visual={<MessageSquare aria-hidden="true" />} title="Обращений нет"
          description={status ? 'В выбранном статусе пока нет обращений.' : 'Новые сообщения пользователей появятся здесь.'}>
          {status && <Button variant="secondary" onClick={() => { setStatus(''); setOffset(0) }}>Показать все статусы</Button>}
        </EmptyState>}
        {results.data.items.map((item) => <Card key={item.id} className="admin-card">
          <div className="admin-between"><h2>{item.subject}</h2><Badge>{feedbackLabels[item.status]}</Badge></div>
          <div className="admin-filters muted">{stamp(item.created_at)} · Автор <RecordId value={item.user_id} /></div>
          <p className="admin-preserve">{item.message}</p>
          <label className="admin-field">Изменить статус
            <select value={item.status} disabled={write.isPending} onChange={(event) => write.mutate({
              kind: 'feedback', id: item.id, value: feedbackStatus.parse(event.target.value),
            })}>{feedbackStatus.options.map((value) => <option key={value} value={value}>{feedbackLabels[value]}</option>)}</select>
          </label>
          {write.isError && write.variables?.kind === 'feedback' && write.variables.id === item.id
            && <p role="alert" className="admin-error">{adminMessage(write.error)}</p>}
        </Card>)}
        <Pagination offset={offset} more={results.data.has_more} onChange={setOffset} />
      </>}
  </>
}

const auditLabels: Record<string, string> = {
  before: 'Было', after: 'Стало', token_price_before: 'Прежняя ставка', token_price_after: 'Новая ставка',
  feedback_enabled_before: 'Прежний приём обращений', feedback_enabled_after: 'Новый приём обращений',
}

function auditValue(value: string | boolean | number | null) {
  if (typeof value === 'boolean') return value ? 'Включён' : 'Выключен'
  const parsedRole = role.safeParse(value)
  if (parsedRole.success) return roles[parsedRole.data]
  const parsedFeedback = feedbackStatus.safeParse(value)
  if (parsedFeedback.success) return feedbackLabels[parsedFeedback.data]
  return value == null ? '—' : typeof value === 'number' ? number.format(value) : value
}

function RecordId({ value }: { value: string }) {
  return <details className="admin-id">
    <summary aria-label={'Показать полный идентификатор ' + value}><code>{value.slice(0, 8)}…</code></summary>
    <code>{value}</code>
  </details>
}

export function AuditLog({ owner }: { owner: string }) {
  const [kind, setKind] = useState('')
  const [actorDraft, setActorDraft] = useState('')
  const [actor, setActor] = useState('')
  const [offset, setOffset] = useState(0)
  const query = useAudit(owner, offset, kind, actor)
  const valid = !actorDraft.trim() || z.uuid().safeParse(actorDraft.trim()).success
  return <>
    <form className="admin-filters" onSubmit={(event) => {
      event.preventDefault()
      if (valid) { setActor(actorDraft.trim()); setOffset(0) }
    }}>
      <label>Действие<select value={kind} onChange={(event) => { setKind(event.target.value); setOffset(0) }}>
        <option value="">Все действия</option>{action.options.map((item) => <option key={item} value={item}>{actions[item]}</option>)}
      </select></label>
      <label>Идентификатор администратора<Input value={actorDraft} maxLength={36} onChange={(event) => setActorDraft(event.target.value)}
        aria-invalid={!valid} /></label><Button type="submit" disabled={!valid}>Найти</Button>
    </form>
    {!valid && <p className="muted">Введите идентификатор в формате UUID.</p>}
    {query.isPending ? <LoadingSkeleton label="Загружаем журнал" />
      : query.isError ? <ResultError error={query.error} retry={() => { void query.refetch() }} />
      : <Card className="admin-card">
        {query.data.items.length ? <div className="admin-table-wrap admin-audit-table" role="region"
          aria-label="Записи журнала действий" tabIndex={0}><table>
          <thead><tr><th scope="col">Время</th><th scope="col">Действие</th><th scope="col">Кто</th>
            <th scope="col">Объект</th><th scope="col">Изменения</th></tr></thead>
          <tbody>{query.data.items.map((entry) => <tr key={entry.id}>
            <td>{stamp(entry.created_at)}</td><th scope="row">{actions[entry.action]}</th>
            <td>{entry.actor_id ? <RecordId value={entry.actor_id} /> : 'Консоль сервера'}</td>
            <td>{entry.target_id ? <RecordId value={entry.target_id} /> : '—'}</td>
            <td>{Object.entries(entry.changes).map(([field, value]) =>
              <div key={field}>{auditLabels[field] ?? field} · {auditValue(value)}</div>)}</td>
          </tr>)}</tbody>
        </table></div> : <EmptyState visual={<ClipboardList aria-hidden="true" />} title="Записей нет"
          description={kind || actor ? 'Измените фильтры, чтобы увидеть другие записи.' : 'Действия администраторов появятся здесь.'}>
          {(kind || actor) && <Button variant="secondary" onClick={() => { setKind(''); setActor(''); setActorDraft(''); setOffset(0) }}>
            Сбросить фильтры
          </Button>}
        </EmptyState>}
        <Pagination offset={offset} more={query.data.has_more} onChange={setOffset} />
      </Card>}
  </>
}

function SettingsEditor({ initial, owner, canEdit }: { initial: RuntimeSettings; owner: string; canEdit: boolean }) {
  const [feedback, setFeedback] = useState(initial.feedback_enabled)
  const [price, setPrice] = useState(initial.token_price?.toLocaleString(locale, { useGrouping: false, maximumSignificantDigits: 21 }) ?? '')
  const write = useAdminWrite(owner)
  const rawPrice = price.trim()
  const parsedPrice = rawPrice === '' ? null : Number(rawPrice.replace(',', '.'))
  const validPrice = parsedPrice === null || (/^(?:\d+(?:[.,]\d+)?|[.,]\d+)$/.test(rawPrice)
    && Number.isFinite(parsedPrice) && parsedPrice <= 1000)
  return <Card className="admin-card">
    <form className="admin-details" onSubmit={(event) => {
      event.preventDefault()
      if (canEdit && validPrice && !write.isPending) {
        write.mutate({ kind: 'settings', value: { feedback_enabled: feedback, token_price: parsedPrice } })
      }
    }}>
      <label><input type="checkbox" checked={feedback} disabled={!canEdit || write.isPending}
        onChange={(event) => setFeedback(event.target.checked)} /> Принимать обращения</label>
      <div className="admin-field admin-price">
        <label htmlFor="admin-token-price">Расчётная ставка ИИ</label>
        <div className="admin-price-control">
          <Input id="admin-token-price" inputMode="decimal" placeholder="0,25" value={price} disabled={!canEdit || write.isPending}
            aria-invalid={!validPrice} aria-describedby={'admin-price-help' + (validPrice ? '' : ' admin-price-error')}
            onChange={(event) => { setPrice(event.target.value); if (write.isError) write.reset() }} />
          <span className="muted">USD за 1 млн токенов</span>
        </div>
        <p id="admin-price-help" className="muted">Например, ставка 0,25 даст оценку 0,125 USD за 500 000 токенов.
          Пустое поле скрывает оценку, ставка 0 показывает нулевую стоимость.</p>
        {!validPrice && <p id="admin-price-error" role="alert" className="admin-error">Введите число от 0 до 1 000. Можно использовать запятую или точку.</p>}
      </div>
      <p className="muted">Ставка применяется к отчётным токенам выбранного периода. Биллинг провайдера управляется отдельно.</p>
      {write.isError && <p role="alert" className="admin-error">{adminMessage(write.error)}</p>}
      {canEdit ? <Button type="submit" disabled={write.isPending || !validPrice}>{write.isPending ? 'Сохраняем…' : 'Сохранить'}</Button>
        : <p className="muted">Редактирование доступно суперадминистратору.</p>}
    </form>
  </Card>
}

export function AdminSettings({ owner, access }: { owner: string; access: AdminRole }) {
  const query = useSettings(owner)
  if (query.isPending) return <LoadingSkeleton label="Загружаем настройки" />
  if (query.isError) return <ResultError error={query.error} retry={() => { void query.refetch() }} />
  return <SettingsEditor key={JSON.stringify(query.data)} initial={query.data} owner={owner} canEdit={access === 'super_admin'} />
}
