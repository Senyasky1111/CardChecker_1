---
type: module
status: placeholder
source: mobile/src/stores/authStore.ts
storage-key: cardchecker-auth
persisted: partial (isAuthenticated, user, token)
created: 2026-05-21
updated: 2026-05-21
area: [mobile, state, auth]
tags: [zustand, auth, mock]
related: [[_MOC]], [[../../../10-Projects/2026-Q2-mobile-auth-and-cloud]]
---

# authStore

> ⚠️ **Placeholder — mock-only**. Все методы возвращают hardcoded users после 1-1.5s delay.
> Real auth — задача [[../../../10-Projects/2026-Q2-mobile-auth-and-cloud]].

## State

```typescript
{
  isAuthenticated: boolean,
  user: UserProfile | null,         // { id, email, displayName, avatarUrl, createdAt }
  token: string | null,
  isLoading: boolean
}
```

## Actions (все mock)

- `login(email, password)` — mock API, sets user & token
- `loginWithSSO(provider: 'google' | 'apple')` — mock SSO
- `register(email, password, displayName)` — mock registration
- `logout()` — clears auth state
- `setUser(user)`, `setToken(token)` — manual

## Persistence

- Key: `cardchecker-auth`
- `partialize: (state) => ({ isAuthenticated, user, token })`
- Не персистится `isLoading`

## ⚠️ Что не работает

- **Passwords не валидируются** — любой пароль accepted
- **Token не verified** — просто random string
- **Token refresh** — нет логики
- **Backend integration** — нет
- **Cloud sync** — даже после "login" ничего не sync'ится

## Что нужно сделать (project)

См. [[../../../10-Projects/2026-Q2-mobile-auth-and-cloud]]:

1. Решить provider (Firebase / Supabase / своё через FastAPI)
2. JWT + refresh tokens
3. Password reset flow
4. User entity на backend
5. Subscription tier persisted serve-side
6. Cloud sync collection/watchlist/grading history

## Используется в

- `app/auth/login.tsx` — UI placeholder
- `app/(tabs)/profile.tsx` — display user info, logout button
- (Сейчас приложение работает в **anonymous mode** — auth не требуется для core features)

## Связанные

- All stores: [[_MOC]]
- Project: [[../../../10-Projects/2026-Q2-mobile-auth-and-cloud]]
- Webapp auth (тоже placeholder): [[../../08-webapp/known-issues]]
