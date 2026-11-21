import { Activity, Bot, ChevronLeft, ClipboardList, LayoutDashboard, MessageSquare, Settings, UsersRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes } from 'react-router'
import { Badge, ErrorState, LoadingSkeleton, PageHeader } from '../../components/ui/Primitives'
import { ApiError } from '../../lib/api/errors'
import { useSession } from '../auth/session'
import { dateShift } from '../dashboard/data'
import { adminMessage, useAdminAccess } from './data'
import { AdminSettings, AuditLog, FeedbackInbox, Users } from './Management'
import { OverviewPanel } from './OverviewPanel'
import './admin.css'

const sections = [
  { path: '', name: 'Обзор', icon: LayoutDashboard },
  { path: 'users', name: 'Пользователи', icon: UsersRound },
  { path: 'analytics', name: 'Аналитика', icon: Activity },
  { path: 'ai', name: 'Управление ИИ', icon: Bot },
  { path: 'feedback', name: 'Обратная связь', icon: MessageSquare },
  { path: 'audit', name: 'Журнал действий', icon: ClipboardList },
  { path: 'settings', name: 'Настройки панели', icon: Settings },
]

function defaultAdminPeriod() {
  const today = new Date().toISOString().slice(0, 10)
  return { from: dateShift(today, -6), to: today }
}

function AdminWorkspace({ owner }: { owner: string }) {
  const access = useAdminAccess(owner)
  const [period, setPeriod] = useState(defaultAdminPeriod)
  if (access.isPending) return <LoadingSkeleton label="Проверяем права доступа" />
  if (access.isError) return <ErrorState
    title={access.error instanceof ApiError && access.error.status === 403 ? 'Доступ закрыт' : 'Не удалось проверить доступ'}
    description={adminMessage(access.error)}
    onRetry={() => { void access.refetch() }} />
  const role = access.data.role
  return <>
    <PageHeader title="Панель администратора" actions={<Badge tone="lime">{role === 'super_admin' ? 'Суперадминистратор' : 'Администратор'}</Badge>} />
    <div className="admin-layout">
        <nav className="admin-navigation" aria-label="Разделы панели администратора">
          {sections.map(({ path, name, icon: Icon }) => <NavLink key={path}
            to={path === '' ? '/admin' : '/admin/' + path} end>
            <Icon size={17} aria-hidden="true" /> {name}
          </NavLink>)}
        </nav>
      <div className="admin-content">
        <Routes>
          <Route index element={<OverviewPanel key="overview" owner={owner} section="overview" period={period} onPeriod={setPeriod} />} />
          <Route path="analytics" element={<OverviewPanel key="analytics" owner={owner} section="analytics" period={period} onPeriod={setPeriod} />} />
          <Route path="ai" element={<OverviewPanel key="ai" owner={owner} section="ai" period={period} onPeriod={setPeriod} />} />
          <Route path="users" element={<Users owner={owner} access={role} />} />
          <Route path="feedback" element={<FeedbackInbox owner={owner} />} />
          <Route path="audit" element={<AuditLog owner={owner} />} />
          <Route path="settings" element={<AdminSettings owner={owner} access={role} />} />
          <Route path="*" element={<ErrorState title="Раздел не найден" description="Выберите раздел в меню панели." />} />
        </Routes>
      </div>
    </div>
  </>
}

export function AdminPage() {
  const { data } = useSession()
  useEffect(() => { document.title = 'Панель администратора · Disciply AI' }, [])
  return <div className="page admin-page">
    <Link className="admin-return" to="/"><ChevronLeft size={16} aria-hidden="true" /> Рабочее пространство</Link>
    {data && <AdminWorkspace key={data.id} owner={data.id} />}
  </div>
}
