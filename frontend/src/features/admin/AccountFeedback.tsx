import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { Button, Card, Input } from '../../components/ui/Primitives'
import { useToast } from '../../components/ui/toast-context'
import { adminMessage, sendFeedback, useAdminAccess } from './data'
import './admin.css'

export function AccountFeedback({ owner }: { owner: string }) {
  const access = useAdminAccess(owner)
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const toast = useToast()
  const submit = useMutation({
    mutationFn: () => sendFeedback(subject.trim(), message.trim()),
    onSuccess: () => {
      setSubject('')
      setMessage('')
      toast('Обращение отправлено.')
    },
  })
  return <Card className="admin-card">
    <div className="admin-between"><h2>Обратная связь</h2>
      {access.data && !access.isError && <Link className="button button--secondary" to="/admin">Панель администратора</Link>}</div>
    <form className="admin-details" onSubmit={(event) => {
      event.preventDefault()
      if (!submit.isPending && subject.trim() && message.trim()) submit.mutate()
    }}>
      <label className="admin-field">Тема<Input required maxLength={160} value={subject}
        onChange={(event) => setSubject(event.target.value)} /></label>
      <label className="admin-field">Сообщение<textarea required maxLength={2500} rows={3} value={message}
        onChange={(event) => setMessage(event.target.value)} /></label>
      {submit.isError && <p role="alert">{adminMessage(submit.error)}</p>}
      <Button type="submit" disabled={submit.isPending || !subject.trim() || !message.trim()}>
        {submit.isPending ? 'Отправляем…' : 'Отправить обращение'}
      </Button>
    </form>
  </Card>
}
