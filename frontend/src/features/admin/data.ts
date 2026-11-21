import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { z } from 'zod'
import { useToast } from '../../components/ui/toast-context'
import { apiMessage } from '../../i18n'
import { apiRequest } from '../../lib/api/client'
import { ApiError } from '../../lib/api/errors'

const timestamp = z.iso.datetime({ offset: true })
const count = z.number().int().nonnegative()
const date = z.iso.date()
export const role = z.enum(['user', 'admin', 'super_admin'])
export const feedbackStatus = z.enum(['new', 'reviewing', 'closed'])
export const action = z.enum(['role_changed', 'account_suspended', 'account_reactivated',
  'feedback_status_changed', 'settings_updated', 'super_admin_bootstrapped'])
const access = z.object({ role: z.enum(['admin', 'super_admin']) })
const user = z.object({ id: z.uuid(), email: z.string(), created_at: timestamp,
  role, suspended_at: timestamp.nullable() })
const feedback = z.object({ id: z.uuid(), user_id: z.uuid(), created_at: timestamp,
  subject: z.string(), message: z.string(), status: feedbackStatus })
const audit = z.object({ id: z.uuid(), actor_id: z.uuid().nullable(), target_id: z.uuid().nullable(),
  created_at: timestamp, action, changes: z.record(z.string(), z.union([z.boolean(), z.number(), z.string(), z.null()])) })
const settings = z.object({ feedback_enabled: z.boolean(), token_price: z.number().nullable() })
const overview = z.object({
  from_date: date, to_date: date, total_users: count, daily_active_users: count, monthly_active_users: count,
  new_registrations: count, completed_tasks: count, active_habits: count, average_discipline_score: z.number().nullable(),
  scored_user_days: count, database_ready: z.boolean(),
  ai: z.object({
    requests: count, provider_calls: count, provider_failures: count, observed_provider_calls: count,
    provider_error_rate: z.number().nullable(), reported_tokens: count, budgeted_tokens: count,
    rate_rejections: count, quota_rejections: count, estimated_cost_usd: z.number().nullable(),
    provider: z.string().nullable(), model: z.string().nullable(),
  }),
  days: z.array(z.object({ date, registrations: count, active_users: count, completed_tasks: count, ai_requests: count })),
})
const paged = <T>(item: z.ZodType<T>) => z.object({
  items: z.array(item), offset: count, limit: count, has_more: z.boolean(),
})

export type Role = z.infer<typeof role>
export type AdminRole = z.infer<typeof access>['role']
export type AdminUser = z.infer<typeof user>
export type FeedbackStatus = z.infer<typeof feedbackStatus>
export type RuntimeSettings = z.infer<typeof settings>
export type Overview = z.infer<typeof overview>

export function adminMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 403 && error.code === 'feedback_closed') return 'Приём обратной связи временно закрыт.'
    if (error.status === 403) return 'Недостаточно прав для этого действия.'
  }
  return apiMessage(error, 'Не удалось выполнить запрос. Попробуйте ещё раз.')
}

export function useAdminAccess(owner: string) {
  return useQuery({
    queryKey: ['admin-access', owner], retry: false, staleTime: 0, refetchInterval: 60_000,
    queryFn: ({ signal }) => apiRequest('/admin/access', access, { signal }),
  })
}

const adminKey = (owner: string) => ['admin', owner]
function useResource<T>(owner: string, path: `/${string}`, schema: z.ZodType<T>) {
  return useQuery({
    queryKey: [...adminKey(owner), path], retry: false,
    queryFn: ({ signal }) => apiRequest(path, schema, { signal }),
  })
}
export const pageSize = 20
const params = (values: Record<string, string | number>) => new URLSearchParams(
  Object.entries(values).filter(([, value]) => value !== '').map(([key, value]) => [key, String(value)]),
)
export const useOverview = (owner: string, from: string, to: string) =>
  useResource(owner, `/admin/overview?${params({ from_date: from, to_date: to })}`, overview)
export const useUsers = (owner: string, offset: number, search: string, filterRole: string, status: string) =>
  useResource(owner, `/admin/users?${params({ limit: pageSize, offset, search, role: filterRole, status })}`, paged(user))
export const useFeedback = (owner: string, offset: number, status: string) =>
  useResource(owner, `/admin/feedback?${params({ limit: pageSize, offset, status })}`, paged(feedback))
export const useAudit = (owner: string, offset: number, filter: string, actor: string) =>
  useResource(owner, `/admin/audit?${params({ limit: pageSize, offset, action: filter, actor_id: actor })}`, paged(audit))
export const useSettings = (owner: string) => useResource(owner, '/admin/settings', settings)
export const readAdminUser = (id: string, signal?: AbortSignal) => apiRequest(`/admin/users/${id}`, user, { signal })

type Write = { kind: 'role'; id: string; value: Role }
  | { kind: 'status'; id: string; value: 'active' | 'suspended' }
  | { kind: 'feedback'; id: string; value: FeedbackStatus }
  | { kind: 'settings'; value: RuntimeSettings }

export function useAdminWrite(owner: string) {
  const cache = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: async (write: Write) => {
      switch (write.kind) {
        case 'role': await apiRequest(`/admin/users/${write.id}/role`, user, { method: 'PATCH', body: { role: write.value } }); break
        case 'status': await apiRequest(`/admin/users/${write.id}/status`, user, { method: 'PATCH', body: { status: write.value } }); break
        case 'feedback': await apiRequest(`/admin/feedback/${write.id}`, feedback, { method: 'PATCH', body: { status: write.value } }); break
        case 'settings': await apiRequest('/admin/settings', settings, { method: 'PUT', body: write.value }); break
      }
    },
    onSuccess: async (_data, write) => {
      toast(write.kind === 'role' ? 'Роль пользователя обновлена.'
        : write.kind === 'status' ? (write.value === 'suspended' ? 'Аккаунт заблокирован. Сеансы завершены.' : 'Доступ к аккаунту восстановлен.')
        : write.kind === 'feedback' ? 'Статус обращения обновлён.' : 'Настройки панели сохранены.')
      await cache.invalidateQueries({ queryKey: adminKey(owner) })
    },
    onError: (error) => toast(adminMessage(error), 'error'),
  })
}

export const sendFeedback = (subject: string, message: string) =>
  apiRequest('/feedback', feedback, { method: 'POST', body: { subject, message } })
