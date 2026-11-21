import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Tooltip, XAxis, YAxis } from 'recharts'
import { Badge, Button, Card, ErrorState, Input, LoadingSkeleton } from '../../components/ui/Primitives'
import { ChartFrame } from '../../components/ui/ChartFrame'
import { locale, number, percent } from '../../i18n'
import { dateShift } from '../dashboard/data'
import { dateLabel } from '../planner/calendar'
import { adminMessage, useOverview } from './data'
import type { Overview } from './data'

const usd = new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD', maximumFractionDigits: 6 })

function Metrics({ values }: { values: [string, string | number][] }) {
  return <dl className="admin-metrics">{values.map(([label, value]) =>
    <Card key={label}><dt>{label}</dt><dd>{typeof value === 'number' ? number.format(value) : value}</dd></Card>,
  )}</dl>
}

function Trends({ data, ai }: { data: Overview; ai: boolean }) {
  const series = ai ? [['ai_requests', 'Запросы ИИ', '#b9ff66']]
    : [['active_users', 'Активные пользователи', '#b9ff66'], ['registrations', 'Регистрации', '#ff9f2e'],
      ['completed_tasks', 'Выполненные задачи', '#a8b3d2']]
  return <Card className="admin-card">
    <h2>{ai ? 'Запросы по дням' : 'Динамика по дням'}</h2>
    <ChartFrame label={ai ? 'Запросы ИИ по дням' : 'Активность, регистрации и задачи по дням'} height={280}>
      <BarChart data={data.days} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="#434343" />
        <XAxis dataKey="date" tickFormatter={(day: string) => dateLabel(day, { day: 'numeric', month: 'short' })}
          tick={{ fill: '#ccc', fontSize: 11 }} minTickGap={20} />
        <YAxis allowDecimals={false} width={34} tick={{ fill: '#ccc', fontSize: 11 }} />
        <Tooltip labelFormatter={(day) => dateLabel(String(day), { dateStyle: 'medium' })}
          contentStyle={{ backgroundColor: '#202020', borderColor: '#666' }} />
        <Legend />
        {series.map(([key, label, fill]) => <Bar key={key} dataKey={key ?? ''} name={label} fill={fill} radius={[3, 3, 0, 0]} />)}
      </BarChart>
    </ChartFrame>
    <details><summary>Данные диаграммы</summary>
      <div className="admin-table-wrap"><table>
        <thead><tr><th scope="col">Дата</th>{series.map(([key, label]) => <th key={key} scope="col">{label}</th>)}</tr></thead>
        <tbody>{data.days.map(({ date, ...row }) => <tr key={date}><th scope="row">{dateLabel(date, { dateStyle: 'medium' })}</th>
          {series.map(([key]) => <td key={key}>{number.format(row[key as keyof typeof row])}</td>)}</tr>)}</tbody>
      </table></div>
    </details>
  </Card>
}

type Period = { from: string; to: string }

export function OverviewPanel({ owner, section, period, onPeriod }: {
  owner: string; section: 'overview' | 'analytics' | 'ai'; period: Period; onPeriod: (period: Period) => void
}) {
  const today = new Date().toISOString().slice(0, 10)
  const [draftFrom, setDraftFrom] = useState(period.from)
  const [draftTo, setDraftTo] = useState(period.to)
  const valid = Boolean(draftFrom && draftTo && draftFrom >= '2000-01-01'
    && draftFrom <= draftTo && draftTo <= today && draftFrom >= dateShift(draftTo, -89))
  const report = useOverview(owner, period.from, period.to)
  const ai = section === 'ai'
  return <>
    <form className="admin-filters" onSubmit={(event) => {
      event.preventDefault()
      if (valid) onPeriod({ from: draftFrom, to: draftTo })
    }}>
      <label>С <Input type="date" required min="2000-01-01"
        max={draftTo || today} value={draftFrom} onChange={(event) => setDraftFrom(event.target.value)} /></label>
      <label>По <Input type="date" required min={draftFrom} max={today} value={draftTo}
        onChange={(event) => setDraftTo(event.target.value)} /></label>
      <Button type="submit" disabled={!valid}>Применить</Button><span className="muted">До 90 дней · UTC</span>
    </form>
    {!valid && <p role="status" className="admin-error">Выберите период до 90 дней с окончанием не позже сегодня.</p>}
    {report.isPending ? <LoadingSkeleton label="Загружаем показатели" />
      : report.isError ? <ErrorState description={adminMessage(report.error)} onRetry={() => { void report.refetch() }} />
      : <>
        <p className="muted">Период отчёта: {dateLabel(report.data.from_date, { dateStyle: 'medium' })} — {
          dateLabel(report.data.to_date, { dateStyle: 'medium' })} · UTC</p>
        {ai ? <>
          <Metrics values={[
            ['Запросы ИИ', report.data.ai.requests], ['Попытки провайдера', report.data.ai.provider_calls],
            ['Токены по отчёту', report.data.ai.reported_tokens], ['Учтённый бюджет токенов', report.data.ai.budgeted_tokens],
            ['Оценка расходов', report.data.ai.estimated_cost_usd == null ? 'Нет оценки' : usd.format(report.data.ai.estimated_cost_usd)],
            ['Доля ошибок провайдера', report.data.ai.provider_error_rate == null ? 'Нет наблюдений' : percent.format(report.data.ai.provider_error_rate)],
            ['Отказы по лимиту частоты', report.data.ai.rate_rejections], ['Отказы по дневной квоте', report.data.ai.quota_rejections],
          ]} />
          <Card className="admin-card">
            <h2>Провайдер</h2>
            <p>{report.data.ai.provider ? [report.data.ai.provider === 'gemini' ? 'Google Gemini' : 'Совместимый провайдер', report.data.ai.model]
              .filter(Boolean).join(' · ') : 'Внешний ИИ не настроен'}</p>
            <p className="muted">Измерено ответов провайдера: {number.format(report.data.ai.observed_provider_calls)}.
              Ошибки: {number.format(report.data.ai.provider_failures)}. Оценка расходов использует настроенную ставку и токены,
              которые провайдер указал в отчётах.</p>
          </Card>
        </> : <>
          <Metrics values={[
            ['Аккаунты на конец периода', report.data.total_users], ['Активные за последний день периода', report.data.daily_active_users],
            ['Активные за 30 дней до конца периода', report.data.monthly_active_users], ['Новые регистрации', report.data.new_registrations],
            ['Выполненные задачи', report.data.completed_tasks], ['Активные привычки на конец периода', report.data.active_habits],
            ['Средний балл дисциплины', report.data.average_discipline_score ?? 'Нет измерений'],
            ['Запросы ИИ', report.data.ai.requests],
            ['Оценка расходов ИИ', report.data.ai.estimated_cost_usd == null ? 'Нет оценки' : usd.format(report.data.ai.estimated_cost_usd)],
          ]} />
          <Card className="admin-card">
            <h2>Состояние системы</h2>
            <div className="admin-filters"><Badge tone="lime">API отвечает</Badge>
              <Badge tone={report.data.database_ready ? 'lime' : 'orange'}>
                {report.data.database_ready ? 'База данных готова' : 'Проверьте версию схемы'}</Badge></div>
            <p className="muted">Активность учитывает вход, выполнение задач и сеансов фокуса, отметки привычек и запросы ИИ.
              Средний балл рассчитан по {number.format(report.data.scored_user_days)} сохранённым дневным измерениям.</p>
          </Card>
        </>}
        <Trends data={report.data} ai={ai} />
      </>}
  </>
}
